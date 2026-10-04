package org.enigmagrid.android;
import android.app.Instrumentation;
import android.os.Bundle;
import android.content.Intent;
import android.net.Uri;
import java.io.File;
/** Real Android package parsing and provider test; exists only in the .lab APK. */
public final class UpdateQualification extends Instrumentation {
 private Bundle args;
 public void onCreate(Bundle args){super.onCreate(args);this.args=args;start();}
 public void onStart(){Bundle result=new Bundle();try{
  android.content.Context c=getTargetContext();
  if(!c.getPackageName().endsWith(".lab"))throw new AssertionError("Lab only");
  File candidate=new File(c.getCacheDir(),"updates/update.apk");
  UpdateDownload.verifyPackage(c,candidate,args.getString("version"));
  boolean rejected=false;
  try{UpdateDownload.verifyPackage(c,new File(c.getApplicationInfo().sourceDir),c.getPackageManager().getPackageInfo(c.getPackageName(),0).versionName);}catch(Exception expected){rejected=true;}
  if(!rejected)throw new AssertionError("Same version accepted");
  Uri uri=Uri.parse("content://"+c.getPackageName()+".updates/update.apk");
  try(android.os.ParcelFileDescriptor fd=c.getContentResolver().openFileDescriptor(uri,"r")){
   if(fd==null||fd.getStatSize()!=candidate.length())throw new AssertionError("Provider size");
  }
  c.getSharedPreferences("update-test",0).edit().putString("sentinel","preserve-across-install").commit();
  result.putString("result","PASS real Android package/signature/version and provider checks");
  if("true".equals(args.getString("install")))c.startActivity(new Intent(Intent.ACTION_VIEW).setDataAndType(uri,"application/vnd.android.package-archive").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_GRANT_READ_URI_PERMISSION));
  finish(-1,result);
 }catch(Throwable e){result.putString("failure",e.toString());finish(0,result);}}
}
