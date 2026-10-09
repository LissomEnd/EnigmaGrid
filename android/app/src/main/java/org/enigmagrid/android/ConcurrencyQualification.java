package org.enigmagrid.android;

import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.*;
import org.enigmagrid.core.*;

/** Local, CPU-replayed fixtures; these are never submitted or counted as grid credits. */
final class ConcurrencyQualification {
    static String key(boolean solver){return SolverQualification.key()+(solver?":hybrid":":cpu-rows");}
    static final class Report {
        final int jobs; final String text;
        Report(int jobs,String text){this.jobs=jobs;this.text=text;}
    }
    static Report run(GpuProcess gpu,boolean solver,Supplier<String> restriction)throws Exception {
        AtomicBoolean closing=new AtomicBoolean();
        BooleanSupplier cancel=()->{
            if(closing.get()||Thread.currentThread().isInterrupted())return true;
            String reason=restriction.get();
            if(reason!=null)throw new QualificationProtection(reason);
            return false;
        };
        BoundedCrib.RowProvider backend=new BatchedRows(gpu::rows,cancel);
        if(solver)backend=new BatchedSolver(backend,gpu::solve,cancel,true).withKeyDispatch(gpu::solveKeys).withCpuShare();
        AdaptiveRows shared=new AdaptiveRows(backend,()->100,cancel,new WorkControl.SystemTiming());
        String cipher="QWERTZUIOPASDFGHJKLYXCVBNM";
        char[] letters="ABCDEFGHIJKLMNOPQRSTUVWX".toCharArray();
        for(int i=0;i<letters.length;i++)if(letters[i]==cipher.charAt(i))letters[i]=(char)('A'+(letters[i]-'A'+1)%26);
        String crib=new String(letters);
        int workers=Math.max(1,Math.min(8,Runtime.getRuntime().availableProcessors()));
        long[][] keys=new long[12][128];String[] references=new String[12];
        for(int job=0;job<12;job++){
            for(int core=0;core<128;core++)keys[job][core]=(job*128L+core)*7919L;
            references[job]=Canonical.json(BoundedCrib.search(cipher,crib,0,keys[job],10,5000,64,256,32,cancel,null,workers));
        }
        ExecutorService executor=Executors.newFixedThreadPool(4);
        List<Future<?>> active=new ArrayList<>();
        long[][] elapsed=new long[4][3];StringBuilder details=new StringBuilder();
        try {
            for(int round=0;round<4;round++)for(int step=0;step<3;step++){
                int index=(round+step)%3,limit=1<<index;
                CompletionService<Integer> completed=new ExecutorCompletionService<>(executor);
                long began=System.nanoTime();int next=0,finished=0,inFlight=0;
                while(finished<12){
                    if(cancel.getAsBoolean())throw new CancellationException();
                    while(next<12&&inFlight<limit){
                        final int job=next++;
                        active.add(completed.submit(()->{
                            Map<String,Object> result=BoundedCrib.search(cipher,crib,0,keys[job],10,5000,64,256,32,cancel,shared.newSearch(),workers);
                            if(!references[job].equals(Canonical.json(result)))throw new IllegalStateException("Concurrent receipt differs from CPU reference");
                            return job;
                        }));inFlight++;
                    }
                    Future<Integer> done=completed.poll(100,TimeUnit.MILLISECONDS);
                    if(done!=null){done.get();finished++;inFlight--;active.remove(done);}
                }
                elapsed[round][index]=System.nanoTime()-began;
                details.append("\nRound ").append(round).append(" / ").append(limit).append(" jobs: ").append(elapsed[round][index]/1_000_000).append(" ms for 12 CPU-replayed receipts");
            }
            if(shared.failed())throw new IllegalStateException("GPU fallback during concurrency qualification");
            long[] totals=new long[3];int[] wins=new int[3];
            for(int round=1;round<4;round++)for(int i=0;i<3;i++){
                totals[i]+=elapsed[round][i];if(elapsed[round][i]<elapsed[round][0])wins[i]++;
            }
            int selected=0;
            for(int i=1;i<3;i++)if(wins[i]>=2&&totals[i]<totals[0]*.95&&totals[i]<totals[selected])selected=i;
            return new Report(1<<selected,"\nLocal concurrency selection: "+(1<<selected)+" jobs. Warm totals 1/2/4: "+totals[0]/1_000_000+" / "+totals[1]/1_000_000+" / "+totals[2]/1_000_000+" ms. Local parity only; sustained grid verification throughput remains to be measured."+details);
        } finally {
            closing.set(true);for(Future<?> task:active)task.cancel(true);executor.shutdownNow();
            if(!executor.awaitTermination(8,TimeUnit.SECONDS))throw new IllegalStateException("Concurrent qualification did not stop");
        }
    }
}
