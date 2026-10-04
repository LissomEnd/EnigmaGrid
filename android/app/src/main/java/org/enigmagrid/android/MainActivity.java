package org.enigmagrid.android;



import android.app.Activity;

import android.os.Bundle;

import android.os.Build;

import android.graphics.Color;

import android.view.View;

import android.widget.*;

import org.enigmagrid.core.EnigmaM4;



/** Development onboarding; never claims an unqualified engine is ready for work. */

public final class MainActivity extends Activity {

    private TextView status;

    private SeekBar gpuSlider;
    private final java.util.List<Button> gpuSteps=new java.util.ArrayList<>();

    private Thread qualification;

    private Thread gpuQualification;

    @Override public void onCreate(Bundle state) {

        super.onCreate(state);

        LinearLayout content = new LinearLayout(this);

        content.setOrientation(LinearLayout.VERTICAL);

        content.setPadding(dp(20), dp(24), dp(20), dp(20));

        content.setBackgroundColor(Color.rgb(8,21,34));

        content.setOnApplyWindowInsetsListener((view, insets) -> {

            view.setPadding(dp(20), Math.max(dp(20),insets.getSystemWindowInsetTop()),dp(20),

                Math.max(dp(20),insets.getSystemWindowInsetBottom())); return insets;

        });

        ScrollView scroll = new ScrollView(this); scroll.addView(content); setContentView(scroll);

        ImageView brand=new ImageView(this);brand.setImageResource(org.enigmagrid.android.R.drawable.enigmagrid_icon);

        brand.setContentDescription("EnigmaGrid rotor and connected grid");

        int iconSize=(int)(88*getResources().getDisplayMetrics().density);

        LinearLayout.LayoutParams iconLayout=new LinearLayout.LayoutParams(iconSize,iconSize);iconLayout.gravity=android.view.Gravity.CENTER_HORIZONTAL;

        content.addView(brand,iconLayout);

        label(content, "EnigmaGrid", 32);

        label(content, "Contribute on your terms", 22);

        label(content, "Android 0.4.3 • experimental volunteer computing", 15);

        label(content, "Help investigate an unresolved Enigma message. No decryption or scientific advantage is claimed.", 17);

        LinearLayout navigation=new LinearLayout(this);content.addView(navigation);

        LinearLayout controls=card(content), dashboard=card(content), diagnostics=card(content), account=card(content);

        LinearLayout[] pages={controls,dashboard,diagnostics,account};

        String[] titles={"Compute","Dashboard","Device","Account"};

        for(int index=0;index<pages.length;index++) {

            final int selected=index;Button tab=new Button(this);tab.setText(titles[index]);tab.setAllCaps(false);tab.setTextSize(12);

            navigation.addView(tab,new LinearLayout.LayoutParams(0,dp(56),1));

            tab.setOnClickListener(v->{for(int i=0;i<pages.length;i++){pages[i].setVisibility(i==selected?View.VISIBLE:View.GONE);navigation.getChildAt(i).setSelected(i==selected);}});

        }

        dashboard.setVisibility(View.GONE);diagnostics.setVisibility(View.GONE);account.setVisibility(View.GONE);navigation.getChildAt(0).setSelected(true);

        label(diagnostics, "Device compatibility", 22);

        label(diagnostics, "Android " + Build.VERSION.RELEASE + " • " + String.join(", ", Build.SUPPORTED_ABIS), 16);

        boolean vulkan = getPackageManager().hasSystemFeature("android.hardware.vulkan.compute");

        label(diagnostics, vulkan ? "Vulkan Compute detected — GPU qualification pending" : "Vulkan Compute unavailable — CPU fallback required", 16);

        TextView gpuStatus=label(diagnostics,"GPU computation has not been tested.",16);

        Button gpuTest=new Button(this);gpuTest.setText("Test Vulkan computation");diagnostics.addView(gpuTest);

        gpuTest.setOnClickListener(v->{gpuTest.setEnabled(false);gpuStatus.setText("Comparing Vulkan and CPU…");gpuQualification=new Thread(()->{

            String result;boolean passed=false;try{result=GpuQualification.run(getApplicationContext());passed=true;}catch(Exception|UnsatisfiedLinkError e){result="GPU check failed; CPU remains available. "+e.getClass().getSimpleName();}

            final boolean qualified=passed;getSharedPreferences("worker-settings",0).edit().putString("gpu_qualification",passed?GpuProcess.qualificationKey():"").apply();

            final String message=result;runOnUiThread(()->{if(!isDestroyed()){gpuStatus.setText(message);gpuTest.setEnabled(true);if(gpuSlider!=null){gpuSlider.setEnabled(qualified);for(Button step:gpuSteps)step.setEnabled(qualified);((TextView)gpuSlider.getTag()).setText("GPU: "+gpuSlider.getProgress()+"%"+(qualified?"":" — check required"));}}});

        },"gpu-qualification");gpuQualification.start();});

        status = label(diagnostics, "CPU engine checks have not run yet.", 17);

        Button test = new Button(this); test.setText("Check CPU engine"); diagnostics.addView(test);

        test.setOnClickListener(v -> {

            if (qualification != null && qualification.isAlive()) return;

            test.setEnabled(false); status.setText("Checking CPU cipher and reference search receipts…");

            qualification = new Thread(() -> {

                String result;

                try {

                    String value=EnigmaM4.crypt("AAAAA", "Bthin", "Beta", new String[]{"I","II","III"}, "AAAA", "AAAA", new String[0]);

                    if (!"BDZGO".equals(value)) throw new IllegalStateException("Reference mismatch");

                    int count=EngineQualification.run(getApplicationContext());

                    result="CPU checks passed: cipher and " + count + " complete search receipts match the reference. Encrypted storage check passed. This local check does not submit grid work.";

                } catch (Exception e) { result="CPU checks did not pass. Grid work is disabled."; }

                final String message=result;

                runOnUiThread(() -> { if (!isDestroyed()) {status.setText(message); test.setEnabled(true);} });

            }, "cipher-qualification"); qualification.start();

        });

        label(controls, "Resource controls", 22);

        android.content.SharedPreferences preferences=getSharedPreferences("worker-settings",MODE_PRIVATE);

        resourceSlider(controls,preferences,"cpu_percent","CPU",25,true);

        resourceSlider(controls,preferences,"gpu_percent","GPU",0,GpuProcess.qualificationKey().equals(preferences.getString("gpu_qualification","")));

        label(controls,"GPU assists computation after the device test passes. GPU 0% uses CPU only. CPU must stay above 0% to run the search. Percentages limit worker activity, not total device utilization.",14);

        Switch charging=new Switch(this);charging.setText("Compute only while charging");charging.setChecked(preferences.getBoolean("charging_only",true));controls.addView(charging);

        charging.setOnCheckedChangeListener((button,value)->preferences.edit().putBoolean("charging_only",value).apply());

        label(controls,"Limits apply immediately. Battery and thermal protection remain active.",14);

        Button contribute=new Button(this);contribute.setText("Start contributing");controls.addView(contribute);
        contribute.setOnClickListener(v->{
            if(Build.VERSION.SDK_INT>=33&&checkSelfPermission("android.permission.POST_NOTIFICATIONS")!=android.content.pm.PackageManager.PERMISSION_GRANTED){requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"},41);return;}
            startForegroundService(new android.content.Intent(this,ComputeService.class).setAction("work"));
        });
        Button controlled=new Button(this);controlled.setText("Run controlled local checks");controls.addView(controlled);

        controlled.setOnClickListener(v->{

            if(Build.VERSION.SDK_INT>=33&&checkSelfPermission("android.permission.POST_NOTIFICATIONS")!=android.content.pm.PackageManager.PERMISSION_GRANTED){requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"},41);return;}

            startForegroundService(new android.content.Intent(this,ComputeService.class).setAction("qualify"));

        });

        for(String action:new String[]{"pause","resume","stop"}) {

            Button button=new Button(this);button.setText(action+" computation");controls.addView(button);

            button.setOnClickListener(v->startService(new android.content.Intent(this,ComputeService.class).setAction(action)));

        }

        TextView workerState=label(controls,"Ready. Tap Start contributing to join the grid.",16);

        Button refreshWorker=new Button(this);refreshWorker.setText("Refresh computation status");controls.addView(refreshWorker);

        refreshWorker.setOnClickListener(v->workerState.setText(getSharedPreferences("worker-status",0).getString("state","Idle")));

        label(diagnostics,"Background operation",22);
        label(diagnostics,"Keep the ongoing notification enabled. Allow unrestricted battery use and auto-start in your phone settings. Android may still stop work; open the app and tap Start after a force-stop or reboot.",15);
        Button battery=new Button(this);battery.setText("Open app battery settings");diagnostics.addView(battery);
        battery.setOnClickListener(v->startActivity(new android.content.Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,android.net.Uri.parse("package:"+getPackageName()))));
        new DashboardPanel(this,dashboard);
        new AccountPanel(this,account);

    }

    private void resourceSlider(LinearLayout parent,android.content.SharedPreferences preferences,String key,String title,int initial,boolean enabled) {

        int saved=Math.max(0,Math.min(100,preferences.getInt(key,initial)));

        TextView caption=label(parent,title+": "+saved+"%"+(enabled?"":" — not qualified"),18);

        SeekBar slider=new SeekBar(this);slider.setMax(100);slider.setProgress(saved);slider.setEnabled(enabled);slider.setContentDescription(title+" usage limit");parent.addView(slider);slider.setTag(caption);if("gpu_percent".equals(key))gpuSlider=slider;

        LinearLayout steps=new LinearLayout(this);parent.addView(steps);
        for(int delta:new int[]{-5,5}){
            Button step=new Button(this);step.setText(delta<0?"−5%":"+5%");step.setContentDescription((delta<0?"Decrease ":"Increase ")+title+" limit");
            steps.addView(step,new LinearLayout.LayoutParams(0,dp(48),1));step.setEnabled(enabled);if("gpu_percent".equals(key))gpuSteps.add(step);
            step.setOnClickListener(v->{if(!slider.isEnabled())return;int value=Math.max(0,Math.min(100,slider.getProgress()+delta));slider.setProgress(value);preferences.edit().putInt(key,value).apply();});
        }
        slider.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener(){

            public void onProgressChanged(SeekBar bar,int progress,boolean fromUser){caption.setText(title+": "+progress+"%"+(progress==0?" — disabled":""));if(fromUser)preferences.edit().putInt(key,progress).apply();}

            public void onStartTrackingTouch(SeekBar bar){}

            public void onStopTrackingTouch(SeekBar bar){}

        });

    }

