package org.enigmagrid.android;

import android.app.*;

import android.content.*;

import android.os.*;

import org.enigmagrid.core.WorkControl;

/** User-started computation, stopped explicitly; resumes requested grid work after system process reclamation. */

public final class ComputeService extends Service {
    @Override protected void dump(java.io.FileDescriptor fd,java.io.PrintWriter writer,String[] args){
        writer.println("gpu_dispatch_diagnostics="+GpuProcess.dispatchDiagnostics());
        writer.println("queue_diagnostics="+org.enigmagrid.core.WorkBlockJson.json(org.enigmagrid.core.WorkBlockQueue.diagnostics()));
        writer.println("block_upload_diagnostics="+org.enigmagrid.core.WorkBlockJson.json(org.enigmagrid.core.WorkBlockTransport.diagnostics()));
        SharedPreferences gpuSettings=getSharedPreferences("worker-settings",0);
        writer.println("gpu_profile_diagnostics="+org.enigmagrid.core.WorkBlockJson.json(org.enigmagrid.core.Canonical.object(
            "rows_only_policy",rowsOnlyOnMeasuredSlowSolver(),
            "row_batch_keys",rowsOnlyOnMeasuredSlowSolver()?128:64,
            "cpu_limit_percent",gpuSettings.getInt("cpu_percent",25),
            "gpu_limit_percent",gpuSettings.getInt("gpu_percent",0),
            "rows_qualified",GpuProcess.qualificationKey().equals(gpuSettings.getString("gpu_qualification","")),
            "rows_driver_failed",GpuProcess.qualificationKey().equals(gpuSettings.getString("gpu_auto_failure_key","")),
            "rows_retry_remaining_ms",Math.max(0L,gpuSettings.getLong("gpu_auto_retry_after_utc_ms",0)-System.currentTimeMillis()),
            "full_solver_mode",gpuSettings.getString("auto_solver_mode","not-qualified"),
            "qualified_backend_available",network!=null&&network.gpuAvailable(),
            "promoted_rows_failed",promotedRows!=null&&promotedRows.failed())));
        android.content.SharedPreferences status=getSharedPreferences("worker-status",0);
        writer.println("worker_diagnostics="+org.enigmagrid.core.WorkBlockJson.json(org.enigmagrid.core.Canonical.object(
            "state",status.getString("state",""),"completed_jobs",status.getLong("completed_jobs",0),
            "completed_units",status.getLong("completed_units",0),"ready_jobs",status.getInt("ready_jobs",0),
            "pending_results",status.getInt("pending_results",0),"executing_jobs",status.getInt("executing_jobs",0),
            "gate_samples",new java.util.TreeMap<>(gateSamples))));
    }


    private static final int NOTIFICATION=41;
    static volatile boolean active;

    private Thread worker;
    private PowerManager.WakeLock wakeLock;
    private volatile NetworkWorker network;
    private volatile Thread automaticGpuCheck;
    private volatile GpuProcess promotedGpu;
    private volatile org.enigmagrid.core.AdaptiveRows promotedRows;
    private volatile GpuProcess activeGpu;
    private volatile org.enigmagrid.core.AdaptiveRows activeRows;
    private boolean gridMode;

    private WorkControl control;
    private volatile boolean destroyed, stopping;

    private final Handler handler=new Handler(Looper.getMainLooper());

    private volatile String outcome;
    private NetworkWorker measuredWorker;
    private long measuredAt,measuredUnits,measuredJobs;
    private final java.util.concurrent.ConcurrentHashMap<String,Long> gateSamples=new java.util.concurrent.ConcurrentHashMap<>();

