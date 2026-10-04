package org.enigmagrid.android;

import android.content.Context;
import android.content.pm.*;
import android.os.Build;
import java.io.*;
import java.net.*;
import java.security.MessageDigest;
import java.util.*;
import javax.net.ssl.HttpsURLConnection;
import org.enigmagrid.core.UpdatePolicy;

/** Bounded download; verifies digest, package, signer and version before installation. */
final class UpdateDownload {
 interface Progress {void received(long bytes,long total);}
 static synchronized File fetch(Context context,UpdateChecker.Result release,Progress progress)throws Exception {
  if(Thread.currentThread().isInterrupted())throw new InterruptedIOException("Download cancelled");
  if(release.url==null||release.sha256==null)throw new IOException("No compatible APK available");
  File directory=new File(context.getCacheDir(),"updates");if(!directory.isDirectory()&&!directory.mkdirs())throw new IOException("Cannot create download folder");
  File partial=new File(directory,"update.part"),ready=new File(directory,"update.apk");
  HttpsURLConnection connection=null;
  try {
   URL next=new URL(release.url);
   for(int hop=0;hop<5;hop++){
    if(!"https".equals(next.getProtocol())||next.getUserInfo()!=null||next.getPort()!=-1)throw new IOException("Unsafe download destination");
    String host=next.getHost();if(!host.equals("github.com")&&!host.equals("release-assets.githubusercontent.com")&&!host.equals("objects.githubusercontent.com"))throw new IOException("Unexpected download host");
    connection=(HttpsURLConnection)next.openConnection();connection.setInstanceFollowRedirects(false);connection.setConnectTimeout(15000);connection.setReadTimeout(30000);
    int code=connection.getResponseCode();
    if(code==200)break;
    if(code!=301&&code!=302&&code!=303&&code!=307&&code!=308)throw new IOException("Download HTTP "+code);
    String location=connection.getHeaderField("Location");connection.disconnect();connection=null;
    if(location==null)throw new IOException("Missing download redirect");next=new URL(next,location);
   }
   if(connection==null||connection.getResponseCode()!=200)throw new IOException("Too many download redirects");
   long count=0;MessageDigest digest=MessageDigest.getInstance("SHA-256");
   try(InputStream in=connection.getInputStream();FileOutputStream out=new FileOutputStream(partial)){
    byte[] buffer=new byte[65536];int n;while((n=in.read(buffer))!=-1){
     if(Thread.currentThread().isInterrupted())throw new InterruptedIOException("Download cancelled");
     count+=n;if(count>release.size)throw new IOException("APK exceeds expected size");
     digest.update(buffer,0,n);out.write(buffer,0,n);progress.received(count,release.size);
    }out.getFD().sync();
   }
   if(count!=release.size||!hex(digest.digest()).equals(release.sha256))throw new IOException("APK integrity check failed");
   verifyPackage(context,partial,release.version);
   if(ready.exists()&&!ready.delete())throw new IOException("Cannot replace cached APK");
   if(!partial.renameTo(ready))throw new IOException("Cannot save verified APK");return ready;
  }finally{if(connection!=null)connection.disconnect();if(partial.exists())partial.delete();}
 }
 static synchronized File cached(Context context,UpdateChecker.Result release)throws Exception {
  File file=new File(context.getCacheDir(),"updates/update.apk");
  if(release.sha256==null||!file.isFile()||file.length()!=release.size)throw new IOException("No matching cached APK");
  MessageDigest digest=MessageDigest.getInstance("SHA-256");
  try(InputStream in=new FileInputStream(file)){byte[] buffer=new byte[65536];int n;while((n=in.read(buffer))!=-1){if(Thread.currentThread().isInterrupted())throw new InterruptedIOException();digest.update(buffer,0,n);}}
  if(!hex(digest.digest()).equals(release.sha256))throw new IOException("Cached APK integrity check failed");
  verifyPackage(context,file,release.version);return file;
 }
 @SuppressWarnings("deprecation")
 static void verifyPackage(Context context,File file,String expected)throws Exception {
  PackageManager manager=context.getPackageManager();int flags=Build.VERSION.SDK_INT>=28?PackageManager.GET_SIGNING_CERTIFICATES:PackageManager.GET_SIGNATURES;
  PackageInfo installed=manager.getPackageInfo(context.getPackageName(),flags),candidate=manager.getPackageArchiveInfo(file.getAbsolutePath(),flags);
  if(candidate==null||!context.getPackageName().equals(candidate.packageName)||!expected.equals(candidate.versionName)||UpdatePolicy.compare(candidate.versionName,installed.versionName)<=0)throw new IOException("APK package/version mismatch");
  long oldCode=Build.VERSION.SDK_INT>=28?installed.getLongVersionCode():installed.versionCode;
  long newCode=Build.VERSION.SDK_INT>=28?candidate.getLongVersionCode():candidate.versionCode;
  if(newCode<=oldCode)throw new IOException("APK version code must increase");
  Signature[] trusted=Build.VERSION.SDK_INT>=28?installed.signingInfo.getApkContentsSigners():installed.signatures;
  Signature[] offered=Build.VERSION.SDK_INT>=28?candidate.signingInfo.getApkContentsSigners():candidate.signatures;
  if(trusted==null||offered==null||trusted.length!=1||offered.length!=1||!MessageDigest.isEqual(trusted[0].toByteArray(),offered[0].toByteArray()))throw new IOException("APK signing identity mismatch");
 }
 private static String hex(byte[] bytes){StringBuilder out=new StringBuilder();for(byte value:bytes)out.append(String.format(Locale.ROOT,"%02x",value&255));return out.toString();}
}
