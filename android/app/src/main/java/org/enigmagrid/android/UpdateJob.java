package org.enigmagrid.android;

import android.app.*;
import android.app.job.*;
import android.content.*;
import android.net.*;
import android.os.*;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import org.enigmagrid.core.UpdatePolicy;

/** OS-scheduled checks. No foreground computation or silent installation. */
public final class UpdateJob extends JobService {
 static final int ID=4708;
 static void schedule(Context context){
  JobScheduler scheduler=context.getSystemService(JobScheduler.class);
  if(scheduler==null||scheduler.getPendingJob(ID)!=null)return;
  scheduler.schedule(new JobInfo.Builder(ID,new ComponentName(context,UpdateJob.class))
   .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).setPeriodic(6*60*60*1000L)
   .setPersisted(true).setRequiresBatteryNotLow(true).build());
 }
 private final Handler main=new Handler(Looper.getMainLooper());
 private AtomicBoolean cancelled;private Thread worker;
 @Override public boolean onStartJob(JobParameters parameters){
  AtomicBoolean token=new AtomicBoolean();cancelled=token;
  worker=new Thread(()->{
   boolean retry=false;
   try{
    Context context=getApplicationContext();
    SharedPreferences prefs=context.getSharedPreferences("updates",0);
    String origin=context.getSharedPreferences("worker-settings",0).getString("server","https://enigma-grid.tail40f219.ts.net");
    Map<String,Object> account=new CredentialStore(context).load();if(account!=null)origin=(String)account.get("server");
    String installed=getPackageManager().getPackageInfo(getPackageName(),0).versionName;
    UpdateChecker.Result result=UpdateChecker.check(origin,installed);
    if(token.get())return;
    prefs.edit().putString("minimum",result.minimum).putLong("background_checked_at",System.currentTimeMillis()).putString("background_state",result.state.name()).apply();
    boolean downloaded=false;
    ConnectivityManager cm=context.getSystemService(ConnectivityManager.class);
    NetworkCapabilities caps=cm==null?null:cm.getNetworkCapabilities(cm.getActiveNetwork());
    if(result.url!=null&&prefs.getBoolean("auto_download",false)&&caps!=null&&caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)){
     try{UpdateDownload.cached(context,result);downloaded=true;}catch(Exception stale){/* Download a fresh verified package below. */}
     if(!downloaded)UpdateDownload.fetch(context,result,(done,total)->{if(token.get())throw new java.util.concurrent.CancellationException();});downloaded=true;
    }
    if(!token.get()&&result.state!=UpdatePolicy.State.CURRENT)notifyUpdate(result,downloaded);
   }catch(Exception e){retry=true;}
   finally{final boolean reschedule=retry;main.post(()->{if(!token.get()){jobFinished(parameters,reschedule);if(cancelled==token){worker=null;cancelled=null;}}});}
  },"periodic-update-check");worker.start();return true;
 }
 @Override public boolean onStopJob(JobParameters parameters){if(cancelled!=null)cancelled.set(true);if(worker!=null)worker.interrupt();worker=null;return true;}
 @Override public void onDestroy(){if(cancelled!=null)cancelled.set(true);if(worker!=null)worker.interrupt();super.onDestroy();}
 private void notifyUpdate(UpdateChecker.Result release,boolean downloaded){
  NotificationManager manager=getSystemService(NotificationManager.class);if(manager==null||!manager.areNotificationsEnabled())return;
  String key=release.state.name()+":"+release.minimum+":"+release.version+":"+downloaded;
  SharedPreferences prefs=getSharedPreferences("updates",0);if(key.equals(prefs.getString("last_notified","")))return;
  manager.createNotificationChannel(new NotificationChannel("updates","App updates",NotificationManager.IMPORTANCE_DEFAULT));
  String title=release.state==UpdatePolicy.State.OPTIONAL?"EnigmaGrid update available":"EnigmaGrid update required";
  String message=downloaded?"Download verified. Open Device to confirm installation.":"Open Device to review the update.";
  PendingIntent open=PendingIntent.getActivity(this,ID,new Intent(this,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP).putExtra("show_updates",true),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
  manager.notify(ID,new Notification.Builder(this,"updates").setSmallIcon(android.R.drawable.stat_sys_download_done).setContentTitle(title).setContentText(message).setContentIntent(open).setAutoCancel(true).build());
  prefs.edit().putString("last_notified",key).apply();
 }
}
