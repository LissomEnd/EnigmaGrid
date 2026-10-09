package org.enigmagrid.core;

import java.util.*;
import static org.enigmagrid.core.Canonical.object;

/** Immutable encrypted receipt records committed before a small atomic manifest.
 * Backend writes must be durable on return. No receipt is acknowledged by this layer.
 */
public final class ChunkedBlockStorage implements ReceiptQueue.Storage {
    public interface Records {
        Map<String,Object> load(String digest)throws Exception;
        void save(String digest,Map<String,Object> record)throws Exception;
        void retain(Set<String> digests)throws Exception;
    }
    private static final String FORMAT="chunked-block-v1";
    private final ReceiptQueue.Storage manifest;
    private final Records records;
    private final int inlineBytes;
    private final Map<String,Map<String,Object>> known=new HashMap<>();
    private final Map<String,String> hashes=new HashMap<>();
    private boolean cleanupPending;
    public ChunkedBlockStorage(ReceiptQueue.Storage manifest,Records records){
        this(manifest,records,0);
    }
    public ChunkedBlockStorage(ReceiptQueue.Storage manifest,Records records,int inlineBytes){
        if(inlineBytes<0)throw new IllegalArgumentException("Negative inline bound");
        this.manifest=Objects.requireNonNull(manifest);this.records=Objects.requireNonNull(records);
        this.inlineBytes=inlineBytes;
    }
    public synchronized boolean cleanupPending(){return cleanupPending;}
    @SuppressWarnings("unchecked") private static <T>T copy(T value){
        if(value instanceof Map){Map<String,Object> result=new TreeMap<>();for(Map.Entry<?,?> entry:((Map<?,?>)value).entrySet())result.put((String)entry.getKey(),copy(entry.getValue()));return (T)result;}
        if(value instanceof List){List<Object> result=new ArrayList<>();for(Object item:(List<?>)value)result.add(copy(item));return (T)result;}
        return value;
    }
    private static String id(Map<String,Object> row){return row.get("block_id")+":"+row.get("unit");}
    private static String recordDigest(Map<String,Object> record){return Canonical.sha256(WorkBlockJson.json(copy(record)));}
    private static void digest(String value){if(value==null||!value.matches("[0-9a-f]{64}"))throw new IllegalStateException("Invalid receipt record identity");}
    @SuppressWarnings("unchecked") public synchronized Map<String,Object> load()throws Exception {
        Map<String,Object> raw=manifest.load();if(raw==null)return null;
        if(!raw.containsKey("storage_format"))return raw; // Legacy remains readable until first successful commit.
        if(!FORMAT.equals(raw.get("storage_format"))||!(raw.get("state") instanceof Map)||!(raw.get("pending_refs") instanceof List))throw new IllegalStateException("Unknown block storage format");
        Map<String,Object> state=copy((Map<String,Object>)raw.get("state"));
        List<?> refs=(List<?>)raw.get("pending_refs");if(refs.size()>128||state.containsKey("pending"))throw new IllegalStateException("Invalid block manifest");
        List<Map<String,Object>> pending=new ArrayList<>();Set<String> identities=new HashSet<>();
        Map<String,Map<String,Object>> loaded=new HashMap<>();Map<String,String> loadedHashes=new HashMap<>();
        for(Object value:refs){
            if(!(value instanceof String))throw new IllegalStateException("Invalid receipt reference");
            String hash=(String)value;digest(hash);Map<String,Object> record=records.load(hash);
            if(record==null||!hash.equals(recordDigest(record))||!Objects.equals(record.get("server"),state.get("server"))||!Objects.equals(record.get("owner"),state.get("owner"))||!(record.get("receipt") instanceof Map))throw new IllegalStateException("Missing, corrupt or foreign receipt record");
            Map<String,Object> receipt=copy((Map<String,Object>)record.get("receipt"));String identity=id(receipt);
            if(!identities.add(identity))throw new IllegalStateException("Duplicate receipt record");
            pending.add(receipt);loaded.put(identity,copy(record));loadedHashes.put(identity,hash);
        }
        state.put("pending",pending);known.clear();known.putAll(loaded);hashes.clear();hashes.putAll(loadedHashes);return state;
    }
    @SuppressWarnings("unchecked") public synchronized void save(Map<String,Object> value)throws Exception {
        Object raw=value.get("pending");if(!(raw instanceof List)||((List<?>)raw).size()>128)throw new IllegalStateException("Invalid pending receipt count");
        if(inlineBytes>0&&WorkBlockJson.json(value).getBytes(java.nio.charset.StandardCharsets.UTF_8).length<=inlineBytes){
            // Small outboxes are cheaper as one atomic write. Commit the complete
            // state before retiring any external records from the previous format.
            manifest.save(copy(value));known.clear();hashes.clear();
            try{records.retain(Collections.emptySet());cleanupPending=false;}catch(Exception deferred){cleanupPending=true;}
            return;
        }
        List<String> refs=new ArrayList<>();Set<String> identities=new HashSet<>();
        Map<String,Map<String,Object>> nextKnown=new HashMap<>();Map<String,String> nextHashes=new HashMap<>();
        for(Object entry:(List<?>)raw){
            if(!(entry instanceof Map))throw new IllegalStateException("Invalid receipt");
            Map<String,Object> row=(Map<String,Object>)entry;String identity=id(row);
            if(!identities.add(identity))throw new IllegalStateException("Duplicate pending receipt");
            Map<String,Object> record=object("server",value.get("server"),"owner",value.get("owner"),"receipt",row);
            String hash=hashes.get(identity);
            if(hash==null||!record.equals(known.get(identity))){
                hash=recordDigest(record);digest(hash);
                records.save(hash,copy(record)); // Must precede manifest commit, including first migration.
            }
            refs.add(hash);nextHashes.put(identity,hash);nextKnown.put(identity,copy(record));
        }
        Map<String,Object> state=new LinkedHashMap<>(value);state.remove("pending");
        manifest.save(object("storage_format",FORMAT,"state",copy(state),"pending_refs",refs));
        known.clear();known.putAll(nextKnown);hashes.clear();hashes.putAll(nextHashes);
        // Cleanup cannot turn a successful atomic commit into a reported failed save.
        try{records.retain(new HashSet<>(refs));cleanupPending=false;}catch(Exception deferred){cleanupPending=true;}
    }
}
