package org.enigmagrid.android;

import android.content.*;
import android.app.ActivityManager;
import android.os.*;
import java.util.Locale;
import java.util.function.Supplier;

/** Device constraints with app-level thermal ceilings and hysteresis. */
final class ResourceGuard implements Supplier<String> {
    static final int MIN_CPU_TEMP_C=55,MAX_CPU_TEMP_C=95;
    static final int MIN_GPU_TEMP_C=50,MAX_GPU_TEMP_C=90;
    private final Context context;
    private final PowerManager power;
    private final ActivityManager memoryManager;
    private final ActivityManager.MemoryInfo memoryInfo=new ActivityManager.MemoryInfo();
    private final SharedPreferences settings;
    private volatile boolean chargingOnly=true;
    private boolean cpuCooling,gpuCooling,batteryCooling;
    private long last=-1;
    private String cached="Checking battery";
    ResourceGuard(Context context,SharedPreferences settings){
        this.context=context.getApplicationContext();this.settings=settings;
        power=(PowerManager)this.context.getSystemService(Context.POWER_SERVICE);
        memoryManager=(ActivityManager)this.context.getSystemService(Context.ACTIVITY_SERVICE);
    }
    synchronized void setChargingOnly(boolean value){if(chargingOnly!=value){chargingOnly=value;last=-1;}}
    @Override public synchronized String get() {
        long now=SystemClock.elapsedRealtime();if(last>=0&&now-last<1000)return cached;last=now;
        if(memoryManager!=null){memoryManager.getMemoryInfo(memoryInfo);if(memoryInfo.lowMemory)return cached="Waiting for available memory";}
        Intent battery=context.registerReceiver(null,new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        if(battery==null)return cached="Battery information unavailable";
        int level=battery.getIntExtra(BatteryManager.EXTRA_LEVEL,-1),scale=battery.getIntExtra(BatteryManager.EXTRA_SCALE,-1);
        boolean charging=battery.getIntExtra(BatteryManager.EXTRA_PLUGGED,0)!=0;
        if(level<0||scale<=0)return cached="Battery information unavailable";
        if(level*100L/scale<30)return cached="Battery below 30%";

        float[] temps=DeviceTelemetry.temperatures(context);
        int cpuMax=clamp(settings.getInt("max_cpu_temp_c",75),MIN_CPU_TEMP_C,MAX_CPU_TEMP_C);
        int gpuMax=clamp(settings.getInt("max_gpu_temp_c",70),MIN_GPU_TEMP_C,MAX_GPU_TEMP_C);
        cpuCooling=updateCooling(cpuCooling,temps[0],cpuMax,5f);
        gpuCooling=updateCooling(gpuCooling,temps[1],gpuMax,5f);
        batteryCooling=updateCooling(batteryCooling,temps[2],43f,3f);
        if(cpuCooling)return cached=String.format(Locale.ROOT,"Cooling CPU · %.1f°C / %d°C",temps[0],cpuMax);
        if(gpuCooling)return cached=String.format(Locale.ROOT,"Cooling GPU · %.1f°C / %d°C",temps[1],gpuMax);
        if(batteryCooling)return cached=String.format(Locale.ROOT,"Cooling battery · %.1f°C / 43°C",temps[2]);
        if(power!=null&&Build.VERSION.SDK_INT>=29&&power.getCurrentThermalStatus()>=PowerManager.THERMAL_STATUS_MODERATE)
            return cached="Cooling down · Android thermal protection";
        if(chargingOnly&&!charging)return cached="Waiting for charger";
        if(power!=null&&power.isPowerSaveMode())return cached="Battery saver enabled";
        cached=null;return null;
    }
    private static boolean updateCooling(boolean active,float value,float limit,float hysteresis){
        // A missing sensor cannot prove the device has cooled. Retain an
        // existing app-level thermal hold until a valid lower sample arrives.
        if(!Float.isFinite(value))return active;
        if(active)return value>limit-hysteresis;
        return value>=limit;
    }
    private static int clamp(int value,int min,int max){return Math.max(min,Math.min(max,value));}
}