    private final Runnable report=new Runnable(){public void run(){

        if(control==null||destroyed)return;

        if(wakeLock!=null)wakeLock.acquire(120000);
        String gate=control.status();
        boolean unrestricted=gate.equals("computing")||gate.equals("CPU duty rest")||gate.equals("ready");
        String category=unrestricted?"unrestricted":gate.startsWith("Cooling CPU")?"cpu_thermal":gate.startsWith("Cooling GPU")?"gpu_thermal":gate.startsWith("Cooling battery")?"battery_thermal":"other_restricted";
        gateSamples.merge(category,1L,Long::sum);
        NetworkWorker current=network;
        if(gridMode&&current!=null&&getSharedPreferences("worker-settings",0).getInt("gpu_percent",0)>0){
            SharedPreferences limits=getSharedPreferences("worker-settings",0);
            GpuProcess session=promotedGpu!=null?promotedGpu:activeGpu;
            org.enigmagrid.core.AdaptiveRows backend=promotedRows!=null?promotedRows:activeRows;
            startAutomaticGpuCheck(current,limits,control,session,backend);
        }
        String currentPhase=current!=null?current.phase():"";
        String state=unrestricted?(outcome!=null?outcome:(current!=null?currentPhase:gate)):gate;
        boolean computing=currentPhase.startsWith("Computing assigned work");
        long sampleAt=System.nanoTime();
        if(current!=measuredWorker){measuredWorker=current;measuredAt=sampleAt;measuredUnits=0;measuredJobs=0;}
        long units=current==null?0:current.completedUnits(),jobs=current==null?0:current.completedJobs();
        double interval=(sampleAt-measuredAt)/1e9;
        // Count completed work over wall time, including network idle. A short
        // job need not happen to be running at this one-second sample instant.
        float unitsPerSecond=interval>0?(float)((units-measuredUnits)/interval):0f;
        float jobsPerSecond=interval>0?(float)((jobs-measuredJobs)/interval):0f;
        measuredAt=sampleAt;measuredUnits=units;measuredJobs=jobs;

        getSharedPreferences("worker-status",0).edit().putLong("updated_at_elapsed_ms",SystemClock.elapsedRealtime()).putString("state",state)
            .putString("backend",current==null?"idle":current.backendName())
            .putFloat("units_per_second",unitsPerSecond).putFloat("jobs_per_second",jobsPerSecond)
            .putFloat("compute_units_per_second",computing&&current!=null?(float)current.unitsPerSecond():0f)
            .putFloat("compute_jobs_per_second",computing&&current!=null?(float)current.jobsPerSecond():0f)
            .putLong("completed_units",current==null?0:current.completedUnits())
            .putLong("completed_jobs",current==null?0:current.completedJobs())
            .putInt("ready_jobs",current==null?0:current.readyJobs())
            .putInt("executing_jobs",current==null?0:current.executingJobs())
            .putInt("pending_results",current==null?0:current.pendingResults())
            .putInt("expired_results",current==null?0:current.expiredResults())
            .putFloat("wall_seconds",current==null?0:(float)current.wallSeconds())
            .putFloat("compute_seconds",current==null?0:(float)current.computeSeconds())
            .putFloat("persistence_seconds",current==null?0:(float)current.persistenceSeconds())
            .putFloat("lease_wait_seconds",current==null?0:(float)current.leaseWaitSeconds())
            .putFloat("upload_wait_seconds",current==null?0:(float)current.uploadWaitSeconds()).apply();

        ((NotificationManager)getSystemService(NOTIFICATION_SERVICE)).notify(NOTIFICATION,notification(state));

        handler.postDelayed(this,1000);

    }};

    @Override public IBinder onBind(Intent intent){return null;}

