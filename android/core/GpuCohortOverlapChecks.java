import java.io.IOException;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.enigmagrid.core.*;

/** Host-only, already-claimed four-job overlap proof; no Android/device calls. */
public final class GpuCohortOverlapChecks {
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    @SuppressWarnings("unchecked") private static List<Map<String,Object>> distinctJobs(){
        List<Map<String,Object>> jobs=GpuCohortChecks.jobs(4,5);
        for(int i=0;i<jobs.size();i++){
            Map<String,Object> config=(Map<String,Object>)jobs.get(i).get("config");
            Map<String,Object> job=(Map<String,Object>)config.get("job");
            job.put("pairs",i);
        }
        return jobs;
    }
    private static String key(int[] packed){return packed.length+"/"+Arrays.hashCode(packed);}
    private static final class FakeGpu implements BatchedSolver.Dispatch {
        final Map<String,int[]> response;
        final AtomicInteger active=new AtomicInteger(),maximum=new AtomicInteger(),calls=new AtomicInteger();
        final CountDownLatch entered=new CountDownLatch(1);
        final long sleepMs;
        FakeGpu(Map<String,int[]> response,long sleepMs){this.response=response;this.sleepMs=sleepMs;}
        @Override public int[] run(int[] packed){
            int now=active.incrementAndGet();maximum.accumulateAndGet(now,Math::max);calls.incrementAndGet();entered.countDown();
            try{Thread.sleep(sleepMs);int[] answer=response.get(key(packed));check(answer!=null,"Foreign dispatch");return answer;}
            catch(InterruptedException cancelled){Thread.currentThread().interrupt();throw new CancellationException();}
            finally{active.decrementAndGet();}
        }
    }
    public static void main(String[] args)throws Exception {
        List<Map<String,Object>> jobs=distinctJobs();List<String> originals=new ArrayList<>();
        for(Map<String,Object> job:jobs)originals.add(Canonical.json(job));
        Map<String,int[]> cached=new HashMap<>();List<String> expected=new ArrayList<>();
        BatchedSolver.Dispatch reference=GpuCohortChecks.dispatch(jobs,new ArrayList<>());
        GpuWorkCohort.run(jobs,packed->{int[] response=reference.run(packed);cached.put(key(packed),response);return response;},
            ()->false,8,(i,r,s)->{check(i==expected.size(),"Warm-up order");expected.add(Canonical.json(r));});
        check(cached.size()==4,"Expected four independent hypotheses, not a widened packet");

        FakeGpu fake=new FakeGpu(cached,22);List<String> actual=new ArrayList<>();
        long start=System.nanoTime();
        GpuWorkCohort.run(jobs,fake,()->false,8,(i,r,s)->{
            check(i==actual.size(),"Receipt order");actual.add(Canonical.json(r));
            check(Double.isFinite(s)&&s>0,"Compute seconds");
            Thread.sleep(16); // controlled durable-callback/write cost
        });
        long wallMs=TimeUnit.NANOSECONDS.toMillis(System.nanoTime()-start);
        check(expected.equals(actual),"Canonical receipts changed");
        check(fake.calls.get()==4&&fake.maximum.get()==1,"Two GPU RPCs or missing dispatch");
        for(int i=0;i<jobs.size();i++)check(originals.get(i).equals(Canonical.json(jobs.get(i))),"Envelope mutated");
        System.out.println("FOUR_JOB_WALL_MS="+wallMs+" GPU_CALLS="+fake.calls.get()+" MAX_CONCURRENT_GPU="+fake.maximum.get());
        if(args.length>0&&"bench".equals(args[0]))return;

        // Cancellation during a blocked dispatch must return promptly and
        // leave the single process-wide GPU lane reusable.
        FakeGpu blocking=new FakeGpu(cached,5000);AtomicBoolean cancel=new AtomicBoolean();
        Thread timer=new Thread(()->{try{blocking.entered.await(2,TimeUnit.SECONDS);Thread.sleep(40);}catch(InterruptedException e){Thread.currentThread().interrupt();}cancel.set(true);});
        timer.start();start=System.nanoTime();
        try{GpuWorkCohort.run(jobs,blocking,cancel::get,8,(i,r,s)->{});throw new AssertionError("Cancellation ignored");}
        catch(CancellationException expectedCancel){}
        timer.join(1000);long cancelMs=TimeUnit.NANOSECONDS.toMillis(System.nanoTime()-start);
        check(cancelMs<750,"Cancellation waited on slow GPU RPC: "+cancelMs);
        for(int i=0;i<30&&blocking.active.get()!=0;i++)Thread.sleep(10);
        check(blocking.active.get()==0&&blocking.maximum.get()==1,"Cancelled GPU RPC still running or overlapped");

        FakeGpu afterCancel=new FakeGpu(cached,1);AtomicInteger callbacks=new AtomicInteger();
        GpuWorkCohort.run(jobs,afterCancel,()->false,8,(i,r,s)->callbacks.incrementAndGet());
        check(callbacks.get()==4&&afterCancel.maximum.get()==1,"GPU lane not reusable after cancellation");

        // A durable-receipt callback failure must stop ordered delivery and
        // cancel the already-prefetched request. No extra claim is made here.
        FakeGpu outboxFailure=new FakeGpu(cached,80);AtomicInteger failuresSeen=new AtomicInteger();
        try{GpuWorkCohort.run(jobs,outboxFailure,()->false,8,(i,r,s)->{
            failuresSeen.incrementAndGet();throw new IOException("synthetic durable outbox failure");
        });throw new AssertionError("Outbox failure swallowed");}
        catch(IOException expectedFailure){}
        for(int i=0;i<30&&outboxFailure.active.get()!=0;i++)Thread.sleep(10);
        check(failuresSeen.get()==1&&outboxFailure.active.get()==0&&outboxFailure.maximum.get()==1,
            "Failed callback leaked work or delivered later receipt");
        AtomicInteger timeoutCallbacks=new AtomicInteger();
        try{GpuWorkCohort.run(jobs,packed->{throw new IllegalStateException("synthetic GPU timeout");},
            ()->false,8,(i,r,s)->timeoutCallbacks.incrementAndGet());
            throw new AssertionError("GPU timeout swallowed");
        }catch(IllegalStateException timeout){check(timeout.getMessage().contains("GPU timeout"),"Wrong timeout failure");}
        check(timeoutCallbacks.get()==0,"Receipt delivered after GPU timeout");
        int dispatchThreads=0;
        for(Thread thread:Thread.getAllStackTraces().keySet())if(thread.isAlive()&&"cohort-gpu-dispatch".equals(thread.getName()))dispatchThreads++;
        check(dispatchThreads==1,"Dispatch thread leaked or duplicated: "+dispatchThreads);
        FakeGpu concurrent=new FakeGpu(cached,30);ExecutorService cohorts=Executors.newFixedThreadPool(2);
        CountDownLatch startBoth=new CountDownLatch(1);List<Future<List<String>>> concurrentReceipts=new ArrayList<>();
        try{
            for(int caller=0;caller<2;caller++)concurrentReceipts.add(cohorts.submit(()->{
                startBoth.await();List<String> values=new ArrayList<>();
                GpuWorkCohort.run(jobs,concurrent,()->false,8,(i,r,s)->{
                    check(i==values.size(),"Concurrent cohort receipt order");values.add(Canonical.json(r));
                });return values;
            }));
            startBoth.countDown();
            for(Future<List<String>> values:concurrentReceipts)
                check(expected.equals(values.get(10,TimeUnit.SECONDS)),"Concurrent production/qualification parity");
            check(concurrent.calls.get()==8&&concurrent.maximum.get()==1,
                "Concurrent cohorts sent two GPU RPCs or lost a group");
        }finally{cohorts.shutdownNow();}
        System.out.println("PASS exact receipts/order, no second GPU RPC, cancellation "+cancelMs+"ms, outbox-failure cleanup");
    }
}
