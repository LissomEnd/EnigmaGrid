import java.util.*;
import java.util.concurrent.*;
import org.enigmagrid.core.LeaseReservations;
import static org.enigmagrid.core.Canonical.object;

public final class LeaseReservationsChecks {
    public static void main(String[] args)throws Exception {
        LeaseReservations queue=new LeaseReservations(Arrays.asList(object("id","executing"),object("id","unused")));
        if(!"executing".equals(queue.take().get("id")))throw new AssertionError();
        try{queue.releaseUnused(items->{throw new java.io.IOException();});throw new AssertionError();}catch(java.io.IOException expected){}
        if(queue.size()!=1)throw new AssertionError("Timeout lost reservation");
        if(queue.releaseUnused(items->false)||queue.size()!=1)throw new AssertionError("Unacknowledged release removed work");
        CountDownLatch entered=new CountDownLatch(1),finish=new CountDownLatch(1);
        ExecutorService threads=Executors.newFixedThreadPool(2);
        try{
            Future<Boolean> releasing=threads.submit(()->queue.releaseUnused(items->{
                if(items.size()!=1||!"unused".equals(items.get(0).get("id")))throw new AssertionError("Executing lease released");
                entered.countDown();if(!finish.await(2,TimeUnit.SECONDS))throw new AssertionError();return true;
            }));
            if(!entered.await(2,TimeUnit.SECONDS))throw new AssertionError();
            Future<Map<String,Object>> claiming=threads.submit(queue::take);
            finish.countDown();if(!releasing.get(2,TimeUnit.SECONDS)||claiming.get(2,TimeUnit.SECONDS)!=null)throw new AssertionError("Released lease executed");
            if(!queue.releaseUnused(items->{throw new AssertionError("Duplicate release");}))throw new AssertionError();
        }finally{finish.countDown();threads.shutdownNow();}
        LeaseReservations replay=new LeaseReservations(Arrays.asList(object("id","a"),object("id","b")));
        replay.take();replay.acknowledge("a");
        if(replay.merge(Arrays.asList(object("id","a"),object("id","b"),object("id","c")))!=1||replay.size()!=2||replay.heldCount()!=2)throw new AssertionError("Stale acknowledgement replay executed twice");
        List<Map<String,Object>> full=new ArrayList<>();for(int i=0;i<32;i++)full.add(object("id","n"+i));
        try{replay.merge(full);throw new AssertionError("Over-reservation accepted");}catch(IllegalStateException expected){}
        if(replay.size()!=2)throw new AssertionError("Failed merge mutated queue");
        System.out.println("PASS claim/release race, active exclusion, timeout retention and replay");
    }
}
