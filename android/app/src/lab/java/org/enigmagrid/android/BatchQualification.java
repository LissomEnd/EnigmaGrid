package org.enigmagrid.android;
import android.app.*;import android.os.Bundle;
public final class BatchQualification extends Instrumentation {
 public void onCreate(Bundle args){super.onCreate(args);start();}
 public void onStart(){Bundle result=new Bundle();try{
  result.putString("result",GpuQualification.run(getTargetContext()));finish(Activity.RESULT_OK,result);
 }catch(Throwable e){result.putString("result","FAIL: "+e.getClass().getSimpleName()+": "+e.getMessage());finish(Activity.RESULT_CANCELED,result);}}
}
