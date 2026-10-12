package org.enigmagrid.core;

import java.util.*;
import java.util.function.BooleanSupplier;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/** Deterministic portable_event_v1 trajectory runner, identical decisions to
 * NumPy/Numba. Its results stay in compact key form for canonical expansion by
 * the coordinator. Scientific activation requires full qualification first.
 */
public final class PortableSearchJob {
    public static final int TRAJECTORIES_PER_COHORT=256;
    public static final int CANONICAL_ITERATIONS=512;

    public static final class SeedState{
        public final String state,increment;
        public SeedState(String state,String increment){this.state=state;this.increment=increment;}
    }
    public static final class Hit{
        public final long attempt;
        public final int cost;
        public final int[] key;
        Hit(long attempt,int cost,int[] key){this.attempt=attempt;this.cost=cost;this.key=key.clone();}
    }
    private static final int MAX_WORKERS=Math.max(1,Math.min(32,Runtime.getRuntime().availableProcessors()));
    // One bounded process-wide pool, rather than a pool for every requested size.
    private static final ThreadPoolExecutor POOL=new ThreadPoolExecutor(
        MAX_WORKERS,MAX_WORKERS,30,TimeUnit.SECONDS,new ArrayBlockingQueue<Runnable>(128),r->{
            Thread t=new Thread(r,"portable-cohort");t.setDaemon(true);return t;
        },new ThreadPoolExecutor.AbortPolicy());
    static { POOL.allowCoreThreadTimeOut(true); }
    private PortableSearchJob(){}

