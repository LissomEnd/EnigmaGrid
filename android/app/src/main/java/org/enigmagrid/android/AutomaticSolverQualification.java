package org.enigmagrid.android;

import java.util.*;
import java.util.concurrent.*;
import java.util.function.*;
import org.enigmagrid.core.*;
import static org.enigmagrid.core.Canonical.object;

/** Small automatic, full-receipt pilot. Results are local fixtures, never credited. */
final class AutomaticSolverQualification {
    static String key(){return "auto-solver-pilot-v2-aggregate:"+SolverQualification.key();}
    static final class Report {
        final boolean solverFaster,mixedFaster;
        final String reason;
        Report(boolean solverFaster,boolean mixedFaster,String reason){
            this.solverFaster=solverFaster;this.mixedFaster=mixedFaster;this.reason=reason;
        }
    }
    private static Map<String,Object> fixture(int ordinal){
        String cipher="QWERTZUIOPASDFGHJKLYXCVBNM";
        char[] letters="ABCDEFGHIJKLMNOPQRSTUVWX".toCharArray();
        for(int i=0;i<letters.length;i++)if(letters[i]==cipher.charAt(i))letters[i]=(char)('A'+(letters[i]-'A'+1)%26);
        List<Long> cores=new ArrayList<>();
        for(int i=0;i<128;i++)cores.add((ordinal*128L+i)*7919L);
        return object("engine","bounded_crib_v1","start_unit",ordinal,"end_unit",ordinal+1,
            "config",object("requires",Arrays.asList("cpu","bounded_crib_v1"),
                "job",object("engine","bounded_crib_v1","ciphertext",cipher,"crib",new String(letters),"offset",0,
                    "core_indices",cores,"model","clean","pairs",10,
                    "budgets",object("node_limit",5000,"board_limit",64,"completion_limit",256,"candidate_limit",32))));
    }
    private static final class Timed {
        final String receipt;final long nanos;
        Timed(String receipt,long nanos){this.receipt=receipt;this.nanos=nanos;}
    }
    static Report run(GpuProcess gpu,Supplier<String> restriction)throws Exception {
        BooleanSupplier cancel=()->{
            if(Thread.currentThread().isInterrupted())return true;
            String blocked=restriction.get();
            if(blocked!=null)throw new QualificationProtection(blocked);
            return false;
        };
        int workers=Math.max(1,Math.min(8,Runtime.getRuntime().availableProcessors()/2));
        Map<String,Object>[] fixtures=new Map[]{fixture(0),fixture(1),fixture(2),fixture(3)};
        String[] expected=new String[fixtures.length];
        for(int i=0;i<fixtures.length;i++)expected[i]=Canonical.json(WorkEnvelope.run(fixtures[i],cancel,null,workers));
        ExecutorService lanes=Executors.newFixedThreadPool(2);
        long[] cpuPairs=new long[2],mixedPairs=new long[2],cpuJobs=new long[2],gpuJobs=new long[2];
        try{
            for(int round=0;round<3;round++){
                if(cancel.getAsBoolean())throw new CancellationException();
                final int first=round%2==0?0:2,second=first+1;
                long began=System.nanoTime();
                Future<Timed> cpuA=lanes.submit(()->timed(fixtures[first],cancel,null,workers));
                Future<Timed> cpuB=lanes.submit(()->timed(fixtures[second],cancel,null,workers));
                Timed a=cpuA.get(),b=cpuB.get();
                check(expected[first],a.receipt);check(expected[second],b.receipt);
                long cpuElapsed=System.nanoTime()-began;
                began=System.nanoTime();
                final int gpuIndex=round%2==0?first:second,cpuIndex=round%2==0?second:first;
                Future<Timed> gpuJob=lanes.submit(()->timed(fixtures[gpuIndex],cancel,
                    new BatchedSolver(new BatchedRows(gpu::rows,cancel),gpu::solve,cancel,true)
                        .withKeyDispatch(gpu::solveKeys).withGpuOnly().withBatchSize(64),workers));
                Future<Timed> cpuJob=lanes.submit(()->timed(fixtures[cpuIndex],cancel,null,workers));
                Timed g=gpuJob.get(),c=cpuJob.get();
                check(expected[gpuIndex],g.receipt);check(expected[cpuIndex],c.receipt);
                long mixedElapsed=System.nanoTime()-began;
                if(round>0){
                    int warm=round-1;
                    cpuPairs[warm]=cpuElapsed;mixedPairs[warm]=mixedElapsed;
                    cpuJobs[warm]=(gpuIndex==first?a.nanos:b.nanos);gpuJobs[warm]=g.nanos;
                }
            }
        }finally{
            lanes.shutdownNow();
            if(!lanes.awaitTermination(8,TimeUnit.SECONDS))throw new IllegalStateException("Automatic pilot did not stop");
        }
        return select(cpuPairs,mixedPairs,cpuJobs,gpuJobs);
    }
    /** A GPU lane is selected by completed cohort wall time, not its isolated job latency. */
    static Report select(long[] cpuPairs,long[] mixedPairs,long[] cpuJobs,long[] gpuJobs){
        if(cpuPairs.length!=2||mixedPairs.length!=2||cpuJobs.length!=2||gpuJobs.length!=2)
            throw new IllegalArgumentException("Two warm rounds required");
        long cpuTotal=0,mixedTotal=0,gpuJobTotal=0,cpuJobTotal=0;
        boolean mixedWins=true,gpuWins=true;
        for(int i=0;i<2;i++){
            if(cpuPairs[i]<=0||mixedPairs[i]<=0||cpuJobs[i]<=0||gpuJobs[i]<=0)
                throw new IllegalArgumentException("Positive qualification timings required");
            cpuTotal+=cpuPairs[i];mixedTotal+=mixedPairs[i];cpuJobTotal+=cpuJobs[i];gpuJobTotal+=gpuJobs[i];
            mixedWins&=mixedPairs[i]<cpuPairs[i];gpuWins&=gpuJobs[i]<cpuJobs[i];
        }
        boolean solverFaster=gpuWins&&gpuJobTotal<cpuJobTotal*.95;
        boolean mixedFaster=mixedWins&&mixedTotal<cpuTotal*.95;
        return new Report(solverFaster,mixedFaster,
            mixedFaster?"Independent CPU + GPU receipts faster in both warm rounds":
            solverFaster?"GPU solver faster alone; mixed throughput not qualified":
            "CPU solver faster or gain unstable; GPU rows retained");
    }
    private static Timed timed(Map<String,Object> fixture,BooleanSupplier cancel,BoundedCrib.RowProvider rows,int workers)throws Exception{
        long start=System.nanoTime();
        Map<String,Object> result=WorkEnvelope.run(fixture,cancel,rows,workers);
        return new Timed(Canonical.json(result),System.nanoTime()-start);
    }
    static void check(String expected,String actual){
        if(!expected.equals(actual))throw new IllegalStateException("Automatic GPU full receipt mismatch");
    }
}
