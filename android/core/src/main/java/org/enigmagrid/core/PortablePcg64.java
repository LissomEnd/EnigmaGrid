package org.enigmagrid.core;

import java.math.BigInteger;

/** NumPy PCG64 XSL RR 128/64 stream from *verified initial state and inc*.
 *
 * The coordinator may supply immutable state hints derived from start_seed.
 * This class deliberately does not implement NumPy SeedSequence; a future
 * worker MUST verify its hints against an independent server-side recomputation
 * before any public/paid result could be accepted. No work is enabled yet.
 */
public final class PortablePcg64 {
    private static final long MUL_HIGH=0x2360ed051fc65da4L;
    private static final long MUL_LOW=0x4385df649fccf645L;
    private static final long UINT32_MASK=0xffffffffL;
    private long stateHigh,stateLow;
    private final long incrementHigh,incrementLow;
    private boolean hasCached32;
    private long cached32;

    public PortablePcg64(String unsignedState,String unsignedIncrement) {
        BigInteger state=new BigInteger(unsignedState,10);
        BigInteger increment=new BigInteger(unsignedIncrement,10);
        if(state.signum()<0||state.bitLength()>128||increment.signum()<=0
                ||increment.bitLength()>128||!increment.testBit(0))
            throw new IllegalArgumentException("Invalid unsigned PCG64 state/inc");
        stateLow=state.longValue();stateHigh=state.shiftRight(64).longValue();
        incrementLow=increment.longValue();incrementHigh=increment.shiftRight(64).longValue();
    }

    public long nextUint64(){
        // 128-bit multiply/add modulo 2^128, using only baseline Java long
        // operations available on Android. No allocation in the draw hot path.
        long low=stateLow*MUL_LOW;
        long high=unsignedMultiplyHigh(stateLow,MUL_LOW)+stateHigh*MUL_LOW+stateLow*MUL_HIGH;
        long added=low+incrementLow;
        long carry=Long.compareUnsigned(added,low)<0?1L:0L;
        stateLow=added;stateHigh=high+incrementHigh+carry;
        return Long.rotateRight(stateHigh^stateLow,(int)(stateHigh>>>58));
    }
    private static long unsignedMultiplyHigh(long x,long y){
        long x0=x&UINT32_MASK,x1=x>>>32,y0=y&UINT32_MASK,y1=y>>>32;
        long first=x0*y0;
        long second=x1*y0+(first>>>32);
        long third=x0*y1+(second&UINT32_MASK);
        return x1*y1+(second>>>32)+(third>>>32);
    }
    public long nextUint32(){
        if(hasCached32){
            hasCached32=false;
            return cached32;
        }
        long raw=nextUint64();
        cached32=(raw>>>32)&UINT32_MASK;
        hasCached32=true;
        return raw&UINT32_MASK;
    }
    /** Same multiply-high with rejection used for NumPy <=32-bit integer ranges. */
    public int bounded(int exclusiveUpper){
        if(exclusiveUpper<=0||exclusiveUpper>(1<<30))
            throw new IllegalArgumentException("Range outside supported C3 draws");
        long upper=exclusiveUpper;
        long threshold=((1L<<32)-upper)%upper;
        while(true){
            long product=nextUint32()*upper;
            if((product&UINT32_MASK)>=threshold)return (int)(product>>>32);
        }
    }
    /** NumPy random_interval / Fisher-Yates for a fixed 26-letter permutation. */
    public int[] permutation26(){
        int[] out=new int[26];
        for(int i=0;i<26;i++)out[i]=i;
        for(int i=25;i>0;i--){
            long mask=(1L<<(32-Integer.numberOfLeadingZeros(i)))-1;
            int selected;
            do{selected=(int)(nextUint32()&mask);}while(selected>i);
            int hold=out[i];out[i]=out[selected];out[selected]=hold;
        }
        return out;
    }
}
