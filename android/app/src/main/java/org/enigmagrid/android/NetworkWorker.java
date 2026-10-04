package org.enigmagrid.android;

import java.util.*;
import java.util.concurrent.*;
import java.util.function.BooleanSupplier;
import org.enigmagrid.core.WorkEnvelope;
import static org.enigmagrid.core.Canonical.object;

/** One lease transaction. Completed results are durable before transmission. */
final class NetworkWorker {
    private final CoordinatorClient client,heartbeat;
    private final CredentialStore store,pending;
    private volatile boolean revoked;
    private boolean acknowledgedWork;
    boolean acknowledgedWork(){return acknowledgedWork;}
    private final org.enigmagrid.core.BoundedCrib.RowProvider rows;
    NetworkWorker(CoordinatorClient client,CredentialStore store){this(client,store,null);}
    NetworkWorker(CoordinatorClient client,CredentialStore store,org.enigmagrid.core.BoundedCrib.RowProvider rows){this.rows=rows;this.client=client;this.heartbeat=client.fork();this.store=store;this.pending=store.pendingResults();}
    private Map<String,Object> metadata(){
        Map<String,Object> meta=Enrollment.metadata();
        if(rows instanceof org.enigmagrid.core.AdaptiveRows&&((org.enigmagrid.core.AdaptiveRows)rows).available()){
            meta.put("capabilities",Arrays.asList("cpu","bounded_crib_v1","gpu"));
            meta.put("gpus",Arrays.asList(object("vendor","Vulkan","name","Qualified Vulkan compute","memory_mb",0)));
        }
        return meta;
    }
    void cancel(){revoked=true;client.cancel();heartbeat.cancel();}
    @SuppressWarnings("unchecked")
    String once(BooleanSupplier control) throws Exception {return once(control,null);}
    @SuppressWarnings("unchecked")
    String once(BooleanSupplier control,Map<String,Object> settings) throws Exception {
        Map<String,Object> state=store.load();
        if(state==null||!client.origin().equals(state.get("server")))throw new IllegalStateException("No matching account");
        String token=(String)state.get("device_token");
        Map<String,Object> saved=pending.load();
        // Migrate the early development format without dropping a result after a crash.
        if(saved==null && state.get("pending_submission") instanceof Map){
            saved=object("server",client.origin(),"owner",org.enigmagrid.core.Canonical.digest(token),"submission",state.get("pending_submission"));pending.save(saved);
        }
        if(saved!=null){
            if(!client.origin().equals(saved.get("server"))||!org.enigmagrid.core.Canonical.digest(token).equals(saved.get("owner")))throw new IllegalStateException("Saved result belongs to a different account; preserved locally");
            if(!(saved.get("submission") instanceof Map))throw new IllegalStateException("Invalid saved result; preserved locally");
            if(state.remove("pending_submission")!=null)store.save(state);
            check(control);submit((Map<String,Object>)saved.get("submission"),token);acknowledgedWork=true;
            return "Saved result acknowledged; independent verification may still be pending";
        }
        check(control);
        if(settings!=null)client.request("/api/device/settings",object("settings",settings),token);
        Map<String,Object> health=heartbeat.request("/api/heartbeat",object("meta",metadata()),token);
        allowed(health);
        Map<String,Object> assignment=client.request("/api/lease",object("meta",metadata()),token);allowed(assignment);
        Object raw=assignment.get("lease");if(raw==null)return "Waiting for compatible work";
        if(!(raw instanceof Map))throw new IllegalArgumentException("Invalid lease");
        Map<String,Object> lease=(Map<String,Object>)raw;WorkEnvelope.validate(lease);
        if(!(lease.get("id") instanceof String)||!(lease.get("work_token") instanceof String))throw new IllegalArgumentException("Missing lease credentials");
        ScheduledExecutorService renew=Executors.newSingleThreadScheduledExecutor();
        renew.scheduleWithFixedDelay(()->{
            try{allowed(heartbeat.request("/api/heartbeat",object("meta",metadata()),token));}
            catch(IllegalStateException e){revoked=true;}
            catch(Exception e){/* Offline computation may finish; durable result waits for reconnection. */}
        },20,20,TimeUnit.SECONDS);
        long started=System.nanoTime();Map<String,Object> result;
        try{result=WorkEnvelope.run(lease,()->revoked||control.getAsBoolean(),rows,Math.max(1,Math.min(32,Runtime.getRuntime().availableProcessors())));}
        finally{renew.shutdownNow();heartbeat.cancel();}
        Map<String,Object> receipt=(Map<String,Object>)result.get("receipt");
        Map<String,Object> submission=object("lease_id",lease.get("id"),"work_token",lease.get("work_token"),"compute_seconds",Math.max(0,(System.nanoTime()-started)/1_000_000_000L),"candidate_count",((List<?>)receipt.get("candidates")).size(),"result",result,"meta",metadata());
        pending.save(object("server",client.origin(),"owner",org.enigmagrid.core.Canonical.digest(token),"submission",submission));
        check(control);submit(submission,token);acknowledgedWork=true;
        return "Result acknowledged; awaiting independent verification";
    }
    private void check(BooleanSupplier control){if(revoked||Thread.currentThread().isInterrupted()||control.getAsBoolean())throw new CancellationException();}
    private void allowed(Map<String,Object> response){if(Boolean.FALSE.equals(response.get("enabled"))||Boolean.TRUE.equals(response.get("quarantined")))throw new IllegalStateException("Device disabled by coordinator");if(Boolean.TRUE.equals(response.get("update_required")))throw new IllegalStateException("Coordinator requires a newer compatible client");}
    private void submit(Map<String,Object> submission,String token) throws Exception {
        Map<String,Object> ack=client.request("/api/complete",submission,token);
        if(!Boolean.TRUE.equals(ack.get("ok")))throw new IllegalStateException("Submission not acknowledged");
        pending.clear();
    }
}
