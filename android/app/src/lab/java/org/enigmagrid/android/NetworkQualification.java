package org.enigmagrid.android;
import android.app.*;
import android.os.Bundle;
import java.util.*;
import java.io.*;
import java.security.KeyStore;
import java.security.cert.CertificateFactory;
import javax.net.ssl.*;
import static org.enigmagrid.core.Canonical.object;

/** Only packaged in the separate .lab APK. Trust is scoped to each test client. */
public final class NetworkQualification extends Instrumentation {
    private Bundle args;
    public void onCreate(Bundle args){super.onCreate(args);this.args=args;start();}
    public void onStart(){
        Bundle result=new Bundle();
        try(GpuProcess gpu="true".equals(args.getString("gpu"))?new GpuProcess(getTargetContext()):null){
            java.util.concurrent.atomic.AtomicInteger dispatches=new java.util.concurrent.atomic.AtomicInteger();
            org.enigmagrid.core.BoundedCrib.RowProvider rows=gpu==null?null:(key,offset,length)->{
                dispatches.incrementAndGet();int[] flat=gpu.rows(org.enigmagrid.core.EnigmaM4.rowInputs(key.reflector,key.greek,key.moving,key.positions,key.rings,offset,length));
                if(flat.length!=length*26)throw new IllegalStateException("GPU rows");int[][] values=new int[length][26];for(int i=0;i<length;i++)System.arraycopy(flat,i*26,values[i],0,26);return values;
            };
            String origin=args.getString("origin");
            if(origin==null||!origin.matches("https://127\\.0\\.0\\.1:[0-9]+"))throw new IllegalArgumentException("Loopback test only");
            byte[] cert=android.util.Base64.decode(args.getString("certificate"),android.util.Base64.DEFAULT);
            KeyStore trust=KeyStore.getInstance(KeyStore.getDefaultType());trust.load(null);
            trust.setCertificateEntry("test",CertificateFactory.getInstance("X.509").generateCertificate(new ByteArrayInputStream(cert)));
            TrustManagerFactory factory=TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());factory.init(trust);
            SSLContext tls=SSLContext.getInstance("TLS");tls.init(null,factory.getTrustManagers(),null);
            CredentialStore store=new CredentialStore(getTargetContext(),true);
            boolean batch="true".equals(args.getString("batch"));
            boolean resume="resume".equals(args.getString("phase"));
            if(resume){
                int previous=getTargetContext().getSharedPreferences("lab-restart",0).getInt("pid",-1);
                if(previous<0||previous==android.os.Process.myPid())throw new AssertionError("No process boundary");
                if(store.load()==null||store.pendingResults().load()==null)throw new AssertionError("State lost across process boundary");
            }else{store.clear();store.pendingResults().clear();store.registrationAttempt().clear();}
            for(int i=0;i<2;i++){
                CoordinatorClient client=new CoordinatorClient(origin,tls.getSocketFactory());
                if(!resume||i!=0)Enrollment.register(client,store,"Android lab "+i,"",object("cpu_percent",25,"gpu_percent",0,"allow_cpu",true,"allow_gpu",false),()->false);
                String status;
                if(i==0){
                    if(!resume)try{new NetworkWorker(client,store,rows,batch).once(()->false);throw new AssertionError("Expected lost acknowledgement");}catch(IOException expected){if(store.pendingResults().load()==null)throw new AssertionError("Before durable result: "+expected.getClass().getSimpleName()+": "+expected.getMessage());}
                    if(store.pendingResults().load()==null)throw new AssertionError("Pending receipt lost");
                    if("prepare".equals(args.getString("phase"))){
                        getTargetContext().getSharedPreferences("lab-restart",0).edit().putInt("pid",android.os.Process.myPid()).commit();
                        result.putString("result","READY_FOR_PROCESS_RESTART");finish(Activity.RESULT_OK,result);return;
                    }
                    // Reopen the real Keystore-backed storage before replay.
                    store=new CredentialStore(getTargetContext(),true);
                    status=new NetworkWorker(client.fork(),store,rows,batch).once(()->false);
                    if(!status.startsWith("Saved result acknowledged"))throw new AssertionError(status);
                    if(batch)new NetworkWorker(client,store,rows,true).once(()->false);
                }else status=new NetworkWorker(client,store,rows,batch).once(()->false);
                if(!((java.util.List<?>)store.pendingResults().load().get("submissions")).isEmpty())throw new AssertionError("Result not acknowledged");
                store.clear();store.pendingResults().clear();store.registrationAttempt().clear();
            }
            if(gpu!=null&&dispatches.get()!=(batch?(resume?15:16):(resume?1:2)))throw new AssertionError("Expected two GPU core dispatches");
            result.putString("result",gpu==null?"PASS_ANDROID_HTTPS_KEYSTORE_REPLAY":"PASS_ANDROID_HTTPS_KEYSTORE_REPLAY_GPU");finish(Activity.RESULT_OK,result);
        }catch(Throwable error){result.putString("result","FAIL: "+error.getClass().getSimpleName()+": "+error.getMessage());finish(Activity.RESULT_CANCELED,result);}
    }
}
