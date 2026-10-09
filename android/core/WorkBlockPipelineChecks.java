import java.util.*;
import java.util.concurrent.*;
import org.enigmagrid.core.*;
import static org.enigmagrid.core.Canonical.object;
public class WorkBlockPipelineChecks {
    static void check(boolean v){if(!v)throw new AssertionError();}
    static final class RateLimited extends java.io.IOException implements WorkBlockPipeline.RetryHint {
        public int status(){return 429;}
        public long retryAfterMillis(){return 7000;}
    }
    static Map<String,Object> block(String id,int end){return object(
        "format",WorkBlock.FORMAT,"block_id",id,"engine","bounded_crib_v1","start_unit",0,"end_unit",end,
        "config",object("requires",Arrays.asList("cpu","bounded_crib_v1"),"program",object("ciphertext","BDZGO",
            "hypotheses",Arrays.asList(object("text","BD","legal_clean_offsets",Arrays.asList(0))),
            "chunk",3,"ordinal_base",0,"candidate_limit",3)));
    }
    /** Slow idempotent release must leave upload and subsequent refill free. */
    static void slowReleaseOverlap()throws Exception {
        WorkBlockQueueChecks.Store store=new WorkBlockQueueChecks.Store();
        WorkBlockQueue queue=new WorkBlockQueue(store,"server","owner",true);
        queue.allocated(queue.allocationRequest(),block("old",1));
        queue.allocated(queue.allocationRequest(),block("working",5));
        Map<String,Map<String,Object>> live=new HashMap<>();
        for(String id:queue.identities())live.put(id,object("status","reserved","valid_for_seconds",600));
        queue.updateStatus(live);
        queue.complete("old",0,object("fixture",0),.05);
        queue.complete("working",0,object("fixture",0),.05);
        CountDownLatch releaseEntered=new CountDownLatch(1),releaseGate=new CountDownLatch(1);
        CountDownLatch uploadWorking=new CountDownLatch(1),refilled=new CountDownLatch(1);
        WorkBlockTransport transport=new WorkBlockTransport(queue,(path,body)->{
            if(path.endsWith("/status")){
                List<Object> rows=new ArrayList<>();
                for(Object id:(List<?>)body.get("blocks"))rows.add(object("block_id",id,"status","reserved","valid_for_seconds",600));
                return object("blocks",rows);
            }
            if(path.endsWith("/release")){
                check("old".equals(body.get("block_id")));releaseEntered.countDown();
                check(releaseGate.await(3,TimeUnit.SECONDS));
                return object("block_id","old","released",true);
            }
            if(path.endsWith("/result-groups")){
                String id=(String)body.get("block_id");
                List<Object> ack=new ArrayList<>();
                for(Object group:(List<?>)body.get("groups"))for(Object row:(List<?>)group)
                    ack.add(object("unit",((Map<?,?>)row).get("unit"),"status","received"));
                if("working".equals(id))uploadWorking.countDown();
                return object("block_id",id,"results",ack);
            }
            check(path.equals("/api/work-blocks"));refilled.countDown();
            return object("status","reserved","block",block("next",5),"valid_for_seconds",600);
        },true);
        check(transport.upload()==1); // old receipt acked; descriptor remains until release ack.
        check(queue.releasable().equals(Arrays.asList("old")));
        WorkBlockPipeline pipeline=new WorkBlockPipeline(queue,transport,envelope->object("fixture",true),2);
        java.lang.reflect.Field rate=WorkBlockPipeline.class.getDeclaredField("rate");
        rate.setAccessible(true);rate.setDouble(pipeline,1.0);
        try{
            pipeline.tick(true);check(releaseEntered.await(2,TimeUnit.SECONDS));
            long limit=System.nanoTime()+2_000_000_000L;
            while(uploadWorking.getCount()>0&&System.nanoTime()<limit){pipeline.tick(true);Thread.sleep(1);}
            check(uploadWorking.getCount()==0); // Upload used its own client while release waited.
            check(refilled.getCount()==1); // At most two local reservations until release ack.
            releaseGate.countDown();
            limit=System.nanoTime()+2_000_000_000L;
            while(refilled.getCount()>0&&System.nanoTime()<limit){pipeline.tick(true);Thread.sleep(1);}
            check(refilled.getCount()==0&&queue.identities().size()<=2);
        }finally{releaseGate.countDown();pipeline.close();}
        WorkBlockQueue restarted=new WorkBlockQueue(store,"server","owner",true);
        check(restarted.identities().contains("next"));
    }
    static void allocationRateLimit()throws Exception {
        WorkBlockQueueChecks.Store store=new WorkBlockQueueChecks.Store();
        WorkBlockQueue queue=new WorkBlockQueue(store,"server","owner",true);
        List<String> ids=Collections.synchronizedList(new ArrayList<>());
        WorkBlockTransport transport=new WorkBlockTransport(queue,(path,body)->{
            if(path.endsWith("/status"))return object("blocks",Collections.emptyList());
            check(path.equals("/api/work-blocks"));ids.add((String)body.get("request_id"));throw new RateLimited();
        },true);
        WorkBlockPipeline pipeline=new WorkBlockPipeline(queue,transport,envelope->{throw new AssertionError("No block");});
        try{
            long began=System.nanoTime();pipeline.tick(true);
            long limit=began+2_000_000_000L;
            while(!"rate_limited".equals(pipeline.waitReason())&&System.nanoTime()<limit){pipeline.tick(true);Thread.sleep(1);}
            check("rate_limited".equals(pipeline.waitReason())&&ids.size()==1);
            java.lang.reflect.Field next=WorkBlockPipeline.class.getDeclaredField("nextFetch");next.setAccessible(true);
            check(next.getLong(pipeline)-System.nanoTime()>6_000_000_000L);
            check(ids.get(0).equals(queue.allocationRequest())); // Idempotent retry identity retained.
        }finally{pipeline.close();}
    }
    static void persistenceOverlap(boolean grouped,int failure)throws Exception {
        CountDownLatch saving=new CountDownLatch(1),releaseSave=new CountDownLatch(1),computed=new CountDownLatch(8);
        WorkBlockQueueChecks.Store store=new WorkBlockQueueChecks.Store(){
            public void save(Map<String,Object> state)throws Exception {
                if(!((List<?>)state.get("pending")).isEmpty()){
                    saving.countDown();check(releaseSave.await(5,TimeUnit.SECONDS));
                    if(failure==2)throw new AssertionError("Injected fatal durable writer failure");
                    if(failure==1)throw new java.io.IOException("Injected durable writer failure");
                }
                super.save(state);
            }
        };
        WorkBlockQueue queue=new WorkBlockQueue(store,"server","owner",grouped);
        for(String id:Arrays.asList("current","next"))queue.allocated(queue.allocationRequest(),object(
            "format",WorkBlock.FORMAT,"block_id",id,"engine","bounded_crib_v1","start_unit",0,"end_unit",1000,
            "config",object("requires",Arrays.asList("cpu","bounded_crib_v1"),"program",object("ciphertext","BDZGO",
                "hypotheses",Arrays.asList(object("text","BD","legal_clean_offsets",Arrays.asList(0))),"chunk",3,"ordinal_base",0,"candidate_limit",3))));
        Map<String,Map<String,Object>> live=new HashMap<>();for(String id:queue.identities())live.put(id,object("status","reserved","valid_for_seconds",600));queue.updateStatus(live);
        WorkBlockTransport link=new WorkBlockTransport(queue,(path,body)->{
            check(path.endsWith("/status"));List<Object> rows=new ArrayList<>();
            for(Object id:(List<?>)body.get("blocks"))rows.add(object("block_id",id,"status","reserved","valid_for_seconds",600));return object("blocks",rows);
        },grouped);
        Set<Long> unique=ConcurrentHashMap.newKeySet();
        WorkBlockPipeline pipeline=new WorkBlockPipeline(queue,link,envelope->{
            long unit=((Number)envelope.get("start_unit")).longValue();check(unique.add(unit));
            if(unit==1||unit>=4)check(saving.await(2,TimeUnit.SECONDS));
            computed.countDown();return object("fixture",unit);
        },2);
        ExecutorService closer=Executors.newSingleThreadExecutor();
        try{
            pipeline.tick(true);check(saving.await(2,TimeUnit.SECONDS));
            check(computed.await(2,TimeUnit.SECONDS)); // All eight computed while first durable write is blocked.
            check(unique.size()==8);check(((List<?>)store.state.get("pending")).isEmpty());
            Future<?> stopped=closer.submit(pipeline::close);
            Thread.sleep(30);check(!stopped.isDone());releaseSave.countDown();
            try{stopped.get(3,TimeUnit.SECONDS);check(failure==0);}catch(ExecutionException expected){if(failure==0||!(expected.getCause() instanceof IllegalStateException))throw new AssertionError("Unexpected close failure",expected);}
            WorkBlockQueue restarted=new WorkBlockQueue(store,"server","owner",grouped);
            check(restarted.pendingCount()==(failure!=0?0:8));Set<Long> units=new HashSet<>();for(Map<String,Object> row:restarted.pending())check(units.add(((Number)row.get("unit")).longValue()));
            restarted.updateStatus(live);if(grouped||failure!=0)check(((Number)((Map<?,?>)restarted.claimNext().get("envelope")).get("start_unit")).longValue()==(failure!=0?0:8));else check(restarted.claimNext()==null);
        }finally{releaseSave.countDown();try{pipeline.close();}catch(IllegalStateException expected){if(failure==0)throw expected;}finally{closer.shutdownNow();}}
    }
    public static void main(String[] args)throws Exception {
        slowReleaseOverlap();allocationRateLimit();
        persistenceOverlap(false,0);persistenceOverlap(true,0);persistenceOverlap(true,1);persistenceOverlap(true,2);
        WorkBlockQueueChecks.Store storage=new WorkBlockQueueChecks.Store();
        WorkBlockQueue q=new WorkBlockQueue(storage,"server","owner",true);
        for(String id:Arrays.asList("current","next")) {
            Map<String,Object> b=object("format",WorkBlock.FORMAT,"block_id",id,"engine","bounded_crib_v1","start_unit",0,"end_unit",1000,
                "config",object("requires",Arrays.asList("cpu","bounded_crib_v1"),"program",object("ciphertext","BDZGO","hypotheses",Arrays.asList(object("text","BD","legal_clean_offsets",Arrays.asList(0))),"chunk",3,"ordinal_base",0,"candidate_limit",3)));
            q.allocated(q.allocationRequest(),b);
        }
        Map<String,Map<String,Object>> states=new HashMap<>();for(String id:q.identities())states.put(id,object("status","reserved","valid_for_seconds",600));q.updateStatus(states);
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        Set<Long> computed=new HashSet<>();
        WorkBlockTransport transport=new WorkBlockTransport(q,(path,body)->{
            if(path.endsWith("/status")) {
                List<Object> rows=new ArrayList<>();for(Object id:(List<?>)body.get("blocks"))rows.add(object("block_id",id,"status","reserved","valid_for_seconds",600));return object("blocks",rows);
            }
            check(path.endsWith("/result-groups"));entered.countDown();check(release.await(5,TimeUnit.SECONDS));
            List<Object> ack=new ArrayList<>();for(Object group:(List<?>)body.get("groups"))for(Object row:(List<?>)group)ack.add(object("unit",((Map<?,?>)row).get("unit"),"status","received"));
            return object("block_id",body.get("block_id"),"results",ack);
        },true);
        WorkBlockPipeline pipeline=new WorkBlockPipeline(q,transport,envelope->{check(computed.add(((Number)envelope.get("start_unit")).longValue()));return object("fixture",true);});
        try {
            check(pipeline.tick(true));check(pipeline.tick(true));check(entered.await(2,TimeUnit.SECONDS));
            for(int i=2;i<64;i++)check(pipeline.tick(true));
            check(!pipeline.tick(true)&&computed.size()==64&&q.pending().size()==64);
            check(!pipeline.tick(false)&&computed.size()==64);
            // Simulate a delayed compute-loop poll without delaying the sender.
            java.lang.reflect.Field started=WorkBlockPipeline.class.getDeclaredField("uploadStarted");
            started.setAccessible(true);started.setLong(pipeline,System.nanoTime()-120_000_000_000L);
            release.countDown();long deadline=System.nanoTime()+2_000_000_000L;
            while(computed.size()==64&&System.nanoTime()<deadline){pipeline.tick(true);Thread.sleep(1);}
            check(computed.size()==65);
            java.lang.reflect.Field latency=WorkBlockPipeline.class.getDeclaredField("uploadLatency");
            latency.setAccessible(true);check(latency.getDouble(pipeline)<100);
        } finally {release.countDown();pipeline.close();}
        WorkBlockTransport recovery=transport.recovery();
        while(!q.pending().isEmpty())recovery.upload();
        check(q.pending().isEmpty());
        for(int lanes:new int[]{2,4}){
            WorkBlockQueueChecks.Store parallelStore=new WorkBlockQueueChecks.Store();
            WorkBlockQueue parallel=new WorkBlockQueue(parallelStore,"server","owner",true);
            for(String id:Arrays.asList("current","next")){
                Map<String,Object> block=object("format",WorkBlock.FORMAT,"block_id",id,"engine","bounded_crib_v1","start_unit",0,"end_unit",1000,
                    "config",object("requires",Arrays.asList("cpu","bounded_crib_v1"),"program",object("ciphertext","BDZGO","hypotheses",Arrays.asList(object("text","BD","legal_clean_offsets",Arrays.asList(0))),"chunk",3,"ordinal_base",0,"candidate_limit",3)));
                parallel.allocated(parallel.allocationRequest(),block);
            }
            Map<String,Map<String,Object>> live=new HashMap<>();for(String id:parallel.identities())live.put(id,object("status","reserved","valid_for_seconds",600));parallel.updateStatus(live);
            WorkBlockTransport link=new WorkBlockTransport(parallel,(path,body)->{
                if(!path.endsWith("/status"))throw new AssertionError("Unexpected network request "+path);
                List<Object> values=new ArrayList<>();for(String id:parallel.identities())values.add(object("block_id",id,"status","reserved","valid_for_seconds",600));return object("blocks",values);
            },true);
            CountDownLatch together=new CountDownLatch(lanes),holdFirst=new CountDownLatch(1);
            Set<Long> started=ConcurrentHashMap.newKeySet();
            WorkBlockPipeline concurrent=new WorkBlockPipeline(parallel,link,envelope->{
                long unit=((Number)envelope.get("start_unit")).longValue();check(started.add(unit));
                together.countDown();check(together.await(2,TimeUnit.SECONDS));
                if(unit==0)holdFirst.await();
                return object("fixture",unit);
            },lanes);
            try{
                check(!concurrent.tick(true));check(together.await(2,TimeUnit.SECONDS));check(concurrent.computing());
                ExecutorService observer=Executors.newSingleThreadExecutor();
                try{
                    Future<?> wake=observer.submit(()->{try{concurrent.awaitProgress(10000);}catch(InterruptedException e){throw new RuntimeException(e);}});
                    wake.get(2,TimeUnit.SECONDS);
                    check(parallel.pendingCount()>0); // Wake must follow persistence.
                }finally{observer.shutdownNow();}
                long deadline=System.nanoTime()+2_000_000_000L;
                while(parallel.pending().size()!=(8/lanes)*(lanes-1)&&System.nanoTime()<deadline)Thread.sleep(1);
                check(parallel.pending().size()==(8/lanes)*(lanes-1)&&started.size()==(8/lanes)*(lanes-1)+1);
                // Cancel the first unfinished job; later completed jobs are already
                // durable despite the gap and must remain after shutdown/restart.
            }finally{concurrent.close();holdFirst.countDown();}
            WorkBlockQueue recovered=new WorkBlockQueue(parallelStore,"server","owner",true);
            check(recovered.pending().size()==(8/lanes)*(lanes-1));
            recovered.updateStatus(live);
            check(((Number)((Map<?,?>)recovered.claimNext(lanes).get("envelope")).get("start_unit")).longValue()==0);
            check(((Number)((Map<?,?>)recovered.claimNext(lanes).get("envelope")).get("start_unit")).longValue()==lanes);
        }
        WorkBlockQueueChecks.Store promotionStore=new WorkBlockQueueChecks.Store();
        WorkBlockQueue promotedQueue=new WorkBlockQueue(promotionStore,"server","owner",true);
        for(String id:Arrays.asList("current","next"))promotedQueue.allocated(promotedQueue.allocationRequest(),object(
            "format",WorkBlock.FORMAT,"block_id",id,"engine","bounded_crib_v1","start_unit",0,"end_unit",1000,
            "config",object("requires",Arrays.asList("cpu","bounded_crib_v1"),"program",object("ciphertext","BDZGO",
                "hypotheses",Arrays.asList(object("text","BD","legal_clean_offsets",Arrays.asList(0))),"chunk",3,"ordinal_base",0,"candidate_limit",3))));
        Map<String,Map<String,Object>> promotionLive=new HashMap<>();
        for(String id:promotedQueue.identities())promotionLive.put(id,object("status","reserved","valid_for_seconds",600));
        promotedQueue.updateStatus(promotionLive);
        WorkBlockTransport promotionLink=new WorkBlockTransport(promotedQueue,(path,body)->{
            if(path.endsWith("/result-groups"))throw new java.io.IOException("Simulated upload delay; receipts remain durable");
            check(path.endsWith("/status"));List<Object> values=new ArrayList<>();
            for(String id:promotedQueue.identities())values.add(object("block_id",id,"status","reserved","valid_for_seconds",600));
            return object("blocks",values);
        },true);
        CountDownLatch promotedTogether=new CountDownLatch(2);
        Set<Long> promotionUnits=ConcurrentHashMap.newKeySet();
        WorkBlockPipeline dynamic=new WorkBlockPipeline(promotedQueue,promotionLink,envelope->{
            long unit=((Number)envelope.get("start_unit")).longValue();check(promotionUnits.add(unit));
            if(unit>0){promotedTogether.countDown();check(promotedTogether.await(3,TimeUnit.SECONDS));}
            return object("fixture",unit);
        });
        try{
            check(dynamic.tick(true));dynamic.promoteToTwoLanes();
            check(!dynamic.tick(true));check(promotedTogether.await(3,TimeUnit.SECONDS));
            long deadline=System.nanoTime()+3_000_000_000L;
            while(promotedQueue.pendingCount()<3&&System.nanoTime()<deadline){dynamic.tick(true);Thread.sleep(1);}
            check(promotedQueue.pendingCount()>=3);
        }finally{dynamic.close();}
        WorkBlockQueue promotedRestart=new WorkBlockQueue(promotionStore,"server","owner",true);
        check(promotedRestart.pendingCount()>=3);
        System.out.println("PASS compute during blocked durable save, legacy/grouped limits, close flush, write failure/Error and restart replay");
        System.out.println("PASS compute during blocked upload, bounded outbox, pause and resumed computation without duplicate units");
        System.out.println("PASS 2/4 concurrent block jobs, durable out-of-order completion, cancellation and restart gap recovery");
        System.out.println("PASS first-use one-to-two-lane promotion at a receipt boundary with durable restart");
    }
}
