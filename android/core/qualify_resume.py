import pathlib,tempfile,subprocess
import argparse
parser=argparse.ArgumentParser();parser.add_argument('--jdk',required=True);args=parser.parse_args()
r=pathlib.Path(__file__).resolve().parents[2];jdk=pathlib.Path(args.jdk)/'bin'

sources={
'android/content/BroadcastReceiver.java':'package android.content;public abstract class BroadcastReceiver{public abstract void onReceive(Context c,Intent i);}',
'android/content/Intent.java':'package android.content;public class Intent{public static final String ACTION_BOOT_COMPLETED="boot",ACTION_MY_PACKAGE_REPLACED="replace";String a;public Intent(Context c,Class<?> t){}public Intent setAction(String a){this.a=a;return this;}public String getAction(){return a;}}',
'android/content/SharedPreferences.java':'package android.content;public class SharedPreferences{public boolean requested,paused;public String state;public boolean getBoolean(String k,boolean d){return k.equals("requested")?requested:paused;}public SharedPreferences edit(){return this;}public SharedPreferences putString(String k,String s){state=s;return this;}public void apply(){}}',
'android/content/Context.java':'package android.content;public class Context{public SharedPreferences prefs=new SharedPreferences();public int starts;public boolean deny;public SharedPreferences getSharedPreferences(String n,int m){return prefs;}public void startForegroundService(Intent i){if(deny)throw new IllegalStateException();if(!i.getAction().equals("work"))throw new AssertionError();starts++;}}',
'org/enigmagrid/android/ComputeService.java':'package org.enigmagrid.android;public class ComputeService{}',
'Check.java':'''import android.content.*;import org.enigmagrid.android.ResumeReceiver;public class Check{public static void main(String[] a){ResumeReceiver r=new ResumeReceiver();Context c=new Context();Intent i=new Intent(c,Check.class).setAction(Intent.ACTION_MY_PACKAGE_REPLACED);r.onReceive(c,i);if(c.starts!=0)throw new AssertionError();c.prefs.requested=true;r.onReceive(c,i);if(c.starts!=1)throw new AssertionError();c.prefs.paused=true;r.onReceive(c,i);if(c.starts!=1)throw new AssertionError();c.prefs.paused=false;i.setAction("unknown");r.onReceive(c,i);if(c.starts!=1)throw new AssertionError();i.setAction(Intent.ACTION_BOOT_COMPLETED);r.onReceive(c,i);if(c.starts!=2)throw new AssertionError();c.deny=true;r.onReceive(c,i);if(c.prefs.state==null||!c.prefs.requested)throw new AssertionError();r.onReceive(c,null);System.out.println("PASS stopped, requested, paused, unrelated broadcast, boot, denied start and null intent");}}'''}
with tempfile.TemporaryDirectory() as d:
 files=[]
 for name,source in sources.items():
  p=pathlib.Path(d)/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(source);files.append(str(p))
 files.append(str(r/'android/app/src/main/java/org/enigmagrid/android/ResumeReceiver.java'))
 subprocess.run([str(jdk/'javac.exe'),'-d',d,*files],check=True);subprocess.run([str(jdk/'java.exe'),'-cp',d,'Check'],check=True)
