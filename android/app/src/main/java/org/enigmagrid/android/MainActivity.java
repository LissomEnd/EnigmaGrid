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
    private CoolingScreen coolingScreen;



    private TextView status;

    private final android.os.Handler uiHandler=new android.os.Handler(android.os.Looper.getMainLooper());

    private Runnable refreshControls;

    private Runnable showUpdates;

    private Runnable monitorRefresh;
    private Runnable refreshBackground;

    private DeviceTelemetry telemetry;






    private SeekBar gpuSlider;

    private final java.util.List<Button> gpuSteps=new java.util.ArrayList<>();



    private Thread qualification;



    private Thread gpuQualification;

    private static volatile boolean gpuCheckRunning;

    static volatile boolean computeStarting;

    private boolean localChecksBusy(){return gpuCheckRunning||(qualification!=null&&qualification.isAlive());}

    private void startCompute(String action){

        if(localChecksBusy()||computeStarting||ComputeService.active)return;

        computeStarting=true;

        try{startForegroundService(new android.content.Intent(this,ComputeService.class).setAction(action));}

        catch(RuntimeException failure){computeStarting=false;throw failure;}

    }



    @Override public void onCreate(Bundle state) {



        super.onCreate(state);

        UpdateJob.schedule(getApplicationContext());



        LinearLayout content = new LinearLayout(this);



        content.setOrientation(LinearLayout.VERTICAL);



        content.setPadding(dp(20), dp(24), dp(20), dp(20));



        content.setBackgroundColor(Color.rgb(8,21,34));



        content.setOnApplyWindowInsetsListener((view, insets) -> {



            view.setPadding(dp(20), Math.max(dp(20),insets.getSystemWindowInsetTop()),dp(20),



                Math.max(dp(20),insets.getSystemWindowInsetBottom())); return insets;



        });



        setContentView(content);



        ImageView brand=new ImageView(this);brand.setImageResource(org.enigmagrid.android.R.drawable.enigmagrid_icon);



        brand.setContentDescription("EnigmaGrid rotor and connected grid");



        int iconSize=(int)(48*getResources().getDisplayMetrics().density);



        LinearLayout.LayoutParams iconLayout=new LinearLayout.LayoutParams(iconSize,iconSize);iconLayout.gravity=android.view.Gravity.CENTER_HORIZONTAL;



        content.addView(brand,iconLayout);



        label(content, "EnigmaGrid", 26);







        label(content, "Android "+BuildConfig.VERSION_NAME+" • experimental volunteer computing", 15);







        HorizontalScrollView tabs=new HorizontalScrollView(this);tabs.setHorizontalScrollBarEnabled(false);

        LinearLayout navigation=new LinearLayout(this);tabs.addView(navigation);content.addView(tabs);



        ScrollView scroll=new ScrollView(this);scroll.setId(R.id.main_content_scroll);scroll.setFillViewport(true);

        LinearLayout pageBody=new LinearLayout(this);pageBody.setOrientation(LinearLayout.VERTICAL);scroll.addView(pageBody);

        content.addView(scroll,new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,0,1f));

        LinearLayout controls=card(pageBody), monitoring=card(pageBody), dashboard=card(pageBody), diagnostics=card(pageBody), account=card(diagnostics);



        label(account, "Experimental research: no confirmed decryption or demonstrated scientific advantage.", 16);

        LinearLayout[] pages={controls,monitoring,dashboard,diagnostics};



        String[] titles={"Compute","Monitor","Results","Settings"};



        for(int index=0;index<pages.length;index++) {



            final int selected=index;Button tab=new Button(this);tab.setText(titles[index]);tab.setAllCaps(false);tab.setTextSize(14);tab.setSingleLine(true);tab.setPadding(dp(16),0,dp(16),0);



            navigation.addView(tab,new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT,dp(48)));



            tab.setOnClickListener(v->{scroll.scrollTo(0,0);for(int i=0;i<pages.length;i++){pages[i].setVisibility(i==selected?View.VISIBLE:View.GONE);navigation.getChildAt(i).setSelected(i==selected);}});



        }



        monitoring.setVisibility(View.GONE);dashboard.setVisibility(View.GONE);diagnostics.setVisibility(View.GONE);navigation.getChildAt(0).setSelected(true);



        LinearLayout devicePanel=new LinearLayout(this);devicePanel.setOrientation(LinearLayout.VERTICAL);diagnostics.addView(devicePanel,0);

        label(devicePanel,"Device test",22);

        label(devicePanel,"Checks CPU correctness, GPU compatibility and the best supported parallel configuration. Stop contribution first. Existing successful GPU checks are reused.",15);

        Button deviceTest=new Button(this);deviceTest.setText("Test device");deviceTest.setAllCaps(false);devicePanel.addView(deviceTest);

        status=label(devicePanel,getSharedPreferences("worker-status",0).getString("device_test_summary","Ready to check this device."),16);

        Button detailsToggle=new Button(this);detailsToggle.setText("Show test details");detailsToggle.setAllCaps(false);devicePanel.addView(detailsToggle);

        TextView details=label(devicePanel,getSharedPreferences("worker-status",0).getString("device_test_details","No general device test recorded."),14);

        details.setVisibility(View.GONE);

        detailsToggle.setOnClickListener(v->{boolean show=details.getVisibility()!=View.VISIBLE;details.setVisibility(show?View.VISIBLE:View.GONE);detailsToggle.setText(show?"Hide test details":"Show test details");});

        deviceTest.setOnClickListener(v->{

            if(ComputeService.active||computeStarting||localChecksBusy()){status.setText("Stop contribution before running the device test. Saved results are retained.");return;}

            gpuCheckRunning=true;deviceTest.setEnabled(false);

            gpuQualification=new Thread(()->{

                String result;StringBuilder report=new StringBuilder();String stage="CPU";

                android.content.SharedPreferences limits=getSharedPreferences("worker-settings",0);

                ResourceGuard guard=new ResourceGuard(getApplicationContext(),limits);

                guard.setChargingOnly(limits.getBoolean("charging_only",true));

                java.util.function.BooleanSupplier cancel=()->{

                    if(Thread.currentThread().isInterrupted())return true;

                    String reason=guard.get();if(reason!=null)throw new org.enigmagrid.core.QualificationProtection(reason);return false;

                };

                try{

                    runOnUiThread(()->status.setText("Checking CPU and encrypted result storage..."));

                    if(cancel.getAsBoolean())throw new java.util.concurrent.CancellationException();

                    String cipher=EnigmaM4.crypt("AAAAA","Bthin","Beta",new String[]{"I","II","III"},"AAAA","AAAA",new String[0]);

                    if(!"BDZGO".equals(cipher))throw new IllegalStateException("CPU reference mismatch");

                    report.append("CPU: ").append(EngineQualification.run(getApplicationContext(),cancel)).append(" reference receipts and encrypted storage passed.\n");
                    BlockStorageQualification.run(getApplicationContext(),cancel);
                    report.append("Block storage: encrypted migration, restart and acknowledgement passed.\n");

                    stage="GPU";

                    if(!GpuProcess.qualificationKey().equals(limits.getString("gpu_qualification",""))){

                        runOnUiThread(()->status.setText("Checking GPU correctness..."));

                        report.append(GpuQualification.run(getApplicationContext())).append('\n');

                        if(!limits.edit().putString("gpu_qualification",GpuProcess.qualificationKey()).commit())throw new IllegalStateException("Cannot save GPU check");

                    }else report.append("GPU correctness: previous successful check retained.\n");

                    if(limits.getInt("cpu_percent",25)!=100||limits.getInt("gpu_percent",0)!=100){

                        result="Correctness passed. At 100/100, Start tunes GPU performance automatically.";

                    }else try(GpuProcess gpu=new GpuProcess(getApplicationContext())){

                        stage="solver";

                        if(!SolverQualification.key().equals(limits.getString("solver_qualification",""))){

                            runOnUiThread(()->status.setText("Comparing CPU and GPU solver performance..."));

                            SolverQualification.Report comparison=SolverQualification.run(gpu,guard);

                            report.append(comparison.text).append('\n');

                            android.content.SharedPreferences.Editor edit=limits.edit();
                            if(comparison.faster)edit.putString("solver_qualification",SolverQualification.key());
                            else edit.remove("solver_qualification");
                            // CPU concurrency is useful even when GPU solving is slower.
                            // Bind the result to the backend actually measured.
                            if(comparison.concurrencyQualified)edit.putInt("qualified_parallel_jobs",comparison.jobs).putString("concurrency_qualification",ConcurrencyQualification.key(comparison.faster));
                            else edit.remove("concurrency_qualification").remove("qualified_parallel_jobs");
                            if(!edit.commit())throw new IllegalStateException("Cannot save device performance check");

                        }else report.append("GPU solver: previous successful comparison retained.\n");

                        if(SolverQualification.key().equals(limits.getString("solver_qualification",""))&&!ConcurrencyQualification.key(true).equals(limits.getString("concurrency_qualification",""))){

                            stage="parallel";runOnUiThread(()->status.setText("Choosing between 1, 2 and 4 simultaneous jobs..."));

                            ConcurrencyQualification.Report parallel=ConcurrencyQualification.run(gpu,true,()->{

                                if(limits.getInt("cpu_percent",25)!=100||limits.getInt("gpu_percent",0)!=100)return "Resource settings changed";

                                return guard.get();

                            });

                            report.append(parallel.text).append('\n');

                            if(!limits.edit().putInt("qualified_parallel_jobs",parallel.jobs).putString("concurrency_qualification",ConcurrencyQualification.key(true)).commit())throw new IllegalStateException("Cannot save parallel check");

                        }

                        stage="independent lanes";
                        runOnUiThread(()->status.setText("Comparing independent CPU and GPU jobs..."));
                        IndependentLaneQualification.Report lanes=IndependentLaneQualification.run(getApplicationContext(),gpu,guard);
                        report.append(lanes.text).append('\n');
                        android.content.SharedPreferences.Editor laneEdit=limits.edit();
                        if(lanes.faster)laneEdit.putString("independent_lane_qualification",IndependentLaneQualification.key()).putInt("independent_lane_batch",lanes.batchSize).putInt("independent_lane_count",lanes.lanes);
                        else laneEdit.remove("independent_lane_qualification").remove("independent_lane_count");
                        laneEdit.remove("auto_solver_checked_key").remove("auto_solver_mode").remove("auto_solver_cohort");
                        if(!laneEdit.commit())throw new IllegalStateException("Cannot save independent lane check");
                        boolean qualified=SolverQualification.key().equals(limits.getString("solver_qualification",""));

                        result=lanes.faster?"Device ready: independent CPU and GPU jobs.":qualified?"Device ready: CPU + GPU solver, "+limits.getInt("qualified_parallel_jobs",1)+" parallel job(s).":"Device ready: CPU solver, "+limits.getInt("qualified_parallel_jobs",1)+" parallel job(s); GPU row acceleration retained.";

                    }

                }catch(Exception|UnsatisfiedLinkError error){

                    boolean interrupted=org.enigmagrid.core.QualificationProtection.interrupted(error);

                    if(!interrupted){

                        android.content.SharedPreferences.Editor edit=limits.edit();

                        if(stage.equals("GPU"))edit.remove("gpu_qualification");

                        if(stage.equals("GPU")||stage.equals("solver"))edit.remove("solver_qualification");

                        if(!stage.equals("CPU"))edit.remove("independent_lane_qualification");
                        if(!stage.equals("CPU"))edit.remove("concurrency_qualification").remove("qualified_parallel_jobs");

                        edit.commit();

                    }

                    result=interrupted?"Test interrupted by device protection or cancellation. Previous configuration retained.":"Device test failed at "+stage+". See details.";

                    report.append(error.getClass().getSimpleName()).append(": ").append(error.getMessage());

                }

                final String summary=result,full=report.toString();

                getSharedPreferences("worker-status",0).edit().putString("device_test_summary",summary).putString("device_test_details",full).apply();

                gpuCheckRunning=false;

                runOnUiThread(()->{if(!isDestroyed()){

                    status.setText(summary);details.setText(full);deviceTest.setEnabled(true);

                    boolean ready=GpuProcess.qualificationKey().equals(limits.getString("gpu_qualification",""));

                    if(gpuSlider!=null){gpuSlider.setEnabled(true);for(Button step:gpuSteps)step.setEnabled(true);((TextView)gpuSlider.getTag()).setText(resourceCaption("GPU",gpuSlider.getProgress(),limits));}

                }});

            },"device-test");gpuQualification.start();

        });



        label(controls, "Resource controls", 22);



        android.content.SharedPreferences preferences=getSharedPreferences("worker-settings",MODE_PRIVATE);



        label(monitoring,"Monitor",22);

        TextView monitorMetrics=label(monitoring,"Waiting",16);
        monitorMetrics.setSingleLine(true);
        monitorMetrics.setEllipsize(android.text.TextUtils.TruncateAt.END);
        monitorMetrics.setPadding(0,0,0,0);
        monitorMetrics.setGravity(android.view.Gravity.CENTER_VERTICAL);
        monitorMetrics.setHeight(Math.max(dp(32),(int)Math.ceil(monitorMetrics.getPaint().getFontSpacing())+dp(8)));

        label(monitoring,"CPU / GPU · last 2 minutes",15);

        TelemetryChartView usageChart=new TelemetryChartView(this,TelemetryChartView.PERCENT,"CPU","GPU");monitoring.addView(usageChart,new LinearLayout.LayoutParams(-1,dp(210)));

        label(monitoring,"Temperature",15);

        TelemetryChartView temperatureChart=new TelemetryChartView(this,true);monitoring.addView(temperatureChart,new LinearLayout.LayoutParams(-1,dp(210)));

        label(monitoring,"Units / second",15);
        TelemetryChartView unitsChart=new TelemetryChartView(this,TelemetryChartView.RATE,"Units","");monitoring.addView(unitsChart,new LinearLayout.LayoutParams(-1,dp(170)));
        label(monitoring,"Jobs / second",15);
        TelemetryChartView jobsChart=new TelemetryChartView(this,TelemetryChartView.RATE,"Jobs","");monitoring.addView(jobsChart,new LinearLayout.LayoutParams(-1,dp(170)));
        TextView queueMetrics=label(monitoring,"Ready — · Running — · To send —",14);
        TextView stageMetrics=label(monitoring,"Compute — · Save — · Network —",14);
        for(TextView metric:new TextView[]{queueMetrics,stageMetrics}){
            metric.setSingleLine(true);metric.setEllipsize(android.text.TextUtils.TruncateAt.END);
            metric.setHeight(Math.max(dp(32),(int)Math.ceil(metric.getPaint().getFontSpacing())+dp(8)));
        }

        label(diagnostics,"Temperature limits",22);
        String[] profileKeys={"auto","lane2_64","lane2_128","qualified_64"};
        String[] profileLabels={"Automatic qualified","Up to two qualified lanes · 64-result outbox","Up to two qualified lanes · adaptive outbox","Qualified lanes · 64-result outbox"};
        Button performanceProfile=new Button(this);performanceProfile.setAllCaps(false);diagnostics.addView(performanceProfile);
        String selectedProfile=preferences.getString("performance_profile","auto");
        int selectedProfileIndex=java.util.Arrays.asList(profileKeys).indexOf(selectedProfile);
        performanceProfile.setText("Performance profile: "+profileLabels[Math.max(0,selectedProfileIndex)]);
        performanceProfile.setOnClickListener(v->new android.app.AlertDialog.Builder(this)
            .setTitle("Performance profile · applies next start")
            .setItems(profileLabels,(dialog,index)->{
                preferences.edit().putString("performance_profile",profileKeys[index]).apply();
                performanceProfile.setText("Performance profile: "+profileLabels[index]);
            }).show());
        temperatureSlider(diagnostics,preferences,"max_cpu_temp_c","CPU maximum",75,ResourceGuard.MIN_CPU_TEMP_C,ResourceGuard.MAX_CPU_TEMP_C);
        temperatureSlider(diagnostics,preferences,"max_gpu_temp_c","GPU maximum",70,ResourceGuard.MIN_GPU_TEMP_C,ResourceGuard.MAX_GPU_TEMP_C);
        label(diagnostics,"Pauses to cool down. Android and battery protection stay active.",14);

        telemetry=new DeviceTelemetry();

        monitorRefresh=()->{

            DeviceTelemetry.Sample sample=telemetry.sample(getApplicationContext());

            android.content.SharedPreferences workerStatus=getSharedPreferences("worker-status",MODE_PRIVATE);

            long reportedAt=workerStatus.getLong("updated_at_elapsed_ms",0);
            long elapsed=android.os.SystemClock.elapsedRealtime();
            boolean fresh=ComputeService.active&&reportedAt>0&&elapsed>=reportedAt&&elapsed-reportedAt<=5000;
            String monitorState=fresh?workerStatus.getString("state","Waiting"):
                ComputeService.active?"Waiting for worker":"Not contributing";
            String lower=monitorState.toLowerCase(java.util.Locale.ROOT);
            String concise=lower.contains("cool")?"Cooling down":
                lower.contains("paused")?"Paused":lower.contains("stopped")?"Stopped":
                lower.contains("verification")?"Waiting for verification":
                lower.contains("comput")?"Computing":lower.contains("upload")||lower.contains("acknowledg")?"Sending results":
                lower.contains("wait")||lower.contains("request")||lower.contains("prefetch")?"Waiting for work":monitorState;
            String backend=workerStatus.getString("backend","idle");
            String engine=backend.startsWith("vulkan-mixed")?"CPU + GPU parallel":
                backend.equals("vulkan-hybrid")?"CPU + GPU solver":
                backend.equals("vulkan-rows")?"CPU + GPU rows":"CPU";
            monitorMetrics.setText(fresh?concise+" · "+engine:monitorState);
            monitorMetrics.setContentDescription(monitorState);
            queueMetrics.setText(fresh?String.format(java.util.Locale.ROOT,"Ready %d · Running %d · To send %d",workerStatus.getInt("ready_jobs",0),workerStatus.getInt("executing_jobs",0),workerStatus.getInt("pending_results",0))+(workerStatus.getInt("expired_results",0)>0?" · Expired, saved "+workerStatus.getInt("expired_results",0):""):"Ready — · Running — · To send —");
            String stages=fresh?String.format(java.util.Locale.ROOT,"Compute %.1fs · Save %.1fs · Network %.1fs",workerStatus.getFloat("compute_seconds",0),workerStatus.getFloat("persistence_seconds",0),workerStatus.getFloat("lease_wait_seconds",0)+workerStatus.getFloat("upload_wait_seconds",0)):"Compute — · Save — · Network —";
            stageMetrics.setText(stages);stageMetrics.setContentDescription(stages+". Cumulative stage times may overlap.");

            usageChart.add(sample.cpuUsagePercent,sample.gpuUsagePercent);

            temperatureChart.add(sample.cpuTempC,sample.gpuTempC);

            unitsChart.add(fresh?sample.unitsPerSecond:Float.NaN,Float.NaN);
            jobsChart.add(fresh?sample.jobsPerSecond:Float.NaN,Float.NaN);

            uiHandler.postDelayed(monitorRefresh,1000);

        };



        resourceSlider(controls,preferences,"cpu_percent","CPU",25,true);



        resourceSlider(controls,preferences,"gpu_percent","GPU",0,true);



        label(controls,"GPU is checked automatically while CPU work continues. GPU 0% uses CPU only. At 100%, EnigmaGrid adds no duty pause; available work, memory and device protection still matter.",14);



        Switch charging=new Switch(this);charging.setText("Compute only while charging");charging.setChecked(preferences.getBoolean("charging_only",true));controls.addView(charging);



        charging.setOnCheckedChangeListener((button,value)->preferences.edit().putBoolean("charging_only",value).apply());



        label(controls,"Limits apply immediately. Battery and thermal protection remain active.",14);



        Button contribute=new Button(this);contribute.setText("Start contributing");controls.addView(contribute);

        contribute.setOnClickListener(v->{

            if(localChecksBusy()||computeStarting||ComputeService.active)return;

            startCompute("work");
            if(!BackgroundExecution.allowed(this)&&
                    !getSharedPreferences("ui",0).getBoolean("background_prompted",false)){
                getSharedPreferences("ui",0).edit().putBoolean("background_prompted",true).apply();
                new android.app.AlertDialog.Builder(this)
                    .setTitle("Keep contributing with the screen off")
                    .setMessage("Allow EnigmaGrid in Android battery settings for overnight work. This can use more battery; the app's temperature and battery limits stay active. Android may pause work without this permission.")
                    .setNegativeButton("Not now",null)
                    .setPositiveButton("Allow screen-off work",(dialog,which)->BackgroundExecution.request(this))
                    .show();
                return;
            }
            // The notification permission improves visibility, but Android does not
            // require it to run this user-started foreground service.
            if(Build.VERSION.SDK_INT>=33&&
                    checkSelfPermission("android.permission.POST_NOTIFICATIONS")!=android.content.pm.PackageManager.PERMISSION_GRANTED&&
                    !getSharedPreferences("ui",0).getBoolean("notifications_prompted",false)){
                getSharedPreferences("ui",0).edit().putBoolean("notifications_prompted",true).apply();
                requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"},41);
            }

        });

        Button pauseResume=new Button(this);pauseResume.setAllCaps(false);controls.addView(pauseResume);

        Button stop=new Button(this);stop.setText("Stop");stop.setAllCaps(false);controls.addView(stop);

        pauseResume.setOnClickListener(v->{

            boolean paused=getSharedPreferences("worker-lifecycle",0).getBoolean("paused",false);

            startService(new android.content.Intent(this,ComputeService.class).setAction(paused?"resume":"pause"));

        });

        stop.setOnClickListener(v->startService(new android.content.Intent(this,ComputeService.class).setAction("stop")));

        Button cooling=new Button(this);cooling.setText("Black pocket screen");cooling.setAllCaps(false);controls.addView(cooling,0);
        cooling.setOnClickListener(v->new android.app.AlertDialog.Builder(this)
            .setTitle("Pocket screen while computing")
            .setMessage("Set the fan in REDMAGIC controls first: this app cannot command its speed through an approved Android interface. Accept Android screen pinning to block Home, recent apps and notifications. To exit, uncover the sensor, hold 3 seconds and confirm. The display stays awake; this is not the Android lock screen.")
            .setNegativeButton("Cancel",null)
            .setNeutralButton("REDMAGIC fan controls",(dialog,which)->{
                try{startActivity(new android.content.Intent("cn.nubia.fan.action.FAN_SETTINGS").setPackage("cn.nubia.fan"));}
                catch(android.content.ActivityNotFoundException unavailable){android.widget.Toast.makeText(this,"REDMAGIC fan controls are unavailable on this device.",android.widget.Toast.LENGTH_LONG).show();}
            })
            .setPositiveButton("Open black screen",(dialog,which)->{
                coolingScreen=new CoolingScreen(this);coolingScreen.show();
            }).show());

        TextView workerState=label(controls,"Ready to contribute",16);

        refreshControls=()->{

            boolean active=ComputeService.active;
            cooling.setEnabled(active);
            if(!active&&coolingScreen!=null)coolingScreen.dismiss();

            if(active)computeStarting=false;

            boolean busy=localChecksBusy();

            contribute.setEnabled(!busy&&!computeStarting);

            deviceTest.setEnabled(!active&&!computeStarting&&!busy);



            boolean paused=getSharedPreferences("worker-lifecycle",0).getBoolean("paused",false);

            contribute.setVisibility(active?View.GONE:View.VISIBLE);

            pauseResume.setVisibility(active?View.VISIBLE:View.GONE);

            stop.setVisibility(active?View.VISIBLE:View.GONE);

            pauseResume.setText(paused?"Resume":"Pause");



            workerState.setText(getSharedPreferences("worker-status",0).getString("state","Ready to contribute"));

            uiHandler.postDelayed(refreshControls,500);

        };



        label(diagnostics,"Background operation",22);
        label(diagnostics,"While contributing, the coordinator receives private five-second performance summaries about every 30 seconds: work rate, queue waits, CPU/GPU use, temperatures and memory. No result contents, credentials or app list are included.",14);

        TextView backgroundState=label(diagnostics,BackgroundExecution.summary(this),15);
        label(diagnostics,"Screen-off work needs Android battery permission. Device-specific restrictions can still apply. After a force-stop, reopen the app and tap Start.",14);

        Button battery=new Button(this);diagnostics.addView(battery);

        battery.setOnClickListener(v->BackgroundExecution.request(this));
        refreshBackground=()->{
            backgroundState.setText(BackgroundExecution.summary(this));
            battery.setText(BackgroundExecution.allowed(this)?"Android battery settings":"Allow screen-off work");
        };
        refreshBackground.run();

        TextView updateHeading=label(diagnostics,"App updates",22);

        new UpdatePanel(this,diagnostics);

        new DashboardPanel(this,dashboard);

        new AccountPanel(this,account);

        showUpdates=()->{

            navigation.getChildAt(3).performClick();

            scroll.post(()->{

                android.graphics.Rect bounds=new android.graphics.Rect();

                updateHeading.getDrawingRect(bounds);

                scroll.offsetDescendantRectToMyCoords(updateHeading,bounds);

                scroll.smoothScrollTo(0,bounds.top);

            });

        };

        openRequestedSection(getIntent());



    }



    private void openRequestedSection(android.content.Intent intent){

        if(intent!=null&&intent.getBooleanExtra("show_updates",false)&&showUpdates!=null){

            intent.removeExtra("show_updates");showUpdates.run();

        }

    }

    @Override protected void onNewIntent(android.content.Intent intent){

        super.onNewIntent(intent);setIntent(intent);openRequestedSection(intent);

    }



    private void temperatureSlider(LinearLayout parent,android.content.SharedPreferences preferences,String key,String title,int initial,int min,int max) {

        int saved=Math.max(min,Math.min(max,preferences.getInt(key,initial)));

        TextView caption=label(parent,title+": "+saved+"°C",18);

        SeekBar slider=new SeekBar(this);slider.setMin(min);slider.setMax(max);slider.setProgress(saved);slider.setContentDescription(title+" temperature limit");parent.addView(slider);

        LinearLayout steps=new LinearLayout(this);parent.addView(steps);

        for(int delta:new int[]{-1,1}){

            Button step=new Button(this);step.setText(delta<0?"−1°C":"+1°C");steps.addView(step,new LinearLayout.LayoutParams(0,dp(48),1));

            step.setOnClickListener(v->{int value=Math.max(min,Math.min(max,slider.getProgress()+delta));slider.setProgress(value);preferences.edit().putInt(key,value).apply();});

        }

        slider.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener(){

            public void onProgressChanged(SeekBar bar,int progress,boolean fromUser){caption.setText(title+": "+progress+"°C");if(fromUser)preferences.edit().putInt(key,progress).apply();}

            public void onStartTrackingTouch(SeekBar bar){}

            public void onStopTrackingTouch(SeekBar bar){}

        });

    }



    private static String resourceCaption(String title,int percent,android.content.SharedPreferences preferences){
        if("GPU".equals(title)&&!GpuProcess.qualificationKey().equals(preferences.getString("gpu_qualification",""))){
            String status=GpuProcess.qualificationKey().equals(preferences.getString("gpu_auto_failure_key",""))
                ?" \u00b7 GPU unavailable on this driver":" \u00b7 checked automatically at Start";
            return title+": "+percent+"%"+status;
        }
        return title+": "+percent+"%"+(percent==0?" \u2014 disabled":"");
    }

    private void resourceSlider(LinearLayout parent,android.content.SharedPreferences preferences,String key,String title,int initial,boolean enabled) {



        int saved=Math.max(0,Math.min(100,preferences.getInt(key,initial)));



        TextView caption=label(parent,resourceCaption(title,saved,preferences),18);



        SeekBar slider=new SeekBar(this);slider.setMax(100);slider.setProgress(saved);slider.setEnabled(enabled);slider.setContentDescription(title+" usage limit");parent.addView(slider);slider.setTag(caption);if("gpu_percent".equals(key))gpuSlider=slider;



        LinearLayout steps=new LinearLayout(this);parent.addView(steps);

        for(int delta:new int[]{-5,5}){

            Button step=new Button(this);step.setText(delta<0?"−5%":"+5%");step.setContentDescription((delta<0?"Decrease ":"Increase ")+title+" limit");

            steps.addView(step,new LinearLayout.LayoutParams(0,dp(48),1));step.setEnabled(enabled);if("gpu_percent".equals(key))gpuSteps.add(step);

            step.setOnClickListener(v->{if(!slider.isEnabled())return;int value=Math.max(0,Math.min(100,slider.getProgress()+delta));slider.setProgress(value);preferences.edit().putInt(key,value).apply();});

        }

        slider.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener(){



            public void onProgressChanged(SeekBar bar,int progress,boolean fromUser){caption.setText(resourceCaption(title,progress,preferences));if(fromUser)preferences.edit().putInt(key,progress).apply();}



            public void onStartTrackingTouch(SeekBar bar){}



            public void onStopTrackingTouch(SeekBar bar){}



        });



    }



    @Override public void onDestroy() {
        if(coolingScreen!=null)coolingScreen.dismiss();



        if(qualification!=null)qualification.interrupt();



        if(gpuQualification!=null)gpuQualification.interrupt();



        uiHandler.removeCallbacksAndMessages(null);

        super.onDestroy();



    }



    @Override protected void onResume(){

        super.onResume();
        if(refreshBackground!=null)refreshBackground.run();

        if(refreshControls!=null){uiHandler.removeCallbacks(refreshControls);uiHandler.post(refreshControls);}

        if(monitorRefresh!=null){uiHandler.removeCallbacks(monitorRefresh);uiHandler.post(monitorRefresh);}

    }

    @Override protected void onPause(){if(coolingScreen!=null&&coolingScreen.isShowing())coolingScreen.dismiss();uiHandler.removeCallbacksAndMessages(null);super.onPause();}

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
