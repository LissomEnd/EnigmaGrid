import java.util.*;
import java.util.concurrent.CancellationException;
import java.util.concurrent.atomic.AtomicInteger;
import org.enigmagrid.core.*;
import static org.enigmagrid.core.Canonical.object;

/** Real distinct scopes, combined transport, independent unchanged receipt reduction. */
public class GpuCohortChecks {
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    static List<Map<String,Object>> jobs(int count,int length){
        List<Map<String,Object>> jobs=new ArrayList<>();
        for(int job=0;job<count;job++){
            List<Long> indices=new ArrayList<>();for(int i=0;i<128;i++)indices.add((job*128L+i)*7919L);
            String cipher=length==5?"BDZGO":"QWERTZUIOPASDFGHJKLYXCVBNM",crib=length==5?"AAAAA":"ABCDEFGHIJKLMNOPQRSTUVWX";
            jobs.add(object("engine","bounded_crib_v1","start_unit",job,"end_unit",job+1,"config",object("requires",Arrays.asList("cpu","bounded_crib_v1"),"job",object(
                "engine","bounded_crib_v1","ciphertext",cipher,"crib",crib,"offset",0,"core_indices",indices,"model","clean","pairs",length==5?0:10,
                "budgets",object("node_limit",5000,"board_limit",64,"completion_limit",256,"candidate_limit",32)))));
        }return jobs;
    }
    @SuppressWarnings("unchecked") static BatchedSolver.Dispatch dispatch(List<Map<String,Object>> jobs,List<Integer> widths){
        Map<String,int[]> rows=new HashMap<>();
        for(Map<String,Object> envelope:jobs){Map<String,Object> job=WorkEnvelope.validate(envelope);int offset=((Number)job.get("offset")).intValue(),length=((String)job.get("crib")).length();
            for(Number index:(List<Number>)job.get("core_indices")){
                BoundedCrib.Key key=BoundedCrib.coreAt(index.longValue());int[] packed=RowBatch.pack(Collections.singletonList(key),offset,length);int[][] cpu=BoundedCrib.cpuRows(key,offset,length);
                for(int r=0;r<length;r++)rows.put(Arrays.toString(Arrays.copyOfRange(packed,625+r*9,634+r*9)),cpu[r]);
            }
        }
        return request->{widths.add(request[0]);return SolverKeyBatch.execute(request,packed->{
            int[] flat=new int[packed[0]*26];for(int r=0;r<packed[0];r++){int[] row=rows.get(Arrays.toString(Arrays.copyOfRange(packed,625+r*9,634+r*9)));check(row!=null,"Unassigned row");System.arraycopy(row,0,flat,r*26,26);}return flat;
        },SolverBatchChecks::cpuDispatch);};
    }
    public static void main(String[] args)throws Exception{
        for(int size:new int[]{1,2,3,4})for(int length:new int[]{5,24}){
            List<Map<String,Object>> jobs=jobs(size,length);List<Integer> widths=new ArrayList<>();List<String> before=new ArrayList<>(),reference=new ArrayList<>(),actual=new ArrayList<>();
            for(Map<String,Object> job:jobs){before.add(Canonical.json(job));reference.add(Canonical.json(WorkEnvelope.run(job,()->false)));}
            GpuWorkCohort.run(jobs,dispatch(jobs,widths),()->false,8,(index,result,seconds)->{check(index==actual.size(),"Receipt order");check(seconds>0&&Double.isFinite(seconds),"Compute time");actual.add(Canonical.json(result));});
            check(reference.equals(actual),"Canonical receipts changed");check(widths.equals(Arrays.asList(size*128)),"Cores not coalesced "+widths);
            for(int i=0;i<size;i++)check(before.get(i).equals(Canonical.json(jobs.get(i))),"Source job mutated");
        }
        List<Map<String,Object>> jobs=jobs(4,5);List<Integer> widths=new ArrayList<>();
        @SuppressWarnings("unchecked") Map<String,Object> changed=(Map<String,Object>)((Map<?,?>)jobs.get(2).get("config")).get("job");changed.put("pairs",1);
        List<String> actual=new ArrayList<>();GpuWorkCohort.run(jobs,dispatch(jobs,widths),()->false,4,(index,result,seconds)->actual.add(Canonical.json(result)));
        check(widths.equals(Arrays.asList(256,128,128)),"Incompatible metadata grouped");
        for(int i=0;i<4;i++)check(actual.get(i).equals(Canonical.json(WorkEnvelope.run(jobs.get(i),()->false))),"Split metadata parity");
        Map<String,Object> beforeFallback=GpuWorkCohort.diagnostics();
        actual.clear();GpuWorkCohort.run(jobs,p->null,()->false,2,(i,r,s)->actual.add(Canonical.json(r)));check(actual.size()==4,"CPU fallback lost result");
        Map<String,Object> afterFallback=GpuWorkCohort.diagnostics();
        for(int size=1;size<=4;size++){
            String key="gpu_groups_"+size;
            check(beforeFallback.get(key).equals(afterFallback.get(key)),"CPU fallback counted as GPU group");
        }
        AtomicInteger delivered=new AtomicInteger();
        try{GpuWorkCohort.run(jobs,dispatch(jobs,new ArrayList<>()),()->delivered.get()>0,4,(i,r,s)->delivered.incrementAndGet());throw new AssertionError("Ignored cancellation");}catch(CancellationException expected){}
        check(delivered.get()==1,"Cancelled receipt delivery");
        try{GpuWorkCohort.run(jobs(5,5),p->{throw new AssertionError("Dispatched oversized cohort");},()->false,1,(i,r,s)->{});throw new AssertionError("Accepted five scopes");}catch(IllegalArgumentException expected){}
        Map<String,Object> stages=GpuWorkCohort.diagnostics();
        check(((Number)stages.get("jobs")).longValue()>=4,"Missing cohort job diagnostics");
        check(((Number)stages.get("gpu_groups_4")).longValue()>=1,"Missing four-job group diagnostics");
        for(String key:Arrays.asList("scope_ns","pack_ns","gpu_ipc_ns","unpack_ns","receipt_reduction_ns","callback_ns","run_ns"))
            check(((Number)stages.get(key)).longValue()>0,"Missing cohort stage "+key);
        System.out.println("PASS 1..4 real jobs / 128..512 transport cores, canonical receipts, mixed metadata split, bounded cancellation and CPU fallback");
    }
}
