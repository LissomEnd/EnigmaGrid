package org.enigmagrid.android;

import android.content.Context;
import java.util.*;
import java.util.concurrent.*;
import org.enigmagrid.core.Canonical;
import org.enigmagrid.core.ServerTimeAnchor;

/** Best-effort private diagnostics. Neither sampling nor upload owns the work or receipt queue. */
final class DeviceTelemetryReporter implements NetworkWorker.TelemetrySession {
    private static final int MAX_PACKET_BUCKETS=12,MAX_READY_BUCKETS=48,MAX_BODY_BYTES=8192;
    private static final int MAX_SENDS_PER_CYCLE=6,MAX_SENDS_PER_MINUTE=10;
    private final Context context;
    private final CoordinatorClient client;
    private final String token,session=UUID.randomUUID().toString().replace("-","");
    private final NetworkWorker worker;
    private final DeviceTelemetry sampler=new DeviceTelemetry();
    private final ScheduledExecutorService samples=Executors.newSingleThreadScheduledExecutor(r->{Thread t=new Thread(r,"telemetry-sample");t.setDaemon(true);return t;});
    private final ScheduledExecutorService sender=Executors.newSingleThreadScheduledExecutor(r->{Thread t=new Thread(r,"telemetry-upload");t.setDaemon(true);return t;});
    private static final class BucketRecord {
        final Map<String,Object> data,metadata;
        BucketRecord(Map<String,Object> data,Map<String,Object> metadata){this.data=data;this.metadata=metadata;}
    }
    private final ArrayDeque<BucketRecord> ready=new ArrayDeque<>();
    private final ArrayDeque<Long> recentAttempts=new ArrayDeque<>();
    private final Map<String,double[]> averages=new HashMap<>();
    private Map<String,Object> bucket,bucketMetadata,inFlight;
    private final ServerTimeAnchor clock;
    private long previousJobs,previousUnits,previousComputeMs,previousPersistMs,previousUploadMs,previousLeaseMs,previousAcks;
    private boolean baseline;
    private long sequence,nextAttemptMs;
    private volatile boolean closed;

