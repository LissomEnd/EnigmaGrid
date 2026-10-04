package org.enigmagrid.android;
import android.app.Activity;import android.content.*;import android.net.Uri;import android.view.View;import android.widget.*;import java.io.File;import org.enigmagrid.core.UpdatePolicy;

/** User-visible update checks and verified installation, never silent installation. */
final class UpdatePanel {
 private final Activity activity;private final SharedPreferences prefs;private final TextView status;
 private final Button check,action;private UpdateChecker.Result release;private File downloaded;private volatile boolean busy;
 UpdatePanel(Activity activity,LinearLayout parent){
  this.activity=activity;prefs=activity.getSharedPreferences("updates",0);
  status=new TextView(activity);status.setTextColor(0xffe2edf2);status.setTextSize(16);status.setText("Updates: checking availability");parent.addView(status);
  check=new Button(activity);check.setText("Check for updates");check.setAllCaps(false);parent.addView(check);check.setOnClickListener(v->check());
  action=new Button(activity);action.setAllCaps(false);action.setVisibility(View.GONE);parent.addView(action);action.setOnClickListener(v->{if(downloaded==null)download();else install();});
  CheckBox automatic=new CheckBox(activity);automatic.setText("Download updates automatically on Wi-Fi");automatic.setChecked(prefs.getBoolean("auto_download",false));parent.addView(automatic);
  automatic.setOnCheckedChangeListener((v,on)->prefs.edit().putBoolean("auto_download",on).apply());
  check();
 }
 private void ui(Runnable run){activity.runOnUiThread(()->{if(!activity.isDestroyed())run.run();});}
 private String installed()throws Exception{return activity.getPackageManager().getPackageInfo(activity.getPackageName(),0).versionName;}
 private void check(){
  if(busy)return;busy=true;check.setEnabled(false);action.setVisibility(View.GONE);status.setText("Checking Android releases…");
  new Thread(()->{try{
   String origin=activity.getSharedPreferences("worker-settings",0).getString("server","https://enigma-grid.tail40f219.ts.net");
   java.util.Map<String,Object> account=new CredentialStore(activity).load();if(account!=null)origin=(String)account.get("server");
   UpdateChecker.Result result=UpdateChecker.check(origin,installed());release=result;downloaded=null;
   prefs.edit().putString("minimum",result.minimum).putLong("last_check",System.currentTimeMillis()).apply();
   ui(()->{busy=false;check.setEnabled(true);
    switch(result.state){
     case CURRENT:status.setText("Android app is up to date");break;
     case REQUIRED_UNAVAILABLE:status.setText("Update required ("+result.minimum+"). No compatible download is currently available. Account and results are retained.");break;
     default:status.setText((result.state==UpdatePolicy.State.REQUIRED?"Required update: ":"Optional update: ")+result.version+"\n"+result.notes);action.setText("Download update");action.setVisibility(View.VISIBLE);
      android.net.ConnectivityManager cm=(android.net.ConnectivityManager)activity.getSystemService(Context.CONNECTIVITY_SERVICE);
      android.net.NetworkCapabilities caps=cm.getNetworkCapabilities(cm.getActiveNetwork());
      if(prefs.getBoolean("auto_download",false)&&caps!=null&&caps.hasTransport(android.net.NetworkCapabilities.TRANSPORT_WIFI))download();
    }
   });
  }catch(Exception e){ui(()->{busy=false;check.setEnabled(true);status.setText("Update check unavailable. Tap Check for updates to retry.");});}},"update-check").start();
 }
 private void download(){if(busy||release==null)return;busy=true;action.setEnabled(false);check.setEnabled(false);
  new Thread(()->{try{File file=UpdateDownload.fetch(activity.getApplicationContext(),release,(done,total)->ui(()->status.setText("Downloading update: "+(done*100/total)+"%")));downloaded=file;ui(()->{status.setText("APK verified. Android will ask you to confirm installation.");action.setText("Install update");});}
   catch(Exception e){downloaded=null;ui(()->status.setText("Download or verification failed. Nothing installed. Retry download."));}
   finally{busy=false;ui(()->{action.setEnabled(true);check.setEnabled(true);});}},"update-download").start();
 }
 private void install(){
  try{
   UpdateDownload.verifyPackage(activity,downloaded,release.version);
   if(!activity.getPackageManager().canRequestPackageInstalls()){
    status.setText("Allow EnigmaGrid to install updates, then return and tap Install update.");
    activity.startActivity(new Intent(android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,Uri.parse("package:"+activity.getPackageName())));return;
   }
   Intent intent=new Intent(Intent.ACTION_VIEW).setDataAndType(Uri.parse("content://"+activity.getPackageName()+".updates/update.apk"),"application/vnd.android.package-archive").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
   activity.startActivity(intent);
  }catch(Exception e){status.setText("Installer could not start. No account or result data was removed.");}
 }
}
