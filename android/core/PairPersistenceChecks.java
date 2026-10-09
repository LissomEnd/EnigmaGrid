import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.enigmagrid.core.*;
import static org.enigmagrid.core.Canonical.object;
public class PairPersistenceChecks {
 static void check(boolean v){if(!v)throw new AssertionError();}
 static class StopGuard extends RuntimeException {}
 static void scenario(int failure,boolean batched)throws Exception{
  AtomicInteger completionSaves=new AtomicInteger();CountDownLatch second=new CountDownLatch(2),hold=new CountDownLatch(1);
  WorkBlockQueueChecks.Store store=new WorkBlockQueueChecks.Store(){public void save(Map<String,Object> value)throws Exception{
   int before=state==null?0:((List<?>)state.get("pending")).size(),after=((List<?>)value.get("pending")).size();
   if(after>before)completionSaves.incrementAndGet();super.save(value);
  }};
  WorkBlockQueue q=new WorkBlockQueue(store,"server","owner",true);Map<String,Map<String,Object>> live=new HashMap<>();
  for(String id:Arrays.asList("a","b")){q.allocated(q.allocationRequest(),object("format",WorkBlock.FORMAT,"block_id",id,"engine","bounded_crib_v1","start_unit",0,"end_unit",1000,
   "config",object("requires",Arrays.asList("cpu","bounded_crib_v1"),"program",object("ciphertext","BDZGO","hypotheses",Arrays.asList(object("text","BD","legal_clean_offsets",Arrays.asList(0))),"chunk",3,"ordinal_base",0,"candidate_limit",3))));live.put(id,object("status","reserved","valid_for_seconds",600));}q.updateStatus(live);
  WorkBlockTransport transport=new WorkBlockTransport(q,(path,body)->{check(path.endsWith("/status"));List<Object> rows=new ArrayList<>();for(Object id:(List<?>)body.get("blocks"))rows.add(object("block_id",id,"status","reserved","valid_for_seconds",600));return object("blocks",rows);},true);
  WorkBlockPipeline.Compute plain=envelope->{long unit=((Number)envelope.get("start_unit")).longValue();if(unit>=2){second.countDown();
   if(failure==1)throw new java.io.IOException("second failed");if(failure==2)throw new CancellationException();if(failure==3)throw new StopGuard();if(failure==4)throw new AssertionError("second error");if(failure==5)hold.await();}
   return object("fixture",unit);};
  WorkBlockPipeline.Compute compute=batched?new WorkBlockPipeline.BatchCompute(){public Map<String,Object> run(Map<String,Object> e)throws Exception{return plain.run(e);}public void runBatch(List<Map<String,Object>> es,WorkBlockPipeline.Completed callback)throws Exception{for(int i=0;i<es.size();i++)callback.accept(i,plain.run(es.get(i)),.01);}}:plain;
  WorkBlockPipeline p=new WorkBlockPipeline(q,transport,compute,2);
  try{p.tick(true);check(second.await(3,TimeUnit.SECONDS));
   if(failure==0){long until=System.nanoTime()+3_000_000_000L;while(q.pendingCount()<8&&System.nanoTime()<until)Thread.sleep(1);}
   p.close();int expected=failure==0?8:2;check(q.pendingCount()==expected);
   check(completionSaves.get()<=Math.max(2,expected/2));
   WorkBlockQueue restart=new WorkBlockQueue(store,"server","owner",true);restart.updateStatus(live);
   check(((Number)((Map<?,?>)restart.claimNext().get("envelope")).get("start_unit")).longValue()==expected);
  }finally{hold.countDown();p.close();}
 }
 public static void main(String[] args)throws Exception{for(boolean batch:new boolean[]{false,true})for(int failure=0;failure<=5;failure++)scenario(failure,batch);
  System.out.println("PASS pair commits: first success survives second IOException/cancellation/guard/Error/stop; batch callback parity, bounded commit counts and restart replay");}
}
