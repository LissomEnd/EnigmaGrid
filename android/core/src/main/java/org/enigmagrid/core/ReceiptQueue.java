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
        for(Map<String,Object> old:entries)if(id.equals(id(old))) {
            if(!Canonical.json(old).equals(Canonical.json(receipt)))
                throw new IllegalStateException("Conflicting receipt for the same lease");
            return;
        }
        if(entries.size()>=8)throw new IllegalStateException("Receipt queue is full");
        entries.add(new LinkedHashMap<>(receipt));persist(entries);
    }
    public synchronized void acknowledge(String leaseId) throws Exception {
        List<Map<String,Object>> entries=pending();
        if(entries.removeIf(entry->leaseId.equals(id(entry))))persist(entries);
    }
    private void persist(List<Map<String,Object>> entries) throws Exception {
        storage.save(object("server",server,"owner",owner,"submissions",entries));
    }
    private static String id(Map<String,Object> entry) {
        Object id=entry.get("lease_id");
        if(!(id instanceof String)||((String)id).isEmpty())throw new IllegalArgumentException("Missing lease ID");
        return (String)id;
    }
}
