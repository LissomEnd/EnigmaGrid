"""Actual transport cancellation must not wait on a blocking disconnect."""
import argparse,pathlib,subprocess,tempfile
p=argparse.ArgumentParser();p.add_argument('--jdk',required=True);a=p.parse_args()
root=pathlib.Path(__file__).resolve().parents[1];jdk=pathlib.Path(a.jdk)/'bin'
source=r"""package org.enigmagrid.android;
import java.util.*;import java.util.concurrent.*;import java.util.concurrent.atomic.*;import javax.net.ssl.*;import java.net.*;
class JsonCodec{static Map<String,Object> object(String s){return null;}}
public class CancelChecks {
 static class Connection extends HttpsURLConnection {
  CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1),done=new CountDownLatch(1);AtomicInteger calls=new AtomicInteger();
  Connection()throws Exception{super(new URL("https://test.invalid"));}
  public void disconnect(){calls.incrementAndGet();entered.countDown();try{release.await();}catch(InterruptedException e){Thread.currentThread().interrupt();}finally{done.countDown();}}
  public boolean usingProxy(){return false;}public void connect(){}public String getCipherSuite(){return "test";}
  public java.security.cert.Certificate[] getLocalCertificates(){return null;}public java.security.cert.Certificate[] getServerCertificates(){return null;}
 }
 public static void main(String[] args)throws Exception{
  CoordinatorClient client=new CoordinatorClient("https://test.invalid");Connection c=new Connection();
  java.lang.reflect.Field field=CoordinatorClient.class.getDeclaredField("active");field.setAccessible(true);
  AtomicReference<HttpsURLConnection> active=(AtomicReference<HttpsURLConnection>)field.get(client);active.set(c);
  ExecutorService ui=Executors.newSingleThreadExecutor();
  try{
   ui.submit(()->client.cancel()).get(1,TimeUnit.SECONDS);
   if(!c.entered.await(1,TimeUnit.SECONDS))throw new AssertionError("disconnect absent");
   ui.submit(()->client.cancel()).get(1,TimeUnit.SECONDS);
   if(c.calls.get()!=1||active.get()!=null)throw new AssertionError("duplicate cancellation");
  }finally{c.release.countDown();ui.shutdownNow();}
  if(!c.done.await(1,TimeUnit.SECONDS))throw new AssertionError("disconnect leaked");
  System.out.println("PASS: blocked disconnect does not block caller; repeated cancellation is idempotent");
 }
}
"""
with tempfile.TemporaryDirectory() as folder:
 d=pathlib.Path(folder);f=d/'CancelChecks.java';f.write_text(source,encoding='utf-8')
 subprocess.run([str(jdk/'javac.exe'),'-d',str(d),str(f),str(root/'app/src/main/java/org/enigmagrid/android/CoordinatorClient.java'),str(root/'core/src/main/java/org/enigmagrid/core/Canonical.java')],check=True)
 subprocess.run([str(jdk/'java.exe'),'-cp',str(d),'org.enigmagrid.android.CancelChecks'],check=True,timeout=10)
