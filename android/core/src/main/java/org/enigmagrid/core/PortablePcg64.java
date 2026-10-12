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
    private static final BigInteger MOD128=BigInteger.ONE.shiftLeft(128).subtract(BigInteger.ONE);
    private static final BigInteger MOD64=BigInteger.ONE.shiftLeft(64).subtract(BigInteger.ONE);
    private static final BigInteger MUL=new BigInteger("2360ed051fc65da44385df649fccf645",16);
    private static final long UINT32_MASK=0xffffffffL;
    private BigInteger state;
    private final BigInteger increment;
    private boolean hasCached32;
    private long cached32;

    public PortablePcg64(String unsignedState,String unsignedIncrement) {
        this.state=new BigInteger(unsignedState,10);
        this.increment=new BigInteger(unsignedIncrement,10);
        if(state.signum()<0||state.bitLength()>128||increment.signum()<=0
                ||increment.bitLength()>128||!increment.testBit(0))
            throw new IllegalArgumentException("Invalid unsigned PCG64 state/inc");
    }

    public long nextUint64(){
        state=state.multiply(MUL).add(increment).and(MOD128);
        long xor=state.shiftRight(64).xor(state).and(MOD64).longValue();
        int rotation=state.shiftRight(122).intValue()&63;
        return Long.rotateRight(xor,rotation);
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
