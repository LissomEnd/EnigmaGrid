package org.enigmagrid.android;
import android.app.*;
import android.os.Bundle;
import java.io.File;
import java.util.*;
import org.enigmagrid.core.*;
import static org.enigmagrid.core.Canonical.object;

/** Isolated encrypted outbox benchmark; never opens enrollment or real results. */
public final class StorageQualification extends Instrumentation {
    public void onCreate(Bundle args){super.onCreate(args);start();}
    public void onStart(){
        Bundle result=new Bundle();String alias="org.enigmagrid.lab.throughput-test.v1";
        File directory=new File(getTargetContext().getCacheDir(),"throughput-test");
        try {
            if(!getTargetContext().getPackageName().endsWith(".lab"))throw new IllegalStateException("Lab only");
            directory.mkdirs();
            java.lang.reflect.Constructor<CredentialStore> ctor=CredentialStore.class.getDeclaredConstructor(File.class,String.class,String.class,int.class);
            ctor.setAccessible(true);
            CredentialStore store=ctor.newInstance(directory,alias,"outbox.enc",8*1024*1024);
            ReceiptQueue.Storage disk=new ReceiptQueue.Storage(){public Map<String,Object> load()throws Exception{return store.load();}public void save(Map<String,Object> v)throws Exception{store.save(v);}};
            StringBuilder values=new StringBuilder();
            for(boolean cached:new boolean[]{false,true,false,true}){
                store.clear();ReceiptQueue q=new ReceiptQueue(cached?new ReceiptStorageSession(disk):disk,"test","owner");
                long start=System.nanoTime();
                for(int i=0;i<20;i++){q.append(object("lease_id","job"+i,"result",object("status","complete","payload",Collections.nCopies(256,12345))));q.acknowledge("job"+i);}
                if(!new ReceiptQueue(disk,"test","owner").pending().isEmpty())throw new AssertionError("Recovery mismatch");
                values.append(cached?"session":"baseline").append("_ms_per_job=").append((System.nanoTime()-start)/1e6/20).append("; ");
            }
            store.clear();result.putString("result",values.toString());finish(Activity.RESULT_OK,result);
        }catch(Throwable error){result.putString("result","FAIL: "+error);finish(Activity.RESULT_CANCELED,result);}
        finally{try{java.security.KeyStore keys=java.security.KeyStore.getInstance("AndroidKeyStore");keys.load(null);keys.deleteEntry(alias);}catch(Exception ignored){}}
    }
}
