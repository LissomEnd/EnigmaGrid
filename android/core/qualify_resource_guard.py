"""Exercise real ResourceGuard with controlled Android signals, not physical sensors."""
import argparse,pathlib,subprocess,tempfile
p=argparse.ArgumentParser();p.add_argument('--jdk',required=True);a=p.parse_args()
jdk=pathlib.Path(a.jdk)/'bin';root=pathlib.Path(__file__).resolve().parents[1]
sources={
'android/os/Build.java':'package android.os;public class Build{public static class VERSION{public static int SDK_INT=26;}}',
'android/os/SystemClock.java':'package android.os;public class SystemClock{public static long now;public static long elapsedRealtime(){return now;}}',
'android/os/BatteryManager.java':'package android.os;public class BatteryManager{public static final String EXTRA_LEVEL="level",EXTRA_SCALE="scale",EXTRA_TEMPERATURE="temperature",EXTRA_PLUGGED="plugged";}',
'android/os/PowerManager.java':'package android.os;public class PowerManager{public static final int THERMAL_STATUS_MODERATE=2;public int thermal;public boolean saver;public int getCurrentThermalStatus(){if(Build.VERSION.SDK_INT<29)throw new AssertionError("Thermal API on old Android");return thermal;}public boolean isPowerSaveMode(){return saver;}}',
'android/app/ActivityManager.java':'package android.app;public class ActivityManager{public boolean low;public int reads;public static class MemoryInfo{public boolean lowMemory;}public void getMemoryInfo(MemoryInfo i){reads++;i.lowMemory=low;}}',
'android/content/IntentFilter.java':'package android.content;public class IntentFilter{public IntentFilter(String s){}}',
'android/content/Intent.java':'package android.content;public class Intent{public static final String ACTION_BATTERY_CHANGED="battery";public java.util.Map<String,Integer> values=new java.util.HashMap<>();public int getIntExtra(String s,int d){return values.getOrDefault(s,d);}}',
'android/content/SharedPreferences.java':'package android.content;public interface SharedPreferences{int getInt(String key,int defaultValue);}',
'android/content/Context.java':'package android.content;public class Context{public static final String POWER_SERVICE="power",ACTIVITY_SERVICE="activity";public android.os.PowerManager power=new android.os.PowerManager();public android.app.ActivityManager memory=new android.app.ActivityManager();public Intent battery=new Intent();public Context getApplicationContext(){return this;}public Object getSystemService(String s){return s.equals(POWER_SERVICE)?power:memory;}public Intent registerReceiver(Object r,IntentFilter f){return battery;}}',
'org/enigmagrid/android/DeviceTelemetry.java':'package org.enigmagrid.android;import android.content.Context;class DeviceTelemetry{static float[] values={Float.NaN,Float.NaN,Float.NaN};static float[] temperatures(Context c){return values.clone();}}',
'org/enigmagrid/android/GuardChecks.java':'''package org.enigmagrid.android;
import android.content.*;import android.os.*;
public class GuardChecks{
 static int checks;
 static final class Settings implements SharedPreferences{java.util.Map<String,Integer> values=new java.util.HashMap<>();public int getInt(String key,int fallback){return values.getOrDefault(key,fallback);}}
 static void expect(ResourceGuard g,String wanted){SystemClock.now+=1000;String got=g.get();if(wanted==null?got!=null:got==null||!got.startsWith(wanted))throw new AssertionError("Expected "+wanted+", got "+got);checks++;}
 public static void main(String[] args){
  for(int api:new int[]{26,28,29,35}){
   Build.VERSION.SDK_INT=api;Context c=new Context();c.battery.values.put("level",80);c.battery.values.put("scale",100);c.battery.values.put("temperature",330);c.battery.values.put("plugged",1);
   Settings settings=new Settings();ResourceGuard g=new ResourceGuard(c,settings);DeviceTelemetry.values=new float[]{Float.NaN,Float.NaN,33};expect(g,null);
   c.memory.low=true;if(g.get()!=null)throw new AssertionError("Cache ignored");expect(g,"Waiting for available memory");
   c.memory.low=false;expect(g,null);
   c.battery.values.put("level",29);expect(g,"Battery below 30%");c.battery.values.put("level",30);expect(g,null);
   DeviceTelemetry.values[0]=75;expect(g,"Cooling CPU");DeviceTelemetry.values[0]=71;expect(g,"Cooling CPU");
   DeviceTelemetry.values[0]=Float.NaN;expect(g,"Cooling CPU"); // Missing data cannot clear a thermal hold.
   DeviceTelemetry.values[0]=70;expect(g,null);
   DeviceTelemetry.values[1]=70;expect(g,"Cooling GPU");DeviceTelemetry.values[1]=Float.NaN;expect(g,"Cooling GPU");DeviceTelemetry.values[1]=66;expect(g,"Cooling GPU");
   DeviceTelemetry.values[1]=65;expect(g,null);
   DeviceTelemetry.values[2]=43;expect(g,"Cooling battery");DeviceTelemetry.values[2]=Float.NaN;expect(g,"Cooling battery");DeviceTelemetry.values[2]=41;expect(g,"Cooling battery");
   DeviceTelemetry.values[2]=40;expect(g,null);
   settings.values.put("max_cpu_temp_c",200);DeviceTelemetry.values[0]=95;expect(g,"Cooling CPU");
   settings.values.put("max_cpu_temp_c",0);DeviceTelemetry.values[0]=49;expect(g,null);DeviceTelemetry.values[0]=55;expect(g,"Cooling CPU");
   DeviceTelemetry.values[0]=49;expect(g,null);DeviceTelemetry.values[0]=Float.NaN;
   settings.values.put("max_gpu_temp_c",200);DeviceTelemetry.values[1]=90;expect(g,"Cooling GPU");
   settings.values.put("max_gpu_temp_c",0);DeviceTelemetry.values[1]=44;expect(g,null);DeviceTelemetry.values[1]=50;expect(g,"Cooling GPU");
   DeviceTelemetry.values[1]=44;expect(g,null);DeviceTelemetry.values[1]=Float.NaN;
   c.battery.values.put("plugged",0);expect(g,"Waiting for charger");g.setChargingOnly(false);if(g.get()!=null)throw new AssertionError("Charging preference cache not invalidated");
   c.power.saver=true;expect(g,"Battery saver enabled");c.power.saver=false;
   c.power.thermal=2;expect(g,api>=29?"Cooling down · Android thermal protection":null);c.power.thermal=0;
   c.battery.values.put("scale",0);expect(g,"Battery information unavailable");c.battery=null;expect(g,"Battery information unavailable");
  }
  System.out.println("PASS "+checks+" resource guard checks across API26/28/29/35: CPU/GPU/battery hysteresis, slider clamps, OS thermal, missing sensors, cache and preferences");
 }
}'''}
with tempfile.TemporaryDirectory(prefix='enigma-guard-') as folder:
 d=pathlib.Path(folder);files=[]
 for name,source in sources.items():
  f=d/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(source,encoding='utf-8');files.append(str(f))
 files.append(str(root/'app/src/main/java/org/enigmagrid/android/ResourceGuard.java'))
 subprocess.run([str(jdk/'javac.exe'),'-J-Xmx128m','-encoding','UTF-8','-d',folder,*files],check=True,timeout=60)
 subprocess.run([str(jdk/'java.exe'),'-Xmx64m','-cp',folder,'org.enigmagrid.android.GuardChecks'],check=True,timeout=30)
