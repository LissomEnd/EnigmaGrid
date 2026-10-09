import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.BooleanSupplier;
import org.enigmagrid.core.*;

/** Host-only: four jobs with two requested workers each must share a CPU cap of P. */
public final class CpuLanePoolTopologyChecks {
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception {
        final int capacity=Math.max(1,Math.min(32,Runtime.getRuntime().availableProcessors()));
        if(capacity<4){System.out.println("SKIP aggregate-four-lane proof: host capacity "+capacity);return;}
        List<Map<String,Object>> jobs=GpuCohortChecks.jobs(4,5);List<String> expected=new ArrayList<>();
        for(Map<String,Object> job:jobs)expected.add(Canonical.json(WorkEnvelope.run(job,()->false)));
        // Count distinct global CPU pool threads, not distinct job providers.
        // FIFO may fill the pool from two jobs before the other two submit.
        CountDownLatch prepared=new CountDownLatch(4),launch=new CountDownLatch(1);
        CountDownLatch entered=new CountDownLatch(4),release=new CountDownLatch(1),start=new CountDownLatch(1);
        AtomicInteger providerCount=new AtomicInteger();
        Set<Thread> enteredThreads=Collections.newSetFromMap(new ConcurrentHashMap<Thread,Boolean>());
        BooleanSupplier checkpoint=()->{
            Thread thread=Thread.currentThread();
            if(thread.getName().startsWith("enigmagrid-cpu-")&&enteredThreads.add(thread)){
                entered.countDown();
                try{check(release.await(20,TimeUnit.SECONDS),"Release never arrived");}
                catch(InterruptedException interrupted){Thread.currentThread().interrupt();throw new CancellationException();}
            }
            return false;
        };
        BoundedCrib.RowProvider factory=new BoundedCrib.RowProvider(){
            public BoundedCrib.RowProvider newSearch(){
                providerCount.incrementAndGet();
                return new BoundedCrib.RowProvider(){
                    public void prepare(List<BoundedCrib.Key> keys,int offset,int length){
                        prepared.countDown();
                        try{check(launch.await(20,TimeUnit.SECONDS),"Prepared searches never launched");}
                        catch(InterruptedException interrupted){Thread.currentThread().interrupt();throw new CancellationException();}
                    }
                    public int[][] rows(BoundedCrib.Key key,int offset,int length){return BoundedCrib.cpuRows(key,offset,length);}
                    public BoardSolver.Result solve(BoundedCrib.Key key,int offset,int length,int[][] edges,int pairs,int nodes,int boards){return null;}
                };
            }
            public int[][] rows(BoundedCrib.Key key,int offset,int length){throw new AssertionError("Factory used as search provider");}
        };
        ExecutorService callers=Executors.newFixedThreadPool(4);List<Future<String>> receipts=new ArrayList<>();
        try {
            for(Map<String,Object> job:jobs)receipts.add(callers.submit(()->{
                start.await();return Canonical.json(WorkEnvelope.run(job,checkpoint,factory,2));
            }));
            start.countDown();
            check(prepared.await(20,TimeUnit.SECONDS),"Four searches did not reach the shared pool");
            launch.countDown();
            boolean fourEntered=entered.await(10,TimeUnit.SECONDS);
            System.out.println("CPU_CAPACITY="+capacity+" JOBS=4 WORKERS_PER_JOB=2 CPU_THREADS_BEFORE_RELEASE="+enteredThreads.size());
            check(fourEntered,"Global CPU pool cannot admit four concurrent stripes");
            release.countDown();
            for(int i=0;i<receipts.size();i++)check(expected.get(i).equals(receipts.get(i).get(30,TimeUnit.SECONDS)),"Receipt parity job "+i);
            check(providerCount.get()==4,"Providers shared across jobs");
            int cpuThreads=0;
            for(Thread thread:Thread.getAllStackTraces().keySet())if(thread.isAlive()&&thread.getName().startsWith("enigmagrid-cpu-"))cpuThreads++;
            check(cpuThreads<=capacity,"CPU oversubscription "+cpuThreads+">"+capacity);
            System.out.println("PASS aggregate four-job capacity, two-stripe requests, exact receipts, CPU threads "+cpuThreads+"/"+capacity);
        } finally {
            launch.countDown();release.countDown();callers.shutdownNow();
        }
    }
}