    DeviceTelemetryReporter(Context context,CoordinatorClient client,String token,NetworkWorker worker,
                            long serverTimeMs,long receivedNs){
        this.context=context.getApplicationContext();this.client=client;this.token=token;this.worker=worker;
        clock=new ServerTimeAnchor(serverTimeMs,receivedNs);
    }
    @Override public void start(){
        samples.scheduleAtFixedRate(()->{try{sample();}catch(Exception ignored){/* Diagnostics never stop work. */}},0,1,TimeUnit.SECONDS);
        // Send the first completed bucket promptly. Subsequent nominal cycles
        // remain 30 seconds apart; a late cycle may catch up with 12 buckets
        // per request without changing the per-device server request budget.
        sender.scheduleAtFixedRate(()->{try{send();}catch(Exception ignored){/* Retry the same sequence later. */}},6,30,TimeUnit.SECONDS);
    }
    private void finite(Map<String,Object> values,String key,float value){
        if(!Float.isFinite(value))return;
        double[] aggregate=averages.computeIfAbsent(key,k->new double[2]);aggregate[0]+=value;aggregate[1]++;
        values.put(key,aggregate[0]/aggregate[1]);
    }
    private static long delta(long current,long previous){return Math.max(0,current-previous);}
    private static String reason(String phase){
        if(phase==null)return "unknown";
        String lower=phase.toLowerCase(Locale.ROOT);
        if(lower.contains("comput"))return "computing";
        if(lower.contains("saved result")||lower.contains("sending"))return "outbox";
        if(lower.contains("compatible work")||lower.contains("prefetch"))return "work_wait";
        if(lower.contains("cool"))return "thermal";
        if(lower.contains("pause"))return "paused";
        return "other";
    }
    private synchronized void sample(){
        if(closed)return;
        long at=clock.nowMs(System.nanoTime()),start=at/5000*5000;
        if(bucket!=null&&((Number)bucket.get("start_ms")).longValue()==start&&
                ((Number)bucket.get("samples")).intValue()>=5)return;
        DeviceTelemetry.Sample device=sampler.sample(context);
        if(bucket!=null&&((Number)bucket.get("start_ms")).longValue()!=start){
            if(((Number)bucket.get("samples")).intValue()>0){ready.addLast(new BucketRecord(bucket,bucketMetadata));while(ready.size()>MAX_READY_BUCKETS)ready.removeFirst();}
            bucket=null;bucketMetadata=null;averages.clear();
        }
        if(bucket==null){
            bucket=Canonical.object("start_ms",start,"duration_ms",5000,"samples",0);
            bucketMetadata=metadata();
        }else{
            // One protocol bucket cannot be split into overlapping profile intervals.
            // Mark only the fields that changed, never retroactively label CPU work as GPU.
            Map<String,Object> current=metadata();
            if(!bucketMetadata.get("backend").equals(current.get("backend")))bucketMetadata.put("backend","mixed");
            if(!"unavailable".equals(current.get("gpu_provider"))){
                if("unavailable".equals(bucketMetadata.get("gpu_provider"))){
                    // Missing samples are not another sensor. Retain the source
                    // of the finite samples actually contributing to the mean.
                    bucketMetadata.put("gpu_scope",current.get("gpu_scope"));
                    bucketMetadata.put("gpu_provider",current.get("gpu_provider"));
                }else if(!bucketMetadata.get("gpu_scope").equals(current.get("gpu_scope"))||
                        !bucketMetadata.get("gpu_provider").equals(current.get("gpu_provider"))){
                    bucketMetadata.put("gpu_scope","unknown");bucketMetadata.put("gpu_provider","mixed");
                    bucket.remove("gpu_percent");averages.remove("gpu_percent");
                }
            }
        }
        int count=((Number)bucket.get("samples")).intValue();if(count>=5)return;
        finite(bucket,"cpu_percent",device.cpuUsagePercent);
        if(!"unavailable".equals(DeviceTelemetry.gpuProvider())&&
                !"mixed".equals(bucketMetadata.get("gpu_provider")))finite(bucket,"gpu_percent",device.gpuUsagePercent);
        finite(bucket,"cpu_temp_c",device.cpuTempC);finite(bucket,"gpu_temp_c",device.gpuTempC);
        finite(bucket,"battery_temp_c",device.batteryTempC);
        if(device.pssKb>=0)bucket.put("memory_bytes",device.pssKb*1024);
        bucket.put("ready_jobs",Math.max(0,worker.readyJobs()));
        bucket.put("pending_receipts",Math.max(0,worker.pendingResults()));
        bucket.put("wait_reason",reason(worker.phase()));
        bucket.put("samples",count+1);
        long jobs=worker.completedJobs(),units=worker.completedUnits(),acks=worker.acknowledgedReceipts();
        long computeMs=(long)(worker.computeSeconds()*1000),persistMs=(long)(worker.persistenceSeconds()*1000);
        long uploadMs=(long)(worker.uploadWaitSeconds()*1000),leaseMs=(long)(worker.leaseWaitSeconds()*1000);
        if(baseline){
            add(bucket,"jobs_done",delta(jobs,previousJobs));add(bucket,"units_done",delta(units,previousUnits));
            add(bucket,"compute_ms",delta(computeMs,previousComputeMs));add(bucket,"persist_ms",delta(persistMs,previousPersistMs));
            add(bucket,"upload_ms",delta(uploadMs,previousUploadMs));add(bucket,"lease_ms",delta(leaseMs,previousLeaseMs));
            add(bucket,"receipts_acked",delta(acks,previousAcks));
        }
        previousJobs=jobs;previousUnits=units;previousComputeMs=computeMs;previousPersistMs=persistMs;
        previousUploadMs=uploadMs;previousLeaseMs=leaseMs;previousAcks=acks;baseline=true;
    }
    private static void add(Map<String,Object> bucket,String key,long delta){bucket.put(key,((Number)bucket.getOrDefault(key,0)).longValue()+delta);}
    private Map<String,Object> metadata(){
        String provider=DeviceTelemetry.gpuProvider();
        return Canonical.object("backend",worker.backendName(),"cpu_scope","process",
            "gpu_scope","unavailable".equals(provider)?"unknown":"device",
            "cpu_provider","Android process CPU time","gpu_provider",provider);
    }
    private void send() throws Exception {
        // A profile transition may require a second packet in this 30-second
        // cycle. Keep the HTTP calls serial and below the server's 12/min cap.
        for(int sent=0;sent<MAX_SENDS_PER_CYCLE;sent++)if(!sendOne())return;
    }
    private boolean sendOne() throws Exception {
        Map<String,Object> payload;
        synchronized(this){
            if(closed||System.currentTimeMillis()<nextAttemptMs)return false;
            long now=System.nanoTime();
            while(!recentAttempts.isEmpty()&&now-recentAttempts.peekFirst()>=TimeUnit.MINUTES.toNanos(1))recentAttempts.removeFirst();
            if(recentAttempts.size()>=MAX_SENDS_PER_MINUTE)return false;
            if(inFlight==null){
            if(ready.isEmpty())return false;
            List<BucketRecord> records=new ArrayList<>();
            List<Map<String,Object>> selected=new ArrayList<>();
            Map<String,Object> profile=ready.peekFirst().metadata;
            // The server requires increasing, nonoverlapping times *within* a
            // packet, not contiguous buckets or chronological packet order.
            // Coalesce equal profiles even when GPU sensor/backend metadata
            // briefly alternates, without ever relabelling a bucket.
            for(BucketRecord item:ready){if(selected.size()==MAX_PACKET_BUCKETS)break;
                if(profile.equals(item.metadata)){records.add(item);selected.add(item.data);}}
            Map<String,Object> body=Canonical.object("format","device_telemetry_v1","session_id",session,"seq",sequence,
                "worker_version",BuildConfig.VERSION_NAME,"backend",profile.get("backend"),
                "cpu_scope",profile.get("cpu_scope"),"gpu_scope",profile.get("gpu_scope"),
                "cpu_provider",profile.get("cpu_provider"),"gpu_provider",profile.get("gpu_provider"),"buckets",selected);
            while(TelemetryJson.json(body).getBytes(java.nio.charset.StandardCharsets.UTF_8).length>MAX_BODY_BYTES&&selected.size()>1){
                selected.remove(selected.size()-1);records.remove(records.size()-1);
            }
            if(TelemetryJson.json(body).getBytes(java.nio.charset.StandardCharsets.UTF_8).length>MAX_BODY_BYTES){ready.removeFirst();return false;}
            for(BucketRecord item:records)ready.remove(item);
            sequence++;
            inFlight=body;
            }
            payload=inFlight;
            recentAttempts.addLast(now);
        }
        try {
            Map<String,Object> response=client.request("/api/device/telemetry/v1",payload,token);
            if(!Boolean.TRUE.equals(response.get("ok"))||((Number)response.get("accepted")).intValue()!=((List<?>)payload.get("buckets")).size())throw new java.io.IOException("Telemetry acknowledgement incomplete");
            synchronized(this){inFlight=null;nextAttemptMs=0;}
            return true;
        }catch(CoordinatorClient.HttpFailure error){
            synchronized(this){if(error.status==400||error.status==401||error.status==403||error.status==404||error.status==409||error.status==422){discardInFlight();}
            else nextAttemptMs=System.currentTimeMillis()+Math.max(30000,error.retryAfterMillis);}
        }catch(java.io.IOException failure){synchronized(this){nextAttemptMs=System.currentTimeMillis()+30000;}}
        return false;
    }
    private void discardInFlight(){
        inFlight=null;nextAttemptMs=System.currentTimeMillis()+60000;
    }
    @Override public void close(){closed=true;samples.shutdownNow();sender.shutdownNow();client.cancel();}
}
