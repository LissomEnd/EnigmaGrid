package org.enigmagrid.core;
import java.util.*;

/** Serializes claim versus release; executing leases leave this queue first. */
public final class LeaseReservations {
    public interface Release {boolean send(List<Map<String,Object>> leases)throws Exception;}
    private final ArrayDeque<Map<String,Object>> ready=new ArrayDeque<>();
    private final Set<String> held=new HashSet<>();
    private final LinkedHashSet<String> seen=new LinkedHashSet<>();
    public LeaseReservations(List<Map<String,Object>> leases){merge(leases);}
    /** Replayed active leases include work already executing or awaiting acknowledgement. */
    public synchronized int merge(List<Map<String,Object>> leases){
        Set<String> incoming=new HashSet<>();List<Map<String,Object>> fresh=new ArrayList<>();
        for(Map<String,Object> lease:leases){
            Object value=lease.get("id");
            if(!(value instanceof String)||!incoming.add((String)value))throw new IllegalArgumentException("Invalid or duplicate reservation");
            if(!seen.contains(value))fresh.add(lease);
        }
        if(leases.size()>32||held.size()+fresh.size()>32)throw new IllegalStateException("Reservation limit exceeded");
        for(Map<String,Object> lease:fresh){String id=(String)lease.get("id");seen.add(id);held.add(id);ready.addLast(lease);}
        // One allocator request is in flight at a time, with at most32 held leases.
        // Retain acknowledged IDs beyond that window to suppress stale response replays.
        Iterator<String> old=seen.iterator();while(seen.size()>256&&old.hasNext()){String id=old.next();if(!held.contains(id))old.remove();}
        return fresh.size();
    }
    public synchronized void acknowledge(String id){held.remove(id);}
    public synchronized int heldCount(){return held.size();}
    public synchronized Map<String,Object> take(){return ready.pollFirst();}
    public synchronized int size(){return ready.size();}
    public synchronized boolean releaseUnused(Release release)throws Exception {
        if(ready.isEmpty())return true;
        List<Map<String,Object>> snapshot=new ArrayList<>(ready);
        if(!release.send(snapshot))return false;
        for(Map<String,Object> lease:snapshot)held.remove((String)lease.get("id"));
        ready.clear();return true;
    }
}
