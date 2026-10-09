package org.enigmagrid.core;

import java.util.*;
import java.nio.charset.StandardCharsets;
import static org.enigmagrid.core.Canonical.object;

/** Negotiated block transport. HTTP success alone never removes a receipt. */
public final class WorkBlockTransport {
    private static final java.util.concurrent.atomic.AtomicLong uploadCalls=new java.util.concurrent.atomic.AtomicLong();
    private static final java.util.concurrent.atomic.AtomicLong uploadReceipts=new java.util.concurrent.atomic.AtomicLong();
    private static final java.util.concurrent.atomic.AtomicLong uploadPrepareNs=new java.util.concurrent.atomic.AtomicLong();
    private static final java.util.concurrent.atomic.AtomicLong uploadHttpNs=new java.util.concurrent.atomic.AtomicLong();
    private static final java.util.concurrent.atomic.AtomicLong uploadCommitNs=new java.util.concurrent.atomic.AtomicLong();
    private static final java.util.concurrent.atomic.AtomicLong uploadErrors=new java.util.concurrent.atomic.AtomicLong();
    /** Process aggregates only; never include block, account, result or token values. */
    public static Map<String,Object> diagnostics(){return object("calls",uploadCalls.get(),"receipts",uploadReceipts.get(),"prepare_ns",uploadPrepareNs.get(),"http_ns",uploadHttpNs.get(),"commit_ns",uploadCommitNs.get(),"errors",uploadErrors.get());}
    public interface Request { Map<String,Object> send(String path,Map<String,Object> body)throws Exception; }
    public static final String GROUP_FORMAT="bounded_result_groups_v1";
    private static final int GROUP_BODY_BYTES=768*1024;
    private static final int LEGACY_BODY_BYTES=256*1024;
    public static final class ReceiptRejected extends Exception {public ReceiptRejected(){super("Block receipt rejected; retained locally");}}
    private final WorkBlockQueue queue;private final Request request;private final boolean grouped;
    private final java.util.concurrent.atomic.AtomicLong acceptedReceipts=new java.util.concurrent.atomic.AtomicLong();
    public long acknowledgedReceipts(){return acceptedReceipts.get();}
    private final Object lifecycle=new Object();private boolean stopped;
    private void checkRunning(){if(stopped)throw new java.util.concurrent.CancellationException("Block transport stopped");}
    public void stop(){synchronized(lifecycle){stopped=true;}}
    public WorkBlockTransport recovery(){return new WorkBlockTransport(queue,request,grouped);}
    public WorkBlockTransport(WorkBlockQueue queue,Request request,boolean grouped){this.queue=queue;this.request=request;this.grouped=grouped;}
    @SuppressWarnings("unchecked") private static Map<String,Object> map(Object value) {
        if(!(value instanceof Map))throw new IllegalArgumentException("Object required");return (Map<String,Object>)value;
    }
    public Map<String,Object> allocate()throws Exception {
        String id;
        synchronized(lifecycle){checkRunning();id=queue.allocationRequest();}
        long requestedAt=System.nanoTime();
        Map<String,Object> response=request.send("/api/work-blocks",object("format",WorkBlock.FORMAT,"request_id",id));
        if(response.get("block")!=null) {
            Map<String,Object> block=map(response.get("block"));
            if(Arrays.asList("expired","released","submitted").contains(response.get("status"))) {
                synchronized(lifecycle){checkRunning();queue.allocationRetired(id,block);}return object("block",null,"wait_reason","previous_block_finished");
            }
            if(!"reserved".equals(response.get("status")))throw new IllegalArgumentException("Invalid reservation");
            synchronized(lifecycle){checkRunning();queue.allocated(id,block);}
            if(response.containsKey("valid_for_seconds")){
                queue.allocatedLifetime((String)block.get("block_id"),response.get("valid_for_seconds"),System.nanoTime()-requestedAt);
            }else refreshStatus(); // Older coordinators have no allocation lifetime.
        }
        return response;
    }
    private Map<String,Object> body(String id,List<Map<String,Object>> receipts) {
        if(!grouped)return object("format",WorkBlock.FORMAT,"block_id",id,"receipts",receipts);
        List<Object> groups=new ArrayList<>();for(int i=0;i<receipts.size();i+=8)groups.add(new ArrayList<>(receipts.subList(i,Math.min(i+8,receipts.size()))));
        return object("format",GROUP_FORMAT,"block_id",id,"groups",groups);
    }
    public int upload()throws Exception {
        synchronized(lifecycle){checkRunning();}
        long started=System.nanoTime();
        List<Map<String,Object>> pending=queue.pending();if(pending.isEmpty())return 0;
        String id=(String)pending.get(0).get("block_id");List<Map<String,Object>> receipts=new ArrayList<>();
        // Count each receipt once. Serializing every growing prefix made packing
        // a 64-result upload quadratic, while holding up the next acknowledgement.
        int wrapperBytes=WorkBlockJson.json(body(id,Collections.emptyList())).getBytes(StandardCharsets.UTF_8).length;
        int payloadBytes=0;
        for(Map<String,Object> item:pending) {
            if(!id.equals(item.get("block_id")))continue;
            Map<String,Object> receipt=new LinkedHashMap<>(item);receipt.remove("block_id");
            int rowBytes=WorkBlockJson.json(receipt).getBytes(StandardCharsets.UTF_8).length;
            int count=receipts.size()+1;
            // n-1 commas total, plus two brackets per group of at most eight.
            int separators=count-1+(grouped?2*((count+7)/8):0);
            if(wrapperBytes+payloadBytes+rowBytes+separators>(grouped?GROUP_BODY_BYTES:LEGACY_BODY_BYTES))break;
            receipts.add(receipt);payloadBytes+=rowBytes;
            if(receipts.size()==(grouped?64:8))break;
        }
        if(receipts.isEmpty())throw new IllegalArgumentException("Receipt exceeds transport bound");
        uploadPrepareNs.addAndGet(System.nanoTime()-started);
        long httpStarted=System.nanoTime();Map<String,Object> response;
        try{response=request.send(grouped?"/api/work-blocks/result-groups":"/api/work-blocks/results",body(id,receipts));}
        catch(Exception failure){uploadErrors.incrementAndGet();throw failure;}
        finally{uploadHttpNs.addAndGet(System.nanoTime()-httpStarted);}
        long commitStarted=System.nanoTime();
        if(!id.equals(response.get("block_id"))||!(response.get("results") instanceof List))throw new IllegalArgumentException("Invalid acknowledgement");
        Set<Long> expected=new HashSet<>(),seen=new HashSet<>(),accepted=new HashSet<>(),expired=new HashSet<>();boolean rejected=false;
        for(Map<String,Object> row:receipts)expected.add(((Number)row.get("unit")).longValue());
        for(Object raw:(List<?>)response.get("results")) {
            Map<String,Object> row=map(raw);Object unit=row.get("unit");
            if(!(unit instanceof Integer)&&!(unit instanceof Long))throw new IllegalArgumentException("Invalid acknowledged unit");
            long ordinal=((Number)unit).longValue();
            if(!expected.contains(ordinal)||!seen.add(ordinal))throw new IllegalArgumentException("Unexpected acknowledged unit");
            if("received".equals(row.get("status")))accepted.add(ordinal);
            else if("expired".equals(row.get("status")))expired.add(ordinal);
            else if("conflict".equals(row.get("status")))rejected=true;
            else throw new IllegalArgumentException("Unknown acknowledgement");
        }
        synchronized(lifecycle){checkRunning();queue.archiveExpired(id,expired);queue.acknowledge(id,accepted);}
        acceptedReceipts.addAndGet(accepted.size());
        uploadCommitNs.addAndGet(System.nanoTime()-commitStarted);uploadCalls.incrementAndGet();uploadReceipts.addAndGet(receipts.size());
        if(rejected)throw new ReceiptRejected();return accepted.size();
    }
    public void refreshStatus()throws Exception {
        synchronized(lifecycle){checkRunning();}
        List<String> ids=queue.identities();if(ids.isEmpty())return;
        long requestedAt=System.nanoTime();
        Map<String,Object> response=request.send("/api/work-blocks/status",object("format",WorkBlock.FORMAT,"blocks",ids));
        if(!(response.get("blocks") instanceof List))throw new IllegalArgumentException("Invalid status");
        Map<String,Map<String,Object>> states=new HashMap<>();
        for(Object raw:(List<?>)response.get("blocks")) {
            Map<String,Object> row=map(raw);String id=(String)row.get("block_id");
            if(!ids.contains(id)||states.put(id,row)!=null)throw new IllegalArgumentException("Invalid status identity");
        }
        if(states.size()!=ids.size())throw new IllegalArgumentException("Incomplete status");
        synchronized(lifecycle){checkRunning();queue.updateStatus(states,System.nanoTime()-requestedAt);}
    }
    private final Object releaseLock=new Object();
    /** The caller owns a dedicated release worker: a slow HTTP response must not
     * hold the allocation or receipt-upload connection. The descriptor stays
     * durable until the server acknowledges the idempotent release. */
    public void releaseReady()throws Exception {
        synchronized(releaseLock){
            synchronized(lifecycle){checkRunning();}
            for(String id:queue.releasable()) {
                Map<String,Object> response=request.send("/api/work-blocks/release",object("format",WorkBlock.FORMAT,"block_id",id));
                if(!id.equals(response.get("block_id"))||!Boolean.TRUE.equals(response.get("released")))throw new IllegalArgumentException("Invalid release acknowledgement");
                synchronized(lifecycle){checkRunning();queue.released(id);}
            }
        }
    }
}
