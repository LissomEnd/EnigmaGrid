import java.util.*;
import org.enigmagrid.core.*;
import static org.enigmagrid.core.Canonical.object;
public class WorkBlockQueueChecks {
    static class Store implements ReceiptQueue.Storage {
        Map<String,Object> state;boolean fail;int writes,loads;
        public Map<String,Object> load(){loads++;return state;}
        public void save(Map<String,Object> value)throws Exception {if(fail)throw new java.io.IOException("disk full");state=value;writes++;}
    }
    static void check(boolean value){if(!value)throw new AssertionError();}
    public static void main(String[] args)throws Exception {
        Store storage=new Store();long[] now={0};
        WorkBlockQueue queue=new WorkBlockQueue(storage,"server","owner",true,()->now[0]);
        Map<String,Object> block=object("format",WorkBlock.FORMAT,"block_id","b","engine","bounded_crib_v1","start_unit",0,"end_unit",100,
            "config",object("requires",Arrays.asList("cpu","bounded_crib_v1"),"program",object("ciphertext","BDZGO","hypotheses",Arrays.asList(object("text","BD","legal_clean_offsets",Arrays.asList(0))),"chunk",3,"ordinal_base",0,"candidate_limit",3)));
        String request=queue.allocationRequest();check(request.equals(queue.allocationRequest()));queue.allocated(request,block);
        check(queue.next()==null); // A restart/allocation requires authoritative lifetime.
        Store lifetimeStore=new Store();long[] lifetimeNow={0};
        WorkBlockQueue allocatedLifetime=new WorkBlockQueue(lifetimeStore,"server","owner",true,()->lifetimeNow[0]);
        allocatedLifetime.allocated(allocatedLifetime.allocationRequest(),block);
        allocatedLifetime.allocatedLifetime("b",10,1_000_000_000L); // Subtract RTT plus one-second expiry margin.
        check(allocatedLifetime.next()!=null);
        lifetimeNow[0]=8_000_000_000L;check(allocatedLifetime.next()==null);
        check(new WorkBlockQueue(lifetimeStore,"server","owner",true,()->lifetimeNow[0]).next()==null);
        try{allocatedLifetime.allocatedLifetime("b",7201,0);throw new AssertionError();}catch(IllegalArgumentException expected){}
        Store slowStatusStore=new Store();long[] statusNow={0};
        WorkBlockQueue slowStatus=new WorkBlockQueue(slowStatusStore,"server","owner",true,()->statusNow[0]);
        slowStatus.allocated(slowStatus.allocationRequest(),block);
        slowStatus.updateStatus(Collections.singletonMap("b",object("status","reserved","valid_for_seconds",10)),2_000_000_000L);
        statusNow[0]=6_000_000_000L;check(slowStatus.next()!=null);
        statusNow[0]=7_000_000_000L;check(slowStatus.next()==null);
        queue.updateStatus(Collections.singletonMap("b",object("status","reserved","valid_for_seconds",10)));
        check(queue.next()!=null);
        int hotLoads=storage.loads;
        for(int n=0;n<100;n++){
            check(queue.pendingCount()==0&&queue.remaining()==100);
            check(queue.identities().equals(Arrays.asList("b"))&&queue.next()!=null);
        }
        check(storage.loads==hotLoads); // The durable snapshot is reused during a hot block.
        storage.fail=true;
        try{queue.complete("b",0,object("result","test"),.05);throw new AssertionError();}catch(java.io.IOException expected){}
        storage.fail=false;check(queue.pending().isEmpty()&&storage.loads==hotLoads);
        queue.complete("b",0,object("result","test"),.05);check(queue.pending().size()==1);
        check(queue.pendingCount()==1&&queue.remaining()==99);
        queue.identities().clear();check(queue.identities().equals(Arrays.asList("b")));
        queue.pending().get(0).clear();check(queue.pendingCount()==1&&queue.pending().get(0).containsKey("unit"));
        WorkBlockQueue restarted=new WorkBlockQueue(storage,"server","owner",true,()->now[0]);
        check(restarted.next()==null&&restarted.pending().size()==1);
        restarted.updateStatus(Collections.singletonMap("b",object("status","reserved","valid_for_seconds",10)));
        check(((Number)((Map<?,?>)restarted.next().get("envelope")).get("start_unit")).longValue()==1);
        now[0]=11_000_000_000L;check(restarted.next()==null);
        restarted.retire();check(restarted.releasable().isEmpty());
        try{restarted.released("b");throw new AssertionError();}catch(IllegalStateException expected){}
        restarted.acknowledge("other",Collections.singleton(0L));check(restarted.pending().size()==1);
        restarted.acknowledge("b",Collections.singleton(0L));check(restarted.releasable().equals(Arrays.asList("b")));
        restarted.released("b");check(restarted.identities().isEmpty());
        try{new WorkBlockQueue(storage,"other-server","owner",true).pending();throw new AssertionError();}catch(IllegalStateException expected){}
        Store fullStore=new Store();WorkBlockQueue full=new WorkBlockQueue(fullStore,"server","owner",true);
        full.allocated(full.allocationRequest(),block);
        for(int n=0;n<33;n++)full.complete("b",n,object("fixture","x".repeat(240000)),.05);
        Map<String,Object> nextBlock=new LinkedHashMap<>(block);nextBlock.put("block_id","next");
        String pendingRequest=full.allocationRequest();
        try{full.allocated(pendingRequest,nextBlock);throw new AssertionError("No space reserved for result");}catch(WorkBlockQueue.CapacityException expected){}
        check(full.pending().size()==33&&pendingRequest.equals(full.allocationRequest()));
        full.acknowledge("b",Collections.singleton(0L));full.allocated(pendingRequest,nextBlock);
        check(full.identities().size()==2&&full.pending().size()==32);
        Store racingStore=new Store();WorkBlockQueue racing=new WorkBlockQueue(racingStore,"server","owner",true);
        racing.allocated(racing.allocationRequest(),block);
        racing.updateStatus(Collections.singletonMap("b",object("status","reserved","valid_for_seconds",10)));
        check(racing.claimNext()!=null&&racing.claimNext()==null);
        racing.updateStatus(Collections.singletonMap("b",object("status","expired","valid_for_seconds",0)));
        check(racing.releasable().isEmpty());
        try{racing.released("b");throw new AssertionError("Released running computation");}catch(IllegalStateException expected){}
        racing.complete("b",0,object("result","late but retained"),.05);racing.releaseClaim();
        check(racing.pending().size()==1&&racing.releasable().isEmpty());
        racing.acknowledge("b",Collections.singleton(0L));check(racing.releasable().equals(Arrays.asList("b")));
        Store foldedStore=new Store();WorkBlockQueue folded=new WorkBlockQueue(foldedStore,"server","owner",true);
        folded.allocated(folded.allocationRequest(),block);
        folded.updateStatus(Collections.singletonMap("b",object("status","reserved","valid_for_seconds",100)));
        folded.complete("b",0,object("result","first"),.05);
        check(folded.claimNext()!=null);int before=foldedStore.writes;
        folded.acknowledge("b",Collections.singleton(0L));check(folded.pending().isEmpty()&&foldedStore.writes==before);
        check(folded.pendingCount()==0&&folded.remaining()==99);
        check(((List<?>)foldedStore.state.get("pending")).size()==1); // Reads never erase durable replay.
        check(new WorkBlockQueue(foldedStore,"server","owner",true).pendingCount()==1);
        check(new WorkBlockQueue(foldedStore,"server","owner",true).pending().size()==1);
        foldedStore.fail=true;
        try{folded.complete("b",1,object("result","second"),.05);throw new AssertionError();}catch(java.io.IOException expected){}
        check(new WorkBlockQueue(foldedStore,"server","owner",true).pending().size()==1);
        foldedStore.fail=false;folded.complete("b",1,object("result","second"),.05);folded.releaseClaim();
        check(foldedStore.writes==before+1);
        List<Map<String,Object>> durable=new WorkBlockQueue(foldedStore,"server","owner",true).pending();
        check(durable.size()==1&&((Number)durable.get(0).get("unit")).longValue()==1);
        for(int lanes:new int[]{2,4}){
            Store concurrentStore=new Store();WorkBlockQueue concurrent=new WorkBlockQueue(concurrentStore,"server","owner",true);
            concurrent.allocated(concurrent.allocationRequest(),block);
            concurrent.updateStatus(Collections.singletonMap("b",object("status","reserved","valid_for_seconds",100)));
            for(int unit=0;unit<lanes;unit++){
                Map<String,Object> claim=concurrent.claimNext(lanes);
                check(((Number)((Map<?,?>)claim.get("envelope")).get("start_unit")).longValue()==unit);
            }
            check(concurrent.claimNext(lanes)==null);
            try{concurrent.releaseClaim();throw new AssertionError("Ambiguous release");}catch(IllegalStateException expected){}
            concurrentStore.fail=true;
            try{concurrent.complete("b",lanes-1,object("fixture",true),.05);throw new AssertionError();}catch(java.io.IOException expected){}
            concurrentStore.fail=false;check(concurrent.pending().isEmpty());
            for(int unit=lanes-1;unit>0;unit--){
                concurrent.complete("b",unit,object("fixture",true),.05);
                concurrent.releaseClaim("b",unit);
            }
            check(Integer.valueOf(2).equals(concurrentStore.state.get("version")));
            check(concurrent.remaining()==100-(lanes-1));
            // Acknowledged out-of-order work must survive a crash without replay
            // as a new computation, even after removal from the durable outbox.
            Set<Long> accepted=new HashSet<>();for(long unit=1;unit<lanes;unit++)accepted.add(unit);
            concurrent.releaseClaim("b",0);concurrent.acknowledge("b",accepted);
            WorkBlockQueue recovered=new WorkBlockQueue(concurrentStore,"server","owner",true);
            check(recovered.pending().isEmpty());
            recovered.updateStatus(Collections.singletonMap("b",object("status","reserved","valid_for_seconds",100)));
            check(((Number)((Map<?,?>)recovered.claimNext(lanes).get("envelope")).get("start_unit")).longValue()==0);
            check(((Number)((Map<?,?>)recovered.claimNext(lanes).get("envelope")).get("start_unit")).longValue()==lanes);
            recovered.complete("b",0,object("fixture",true),.05);recovered.releaseClaim("b",0);
            check(Integer.valueOf(1).equals(concurrentStore.state.get("version")));
            check(((Number)((Map<?,?>)recovered.next().get("envelope")).get("start_unit")).longValue()==lanes);
            recovered.updateStatus(Collections.singletonMap("b",object("status","expired","valid_for_seconds",0)));
            recovered.acknowledge("b",Collections.singleton(0L));check(recovered.releasable().isEmpty());
            recovered.releaseClaim("b",lanes);check(recovered.releasable().equals(Arrays.asList("b")));
        }
        Store capacityStore=new Store();WorkBlockQueue capacity=new WorkBlockQueue(capacityStore,"server","owner",false);
        capacity.allocated(capacity.allocationRequest(),block);
        capacity.updateStatus(Collections.singletonMap("b",object("status","reserved","valid_for_seconds",100)));
        for(int n=0;n<6;n++)capacity.complete("b",n,object("fixture",true),.05);
        check(capacity.claimNext(4)!=null&&capacity.claimNext(4)!=null&&capacity.claimNext(4)==null);
        Store gapStore=new Store();WorkBlockQueue gap=new WorkBlockQueue(gapStore,"server","owner",false);
        gap.allocated(gap.allocationRequest(),block);gap.updateStatus(Collections.singletonMap("b",object("status","reserved","valid_for_seconds",100)));
        check(gap.claimNext(2)!=null);
        for(int unit=1;unit<8;unit++){
            check(((Number)((Map<?,?>)gap.claimNext(2).get("envelope")).get("start_unit")).longValue()==unit);
            gap.complete("b",unit,object("fixture",true),.05);gap.releaseClaim("b",unit);gap.acknowledge("b",Collections.singleton((long)unit));
        }
        check(gap.pending().isEmpty()&&gap.claimNext(2)==null); // Ack cannot grow a gap without bound.
        gap.complete("b",0,object("fixture",true),.05);gap.releaseClaim("b",0);
        check(((Number)((Map<?,?>)gap.claimNext(2).get("envelope")).get("start_unit")).longValue()==8);
        Store batchStore=new Store();WorkBlockQueue batch=new WorkBlockQueue(batchStore,"server","owner",true);
        batch.allocated(batch.allocationRequest(),block);
        batch.updateStatus(Collections.singletonMap("b",object("status","reserved","valid_for_seconds",100)));
        for(int i=0;i<4;i++)check(batch.claimNext(4)!=null);
        Map<String,Object> mutable=object("fixture","original");
        List<WorkBlockQueue.Completion> results=Arrays.asList(
            new WorkBlockQueue.Completion("b",3,mutable,.05),
            new WorkBlockQueue.Completion("b",1,object("fixture",true),.05));
        mutable.put("fixture","changed");int savedWrites=batchStore.writes;
        batchStore.fail=true;
        try{batch.completeBatch(results);throw new AssertionError();}catch(java.io.IOException expected){}
        check(batch.pendingCount()==0&&batch.claimNext(4)==null&&batchStore.writes==savedWrites);
        batchStore.fail=false;
        try{batch.completeBatch(Arrays.asList(results.get(0),results.get(0)));throw new AssertionError();}catch(IllegalArgumentException expected){}
        check(batch.pendingCount()==0&&batch.claimNext(4)==null&&batchStore.writes==savedWrites);
        try{batch.completeBatch(Arrays.asList(results.get(0),new WorkBlockQueue.Completion("foreign",0,object("fixture",true),.05)));throw new AssertionError();}catch(IllegalArgumentException expected){}
        check(batch.pendingCount()==0&&batchStore.writes==savedWrites);
        batch.completeBatch(results);check(batchStore.writes==savedWrites+1&&batch.pendingCount()==2);
        check("original".equals(((Map<?,?>)batch.pending().get(0).get("result")).get("fixture")));
        check(Integer.valueOf(2).equals(batchStore.state.get("version")));
        WorkBlockQueue batchRestart=new WorkBlockQueue(batchStore,"server","owner",true);
        check(batchRestart.pendingCount()==2);
        batchRestart.updateStatus(Collections.singletonMap("b",object("status","reserved","valid_for_seconds",100)));
        check(((Number)((Map<?,?>)batchRestart.claimNext(4).get("envelope")).get("start_unit")).longValue()==0);
        check(((Number)((Map<?,?>)batchRestart.claimNext(4).get("envelope")).get("start_unit")).longValue()==2);
        batchRestart.completeBatch(Arrays.asList(new WorkBlockQueue.Completion("b",2,object("fixture",true),.05),new WorkBlockQueue.Completion("b",0,object("fixture",true),.05)));
        check(batchRestart.pendingCount()==4&&Integer.valueOf(1).equals(batchStore.state.get("version")));
        check(((Number)((Map<?,?>)batchRestart.next().get("envelope")).get("start_unit")).longValue()==4);
        Store wideStore=new Store();Map<String,Object> longBlock=new LinkedHashMap<>(block);longBlock.put("end_unit",200);
        WorkBlockQueue wide=new WorkBlockQueue(wideStore,"server","owner",true,128,()->0L);
        wide.allocated(wide.allocationRequest(),longBlock);
        wide.updateStatus(Collections.singletonMap("b",object("status","reserved","valid_for_seconds",100)));
        for(int unit=0;unit<128;unit++)wide.complete("b",unit,object("fixture",unit),.05);
        check(wide.capacity()==128&&wide.pendingCount()==128&&wide.next()==null);
        WorkBlockQueue wideRestart=new WorkBlockQueue(wideStore,"server","owner",true,128,()->0L);
        check(wideRestart.pendingCount()==128);
        Set<Long> firstHalf=new HashSet<>();for(long unit=0;unit<64;unit++)firstHalf.add(unit);
        wideRestart.acknowledge("b",firstHalf);
        check(wideRestart.pendingCount()==64&&wideRestart.pending().size()==64);
        wideRestart.updateStatus(Collections.singletonMap("b",object("status","reserved","valid_for_seconds",100)));
        check(((Number)((Map<?,?>)wideRestart.next().get("envelope")).get("start_unit")).longValue()==128);
        System.out.println("PASS grouped atomic completion, failed write and invalid member rollback, immutable receipt, restart gaps and one write per group");
        System.out.println("PASS optional 128-result durable window, restart, partial acknowledgement and resumed work");
        System.out.println("PASS atomic cursor, failed save, restart, expiry, release, folded ack, account isolation and 2/4-lane out-of-order recovery with bounded reservations");
    }
}