    public static List<Hit> run(int[] cipher,int[] quadgrams,long startSeed,int count,
                     int iterations,int topk,int minPairs,int maxPairs,
                     int[] kinds,List<SeedState> seedStates,BooleanSupplier stop){
        return run(cipher,quadgrams,startSeed,count,iterations,topk,minPairs,maxPairs,kinds,seedStates,stop,1);
    }
    /** Independent cohorts retain their own PCG stream; worker count cannot alter receipts. */
    public static List<Hit> run(int[] cipher,int[] quadgrams,long startSeed,int count,
                     int iterations,int topk,int minPairs,int maxPairs,
                     int[] kinds,List<SeedState> seedStates,BooleanSupplier stop,int workers){
        if(workers<1||workers>32)throw new IllegalArgumentException("Invalid portable worker count");
        if(cipher.length!=72||quadgrams.length!=PortableEventScore.QUADGRAM_ITEMS
             ||count<TRAJECTORIES_PER_COHORT||count>32768
             ||count%TRAJECTORIES_PER_COHORT!=0||iterations<1||iterations>CANONICAL_ITERATIONS
             ||topk<1||topk>32||seedStates.size()!=count/TRAJECTORIES_PER_COHORT)
            throw new IllegalArgumentException("Invalid portable trajectory envelope");
        int cohorts=count/TRAJECTORIES_PER_COHORT;
        int lanes=Math.min(cohorts,Math.min(workers,MAX_WORKERS));
        List<Hit> candidates=new ArrayList<>();
        if(lanes==1){
            for(int off=0;off<count;off+=TRAJECTORIES_PER_COHORT)
                candidates.addAll(cohort(cipher,quadgrams,startSeed,off,iterations,topk,minPairs,maxPairs,kinds,seedStates,stop));
        }else{
            List<List<Hit>> results=new ArrayList<>(Collections.nCopies(cohorts,null));
            AtomicBoolean cancelled=new AtomicBoolean();
            AtomicReference<Throwable> firstFailure=new AtomicReference<>();
            Object guard=new Object();
            Object lifecycle=new Object();
            int[] active={0};
            BooleanSupplier guardedStop=()->{
                if(cancelled.get())return true;
                synchronized(guard){return cancelled.get()||stop.getAsBoolean();}
            };
            List<Future<?>> tasks=new ArrayList<>();
            try{
                for(int lane=0;lane<lanes;lane++){
                    final int first=lane;
                    tasks.add(POOL.submit(()->{
                        synchronized(lifecycle){
                            if(cancelled.get())return;
                            active[0]++;
                        }
                        try{
                        for(int index=first;index<cohorts;index+=lanes){
                            check(guardedStop);
                            List<Hit> hits=cohort(cipher,quadgrams,startSeed,index*TRAJECTORIES_PER_COHORT,
                                iterations,topk,minPairs,maxPairs,kinds,seedStates,guardedStop);
                            synchronized(results){results.set(index,hits);}
                        }
                        }catch(RuntimeException|Error failure){
                            firstFailure.compareAndSet(null,failure);
                            cancelled.set(true);
                            throw failure;
                        }finally{
                            synchronized(lifecycle){active[0]--;lifecycle.notifyAll();}
                        }
                    }));
                }
                for(Future<?> task:tasks)task.get();
                for(List<Hit> hits:results)candidates.addAll(hits);
            }catch(InterruptedException e){
                Thread.currentThread().interrupt();throw new CancellationException("Portable search interrupted");
            }catch(ExecutionException e){
                Throwable cause=firstFailure.get();
                if(cause==null)cause=e.getCause();
                if(cause instanceof RuntimeException)throw (RuntimeException)cause;
                if(cause instanceof Error)throw (Error)cause;
                throw new IllegalStateException("Portable cohort failed",cause);
            }finally{
                synchronized(lifecycle){cancelled.set(true);}
                for(Future<?> task:tasks)if(!task.isDone())task.cancel(true);
                // Future.cancel marks a future done before its code exits. Join the
                // running lanes before returning so retries cannot overlap old work.
                boolean interrupted=Thread.interrupted();
                synchronized(lifecycle){
                    while(active[0]!=0){
                        try{lifecycle.wait();}catch(InterruptedException e){interrupted=true;}
                    }
                }
                if(interrupted)Thread.currentThread().interrupt();
                POOL.purge();
            }
        }
        candidates.sort((a,b)->{
            int diff=Integer.compare(a.cost,b.cost);
            return diff!=0?diff:Long.compare(a.attempt,b.attempt);
        });
        if(candidates.size()>topk)return new ArrayList<>(candidates.subList(0,topk));
        return candidates;
    }
    private static List<Hit> cohort(int[] cipher,int[] quadgrams,long startSeed,int off,
            int iterations,int topk,int minPairs,int maxPairs,int[] kinds,
            List<SeedState> seedStates,BooleanSupplier stop){
        List<Hit> winners=new ArrayList<>();
        check(stop);
        SeedState seed=seedStates.get(off/TRAJECTORIES_PER_COHORT);
        PortableKeySampler sampler=new PortableKeySampler(
            new PortablePcg64(seed.state,seed.increment),minPairs,maxPairs,kinds);
        int[][] keys=sampler.initial();
        int[] costs=evaluate(cipher,quadgrams,keys);
        int[][] bestKeys=copy(keys);
        int[] bestCosts=costs.clone();
        for(int iter=0;iter<iterations;iter++){
            if((iter&7)==0)check(stop);
            int[][] proposedKeys=sampler.mutate(keys);
            int[] proposed=evaluate(cipher,quadgrams,proposedKeys);
            int temperature=Math.max(2500,38000*(iterations-iter)/iterations);
            int[] randomAllowance=new int[TRAJECTORIES_PER_COHORT];
            for(int i=0;i<randomAllowance.length;i++)
                randomAllowance[i]=sampler.coolingAllowance(temperature+1);
            for(int i=0;i<TRAJECTORIES_PER_COHORT;i++){
                if((long)proposed[i] <= (long)costs[i]+randomAllowance[i]){
                    keys[i]=proposedKeys[i];
                    costs[i]=proposed[i];
                }
                if(costs[i]<bestCosts[i]){
                    bestCosts[i]=costs[i];
                    bestKeys[i]=keys[i].clone();
                }
            }
        }
        // Python lexsort(costs,trajectory index) and union of cohort winners.
        Integer[] rank=new Integer[TRAJECTORIES_PER_COHORT];
        for(int i=0;i<rank.length;i++)rank[i]=i;
        Arrays.sort(rank,(a,b)->{
            int diff=Integer.compare(bestCosts[a],bestCosts[b]);
            return diff!=0?diff:Integer.compare(a,b);
        });
        for(int j=0;j<topk;j++){
            int pos=rank[j];
            winners.add(new Hit(startSeed+off+pos,bestCosts[pos],bestKeys[pos]));
        }
        return winners;
    }
    private static int[] evaluate(int[] cipher,int[] quadgrams,int[][] keys){
        int[] result=new int[keys.length];
        for(int i=0;i<keys.length;i++)
            result[i]=PortableEventScore.score(cipher,keys[i],quadgrams);
        return result;
    }
    private static int[][] copy(int[][] source){
        int[][] out=new int[source.length][];
        for(int i=0;i<source.length;i++)out[i]=source[i].clone();
        return out;
    }
    private static void check(BooleanSupplier stop){
        if(Thread.currentThread().isInterrupted()||stop.getAsBoolean())
            throw new CancellationException("Portable search interrupted");
    }
}
