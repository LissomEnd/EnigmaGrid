import java.lang.reflect.Field;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.enigmagrid.core.*;
import static org.enigmagrid.core.Canonical.object;

/** Focused host check for the staged Android v2 initial fill. */
public final class WorkBlockInitialFillChecks {
    static void check(boolean value){if(!value)throw new AssertionError();}
    static Map<String,Object> block(String id){return object(
        "format",WorkBlock.FORMAT,"block_id",id,"engine","bounded_crib_v1",
        "start_unit",0,"end_unit",1000,
        "config",object("requires",Arrays.asList("cpu","bounded_crib_v1"),"program",object(
            "ciphertext","BDZGO","hypotheses",Arrays.asList(object("text","BD","legal_clean_offsets",Arrays.asList(0))),
            "chunk",3,"ordinal_base",0,"candidate_limit",3)));
    }
    static void rate(WorkBlockPipeline pipeline,double value)throws Exception {
        Field field=WorkBlockPipeline.class.getDeclaredField("rate");field.setAccessible(true);field.setDouble(pipeline,value);
    }
    static boolean initial(WorkBlockPipeline pipeline)throws Exception {
        Field field=WorkBlockPipeline.class.getDeclaredField("initialFill");field.setAccessible(true);return field.getBoolean(pipeline);
    }
    static void observe(WorkBlockPipeline pipeline)throws Exception {
        java.lang.reflect.Method method=WorkBlockPipeline.class.getDeclaredMethod("observeInitialFill");
        method.setAccessible(true);method.invoke(pipeline);
    }
    static void scenario(boolean twoBlocks,double measuredRate,boolean expectFetch)throws Exception {
        WorkBlockQueueChecks.Store store=new WorkBlockQueueChecks.Store();
        WorkBlockQueue queue=new WorkBlockQueue(store,"server","owner",true);
        queue.allocated(queue.allocationRequest(),block("first"));
        if(twoBlocks)queue.allocated(queue.allocationRequest(),block("second"));
        Map<String,Map<String,Object>> live=new HashMap<>();
        for(String id:queue.identities())live.put(id,object("status","reserved","valid_for_seconds",7200));
        queue.updateStatus(live);
        AtomicInteger requests=new AtomicInteger();CountDownLatch computeGate=new CountDownLatch(1);
        WorkBlockTransport link=new WorkBlockTransport(queue,(path,body)->{
            if(path.endsWith("/status")){
                List<Object> rows=new ArrayList<>();
                for(Object id:(List<?>)body.get("blocks"))rows.add(object("block_id",id,"status","reserved","valid_for_seconds",7200));
                return object("blocks",rows);
            }
            check(path.equals("/api/work-blocks"));requests.incrementAndGet();
            return object("block",null,"wait_reason","no_compatible_work","retry_after_seconds",10);
        },true);
        WorkBlockPipeline pipeline=new WorkBlockPipeline(queue,link,envelope->{
            computeGate.await(2,TimeUnit.SECONDS);return object("fixture",true);
        },2);
        rate(pipeline,measuredRate);
        try{
            check(!pipeline.tick(false)&&requests.get()==0); // A paused client never fills.
            pipeline.tick(true);
            if(expectFetch){
                long until=System.nanoTime()+1_000_000_000L;
                while(requests.get()==0&&System.nanoTime()<until)Thread.sleep(1);
                check(requests.get()==1);
            }else{Thread.sleep(40);check(requests.get()==0);}
            check(initial(pipeline)); // No durable completion has been observed.
        }finally{computeGate.countDown();pipeline.close();}
    }
    static void normalRefillAfterTarget()throws Exception {
        WorkBlockQueueChecks.Store store=new WorkBlockQueueChecks.Store();
        WorkBlockQueue queue=new WorkBlockQueue(store,"server","owner",true);
        queue.allocated(queue.allocationRequest(),block("first"));
        queue.updateStatus(Collections.singletonMap("first",object("status","reserved","valid_for_seconds",7200)));
        AtomicInteger calls=new AtomicInteger();CountDownLatch computeGate=new CountDownLatch(1);
        WorkBlockTransport link=new WorkBlockTransport(queue,(path,body)->{
            if(path.endsWith("/status"))return object("blocks",Arrays.asList(object("block_id","first","status","reserved","valid_for_seconds",7200)));
            check(path.equals("/api/work-blocks"));calls.incrementAndGet();
            return object("block",null,"wait_reason","no_compatible_work","retry_after_seconds",10);
        },true);
        WorkBlockPipeline pipeline=new WorkBlockPipeline(queue,link,envelope->{computeGate.await(2,TimeUnit.SECONDS);return object("fixture",true);},2);
        try{
            rate(pipeline,.5);for(int i=0;i<3;i++)observe(pipeline);
            pipeline.tick(true);check(!initial(pipeline)&&calls.get()==0);
            rate(pipeline,.56);observe(pipeline);pipeline.tick(true);
            check(!initial(pipeline)&&calls.get()==0); // 1786 s, comparable +12%.
            // An already latched, comparable-rate profile eventually reaches
            // the ordinary 600-second threshold as its cursor advances.
            Field latch=WorkBlockPipeline.class.getDeclaredField("initialFillLatchRate");latch.setAccessible(true);
            latch.setDouble(pipeline,2.0);
            rate(pipeline,2.0);pipeline.tick(true); // 500 s: normal refill due.
            long until=System.nanoTime()+1_000_000_000L;
            while(calls.get()==0&&System.nanoTime()<until)Thread.sleep(1);
            check(calls.get()==1);
        }finally{computeGate.countDown();pipeline.close();}
    }
    static void rearmAfterStableSlowThenFast()throws Exception {
        WorkBlockQueueChecks.Store store=new WorkBlockQueueChecks.Store();
        WorkBlockQueue queue=new WorkBlockQueue(store,"server","owner",true);
        queue.allocated(queue.allocationRequest(),block("first"));
        queue.updateStatus(Collections.singletonMap("first",object("status","reserved","valid_for_seconds",7200)));
        AtomicInteger calls=new AtomicInteger();CountDownLatch computeGate=new CountDownLatch(1);
        WorkBlockTransport link=new WorkBlockTransport(queue,(path,body)->{
            if(path.endsWith("/status"))return object("blocks",Arrays.asList(object("block_id","first","status","reserved","valid_for_seconds",7200)));
            check(path.equals("/api/work-blocks"));calls.incrementAndGet();
            return object("block",null,"wait_reason","no_compatible_work");
        },true);
        WorkBlockPipeline pipeline=new WorkBlockPipeline(queue,link,envelope->{computeGate.await(2,TimeUnit.SECONDS);return object("fixture",true);},2);
        try{
            rate(pipeline,.5);for(int i=0;i<3;i++)observe(pipeline);
            check(!initial(pipeline));
            rate(pipeline,.56);observe(pipeline);pipeline.tick(true);
            check(!initial(pipeline)&&calls.get()==0); // Comparable rate retains 600 s.
            rate(pipeline,1.0);observe(pipeline);pipeline.tick(true);
            long until=System.nanoTime()+1_000_000_000L;
            while(calls.get()==0&&System.nanoTime()<until)Thread.sleep(1);
            check(initial(pipeline)&&calls.get()==1); // 1000 s now re-arms 1800 s.
        }finally{computeGate.countDown();pipeline.close();}
    }
    static void changingRateDoesNotCloseOnOneSlowJob()throws Exception {
        WorkBlockQueueChecks.Store store=new WorkBlockQueueChecks.Store();
        WorkBlockQueue queue=new WorkBlockQueue(store,"server","owner",true);
        queue.allocated(queue.allocationRequest(),block("first"));
        queue.updateStatus(Collections.singletonMap("first",object("status","reserved","valid_for_seconds",7200)));
        AtomicInteger calls=new AtomicInteger();CountDownLatch computeGate=new CountDownLatch(1);
        WorkBlockTransport link=new WorkBlockTransport(queue,(path,body)->{
            if(path.endsWith("/status"))return object("blocks",Arrays.asList(object("block_id","first","status","reserved","valid_for_seconds",7200)));
            check(path.equals("/api/work-blocks"));calls.incrementAndGet();
            return object("block",null,"wait_reason","no_compatible_work");
        },true);
        WorkBlockPipeline pipeline=new WorkBlockPipeline(queue,link,envelope->{computeGate.await(2,TimeUnit.SECONDS);return object("fixture",true);},2);
        try{
            rate(pipeline,.5);observe(pipeline);check(initial(pipeline));
            rate(pipeline,1.0);observe(pipeline);pipeline.tick(true);
            long until=System.nanoTime()+1_000_000_000L;
            while(calls.get()==0&&System.nanoTime()<until)Thread.sleep(1);
            check(calls.get()==1&&initial(pipeline));
        }finally{computeGate.countDown();pipeline.close();}
    }
    static void fullOutboxDoesNotReserve()throws Exception {
        WorkBlockQueueChecks.Store store=new WorkBlockQueueChecks.Store();
        WorkBlockQueue queue=new WorkBlockQueue(store,"server","owner",false);
        queue.allocated(queue.allocationRequest(),block("first"));
        queue.updateStatus(Collections.singletonMap("first",object("status","reserved","valid_for_seconds",7200)));
        for(int unit=0;unit<queue.capacity();unit++)queue.complete("first",unit,object("fixture",unit),.1);
        check(queue.pendingCount()==queue.capacity());
        AtomicInteger calls=new AtomicInteger();
        WorkBlockTransport link=new WorkBlockTransport(queue,(path,body)->{
            if(path.endsWith("/status"))return object("blocks",Arrays.asList(object("block_id","first","status","reserved","valid_for_seconds",7200)));
            if(path.equals("/api/work-blocks")){calls.incrementAndGet();return object("block",null);}
            throw new AssertionError("Unexpected HTTP request "+path);
        },false);
        WorkBlockPipeline pipeline=new WorkBlockPipeline(queue,link,envelope->{throw new AssertionError("Full outbox computed");},2);
        Field uploadAt=WorkBlockPipeline.class.getDeclaredField("nextUpload");uploadAt.setAccessible(true);
        uploadAt.setLong(pipeline,System.nanoTime()+60_000_000_000L);
        rate(pipeline,1.0);
        try{pipeline.tick(true);Thread.sleep(40);check(calls.get()==0);}
        finally{pipeline.close();}
    }
    static void serverEstimateBeforeFirstCompute()throws Exception {
        WorkBlockQueueChecks.Store store=new WorkBlockQueueChecks.Store();
        WorkBlockQueue queue=new WorkBlockQueue(store,"server","owner",true);
        AtomicInteger calls=new AtomicInteger();CountDownLatch computeGate=new CountDownLatch(1);
        WorkBlockTransport link=new WorkBlockTransport(queue,(path,body)->{
            if(path.endsWith("/status")){
                List<Object> rows=new ArrayList<>();
                for(Object id:(List<?>)body.get("blocks"))rows.add(object("block_id",id,"status","reserved","valid_for_seconds",7200));
                return object("blocks",rows);
            }
            check(path.equals("/api/work-blocks"));
            if(calls.incrementAndGet()==1)return object("status","reserved","block",block("first"),
                "estimated_seconds",1000,"valid_for_seconds",7200);
            return object("block",null,"wait_reason","no_compatible_work","retry_after_seconds",10);
        },true);
        WorkBlockPipeline pipeline=new WorkBlockPipeline(queue,link,envelope->{computeGate.await(2,TimeUnit.SECONDS);return object("fixture",true);},2);
        try{
            pipeline.tick(true);
            long until=System.nanoTime()+1_000_000_000L;
            while(calls.get()<2&&System.nanoTime()<until){pipeline.tick(true);Thread.sleep(1);}
            check(calls.get()==2); // The 1000 s server estimate triggered initial fill.
            Field measured=WorkBlockPipeline.class.getDeclaredField("rate");measured.setAccessible(true);
            check(measured.getDouble(pipeline)==0); // No computed unit was required.
        }finally{computeGate.countDown();pipeline.close();}
    }
    public static void main(String[] args)throws Exception {
        scenario(false,1.0,true);  // One 1000-unit block gives <1800 s.
        scenario(false,.5,false);  // At 2000 s the initial target is already met.
        scenario(true,1.0,false);  // No third reservation while two blocks are held.
        normalRefillAfterTarget();rearmAfterStableSlowThenFast();changingRateDoesNotCloseOnOneSlowJob();fullOutboxDoesNotReserve();serverEstimateBeforeFirstCompute();
        System.out.println("PASS staged Android initial fill, 600s refill, pause, two-block and outbox bounds");
    }
}