    @Override public void onDestroy() {

        if(qualification!=null)qualification.interrupt();

        if(gpuQualification!=null)gpuQualification.interrupt();

        super.onDestroy();

    }

    private int dp(int value){return Math.round(value*getResources().getDisplayMetrics().density);}

    private LinearLayout card(LinearLayout parent){

        LinearLayout panel=new LinearLayout(this);panel.setOrientation(LinearLayout.VERTICAL);panel.setPadding(dp(16),dp(8),dp(16),dp(16));

        android.graphics.drawable.GradientDrawable background=new android.graphics.drawable.GradientDrawable();

        background.setColor(Color.rgb(16,35,50));background.setCornerRadius(dp(20));background.setStroke(dp(1),Color.rgb(36,67,81));panel.setBackground(background);

        LinearLayout.LayoutParams layout=new LinearLayout.LayoutParams(-1,-2);layout.topMargin=dp(16);parent.addView(panel,layout);return panel;

    }

    private TextView label(LinearLayout parent, String text, int size) {

        TextView view=new TextView(this); view.setText(text); view.setTextSize(size);

        view.setTextColor(size>=22?Color.rgb(67,221,208):Color.rgb(226,237,242));

        if(size>=22)view.setTypeface(android.graphics.Typeface.DEFAULT,android.graphics.Typeface.BOLD);

        int space=(int)(getResources().getDisplayMetrics().density*(size>=22?16:8));

        view.setPadding(0,space,0,space); parent.addView(view); return view;

    }

}
