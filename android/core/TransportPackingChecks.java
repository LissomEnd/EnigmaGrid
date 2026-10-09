import java.util.*;
import java.nio.charset.StandardCharsets;
import org.enigmagrid.core.*;
import static org.enigmagrid.core.Canonical.object;
public class TransportPackingChecks {
 static void check(boolean b){if(!b)throw new AssertionError();}
 static Map<String,Object> body(boolean grouped,List<Map<String,Object>> rows){
  if(!grouped)return object("format",WorkBlock.FORMAT,"block_id","b\"\u00e8","receipts",rows);
  List<Object> groups=new ArrayList<>();for(int i=0;i<rows.size();i+=8)groups.add(rows.subList(i,Math.min(i+8,rows.size())));
  return object("format",WorkBlockTransport.GROUP_FORMAT,"block_id","b\"\u00e8","groups",groups);
 }
 public static void main(String[] args)throws Exception{
  for(boolean grouped:new boolean[]{false,true})for(int size:new int[]{1,3900,4000,4096,8000,32000,65000}){
   int bound=grouped?768*1024:256*1024;
   List<Map<String,Object>> pending=new ArrayList<>();
   for(int i=0;i<64;i++)pending.add(object("block_id","b\"\u00e8","unit",i,"result",object("escaped","\n\"\u00e8", "payload","x".repeat(size)),"compute_seconds",.0125));
   WorkBlockQueueChecks.Store storage=new WorkBlockQueueChecks.Store();
   storage.state=object("version",1,"server","s","owner","o","blocks",new ArrayList<>(),"pending",pending);
   WorkBlockQueue queue=new WorkBlockQueue(storage,"s","o",grouped);
   new WorkBlockTransport(queue,(path,sent)->{
    int length=WorkBlockJson.json(sent).getBytes(StandardCharsets.UTF_8).length;check(length<=bound);
    List<Map<String,Object>> packed=new ArrayList<>();
    if(grouped){for(Object g:(List<?>)sent.get("groups"))for(Object row:(List<?>)g)packed.add((Map<String,Object>)row);}
    else for(Object row:(List<?>)sent.get("receipts"))packed.add((Map<String,Object>)row);
    check(!packed.isEmpty());int n=packed.size();
    if(n<(grouped?64:8)){
     Map<String,Object> next=new LinkedHashMap<>(pending.get(n));next.remove("block_id");
     List<Map<String,Object>> enlarged=new ArrayList<>(packed);enlarged.add(next);
     check(WorkBlockJson.json(body(grouped,enlarged)).getBytes(StandardCharsets.UTF_8).length>bound);
    }
    List<Object> ack=new ArrayList<>();for(Map<String,Object> row:packed)ack.add(object("unit",row.get("unit"),"status","received"));
    return object("block_id","b\"\u00e8","results",ack);
   },grouped).upload();
  }
  System.out.println("PASS exact UTF-8 packet bound and maximal packing, legacy/grouped, escaped identifiers and group boundaries");
 }
}
