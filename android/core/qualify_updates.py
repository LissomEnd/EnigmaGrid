"""Exercise actual APK download/verification logic with controlled transport and Android adapters."""
import argparse,pathlib,subprocess,tempfile
p=argparse.ArgumentParser();p.add_argument('--jdk',required=True);a=p.parse_args();jdk=pathlib.Path(a.jdk)/'bin'
root=pathlib.Path(__file__).resolve().parents[1]
sources={
'android/os/Build.java':'package android.os; public class Build {public static class VERSION{public static int SDK_INT=35;}}',
'android/content/Context.java':'''package android.content;import java.io.*;import android.content.pm.*;public class Context{public File dir;public PackageManager pm=new PackageManager();public Context(File d){dir=d;}public File getCacheDir(){return dir;}public PackageManager getPackageManager(){return pm;}public String getPackageName(){return "org.enigmagrid.android";}}''',
'android/content/pm/Signature.java':'''package android.content.pm;public class Signature{byte[] b;public Signature(byte[] b){this.b=b;}public byte[] toByteArray(){return b;}}''',
'android/content/pm/SigningInfo.java':'''package android.content.pm;public class SigningInfo{public Signature[] values={new Signature(new byte[]{1})};public Signature[] getApkContentsSigners(){return values;}}''',
'android/content/pm/PackageInfo.java':'''package android.content.pm;public class PackageInfo{public String packageName="org.enigmagrid.android",versionName="0.4.5";public int versionCode=3;public SigningInfo signingInfo=new SigningInfo();public Signature[] signatures=signingInfo.values;public long getLongVersionCode(){return versionCode;}}''',
'android/content/pm/PackageManager.java':'''package android.content.pm;public class PackageManager{public static int GET_SIGNING_CERTIFICATES=1,GET_SIGNATURES=2;public PackageInfo installed=new PackageInfo(),candidate=new PackageInfo();public PackageManager(){candidate.versionName="0.4.6";candidate.versionCode=4;}public PackageInfo getPackageInfo(String p,int f){return installed;}public PackageInfo getPackageArchiveInfo(String p,int f){return candidate;}}''',
'org/enigmagrid/android/UpdateChecker.java':'''package org.enigmagrid.android;class UpdateChecker{static class Result{String url,sha256,version="0.4.6";long size;Result(String u,String h,long s){url=u;sha256=h;size=s;}}}''',
'org/enigmagrid/android/UpdateChecks.java':r'''package org.enigmagrid.android;
import java.io.*;import java.net.*;import java.security.*;import java.security.cert.Certificate;import javax.net.ssl.*;import android.content.*;
public class UpdateChecks{
 static byte[] payload={1,2,3,4};static String redirect;static int checks;
 static class Connection extends HttpsURLConnection{Connection(URL u){super(u);}public int getResponseCode(){return redirect==null?200:302;}public String getHeaderField(String k){return redirect;}public InputStream getInputStream(){return new ByteArrayInputStream(payload);}public void disconnect(){}public boolean usingProxy(){return false;}public void connect(){}public String getCipherSuite(){return "test";}public Certificate[] getLocalCertificates(){return null;}public Certificate[] getServerCertificates(){return null;}}
 interface Task{void run()throws Exception;}static void rejects(Task task)throws Exception{try{task.run();throw new AssertionError("Accepted invalid update");}catch(IOException expected){checks++;}}
 public static void main(String[] args)throws Exception{
  URL.setURLStreamHandlerFactory(protocol->protocol.equals("https")?new URLStreamHandler(){protected URLConnection openConnection(URL u){return new Connection(u);}}:null);
  Context c=new Context(new File(args[0]));String hash="9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a";
  UpdateChecker.Result r=new UpdateChecker.Result("https://github.com/LissomEnd/EnigmaGrid/releases/download/android-v0.4.6/EnigmaGrid-Android-0.4.6.apk",hash,4);
  File good=UpdateDownload.fetch(c,r,(x,y)->{});if(good.length()!=4)throw new AssertionError();checks++;
  r.sha256="0".repeat(64);rejects(()->UpdateDownload.fetch(c,r,(x,y)->{}));r.sha256=hash;
  r.size=3;rejects(()->UpdateDownload.fetch(c,r,(x,y)->{}));r.size=5;rejects(()->UpdateDownload.fetch(c,r,(x,y)->{}));r.size=4;
  redirect="http://github.com/file.apk";rejects(()->UpdateDownload.fetch(c,r,(x,y)->{}));redirect="https://example.com/file.apk";rejects(()->UpdateDownload.fetch(c,r,(x,y)->{}));redirect=null;
  c.pm.candidate.packageName="other.app";rejects(()->UpdateDownload.verifyPackage(c,good,"0.4.6"));c.pm.candidate.packageName="org.enigmagrid.android";
  c.pm.candidate.versionCode=3;rejects(()->UpdateDownload.verifyPackage(c,good,"0.4.6"));c.pm.candidate.versionCode=4;
  c.pm.candidate.signingInfo.values=new android.content.pm.Signature[]{new android.content.pm.Signature(new byte[]{2})};rejects(()->UpdateDownload.verifyPackage(c,good,"0.4.6"));
  if(new File(c.dir,"updates/update.part").exists())throw new AssertionError("Partial retained");
  System.out.println("PASS "+checks+" download/package checks (controlled transport and Android adapters)");
 }
}'''
}
with tempfile.TemporaryDirectory(prefix='enigma-update-checks-') as folder:
 d=pathlib.Path(folder);files=[]
 for name,source in sources.items():
  f=d/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(source,encoding='utf-8');files.append(str(f))
 files += [str(root/'app/src/main/java/org/enigmagrid/android/UpdateDownload.java'),str(root/'core/src/main/java/org/enigmagrid/core/UpdatePolicy.java')]
 subprocess.run([str(jdk/'javac.exe'),'-encoding','UTF-8','-d',str(d),*files],check=True)
 subprocess.run([str(jdk/'java.exe'),'-cp',str(d),'org.enigmagrid.android.UpdateChecks',str(d/'cache')],check=True)
