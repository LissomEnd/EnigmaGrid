import java.util.*;
import java.lang.reflect.*;
import org.enigmagrid.core.*;
import static org.enigmagrid.core.Canonical.object;
public class ClaimWindowChecks {
    static void check(boolean v){if(!v)throw new AssertionError();}
    static WorkBlockQueue setup(WorkBlockQueueChecks.Store store,boolean grouped,int pending,int padding)throws Exception {
        WorkBlockQueue q=new WorkBlockQueue(store,"server","owner",grouped,()->0L);
        q.allocated(q.allocationRequest(),object("format",WorkBlock.FORMAT,"block_id","b","engine","bounded_crib_v1","start_unit",0,"end_unit",1000,
            "config",object("requires",Arrays.asList("cpu","bounded_crib_v1"),"program",object("ciphertext","BDZGO","hypotheses",Arrays.asList(object("text","BD","legal_clean_offsets",Arrays.asList(0))),"chunk",3,"ordinal_base",0,"candidate_limit",3))));
        q.updateStatus(Collections.singletonMap("b",object("status","reserved","valid_for_seconds",600)));
        for(int n=0;n<pending;n++)q.complete("b",n,object("fixture",n),.01);
        if(padding>0){
            // Inject the padding before reloading the queue. The production
            // queue is the sole writer and caches the committed byte length;
            // mutating its backing store behind its back invalidates the test.
            store.state.put("padding","x".repeat(padding));
            q=new WorkBlockQueue(store,"server","owner",grouped,()->0L);
            q.updateStatus(Collections.singletonMap("b",object("status","reserved","valid_for_seconds",600)));
        }
        return q;
    }
    static long counter(String name){return ((Number)WorkBlockQueue.diagnostics().get(name)).longValue();}
    static void compare(boolean grouped,int pending,int lanes,int available,int rounds,int padding)throws Exception {
        WorkBlockQueueChecks.Store first=new WorkBlockQueueChecks.Store(),second=new WorkBlockQueueChecks.Store();
        WorkBlockQueue old=setup(first,grouped,pending,padding),now=setup(second,grouped,pending,padding);
        Method claim=WorkBlockQueue.class.getDeclaredMethod("claimPrefetched",int.class,int.class);claim.setAccessible(true);
        // Model an already running lane: it owns a claim before the free-lane window.
        if(available<lanes){check(Canonical.json(old.claimNext(lanes)).equals(Canonical.json(now.claimNext(lanes))));}
        List<List<Map<String,Object>>> expected=new ArrayList<>();for(int i=0;i<available;i++)expected.add(new ArrayList<>());
        for(int r=0;r<rounds;r++)for(int lane=0;lane<available;lane++){
            @SuppressWarnings("unchecked") Map<String,Object> item=(Map<String,Object>)claim.invoke(old,lanes,lanes*rounds);
            if(item!=null)expected.get(lane).add(item);
        }
        long before=counter("claim_window_size_passes");int writes=second.writes;
        List<List<Map<String,Object>>> actual=now.claimWindow(lanes,available,rounds);
        int capacity=grouped?64:8;int existing=available<lanes&&pending<capacity?1:0;
        check(counter("claim_window_size_passes")==before+(pending+existing>=capacity?0:1));check(second.writes==writes);
        check(Canonical.json(expected).equals(Canonical.json(actual)));
        check(now.pendingCount()==pending);
        int count=actual.stream().mapToInt(List::size).sum();check(count<=lanes*rounds);
        if(padding>7*1024*1024)check(count<=1);
    }
    public static void main(String[] args)throws Exception {
        for(boolean grouped:new boolean[]{false,true})for(int pending:new int[]{0,5,7,8})for(int lanes:new int[]{2,4})for(int available:new int[]{1,lanes})compare(grouped,pending,lanes,available,2,0);
        for(int pending:new int[]{0,60,63,64})compare(true,pending,2,2,4,0);
        compare(true,0,2,2,4,7*1024*1024+100);
        compare(true,0,4,4,2,8*1024*1024-1000);
        System.out.println("PASS atomic claim windows match per-claim round-robin, existing claims, legacy/grouped count and byte bounds; one size pass and no writes per window");
    }
}
