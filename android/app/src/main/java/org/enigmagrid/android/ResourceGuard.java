package org.enigmagrid.android;

import android.content.*;
import android.os.*;
import java.util.function.Supplier;

/** Cached device constraints; unavailable battery readings suspend work. */
final class ResourceGuard implements Supplier<String> {
    private final Context context;
    private final PowerManager power;
    private volatile boolean chargingOnly=true;
    private long last=-1;
    private String cached="Checking battery";
    ResourceGuard(Context context){this.context=context.getApplicationContext();power=(PowerManager)context.getSystemService(Context.POWER_SERVICE);}
    void setChargingOnly(boolean value){if(chargingOnly!=value){chargingOnly=value;last=-1;}}
    @Override public synchronized String get() {
        long now=SystemClock.elapsedRealtime();if(last>=0&&now-last<1000)return cached;last=now;
        Intent battery=context.registerReceiver(null,new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        if(battery==null)return cached="Battery information unavailable";
        int level=battery.getIntExtra(BatteryManager.EXTRA_LEVEL,-1),scale=battery.getIntExtra(BatteryManager.EXTRA_SCALE,-1),temperature=battery.getIntExtra(BatteryManager.EXTRA_TEMPERATURE,-1);
        boolean charging=battery.getIntExtra(BatteryManager.EXTRA_PLUGGED,0)!=0;
        if(level<0||scale<=0||temperature<0)return cached="Battery information unavailable";
        if(level*100L/scale<30)return cached="Battery below 30%";
        if(temperature>=400)return cached="Cooling down";
        if(power!=null&&Build.VERSION.SDK_INT>=29&&power.getCurrentThermalStatus()>=PowerManager.THERMAL_STATUS_MODERATE)return cached="Cooling down";
        if(chargingOnly&&!charging)return cached="Waiting for charger";
        if(power!=null&&power.isPowerSaveMode())return cached="Battery saver enabled";
        cached=null;return null;
    }
}
