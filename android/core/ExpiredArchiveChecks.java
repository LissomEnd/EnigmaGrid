import java.util.*;
import org.enigmagrid.core.*;
import static org.enigmagrid.core.Canonical.object;
public class ExpiredArchiveChecks {
 static void check(boolean value){if(!value)throw new AssertionError();}
 public static void main(String[] args)throws Exception{
  WorkBlockQueueChecks.Store hot=new WorkBlockQueueChecks.Store(),archive=new WorkBlockQueueChecks.Store();
  Map<String,Object> receipt=object("block_id","expired","unit",7L,"result",object("candidate","preserved"),"compute_seconds",.125);
  hot.state=object("version",1,"server","server","owner","owner","blocks",new ArrayList<>(),"pending",new ArrayList<>(),"expired_receipts",Arrays.asList(receipt));
  WorkBlockQueue q=new WorkBlockQueue(hot,"server","owner",true);
  archive.fail=true;
  try{q.useExpiredStorage(archive);throw new AssertionError();}catch(java.io.IOException expected){}
  check(q.expiredReceiptCount()==1&&hot.state.containsKey("expired_receipts"));
  archive.fail=false;hot.fail=true;
  try{q.useExpiredStorage(archive);throw new AssertionError();}catch(java.io.IOException expected){}
  check(q.expiredReceiptCount()==1&&hot.state.containsKey("expired_receipts")&&((List<?>)archive.state.get("receipts")).size()==1);
  hot.fail=false;
  Map<String,Object> reordered=new LinkedHashMap<>();reordered.put("compute_seconds",.125);reordered.put("result",object("candidate","preserved"));reordered.put("unit",7L);reordered.put("block_id","expired");
  archive.state.put("receipts",new ArrayList<>(Arrays.asList(reordered)));
  q.useExpiredStorage(archive);
  check(q.expiredReceiptCount()==1&&!hot.state.containsKey("expired_receipts"));
  check(((Map<?,?>)((List<?>)archive.state.get("receipts")).get(0)).equals(receipt));
  int writes=archive.writes;new WorkBlockQueue(hot,"server","owner",true).useExpiredStorage(archive);check(archive.writes==writes);
  try{q.useExpiredStorage(new WorkBlockQueueChecks.Store());throw new AssertionError();}catch(IllegalStateException expected){}
  archive.state.put("owner","other");
  try{q.useExpiredStorage(archive);throw new AssertionError();}catch(IllegalStateException expected){}
  check(q.expiredReceiptCount()==1);
  System.out.println("PASS expired archive atomic copy-before-detach, failures at both writes, retry deduplication, restart, missing archive and account isolation");
 }
}
