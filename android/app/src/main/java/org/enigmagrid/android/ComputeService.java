package org.enigmagrid.android;

import android.app.*;

import android.content.*;

import android.os.*;

import org.enigmagrid.core.WorkControl;

/** User-started computation, stopped explicitly; resumes requested grid work after system process reclamation. */

public final class ComputeService extends Service {

    private static final int NOTIFICATION=41;
    static volatile boolean active;

    private Thread worker;
    private PowerManager.WakeLock wakeLock;
    private volatile NetworkWorker network;
    private boolean gridMode;

    private WorkControl control;
    private boolean destroyed, stopping;

    private final Handler handler=new Handler(Looper.getMainLooper());

    private volatile String outcome;

    private final Runnable report=new Runnable(){public void run(){

        if(control==null||destroyed)return;

        if(wakeLock!=null)wakeLock.acquire(120000);
        String gate=control.status();
        String state=outcome!=null&&(gate.equals("computing")||gate.equals("CPU duty rest")||gate.equals("ready"))?outcome:gate;

        getSharedPreferences("worker-status",0).edit().putString("state",state).apply();

        ((NotificationManager)getSystemService(NOTIFICATION_SERVICE)).notify(NOTIFICATION,notification(state));

        handler.postDelayed(this,1000);

    }};

    @Override public IBinder onBind(Intent intent){return null;}

