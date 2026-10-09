package org.enigmagrid.core;

import java.util.*;
import java.util.concurrent.*;

/** Bounded compute lanes with independent allocation, upload and status requests. */
public final class WorkBlockPipeline implements AutoCloseable {
    public interface Compute {Map<String,Object> run(Map<String,Object> envelope)throws Exception;}
    /** Implemented by HTTP failures that carry a coordinator retry interval. */
    public interface RetryHint {int status();long retryAfterMillis();}
    public interface Completed {void accept(int index,Map<String,Object> receipt,double seconds)throws Exception;}
    public interface BatchCompute extends Compute {
        void runBatch(List<Map<String,Object>> envelopes,Completed completed)throws Exception;
    }
    private final WorkBlockQueue queue;private final WorkBlockTransport transport;private final Compute compute;
    private volatile int lanes;private final ExecutorService solvers;
    /** Count only receipts whose queue mutation has completed its durable save. */
    public static final class DurableProgress {
        public final long units,scopeGeneration;public final String scope;
        DurableProgress(long units,long scopeGeneration,String scope){this.units=units;this.scopeGeneration=scopeGeneration;this.scope=scope;}
    }
    private volatile DurableProgress durableProgress=new DurableProgress(0,0,null);
    private static final class ActiveScope {
        final String digest;int claims;
        ActiveScope(String digest){this.digest=digest;claims=1;}
    }
    // Entries live only while a claimed job (including its durable write) is
    // active. Long-running sessions may legitimately see more than 16 blocks.
    private final java.util.concurrent.ConcurrentHashMap<String,ActiveScope> scopeByBlock=new java.util.concurrent.ConcurrentHashMap<>();
    private volatile int requestedCpuLanes;
    private java.util.function.IntConsumer laneBudgetPublisher=ignored->{};
    private final BlockingQueue<Boolean> progress=new ArrayBlockingQueue<>(1);
    private final List<Future<Double>> running=new ArrayList<>();
    private final List<Map<String,Object>> claims=new ArrayList<>();
    private final Map<Future<Double>,List<Map<String,Object>>> assignments=new HashMap<>();
    private final ExecutorService writer=Executors.newSingleThreadExecutor();
    private static final class Write {
        final List<WorkBlockQueue.Completion> completions;final CompletableFuture<Void> durable=new CompletableFuture<>();
        Write(List<WorkBlockQueue.Completion> completions){this.completions=new ArrayList<>(completions);}
    }
    private final BlockingQueue<Write> waitingWrites=new ArrayBlockingQueue<>(8);
    private final List<Future<?>> writes=Collections.synchronizedList(new ArrayList<>());
    private volatile boolean allowNext=true;
    private final ExecutorService fetcher=Executors.newSingleThreadExecutor(),sender=Executors.newSingleThreadExecutor(),statusReader=Executors.newSingleThreadExecutor(),releaser=Executors.newSingleThreadExecutor();
    private Future<Map<String,Object>> fetch;private Future<Double> upload;private Future<?> status,releaseTask;
    private long nextFetch,nextUpload,nextStatus,nextRelease,flushAt,uploadStarted;
    private int emptyFetches,failedFetches,failedReleases;
    private double rate,uploadLatency=.25;
    private double fillRateHint;
    private boolean initialFill=true;
    private double initialFillLatchRate;
    private final ArrayDeque<Double> initialFillSamples=new ArrayDeque<>();
    private volatile boolean closed;
    private String waitReason;
    public String waitReason(){return waitReason;}
    private void observeInitialFill()throws Exception {
        if(rate<=0)return;
        long remaining=queue.remaining();
        // Early stable slow jobs can overstate how long a block will last.
        // Re-arm only on a material measured speedup, preserving normal refill
        // when subsequent rates are comparable to the latched observation.
        if(!initialFill){
            if(initialFillLatchRate>0&&rate>initialFillLatchRate*1.15&&remaining/rate<1800){
                initialFill=true;initialFillSamples.clear();
            }
            return;
        }
        if(remaining/rate<1800){initialFillSamples.clear();return;}
        initialFillSamples.addLast(rate);
        if(initialFillSamples.size()>3)initialFillSamples.removeFirst();
        if(initialFillSamples.size()==3){
            double low=Double.POSITIVE_INFINITY,high=0;
            for(double sample:initialFillSamples){low=Math.min(low,sample);high=Math.max(high,sample);}
            if(low>0&&high/low<=1.15){initialFill=false;initialFillLatchRate=rate;}
        }
    }
    public WorkBlockPipeline(WorkBlockQueue queue,WorkBlockTransport transport,Compute compute){this(queue,transport,compute,1);}
    public WorkBlockPipeline(WorkBlockQueue queue,WorkBlockTransport transport,Compute compute,int lanes){
        if(lanes!=1&&lanes!=2&&lanes!=4)throw new IllegalArgumentException("Compute lanes must be 1, 2 or 4");
        this.queue=queue;this.transport=transport;this.compute=compute;this.lanes=lanes;
        // Threads are created lazily; a qualified first-use GPU profile may
        // promote one synchronous CPU lane to two receipt-safe lanes later.
        solvers=new ThreadPoolExecutor(4,4,0L,TimeUnit.MILLISECONDS,new LinkedBlockingQueue<Runnable>()) {
            @Override protected void afterExecute(Runnable task,Throwable error){
                super.afterExecute(task,error);
                // FutureTask is now complete, including a failed durable save.
                progress.offer(Boolean.TRUE);
            }
        };
    }
    public synchronized void promoteToTwoLanes(){
        if(closed)throw new IllegalStateException("Pipeline closed");
        requestedCpuLanes=0;
        if(lanes==1)lanes=2;
    }
    public int lanes(){return lanes;}
    public DurableProgress durableProgress(){return durableProgress;}
    /** CPU-only transitions are applied by tick after claims and writes drain. */
    public void setCpuLaneBudgetPublisher(java.util.function.IntConsumer publisher){laneBudgetPublisher=Objects.requireNonNull(publisher);}
    public synchronized void requestCpuLanes(int target){
        if(closed||target!=1&&target!=2)throw new IllegalArgumentException("CPU lane transition");
        requestedCpuLanes=target==lanes?0:target;
    }
    public synchronized void cancelCpuTransition(){requestedCpuLanes=0;}
    private synchronized boolean applyCpuTransition(){
        int target=requestedCpuLanes;
        if(target==0||!running.isEmpty()||!claims.isEmpty()||!assignments.isEmpty()||!waitingWrites.isEmpty())return false;
        synchronized(writes){if(!writes.isEmpty())return false;}
        // Publish the per-lane stripe budget before the next claim can launch.
        laneBudgetPublisher.accept(target);lanes=target;requestedCpuLanes=0;return true;
    }
    @SuppressWarnings("unchecked") private void rememberScope(Map<String,Object> claim){
        String id=(String)claim.get("block_id");
        Map<String,Object> envelope=(Map<String,Object>)claim.get("envelope");
        scopeByBlock.compute(id,(key,active)->{
            if(active!=null){active.claims++;return active;}
            return new ActiveScope(Canonical.digest(envelope.get("config")));
        });
    }
    private void forgetScope(String id){
        scopeByBlock.computeIfPresent(id,(key,active)->{
            if(--active.claims<0)throw new IllegalStateException("Scope claim underflow");
            return active.claims==0?null:active;
        });
    }
    private String activeScope(String id){
        ActiveScope active=scopeByBlock.get(id);return active==null?"unknown":active.digest;
    }
    private synchronized void recordDurable(List<WorkBlockQueue.Completion> completions){
        DurableProgress old=durableProgress;String scope=old.scope;long generation=old.scopeGeneration;
        for(WorkBlockQueue.Completion receipt:completions){
            String next=activeScope(receipt.id);
            if(!Objects.equals(scope,next)){scope=next;generation++;}
        }
        durableProgress=new DurableProgress(old.units+completions.size(),generation,scope);
    }
    private synchronized void recordDurable(String id){
        DurableProgress old=durableProgress;String scope=activeScope(id);
        durableProgress=new DurableProgress(old.units+1,old.scopeGeneration+(Objects.equals(old.scope,scope)?0:1),scope);
    }
    public boolean computing(){return !running.isEmpty();}
    /** Wake promptly after durable completion; coalesce notifications to bound memory. */
    public void awaitProgress(long timeoutMillis)throws InterruptedException {
        if(timeoutMillis<0)throw new IllegalArgumentException("Negative wait");
        progress.poll(timeoutMillis,TimeUnit.MILLISECONDS);
    }
    private static <T> T result(Future<T> future)throws Exception {
        try{return future.get();}catch(ExecutionException e){if(e.getCause() instanceof Exception)throw (Exception)e.getCause();throw new IllegalStateException(e.getCause());}
    }
    private static long backoffNanos(int failures,long firstSeconds,long maxSeconds){
        return Math.min(maxSeconds,firstSeconds<<Math.min(5,Math.max(0,failures-1)))*1_000_000_000L;
    }
    private static long networkBackoffNanos(java.io.IOException error,int failures){
        if(error instanceof RetryHint&&((RetryHint)error).status()==429){
            long retry=((RetryHint)error).retryAfterMillis();
            // Never turn a coordinator rate-limit response into a fast retry.
            return Math.max(5_000_000_000L,Math.min(300_000L,Math.max(0,retry))*1_000_000L);
        }
        return backoffNanos(failures,1,30);
    }
    @SuppressWarnings("unchecked") public boolean tick(boolean allowCompute)throws Exception {
        if(closed)throw new IllegalStateException("Pipeline closed");allowNext=allowCompute;long now=System.nanoTime();
        if(fetch!=null&&fetch.isDone()) {
            try{Map<String,Object> response=result(fetch);waitReason=(String)response.get("wait_reason");failedFetches=0;
                if(response.get("block")==null)nextFetch=now+backoffNanos(++emptyFetches,1,16);
                else{
                    emptyFetches=0;nextFetch=now;
                    Object block=response.get("block"),estimate=response.get("estimated_seconds");
                    if(block instanceof Map&&estimate instanceof Number){
                        double seconds=((Number)estimate).doubleValue();Map<?,?> row=(Map<?,?>)block;
                        Object start=row.get("start_unit"),end=row.get("end_unit");
                        if(Double.isFinite(seconds)&&seconds>0&&start instanceof Number&&end instanceof Number){
                            long units=((Number)end).longValue()-((Number)start).longValue();
                            double hint=units/seconds;
                            if(units>0&&Double.isFinite(hint)&&hint>0)fillRateHint=hint;
                        }
                    }
                }
            }
            catch(java.io.IOException e){nextFetch=now+networkBackoffNanos(e,++failedFetches);waitReason=e instanceof RetryHint&&((RetryHint)e).status()==429?"rate_limited":"network";}
            catch(WorkBlockQueue.CapacityException e){nextFetch=now+1_000_000_000L;waitReason="result_storage_full";}
            finally{fetch=null;}
        }
        if(upload!=null&&upload.isDone()) {
            try{double elapsed=result(upload);uploadLatency=Math.max(elapsed,.8*uploadLatency+.2*elapsed);}
            catch(java.io.IOException e){nextUpload=now+5_000_000_000L;waitReason="network";}
            finally{upload=null;}
        }
        if(status!=null&&status.isDone()) {
            try{result(status);}catch(java.io.IOException e){waitReason="network";}
            finally{status=null;nextStatus=now+20_000_000_000L;}
        }
        if(releaseTask!=null&&releaseTask.isDone()){
            try{result(releaseTask);failedReleases=0;nextRelease=now;}
            catch(java.io.IOException e){nextRelease=now+networkBackoffNanos(e,++failedReleases);}
            finally{releaseTask=null;}
        }
        if(status==null&&now>=nextStatus)status=statusReader.submit(()->{transport.refreshStatus();return null;});
        if(releaseTask==null&&now>=nextRelease&&!queue.releasable().isEmpty())
            releaseTask=releaser.submit(()->{transport.releaseReady();return null;});
        long remaining=queue.remaining();
        int pending=queue.pendingCount();
        double reserveRate=rate>0?rate:fillRateHint;
        // The server estimate can be a default on an uncalibrated validator;
        // only measured local throughput closes the initial-fill phase.
        // Only distinct durable completions can close the initial-fill phase.
        boolean refillDue=remaining==0||(reserveRate>0&&(initialFill?remaining/reserveRate<1800:remaining/reserveRate<=600));
        // A full durable outbox cannot consume another reservation. The
        // independent uploader reopens this path after an acknowledgement.
        if(allowCompute&&fetch==null&&now>=nextFetch&&queue.identities().size()<2
                &&pending<queue.capacity()&&refillDue)fetch=fetcher.submit(transport::allocate);
        // Start a grouped upload once the device has produced roughly one
        // request's worth of work. The old capacity-minus-headroom threshold
        // sent tiny groups on a 64-result queue and waited until nearly full
        // on a larger queue. Keep eight slots for in-flight durable writes.
        int uploadTarget=Math.max(8,Math.min(queue.capacity()-8,(int)Math.ceil(uploadLatency*rate*1.15)));
        if(pending>0&&upload==null&&now>=nextUpload&&(pending>=uploadTarget||remaining==0||now>=flushAt)) {
            uploadStarted=now;upload=sender.submit(()->{
                long began=System.nanoTime();transport.upload();
                return Math.max(.001,(System.nanoTime()-began)/1e9);
            });flushAt=now+1_000_000_000L;
        }
        int activeLanes=lanes;
        if(activeLanes>1){
            boolean worked=false;
            for(Iterator<Future<Double>> iterator=running.iterator();iterator.hasNext();){
                Future<Double> task=iterator.next();if(!task.isDone())continue;
                double seconds=result(task);iterator.remove();
                List<Map<String,Object>> done=assignments.remove(task);
                for(Map<String,Object> claim:done){release(claim);claims.remove(claim);}
                rate=rate==0?activeLanes/seconds:.8*rate+.2*activeLanes/seconds;observeInitialFill();worked=true;
            }
            synchronized(writes){
                for(Iterator<Future<?>> it=writes.iterator();it.hasNext();){
                    Future<?> write=it.next();if(write.isDone()){result(write);it.remove();}
                }
            }
            if(requestedCpuLanes!=0){applyCpuTransition();return worked;}
            if(!allowCompute)return worked;
            if(running.size()<activeLanes){
                int available=activeLanes-running.size();
                // One snapshot/size pass; retain the same round-robin window and bounds.
                List<List<Map<String,Object>>> assigned=queue.claimWindow(activeLanes,available,Math.min(4,8/activeLanes));
                for(List<Map<String,Object>> batch:assigned){for(Map<String,Object> claim:batch)rememberScope(claim);claims.addAll(batch);}
                for(List<Map<String,Object>> batch:assigned){
                    if(batch.isEmpty())continue;
                    Future<Double> task=solvers.submit(()->{
                        double seconds=0;int count=0;
                        List<Future<?>> persisted=new ArrayList<>();
                        if(compute instanceof BatchCompute){
                            if(closed||!allowNext||Thread.currentThread().isInterrupted())return .000001;
                            List<Map<String,Object>> envelopes=new ArrayList<>();
                            for(Map<String,Object> current:batch)envelopes.add((Map<String,Object>)current.get("envelope"));
                            final int[] received={0};final double[] elapsed={0};
                            List<WorkBlockQueue.Completion> pair=new ArrayList<>();
                            try{((BatchCompute)compute).runBatch(envelopes,(index,receipt,duration)->{
                                if(index!=received[0]||index>=batch.size()||!Double.isFinite(duration)||duration<=0)throw new IllegalStateException("Invalid cohort completion");
                                Map<String,Object> current=batch.get(index),envelope=envelopes.get(index);
                                pair.add(new WorkBlockQueue.Completion((String)current.get("block_id"),((Number)envelope.get("start_unit")).longValue(),receipt,duration));
                                if(pair.size()==2){Future<?> durable=persist(pair);writes.add(durable);persisted.add(durable);pair.clear();}
                                received[0]++;elapsed[0]+=duration;
                            });}finally{
                                if(!pair.isEmpty()){Future<?> durable=persist(pair);writes.add(durable);persisted.add(durable);}
                            }
                            if(received[0]!=batch.size()&&!closed&&!Thread.currentThread().isInterrupted())throw new IllegalStateException("Incomplete cohort");
                            for(Future<?> durable:persisted)result(durable);
                            return Math.max(.000001,elapsed[0]/Math.max(1,received[0]));
                        }
                        List<WorkBlockQueue.Completion> pair=new ArrayList<>();
                        try{for(Map<String,Object> current:batch){
                            if(closed||!allowNext||Thread.currentThread().isInterrupted())break;
                            // Observe failures before starting more work. The next
                            // pre-reserved job may overlap a still-running save.
                            for(Future<?> done:persisted)if(done.isDone())result(done);
                            Map<String,Object> envelope=(Map<String,Object>)current.get("envelope");
                            long began=System.nanoTime();Map<String,Object> receipt=compute.run(envelope);
                            double elapsed=Math.max(.000001,(System.nanoTime()-began)/1e9);
                            WorkBlockQueue.Completion completion=new WorkBlockQueue.Completion(
                                (String)current.get("block_id"),((Number)envelope.get("start_unit")).longValue(),receipt,elapsed);
                            pair.add(completion);seconds+=elapsed;count++;
                            if(pair.size()==2){Future<?> durable=persist(pair);writes.add(durable);persisted.add(durable);pair.clear();}
                        }}finally{
                            // A failed/cancelled second job cannot discard the first receipt.
                            if(!pair.isEmpty()){Future<?> durable=persist(pair);writes.add(durable);persisted.add(durable);}
                        }
                        for(Future<?> durable:persisted)result(durable);
                        return Math.max(.000001,seconds/Math.max(1,count));
                    });
                    running.add(task);assignments.put(task,batch);
                }
            }
            return worked;
        }
        if(requestedCpuLanes!=0){applyCpuTransition();return false;}
        if(!allowCompute)return false;
        Map<String,Object> current=queue.claimNext();if(current==null)return false;
        rememberScope(current);
        try{
        Map<String,Object> envelope=(Map<String,Object>)current.get("envelope");long began=System.nanoTime();
        Map<String,Object> receipt=compute.run(envelope);double seconds=Math.max(.000001,(System.nanoTime()-began)/1e9);
        queue.complete((String)current.get("block_id"),((Number)envelope.get("start_unit")).longValue(),receipt,seconds);
        recordDurable((String)current.get("block_id"));
        rate=rate==0?1/seconds:.8*rate+.2/seconds;observeInitialFill();return true;
        }finally{try{queue.releaseClaim();}finally{forgetScope((String)current.get("block_id"));}}
    }
    private Future<?> persist(List<WorkBlockQueue.Completion> completions){
        if(completions.isEmpty()||completions.size()>2)throw new IllegalArgumentException("Persistence pair");
        Write write=new Write(completions);
        if(!waitingWrites.offer(write))throw new IllegalStateException("Bounded writer reservations exceeded");
        writer.execute(()->{
            List<Write> batch=new ArrayList<>();List<WorkBlockQueue.Completion> values=new ArrayList<>();
            // Never split a lane's pair or exceed the existing four-receipt commit.
            while(true){Write item=waitingWrites.peek();if(item==null||values.size()+item.completions.size()>4)break;
                waitingWrites.remove();batch.add(item);values.addAll(item.completions);}
            if(batch.isEmpty())return;
            try{
                queue.completeBatch(values);
                recordDurable(values);
                for(Write item:batch)item.durable.complete(null);
                progress.offer(Boolean.TRUE);
            }catch(Throwable failure){for(Write item:batch)item.durable.completeExceptionally(failure);}
        });
        return write.durable;
    }
    private void release(Map<String,Object> claim){
        Map<?,?> envelope=(Map<?,?>)claim.get("envelope");
        String id=(String)claim.get("block_id");
        try{queue.releaseClaim(id,((Number)envelope.get("start_unit")).longValue());}
        finally{forgetScope(id);}
    }
    public void close() {
        closed=true;transport.stop();
        for(Future<?> task:running)task.cancel(true);solvers.shutdownNow();
        // A late HTTP response cannot mutate the durable queue after stop,
        // even when the platform socket ignores thread interruption.
        for(ExecutorService executor:Arrays.asList(fetcher,sender,statusReader,releaser))executor.shutdownNow();
        boolean interrupted=Thread.interrupted();
        try {
            {
                try{
                    if(!solvers.awaitTermination(8,TimeUnit.SECONDS))throw new IllegalStateException("Block solvers did not stop; durable queue retained");
                    // Completed receipts are never cancelled with the solvers.
                    // Drain durable writes before releasing any reservations.
                    writer.shutdown();
                    if(!writer.awaitTermination(8,TimeUnit.SECONDS))throw new IllegalStateException("Block writer did not stop; uncommitted receipts remain in memory and durable cursor permits replay");
                    for(Future<?> write:writes){
                        try{result(write);}catch(Exception failure){throw new IllegalStateException("Block receipt persistence failed; cursor retained for replay",failure);}
                    }
                    for(Map<String,Object> claim:claims)release(claim);
                    claims.clear();running.clear();assignments.clear();writes.clear();
                }
                catch(InterruptedException stop){interrupted=true;throw new IllegalStateException("Interrupted while stopping block solvers",stop);}
            }
            for(ExecutorService executor:Arrays.asList(fetcher,sender,statusReader,releaser)) {
                try{executor.awaitTermination(1,TimeUnit.SECONDS);}
                catch(InterruptedException stop){interrupted=true;}
            }
        } finally {writer.shutdown();if(interrupted)Thread.currentThread().interrupt();}
    }
}
