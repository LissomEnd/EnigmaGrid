package org.enigmagrid.android;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;

/** Resume only work the user had left running, never a stopped or paused session. */
public final class ResumeReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context,Intent intent) {
        if(intent==null)return;
        String action=intent.getAction();
        if(!Intent.ACTION_BOOT_COMPLETED.equals(action)&&!Intent.ACTION_MY_PACKAGE_REPLACED.equals(action))return;
        SharedPreferences lifecycle=context.getSharedPreferences("worker-lifecycle",0);
        if(!lifecycle.getBoolean("requested",false)||lifecycle.getBoolean("paused",false))return;
        try {
            context.startForegroundService(new Intent(context,ComputeService.class).setAction("work"));
        } catch(RuntimeException denied) {
            context.getSharedPreferences("worker-status",0).edit()
                .putString("state","Android prevented automatic resume. Open the app and tap Start.").apply();
        }
    }
}