    @Override public int onStartCommand(Intent intent,int flags,int startId) {

        SharedPreferences lifecycle=getSharedPreferences("worker-lifecycle",0);
        String action=intent==null?(lifecycle.getBoolean("requested",false)?"work":"stop"):intent.getAction();

        if("stop".equals(action)){lifecycle.edit().putBoolean("requested",false).putBoolean("paused",false).commit();stopping=true;if(network!=null)network.cancel();if(control!=null)control.stop();if(worker!=null)worker.interrupt();else stopSelf();return START_NOT_STICKY;}

        if("pause".equals(action)){lifecycle.edit().putBoolean("paused",true).commit();if(control!=null)control.pause();else stopSelf();return gridMode?START_STICKY:START_NOT_STICKY;}

        if("resume".equals(action)){lifecycle.edit().putBoolean("paused",false).commit();if(control!=null&&!stopping)control.resume();else if(worker==null)stopSelf();return gridMode?START_STICKY:START_NOT_STICKY;}

        if(!"qualify".equals(action)&&!"work".equals(action)){if(worker==null)stopSelf();return START_NOT_STICKY;}

        NotificationManager manager=(NotificationManager)getSystemService(NOTIFICATION_SERVICE);

        manager.createNotificationChannel(new NotificationChannel("compute","EnigmaGrid computation",NotificationManager.IMPORTANCE_LOW));

        if(worker==null)gridMode="work".equals(action);
        startForeground(NOTIFICATION,notification(gridMode?"Connecting to grid":"Starting controlled checks"));

        if(worker!=null)return gridMode?START_STICKY:START_NOT_STICKY;

        ResourceGuard guard=new ResourceGuard(this);SharedPreferences settings=getSharedPreferences("worker-settings",0);

        control=new WorkControl(new WorkControl.SystemTiming(),()->{

            int percent=Math.max(0,Math.min(100,settings.getInt("cpu_percent",25)));

            if(percent==0)return "CPU disabled";

            control.setPercent(percent);guard.setChargingOnly(settings.getBoolean("charging_only",true));return guard.get();

        });

        lifecycle.edit().putBoolean("requested",gridMode).commit();
        if(gridMode&&lifecycle.getBoolean("paused",false))control.pause();
        wakeLock=((PowerManager)getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"EnigmaGrid:compute");
        wakeLock.setReferenceCounted(false);wakeLock.acquire(120000);
        active=true;stopping=false;outcome=null;handler.removeCallbacks(report);handler.post(report);

        worker=new Thread(()->{
            String completed;

            try(GpuProcess gpu=GpuProcess.qualificationKey().equals(settings.getString("gpu_qualification",""))?new GpuProcess(this):null){

                org.enigmagrid.core.AdaptiveRows rows=gpu==null?null:new org.enigmagrid.core.AdaptiveRows((key,offset,length)->{

                    int[] flat=gpu.rows(org.enigmagrid.core.EnigmaM4.rowInputs(key.reflector,key.greek,key.moving,key.positions,key.rings,offset,length));

                    if(flat.length!=length*26)throw new IllegalStateException("GPU row count");

                    int[][] result=new int[length][26];for(int i=0;i<length;i++)System.arraycopy(flat,i*26,result[i],0,26);return result;

                },()->Math.max(0,Math.min(100,settings.getInt("gpu_percent",0))),control,new WorkControl.SystemTiming());

                if(gridMode){
                    CredentialStore store=new CredentialStore(getApplicationContext());
                    java.util.Map<String,Object> account=store.load();
                    if(account==null)throw new IllegalStateException("Register this device from Account before starting work.");
                    CoordinatorClient client=new CoordinatorClient((String)account.get("server"));
                    while(!control.getAsBoolean()){
                        network=new NetworkWorker(client,store,rows);
                        boolean acknowledged=false;long transactionStarted=System.nanoTime();
                        try{
                            outcome=null;
                            String result=network.once(control,org.enigmagrid.core.Canonical.object("cpu_percent",Math.max(0,Math.min(100,settings.getInt("cpu_percent",25))),"gpu_percent",Math.max(0,Math.min(100,settings.getInt("gpu_percent",0))),"allow_cpu",true,"allow_gpu",rows!=null&&rows.available()));
                            acknowledged=network.acknowledgedWork();
                            outcome=result+(rows==null?"":" | GPU dispatches: "+rows.dispatches()+(rows.failed()?" (CPU fallback)":""));
                        }catch(CoordinatorClient.HttpFailure e){
                            if(e.status==401||e.status==403||e.status==422)throw new IllegalStateException("Coordinator refused the request ("+e.status+"). Saved account and results retained.");
                            outcome="Coordinator temporarily unavailable; retrying in 30 seconds";
                        }catch(java.io.IOException e){outcome="Connection unavailable; saved results retained. Retrying in 30 seconds";}
                        finally{network=null;}
                        if(rows!=null&&rows.failed())settings.edit().remove("gpu_qualification").apply();
                        long waitMillis=org.enigmagrid.core.JobPacing.delayMillis(acknowledged,(System.nanoTime()-transactionStarted)/1_000_000L);
                        for(long remaining=waitMillis;remaining>0;remaining-=100){if(control.getAsBoolean())throw new java.util.concurrent.CancellationException();Thread.sleep(Math.min(100,remaining));}
                    }
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
            catch(Exception e){completed=gridMode?"Work stopped after an error; saved results retained":"Checks failed; grid work disabled";}

            final String terminal=completed;
            handler.post(()->{
                if(destroyed)return;
                outcome=stopping?"Stopped":terminal;
                getSharedPreferences("worker-status",0).edit().putString("state",outcome).apply();
                lifecycle.edit().putBoolean("requested",false).commit();
                active=false;worker=null;handler.removeCallbacks(report);stopSelf();
            });

        },"controlled-compute");worker.start();return gridMode?START_STICKY:START_NOT_STICKY;

    }

    private Notification notification(String state) {

        PendingIntent open=PendingIntent.getActivity(this,0,new Intent(this,MainActivity.class),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);

        Notification.Builder builder=new Notification.Builder(this,"compute").setSmallIcon(android.R.drawable.ic_popup_sync).setContentTitle(gridMode?"EnigmaGrid · contributing":"EnigmaGrid · local checks").setContentText(state).setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true);

        for(String action:new String[]{getSharedPreferences("worker-lifecycle",0).getBoolean("paused",false)?"resume":"pause","stop"}) {

            PendingIntent command=PendingIntent.getService(this,action.hashCode(),new Intent(this,ComputeService.class).setAction(action),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);

            builder.addAction(new Notification.Action.Builder(null,action.substring(0,1).toUpperCase()+action.substring(1),command).build());

        }

        return builder.build();

    }

    @Override public void onDestroy(){active=false;destroyed=true;if(wakeLock!=null&&wakeLock.isHeld())wakeLock.release();if(network!=null)network.cancel();handler.removeCallbacks(report);if(control!=null)control.stop();if(worker!=null)worker.interrupt();stopForeground(STOP_FOREGROUND_REMOVE);super.onDestroy();}

}
