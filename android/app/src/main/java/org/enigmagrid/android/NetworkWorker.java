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
    private boolean batchEnabled;
    private volatile String phase="Preparing account";
    private volatile boolean uploadActive;
    String phase(){String current=phase;return uploadActive&&"Computing assigned work".equals(current)?"Computing assigned work · uploading previous result":current;}
    private String acknowledgedSettings;
    boolean acknowledgedWork(){return acknowledgedWork;}
    private final org.enigmagrid.core.BoundedCrib.RowProvider rows;
    NetworkWorker(CoordinatorClient client,CredentialStore store){this(client,store,null);}
    // Older coordinators return 404 once; the worker then retains single-lease mode.
    NetworkWorker(CoordinatorClient client,CredentialStore store,org.enigmagrid.core.BoundedCrib.RowProvider rows){this(client,store,rows,true);}
    NetworkWorker(CoordinatorClient client,CredentialStore store,org.enigmagrid.core.BoundedCrib.RowProvider rows,boolean batchEnabled){this.batchEnabled=batchEnabled;this.rows=rows;this.client=client;this.heartbeat=client.fork();this.store=store;this.pending=store.pendingResults();}
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
        acknowledgedWork=false;phase="Reading saved account and receipts";
        Map<String,Object> state=store.load();
        if(state==null||!client.origin().equals(state.get("server")))throw new IllegalStateException("No matching account");
        String token=(String)state.get("device_token");
        Map<String,Object> saved=pending.load();
        // Migrate the early development format without dropping a result after a crash.
        if(saved==null && state.get("pending_submission") instanceof Map){
            saved=object("server",client.origin(),"owner",org.enigmagrid.core.Canonical.digest(token),"submission",state.get("pending_submission"));pending.save(saved);
        }
        org.enigmagrid.core.ReceiptQueue queue=new org.enigmagrid.core.ReceiptQueue(new org.enigmagrid.core.ReceiptQueue.Storage(){
            public Map<String,Object> load() throws Exception{return pending.load();}
            public void save(Map<String,Object> value) throws Exception{pending.save(value);}
        },client.origin(),org.enigmagrid.core.Canonical.digest(token));
        java.util.List<Map<String,Object>> receipts=queue.pending();
        if(!receipts.isEmpty()){
            if(state.remove("pending_submission")!=null)store.save(state);
            Map<String,Object> receipt=receipts.get(0);
            phase="Sending saved result; waiting for coordinator";
            check(control);submit(receipt,token);queue.acknowledge((String)receipt.get("lease_id"));acknowledgedWork=true;
            return "Saved result acknowledged; independent verification may still be pending";
        }
        check(control);
        phase="Synchronizing resource settings";
        if(settings!=null){
            String signature=org.enigmagrid.core.Canonical.json(object("owner",org.enigmagrid.core.Canonical.digest(token),"settings",settings));
            if(!signature.equals(acknowledgedSettings)){
                Map<String,Object> ack=client.request("/api/device/settings",object("settings",settings),token);
                if(!Boolean.TRUE.equals(ack.get("ok")))throw new IllegalStateException("Settings not acknowledged");
                acknowledgedSettings=signature;
            }
        }
        // Lease itself checks revocation and mandatory updates, and records runtime metadata.
        // Long-running work still renews its lease with the scheduled heartbeat below.
        phase="Requesting compatible work";
        Map<String,Object> assignment=null;
        if(batchEnabled)try{assignment=client.request("/api/leases",object("meta",metadata(),"count",8),token);}
        catch(CoordinatorClient.HttpFailure unsupported){if(unsupported.status!=404)throw unsupported;batchEnabled=false;}
        if(assignment==null)assignment=client.request("/api/lease",object("meta",metadata()),token);
        allowed(assignment);
        Object raw=batchEnabled?assignment.get("leases"):assignment.get("lease");
        List<?> leases=batchEnabled?(raw instanceof List?(List<?>)raw:null):(raw==null?Collections.emptyList():Collections.singletonList(raw));
        if(leases==null||leases.size()>8)throw new IllegalArgumentException("Invalid lease batch");
        if(leases.isEmpty())return "Waiting for compatible work";
        Set<String> ids=new HashSet<>();
        for(Object item:leases){
            if(!(item instanceof Map))throw new IllegalArgumentException("Invalid lease");
            Map<String,Object> lease=(Map<String,Object>)item;WorkEnvelope.validate(lease);
            if(!(lease.get("id") instanceof String)||!(lease.get("work_token") instanceof String)||!ids.add((String)lease.get("id")))throw new IllegalArgumentException("Invalid lease credentials or duplicate lease");
        }
        ScheduledExecutorService renew=Executors.newSingleThreadScheduledExecutor();
        renew.scheduleWithFixedDelay(()->{
            try{allowed(heartbeat.request("/api/heartbeat",object("meta",metadata()),token));}
            catch(IllegalStateException e){revoked=true;}
            catch(Exception e){/* Offline computation may finish; durable result waits for reconnection. */}
        },20,20,TimeUnit.SECONDS);
        ExecutorService uploads=Executors.newSingleThreadExecutor();
        Future<?> uploading=null;String uploadingId=null;
        try {
        for(Object item:leases){
        check(control);
        Map<String,Object> lease=(Map<String,Object>)item;
        phase="Computing assigned work";
        long started=System.nanoTime();Map<String,Object> result;
        result=WorkEnvelope.run(lease,()->revoked||control.getAsBoolean(),rows,Math.max(1,Math.min(32,Runtime.getRuntime().availableProcessors())));
        Map<String,Object> receipt=(Map<String,Object>)result.get("receipt");
        Map<String,Object> submission=object("lease_id",lease.get("id"),"work_token",lease.get("work_token"),"compute_seconds",Double.toString(Math.max(0.0,(System.nanoTime()-started)/1_000_000_000.0)),"candidate_count",((List<?>)receipt.get("candidates")).size(),"result",result,"meta",metadata());
        phase="Saving completed result";
        queue.append(submission);
        // At most one upload overlaps the next computation. Only this thread
        // changes the durable queue, so late acknowledgements cannot erase work.
        if(uploading!=null){awaitUpload(uploading,control);queue.acknowledge(uploadingId);acknowledgedWork=true;}
        check(control);
        uploadingId=(String)submission.get("lease_id");
        uploading=uploads.submit(()->{submit(submission,token);return null;});
        }
        if(uploading!=null){awaitUpload(uploading,control);queue.acknowledge(uploadingId);acknowledgedWork=true;}
        } finally {
            if(uploading!=null&&!uploading.isDone()){client.cancel();uploading.cancel(true);}
            uploads.shutdownNow();
            renew.shutdownNow();heartbeat.cancel();
            if(!uploads.awaitTermination(2,TimeUnit.SECONDS))
                throw new IllegalStateException("Upload did not stop; saved results retained");
        }
        return "Result acknowledged; awaiting independent verification";
    }
    private void check(BooleanSupplier control){if(revoked||Thread.currentThread().isInterrupted()||control.getAsBoolean())throw new CancellationException();}
    private void awaitUpload(Future<?> upload,BooleanSupplier control) throws Exception {
        phase="Waiting for saved result acknowledgement";
        while(true){
            check(control);
            try{upload.get(100,TimeUnit.MILLISECONDS);return;}
            catch(TimeoutException waiting){/* Keep pause/stop controls responsive. */}
            catch(ExecutionException failed){
                Throwable cause=failed.getCause();
                if(cause instanceof Exception)throw (Exception)cause;
                if(cause instanceof Error)throw (Error)cause;
                throw new IllegalStateException(cause);
            }
        }
    }
    private void allowed(Map<String,Object> response){if(Boolean.FALSE.equals(response.get("enabled"))||Boolean.TRUE.equals(response.get("quarantined")))throw new IllegalStateException("Device disabled by coordinator");if(Boolean.TRUE.equals(response.get("update_required")))throw new IllegalStateException("Coordinator requires a newer compatible client");}
    private void submit(Map<String,Object> submission,String token) throws Exception {
        uploadActive=true;
        try {
            Map<String,Object> ack=client.request("/api/complete",submission,token);
            if(!Boolean.TRUE.equals(ack.get("ok")))throw new IllegalStateException("Submission not acknowledged");
        } finally {uploadActive=false;}

    }
}
