package org.enigmagrid.android;

import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;
import org.enigmagrid.core.ServerTimeAnchor;

/** Drive the real bounded reporter without Android or a network. */
public final class DeviceTelemetryReporterChecks {
    private static final Method SAMPLE,SEND;
    static {try{
        SAMPLE=DeviceTelemetryReporter.class.getDeclaredMethod("sample");SAMPLE.setAccessible(true);
        SEND=DeviceTelemetryReporter.class.getDeclaredMethod("send");SEND.setAccessible(true);
    }catch(Exception error){throw new ExceptionInInitializerError(error);}}
    private static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
    private static DeviceTelemetryReporter reporter(CoordinatorClient client,NetworkWorker worker,long start){
        return new DeviceTelemetryReporter(new android.content.Context(),client,"test_token_0123456789",worker,start,System.nanoTime());
    }
    private static void sample(DeviceTelemetryReporter reporter,long at)throws Exception{
        ServerTimeAnchor.currentMs=at;SAMPLE.invoke(reporter);
    }
    private static void send(DeviceTelemetryReporter reporter)throws Exception{SEND.invoke(reporter);}
    private static int queued(DeviceTelemetryReporter reporter)throws Exception{
        Field field=DeviceTelemetryReporter.class.getDeclaredField("ready");field.setAccessible(true);
        return ((ArrayDeque<?>)field.get(reporter)).size();
    }
    public static void main(String[] args)throws Exception {
        long start=System.currentTimeMillis()/5000*5000-5000;
        CoordinatorClient decimal=new CoordinatorClient();DeviceTelemetryReporter first=reporter(decimal,new NetworkWorker(),start);
        sample(first,start);sample(first,start+5000);send(first);
        check(decimal.payloads.size()==1,"Completed bucket was not sent");
        String json=TelemetryJson.json(decimal.payloads.get(0));
        check(json.contains("\"cpu_percent\":17.25"),"Decimal sample lost");first.close();

        // Alternating metadata must not turn 24 buckets into 24 requests or
        // change the original backend/sensor scope on any individual bucket.
        CoordinatorClient flap=new CoordinatorClient();NetworkWorker changing=new NetworkWorker();
        DeviceTelemetryReporter second=reporter(flap,changing,start);
        for(int i=0;i<=24;i++){
            changing.backend=i%2==0?"cpu":"vulkan-mixed2";
            DeviceTelemetry.provider=i%2==0?"unavailable":"KGSL gpubusy";
            sample(second,start+i*5000L);
        }
        check(queued(second)==24,"Expected 24 completed buckets");send(second);
        check(flap.payloads.size()==2,"Profile flap was not coalesced into two packets");
        Set<Long> starts=new HashSet<>();
        for(Map<String,Object> packet:flap.payloads){
            String profile=(String)packet.get("backend");
            List<?> buckets=(List<?>)packet.get("buckets");check(buckets.size()==12,"Packet bound or coalescing failed");
            check(TelemetryJson.json(packet).getBytes(StandardCharsets.UTF_8).length<=8192,"Oversized packet");
            long prior=-1;
            for(Object raw:buckets){long at=((Number)((Map<?,?>)raw).get("start_ms")).longValue();
                check(at>prior&&starts.add(at),"Duplicate or unordered bucket");prior=at;
                check(profile.equals(((at-start)/5000)%2==0?"cpu":"vulkan-mixed2"),"Bucket metadata changed");}
        }
        check(starts.size()==24&&queued(second)==0,"Profile backlog retained");second.close();

        CoordinatorClient retry=new CoordinatorClient();retry.failOnce=true;
        DeviceTelemetryReporter third=reporter(retry,new NetworkWorker(),start);
        sample(third,start);sample(third,start+5000);send(third);
        check(retry.payloads.size()==1,"Failed request missing");
        Field next=DeviceTelemetryReporter.class.getDeclaredField("nextAttemptMs");next.setAccessible(true);next.setLong(third,0);
        send(third);check(retry.payloads.size()==2,"Retry missing");
        check(TelemetryJson.json(retry.payloads.get(0)).equals(TelemetryJson.json(retry.payloads.get(1))),"Retry changed payload or seq");
        third.close();

        // Simulated slow HTTP cannot hold the sampler lock; 35 newer buckets
        // stay bounded and are drained when the connection completes.
        CoordinatorClient slow=new CoordinatorClient();slow.blockNext=true;
        DeviceTelemetryReporter fourth=reporter(slow,new NetworkWorker(),start);
        sample(fourth,start);sample(fourth,start+5000);
        AtomicReference<Throwable> error=new AtomicReference<>();
        Thread uploading=new Thread(()->{try{send(fourth);}catch(Throwable failure){error.set(failure);}});
        uploading.start();check(slow.entered.await(2,TimeUnit.SECONDS),"Slow upload did not start");
        for(int i=2;i<=36;i++)sample(fourth,start+i*5000L);
        check(queued(fourth)==35,"Slow request blocked sampler or lost bounded history");
        slow.release.countDown();uploading.join(2000);check(!uploading.isAlive()&&error.get()==null,"Slow upload did not complete");
        send(fourth);int delivered=0;for(Map<String,Object> packet:slow.payloads)
            delivered+=((List<?>)packet.get("buckets")).size();
        check(delivered==36&&queued(fourth)==0,"Slow HTTP lost diagnostic buckets");fourth.close();

        CoordinatorClient bounded=new CoordinatorClient();DeviceTelemetryReporter fifth=reporter(bounded,new NetworkWorker(),start);
        for(int i=0;i<=60;i++)sample(fifth,start+i*5000L);
        check(queued(fifth)==48,"Unsent diagnostic queue is not bounded");fifth.close();

        CoordinatorClient sensor=new CoordinatorClient();DeviceTelemetryReporter sixth=reporter(sensor,new NetworkWorker(),start);
        DeviceTelemetry.provider="KGSL gpubusy";DeviceTelemetry.gpu=20;sample(sixth,start);
        DeviceTelemetry.provider="unavailable";DeviceTelemetry.gpu=Float.NaN;sample(sixth,start+1000);
        DeviceTelemetry.provider="KGSL gpubusy";DeviceTelemetry.gpu=40;sample(sixth,start+2000);
        DeviceTelemetry.provider="unavailable";DeviceTelemetry.gpu=Float.NaN;sample(sixth,start+5000);
        DeviceTelemetry.provider="KGSL gpubusy";DeviceTelemetry.gpu=60;sample(sixth,start+6000);
        sample(sixth,start+10000);
        DeviceTelemetry.provider="DRM busy";DeviceTelemetry.gpu=10;sample(sixth,start+11000);
        sample(sixth,start+15000);send(sixth);
        Map<Long,Map<?,?>> measured=new HashMap<>();
        for(Map<String,Object> packet:sensor.payloads)for(Object raw:(List<?>)packet.get("buckets")){
            Map<?,?> value=(Map<?,?>)raw;measured.put(((Number)value.get("start_ms")).longValue(),value);
        }
        check(((Number)measured.get(start).get("gpu_percent")).doubleValue()==30,"Missing sample erased valid GPU readings");
        check(((Number)measured.get(start+5000).get("gpu_percent")).doubleValue()==60,"First valid sensor after missing sample lost");
        check(!measured.get(start+10000).containsKey("gpu_percent"),"Different sensors were silently averaged");
        sixth.close();DeviceTelemetry.provider="unavailable";DeviceTelemetry.gpu=Float.NaN;
        System.out.println(TelemetryJson.json(org.enigmagrid.core.Canonical.object(
            "decimal",decimal.payloads,"flap",flap.payloads,"retry",retry.payloads,"slow",slow.payloads,"sensor",sensor.payloads)));
    }
}
