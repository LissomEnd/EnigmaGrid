import java.util.*;
import java.util.concurrent.*;
import org.enigmagrid.core.*;
import static org.enigmagrid.core.Canonical.object;

public class GpuCohortPipelineChecks {
    static void check(boolean value){if(!value)throw new AssertionError();}
    public static void main(String[] args)throws Exception {
        for(int lanes:new int[]{2,4})for(boolean grouped:new boolean[]{false,true}){
            CountDownLatch saving=new CountDownLatch(1),release=new CountDownLatch(1),computed=new CountDownLatch(8);
            WorkBlockQueueChecks.Store store=new WorkBlockQueueChecks.Store(){
                public void save(Map<String,Object> state)throws Exception {
                    if(!((List<?>)state.get("pending")).isEmpty()){saving.countDown();check(release.await(5,TimeUnit.SECONDS));}
                    super.save(state);
                }
            };
            WorkBlockQueue queue=new WorkBlockQueue(store,"server","owner",grouped);
            for(String id:Arrays.asList("current","next"))queue.allocated(queue.allocationRequest(),object(
                "format",WorkBlock.FORMAT,"block_id",id,"engine","bounded_crib_v1","start_unit",0,"end_unit",1000,
                "config",object("requires",Arrays.asList("cpu","bounded_crib_v1"),"program",object("ciphertext","BDZGO","hypotheses",Arrays.asList(object("text","BD","legal_clean_offsets",Arrays.asList(0))),"chunk",3,"ordinal_base",0,"candidate_limit",3))));
            Map<String,Map<String,Object>> live=new HashMap<>();for(String id:queue.identities())live.put(id,object("status","reserved","valid_for_seconds",600));queue.updateStatus(live);
            WorkBlockTransport transport=new WorkBlockTransport(queue,(path,body)->{
                check(path.endsWith("/status"));List<Object> values=new ArrayList<>();for(Object id:(List<?>)body.get("blocks"))values.add(object("block_id",id,"status","reserved","valid_for_seconds",600));return object("blocks",values);
            },grouped);
            Set<Long> unique=ConcurrentHashMap.newKeySet();List<Integer> widths=Collections.synchronizedList(new ArrayList<>());
            WorkBlockPipeline pipeline=new WorkBlockPipeline(queue,transport,new WorkBlockPipeline.BatchCompute(){
                public Map<String,Object> run(Map<String,Object> envelope){throw new AssertionError("Per-job callback used");}
                public void runBatch(List<Map<String,Object>> envelopes,WorkBlockPipeline.Completed completed)throws Exception {
                    check(envelopes.size()==8/lanes);widths.add(envelopes.size());
                    for(int i=0;i<envelopes.size();i++){
                        long unit=((Number)envelopes.get(i).get("start_unit")).longValue();check(unique.add(unit));computed.countDown();completed.accept(i,object("fixture",unit),.01);
                    }
                }
            },lanes);
            ExecutorService closer=Executors.newSingleThreadExecutor();
            try{
                pipeline.tick(true);check(saving.await(2,TimeUnit.SECONDS));check(computed.await(2,TimeUnit.SECONDS));check(unique.size()==8);
                check(((List<?>)store.state.get("pending")).isEmpty());
                Future<?> stop=closer.submit(pipeline::close);Thread.sleep(20);check(!stop.isDone());release.countDown();stop.get(3,TimeUnit.SECONDS);
                WorkBlockQueue recovered=new WorkBlockQueue(store,"server","owner",grouped);check(recovered.pendingCount()==8);recovered.updateStatus(live);
                if(grouped)check(((Number)((Map<?,?>)recovered.claimNext().get("envelope")).get("start_unit")).longValue()==8);
                else check(recovered.claimNext()==null);
            }finally{release.countDown();pipeline.close();closer.shutdownNow();}
        }
        System.out.println("PASS cohort pipeline 2/4 physical lanes, eight reserved real units, blocked storage overlap, stop flush and legacy/grouped bounds");
    }
}
