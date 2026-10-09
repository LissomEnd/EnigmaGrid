package org.enigmagrid.android;

import java.util.*;
import java.util.concurrent.*;
import java.util.function.BooleanSupplier;
import org.enigmagrid.core.WorkEnvelope;
import static org.enigmagrid.core.Canonical.object;

/** One lease transaction. Completed results are durable before transmission. */
final class NetworkWorker {
    private final CoordinatorClient client,heartbeat,allocator;
    private java.util.function.Supplier<Map<String,Object>> settingsSource;
    void setSettingsSource(java.util.function.Supplier<Map<String,Object>> source){settingsSource=source;}
    interface TelemetrySession extends AutoCloseable {void start();void close();}
    interface TelemetryFactory {TelemetrySession create(String token,NetworkWorker worker,long serverTimeMs,long receivedNs);}
    private TelemetryFactory telemetryFactory;
    private TelemetrySession telemetryReporter;
    void setTelemetryFactory(TelemetryFactory factory){telemetryFactory=factory;}
    private synchronized void startTelemetryIfAvailable(Map<String,Object> capabilities,String token,long receivedNs){
        if(telemetryReporter!=null||telemetryFactory==null||!"device_telemetry_v1".equals(capabilities.get("device_telemetry")))return;
        Object serverClock=capabilities.get("server_time_ms");
        long serverTimeMs=serverClock instanceof Number?((Number)serverClock).longValue():System.currentTimeMillis();
        if(serverTimeMs<1_000_000_000_000L||serverTimeMs>4_000_000_000_000L)
            serverTimeMs=System.currentTimeMillis(); // Compatibility with an older coordinator.
        TelemetrySession session=null;
        try{session=telemetryFactory.create(token,this,serverTimeMs,receivedNs);session.start();telemetryReporter=session;}
        catch(RuntimeException unavailable){if(session!=null)session.close();}
    }
    private volatile int parallelJobs=1;
    private volatile CpuOnlyProductionProfile cpuProfile;
    private volatile java.util.function.Supplier<String> cpuProfileGuard;
    private volatile boolean cpuOnlyProfileConfigured;
    private final Object cpuLaneOwnership=new Object();
    void setCpuOnlyProductionProfile(CpuOnlyProductionProfile profile,java.util.function.Supplier<String> guard){
        cpuProfile=java.util.Objects.requireNonNull(profile);cpuProfileGuard=java.util.Objects.requireNonNull(guard);
        cpuOnlyProfileConfigured=true;
    }
    private int groupedOutboxLimit=64;
    void setGroupedOutboxLimit(int count){if(count!=64&&count!=128)throw new IllegalArgumentException("Outbox limit");groupedOutboxLimit=count;}
    private volatile boolean independentGpuLane;
    private volatile org.enigmagrid.core.BatchedSolver.Dispatch cohortDispatch;
    private volatile org.enigmagrid.core.WorkBlockPipeline activeBlockPipeline;
    void enableGpuCohorts(org.enigmagrid.core.BatchedSolver.Dispatch dispatch){cohortDispatch=dispatch;}
    void enableIndependentGpuLane(){enableIndependentGpuLane(2);}
    void enableIndependentGpuLane(int lanes){
        if(lanes!=2&&lanes!=4)throw new IllegalArgumentException("Independent lanes");
        synchronized(cpuLaneOwnership){
            // GPU qualification owns the lane topology from this point. A
            // pending CPU A/B demotion must not undo a qualified GPU lane.
            cpuOnlyProfileConfigured=false;cpuProfile=null;cpuProfileGuard=null;
            org.enigmagrid.core.WorkBlockPipeline pipeline=activeBlockPipeline;
            if(pipeline!=null){pipeline.cancelCpuTransition();if(lanes==2)pipeline.promoteToTwoLanes();}
            parallelJobs=lanes;independentGpuLane=true;
        }
    }
    void setParallelJobs(int count){if(count!=1&&count!=2&&count!=4)throw new IllegalArgumentException("Job concurrency must be 1, 2 or 4");parallelJobs=count;}
    private volatile boolean continuous;
    void enableContinuousPrefetch(){continuous=true;}
    private boolean persistentPipeline;
    private boolean blockNegotiated;
    void enablePersistentPipeline(){continuous=true;persistentPipeline=true;}
    private final CompletionTransport completions;
    private final CredentialStore store,pending;
    private volatile boolean revoked;
    private ScheduledExecutorService presence;
    private CoordinatorClient presenceClient;
    synchronized void startPresence(java.util.function.Supplier<String> status,Runnable refused) throws Exception {
        if(presence!=null)return;
        Map<String,Object> account=store.load();
        if(account==null||!client.origin().equals(account.get("server")))throw new IllegalStateException("No matching account");
        final String token=(String)account.get("device_token");
        presenceClient=client.fork();
        final CoordinatorClient connection=presenceClient;
        presence=Executors.newSingleThreadScheduledExecutor();
        presence.scheduleWithFixedDelay(()->{
            String current=status.get();
            // Active work owns its heartbeat. A blocked cooperative gate must
            // not make an otherwise live device disappear from the coordinator.
            if(revoked||current==null||"ready".equals(current)||"computing".equals(current)||"stopped".equals(current)||current.startsWith("CPU quota")||current.startsWith("CPU duty"))return;
            try{allowed(connection.request("/api/heartbeat",object("meta",metadata()),token));}
            catch(IllegalStateException rejected){revoked=true;refused.run();}
            catch(CoordinatorClient.HttpFailure rejected){if(rejected.status==401||rejected.status==403||rejected.status==422){revoked=true;refused.run();}}
            catch(Exception offline){/* Keep thermal protection and saved work intact. */}
        },0,20,TimeUnit.SECONDS);
    }
    synchronized void stopPresence(){if(presence!=null){presence.shutdownNow();presence=null;}if(presenceClient!=null){presenceClient.cancel();presenceClient=null;}
        if(telemetryReporter!=null){telemetryReporter.close();telemetryReporter=null;}}
    private volatile boolean schedulingPaused;
    private Boolean releaseSupported;
    void pauseScheduling(){schedulingPaused=true;}
    void resumeScheduling(){schedulingPaused=false;}
    private volatile boolean acknowledgedWork;
    private volatile long workRetryMillis;
    long workRetryMillis(){return workRetryMillis;}
    private boolean batchEnabled;
    private volatile String phase="Preparing account";
    private volatile boolean uploadActive;
    private volatile org.enigmagrid.core.LeaseReservations workWindow;
    private volatile int executingJobs,pendingResults;
    private volatile int blockReady;
    int readyJobs(){org.enigmagrid.core.LeaseReservations window=workWindow;return window==null?blockReady:window.size();}
    int executingJobs(){return executingJobs;}
    int pendingResults(){return pendingResults;}
    private volatile int expiredResults;
    int expiredResults(){return expiredResults;}
    private volatile double unitsPerSecond,jobsPerSecond;
    private final long metricsStarted=System.nanoTime();
    private volatile long completedUnits,completedJobs,computeNanos,leaseWaitNanos,uploadWaitNanos;
    long completedUnits(){return completedUnits;}
    long completedJobs(){return completedJobs;}
    double wallSeconds(){return (System.nanoTime()-metricsStarted)/1e9;}
    double computeSeconds(){return computeNanos/1e9;}
    double leaseWaitSeconds(){return leaseWaitNanos/1e9;}
    double uploadWaitSeconds(){return uploadWaitNanos/1e9;}
    private volatile double completedPersistenceSeconds;
    private volatile org.enigmagrid.core.WorkBlockQueue activeBlockQueue;
    private volatile org.enigmagrid.core.WorkBlockTransport activeBlockTransport;
    private volatile long completedBlockAcks;
    synchronized long acknowledgedReceipts(){
        org.enigmagrid.core.WorkBlockTransport active=activeBlockTransport;
        return completedBlockAcks+(active==null?0:active.acknowledgedReceipts());
    }
    double persistenceSeconds(){org.enigmagrid.core.WorkBlockQueue q=activeBlockQueue;return completedPersistenceSeconds+(q==null?0:q.persistenceSeconds());}
    String phase(){String current=phase;return uploadActive&&"Computing assigned work".equals(current)?"Computing assigned work · uploading previous result":current;}
    double unitsPerSecond(){return unitsPerSecond;}
    double jobsPerSecond(){return jobsPerSecond;}
    private String acknowledgedSettings;
    boolean acknowledgedWork(){return acknowledgedWork;}
    private volatile org.enigmagrid.core.BoundedCrib.RowProvider rows;
    void promoteQualifiedRows(org.enigmagrid.core.AdaptiveRows qualified){
        if(qualified==null)throw new IllegalArgumentException("Qualified GPU rows required");
        rows=qualified; // Future jobs switch at their invocation boundary; running receipts keep their original backend.
    }
    void promoteQualifiedSolver(org.enigmagrid.core.AdaptiveRows qualified,boolean mixed,
                                org.enigmagrid.core.BatchedSolver.Dispatch cohort){
        promoteQualifiedRows(qualified);
        if(mixed){if(cohort!=null)enableGpuCohorts(cohort);enableIndependentGpuLane(2);}
    }
    boolean gpuAvailable(){
        org.enigmagrid.core.BoundedCrib.RowProvider current=rows;
        return current instanceof org.enigmagrid.core.AdaptiveRows&&((org.enigmagrid.core.AdaptiveRows)current).available();
    }
    String backendName(){
        org.enigmagrid.core.BoundedCrib.RowProvider current=rows;
        if(!gpuAvailable())return "cpu";
        if(independentGpuLane)return "vulkan-mixed"+parallelJobs;
        return current.hybrid()?"vulkan-hybrid":"vulkan-rows";
    }
    NetworkWorker(CoordinatorClient client,CredentialStore store){this(client,store,null);}
    // Older coordinators return 404 once; the worker then retains single-lease mode.
    NetworkWorker(CoordinatorClient client,CredentialStore store,org.enigmagrid.core.BoundedCrib.RowProvider rows){this(client,store,rows,true);}
    NetworkWorker(CoordinatorClient client,CredentialStore store,org.enigmagrid.core.BoundedCrib.RowProvider rows,boolean batchEnabled){this.batchEnabled=batchEnabled;this.rows=rows;this.client=client;this.completions=new CompletionTransport(client);this.heartbeat=client.fork();this.allocator=client.fork();this.store=store;this.pending=store.pendingResults();}
    private Map<String,Object> metadata(){
        Map<String,Object> meta=Enrollment.metadata();
        if(gpuAvailable()){
            meta.put("capabilities",Arrays.asList("cpu","bounded_crib_v1","gpu"));
            meta.put("gpus",Arrays.asList(object("vendor","Vulkan","name","Qualified Vulkan compute","memory_mb",0)));
        }
        return meta;
    }
    void cancel(){revoked=true;stopPresence();client.cancel();heartbeat.cancel();allocator.cancel();}
    @SuppressWarnings("unchecked")
    String once(BooleanSupplier control) throws Exception {return once(control,null);}
    @SuppressWarnings("unchecked")
    String once(BooleanSupplier control,Map<String,Object> settings) throws Exception {
        acknowledgedWork=false;workRetryMillis=0;phase="Reading saved account and receipts";
        Map<String,Object> state=store.load();
        if(state==null||!client.origin().equals(state.get("server")))throw new IllegalStateException("No matching account");
        String token=(String)state.get("device_token");
        Map<String,Object> saved=pending.load();
        // Migrate the early development format without dropping a result after a crash.
        if(saved==null && state.get("pending_submission") instanceof Map){
            saved=object("server",client.origin(),"owner",org.enigmagrid.core.Canonical.digest(token),"submission",state.get("pending_submission"));pending.save(saved);
        }
        org.enigmagrid.core.ReceiptQueue queue=new org.enigmagrid.core.ReceiptQueue(new org.enigmagrid.core.ReceiptStorageSession(new org.enigmagrid.core.ReceiptQueue.Storage(){
            public Map<String,Object> load() throws Exception{return pending.load();}
            public void save(Map<String,Object> value) throws Exception{pending.save(value);}
        }),client.origin(),org.enigmagrid.core.Canonical.digest(token));
        java.util.List<Map<String,Object>> receipts=queue.pending();
        pendingResults=receipts.size();
        if(!receipts.isEmpty()){
            if(state.remove("pending_submission")!=null)store.save(state);
            Map<String,Object> receipt=receipts.get(0);
            phase="Sending saved result; waiting for coordinator";
            check(control);submit(receipt,token);queue.acknowledge((String)receipt.get("lease_id"));pendingResults=queue.unacknowledgedCount();acknowledgedWork=true;
            return "Saved result acknowledged; independent verification may still be pending";
        }
        check(control);
        phase="Synchronizing resource settings";
        if(settings!=null){
            String signature=org.enigmagrid.core.Canonical.json(object("owner",org.enigmagrid.core.Canonical.digest(token),"settings",settings));
            if(!signature.equals(acknowledgedSettings)){
                Map<String,Object> ack=client.request("/api/device/settings",object("settings",settings),token);
                if(!Boolean.TRUE.equals(ack.get("ok")))throw new IllegalStateException("Settings not acknowledged");
                acknowledgedSettings=signature;
            }
        }
        // Lease itself checks revocation and mandatory updates, and records runtime metadata.
        if(persistentPipeline){String blockResult=runBlocks(token,control);if(blockResult!=null)return blockResult;}
        // Long-running work still renews its lease with the scheduled heartbeat below.
        phase="Requesting compatible work";
        Map<String,Object> assignment=null;
        long leaseStarted=System.nanoTime();
        try {
        if(batchEnabled)try{assignment=client.request("/api/leases",object("meta",metadata(),"count",32),token);}
        catch(CoordinatorClient.HttpFailure unsupported){if(unsupported.status!=404)throw unsupported;batchEnabled=false;}
        if(assignment==null)assignment=client.request("/api/lease",object("meta",metadata()),token);
        } finally {leaseWaitNanos+=System.nanoTime()-leaseStarted;}
        allowed(assignment);
        final boolean newLeaseLimit=Boolean.TRUE.equals(assignment.get("new_lease_limit"));
        Object raw=batchEnabled?assignment.get("leases"):assignment.get("lease");
        List<?> leases=batchEnabled?(raw instanceof List?(List<?>)raw:null):(raw==null?Collections.emptyList():Collections.singletonList(raw));
        if(leases==null||leases.size()>32)throw new IllegalArgumentException("Invalid lease batch");
        if(leases.isEmpty()){
            Object retry=assignment.get("retry_after_seconds");
            if(retry instanceof Number){double seconds=((Number)retry).doubleValue();if(Double.isFinite(seconds))workRetryMillis=(long)(Math.max(0,Math.min(60,seconds))*1000);}
            String reason=String.valueOf(assignment.get("wait_reason"));
            if("verification_pending".equals(reason))return "Waiting for independent verification; safety limit reached";
            if("primary_held_for_verification".equals(reason))return "Coordinator is prioritizing independent verification";
            return "Waiting for compatible work";
        }
        Set<String> ids=new HashSet<>();
        for(Object item:leases){
            if(!(item instanceof Map))throw new IllegalArgumentException("Invalid lease");
            Map<String,Object> lease=(Map<String,Object>)item;WorkEnvelope.validate(lease);
            if(!(lease.get("id") instanceof String)||!(lease.get("work_token") instanceof String)||!ids.add((String)lease.get("id")))throw new IllegalArgumentException("Invalid lease credentials or duplicate lease");
        }
        ScheduledExecutorService renew=Executors.newSingleThreadScheduledExecutor();
        List<Map<String,Object>> assigned=new ArrayList<>();for(Object lease:leases)assigned.add((Map<String,Object>)lease);
        org.enigmagrid.core.LeaseReservations reservations=new org.enigmagrid.core.LeaseReservations(assigned);
        workWindow=reservations;
        ExecutorService fetching=Executors.newSingleThreadExecutor();
        Future<Integer> refill=null;
        long nextRefillAt=0;
        java.util.concurrent.atomic.AtomicLong refillDelayNanos=new java.util.concurrent.atomic.AtomicLong(1_000_000_000L);
        java.util.concurrent.atomic.AtomicReference<String> idleReason=new java.util.concurrent.atomic.AtomicReference<>("Waiting for compatible work");
        java.util.concurrent.atomic.AtomicBoolean closing=new java.util.concurrent.atomic.AtomicBoolean();
        // Finish one calibration/validation batch, then negotiate blocks again.
        // Otherwise the legacy persistent loop can keep this client there forever.
        boolean refillEnabled=continuous&&batchEnabled&&!blockNegotiated;
        double averageJobSeconds=.1;
        final java.util.concurrent.atomic.AtomicLong allocationNanos=new java.util.concurrent.atomic.AtomicLong(System.nanoTime()-leaseStarted);
        long[] heartbeatAt={System.nanoTime()};
        renew.scheduleWithFixedDelay(()->{
            try{
                if(schedulingPaused)releaseUnused(reservations,token);
                if(System.nanoTime()-heartbeatAt[0]>=20_000_000_000L){
                    allowed(heartbeat.request("/api/heartbeat",object("meta",metadata()),token));heartbeatAt[0]=System.nanoTime();
                }
            }
            catch(IllegalStateException e){revoked=true;}
            catch(Exception e){/* Offline computation may finish; durable result waits for reconnection. */}
        },1,1,TimeUnit.SECONDS);
        ExecutorService uploads=Executors.newSingleThreadExecutor();
        BlockingQueue<Map<String,Object>> ready=new ArrayBlockingQueue<>(8);
        java.util.concurrent.atomic.AtomicBoolean produced=new java.util.concurrent.atomic.AtomicBoolean();
        Future<?> uploading=uploads.submit(()->{
            while(!produced.get()||!ready.isEmpty()){
                Map<String,Object> submission=ready.poll(100,TimeUnit.MILLISECONDS);
                if(submission==null)continue;
                List<Map<String,Object>> batch=new ArrayList<>();batch.add(submission);ready.drainTo(batch,7);
                uploadActive=true;
                try{completions.send(batch,token,id->{queue.confirm(id);pendingResults=queue.unacknowledgedCount();reservations.acknowledge(id);acknowledgedWork=true;});}
                finally{uploadActive=false;}
            }
            queue.flushConfirmed();
            return null;
        });
        ExecutorService computation=Executors.newFixedThreadPool(4);
        CompletionService<Double> completed=new ExecutorCompletionService<>(computation);
        Set<Future<Double>> running=new HashSet<>();
        try {
        while(true){
            check(control);
            Future<Double> finished;
            while((finished=completed.poll())!=null){
                running.remove(finished);executingJobs=running.size();
                double seconds=refillResult(finished);
                averageJobSeconds=averageJobSeconds*.8+seconds*.2;
            }
            if(refill!=null&&refill.isDone()){
                int added=refillResult(refill);refill=null;
                // A replay-only response is temporary: active leases may still
                // occupy the server window until the uploader acknowledges them.
                // Retry while computation continues rather than draining the
                // entire queue and tearing down the pipeline after one miss.
                nextRefillAt=added==0?System.nanoTime()+refillDelayNanos.get():0;
            }
            int threshold=Math.max(2,Math.min(24,(int)Math.ceil(parallelJobs*allocationNanos.get()/1e9/Math.max(.001,averageJobSeconds))+2*parallelJobs));
            if(refillEnabled&&refill==null&&System.nanoTime()>=nextRefillAt&&!schedulingPaused&&reservations.size()<=threshold&&reservations.heldCount()<32){
                refill=fetching.submit(()->{
                    if(schedulingPaused||revoked||closing.get())return 0;
                    long began=System.nanoTime();
                    try{
                        if(settingsSource!=null){
                            Map<String,Object> currentSettings=settingsSource.get();String signature=org.enigmagrid.core.Canonical.json(object("owner",org.enigmagrid.core.Canonical.digest(token),"settings",currentSettings));
                            if(!signature.equals(acknowledgedSettings)){
                                Map<String,Object> ack=allocator.request("/api/device/settings",object("settings",currentSettings),token);
                                if(!Boolean.TRUE.equals(ack.get("ok")))throw new IllegalStateException("Settings not acknowledged");
                                acknowledgedSettings=signature;
                            }
                        }
                        // Completion may commit on the server before its acknowledgement
                        // reaches this uploader. Reserve against the local window,
                        // including those receipts, not a fresh server-sized window.
                        // Existing leases can be replayed above this count; only
                        // newly issued work consumes the remaining local slots.
                        int requested=32-reservations.heldCount();
                        if(requested<=0)return 0;
                        Map<String,Object> request=object("meta",metadata(),"count",newLeaseLimit?32:requested);
                        if(newLeaseLimit)request.put("max_new",requested);
                        Map<String,Object> reply=allocator.request("/api/leases",request,token);allowed(reply);
                        Object delay=reply.get("retry_after_seconds");double seconds=delay instanceof Number?((Number)delay).doubleValue():1;
                        refillDelayNanos.set((long)((Double.isFinite(seconds)?Math.max(1,Math.min(60,seconds)):1)*1e9));
                        String reason=String.valueOf(reply.get("wait_reason"));
                        idleReason.set("verification_pending".equals(reason)?"Waiting for independent verification; safety limit reached":"primary_held_for_verification".equals(reason)?"Coordinator is prioritizing independent verification":"Waiting for compatible work");
                        Object value=reply.get("leases");if(!(value instanceof List)||((List<?>)value).size()>32)throw new IllegalArgumentException("Invalid prefetch batch");
                        List<Map<String,Object>> result=new ArrayList<>();Set<String> unique=new HashSet<>();
                        for(Object item:(List<?>)value){
                            if(!(item instanceof Map))throw new IllegalArgumentException("Invalid prefetch lease");
                            Map<String,Object> lease=(Map<String,Object>)item;WorkEnvelope.validate(lease);
                            if(!(lease.get("id") instanceof String)||!(lease.get("work_token") instanceof String)||!unique.add((String)lease.get("id")))throw new IllegalArgumentException("Invalid prefetch credentials");
                            result.add(lease);
                        }
                        int added=reservations.merge(result);
                        if(schedulingPaused||revoked||closing.get())releaseUnused(reservations,token);
                        return added;
                    }finally{long elapsed=System.nanoTime()-began;allocationNanos.set(elapsed);leaseWaitNanos+=elapsed;}
                });
            }
            if(uploading.isDone())awaitUpload(uploading,control);
            if(running.size()>=parallelJobs||!queue.hasCapacity()){
                phase=running.isEmpty()?"Result queue full; waiting for upload":"Computing assigned work";
                Future<Double> next=completed.poll(10,TimeUnit.MILLISECONDS);
                if(next!=null){running.remove(next);executingJobs=running.size();double seconds=refillResult(next);averageJobSeconds=averageJobSeconds*.8+seconds*.2;}
                continue;
            }
            Map<String,Object> lease=reservations.take();
            if(lease==null){
                if(refill!=null||!running.isEmpty()){
                    phase=running.isEmpty()?"Waiting for prefetched work":"Computing assigned work";
                    Thread.sleep(10);continue;
                }
                if(persistentPipeline&&refillEnabled){
                    phase=idleReason.get();Thread.sleep(50);continue;
                }
                break;
            }
            String reservedLease=(String)lease.get("id");
            if(!queue.reserve(reservedLease))throw new IllegalStateException("Result capacity unavailable before computation");
            phase="Computing assigned work";
            try {
                running.add(completed.submit(()->{
                    try {
                        check(()->closing.get()||control.getAsBoolean());
                        long started=System.nanoTime();
                        Map<String,Object> result=WorkEnvelope.run(lease,()->closing.get()||revoked||control.getAsBoolean(),rows,Math.max(1,Math.min(32,Runtime.getRuntime().availableProcessors())));
                        double seconds=Math.max(.000001,(System.nanoTime()-started)/1e9);
                        long units=unitCount(lease);
                        Map<String,Object> receipt=(Map<String,Object>)result.get("receipt");
                        Map<String,Object> submission=object("lease_id",lease.get("id"),"work_token",lease.get("work_token"),"compute_seconds",Double.toString(seconds),"candidate_count",((List<?>)receipt.get("candidates")).size(),"result",result,"meta",metadata());
                        // Persist even if stop arrives after computation completed.
                        queue.append(submission);pendingResults=queue.unacknowledgedCount();
                        synchronized(this){
                            unitsPerSecond=units/seconds;jobsPerSecond=1.0/seconds;
                            completedUnits+=units;completedJobs++;computeNanos+=(long)(seconds*1e9);
                        }
                        ready.put(submission);return seconds;
                    } finally {queue.releaseReservation(reservedLease);}
                }));
                executingJobs=running.size();
            } catch(RuntimeException rejected){queue.releaseReservation(reservedLease);throw rejected;}
        }
        produced.set(true);awaitUpload(uploading,control);
        } finally {
            closing.set(true);
            for(Future<?> task:running)task.cancel(true);
            computation.shutdownNow();
            boolean computeInterrupted=Thread.interrupted();
            boolean computeStopped=false;
            try{computeStopped=computation.awaitTermination(8,TimeUnit.SECONDS);}
            finally{if(computeInterrupted)Thread.currentThread().interrupt();produced.set(true);}
            executingJobs=0;
            allocator.cancel();if(refill!=null)refill.cancel(true);fetching.shutdownNow();
            if(!uploading.isDone()){client.cancel();uploading.cancel(true);}
            uploads.shutdownNow();
            boolean interrupted=Thread.interrupted();
            try{
                Future<?> release=renew.submit(()->{try{releaseUnused(reservations,token);}catch(Exception ignored){/* Uncertain releases remain reserved until expiry/replay. */}});
                try{release.get(5,TimeUnit.SECONDS);}catch(Exception unfinished){release.cancel(true);}
                if(!uploads.awaitTermination(2,TimeUnit.SECONDS))
                    throw new IllegalStateException("Upload did not stop; saved results retained");
                queue.flushConfirmed();
                if(!computeStopped)throw new IllegalStateException("Compute did not stop; worker restart prohibited");
            }finally{workWindow=null;renew.shutdownNow();heartbeat.cancel();if(interrupted)Thread.currentThread().interrupt();}
        }
        return "Result acknowledged; awaiting independent verification";
    }
    private static <T> T refillResult(Future<T> future)throws Exception {
        try{return future.get();}catch(ExecutionException error){
            Throwable cause=error.getCause();if(cause instanceof Exception)throw (Exception)cause;
            if(cause instanceof Error)throw (Error)cause;throw new IllegalStateException(cause);
        }
    }
    private synchronized void releaseUnused(org.enigmagrid.core.LeaseReservations reservations,String token)throws Exception {
        if(reservations.size()==0)return;
        if(releaseSupported==null){
            try{releaseSupported=Boolean.TRUE.equals(heartbeat.request("/api/capabilities",null,null).get("release_leases"));}
            catch(CoordinatorClient.HttpFailure error){if(error.status!=404&&error.status!=405)throw error;releaseSupported=false;}
        }
        if(!releaseSupported)return;
        reservations.releaseUnused(unused->{
            List<Map<String,Object>> payload=new ArrayList<>();
            for(Map<String,Object> lease:unused)payload.add(object("lease_id",lease.get("id"),"work_token",lease.get("work_token")));
            return Boolean.TRUE.equals(heartbeat.request("/api/leases/release",object("leases",payload),token).get("ok"));
        });
    }
    private String runBlocks(String token,BooleanSupplier control)throws Exception {
        blockNegotiated=false;
        Map<String,Object> capabilities;
        try{capabilities=allocator.request("/api/capabilities",null,null);}
        catch(CoordinatorClient.HttpFailure error){if(error.status==404||error.status==405)return null;throw error;}
        long capabilitiesReceivedNs=System.nanoTime();
        // One reporter follows the worker across bounded and legacy leases.
        // A calibration fallback must not interrupt diagnostics or create a
        // second session with overlapping five-second buckets.
        startTelemetryIfAvailable(capabilities,token,capabilitiesReceivedNs);
        if(!org.enigmagrid.core.WorkBlock.FORMAT.equals(capabilities.get("long_work_blocks")))return null;
        blockNegotiated=true;
        boolean grouped=org.enigmagrid.core.WorkBlockTransport.GROUP_FORMAT.equals(capabilities.get("work_result_groups"));
        org.enigmagrid.core.ReceiptQueue.Storage saved=store.workBlockStorage();
        int pendingLimit=grouped?groupedOutboxLimit:8;
        org.enigmagrid.core.WorkBlockQueue queue=new org.enigmagrid.core.WorkBlockQueue(new org.enigmagrid.core.ReceiptStorageSession(new org.enigmagrid.core.ReceiptQueue.Storage(){
            public Map<String,Object> load()throws Exception{return saved.load();}
            public void save(Map<String,Object> value)throws Exception{saved.save(value);}
        }),client.origin(),org.enigmagrid.core.Canonical.digest(token),grouped,pendingLimit,System::nanoTime);
        CredentialStore expired=store.expiredResults();
        queue.useExpiredStorage(new org.enigmagrid.core.ReceiptStorageSession(new org.enigmagrid.core.ReceiptQueue.Storage(){
            public Map<String,Object> load()throws Exception{return expired.load();}
            public void save(Map<String,Object> value)throws Exception{expired.save(value);}
        }));
        activeBlockQueue=queue;
        CoordinatorClient blockUpload=client.fork(),blockStatus=client.fork(),blockAllocation=client.fork(),blockRelease=client.fork();
        org.enigmagrid.core.WorkBlockTransport transport=new org.enigmagrid.core.WorkBlockTransport(queue,(path,body)->{
            CoordinatorClient connection=path.endsWith("/status")?blockStatus:path.endsWith("/release")?blockRelease:path.contains("result")?blockUpload:blockAllocation;
            boolean sending=path.contains("result");long began=System.nanoTime();if(sending)uploadActive=true;
            try{Map<String,Object> response=connection.request(path,body,token);allowed(response);return response;}
            catch(CoordinatorClient.HttpFailure failure){if(failure.status==401||failure.status==403||failure.status==422)throw new IllegalStateException("Coordinator rejected block request",failure);throw failure;}
            finally{if(sending){uploadActive=false;uploadWaitNanos+=System.nanoTime()-began;}else if(path.equals("/api/work-blocks"))leaseWaitNanos+=System.nanoTime()-began;}
        },grouped);
        activeBlockTransport=transport;
        java.util.concurrent.atomic.AtomicInteger laneSequence=new java.util.concurrent.atomic.AtomicInteger();
        ThreadLocal<Boolean> gpuLane=ThreadLocal.withInitial(()->laneSequence.getAndIncrement()==0);
        ScheduledExecutorService renew=Executors.newSingleThreadScheduledExecutor();
        org.enigmagrid.core.WorkBlockPipeline.BatchCompute computation=new org.enigmagrid.core.WorkBlockPipeline.BatchCompute(){
            public Map<String,Object> run(Map<String,Object> envelope)throws Exception {
                check(control);phase="Computing assigned work";synchronized(NetworkWorker.this){executingJobs++;}long began=System.nanoTime();
                try {
                    int laneWorkers=org.enigmagrid.core.CpuLaneBudget.forLane(
                        Runtime.getRuntime().availableProcessors(),parallelJobs,independentGpuLane,independentGpuLane&&gpuLane.get());
                    Map<String,Object> result=WorkEnvelope.run(envelope,()->revoked||control.getAsBoolean(),independentGpuLane&&!gpuLane.get()?null:rows,laneWorkers);
                    accountResult((System.nanoTime()-began)/1e9);return result;
                } finally{synchronized(NetworkWorker.this){executingJobs--;}}
            }
            private void accountResult(double seconds){synchronized(NetworkWorker.this){seconds=Math.max(.000001,seconds);completedJobs++;completedUnits++;computeNanos+=(long)(seconds*1e9);unitsPerSecond=jobsPerSecond=1/seconds;}}
            public void runBatch(List<Map<String,Object>> envelopes,org.enigmagrid.core.WorkBlockPipeline.Completed completed)throws Exception {
                check(control);
                if(cohortDispatch==null||!independentGpuLane||!gpuLane.get()){
                    for(int i=0;i<envelopes.size();i++){check(control);long began=System.nanoTime();Map<String,Object> result=run(envelopes.get(i));completed.accept(i,result,Math.max(.000001,(System.nanoTime()-began)/1e9));}return;
                }
                phase="Computing assigned work";synchronized(NetworkWorker.this){executingJobs++;}long began=System.nanoTime();
                try{
                    org.enigmagrid.core.GpuWorkCohort.run(envelopes,cohortDispatch,()->revoked||control.getAsBoolean(),
                        org.enigmagrid.core.CpuLaneBudget.forLane(Runtime.getRuntime().availableProcessors(),parallelJobs,true,true),(index,result,seconds)->{
                        accountResult(seconds);completed.accept(index,result,seconds);
                    });
                }finally{synchronized(NetworkWorker.this){executingJobs--;}}
            }
        };
        // Four-job windows are enabled only for qualified independent GPU execution.
        org.enigmagrid.core.WorkBlockPipeline.Compute execution=computation;
        org.enigmagrid.core.WorkBlockPipeline pipeline=new org.enigmagrid.core.WorkBlockPipeline(queue,transport,execution,parallelJobs);
        pipeline.setCpuLaneBudgetPublisher(target->parallelJobs=target);
        activeBlockPipeline=pipeline;
        long nextCpuProfileSample=0,nextCpuSafetySample=0;
        try {
            allowed(heartbeat.request("/api/heartbeat",object("meta",metadata()),token));transport.refreshStatus();
            renew.scheduleWithFixedDelay(()->{try {
                allowed(heartbeat.request("/api/heartbeat",object("meta",metadata()),token));
                if(settingsSource!=null){Map<String,Object> current=settingsSource.get();String signature=org.enigmagrid.core.Canonical.json(object("owner",org.enigmagrid.core.Canonical.digest(token),"settings",current));
                    if(!signature.equals(acknowledgedSettings)){Map<String,Object> ack=heartbeat.request("/api/device/settings",object("settings",current),token);if(!Boolean.TRUE.equals(ack.get("ok")))throw new IllegalStateException("Settings not acknowledged");acknowledgedSettings=signature;}}
            }catch(IllegalStateException e){revoked=true;}catch(CoordinatorClient.HttpFailure e){if(e.status==401||e.status==403||e.status==422)revoked=true;}catch(Exception offline){}},20,20,TimeUnit.SECONDS);
            while(true){
                check(control);
                if(schedulingPaused){queue.retire();return "Paused; completed block results retained";}
                boolean worked=pipeline.tick(true);pendingResults=queue.pendingCount();expiredResults=queue.expiredReceiptCount();blockReady=(int)Math.min(Integer.MAX_VALUE,queue.remaining());
                long profileNow=System.nanoTime();
                synchronized(cpuLaneOwnership){
                CpuOnlyProductionProfile profile=cpuOnlyProfileConfigured?cpuProfile:null;
                if(cpuOnlyProfileConfigured&&pipeline.lanes()==2&&(profile==null||profile.done())
                    &&profileNow>=nextCpuSafetySample){
                    nextCpuSafetySample=profileNow+500_000_000L;
                    java.util.function.Supplier<String> gate=cpuProfileGuard;
                    boolean safe;
                    try{safe=!revoked&&!schedulingPaused&&!independentGpuLane&&!gpuAvailable()
                        &&pendingResults<queue.capacity()-8
                        &&gate!=null&&gate.get()==null;}
                    catch(RuntimeException unavailable){safe=false;}
                    if(!safe)pipeline.requestCpuLanes(1);
                }
                if(profile!=null&&!profile.done()&&profileNow>=nextCpuProfileSample){
                    nextCpuProfileSample=profileNow+500_000_000L;
                    try{
                        org.enigmagrid.core.WorkBlockPipeline.DurableProgress durable=pipeline.durableProgress();
                        java.util.function.Supplier<String> gate=cpuProfileGuard;
                        boolean eligible=!revoked&&!schedulingPaused&&!independentGpuLane&&!gpuAvailable()
                            &&gate!=null&&gate.get()==null;
                        CpuOnlyProductionProfile.Sample sample=new CpuOnlyProductionProfile.Sample(profileNow,durable.units,
                            durable.scopeGeneration,durable.scope,transport.acknowledgedReceipts(),blockReady,pendingResults,
                            queue.capacity(),pipeline.lanes(),eligible);
                        int target=profile.observe(sample);if(target!=0)pipeline.requestCpuLanes(target);
                    }
                    catch(RuntimeException localProfileFailure){
                        // A local performance profile cannot stop receipt work.
                        pipeline.requestCpuLanes(1);
                        cpuProfile=null;
                    }
                }
                }
                if(!worked){
                    if(pipeline.computing()){pipeline.awaitProgress(20);continue;}
                    if(blockReady==0&&pendingResults==0&&Arrays.asList("block_calibration_required","legacy_priority_work","legacy_validation_work").contains(pipeline.waitReason()))return null;
                    phase=pendingResults>=queue.capacity()?"Sending saved results":"Waiting for compatible work";unitsPerSecond=jobsPerSecond=0;Thread.sleep(20);
                }
            }
        } finally {
            renew.shutdownNow();blockUpload.cancel();blockStatus.cancel();blockAllocation.cancel();blockRelease.cancel();
            pipeline.close();activeBlockPipeline=null;queue.retire();blockReady=0;
            // A newly constructed pipeline cannot inherit an in-flight pilot's
            // two-lane setting after an interrupted or failed block session.
            synchronized(cpuLaneOwnership){
                if(cpuOnlyProfileConfigured){
                    CpuOnlyProductionProfile finished=cpuProfile;
                    parallelJobs=1;
                    // A new pipeline first establishes its own block scope. Only
                    // a previously saved two-lane result may be reloaded there.
                    cpuProfile=finished!=null&&finished.qualifiedTwo()?finished.nextSession():null;
                    if(cpuProfile==null)cpuProfileGuard=null;
                }
            }
            try{transport.recovery().releaseReady();}catch(Exception uncertain){/* Retired ranges remain durable for recovery. */}
            synchronized(this){completedBlockAcks+=transport.acknowledgedReceipts();activeBlockTransport=null;}
            completedPersistenceSeconds+=queue.persistenceSeconds();activeBlockQueue=null;
        }
    }
    private static long unitCount(Map<String,Object> lease){
        Object start=lease.get("start_unit"),end=lease.get("end_unit");
        if(start instanceof Number&&end instanceof Number)return Math.max(1L,((Number)end).longValue()-((Number)start).longValue());
        return 1L;
    }
    private void check(BooleanSupplier control){if(revoked||Thread.currentThread().isInterrupted()||control.getAsBoolean())throw new CancellationException();}
    private void awaitUpload(Future<?> upload,BooleanSupplier control) throws Exception {
        phase="Waiting for saved result acknowledgement";
        long waitStarted=System.nanoTime();
        try {
        while(true){
            check(control);
            try{upload.get(100,TimeUnit.MILLISECONDS);return;}
            catch(TimeoutException waiting){/* Keep pause/stop controls responsive. */}
            catch(ExecutionException failed){
                Throwable cause=failed.getCause();
                if(cause instanceof Exception)throw (Exception)cause;
                if(cause instanceof Error)throw (Error)cause;
                throw new IllegalStateException(cause);
            }
        }
        } finally {uploadWaitNanos+=System.nanoTime()-waitStarted;}
    }
    private void allowed(Map<String,Object> response){if(Boolean.FALSE.equals(response.get("enabled"))||Boolean.TRUE.equals(response.get("quarantined")))throw new IllegalStateException("Device disabled by coordinator");if(Boolean.TRUE.equals(response.get("update_required")))throw new IllegalStateException("Coordinator requires a newer compatible client");}
    private void submit(Map<String,Object> submission,String token) throws Exception {
        uploadActive=true;
        try {
            Map<String,Object> ack=client.request("/api/complete",submission,token);
            if(!Boolean.TRUE.equals(ack.get("ok")))throw new IllegalStateException("Submission not acknowledged");
        } finally {uploadActive=false;}

    }
}
