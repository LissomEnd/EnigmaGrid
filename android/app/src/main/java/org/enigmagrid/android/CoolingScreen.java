package org.enigmagrid.android;

import android.app.Activity;
import android.app.ActivityManager;
import android.app.KeyguardManager;
import android.widget.Toast;
import android.app.AlertDialog;
import android.app.Dialog;
import android.graphics.Color;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import android.view.WindowManager;
import android.widget.TextView;

/** Awake pocket screen; does not replace Android's secure lock screen. */
final class CoolingScreen extends Dialog implements SensorEventListener {
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final Activity activity;
    private final ActivityManager activityManager;
    private boolean requestedPin, ownsPin;
    private final SensorManager sensors;
    private final Sensor proximity;
    private final TextView surface;
    private boolean covered,holding;
    private long uncoveredAt;
    private float downX,downY;
    private final int slop;
    private AlertDialog confirmation;
    private final Runnable requestExit=()->{
        if(holding&&canExit())confirmExit();
        holding=false;
    };
    CoolingScreen(Activity activity) {
        super(activity, android.R.style.Theme_Black_NoTitleBar_Fullscreen);
        this.activity=activity;
        activityManager=(ActivityManager)activity.getSystemService(Activity.ACTIVITY_SERVICE);
        sensors=(SensorManager)activity.getSystemService(Activity.SENSOR_SERVICE);
        proximity=sensors==null?null:sensors.getDefaultSensor(Sensor.TYPE_PROXIMITY);
        covered=proximity!=null;
        slop=ViewConfiguration.get(activity).getScaledTouchSlop();
        surface=new TextView(activity);
        surface.setBackgroundColor(Color.BLACK);
        surface.setTextColor(0xff666666);
        surface.setText("Pocket cooling · hold 3 seconds to exit");
        surface.setGravity(android.view.Gravity.CENTER);
        surface.setContentDescription("Pocket cooling. Uncover the proximity sensor, hold for three seconds, then confirm exit.");
        surface.setOnTouchListener((v,event)->{
            switch(event.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    cancelHold();
                    if(canExit()){
                        downX=event.getX();downY=event.getY();holding=true;
                        handler.postDelayed(requestExit,3000);
                    }
                    break;
                case MotionEvent.ACTION_MOVE:
                    if(Math.abs(event.getX()-downX)>slop||Math.abs(event.getY()-downY)>slop)cancelHold();
                    break;
                case MotionEvent.ACTION_UP:
                case MotionEvent.ACTION_CANCEL:
                case MotionEvent.ACTION_POINTER_DOWN: cancelHold();break;
            }
            return true;
        });
        setContentView(surface);
        setCanceledOnTouchOutside(false);
        setOnShowListener(dialog->{
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            getWindow().setLayout(-1,-1);
            getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN
                |View.SYSTEM_UI_FLAG_HIDE_NAVIGATION|View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
            uncoveredAt=SystemClock.elapsedRealtime();
            if(proximity!=null&&!sensors.registerListener(this,proximity,SensorManager.SENSOR_DELAY_NORMAL)){
                // If unavailable, the deliberate hold and confirmation still prevent tap exits.
                covered=false;
            }
            handler.postDelayed(()->surface.setText(""),4000);
        });
    }
    // Immersive flags alone do not block Home, Overview or the notification shade.
    // Let Android pin this task, and show the black surface only after confirmation.
    @Override public void show(){
        KeyguardManager keyguard=(KeyguardManager)activity.getSystemService(Activity.KEYGUARD_SERVICE);
        if(activityManager==null||keyguard.isKeyguardLocked())return;
        if(activityManager.getLockTaskModeState()!=ActivityManager.LOCK_TASK_MODE_NONE){
            showPinned();return;
        }
        try{
            requestedPin=true;
            activity.startLockTask();
            handler.postDelayed(this::checkPin,1000);
        }catch(RuntimeException ex){requestedPin=false;pinUnavailable();}
    }
    private void checkPin(){
        if(!requestedPin)return;
        if(activity.isFinishing()||activity.isDestroyed()){dismiss();return;}
        if(activityManager.getLockTaskModeState()!=ActivityManager.LOCK_TASK_MODE_NONE){
            ownsPin=true;requestedPin=false;showPinned();
        }else if(activity.hasWindowFocus()){
            requestedPin=false;pinUnavailable();
        }else handler.postDelayed(this::checkPin,250);
    }
    private void pinUnavailable(){
        Toast.makeText(activity,"Pocket mode needs Android screen pinning. Accept the system prompt to protect system gestures.",Toast.LENGTH_LONG).show();
    }
    private void showPinned(){super.show();handler.postDelayed(this::checkStillPinned,500);}
    private void checkStillPinned(){
        if(!isShowing())return;
        if(activityManager.getLockTaskModeState()==ActivityManager.LOCK_TASK_MODE_NONE){
            ownsPin=false;dismiss();return;
        }
        handler.postDelayed(this::checkStillPinned,500);
    }
    private boolean canExit(){return !covered&&SystemClock.elapsedRealtime()-uncoveredAt>=500;}
    private void cancelHold(){holding=false;handler.removeCallbacks(requestExit);}
    private void confirmExit(){
        if(!canExit()||confirmation!=null)return;
        confirmation=new AlertDialog.Builder(getContext()).setTitle("Exit pocket cooling?")
            .setNegativeButton("Keep cooling",(d,w)->{})
            .setPositiveButton("Exit",(d,w)->{if(canExit())dismiss();}).create();
        confirmation.setOnDismissListener(d->confirmation=null);
        confirmation.show();
    }
    @Override public void onBackPressed(){confirmExit();}
    @Override public void onSensorChanged(SensorEvent event){
        if(event.sensor.getType()!=Sensor.TYPE_PROXIMITY)return;
        boolean near=event.values[0]<Math.min(5f,proximity.getMaximumRange());
        if(covered&&!near)uncoveredAt=SystemClock.elapsedRealtime();
        covered=near;
        if(near){cancelHold();if(confirmation!=null)confirmation.dismiss();}
    }
    @Override public void onAccuracyChanged(Sensor sensor,int accuracy){}
    @Override public void dismiss(){
        requestedPin=false;
        handler.removeCallbacksAndMessages(null);
        if(ownsPin){
            ownsPin=false;
            try{activity.stopLockTask();}catch(RuntimeException ignored){}
        }
        if(sensors!=null)sensors.unregisterListener(this);
        if(confirmation!=null){confirmation.dismiss();confirmation=null;}
        super.dismiss();
    }
}
