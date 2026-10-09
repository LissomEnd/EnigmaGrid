import java.util.*;
import org.enigmagrid.core.*;
import static org.enigmagrid.core.Canonical.object;

public class ReceiptStorageSessionChecks {
    static final class Disk implements ReceiptQueue.Storage {
        Map<String,Object> value;int reads,writes;boolean fail;
        public Map<String,Object> load(){reads++;return value;}
        public void save(Map<String,Object> v) throws Exception {if(fail)throw new java.io.IOException();value=v;writes++;}
    }
    public static void main(String[] args)throws Exception {
        Disk disk=new Disk();ReceiptQueue q=new ReceiptQueue(new ReceiptStorageSession(disk),"server","owner");
        q.append(object("lease_id","a"));q.append(object("lease_id","b"));
        if(disk.reads!=1||disk.writes!=2)throw new AssertionError("Unexpected storage operations");
        disk.fail=true;
        try{q.acknowledge("a");throw new AssertionError("Failed write accepted");}catch(java.io.IOException expected){}
        if(q.pending().size()!=2)throw new AssertionError("Failed ack lost receipt");
        try{q.append(object("lease_id","c"));throw new AssertionError("Failed append accepted");}catch(java.io.IOException expected){}
        if(q.pending().size()!=2)throw new AssertionError("Failed append changed session");
        disk.fail=false;q.acknowledge("a");
        ReceiptQueue restarted=new ReceiptQueue(new ReceiptStorageSession(disk),"server","owner");
        if(restarted.pending().size()!=1||!"b".equals(restarted.pending().get(0).get("lease_id")))throw new AssertionError("Restart lost receipt");
        try{new ReceiptQueue(new ReceiptStorageSession(disk),"server","other").pending();throw new AssertionError("Wrong owner accepted");}catch(IllegalStateException expected){}
        restarted.acknowledge("b");if(!restarted.pending().isEmpty())throw new AssertionError();
        restarted.append(object("lease_id","x"));
        disk.fail=true;
        try{restarted.advance(object("lease_id","y"),"x");throw new AssertionError();}catch(java.io.IOException expected){}
        if(!"x".equals(restarted.pending().get(0).get("lease_id")))throw new AssertionError("Failed transition lost predecessor");
        disk.fail=false;int writes=disk.writes;restarted.advance(object("lease_id","y"),"x");
        if(disk.writes!=writes+1||restarted.pending().size()!=1)throw new AssertionError("Transition not atomic");
        ReceiptQueue afterTransition=new ReceiptQueue(new ReceiptStorageSession(disk),"server","owner");
        if(!"y".equals(afterTransition.pending().get(0).get("lease_id")))throw new AssertionError("Transition restart");
        writes=disk.writes;afterTransition.confirm("y");
        if(disk.writes!=writes)throw new AssertionError("Confirmation wrote before coalescing");
        if(new ReceiptQueue(new ReceiptStorageSession(disk),"server","owner").pending().size()!=1)throw new AssertionError("Crash replay missing");
        disk.fail=true;
        try{afterTransition.append(object("lease_id","z"));throw new AssertionError();}catch(java.io.IOException expected){}
        if(!"y".equals(afterTransition.pending().get(0).get("lease_id")))throw new AssertionError("Failed coalesced write lost receipt");
        disk.fail=false;afterTransition.append(object("lease_id","z"));
        if(disk.writes!=writes+1||afterTransition.pending().size()!=1||!"z".equals(afterTransition.pending().get(0).get("lease_id")))throw new AssertionError("Ack and append not coalesced");
        afterTransition.confirm("z");afterTransition.flushConfirmed();
        if(!afterTransition.pending().isEmpty())throw new AssertionError("Final confirmations not flushed");
        Disk reservedDisk=new Disk();ReceiptQueue bounded=new ReceiptQueue(new ReceiptStorageSession(reservedDisk),"server","owner");
        for(int i=0;i<8;i++)if(!bounded.reserve("r"+i))throw new AssertionError("Reservation rejected before count limit");
        if(bounded.reserve("extra")||bounded.reserve("r0")||bounded.hasCapacity())throw new AssertionError("Overbooked or duplicate reservation");
        try{bounded.append(object("lease_id","unreserved"));throw new AssertionError("Unreserved append stole slot");}catch(IllegalStateException expected){}
        reservedDisk.fail=true;
        try{bounded.append(object("lease_id","r0"));throw new AssertionError();}catch(java.io.IOException expected){}
        if(bounded.reservedCount()!=8||!bounded.pending().isEmpty())throw new AssertionError("Failed save consumed reservation");
        reservedDisk.fail=false;
        java.util.concurrent.ExecutorService producers=java.util.concurrent.Executors.newFixedThreadPool(4);
        try{
            List<java.util.concurrent.Future<?>> writesPending=new ArrayList<>();
            for(int i=0;i<8;i++){final int index=i;writesPending.add(producers.submit(()->{try{bounded.append(object("lease_id","r"+index));}catch(Exception e){throw new RuntimeException(e);}}));}
            for(java.util.concurrent.Future<?> write:writesPending)write.get();
        }finally{producers.shutdownNow();}
        if(bounded.reservedCount()!=0||bounded.pending().size()!=8)throw new AssertionError("Concurrent durable results lost");
        bounded.confirm("r0");if(!bounded.reserve("new"))throw new AssertionError("Acknowledged slot not reclaimed");
        bounded.releaseReservation("new");bounded.releaseReservation("r1");
        if(bounded.pending().size()!=8)throw new AssertionError("Cancellation removed durable result");
        System.out.println("PASS durable session writes, failed-write rollback, restart and account isolation");
    }
}