    @Override public int onStartCommand(Intent intent,int flags,int startId) {

        MainActivity.computeStarting=false;
        SharedPreferences lifecycle=getSharedPreferences("worker-lifecycle",0);
        String action=intent==null?(lifecycle.getBoolean("requested",false)?"work":"stop"):intent.getAction();

        if("stop".equals(action)){lifecycle.edit().putBoolean("requested",false).putBoolean("paused",false).commit();stopping=true;if(network!=null)network.cancel();if(control!=null)control.stop();if(worker!=null)worker.interrupt();else stopSelf();return START_NOT_STICKY;}

        if("pause".equals(action)){lifecycle.edit().putBoolean("paused",true).commit();if(network!=null)network.pauseScheduling();if(control!=null)control.pause();else stopSelf();return gridMode?START_STICKY:START_NOT_STICKY;}

        if("resume".equals(action)){lifecycle.edit().putBoolean("paused",false).commit();if(network!=null)network.resumeScheduling();if(control!=null&&!stopping)control.resume();else if(worker==null)stopSelf();return gridMode?START_STICKY:START_NOT_STICKY;}

        if(!"qualify".equals(action)&&!"work".equals(action)){if(worker==null)stopSelf();return START_NOT_STICKY;}

        NotificationManager manager=(NotificationManager)getSystemService(NOTIFICATION_SERVICE);

        manager.createNotificationChannel(new NotificationChannel("compute","EnigmaGrid computation",NotificationManager.IMPORTANCE_LOW));

        if(worker==null)gridMode="work".equals(action);
        startForeground(NOTIFICATION,notification(gridMode?"Connecting to grid":"Starting controlled checks"));

        if(worker!=null)return gridMode?START_STICKY:START_NOT_STICKY;

        SharedPreferences settings=getSharedPreferences("worker-settings",0);ResourceGuard guard=new ResourceGuard(this,settings);

        control=new WorkControl(new WorkControl.SystemTiming(),()->{

            int percent=Math.max(0,Math.min(100,settings.getInt("cpu_percent",25)));

            if(percent==0)return "CPU disabled";

            control.setPercent(percent);guard.setChargingOnly(settings.getBoolean("charging_only",true));return guard.get();

        },()->(android.os.Process.getElapsedCpuTime()+GpuProcess.cpuMillis())*1_000_000L,
          Math.max(1,Runtime.getRuntime().availableProcessors()));

        lifecycle.edit().putBoolean("requested",gridMode).commit();
        if(gridMode&&lifecycle.getBoolean("paused",false))control.pause();
        wakeLock=((PowerManager)getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"EnigmaGrid:compute");
        wakeLock.setReferenceCounted(false);wakeLock.acquire(120000);
        active=true;stopping=false;outcome=null;handler.removeCallbacks(report);handler.post(report);

        worker=new Thread(()->{
            String completed;

            try(GpuProcess gpu=GpuProcess.qualificationKey().equals(settings.getString("gpu_qualification",""))?new GpuProcess(this):null){

                String laneKey=settings.getString("independent_lane_qualification","");
                boolean modernLanes=IndependentLaneQualification.key().equals(laneKey);
                boolean autoProfile=AutomaticSolverQualification.key().equals(settings.getString("auto_solver_checked_key",""));
                String autoMode=autoProfile?settings.getString("auto_solver_mode","rows"):"rows";
                boolean autoMixed="mixed2".equals(autoMode);
                boolean independentLanes=gpu!=null&&settings.getInt("gpu_percent",0)>0&&(modernLanes||IndependentLaneQualification.legacyKey().equals(laneKey)||autoMixed);
                int qualifiedLanes=modernLanes?settings.getInt("independent_lane_count",2):2;
                if(qualifiedLanes!=2&&qualifiedLanes!=4)qualifiedLanes=2;
                String performanceProfile=settings.getString("performance_profile","auto");
                if(performanceProfile.startsWith("lane2_"))qualifiedLanes=2;
                boolean solverQualified=gpu!=null&&(SolverQualification.key().equals(settings.getString("solver_qualification",""))||"hybrid".equals(autoMode));
                org.enigmagrid.core.BoundedCrib.RowProvider accelerator=gpu==null?null:new org.enigmagrid.core.BatchedRows(gpu::rows,control,rowsOnlyOnMeasuredSlowSolver()?128:64);
                if(independentLanes)accelerator=new org.enigmagrid.core.BatchedSolver(accelerator,gpu::solve,control,true).withKeyDispatch(gpu::solveKeys).withGpuOnly().withBatchSize(autoMixed?64:Math.min(128,settings.getInt("independent_lane_batch",64)));
                else if(solverQualified)accelerator=new org.enigmagrid.core.BatchedSolver(accelerator,gpu::solve,control,true).withKeyDispatch(gpu::solveKeys).withCpuShare();
                org.enigmagrid.core.AdaptiveRows rows=gpu==null?null:new org.enigmagrid.core.AdaptiveRows(accelerator,()->Math.max(0,Math.min(100,settings.getInt("gpu_percent",0))),control,new WorkControl.SystemTiming());
                activeGpu=gpu;activeRows=rows;

                if(gridMode){
                    CredentialStore store=new CredentialStore(getApplicationContext());
                    java.util.Map<String,Object> account=store.load();
                    if(account==null)throw new IllegalStateException("Register this device from Account before starting work.");
                    CoordinatorClient client=new CoordinatorClient((String)account.get("server"));
                    network=new NetworkWorker(client,store,rows);
                    final NetworkWorker activeNetwork=network;
                    network.setTelemetryFactory((token,worker,serverTimeMs,receivedNs)->
                        new DeviceTelemetryReporter(getApplicationContext(),client.fork(),token,worker,serverTimeMs,receivedNs));
                    android.app.ActivityManager.MemoryInfo memory=new android.app.ActivityManager.MemoryInfo();
                    ((android.app.ActivityManager)getSystemService(ACTIVITY_SERVICE)).getMemoryInfo(memory);
                    int profileOutboxLimit=!performanceProfile.endsWith("_64")&&!memory.lowMemory
                        &&memory.totalMem>=4L*1024*1024*1024&&memory.availMem>=1024L*1024*1024?128:64;
                    if(profileOutboxLimit==128)network.setGroupedOutboxLimit(128);
                    network.setSettingsSource(()->org.enigmagrid.core.Canonical.object("cpu_percent",Math.max(0,Math.min(100,settings.getInt("cpu_percent",25))),"gpu_percent",Math.max(0,Math.min(100,settings.getInt("gpu_percent",0))),"allow_cpu",true,"allow_gpu",activeNetwork.gpuAvailable()));
                    // A legacy synthetic CPU-only profile is not evidence of
                    // useful grid throughput. Only GPU-qualified modes retain
                    // that historical selection; CPU-only uses durable A/B/B/A.
                    if(solverQualified&&ConcurrencyQualification.key(true).equals(settings.getString("concurrency_qualification",""))){
                        int jobs=settings.getInt("qualified_parallel_jobs",1);
                        if(jobs==1||jobs==2||jobs==4)network.setParallelJobs(jobs);
                    }
                    else if(settings.getInt("cpu_percent",25)==100&&!independentLanes
                        &&Runtime.getRuntime().availableProcessors()>=2){
                        String prefix="cpu-real-abba-v1:"+BuildConfig.VERSION_CODE+":"
                            +android.os.Build.SUPPORTED_ABIS[0]+":"+Runtime.getRuntime().availableProcessors()
                            +":"+performanceProfile+":"+profileOutboxLimit;
                        network.setCpuOnlyProductionProfile(new CpuOnlyProductionProfile(prefix,new CpuOnlyProductionProfile.Cache(){
                            public Integer load(String key){int value=settings.getInt(key,0);return value==1||value==2?value:null;}
                            public void save(String key,int lanes){if(!settings.edit().putInt(key,lanes).commit())throw new IllegalStateException("Cannot retain CPU profile");}
                        }),()->{
                            if(stopping||destroyed||settings.getInt("cpu_percent",25)!=100
                                ||!performanceProfile.equals(settings.getString("performance_profile","auto")))
                                return "CPU budget changed";
                            if(lifecycle.getBoolean("paused",false))return "Contribution paused";
                            Thread gpuCheck=automaticGpuCheck;
                            if(gpuCheck!=null&&gpuCheck.isAlive())return "GPU qualification in progress";
                            android.app.ActivityManager.MemoryInfo profileMemory=new android.app.ActivityManager.MemoryInfo();
                            ((android.app.ActivityManager)getSystemService(ACTIVITY_SERVICE)).getMemoryInfo(profileMemory);
                            if(profileMemory.lowMemory||profileMemory.totalMem<2L*1024*1024*1024
                                ||profileMemory.availMem<512L*1024*1024)return "CPU lane memory headroom";
                            return guard.get();
                        });
                    }
                    if(independentLanes){network.enableIndependentGpuLane(qualifiedLanes);if(android.os.Build.VERSION.SDK_INT>=27&&(autoMixed?settings.getBoolean("auto_solver_cohort",false):settings.getInt("independent_lane_batch",64)==512))network.enableGpuCohorts(input->rows.dispatchCohort(input,gpu::solveKeys));}
                    network.enablePersistentPipeline();
                    network.startPresence(control::status,control::stop);
                    startAutomaticGpuCheck(activeNetwork,settings,control,gpu,rows);
                    try{
                    while(!control.getAsBoolean()){
                        boolean acknowledged=false;long transactionStarted=System.nanoTime();long retryMillis=-1;
                        try{
                            outcome=null;
                            String result=network.once(control,org.enigmagrid.core.Canonical.object("cpu_percent",Math.max(0,Math.min(100,settings.getInt("cpu_percent",25))),"gpu_percent",Math.max(0,Math.min(100,settings.getInt("gpu_percent",0))),"allow_cpu",true,"allow_gpu",activeNetwork.gpuAvailable()));
                            acknowledged=network.acknowledgedWork();
                            outcome=result+(rows==null?"":" | GPU "+(independentLanes?"independent solver lane":solverQualified?"bounded solver + rows":"rows only")+": "+rows.dispatches()+" dispatches"+(rows.failed()?" (CPU fallback)":""));
                        }catch(CoordinatorClient.HttpFailure e){
                            if(e.status==401||e.status==403||e.status==422)throw new IllegalStateException("Coordinator refused the request ("+e.status+"). Saved account and results retained.");
                            retryMillis=Math.max(e.status==429?1000:5000,e.retryAfterMillis);
                            outcome="Coordinator HTTP "+e.status+"; retrying in "+(retryMillis/1000)+" seconds";
                        }catch(java.io.IOException e){retryMillis=5000;outcome="Connection unavailable; saved results retained. Retrying in 5 seconds";}

                        if((rows!=null&&rows.failed())||(promotedRows!=null&&promotedRows.failed()))settings.edit().remove("gpu_qualification").apply();
                        long waitMillis=retryMillis>=0?retryMillis:org.enigmagrid.core.JobPacing.delayMillis(acknowledged,(System.nanoTime()-transactionStarted)/1_000_000L);
                        if(retryMillis<0&&!acknowledged)waitMillis=Math.max(waitMillis,network.workRetryMillis());
                        for(long remaining=waitMillis;remaining>0;remaining-=100){if(control.getAsBoolean())throw new java.util.concurrent.CancellationException();Thread.sleep(Math.min(100,remaining));}
                    }
                    }finally{
                        network.stopPresence();
                        Thread check=automaticGpuCheck;if(check!=null){check.interrupt();check.join(8000);automaticGpuCheck=null;}
                        GpuProcess promoted=promotedGpu;promotedGpu=null;if(promoted!=null)promoted.close();promotedRows=null;
                        activeGpu=null;activeRows=null;
                    }
                    network=null;
                    completed="Stopped";
                }else{
                    int count=EngineQualification.run(getApplicationContext(),control,rows);
                    completed="Controlled checks passed: "+count+(rows!=null&&rows.failed()?" · GPU failed, CPU fallback used":"");
                }

                if(rows!=null&&rows.failed())settings.edit().remove("gpu_qualification").apply();

            }

            catch(java.util.concurrent.CancellationException e){completed="Stopped";}

            catch(InterruptedException e){Thread.currentThread().interrupt();completed="Stopped";}
            catch(IllegalStateException e){completed=e.getMessage();}
            catch(Exception e){
                // Record classes and frames only: exception messages can contain
                // remote responses or account data and must not enter logcat.
                for(Throwable cause=e;cause!=null;cause=cause.getCause()){
                    android.util.Log.e("EnigmaGridWorker",cause.getClass().getName());
                    for(StackTraceElement frame:cause.getStackTrace())
                        android.util.Log.e("EnigmaGridWorker","at "+frame.toString());
                }
                completed=gridMode?"Work stopped ("+e.getClass().getSimpleName()+"); saved results retained":"Checks failed; grid work disabled";
            }

            final String terminal=completed;
            handler.post(()->{
                if(destroyed)return;
                outcome=stopping?"Stopped":terminal;
                getSharedPreferences("worker-status",0).edit().putString("state",outcome)
                    .putFloat("units_per_second",0f).putFloat("jobs_per_second",0f).apply();
                lifecycle.edit().putBoolean("requested",false).commit();
                active=false;worker=null;handler.removeCallbacks(report);stopSelf();
            });

        },"controlled-compute");worker.start();return gridMode?START_STICKY:START_NOT_STICKY;

    }

