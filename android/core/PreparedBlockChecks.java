import java.util.*;
import org.enigmagrid.core.*;
import static org.enigmagrid.core.Canonical.object;
public class PreparedBlockChecks {
 static void check(boolean v){if(!v)throw new AssertionError();}
 @SuppressWarnings("unchecked") static Map<String,Object> map(Object x){return (Map<String,Object>)x;}
 static Map<String,Object> block(){return object("format",WorkBlock.FORMAT,"block_id","b","engine","bounded_crib_v1","start_unit",0,"end_unit",20,
  "config",object("requires",Arrays.asList("cpu","bounded_crib_v1"),"program",object("ciphertext","BDZGO","hypotheses",Arrays.asList(object("text","BD","legal_clean_offsets",Arrays.asList(0,1))),"chunk",3,"ordinal_base",0,"candidate_limit",3)));}
 static void live(WorkBlockQueue q)throws Exception{q.updateStatus(Collections.singletonMap("b",object("status","reserved","valid_for_seconds",600)));}
 static WorkBlockQueue setup(WorkBlockQueueChecks.Store s,Map<String,Object> b)throws Exception{WorkBlockQueue q=new WorkBlockQueue(s,"server","owner",true,()->0L);q.allocated(q.allocationRequest(),b);live(q);return q;}
 static Map<String,Object> descriptor(WorkBlockQueueChecks.Store s){return map(map(((List<?>)s.state.get("blocks")).get(0)).get("block"));}
 public static void main(String[] args)throws Exception{
  Map<String,Object> original=block();WorkBlockQueueChecks.Store store=new WorkBlockQueueChecks.Store();WorkBlockQueue q=setup(store,original);
  map(map(original.get("config")).get("program")).put("ciphertext","XXXXX");
  for(int n=0;n<4;n++){
   Map<String,Object> claim=q.claimNext(),actual=map(claim.get("envelope")),expected=WorkBlock.unitEnvelope(block(),n);
   check(Canonical.json(actual).equals(Canonical.json(expected)));
   check(Canonical.json(WorkEnvelope.run(actual,()->false)).equals(Canonical.json(WorkEnvelope.run(expected,()->false))));
   q.complete("b",n,object("fixture",n),.01);
   map(map(actual.get("config")).get("program")).put("ciphertext","ZZZZZ");
  }
  // A same-ID descriptor alteration is rejected, not masked by the private cache.
  map(map(descriptor(store).get("config")).get("program")).put("ciphertext","XXXXX");
  try{q.claimNext();throw new AssertionError("Changed descriptor accepted");}catch(IllegalArgumentException expected){}
  // Invalid persisted descriptors are fully revalidated on the first use after restart.
  WorkBlockQueueChecks.Store invalid=new WorkBlockQueueChecks.Store();setup(invalid,block());descriptor(invalid).put("engine","wrong");
  WorkBlockQueue restarted=new WorkBlockQueue(invalid,"server","owner",true,()->0L);live(restarted);
  try{restarted.claimNext();throw new AssertionError("Invalid persisted descriptor accepted");}catch(IllegalArgumentException expected){}
  // Selected validation and public intake validation are not bypassed.
  Map<String,Object> bad=block();map(map(bad.get("config")).get("program")).put("chunk",129);
  try{setup(new WorkBlockQueueChecks.Store(),bad);throw new AssertionError();}catch(IllegalArgumentException expected){}
  try{WorkBlock.unitEnvelope(block(),20);throw new AssertionError();}catch(IllegalArgumentException expected){}
  WorkBlockQueueChecks.Store valid=new WorkBlockQueueChecks.Store();WorkBlockQueue first=setup(valid,block());first.claimNext();first.complete("b",0,object("fixture",0),.01);
  WorkBlockQueue again=new WorkBlockQueue(valid,"server","owner",true,()->0L);live(again);
  check(Canonical.json(map(again.claimNext().get("envelope"))).equals(Canonical.json(WorkBlock.unitEnvelope(block(),1))));
  System.out.println("PASS prepared descriptor canonical envelope/receipt parity, caller/envelope mutation isolation, same-ID mutation rejection, restart validation, bounds and invalid intake");
 }
}
