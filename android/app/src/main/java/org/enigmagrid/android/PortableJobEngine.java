package org.enigmagrid.android;

import android.content.Context;
import java.util.*;
import java.util.function.BooleanSupplier;
import java.util.concurrent.CancellationException;
import java.util.concurrent.Semaphore;
import java.util.concurrent.atomic.AtomicBoolean;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.json.JSONObject;
import org.enigmagrid.core.PortableSearchJob;
import org.enigmagrid.core.PortableEventScore;
import org.enigmagrid.core.PortableSelfTest;
import org.enigmagrid.core.PortableGpuSearch;
import static org.enigmagrid.core.Canonical.object;

/** Exact Android portable_event_v1 implementation with opt-in qualified GPU cohorts.
 *
 * Production calls require a canonical versioned asset checksum and NumPy
 * PCG64 stream states from the coordinator. All work is independently
 * replicated and canonicalized by the Python server; a failed qualification
 * must leave the bounded worker available.
 */
final class PortableJobEngine {
    private final int[] cipher,quadgrams;

    interface BackendFactory { PortableGpuSearch.Backend create() throws Exception; }
    private static final Semaphore GPU_SLOT=new Semaphore(1);
    private BackendFactory gpuFactory;
    private BooleanSupplier gpuEligible=()->false,gpuStop=()->true;
    // Qualification and measured split are scoped to the three distinct pair profiles.
    private final int[] qualification=new int[3]; // 0 untested, 1 exact/fast, 2 one warm trial, -1 failed, -2 slower
    private final double[] cpuPerWave=new double[3],gpuPerCohort=new double[3];
    private volatile String gpuState="disabled",gpuReason="not_configured";
    private volatile long gpuRetryAfterNanos;
    private volatile int lastCpuCohorts=16,lastGpuCohorts;
    private volatile double lastCpuSeconds,lastGpuSeconds;
    private static final int[] KINDS={1,2,3,4,5,6};

