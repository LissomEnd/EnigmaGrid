package org.enigmagrid.core;

import java.util.*;
import java.nio.charset.StandardCharsets;
import static org.enigmagrid.core.Canonical.object;

/** Atomic block cursor and outbox; compute reservations share the network lock. */
public final class WorkBlockQueue {
    public static final class CapacityException extends IllegalStateException {
        public CapacityException(){super("Block storage full");}
    }
    private final ReceiptQueue.Storage storage;
    private final String server,owner;
    private final int limit;
    // This queue is the only writer for its encrypted store. Every mutation starts
    // from read()'s private copy and replaces this snapshot only after durable save.
    // A new queue instance always reloads disk, preserving crash/replay behavior.
    private Map<String,Object> committed;
    private int committedBytes;
    private ReceiptQueue.Storage expiredStorage;
    private final java.util.function.LongSupplier clock;
    private final Map<String,Long> deadlines=new HashMap<>();
    private final Map<String,WorkBlock.Prepared> prepared=new LinkedHashMap<>();
    private final Map<String,Set<Long>> computing=new HashMap<>();
    private int computingCount(){int count=0;for(Set<Long> units:computing.values())count+=units.size();return count;}
    private static Set<Long> ahead(Map<String,Object> item){
        Set<Long> result=new TreeSet<>();Object values=item.get("completed_ahead");
        if(values!=null)for(Object value:(List<?>)values)result.add(((Number)value).longValue());
        return result;
    }
    private final Map<String,Map<String,Object>> confirmed=new HashMap<>();
    private static String receiptId(Map<String,Object> row){return row.get("block_id")+":"+row.get("unit");}
    private volatile long persistenceNanos;
    private static final java.util.concurrent.atomic.AtomicLong windowCalls=new java.util.concurrent.atomic.AtomicLong(),windowNanos=new java.util.concurrent.atomic.AtomicLong(),windowSizePasses=new java.util.concurrent.atomic.AtomicLong(),windowClaims=new java.util.concurrent.atomic.AtomicLong(),saveCalls=new java.util.concurrent.atomic.AtomicLong(),saveNanos=new java.util.concurrent.atomic.AtomicLong(),saveErrors=new java.util.concurrent.atomic.AtomicLong(),loadCalls=new java.util.concurrent.atomic.AtomicLong(),loadNanos=new java.util.concurrent.atomic.AtomicLong(),cacheHits=new java.util.concurrent.atomic.AtomicLong(),envelopeCalls=new java.util.concurrent.atomic.AtomicLong(),envelopeNanos=new java.util.concurrent.atomic.AtomicLong(),descriptorPreparations=new java.util.concurrent.atomic.AtomicLong();
    public static Map<String,Object> diagnostics(){return object("claim_window_calls",windowCalls.get(),"claim_window_elapsed_ns",windowNanos.get(),"claim_window_size_passes",windowSizePasses.get(),"claim_window_claims",windowClaims.get(),"storage_calls",saveCalls.get(),"storage_elapsed_ns",saveNanos.get(),"storage_errors",saveErrors.get(),"load_calls",loadCalls.get(),"load_elapsed_ns",loadNanos.get(),"cache_hits",cacheHits.get(),"envelope_calls",envelopeCalls.get(),"envelope_elapsed_ns",envelopeNanos.get(),"descriptor_preparations",descriptorPreparations.get());}
    public double persistenceSeconds(){return persistenceNanos/1e9;}
    private static final int MAX_BYTES=8*1024*1024,RESERVE=512*1024;
    public WorkBlockQueue(ReceiptQueue.Storage storage,String server,String owner,boolean grouped) {
        this(storage,server,owner,grouped,grouped?64:8,System::nanoTime);
    }
    public WorkBlockQueue(ReceiptQueue.Storage storage,String server,String owner,boolean grouped,java.util.function.LongSupplier clock) {
        this(storage,server,owner,grouped,grouped?64:8,clock);
    }
    /** The larger durable window is opt-in for devices with enough memory and storage headroom.
     * HTTP uploads remain individually bounded to 64 grouped receipts. */
    public WorkBlockQueue(ReceiptQueue.Storage storage,String server,String owner,boolean grouped,int pendingLimit,java.util.function.LongSupplier clock) {
        this.storage=Objects.requireNonNull(storage);this.server=Objects.requireNonNull(server);
        if(pendingLimit!=(grouped?64:8)&&!(grouped&&pendingLimit==128))throw new IllegalArgumentException("Unsupported durable outbox limit");
        this.owner=Objects.requireNonNull(owner);this.limit=pendingLimit;this.clock=Objects.requireNonNull(clock);
    }
    @SuppressWarnings("unchecked") private static <T> T copy(T value) {
        if(value instanceof Map) {
            Map<String,Object> result=new LinkedHashMap<>();
            for(Map.Entry<?,?> e:((Map<?,?>)value).entrySet())result.put((String)e.getKey(),copy(e.getValue()));
            return (T)result;
        }
        if(value instanceof List) {
            List<Object> result=new ArrayList<>();for(Object item:(List<?>)value)result.add(copy(item));return (T)result;
        }
        return value;
    }
    @SuppressWarnings("unchecked") private static List<Map<String,Object>> rows(Map<String,Object> state,String key) {
        return (List<Map<String,Object>>)state.get(key);
    }
    /** Borrowed under this queue's monitor; never mutate or return to callers. */
    private Map<String,Object> stored() throws Exception {
        if(committed!=null){cacheHits.incrementAndGet();return committed;}
        long began=System.nanoTime();Map<String,Object> state;
        try{state=storage.load();}finally{loadCalls.incrementAndGet();loadNanos.addAndGet(System.nanoTime()-began);}
        if(state==null)return object("version",1,"server",server,"owner",owner,"blocks",new ArrayList<>(),"pending",new ArrayList<>());
        if(!server.equals(state.get("server"))||!owner.equals(state.get("owner"))||!(Integer.valueOf(1).equals(state.get("version"))||Integer.valueOf(2).equals(state.get("version"))))
            throw new IllegalStateException("Block queue account or format mismatch");
        committed=copy(state);committedBytes=bytes(committed);return committed;
    }
    // Read-only view under the queue monitor. Filter acknowledged rows without
    // copying every receipt/candidate when merely reserving the next unit.
    private Map<String,Object> view() throws Exception {
        Map<String,Object> state=stored();
        if(confirmed.isEmpty())return state;
        Map<String,Object> filtered=new LinkedHashMap<>(state);
        List<Map<String,Object>> pending=new ArrayList<>();
        for(Map<String,Object> row:rows(state,"pending"))
            if(!row.equals(confirmed.get(receiptId(row))))pending.add(row);
        filtered.put("pending",pending);return filtered;
    }
    private Map<String,Object> read() throws Exception {return copy(view());}
    private static int bytes(Object state){return WorkBlockJson.json(state).getBytes(StandardCharsets.UTF_8).length;}
    // The committed snapshot cannot change between durable saves. A filtered
    // acknowledgement view is different and must still be measured exactly.
    private int viewBytes(Map<String,Object> state){return state==committed?committedBytes:bytes(state);}
    private void save(Map<String,Object> state) throws Exception {
        save(state,0);
    }
    private void save(Map<String,Object> state,int completedClaims) throws Exception {
        // An old client must fail closed while out-of-order completions exist.
        // Once gaps close, the persisted format is again legacy-readable.
        state.put("version",rows(state,"blocks").stream().anyMatch(item->!ahead(item).isEmpty())?2:1);
        long reserved=(long)Math.max(0,computingCount()-completedClaims)*RESERVE;
        int stateBytes=bytes(state);
        if(rows(state,"pending").size()>128||stateBytes+reserved>MAX_BYTES)throw new CapacityException();
        long began=System.nanoTime();
        try{storage.save(state);committed=state;committedBytes=stateBytes;confirmed.clear();}catch(Exception|Error failure){saveErrors.incrementAndGet();throw failure;}finally{long elapsed=System.nanoTime()-began;persistenceNanos+=elapsed;saveCalls.incrementAndGet();saveNanos.addAndGet(elapsed);}
    }
    public synchronized String allocationRequest() throws Exception {
        Map<String,Object> state=read();
        if(!state.containsKey("request")){state.put("request",UUID.randomUUID().toString());save(state);}
        return (String)state.get("request");
    }
    public synchronized void allocated(String request,Map<String,Object> block) throws Exception {
        WorkBlock.validate(block);Map<String,Object> state=read();
        if(!request.equals(state.get("request")))throw new IllegalArgumentException("Unexpected allocation");
        List<Map<String,Object>> blocks=rows(state,"blocks");
        for(Map<String,Object> item:blocks) {
            Map<?,?> old=(Map<?,?>)item.get("block");
            if(old.get("block_id").equals(block.get("block_id"))) {
                if(!Canonical.json(old).equals(Canonical.json(block)))throw new IllegalArgumentException("Conflicting replay");
                state.remove("request");save(state);return;
            }
        }
        if(blocks.size()>=2||bytes(state)+bytes(block)+(long)RESERVE*Math.max(1,computingCount())>MAX_BYTES)throw new CapacityException();
        blocks.add(object("block",copy(block),"next",block.get("start_unit")));
        state.remove("request");save(state);
    }
    /** Seed only this process's expiry guard from the allocation response.
     * Recovery still requires authoritative status after a process restart. */
    public synchronized void allocatedLifetime(String id,Object raw,long elapsedNanos)throws Exception{
        if(!(raw instanceof Number)||elapsedNanos<0)throw new IllegalArgumentException("Missing allocation lifetime");
        double seconds=((Number)raw).doubleValue();
        if(!Double.isFinite(seconds)||seconds<0||seconds>7200)throw new IllegalArgumentException("Invalid allocation lifetime");
        boolean known=false;
        for(Map<String,Object> item:rows(view(),"blocks"))if(id.equals(((Map<?,?>)item.get("block")).get("block_id")))known=true;
        if(!known)throw new IllegalArgumentException("Unknown allocation lifetime");
        long remaining=Math.max(0,(long)(seconds*1e9)-elapsedNanos-1_000_000_000L);
        if(!deadlines.containsKey(id))deadlines.put(id,clock.getAsLong()+remaining);
    }
    @SuppressWarnings("unchecked") public synchronized Map<String,Object> next() throws Exception {
        Map<String,Object> state=view();
        if(rows(state,"pending").size()>=limit||viewBytes(state)+RESERVE>MAX_BYTES)return null;
        for(Map<String,Object> item:rows(state,"blocks")) {
            Map<String,Object> block=(Map<String,Object>)item.get("block");long n=((Number)item.get("next")).longValue();
            Long deadline=deadlines.get((String)block.get("block_id"));
            if(deadline!=null&&deadline-clock.getAsLong()>0&&!Boolean.TRUE.equals(item.get("retiring"))&&n<((Number)block.get("end_unit")).longValue())
                return object("block_id",block.get("block_id"),"envelope",preparedEnvelope(block,n));
        }
        return null;
    }
    /** Hold the descriptor until compute/persistence finishes, even if status expires it. */
    public synchronized Map<String,Object> claimNext() throws Exception {
        return claimNext(1);
    }
    /** Reserve both result count and bytes before starting another solver. */
    @SuppressWarnings("unchecked") public synchronized Map<String,Object> claimNext(int lanes) throws Exception {
        if(lanes!=1&&lanes!=2&&lanes!=4)throw new IllegalArgumentException("Compute lanes must be 1, 2 or 4");
        return claimReserved(lanes);
    }
    /** Reserve one current and one following job per physical solver lane. */
    synchronized Map<String,Object> claimPrefetched(int lanes)throws Exception {return claimPrefetched(lanes,2*lanes);}
    synchronized Map<String,Object> claimPrefetched(int lanes,int window)throws Exception {
        if(window<lanes||window>8)throw new IllegalArgumentException("Prefetch window");
        if(lanes!=2&&lanes!=4)throw new IllegalArgumentException("Prefetch lanes");
        return claimReserved(window);
    }
    /** One locked snapshot and size pass for the existing round-robin reservation window. */
    public List<List<Map<String,Object>>> claimWindow(int lanes,int available,int rounds)throws Exception {
        if((lanes!=2&&lanes!=4)||available<1||available>lanes||rounds<1||rounds>4||lanes*rounds>8)throw new IllegalArgumentException("Claim window bounds");
        long began=System.nanoTime();windowCalls.incrementAndGet();
        try{synchronized(this){
            List<List<Map<String,Object>>> result=new ArrayList<>();for(int i=0;i<available;i++)result.add(new ArrayList<>());
            Map<String,Object> state=view();int active=computingCount();
            if(active>=lanes*rounds||rows(state,"pending").size()+active>=limit)return result;
            int stateBytes=viewBytes(state);windowSizePasses.incrementAndGet();
            List<Map<String,Object>> reserved=new ArrayList<>();
            try{
                for(int round=0;round<rounds;round++)for(int lane=0;lane<available;lane++){
                    Map<String,Object> claim=claimReserved(lanes*rounds,state,stateBytes);
                    if(claim!=null){result.get(lane).add(claim);reserved.add(claim);}
                }
            }catch(Exception|Error failure){
                for(Map<String,Object> claim:reserved){Map<?,?> envelope=(Map<?,?>)claim.get("envelope");releaseClaim((String)claim.get("block_id"),((Number)envelope.get("start_unit")).longValue());}
                throw failure;
            }
            windowClaims.addAndGet(reserved.size());return result;
        }}finally{windowNanos.addAndGet(System.nanoTime()-began);}
    }
    @SuppressWarnings("unchecked") private Map<String,Object> claimReserved(int reservations)throws Exception {
        int active=computingCount();if(active>=reservations)return null;
        Map<String,Object> state=view();return claimReserved(reservations,state,viewBytes(state));
    }
    @SuppressWarnings("unchecked") private Map<String,Object> claimReserved(int reservations,Map<String,Object> state,int stateBytes)throws Exception {
        int active=computingCount();if(active>=reservations)return null;
        if(rows(state,"pending").size()+active>=limit||stateBytes+(long)RESERVE*(active+1)>MAX_BYTES)return null;
        for(Map<String,Object> item:rows(state,"blocks")){
            Map<String,Object> block=(Map<String,Object>)item.get("block");String id=(String)block.get("block_id");
            Long deadline=deadlines.get(id);
            if(deadline==null||deadline-clock.getAsLong()<=0||Boolean.TRUE.equals(item.get("retiring")))continue;
            Set<Long> claimed=computing.getOrDefault(id,Collections.emptySet()),finished=ahead(item);
            long cursor=((Number)item.get("next")).longValue(),unit=cursor,end=((Number)block.get("end_unit")).longValue();
            while(unit<end&&(claimed.contains(unit)||finished.contains(unit)))unit++;
            // Bound the persisted gap ledger even if faster lanes keep getting
            // acknowledged while the earliest unit is slow or interrupted.
            if(unit<end&&unit-cursor<limit){
                Map<String,Object> envelope=preparedEnvelope(block,unit);
                computing.computeIfAbsent(id,k->new HashSet<>()).add(unit);
                return object("block_id",id,"envelope",envelope);
            }
        }
        return null;
    }
    private Map<String,Object> preparedEnvelope(Map<String,Object> block,long unit){
        long began=System.nanoTime();envelopeCalls.incrementAndGet();
        try{
            Object rawId=block.get("block_id");if(!(rawId instanceof String))throw new IllegalArgumentException("Invalid block identity");
            String id=(String)rawId;WorkBlock.Prepared entry=prepared.get(id);
            if(entry==null){
                entry=new WorkBlock.Prepared(block);descriptorPreparations.incrementAndGet();
                // Only current/next descriptors belong in the hot cache. Eviction
                // is safe: a later use repeats full validation, never trusts an ID.
                if(prepared.size()>=2)prepared.remove(prepared.keySet().iterator().next());
                prepared.put(id,entry);
            }else if(!entry.matches(block))throw new IllegalArgumentException("Changed block descriptor");
            return entry.envelope(unit);
        }finally{envelopeNanos.addAndGet(System.nanoTime()-began);}
    }
    public synchronized void releaseClaim(){
        if(computingCount()>1)throw new IllegalStateException("Release concurrent claims by identity");
        computing.clear();
    }
    public synchronized void releaseClaim(String id,long unit){
        Set<Long> units=computing.get(id);if(units!=null){units.remove(unit);if(units.isEmpty())computing.remove(id);}
    }
    public static final class Completion {
        final String id;final long unit;final Map<String,Object> result;final double seconds;
        public Completion(String id,long unit,Map<String,Object> result,double seconds){
            this.id=Objects.requireNonNull(id);this.unit=unit;
            this.result=copy(Objects.requireNonNull(result));this.seconds=seconds;
        }
    }
    public synchronized void complete(String id,long unit,Map<String,Object> result,double seconds) throws Exception {
        completeBatch(Collections.singletonList(new Completion(id,unit,result,seconds)));
    }
    /** Commit cursor changes and all receipts together; failure releases no reservations. */
    public synchronized void completeBatch(List<Completion> completions) throws Exception {
        if(completions.isEmpty()||completions.size()>4)throw new IllegalArgumentException("Completion batch size");
        Map<String,Object> state=read();List<Map<String,Object>> pending=rows(state,"pending");
        if(pending.size()+completions.size()>limit)throw new IllegalStateException("Outbox full");
        int claimedCount=0;
        for(Completion completion:completions){
            String id=completion.id;long unit=completion.unit;double seconds=completion.seconds;
            if(!Double.isFinite(seconds)||seconds<0)throw new IllegalArgumentException("Invalid duration");
            boolean matched=false;
            for(Map<String,Object> item:rows(state,"blocks")) {
                Map<?,?> block=(Map<?,?>)item.get("block");
                long cursor=((Number)item.get("next")).longValue();Set<Long> finished=ahead(item);
                boolean claimed=computing.getOrDefault(id,Collections.emptySet()).contains(unit);
                if(id.equals(block.get("block_id"))&&unit>=cursor&&!finished.contains(unit)&&(unit==cursor||claimed)&&unit<((Number)block.get("end_unit")).longValue()) {
                    Map<String,Object> receipt=object("block_id",id,"unit",unit,"result",copy(completion.result),"compute_seconds",seconds);
                    if(bytes(receipt)>256*1024-1024)throw new IllegalArgumentException("Receipt too large");
                    pending.add(receipt);finished.add(unit);
                    while(finished.remove(cursor))cursor++;
                    item.put("next",cursor);
                    if(finished.isEmpty())item.remove("completed_ahead");else item.put("completed_ahead",new ArrayList<>(finished));
                    if(claimed)claimedCount++;
                    matched=true;break;
                }
            }
            if(!matched)throw new IllegalArgumentException("Completion does not match cursor");
        }
        save(state,claimedCount);
        for(Completion completion:completions)releaseClaim(completion.id,completion.unit);
    }
    public synchronized List<Map<String,Object>> pending() throws Exception{return rows(read(),"pending");}
    public synchronized int expiredReceiptCount() throws Exception {
        Map<String,Object> state=stored();return ((Number)state.getOrDefault("external_expired_count",0)).intValue()+(state.containsKey("expired_receipts")?rows(state,"expired_receipts").size():0);
    }
    private static Object orderedArchive(Object value){
        if(value instanceof Map){Map<String,Object> sorted=new TreeMap<>();for(Map.Entry<?,?> e:((Map<?,?>)value).entrySet())sorted.put((String)e.getKey(),orderedArchive(e.getValue()));return sorted;}
        if(value instanceof List){List<Object> sorted=new ArrayList<>();for(Object item:(List<?>)value)sorted.add(orderedArchive(item));return sorted;}
        return value;
    }
    private static String orderedArchiveJson(Object value){return WorkBlockJson.json(orderedArchive(value));}
    /** Copy archive first, then detach from the hot snapshot. Either failed write
     * leaves a recoverable copy; retries deduplicate identical receipts. */
    public synchronized void useExpiredStorage(ReceiptQueue.Storage archiveStorage) throws Exception {
        Map<String,Object> state=read(),archive=archiveStorage.load();
        int expected=((Number)state.getOrDefault("external_expired_count",0)).intValue();
        if(archive==null){
            if(expected>0)throw new IllegalStateException("Missing expired receipt archive");
            archive=object("version",1,"server",server,"owner",owner,"receipts",new ArrayList<>());
        }else{
            if(!server.equals(archive.get("server"))||!owner.equals(archive.get("owner"))||!Integer.valueOf(1).equals(archive.get("version")))
                throw new IllegalStateException("Expired archive account or format mismatch");
            archive=copy(archive);
        }
        List<Map<String,Object>> stored=rows(archive,"receipts");
        if(stored.size()<expected)throw new IllegalStateException("Incomplete expired archive");
        Map<String,Map<String,Object>> known=new HashMap<>();
        for(Map<String,Object> row:stored)if(known.put(receiptId(row),row)!=null)throw new IllegalStateException("Duplicate expired archive entry");
        List<Map<String,Object>> local=state.containsKey("expired_receipts")?rows(state,"expired_receipts"):Collections.emptyList();
        boolean changed=false;
        for(Map<String,Object> row:local){
            Map<String,Object> previous=known.get(receiptId(row));
            if(previous!=null){if(!orderedArchiveJson(previous).equals(orderedArchiveJson(row)))throw new IllegalStateException("Conflicting expired archive entry");}
            else {Map<String,Object> retained=copy(row);stored.add(retained);known.put(receiptId(row),retained);changed=true;}
        }
        if(bytes(archive)>MAX_BYTES)throw new CapacityException();
        if(changed)archiveStorage.save(archive);
        if(!local.isEmpty()||expected!=stored.size()){
            state.remove("expired_receipts");state.put("external_expired_count",stored.size());save(state);
        }
        expiredStorage=archiveStorage;
    }
    /** Preserve explicitly expired receipts in the same atomic encrypted record.
     * They are not acknowledged, credited, or retried as current work. */
    public synchronized void archiveExpired(String id,Set<Long> units) throws Exception {
        if(units.isEmpty())return;
        Map<String,Object> state=read();
        state.putIfAbsent("expired_receipts",new ArrayList<>());
        List<Map<String,Object>> archive=rows(state,"expired_receipts");
        for(Iterator<Map<String,Object>> it=rows(state,"pending").iterator();it.hasNext();){
            Map<String,Object> receipt=it.next();
            if(id.equals(receipt.get("block_id"))&&units.contains(((Number)receipt.get("unit")).longValue())){
                Map<String,Object> preserved=copy(receipt);preserved.put("server_status","expired");
                for(Map<String,Object> item:rows(state,"blocks"))
                    if(id.equals(((Map<?,?>)item.get("block")).get("block_id")))preserved.put("block",copy(item.get("block")));
                archive.add(preserved);it.remove();
            }
        }
        for(Map<String,Object> item:rows(state,"blocks"))
            if(id.equals(((Map<?,?>)item.get("block")).get("block_id")))item.put("retiring",true);
        // Persist first, then copy into the independent archive. Never prune on failure.
        save(state);
        if(expiredStorage!=null)useExpiredStorage(expiredStorage);
    }
    public int capacity(){return limit;}
    public synchronized int pendingCount() throws Exception {
        int count=0;
        for(Map<String,Object> row:rows(stored(),"pending"))
            if(!row.equals(confirmed.get(receiptId(row))))count++;
        return count;
    }
    public synchronized long remaining() throws Exception {
        long count=0;for(Map<String,Object> item:rows(stored(),"blocks"))if(!Boolean.TRUE.equals(item.get("retiring")))
            count+=Math.max(0,((Number)((Map<?,?>)item.get("block")).get("end_unit")).longValue()-((Number)item.get("next")).longValue()-ahead(item).size());
        return count;
    }
    public synchronized void acknowledge(String id,Set<Long> units) throws Exception {
        Map<String,Object> state=read();
        if(!computing.isEmpty()){
            // Fold an individual server acknowledgement into the next atomic
            // completion. A crash before it merely replays the accepted receipt.
            for(Map<String,Object> row:rows(state,"pending"))
                if(id.equals(row.get("block_id"))&&units.contains(((Number)row.get("unit")).longValue()))
                    confirmed.put(receiptId(row),copy(row));
            return;
        }
        rows(state,"pending").removeIf(r->id.equals(r.get("block_id"))&&units.contains(((Number)r.get("unit")).longValue()));save(state);
    }
    public synchronized List<String> identities() throws Exception {
        List<String> ids=new ArrayList<>();for(Map<String,Object> item:rows(stored(),"blocks"))ids.add((String)((Map<?,?>)item.get("block")).get("block_id"));return ids;
    }
    public synchronized void allocationRetired(String request,Map<String,Object> block) throws Exception {
        WorkBlock.validate(block);Map<String,Object> state=read();
        if(!request.equals(state.get("request")))throw new IllegalArgumentException("Unexpected allocation");
        for(Map<String,Object> item:rows(state,"blocks")) {
            Map<?,?> old=(Map<?,?>)item.get("block");
            if(old.get("block_id").equals(block.get("block_id"))) {
                if(!Canonical.json(old).equals(Canonical.json(block)))throw new IllegalArgumentException("Conflicting replay");
                item.put("retiring",true);
            }
        }
        state.remove("request");save(state);
    }
    public synchronized void updateStatus(Map<String,Map<String,Object>> states) throws Exception {updateStatus(states,0);}
    public synchronized void updateStatus(Map<String,Map<String,Object>> states,long elapsedNanos) throws Exception {
        if(elapsedNanos<0)throw new IllegalArgumentException("Negative status elapsed time");
        Map<String,Object> state=read();Map<String,Long> nextDeadlines=new HashMap<>(deadlines);
        for(Map<String,Object> item:rows(state,"blocks")) {
            String id=(String)((Map<?,?>)item.get("block")).get("block_id");Map<String,Object> status=states.get(id);
            if(status==null)continue; // New prefetch may not belong to this response.
            Object raw=status.get("valid_for_seconds");
            if(!(raw instanceof Number))throw new IllegalArgumentException("Missing lifetime");
            double seconds=((Number)raw).doubleValue();
            if(!Double.isFinite(seconds)||seconds<0||seconds>7200||!Arrays.asList("reserved","submitted","released","expired").contains(status.get("status")))throw new IllegalArgumentException("Invalid block status");
            nextDeadlines.put(id,clock.getAsLong()+Math.max(0,(long)(seconds*1e9)-elapsedNanos-1_000_000_000L));
            if(!"reserved".equals(status.get("status")))item.put("retiring",true);
        }
        save(state);deadlines.clear();deadlines.putAll(nextDeadlines);
    }
    public synchronized void retire() throws Exception {
        Map<String,Object> state=read();for(Map<String,Object> item:rows(state,"blocks"))item.put("retiring",true);save(state);
    }
    public synchronized List<String> releasable() throws Exception {
        // The read-only tick probe can use the borrowed view under this lock.
        // view() still filters acknowledged receipts without cloning all rows.
        Map<String,Object> state=view();Set<String> pending=new HashSet<>();List<String> result=new ArrayList<>();
        for(Map<String,Object> receipt:rows(state,"pending"))pending.add((String)receipt.get("block_id"));
        for(Map<String,Object> item:rows(state,"blocks")) {
            Map<?,?> block=(Map<?,?>)item.get("block");String id=(String)block.get("block_id");
            if(!computing.containsKey(id)&&!pending.contains(id)&&(Boolean.TRUE.equals(item.get("retiring"))||((Number)item.get("next")).longValue()>=((Number)block.get("end_unit")).longValue()))result.add(id);
        }
        return result;
    }
    public synchronized void released(String id) throws Exception {
        if(!releasable().contains(id))throw new IllegalStateException("Block still active or has pending receipts");
        Map<String,Object> state=read();rows(state,"blocks").removeIf(item->id.equals(((Map<?,?>)item.get("block")).get("block_id")));save(state);deadlines.remove(id);
    }
}
