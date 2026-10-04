package org.enigmagrid.android;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Context;
import android.os.Bundle;
import android.os.Build;

/** Offline, CPU-only reference receipts and Android encrypted-storage checks. */
public final class CpuCompatibilityQualification extends Instrumentation {
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
            result.putString("result","PASS CPU_COMPATIBILITY receipts="+fixtures+" sdk="+Build.VERSION.SDK_INT+" abi="+Build.SUPPORTED_ABIS[0]+" keystore_and_durable_queue=passed");
            status=Activity.RESULT_OK;
        }catch(Throwable failure){result.putString("result","FAIL CPU_COMPATIBILITY "+failure.getClass().getSimpleName()+": "+failure.getMessage());result.putString("trace",android.util.Log.getStackTraceString(failure));}
        finally{
            if(lab){CredentialStore storage=new CredentialStore(context,true);storage.pendingResults().clear();storage.clear();}
            finish(status,result);
        }
    }
}