    /** Call once for a new worker/GPU session. Never implicitly retries failed qualification. */
    synchronized void configureGpu(BackendFactory factory,BooleanSupplier eligible100Percent,BooleanSupplier stopGpu){
        gpuFactory=Objects.requireNonNull(factory);gpuEligible=Objects.requireNonNull(eligible100Percent);
        gpuStop=Objects.requireNonNull(stopGpu);Arrays.fill(qualification,0);
        Arrays.fill(cpuPerWave,0);Arrays.fill(gpuPerCohort,0);gpuState="unqualified";gpuReason="first_unit_parity_required";gpuRetryAfterNanos=0;
    }
    Map<String,Object> diagnostics(){
        return object("state",gpuState,"reason",gpuReason,"retry_after_seconds",Math.max(0,(gpuRetryAfterNanos-System.nanoTime())/1e9),"cpu_cohorts",lastCpuCohorts,"gpu_cohorts",lastGpuCohorts,
                "cpu_seconds",lastCpuSeconds,"gpu_seconds",lastGpuSeconds);
    }
    private static final class GpuAttempt {
        final Thread thread;
        final AtomicBoolean abort=new AtomicBoolean();
        volatile List<PortableSearchJob.Hit> hits;
        volatile Throwable failure;
        volatile double seconds;
        GpuAttempt(String name,java.util.function.Consumer<GpuAttempt> action){
            thread=new Thread(()->action.accept(this),name);thread.setDaemon(true);
        }
        void join(boolean abortNow){
            if(abortNow){abort.set(true);thread.interrupt();}
            boolean interrupted=Thread.interrupted();
            if(interrupted){abort.set(true);thread.interrupt();}
            while(thread.isAlive()){
                try{thread.join();}catch(InterruptedException stop){interrupted=true;abort.set(true);thread.interrupt();}
            }
            if(interrupted)Thread.currentThread().interrupt();
        }
    }
    private GpuAttempt startGpu(Plan job,int first,int cohorts,BooleanSupplier cancel){
        if(!GPU_SLOT.tryAcquire())return null;
        GpuAttempt attempt=new GpuAttempt("portable-resident-gpu",task->{
            long started=System.nanoTime();
            try{
                BooleanSupplier stop=()->task.abort.get()||cancel.getAsBoolean()||!gpuEligible.getAsBoolean()||gpuStop.getAsBoolean();
                checkCancelled(stop);
                task.hits=PortableGpuSearch.run(cipher,quadgrams,job.seed+first*256L,cohorts*256,
                        job.topk,job.minPairs,job.maxPairs,KINDS,
                        new ArrayList<>(job.states.subList(first,first+cohorts)),stop,gpuFactory.create());
            }catch(Throwable failure){task.failure=failure;}
            finally{task.seconds=Math.max(.000001,(System.nanoTime()-started)/1e9);GPU_SLOT.release();}
        });
        try{attempt.thread.start();return attempt;}
        catch(RuntimeException|Error failure){GPU_SLOT.release();throw failure;}
    }
    private static void checkCancelled(BooleanSupplier cancel){
        if(Thread.currentThread().isInterrupted()||cancel.getAsBoolean())throw new CancellationException("Portable search cancelled");
    }
    private List<PortableSearchJob.Hit> cpu(Plan job,int first,int cohorts,BooleanSupplier cancel){
        return PortableSearchJob.run(cipher,quadgrams,job.seed+first*256L,cohorts*256,512,job.topk,
                job.minPairs,job.maxPairs,KINDS,new ArrayList<>(job.states.subList(first,first+cohorts)),cancel,
                Math.max(1,Math.min(cohorts,Math.min(16,Runtime.getRuntime().availableProcessors()))));
    }
    private static boolean exact(List<PortableSearchJob.Hit> a,List<PortableSearchJob.Hit> b){
        if(a==null||b==null||a.size()!=b.size())return false;
        for(int i=0;i<a.size();i++)if(a.get(i).attempt!=b.get(i).attempt||a.get(i).cost!=b.get(i).cost
                ||!Arrays.equals(a.get(i).key,b.get(i).key))return false;
        return true;
    }
    private static int cpuWaves(int cohorts){
        int capacity=Math.max(1,Math.min(16,Runtime.getRuntime().availableProcessors()));
        return (cohorts+capacity-1)/capacity;
    }
    private static int warmGpuCohorts(){
        int capacity=Math.max(1,Math.min(16,Runtime.getRuntime().availableProcessors()));
        // Leave at least one CPU cohort; remove one whole CPU scheduling wave.
        return 16-Math.max(1,(cpuWaves(16)-1)*capacity);
    }
    private int balancedGpuCohorts(int profile){
        int best=1;double time=Double.POSITIVE_INFINITY;
        for(int gpu=1;gpu<16;gpu++){
            double predicted=Math.max(cpuPerWave[profile]*cpuWaves(16-gpu),gpuPerCohort[profile]*gpu);
            if(predicted<time){best=gpu;time=predicted;}
        }
        return best;
    }
    private List<PortableSearchJob.Hit> compute(Plan job,BooleanSupplier cancel){
        int profile=job.minPairs==0?0:job.minPairs==4?1:2;
        lastCpuCohorts=16;lastGpuCohorts=0;lastCpuSeconds=0;lastGpuSeconds=0;
        if(gpuRetryAfterNanos>System.nanoTime()){
            gpuState="deferred";gpuReason="resident_session_cleanup";return cpu(job,0,16,cancel);
        }
        if(gpuFactory==null||!gpuEligible.getAsBoolean()||qualification[profile]<0){
            gpuState=gpuFactory==null?"disabled":qualification[profile]==-1?"failed":qualification[profile]==-2?"slower":"cpu_settings";
            if(qualification[profile]>=0)gpuReason=gpuFactory==null?"not_configured":"settings_memory_or_other_gpu_work";
            return cpu(job,0,16,cancel);
        }
        boolean qualifying=qualification[profile]==0;
        boolean warmTrial=qualification[profile]==2;
        int gpuCohorts=qualifying?16:warmTrial?warmGpuCohorts():balancedGpuCohorts(profile);
        int cpuCohorts=qualifying?16:16-gpuCohorts;
        GpuAttempt gpu=startGpu(job,qualifying?0:cpuCohorts,gpuCohorts,cancel);
        if(gpu==null){gpuState="gpu_busy";gpuReason="resident_slot_busy";return cpu(job,0,16,cancel);}
        gpuState=qualifying?"qualifying":warmTrial?"warm_trial":"hybrid";gpuReason=qualifying?"independent_full_unit_comparison":warmTrial?"single_warm_trial_after_cold_start":"measured_cohort_split";lastCpuCohorts=cpuCohorts;lastGpuCohorts=gpuCohorts;
        boolean completed=false;long wallStarted=System.nanoTime();
        try{
            long cpuStarted=System.nanoTime();
            List<PortableSearchJob.Hit> hits=cpu(job,0,cpuCohorts,cancel);
            lastCpuSeconds=Math.max(.000001,(System.nanoTime()-cpuStarted)/1e9);
            gpu.join(false);lastGpuSeconds=gpu.seconds;
            checkCancelled(cancel);
            if(gpu.failure instanceof Error&&!(gpu.failure instanceof LinkageError))throw (Error)gpu.failure;
            if(gpu.failure!=null){
                // GPU-only settings/thermal stop falls back; a user/global stop was checked above.
                if(gpu.failure instanceof CancellationException||!gpuEligible.getAsBoolean()||gpuStop.getAsBoolean()){
                    gpuState="deferred";gpuReason="gpu_control_changed";
                    gpuRetryAfterNanos=System.nanoTime()+35000000000L;
                }else{Arrays.fill(qualification,-1);gpuState="failed";gpuReason=gpu.failure.getClass().getSimpleName();}
                if(!qualifying)hits.addAll(cpu(job,cpuCohorts,gpuCohorts,cancel));
            }else if(qualifying){
                if(!exact(hits,gpu.hits)){Arrays.fill(qualification,-1);gpuState="parity_failed";gpuReason="exact_keys_costs_attempts_differ";}
                else{
                    cpuPerWave[profile]=lastCpuSeconds/cpuWaves(16);gpuPerCohort[profile]=gpu.seconds/16;
                    qualification[profile]=gpu.seconds>lastCpuSeconds?2:1;
                    gpuState=qualification[profile]==2?"warm_trial_pending":"qualified";
                    gpuReason=qualification[profile]==2?"exact_cold_start_needs_one_warm_trial":"exact_and_faster_on_first_unit";
                }
                // First actual unit always returns the independent CPU result.
            }else{
                hits.addAll(gpu.hits);
                double wall=(System.nanoTime()-wallStarted)/1e9;
                double baseline=cpuPerWave[profile]*cpuWaves(16);
                if(wall>baseline*(warmTrial?1.0:1.05)){
                    qualification[profile]=-2;gpuState="slower";gpuReason=warmTrial?"warm_trial_no_wall_gain":"measured_gpu_not_faster";
                }else if(warmTrial){qualification[profile]=1;gpuState="qualified";gpuReason="warm_trial_wall_gain";}
                cpuPerWave[profile]=.75*cpuPerWave[profile]+.25*lastCpuSeconds/cpuWaves(cpuCohorts);
                gpuPerCohort[profile]=warmTrial?gpu.seconds/gpuCohorts:.75*gpuPerCohort[profile]+.25*gpu.seconds/gpuCohorts;
            }
            hits.sort((a,b)->{int order=Integer.compare(a.cost,b.cost);return order!=0?order:Long.compare(a.attempt,b.attempt);});
            completed=true;return new ArrayList<>(hits.subList(0,job.topk));
        }finally{gpu.join(!completed);}
    }

