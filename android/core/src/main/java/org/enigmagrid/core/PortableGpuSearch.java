package org.enigmagrid.core;

import java.util.*;
import java.util.concurrent.CancellationException;
import java.util.function.BooleanSupplier;

/** Experimental resident portable solver runner; no production activation here. */
public final class PortableGpuSearch {
    public static final int STRIDE=86,CHUNK_ITERATIONS=16,ITERATIONS=512;
    public interface Backend {
        int begin(int[] reference,int[] state,int[] parameters) throws Exception;
        void step(int session,int[] tape,int iterations) throws Exception;
        int[] finish(int session) throws Exception;
        /** Idempotent after successful finish; must never close a different session. */
        void close(int session) throws Exception;
    }
    private PortableGpuSearch(){}
    public static List<PortableSearchJob.Hit> run(int[] cipher,int[] quadgrams,long startSeed,
            int count,int topk,int minPairs,int maxPairs,int[] kinds,
            List<PortableSearchJob.SeedState> states,BooleanSupplier stop,Backend backend) throws Exception {
        Objects.requireNonNull(stop);Objects.requireNonNull(backend);
        if(cipher==null||cipher.length!=72||quadgrams==null||quadgrams.length!=PortableEventScore.QUADGRAM_ITEMS
                ||count<256||count>4096||count%256!=0||states==null||states.size()!=count/256
                ||topk<1||topk>32||startSeed<0||startSeed>Long.MAX_VALUE-count)
            throw new IllegalArgumentException("Invalid portable GPU scope");
        for(int x:cipher)if(x<0||x>25)throw new IllegalArgumentException("Invalid ciphertext");
        // Keep integer score sums safely bounded, including shader division semantics.
        for(int q:quadgrams)if(q<2357||q>10924)throw new IllegalArgumentException("Unqualified quadgrams");
        check(stop);
        PortableRandomTape tape=new PortableRandomTape(states,minPairs,maxPairs,kinds,ITERATIONS);
        int[] reference=new int[72+625+quadgrams.length],wires=new int[625];
        EnigmaM4.copyRowTables(wires);
        System.arraycopy(cipher,0,reference,0,72);System.arraycopy(wires,0,reference,72,625);
        System.arraycopy(quadgrams,0,reference,697,quadgrams.length);
        int[][] keys=tape.initialKeys();int[] state=new int[count*STRIDE];
        for(int i=0;i<count;i++){
            System.arraycopy(keys[i],0,state,i*STRIDE,42);
            System.arraycopy(keys[i],0,state,i*STRIDE+42,42);
        }
        int[] parameters=new int[12];
        parameters[0]=count;parameters[1]=0;parameters[2]=1;
        parameters[3]=minPairs;parameters[4]=maxPairs;parameters[5]=kinds.length;
        System.arraycopy(kinds,0,parameters,6,kinds.length);
        check(stop);
        final int session=backend.begin(reference,state,parameters);
        // A backend failure or cancellation cannot leave a resident allocation behind.
        try(AutoCloseable cleanup=()->backend.close(session)){
            check(stop);
            for(int iter=0;iter<ITERATIONS;iter+=CHUNK_ITERATIONS){
                check(stop);
                int[] chunk=tape.next(CHUNK_ITERATIONS);
                check(stop);
                backend.step(session,chunk,CHUNK_ITERATIONS);
                check(stop);
            }
            int[] result=backend.finish(session);
            check(stop);
            if(result==null||result.length!=count*STRIDE)
                throw new IllegalStateException("Incomplete portable GPU state");
            List<PortableSearchJob.Hit> hits=new ArrayList<>();
            for(int i=0;i<count;i++){
                if((i&31)==0)check(stop);
                int base=i*STRIDE;
                int[] current=Arrays.copyOfRange(result,base,base+42);
                int[] best=Arrays.copyOfRange(result,base+42,base+84);
                validateKey(current,minPairs,maxPairs,kinds);validateKey(best,minPairs,maxPairs,kinds);
                int cost=result[base+84],bestCost=result[base+85];
                if(bestCost>cost||cost!=PortableEventScore.score(cipher,current,quadgrams)
                        ||bestCost!=PortableEventScore.score(cipher,best,quadgrams))
                    throw new IllegalStateException("Portable GPU score mismatch");
                hits.add(new PortableSearchJob.Hit(startSeed+i,bestCost,best));
            }
            hits.sort((a,b)->{int order=Integer.compare(a.cost,b.cost);return order!=0?order:Long.compare(a.attempt,b.attempt);});
            return new ArrayList<>(hits.subList(0,topk));
        }
    }
    private static void validateKey(int[] key,int min,int max,int[] kinds){
        if(key[0]<0||key[0]>=1344||key[1]!=0)throw new IllegalStateException("Invalid GPU rotor shell");
        for(int j=2;j<9;j++)if(key[j]<0||key[j]>25)throw new IllegalStateException("Invalid GPU rotor position");
        int plugged=0;
        for(int j=0;j<26;j++){
            int value=key[9+j];
            if(value<0||value>25||key[9+value]!=j)throw new IllegalStateException("Invalid GPU plugboard");
            if(value!=j)plugged++;
        }
        if(plugged/2<min||plugged/2>max)throw new IllegalStateException("Invalid GPU pair count");
        for(int j=35;j<39;j++)if(key[j]<0||key[j]>25)throw new IllegalStateException("Invalid GPU reset position");
        boolean allowed=false;for(int kind:kinds)allowed|=kind==key[39];
        if(!allowed||key[40]<4||key[40]>68||key[40]%4!=0||key[41]<1||key[41]>4)
            throw new IllegalStateException("Invalid GPU event");
    }
    private static void check(BooleanSupplier stop){
        if(Thread.currentThread().isInterrupted()||stop.getAsBoolean())throw new CancellationException("Portable GPU interrupted");
    }
}
