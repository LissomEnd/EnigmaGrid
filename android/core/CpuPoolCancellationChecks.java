import java.lang.reflect.Field;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.enigmagrid.core.*;

/** Host-only queue saturation: stop must escape bounded CPU stripe submission. */
public final class CpuPoolCancellationChecks {
    private static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
    public static void main(String[] args)throws Exception {
        Field field=BoundedCrib.class.getDeclaredField("CPU_POOL");field.setAccessible(true);
        ThreadPoolExecutor pool=(ThreadPoolExecutor)field.get(null);
        List<Map<String,Object>> jobs=GpuCohortChecks.jobs(5,5);
        CountDownLatch release=new CountDownLatch(1);AtomicBoolean stopFifth=new AtomicBoolean();
        BoundedCrib.RowProvider factory=new BoundedCrib.RowProvider(){
            public BoundedCrib.RowProvider newSearch(){return new BoundedCrib.RowProvider(){
                private boolean first=true;
                public int[][] rows(BoundedCrib.Key key,int offset,int length){return BoundedCrib.cpuRows(key,offset,length);}
                public BoardSolver.Result solve(BoundedCrib.Key key,int offset,int length,int[][] edges,int pairs,int nodes,int boards){
                    if(first){first=false;try{release.await(5,TimeUnit.SECONDS);}
                        catch(InterruptedException cancelled){Thread.currentThread().interrupt();throw new CancellationException();}}
                    return null;
                }
            };}
            public int[][] rows(BoundedCrib.Key key,int offset,int length){throw new AssertionError("Factory used directly");}
        };
        ExecutorService callers=Executors.newFixedThreadPool(5);List<Future<?>> firstFour=new ArrayList<>();
        try {
            for(int i=0;i<4;i++){final int job=i;
                firstFour.add(callers.submit(()->WorkEnvelope.run(jobs.get(job),()->false,factory,32)));
            }
            long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(2);
            while(pool.getQueue().size()<116&&System.nanoTime()<deadline)Thread.sleep(10);
            check(pool.getQueue().size()>=116,"Four job stripe queue did not fill as expected");
            Future<?> fifth=callers.submit(()->WorkEnvelope.run(jobs.get(4),stopFifth::get,factory,32));
            deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(2);
            while(pool.getQueue().remainingCapacity()>0&&System.nanoTime()<deadline)Thread.sleep(10);
            check(pool.getQueue().remainingCapacity()==0,"Fifth job did not exercise bounded admission");
            long began=System.nanoTime();stopFifth.set(true);
            try{fifth.get(1,TimeUnit.SECONDS);throw new AssertionError("Stop ignored");}
            catch(ExecutionException failure){check(failure.getCause() instanceof CancellationException,"Wrong cancellation failure");}
            long stopMs=TimeUnit.NANOSECONDS.toMillis(System.nanoTime()-began);
            check(stopMs<500,"Stop blocked on a full CPU queue: "+stopMs);
            deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(1);
            while(pool.getQueue().remainingCapacity()==0&&System.nanoTime()<deadline)Thread.sleep(10);
            check(pool.getQueue().remainingCapacity()>0,"Cancelled queued stripes were not removed");
            System.out.println("PASS bounded queue cancellation "+stopMs+"ms, no stuck submitter, queued stripes removed");
        } finally {
            release.countDown();for(Future<?> future:firstFour)future.cancel(true);
            callers.shutdownNow();
        }
    }
}
