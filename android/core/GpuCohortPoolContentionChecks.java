import java.util.*;
import java.util.concurrent.*;
import org.enigmagrid.core.*;

/** Cached GPU receipts must not wait behind a concurrent CPU solver job. */
public final class GpuCohortPoolContentionChecks {
    private static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
    public static void main(String[] args)throws Exception {
        List<Map<String,Object>> jobs=GpuCohortChecks.jobs(1,24);
        Map<String,Object> job=jobs.get(0);
        String expected=Canonical.json(WorkEnvelope.run(job,()->false));
        BatchedSolver.Dispatch source=GpuCohortChecks.dispatch(jobs,new ArrayList<>());
        final int[][] cached={null};
        BatchedSolver.Dispatch dispatch=request->{
            if(cached[0]==null)cached[0]=source.run(request);
            return cached[0];
        };
        List<String> warm=new ArrayList<>();
        GpuWorkCohort.run(jobs,dispatch,()->false,4,(index,receipt,seconds)->warm.add(Canonical.json(receipt)));
        check(warm.size()==1&&expected.equals(warm.get(0))&&cached[0]!=null,"Warm GPU receipt parity");

        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        BoundedCrib.RowProvider blockingCpu=new BoundedCrib.RowProvider(){
            public int[][] rows(BoundedCrib.Key key,int offset,int length){return BoundedCrib.cpuRows(key,offset,length);}
            public BoardSolver.Result solve(BoundedCrib.Key key,int offset,int length,int[][] edges,int pairs,int nodes,int boards){
                entered.countDown();
                try{release.await();}catch(InterruptedException interrupted){Thread.currentThread().interrupt();throw new CancellationException();}
                return null;
            }
        };
        ExecutorService cpu=Executors.newSingleThreadExecutor(),gpu=Executors.newSingleThreadExecutor();
        try {
            Future<Map<String,Object>> cpuJob=cpu.submit(()->WorkEnvelope.run(job,()->false,blockingCpu,4));
            check(entered.await(2,TimeUnit.SECONDS),"CPU solver did not enter shared pool");
            Future<String> gpuJob=gpu.submit(()->{
                List<String> received=new ArrayList<>();
                GpuWorkCohort.run(jobs,dispatch,()->false,4,(index,receipt,seconds)->received.add(Canonical.json(receipt)));
                check(received.size()==1,"GPU receipt count");
                return received.get(0);
            });
            check(expected.equals(gpuJob.get(2,TimeUnit.SECONDS)),"Cached GPU receipt blocked or changed");
            check(release.getCount()==1,"CPU long job was released before GPU receipt");
            release.countDown();
            check(expected.equals(Canonical.json(cpuJob.get(30,TimeUnit.SECONDS))),"CPU long-job receipt parity");
        } finally {
            release.countDown();cpu.shutdownNow();gpu.shutdownNow();
        }
        System.out.println("PASS cached GPU receipt parity and completion while shared CPU solver pool is occupied");
    }
}