    /** Two bounded, asynchronous stages: GPU receipt parity, then measured CPU/GPU
     * solver parity. CPU grid work and durable upload continue throughout. */
    private boolean qualificationMemoryAvailable(boolean solver){return qualificationMemoryAvailable(solver,0);}
    private boolean qualificationMemoryAvailable(boolean solver,long minimumBytes){
        android.app.ActivityManager.MemoryInfo memory=new android.app.ActivityManager.MemoryInfo();
        ((android.app.ActivityManager)getSystemService(ACTIVITY_SERVICE)).getMemoryInfo(memory);
        long sharedPayload=(long)GpuSharedTransport.MAX_INTS*Integer.BYTES;
        // Four mapped/copy buffers plus the bounded Java/native qualification
        // context, on top of a reserve for the active CPU worker and Android.
        long transientBytes=4*sharedPayload+(solver?224L:96L)*1024*1024;
        long required=Math.max(minimumBytes,384L*1024*1024+transientBytes);
        return !memory.lowMemory&&memory.availMem>=required;
    }
    // Qualified full Vulkan row receipts work on Samsung SM-T500 (bengal),
    // but the optional full solver GPU pilot consistently times out there.
    // This affects solver-benchmark admission only, never GPU-row eligibility
    // or the independent driver/receipt correctness qualification.
    private static boolean rowsOnlyOnMeasuredSlowSolver(){
        return "SM-T500".equalsIgnoreCase(android.os.Build.MODEL)
            && "bengal".equalsIgnoreCase(android.os.Build.BOARD);
    }
    private synchronized void startAutomaticGpuCheck(NetworkWorker current,SharedPreferences settings,WorkControl control,
                                        GpuProcess existingGpu,org.enigmagrid.core.AdaptiveRows existingRows){
        Thread currentCheck=automaticGpuCheck;if(currentCheck!=null&&currentCheck.isAlive())return;
        if(stopping||destroyed||control.getAsBoolean())return;
        String key=GpuProcess.qualificationKey();
        if(settings.getInt("gpu_percent",0)<=0)return;
        boolean rowsNeeded=!key.equals(settings.getString("gpu_qualification",""));
        boolean solverNeeded=!rowsOnlyOnMeasuredSlowSolver()
            &&settings.getInt("cpu_percent",25)==100&&settings.getInt("gpu_percent",0)==100
            &&!AutomaticSolverQualification.key().equals(settings.getString("auto_solver_checked_key",""));
        if(!rowsNeeded&&!solverNeeded)return;
        if(rowsNeeded&&(key.equals(settings.getString("gpu_auto_failure_key",""))
            ||System.currentTimeMillis()<settings.getLong("gpu_auto_retry_after_utc_ms",0)))return;
        if(System.currentTimeMillis()<settings.getLong("auto_solver_retry_after_utc_ms",0)&&!rowsNeeded)return;
        // Keep a physical-memory reserve while the CPU worker and a separate
        // Vulkan service are live. The solver stage needs more transient space
        // than row parity; recheck after rows instead of using a stale sample.
        if(!qualificationMemoryAvailable(false))return;
        automaticGpuCheck=new Thread(()->{
            Thread self=Thread.currentThread();
            Runnable timeout=self::interrupt;
            handler.postDelayed(timeout,110_000);
            boolean rowsPassed=!rowsNeeded;
            try{
                GpuProcess session=existingGpu;
                if(rowsNeeded){
                    // Full fixture receipt parity; no real campaign result is consumed.
                    GpuQualification.run(getApplicationContext());
                    if(Thread.currentThread().isInterrupted()||control.getAsBoolean()||stopping)return;
                    if(!settings.edit().putString("gpu_qualification",key).remove("gpu_auto_failure_key").remove("gpu_auto_retry_after_utc_ms").commit())return;
                    rowsPassed=true;
                    session=new GpuProcess(getApplicationContext());
                    org.enigmagrid.core.AdaptiveRows qualified=new org.enigmagrid.core.AdaptiveRows(
                        new org.enigmagrid.core.BatchedRows(session::rows,control,rowsOnlyOnMeasuredSlowSolver()?128:64),
                        ()->Math.max(0,Math.min(100,settings.getInt("gpu_percent",0))),control,new WorkControl.SystemTiming());
                    if(Thread.currentThread().isInterrupted()||control.getAsBoolean()||stopping){session.close();return;}
                    promotedGpu=session;promotedRows=qualified;
                    current.promoteQualifiedRows(qualified);
                    // Each qualification stage has its own strict 110-second watchdog.
                    handler.removeCallbacks(timeout);handler.postDelayed(timeout,110_000);
                }
                if(session==null&&rowsPassed){
                    session=new GpuProcess(getApplicationContext());
                    org.enigmagrid.core.AdaptiveRows qualified=new org.enigmagrid.core.AdaptiveRows(
                        new org.enigmagrid.core.BatchedRows(session::rows,control,rowsOnlyOnMeasuredSlowSolver()?128:64),
                        ()->Math.max(0,Math.min(100,settings.getInt("gpu_percent",0))),control,new WorkControl.SystemTiming());
                    promotedGpu=session;promotedRows=qualified;current.promoteQualifiedRows(qualified);
                }
                if(!solverNeeded||settings.getInt("cpu_percent",25)!=100||settings.getInt("gpu_percent",0)!=100){
                    if(rowsOnlyOnMeasuredSlowSolver())getSharedPreferences("worker-status",0).edit()
                        .putString("gpu_profile_reason","Vulkan rows independently qualified; full GPU solver benchmark skipped after measured timeout on this chipset").apply();
                    return;
                }
                if(!qualificationMemoryAvailable(true))throw new org.enigmagrid.core.QualificationProtection("Qualification memory headroom");
                final GpuProcess measured=session;
                if(measured==null)return;
                ResourceGuard protection=new ResourceGuard(getApplicationContext(),settings);
                protection.setChargingOnly(settings.getBoolean("charging_only",true));
                AutomaticSolverQualification.Report pilot=AutomaticSolverQualification.run(measured,protection);
                if(Thread.currentThread().isInterrupted()||control.getAsBoolean()||stopping)return;
                String mode=pilot.mixedFaster?"mixed2":pilot.solverFaster?"hybrid":"rows";
                if(!settings.edit().putString("auto_solver_checked_key",AutomaticSolverQualification.key())
                    .putString("auto_solver_mode",mode).putBoolean("auto_solver_cohort",false)
                    .remove("auto_solver_retry_after_utc_ms").commit())return;
                getSharedPreferences("worker-status",0).edit().putString("gpu_profile_reason",pilot.reason).apply();
                if(!pilot.solverFaster&&!pilot.mixedFaster)return;
                org.enigmagrid.core.BatchedSolver solver=new org.enigmagrid.core.BatchedSolver(
                    new org.enigmagrid.core.BatchedRows(measured::rows,control),measured::solve,control,true)
                    .withKeyDispatch(measured::solveKeys);
                if(pilot.mixedFaster)solver=solver.withGpuOnly().withBatchSize(64);
                else solver=solver.withCpuShare();
                org.enigmagrid.core.AdaptiveRows selected=new org.enigmagrid.core.AdaptiveRows(solver,
                    ()->Math.max(0,Math.min(100,settings.getInt("gpu_percent",0))),control,new WorkControl.SystemTiming());
                promotedRows=selected;
                current.promoteQualifiedSolver(selected,pilot.mixedFaster,null);
                if(pilot.mixedFaster&&qualificationMemoryAvailable(true,1024L*1024*1024)&&android.os.Build.VERSION.SDK_INT>=27){
                    handler.removeCallbacks(timeout);handler.postDelayed(timeout,110_000);
                    try{
                        CohortQualification.run(measured,()->Thread.currentThread().isInterrupted()||control.getAsBoolean());
                        if(!Thread.currentThread().isInterrupted()&&!control.getAsBoolean()&&!stopping){
                            current.enableGpuCohorts(input->selected.dispatchCohort(input,measured::solveKeys));
                            settings.edit().putBoolean("auto_solver_cohort",true).apply();
                        }
                    }catch(Exception|UnsatisfiedLinkError optionalCohortUnavailable){
                        // The already verified independent two-lane profile remains valid.
                    }
                }
            }catch(org.enigmagrid.core.QualificationProtection protectedDevice){
                // Charging, memory or thermal protection is transient. CPU work continues.
                settings.edit().putLong(rowsPassed?"auto_solver_retry_after_utc_ms":"gpu_auto_retry_after_utc_ms",System.currentTimeMillis()+5*60_000L).apply();
            }catch(java.util.concurrent.CancellationException stoppedCheck){
                // Pause/stop/Android process lifecycle may cancel qualification.
                if(!stopping&&!destroyed)settings.edit().putLong(rowsPassed?"auto_solver_retry_after_utc_ms":"gpu_auto_retry_after_utc_ms",System.currentTimeMillis()+30*60_000L).apply();
            }catch(Exception|UnsatisfiedLinkError failure){
                if(!Thread.currentThread().isInterrupted()&&!control.getAsBoolean()){
                    String message=failure.getMessage()==null?"":failure.getMessage().toLowerCase(java.util.Locale.ROOT);
                    boolean deterministic=failure instanceof UnsatisfiedLinkError||message.contains("mismatch")
                        ||message.contains("invalid")||message.contains("gpu result size")||message.contains("unexpected gpu batch");
                    if(!rowsPassed){
                        if(deterministic)settings.edit().putString("gpu_auto_failure_key",key).apply();
                        else settings.edit().putLong("gpu_auto_retry_after_utc_ms",System.currentTimeMillis()+30*60_000L).apply();
                    }else if(deterministic){
                        // Solver failure leaves the separately verified GPU rows intact.
                        settings.edit().putString("auto_solver_checked_key",AutomaticSolverQualification.key())
                            .putString("auto_solver_mode","rows").putBoolean("auto_solver_cohort",false).apply();
                        getSharedPreferences("worker-status",0).edit().putString("gpu_profile_reason","GPU solver parity unavailable; verified GPU rows retained").apply();
                    }else settings.edit().putLong("auto_solver_retry_after_utc_ms",System.currentTimeMillis()+30*60_000L).apply();
                }
                android.util.Log.w("EnigmaGridGpu","Automatic GPU check: "+failure.getClass().getSimpleName());
            }finally{handler.removeCallbacks(timeout);}
        },"gpu-first-use-check");
        automaticGpuCheck.start();
    }