    PortableJobEngine(Context context) throws Exception {
        byte[] contents=read(context,"portable_c3_scope_v1.json");
        JSONObject scope=new JSONObject(new String(contents,StandardCharsets.UTF_8));
        if(!"portable_event_v1".equals(scope.getString("engine")))
            throw new IllegalArgumentException("Wrong search engine");
        String text=scope.getString("ciphertext");
        cipher=PortableEventScore.ciphertext(text);
        byte[] table=read(context,"portable_qint_v1.bin");
        if(table.length!=PortableEventScore.QUADGRAM_ITEMS*4)
            throw new IllegalArgumentException("Unexpected fixed table size");
        byte[] digest=MessageDigest.getInstance("SHA-256").digest(table);
        StringBuilder hex=new StringBuilder(64);
        for(byte b:digest)hex.append(Character.forDigit((b>>4)&15,16)).append(Character.forDigit(b&15,16));
        if(!hex.toString().equals(scope.getString("quadgram_sha256")))
            throw new IllegalStateException("Portable reference quadgrams integrity failure");
        quadgrams=new int[PortableEventScore.QUADGRAM_ITEMS];
        try(DataInputStream stream=new DataInputStream(new ByteArrayInputStream(table))){
            for(int i=0;i<quadgrams.length;i++)quadgrams[i]=stream.readInt();
        }
        PortableSelfTest.verify(cipher,quadgrams);
    }
    private static byte[] read(Context context,String name) throws Exception {
        try(InputStream in=context.getAssets().open(name)){
            ByteArrayOutputStream out=new ByteArrayOutputStream();
            byte[] bytes=new byte[16384];int n;
            while((n=in.read(bytes))!=-1){
                if(out.size()>2*1024*1024)throw new IllegalArgumentException("Oversized asset");
                out.write(bytes,0,n);
            }
            return out.toByteArray();
        }
    }
    private static Map<?,?> asMap(Object x) {
        if(!(x instanceof Map))throw new IllegalArgumentException("Expected object");
        return (Map<?,?>)x;
    }
    private static long range(Object x,long min,long max){
        if(!(x instanceof Integer)&&!(x instanceof Long))
            throw new IllegalArgumentException("Expected exact integral number");
        long value=((Number)x).longValue();
        if(value<min||value>max)throw new IllegalArgumentException("Number outside scope");
        return value;
    }
    static final class Plan {
        final long unit,seed;
        final int minPairs,maxPairs,topk;
        final List<PortableSearchJob.SeedState> states;
        Plan(long unit,long seed,int min,int max,int k,List<PortableSearchJob.SeedState> states){
            this.unit=unit;this.seed=seed;this.minPairs=min;this.maxPairs=max;topk=k;this.states=states;
        }
    }
    static Plan validate(Map<String,Object> lease) {
        if(!"portable_event_v1".equals(lease.get("engine")))
            throw new IllegalArgumentException("Unsupported portable engine");
        String segment=String.valueOf(lease.get("segment_id"));
        long expectedBase;int min,max;
        if("portable-low-v1".equals(segment)){expectedBase=71000000000L;min=0;max=3;}
        else if("portable-normal-v1".equals(segment)){expectedBase=72000000000L;min=4;max=10;}
        else if("portable-extended-v1".equals(segment)){expectedBase=73000000000L;min=11;max=13;}
        else throw new IllegalArgumentException("Unknown canonical C3 segment");
        long unit=range(lease.get("start_unit"),0,24999);
        if(range(lease.get("end_unit"),1,25000)!=unit+1)
            throw new IllegalArgumentException("One unit per Android lease");
        Map<?,?> cfg=asMap(lease.get("config"));
        if(range(cfg.get("base_attempt"),expectedBase,expectedBase)!=expectedBase
                ||range(cfg.get("count_per_unit"),4096,4096)!=4096
                ||range(cfg.get("iterations"),512,512)!=512
                ||range(cfg.get("topk"),8,8)!=8
                ||range(cfg.get("min_pairs"),min,min)!=min
                ||range(cfg.get("max_pairs"),max,max)!=max
                ||range(cfg.get("replicas_required"),2,2)!=2)
            throw new IllegalArgumentException("Unexpected C3 search parameters");
        if(!(cfg.get("requires") instanceof List) ||
                !Arrays.asList("cpu").equals(cfg.get("requires")))
            throw new IllegalArgumentException("Portable requires CPU");
        if(!(cfg.get("event_kinds") instanceof List)
                ||!Arrays.asList(1,2,3,4,5,6).equals(cfg.get("event_kinds")))
            throw new IllegalArgumentException("Unqualified event models");
        if(!(lease.get("portable_rng_states") instanceof List))
            throw new IllegalArgumentException("Missing PCG64 seed hints");
        List<?> raw=(List<?>)lease.get("portable_rng_states");
        if(raw.size()!=16)throw new IllegalArgumentException("Expected 16 deterministic 256-key cohorts");
        List<PortableSearchJob.SeedState> states=new ArrayList<>();
        for(int i=0;i<16;i++){
            Map<?,?> item=asMap(raw.get(i));
            if(range(item.get("offset"),i*256,i*256)!=i*256)
                throw new IllegalArgumentException("PCG64 hint offset mismatch");
            if(!(item.get("state") instanceof String)||!(item.get("inc") instanceof String))
                throw new IllegalArgumentException("PCG64 hints must be decimal strings");
            String state=(String)item.get("state"),inc=(String)item.get("inc");
            if(!state.matches("[0-9]{1,39}")||!inc.matches("[0-9]{1,39}"))
                throw new IllegalArgumentException("Invalid PCG64 decimal state");
            states.add(new PortableSearchJob.SeedState(state,inc));
        }
        return new Plan(unit,expectedBase+unit*4096L,min,max,8,states);
    }
    synchronized Map<String,Object> run(Map<String,Object> lease,BooleanSupplier cancel){
        Plan job=validate(lease);
        Object controlLock=new Object();
        BooleanSupplier guardedCancel=()->{synchronized(controlLock){return cancel.getAsBoolean();}};
        List<PortableSearchJob.Hit> hits=compute(job,guardedCancel);
        List<Object> compact=new ArrayList<>();
        for(PortableSearchJob.Hit h:hits){
            List<Integer> key=new ArrayList<>(h.key.length);
            for(int value:h.key)key.add(value);
            compact.add(object("unit",job.unit,"attempt",h.attempt,"cost",h.cost,"key",key));
        }
        if(compact.size()!=8)throw new IllegalStateException("Incomplete portable result");
        return object("summary",object("engine","portable_event_v1","units",1),
                "portable_key_rows",compact);
    }
}
