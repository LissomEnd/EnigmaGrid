package org.enigmagrid.android;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.*;
import org.enigmagrid.core.*;

/** Whole-job CPU/GPU overlap; local fixtures are never submitted to the coordinator. */
final class IndependentLaneQualification {
    static String key(){return "independent-lanes-v4-adaptive:"+SolverQualification.key();}
    static String legacyKey(){return "independent-lanes-v3-cohort:"+SolverQualification.key();}
    static final class Report {
        final boolean faster; final String text; final int batchSize,lanes;
        Report(boolean faster,String text,int batchSize,int lanes){this.faster=faster;this.text=text;this.batchSize=batchSize;this.lanes=lanes;}
    }
    private static void cool(android.content.Context context,Supplier<String> restriction)throws Exception {
        android.content.SharedPreferences settings=context.getSharedPreferences("worker-settings",0);
        long deadline=android.os.SystemClock.elapsedRealtime()+60000;
        while(true){
            if(Thread.currentThread().isInterrupted())throw new CancellationException();
            float[] t=DeviceTelemetry.temperatures(context);
            boolean headroom=(!Float.isFinite(t[0])||t[0]<=settings.getInt("max_cpu_temp_c",75)-15)
                &&(!Float.isFinite(t[1])||t[1]<=settings.getInt("max_gpu_temp_c",70)-10)
                &&(!Float.isFinite(t[2])||t[2]<=40);
            String reason=restriction.get();
            if(headroom&&reason==null)return;
            if(android.os.SystemClock.elapsedRealtime()>=deadline)throw new QualificationProtection("Waiting for benchmark thermal headroom");
            Thread.sleep(500);
        }
    }
    static Report run(android.content.Context context,GpuProcess gpu,Supplier<String> restriction)throws Exception {
        BooleanSupplier cancel=()->{if(Thread.currentThread().isInterrupted())return true;String reason=restriction.get();if(reason!=null)throw new QualificationProtection(reason);return false;};
        int workers=Math.max(1,Math.min(8,Runtime.getRuntime().availableProcessors()));
        String cipher="QWERTZUIOPASDFGHJKLYXCVBNM",crib="ABCDEFGHIJKLMNOPQRSTUVWX";
        char[] chars=crib.toCharArray();for(int i=0;i<chars.length;i++)if(chars[i]==cipher.charAt(i))chars[i]=(char)('A'+(chars[i]-'A'+1)%26);final String text=new String(chars);
        long[][] keys=new long[24][128];String[] expected=new String[24];
        cool(context,restriction);
        if(android.os.Build.VERSION.SDK_INT>=27)CohortQualification.run(gpu,cancel);
        for(int job=0;job<keys.length;job++){
            for(int core=0;core<128;core++)keys[job][core]=(job*128L+core)*7919L;
            expected[job]=Canonical.json(BoundedCrib.search(cipher,text,0,keys[job],10,5000,64,256,32,cancel,null,workers));
        }
        int modes=android.os.Build.VERSION.SDK_INT>=27?8:5;
        long[][] times=new long[4][8];StringBuilder detail=new StringBuilder();
        // Compare against all existing CPU concurrency choices, not just one slow baseline.
        for(int round=0;round<4;round++)for(int step=0;step<modes;step++){
            // Cooling is outside the timed interval; never bypass the runtime guard.
            cool(context,restriction);
            int mode=(round+step)%modes,lanes=mode>=6?4:mode>=3?2:1<<mode;
            AtomicInteger next=new AtomicInteger(),gpuJobs=new AtomicInteger();
            ExecutorService pool=Executors.newFixedThreadPool(lanes);List<Future<?>> futures=new ArrayList<>();
            long began=System.nanoTime();
            try{
                for(int lane=0;lane<lanes;lane++){
                    final boolean gpuLane=mode>=3&&lane==0;
                    futures.add(pool.submit(()->{
                        int cpuWorkers=CpuLaneBudget.forLane(Runtime.getRuntime().availableProcessors(),lanes,mode>=3,gpuLane);
                        BoundedCrib.RowProvider backend=gpuLane?new BatchedSolver(new BatchedRows(gpu::rows,cancel),gpu::solve,cancel,true).withKeyDispatch(gpu::solveKeys).withGpuOnly().withBatchSize(mode==4||mode==6?128:64):null;
                        for(int job;(job=next.getAndAdd(gpuLane&&(mode==5||mode==7)?4:1))<keys.length;){
                            if(cancel.getAsBoolean())throw new CancellationException();
                            if(gpuLane&&(mode==5||mode==7)){
                                final int first=job;List<Map<String,Object>> cohort=new ArrayList<>();
                                for(int index=first;index<Math.min(first+4,keys.length);index++){
                                    List<Long> coreList=new ArrayList<>();for(long key:keys[index])coreList.add(key);
                                    cohort.add(Canonical.object("engine","bounded_crib_v1","start_unit",index,"end_unit",index+1,"config",Canonical.object("requires",Arrays.asList("cpu","bounded_crib_v1"),"job",Canonical.object(
                                        "engine","bounded_crib_v1","ciphertext",cipher,"crib",text,"offset",0,"core_indices",coreList,"model","clean","pairs",10,
                                        "budgets",Canonical.object("node_limit",5000,"board_limit",64,"completion_limit",256,"candidate_limit",32)))));
                                }
                                try{GpuWorkCohort.run(cohort,gpu::solveKeys,cancel,cpuWorkers,(index,result,seconds)->{
                                    if(!expected[first+index].equals(Canonical.json(result.get("receipt"))))throw new IllegalStateException("Cohort receipt mismatch");gpuJobs.incrementAndGet();
                                });}catch(RuntimeException e){throw e;}catch(Exception e){throw new IllegalStateException(e);}
                                continue;
                            }
                            Map<String,Object> result=BoundedCrib.search(cipher,text,0,keys[job],10,5000,64,256,32,cancel,backend==null?null:backend.newSearch(),cpuWorkers);
                            if(!expected[job].equals(Canonical.json(result)))throw new IllegalStateException("Independent lane receipt mismatch");
                            if(gpuLane)gpuJobs.incrementAndGet();
                        }
                    }));
                }
                for(Future<?> future:futures)future.get();
                if(mode>=3&&gpuJobs.get()==0)throw new IllegalStateException("GPU lane received no work");
                times[round][mode]=System.nanoTime()-began;
                detail.append("\nRound ").append(round).append(" mode ").append(mode).append(": ").append(times[round][mode]/1000000).append(" ms, GPU jobs ").append(gpuJobs.get());
            }finally{for(Future<?> future:futures)future.cancel(true);pool.shutdownNow();if(!pool.awaitTermination(8,TimeUnit.SECONDS))throw new IllegalStateException("Lane qualification did not stop");}
        }
        long[] totals=new long[modes];for(int r=1;r<4;r++)for(int m=0;m<modes;m++)totals[m]+=times[r][m];
        int best=0;for(int m=1;m<3;m++)if(totals[m]<totals[best])best=m;
        int mixed=3;for(int m=4;m<modes;m++)if(totals[m]<totals[mixed])mixed=m;
        int wins=0;for(int r=1;r<4;r++)if(times[r][mixed]<times[r][best])wins++;
        boolean faster=wins>=2&&totals[mixed]<totals[best]*.95;
        return new Report(faster,"Independent CPU + GPU lanes: "+(faster?"throughput qualified":"no stable gain")+". Warm totals CPU 1/2/4 / mixed2 64/128/cohort512 / mixed4 128/cohort512: "+Arrays.toString(totals)+" ns."+detail,(mixed==5||mixed==7)?512:(mixed==4||mixed==6)?128:64,mixed>=6?4:2);
    }
}
