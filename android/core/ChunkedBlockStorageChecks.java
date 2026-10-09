import java.util.*;
import org.enigmagrid.core.*;
import static org.enigmagrid.core.Canonical.object;

public final class ChunkedBlockStorageChecks {
    static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
    static class Disk implements ReceiptQueue.Storage {
        Map<String,Object> value;boolean fail;long bytes;
        public Map<String,Object> load(){return value;}
        public void save(Map<String,Object> next)throws Exception{if(fail)throw new java.io.IOException("manifest");value=next;bytes+=WorkBlockJson.json(next).length();}
    }
    static class Records implements ChunkedBlockStorage.Records {
        Map<String,Map<String,Object>> values=new HashMap<>();boolean fail,failCleanup;int writes;long bytes;
        public Map<String,Object> load(String id){return values.get(id);}
        public void save(String id,Map<String,Object> value)throws Exception{if(fail)throw new java.io.IOException("record");values.put(id,value);writes++;bytes+=WorkBlockJson.json(value).length();}
        public void retain(Set<String> ids)throws Exception{if(failCleanup)throw new java.io.IOException("cleanup");values.keySet().retainAll(ids);}
    }
    static Map<String,Object> state(int count){
        List<Object> pending=new ArrayList<>();
        for(int i=0;i<count;i++)pending.add(object("block_id","b","unit",i,"compute_seconds",.0125,"result",object("payload","x".repeat(10000))));
        return object("version",1,"server","server","owner","owner","blocks",new ArrayList<>(),"pending",pending);
    }
    static void rejected(ReceiptQueue.Storage store)throws Exception{try{store.load();throw new AssertionError("Corrupt state accepted");}catch(IllegalStateException expected){}}
    public static void main(String[] args)throws Exception {
        Disk disk=new Disk();Records files=new Records();disk.value=state(2);
        ChunkedBlockStorage store=new ChunkedBlockStorage(disk,files);
        check(WorkBlockJson.json(store.load()).equals(WorkBlockJson.json(state(2))),"legacy unreadable");
        files.fail=true;try{store.save(state(3));throw new AssertionError();}catch(java.io.IOException expected){}
        check(!disk.value.containsKey("storage_format"),"failed migration replaced legacy");files.fail=false;
        store.save(state(3));check(files.writes==3,"initial records missing");
        Map<String,Object> prior=disk.value;disk.fail=true;
        try{store.save(state(4));throw new AssertionError();}catch(java.io.IOException expected){}
        check(prior==disk.value,"failed manifest committed");
        check(((List<?>)new ChunkedBlockStorage(disk,files).load().get("pending")).size()==3,"restart lost prior commit");
        disk.fail=false;int writes=files.writes;store.save(state(4));check(files.writes==writes+1,"unchanged receipts rewritten");
        files.failCleanup=true;store.save(state(1));check(store.cleanupPending(),"cleanup failure hidden");
        check(((List<?>)new ChunkedBlockStorage(disk,files).load().get("pending")).size()==1,"cleanup failure invalidated commit");
        files.failCleanup=false;store.save(state(1));check(files.values.size()==1&&!store.cleanupPending(),"orphan cleanup failed");
        String hash=files.values.keySet().iterator().next();Map<String,Object> intact=files.values.get(hash);
        files.values.remove(hash);rejected(new ChunkedBlockStorage(disk,files));files.values.put(hash,intact);
        Map<String,Object> corrupt=new HashMap<>(intact);corrupt.put("owner","another account");files.values.put(hash,corrupt);rejected(new ChunkedBlockStorage(disk,files));files.values.put(hash,intact);
        Map<String,Object> reordered=new HashMap<>(intact);files.values.put(hash,reordered);check(new ChunkedBlockStorage(disk,files).load()!=null,"map order affected digest");
        Disk scaleDisk=new Disk();Records scaleFiles=new Records();ChunkedBlockStorage scale=new ChunkedBlockStorage(scaleDisk,scaleFiles);long legacyBytes=0;
        for(int count=1;count<=64;count++){Map<String,Object> value=state(count);legacyBytes+=WorkBlockJson.json(value).length();scale.save(value);}
        check(scaleFiles.writes==64,"receipt writes are not linear");check(scaleFiles.bytes+scaleDisk.bytes<legacyBytes/4,"write amplification not reduced");
        check(((List<?>)new ChunkedBlockStorage(scaleDisk,scaleFiles).load().get("pending")).size()==64,"restart count");
        ChunkedBlockStorage adaptive=new ChunkedBlockStorage(scaleDisk,scaleFiles,131072);
        scaleDisk.fail=true;try{adaptive.save(state(1));throw new AssertionError();}catch(java.io.IOException expected){}
        check(((List<?>)new ChunkedBlockStorage(scaleDisk,scaleFiles).load().get("pending")).size()==64,"failed inline switch lost records");
        scaleDisk.fail=false;adaptive.save(state(1));check(!scaleDisk.value.containsKey("storage_format")&&scaleFiles.values.isEmpty(),"small outbox not inlined");
        adaptive.save(state(64));check(((List<?>)new ChunkedBlockStorage(scaleDisk,scaleFiles).load().get("pending")).size()==64,"inline to chunked transition failed");
        adaptive.save(state(128));check(((List<?>)new ChunkedBlockStorage(scaleDisk,scaleFiles).load().get("pending")).size()==128,"wide grouped outbox lost receipts");
        scaleDisk.fail=true;try{adaptive.save(state(127));throw new AssertionError();}catch(java.io.IOException expected){}
        check(((List<?>)new ChunkedBlockStorage(scaleDisk,scaleFiles).load().get("pending")).size()==128,"failed wide commit changed durable outbox");
        System.out.println("PASS chunked migration, failures before/at commit, restart, orphan cleanup, digest/account protection; persisted bytes "+(scaleFiles.bytes+scaleDisk.bytes)+" vs "+legacyBytes+" full rewrites");
    }
}
