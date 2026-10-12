package org.enigmagrid.core;

import java.util.List;

/** Experimental host-side random input for a resident portable GPU solver.
 * No production caller. Each cohort owns its canonical PCG stream; packing is
 * iteration-major, trajectory-major, then op/a/b/value/cooling allowance.
 */
public final class PortableRandomTape {
    public static final int FIELDS=5;
    private static final int MAX_INTS=16*1024*1024;
    private final PortablePcg64[] streams;
    private final int[][] initial;
    private final int iterations;
    private int nextIteration;

    public PortableRandomTape(List<PortableSearchJob.SeedState> states,int minPairs,int maxPairs,
                              int[] kinds,int iterations){
        if(states==null||states.isEmpty()||states.size()>128||iterations<1||iterations>512)
            throw new IllegalArgumentException("Invalid portable tape scope");
        this.iterations=iterations;
        streams=new PortablePcg64[states.size()];
        initial=new int[states.size()*PortableKeySampler.TRAJECTORIES][];
        for(int c=0;c<streams.length;c++){
            PortableSearchJob.SeedState state=states.get(c);
            streams[c]=new PortablePcg64(state.state,state.increment);
            int[][] keys=new PortableKeySampler(streams[c],minPairs,maxPairs,kinds).initial();
            System.arraycopy(keys,0,initial,c*PortableKeySampler.TRAJECTORIES,keys.length);
        }
    }
    public int trajectoryCount(){return initial.length;}
    public int nextIteration(){return nextIteration;}
    public int[][] initialKeys(){
        int[][] copy=new int[initial.length][];
        for(int i=0;i<copy.length;i++)copy[i]=initial[i].clone();
        return copy;
    }
    /** Advances this single-owner stream by exactly count iterations.
     * Chunk boundaries never restart cooling or discard cached PCG halves.
     * Invalid sizes fail before advancing any state.
     */
    public int[] next(int count){
        long size=(long)count*initial.length*FIELDS;
        if(count<1||count>iterations-nextIteration||size>MAX_INTS)
            throw new IllegalArgumentException("Invalid portable tape chunk");
        int[] tape=new int[(int)size];
        for(int step=0;step<count;step++){
            int temperature=Math.max(2500,38000*(iterations-nextIteration-step)/iterations);
            for(int c=0;c<streams.length;c++){
                PortablePcg64 random=streams[c];
                int base=(step*initial.length+c*PortableKeySampler.TRAJECTORIES)*FIELDS;
                // Draw whole arrays in canonical order BEFORE interleaving.
                for(int i=0;i<256;i++)tape[base+i*FIELDS]=random.bounded(100);
                for(int i=0;i<256;i++)tape[base+i*FIELDS+1]=random.bounded(26);
                for(int i=0;i<256;i++)tape[base+i*FIELDS+2]=random.bounded(26);
                for(int i=0;i<256;i++)tape[base+i*FIELDS+3]=random.bounded(1<<30);
                for(int i=0;i<256;i++)tape[base+i*FIELDS+4]=random.bounded(temperature+1);
            }
        }
        nextIteration+=count;
        return tape;
    }
}
