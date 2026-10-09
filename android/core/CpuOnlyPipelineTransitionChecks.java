import java.util.*;
import java.util.concurrent.*;
import org.enigmagrid.core.*;
import static org.enigmagrid.core.Canonical.object;

public final class CpuOnlyPipelineTransitionChecks {
    static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
    static Map<String,Object> block(){return object("format",WorkBlock.FORMAT,"block_id","cpu-test","engine","bounded_crib_v1",
        "start_unit",0,"end_unit",100,"config",object("requires",Arrays.asList("cpu","bounded_crib_v1"),
        "program",object("ciphertext","BDZGO","hypotheses",Arrays.asList(object("text","BD","legal_clean_offsets",Arrays.asList(0))),
            "chunk",3,"ordinal_base",0,"candidate_limit",3)));}
    static WorkBlockTransport transport(WorkBlockQueue queue){return new WorkBlockTransport(queue,(path,body)->{
        if(path.endsWith("/status"))return object("blocks",Arrays.asList(object("block_id","cpu-test","status","reserved","valid_for_seconds",600)));
        if(path.endsWith("/result-groups"))throw new java.io.IOException("hold ACK for durability check");
        if(path.equals("/api/work-blocks"))return object("block",null,"wait_reason","no_work");
        throw new IllegalStateException("Unexpected path "+path);
    },true);}
    static void transitionAndReplay()throws Exception{
        WorkBlockQueueChecks.Store store=new WorkBlockQueueChecks.Store();
        WorkBlockQueue queue=new WorkBlockQueue(store,"server","owner",true);
        queue.allocated(queue.allocationRequest(),block());
        queue.updateStatus(Collections.singletonMap("cpu-test",object("status","reserved","valid_for_seconds",600)));
        CountDownLatch entered=new CountDownLatch(2),release=new CountDownLatch(1);
        WorkBlockPipeline pipeline=new WorkBlockPipeline(queue,transport(queue),envelope->{
            long unit=((Number)envelope.get("start_unit")).longValue();
            if(unit>0){entered.countDown();check(release.await(3,TimeUnit.SECONDS),"release blocked job");}
            return object("fixture",unit);
        });
        java.util.concurrent.atomic.AtomicInteger budget=new java.util.concurrent.atomic.AtomicInteger(1);
        pipeline.setCpuLaneBudgetPublisher(budget::set);
        try{
            check(pipeline.tick(true),"first receipt");
            check(pipeline.durableProgress().units==1&&pipeline.durableProgress().scope!=null,"count only durable receipt");
            pipeline.requestCpuLanes(2);pipeline.tick(true);
            check(pipeline.lanes()==2&&budget.get()==2,"promote at boundary");
            pipeline.tick(true);check(entered.await(3,TimeUnit.SECONDS),"two jobs started");
            pipeline.requestCpuLanes(1);pipeline.tick(false);
            check(pipeline.lanes()==2,"must not demote with active jobs");
            release.countDown();
            long until=System.nanoTime()+4_000_000_000L;
            while(pipeline.lanes()!=1&&System.nanoTime()<until){pipeline.tick(false);Thread.sleep(2);}
            check(pipeline.lanes()==1&&budget.get()==1,"demote after durable drain under tick(false)");
            check(pipeline.durableProgress().units==queue.pendingCount(),"durable count matches saved outbox");
            check(pipeline.durableProgress().units>=3,"both started jobs saved");
        }finally{release.countDown();pipeline.close();}
        WorkBlockQueue replay=new WorkBlockQueue(store,"server","owner",true);
        check(replay.pendingCount()>=3,"restart retains receipts");
    }
    static void failedSaveDoesNotCount()throws Exception{
        WorkBlockQueueChecks.Store store=new WorkBlockQueueChecks.Store();
        WorkBlockQueue queue=new WorkBlockQueue(store,"server","owner",true);
        queue.allocated(queue.allocationRequest(),block());
        queue.updateStatus(Collections.singletonMap("cpu-test",object("status","reserved","valid_for_seconds",600)));
        WorkBlockPipeline pipeline=new WorkBlockPipeline(queue,transport(queue),envelope->object("fixture",true));
        try{
            store.fail=true;
            try{pipeline.tick(true);throw new AssertionError("Expected durable save failure");}
            catch(java.io.IOException expected){}
            check(pipeline.durableProgress().units==0,"failed write cannot count as durable");
        }finally{store.fail=false;pipeline.close();}
    }
    static void gpuTakeoverCancelsCpuDemotion()throws Exception{
        WorkBlockQueueChecks.Store store=new WorkBlockQueueChecks.Store();
        WorkBlockQueue queue=new WorkBlockQueue(store,"server","owner",true);
        WorkBlockPipeline pipeline=new WorkBlockPipeline(queue,transport(queue),envelope->object("fixture",true),2);
        try{
            pipeline.requestCpuLanes(1);
            pipeline.promoteToTwoLanes(); // Qualified GPU takes ownership of topology.
            pipeline.tick(false);
            check(pipeline.lanes()==2,"CPU pilot cannot demote qualified GPU lane");
        }finally{pipeline.close();}
    }
    @SuppressWarnings("unchecked") static void manyShortBlocksKeepScope()throws Exception{
        WorkBlockQueueChecks.Store store=new WorkBlockQueueChecks.Store();
        WorkBlockQueue queue=new WorkBlockQueue(store,"server","owner",true);
        WorkBlockTransport transport=new WorkBlockTransport(queue,(path,body)->{
            if(path.endsWith("/status")){
                List<Object> states=new ArrayList<>();
                for(Object id:(List<?>)body.get("blocks"))states.add(object("block_id",id,"status","reserved","valid_for_seconds",600));
                return object("blocks",states);
            }
            if(path.endsWith("/release")||path.endsWith("/result-groups"))throw new java.io.IOException("hold ACK");
            if(path.equals("/api/work-blocks"))return object("block",null,"wait_reason","no_work");
            throw new IllegalStateException("Unexpected path "+path);
        },true);
        WorkBlockPipeline pipeline=new WorkBlockPipeline(queue,transport,envelope->object("fixture",true));
        try{
            for(int i=0;i<24;i++){
                String id="short-"+i;
                Map<String,Object> descriptor=new LinkedHashMap<>(block());
                descriptor.put("block_id",id);descriptor.put("end_unit",1);
                queue.allocated(queue.allocationRequest(),descriptor);
                queue.updateStatus(Collections.singletonMap(id,object("status","reserved","valid_for_seconds",600)));
                check(pipeline.tick(true),"short block receipt "+i);
                check(pipeline.durableProgress().units==i+1,"durable count for short block "+i);
                check(!"unknown".equals(pipeline.durableProgress().scope),"scope retained beyond 16 blocks");
                queue.acknowledge(id,Collections.singleton(0L));queue.released(id);
                java.lang.reflect.Field field=WorkBlockPipeline.class.getDeclaredField("scopeByBlock");field.setAccessible(true);
                check(((Map<?,?>)field.get(pipeline)).isEmpty(),"scope entry released after durable completion");
            }
        }finally{pipeline.close();}
    }
    public static void main(String[] args)throws Exception{
        transitionAndReplay();failedSaveDoesNotCount();gpuTakeoverCancelsCpuDemotion();manyShortBlocksKeepScope();
        System.out.println("PASS CPU A/B boundary drain, durable count, restart and failed save");
    }
}
