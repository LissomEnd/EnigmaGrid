package org.enigmagrid.android;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.PowerManager;
import android.provider.Settings;

/** The user's standard Android exemption, never a device-wide power override. */
final class BackgroundExecution {
    static boolean allowed(Context context) {
        PowerManager power=(PowerManager)context.getSystemService(Context.POWER_SERVICE);
        return power!=null && power.isIgnoringBatteryOptimizations(context.getPackageName());
    }

    static String summary(Context context) {
        return allowed(context)
            ? "Screen-off work allowed by Android"
            : "Android may pause work when the screen is locked";
    }

    static void request(Activity activity) {
        // Ongoing, explicitly started computation is the app's core function.
        // Android presents its own consent dialog; denial never stops the worker.
        String action=allowed(activity) ? Settings.ACTION_APPLICATION_DETAILS_SETTINGS
            : Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS;
        try {
            activity.startActivity(new Intent(action,Uri.parse("package:"+activity.getPackageName())));
        } catch (android.content.ActivityNotFoundException | SecurityException unavailable) {
            try { activity.startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)); }
            catch (android.content.ActivityNotFoundException | SecurityException noSettings) {
                android.widget.Toast.makeText(activity,"Open Android Settings > Apps > EnigmaGrid > Battery.",
                    android.widget.Toast.LENGTH_LONG).show();
            }
        }
    }

    private BackgroundExecution() {}
}
