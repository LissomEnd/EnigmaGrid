package org.enigmagrid.android;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Context;
import android.os.Bundle;
import android.os.Build;

/** Offline, CPU-only reference receipts and Android encrypted-storage checks. */
public final class CpuCompatibilityQualification extends Instrumentation {
    private static void verifyTamperRejection(Context context) throws Exception {
        CredentialStore pending=new CredentialStore(context,true).pendingResults();
        char[] data=new char[256*1024];java.util.Arrays.fill(data,'T');
        try {
            pending.save(org.enigmagrid.core.Canonical.object("payload",new String(data)));
            java.io.File encrypted=new java.io.File(context.getNoBackupFilesDir(),"qualification-results.enc");
            try(java.io.RandomAccessFile file=new java.io.RandomAccessFile(encrypted,"rw")){
                long position=file.length()-1;
                file.seek(position);int original=file.read();file.seek(position);file.write(original^1);
            }
            try {pending.load();throw new IllegalStateException("Corrupted ciphertext accepted");}
            catch(javax.crypto.AEADBadTagException expected){/* Required authentication rejection. */}
        } finally {pending.clear();}
    }
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){
        Bundle result=new Bundle();int status=Activity.RESULT_CANCELED;
        Context context=getTargetContext();boolean lab="org.enigmagrid.android.lab".equals(context.getPackageName());
        try{
            if(!lab)throw new IllegalStateException("Lab package required");
            if(new CredentialStore(context).load()!=null)throw new IllegalStateException("Lab must be unenrolled");
            if(ComputeService.active)throw new IllegalStateException("Lab computation must be stopped");
            int fixtures=EngineQualification.run(context);
            if(fixtures<=0)throw new IllegalStateException("Missing reference fixtures");
            verifyTamperRejection(context);
            result.putString("integrity","PASS corrupted large ciphertext rejected");
            result.putString("result","PASS CPU_COMPATIBILITY receipts="+fixtures+" sdk="+Build.VERSION.SDK_INT+" abi="+Build.SUPPORTED_ABIS[0]+" keystore_and_durable_queue=passed");
            status=Activity.RESULT_OK;
        }catch(Throwable failure){result.putString("result","FAIL CPU_COMPATIBILITY "+failure.getClass().getSimpleName()+": "+failure.getMessage());result.putString("trace",android.util.Log.getStackTraceString(failure));}
        finally{
            if(lab){CredentialStore storage=new CredentialStore(context,true);storage.pendingResults().clear();storage.clear();}
            finish(status,result);
        }
    }
}
