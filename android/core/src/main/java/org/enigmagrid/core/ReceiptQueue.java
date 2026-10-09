package org.enigmagrid.core;

import java.util.*;
import static org.enigmagrid.core.Canonical.object;

/** Bounded durable outbox. Persistence succeeds before any transition is returned. */
public final class ReceiptQueue {
    public interface Storage {
        Map<String,Object> load() throws Exception;
        void save(Map<String,Object> value) throws Exception;
    }
    private final Storage storage;
    private final String server, owner;
    private final Set<String> confirmed=new HashSet<>();
    private final Set<String> reserved=new HashSet<>();
    private static final int RESERVED_BYTES=512*1024;
    public ReceiptQueue(Storage storage,String server,String owner) {
        this.storage=Objects.requireNonNull(storage);
        this.server=Objects.requireNonNull(server);this.owner=Objects.requireNonNull(owner);
    }
    @SuppressWarnings("unchecked")
    public synchronized List<Map<String,Object>> pending() throws Exception {
        Map<String,Object> saved=storage.load();
        if(saved==null)return new ArrayList<>();
        if(!server.equals(saved.get("server"))||!owner.equals(saved.get("owner")))
            throw new IllegalStateException("Saved receipts belong to another account");
        Object raw=saved.get("submissions");
        if(raw==null&&saved.get("submission") instanceof Map)raw=Collections.singletonList(saved.get("submission"));
        if(!(raw instanceof List)||((List<?>)raw).size()>8)
            throw new IllegalStateException("Invalid receipt queue");
        List<Map<String,Object>> result=new ArrayList<>();Set<String> ids=new HashSet<>();
        for(Object entry:(List<?>)raw) {
            if(!(entry instanceof Map))throw new IllegalStateException("Invalid receipt");
            Map<String,Object> receipt=(Map<String,Object>)entry;
            if(!ids.add(id(receipt)))throw new IllegalStateException("Duplicate receipt");
            result.add(new LinkedHashMap<>(receipt));
        }
        return result;
    }
    public synchronized void append(Map<String,Object> receipt) throws Exception {
        String id=id(receipt);List<Map<String,Object>> entries=pending();
        entries.removeIf(entry->confirmed.contains(id(entry)));
        for(Map<String,Object> old:entries)if(id.equals(id(old))) {
            if(!Canonical.json(old).equals(Canonical.json(receipt)))
                throw new IllegalStateException("Conflicting receipt for the same lease");
            reserved.remove(id);
            return;
        }
        if(entries.size()>=8)throw new IllegalStateException("Receipt queue is full");
        entries.add(new LinkedHashMap<>(receipt));persist(entries);
    }
    /** Persist the new result and remove only an already acknowledged predecessor atomically. */
    public synchronized void advance(Map<String,Object> receipt,String acknowledgedLeaseId) throws Exception {
        String nextId=id(receipt);
        if(nextId.equals(acknowledgedLeaseId))throw new IllegalArgumentException("Same receipt transition");
        List<Map<String,Object>> entries=pending();
        boolean existing=false;
        for(Map<String,Object> old:entries)if(nextId.equals(id(old))) {
            if(!Canonical.json(old).equals(Canonical.json(receipt)))throw new IllegalStateException("Conflicting receipt");
            existing=true;
        }
        entries.removeIf(entry->acknowledgedLeaseId.equals(id(entry)));
        if(!existing){if(entries.size()>=8)throw new IllegalStateException("Receipt queue is full");entries.add(new LinkedHashMap<>(receipt));}
        persist(entries);
    }
    public synchronized void acknowledge(String leaseId) throws Exception {
        List<Map<String,Object>> entries=pending();
        if(entries.removeIf(entry->leaseId.equals(id(entry))))persist(entries);
    }
    public synchronized boolean hasCapacity() throws Exception {
        List<Map<String,Object>> entries=pending();
        entries.removeIf(entry->confirmed.contains(id(entry)));
        return entries.size()+reserved.size()<8 && encodedBytes(entries)+(reserved.size()+1L)*RESERVED_BYTES<=8L*1024*1024;
    }
    /** Atomically claim one result slot and 512 KiB (above the 256 KiB HTTP body limit) before starting a lease. */
    public synchronized boolean reserve(String leaseId) throws Exception {
        if(leaseId==null||leaseId.isEmpty())throw new IllegalArgumentException("Missing lease ID");
        if(reserved.contains(leaseId))return false;
        for(Map<String,Object> entry:pending())if(leaseId.equals(id(entry)))return false;
        if(!hasCapacity())return false;
        reserved.add(leaseId);return true;
    }
    /** Cancellation releases only the in-memory claim, never a durable result. */
    public synchronized void releaseReservation(String leaseId){reserved.remove(leaseId);}
    public synchronized int reservedCount(){return reserved.size();}
    public synchronized int unacknowledgedCount() throws Exception {
        int count=0;for(Map<String,Object> entry:pending())if(!confirmed.contains(id(entry)))count++;return count;
    }
    private void persist(List<Map<String,Object>> entries) throws Exception {
        Set<String> outstanding=new HashSet<>(reserved);
        for(Map<String,Object> entry:entries){
            if(outstanding.remove(id(entry)) && Canonical.json(entry).getBytes(java.nio.charset.StandardCharsets.UTF_8).length>RESERVED_BYTES)
                throw new IllegalStateException("Receipt exceeded its reserved byte capacity");
        }
        if(entries.size()+outstanding.size()>8)throw new IllegalStateException("Receipt slots are reserved");
        if(encodedBytes(entries)+outstanding.size()*(long)RESERVED_BYTES>8L*1024*1024)
            throw new IllegalStateException("Receipt queue byte limit reached");
        storage.save(object("server",server,"owner",owner,"submissions",entries));
        reserved.retainAll(outstanding);
        Set<String> remaining=new HashSet<>();for(Map<String,Object> entry:entries)remaining.add(id(entry));
        confirmed.retainAll(remaining);
    }
    private int encodedBytes(List<Map<String,Object>> entries){
        return Canonical.json(object("server",server,"owner",owner,"submissions",entries)).getBytes(java.nio.charset.StandardCharsets.UTF_8).length;
    }
    /** An HTTP acknowledgement may be folded into the next durable append.
     * A crash before that write only replays an already accepted receipt. */
    public synchronized void confirm(String leaseId) throws Exception {
        for(Map<String,Object> entry:pending())if(leaseId.equals(id(entry))){confirmed.add(leaseId);return;}
    }
    public synchronized void flushConfirmed() throws Exception {
        if(confirmed.isEmpty())return;
        List<Map<String,Object>> entries=pending();entries.removeIf(entry->confirmed.contains(id(entry)));persist(entries);
    }
    private static String id(Map<String,Object> entry) {
        Object id=entry.get("lease_id");
        if(!(id instanceof String)||((String)id).isEmpty())throw new IllegalArgumentException("Missing lease ID");
        return (String)id;
    }
}
