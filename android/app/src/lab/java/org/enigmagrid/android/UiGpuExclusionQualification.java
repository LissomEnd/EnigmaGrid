package org.enigmagrid.android;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.TextView;

/** Real lab UI handlers, no production enrollment or computation. */
public final class UiGpuExclusionQualification extends Instrumentation {
    private MainActivity activity;
    private Context context;
    public void onCreate(Bundle args){super.onCreate(args);start();}
    private Button button(String title){return (Button)find(activity.getWindow().getDecorView(),title,true);}
    private View find(View view,String text,boolean exact){
        if(view instanceof TextView){String value=((TextView)view).getText().toString();if(exact?value.equals(text):value.contains(text))return view;}
        if(view instanceof ViewGroup)for(int i=0;i<((ViewGroup)view).getChildCount();i++){View found=find(((ViewGroup)view).getChildAt(i),text,exact);if(found!=null)return found;}
        return null;
    }
    private void require(boolean condition,String message){if(!condition)throw new AssertionError(message);}
    private void launch(){activity=(MainActivity)startActivitySync(new Intent(context,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));waitForIdleSync();}
    public void onStart(){
        Bundle result=new Bundle();int code=Activity.RESULT_CANCELED;
        try{
            context=getTargetContext();require("org.enigmagrid.android.lab".equals(context.getPackageName()),"Lab package required");
            require(new CredentialStore(context).load()==null,"Lab must not be enrolled");
            if(android.os.Build.VERSION.SDK_INT>=33)require(context.checkSelfPermission("android.permission.POST_NOTIFICATIONS")==android.content.pm.PackageManager.PERMISSION_GRANTED,"Grant lab notification permission before test");
            context.stopService(new Intent(context,ComputeService.class));
            context.getSharedPreferences("worker-lifecycle",0).edit().clear().commit();
            final String key=GpuProcess.qualificationKey();
            context.getSharedPreferences("worker-settings",0).edit().putString("gpu_qualification",key).commit();
            launch();
            runOnMainSync(()->{
                Button gpu=button("Test Vulkan computation");require(gpu!=null,"GPU button missing");
                button("Start contributing").performClick();
                require(MainActivity.computeStarting,"Start handler did not establish pending gate");
                gpu.performClick();
                require(find(activity.getWindow().getDecorView(),"Comparing Vulkan and CPU",false)==null,"GPU test started during pending compute start");
            });
            waitForIdleSync();
            context.stopService(new Intent(context,ComputeService.class));
            long deadline=SystemClock.elapsedRealtime()+5000;
            while((ComputeService.active||MainActivity.computeStarting)&&SystemClock.elapsedRealtime()<deadline)SystemClock.sleep(20);
            require(!ComputeService.active&&!MainActivity.computeStarting,"Lab service did not stop");
            runOnMainSync(()->activity.finish());waitForIdleSync();
            context.getSharedPreferences("worker-lifecycle",0).edit().clear().commit();
            launch();
            runOnMainSync(()->{
                button("Test Vulkan computation").performClick();
                require(find(activity.getWindow().getDecorView(),"Comparing Vulkan and CPU",false)!=null,"GPU diagnostic not started");
                button("Start contributing").performClick();
                button("Run controlled local checks").performClick();
                require(!MainActivity.computeStarting&&!ComputeService.active,"Compute started during GPU diagnostic");
                require(!context.getSharedPreferences("worker-lifecycle",0).getBoolean("requested",false),"Contribution requested during diagnostic");
                activity.finish();
            });
            waitForIdleSync();
            long cancelDeadline=SystemClock.elapsedRealtime()+10000;
            boolean diagnosticAlive;
            do{diagnosticAlive=false;for(Thread thread:Thread.getAllStackTraces().keySet())if(thread.isAlive()&&thread.getName().equals("gpu-qualification"))diagnosticAlive=true;if(diagnosticAlive)SystemClock.sleep(20);}
            while(diagnosticAlive&&SystemClock.elapsedRealtime()<cancelDeadline);
            require(!diagnosticAlive,"GPU diagnostic cancellation did not finish");waitForIdleSync();
            require(key.equals(context.getSharedPreferences("worker-settings",0).getString("gpu_qualification","")),"Cancellation erased previous GPU qualification");
            require(!ComputeService.active,"Lab compute left active");
            result.putString("result","PASS: actual UI pending-start exclusion, diagnostic-to-start/local-check exclusion, activity cancellation retains qualification");code=Activity.RESULT_OK;
        }catch(Throwable error){result.putString("result","FAIL: "+error);}
        finally{
            if(context!=null&&"org.enigmagrid.android.lab".equals(context.getPackageName())){
                context.stopService(new Intent(context,ComputeService.class));
                context.getSharedPreferences("worker-lifecycle",0).edit().clear().commit();
                context.getSystemService(android.app.job.JobScheduler.class).cancel(UpdateJob.ID);
                if(activity!=null)runOnMainSync(()->activity.finish());
            }
            finish(code,result);
        }
    }
}