    private Notification notification(String state) {

        PendingIntent open=PendingIntent.getActivity(this,0,new Intent(this,MainActivity.class),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);

        Notification.Builder builder=new Notification.Builder(this,"compute").setSmallIcon(android.R.drawable.ic_popup_sync).setContentTitle(gridMode?"EnigmaGrid · contributing":"EnigmaGrid · local checks").setContentText(state).setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true);

        for(String action:new String[]{getSharedPreferences("worker-lifecycle",0).getBoolean("paused",false)?"resume":"pause","stop"}) {

            PendingIntent command=PendingIntent.getService(this,action.hashCode(),new Intent(this,ComputeService.class).setAction(action),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);

            builder.addAction(new Notification.Action.Builder(null,action.substring(0,1).toUpperCase(java.util.Locale.ROOT)+action.substring(1),command).build());

        }

        return builder.build();

    }

    @Override public void onDestroy(){MainActivity.computeStarting=false;active=false;destroyed=true;if(wakeLock!=null&&wakeLock.isHeld())wakeLock.release();if(network!=null)network.cancel();Thread gpuCheck=automaticGpuCheck;if(gpuCheck!=null)gpuCheck.interrupt();handler.removeCallbacks(report);if(control!=null)control.stop();if(worker!=null)worker.interrupt();stopForeground(STOP_FOREGROUND_REMOVE);super.onDestroy();}

}
