import java.util.*;
import java.util.concurrent.*;
import org.enigmagrid.core.*;
import static org.enigmagrid.core.Canonical.object;

/** HTTP may finish after cancellation: old sessions must never overwrite recovery. */
public class WorkBlockStopChecks {
    static void check(boolean value){if(!value)throw new AssertionError();}
    public static void main(String[] args)throws Exception {
        WorkBlockQueueChecks.Store store=new WorkBlockQueueChecks.Store();
        WorkBlockQueue queue=new WorkBlockQueue(store,"server","owner",true);
        Map<String,Object> block=object("format",WorkBlock.FORMAT,"block_id","late","engine","bounded_crib_v1","start_unit",0,"end_unit",100,
            "config",object("requires",Arrays.asList("cpu","bounded_crib_v1"),"program",object("ciphertext","BDZGO","hypotheses",Arrays.asList(object("text","BD","legal_clean_offsets",Arrays.asList(0))),"chunk",3,"ordinal_base",0,"candidate_limit",3)));
        CountDownLatch entered=new CountDownLatch(1),response=new CountDownLatch(1);
        WorkBlockTransport transport=new WorkBlockTransport(queue,(path,body)->{
            check(path.equals("/api/work-blocks"));entered.countDown();response.await();
            return object("status","reserved","block",block);
        },true);
        ExecutorService executor=Executors.newSingleThreadExecutor();
        try {
            Future<?> allocation=executor.submit(()->{transport.allocate();return null;});
            check(entered.await(2,TimeUnit.SECONDS));String request=queue.allocationRequest();
            transport.stop();queue.retire();response.countDown();
            try{allocation.get(2,TimeUnit.SECONDS);throw new AssertionError("Late allocation accepted");}
            catch(ExecutionException expected){check(expected.getCause() instanceof CancellationException);}
            check(queue.identities().isEmpty()&&request.equals(queue.allocationRequest()));
            // Recovery replays the same request, rather than losing the reserved range.
            queue.allocated(request,block);queue.complete("late",0,object("fixture",true),.05);
            CountDownLatch uploadEntered=new CountDownLatch(1),uploadResponse=new CountDownLatch(1);
            WorkBlockTransport uploading=new WorkBlockTransport(queue,(path,body)->{
                uploadEntered.countDown();uploadResponse.await();
                return object("block_id","late","results",Arrays.asList(object("unit",0,"status","received")));
            },true);
            Future<?> upload=executor.submit(()->{uploading.upload();return null;});
            check(uploadEntered.await(2,TimeUnit.SECONDS));uploading.stop();queue.retire();uploadResponse.countDown();
            try{upload.get(2,TimeUnit.SECONDS);throw new AssertionError("Late upload mutated queue");}
            catch(ExecutionException expected){check(expected.getCause() instanceof CancellationException);}
            check(queue.pending().size()==1&&queue.releasable().isEmpty());
            WorkBlockPipeline closing=new WorkBlockPipeline(queue,uploading.recovery(),e->{throw new AssertionError("Unexpected compute");});
            Thread.currentThread().interrupt();closing.close();
            check(Thread.interrupted());
            queue.retire();check(queue.pending().size()==1);
        } finally {response.countDown();executor.shutdownNow();}
        System.out.println("PASS late allocation and upload cannot mutate stopped session; request and receipt retained for replay");
    }
}
