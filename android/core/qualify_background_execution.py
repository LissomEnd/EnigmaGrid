"""Host checks for explicit Android background consent and unavailable OEM settings."""
import argparse
import pathlib
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--jdk', required=True)
args = parser.parse_args()
root = pathlib.Path(__file__).resolve().parents[2]
jdk = pathlib.Path(args.jdk) / 'bin'
sources = {
    'android/content/Context.java': '''package android.content;
public class Context {public static final String POWER_SERVICE="power";
public android.os.PowerManager power=new android.os.PowerManager();
public Object getSystemService(String name){return power;}
public String getPackageName(){return "org.enigmagrid.android";}}''',
    'android/os/PowerManager.java': '''package android.os; public class PowerManager {
public boolean allowed; public boolean isIgnoringBatteryOptimizations(String pkg){
if(!pkg.equals("org.enigmagrid.android"))throw new AssertionError();return allowed;}}''',
    'android/content/Intent.java': '''package android.content; public class Intent {
public String action;public android.net.Uri uri;
public Intent(String action){this.action=action;}
public Intent(String action,android.net.Uri uri){this.action=action;this.uri=uri;}}''',
    'android/net/Uri.java': '''package android.net; public class Uri {public String value;
public static Uri parse(String value){Uri uri=new Uri();uri.value=value;return uri;}}''',
    'android/provider/Settings.java': '''package android.provider;public class Settings {
public static final String ACTION_APPLICATION_DETAILS_SETTINGS="details",
ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS="request",ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS="list";}''',
    'android/content/ActivityNotFoundException.java': '''package android.content;
public class ActivityNotFoundException extends RuntimeException {}''',
    'android/app/Activity.java': '''package android.app;public class Activity extends android.content.Context {
public java.util.List<android.content.Intent> attempts=new java.util.ArrayList<>();
public int failures;public boolean denied;
public void startActivity(android.content.Intent intent){attempts.add(intent);
if(failures-->0){if(denied)throw new SecurityException();throw new android.content.ActivityNotFoundException();}}}''',
    'android/widget/Toast.java': '''package android.widget;public class Toast {
public static final int LENGTH_LONG=1;public static int shown;
public static Toast makeText(android.content.Context c,String s,int duration){return new Toast();}
public void show(){shown++;}}''',
    'org/enigmagrid/android/Check.java': '''package org.enigmagrid.android;
import android.app.Activity;
public class Check {
static void require(boolean value){if(!value)throw new AssertionError();}
public static void main(String[] args){
Activity denied=new Activity();require(!BackgroundExecution.allowed(denied));
require(BackgroundExecution.summary(denied).contains("may pause"));
require(denied.attempts.isEmpty());
BackgroundExecution.request(denied);require(denied.attempts.size()==1);
require(denied.attempts.get(0).action.equals("request"));
require(denied.attempts.get(0).uri.value.equals("package:org.enigmagrid.android"));
require(!denied.power.allowed); // Launching consent must never imply that it was granted.
denied.power.allowed=true;require(BackgroundExecution.allowed(denied));
BackgroundExecution.request(denied);require(denied.attempts.get(1).action.equals("details"));
for(boolean security:new boolean[]{false,true}){
Activity absent=new Activity();absent.failures=1;absent.denied=security;
BackgroundExecution.request(absent);require(absent.attempts.size()==2);
require(absent.attempts.get(1).action.equals("list"));
Activity noSettings=new Activity();noSettings.failures=2;noSettings.denied=security;
int before=android.widget.Toast.shown;BackgroundExecution.request(noSettings);
require(android.widget.Toast.shown==before+1);require(!noSettings.power.allowed);
}
denied.power=null;require(!BackgroundExecution.allowed(denied));
System.out.println("PASS explicit consent, denial, refreshed grant, missing OEM settings and permission fallback");
}}''',
}
with tempfile.TemporaryDirectory() as temporary:
    files = []
    for name, source in sources.items():
        path = pathlib.Path(temporary) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')
        files.append(str(path))
    files.append(str(root / 'android/app/src/main/java/org/enigmagrid/android/BackgroundExecution.java'))
    subprocess.run([str(jdk / 'javac.exe'), '-d', temporary, *files], check=True)
    subprocess.run([str(jdk / 'java.exe'), '-cp', temporary, 'org.enigmagrid.android.Check'], check=True)
