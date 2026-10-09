import java.util.*;
import org.enigmagrid.core.*;
import static org.enigmagrid.core.Canonical.object;
public class WorkBlockTransportChecks {
    static void check(boolean v){if(!v)throw new AssertionError();}
    public static void main(String[] args)throws Exception {
        WorkBlockQueueChecks.Store storage=new WorkBlockQueueChecks.Store();
        WorkBlockQueue queue=new WorkBlockQueue(storage,"server","owner",true);
        Map<String,Object> block=object("format",WorkBlock.FORMAT,"block_id","b","engine","bounded_crib_v1","start_unit",0,"end_unit",100,
            "config",object("requires",Arrays.asList("cpu","bounded_crib_v1"),"program",object("ciphertext","BDZGO","hypotheses",Arrays.asList(object("text","BD","legal_clean_offsets",Arrays.asList(0))),"chunk",3,"ordinal_base",0,"candidate_limit",3)));
        WorkBlockQueueChecks.Store lifetimeStore=new WorkBlockQueueChecks.Store();
        WorkBlockQueue lifetimeQueue=new WorkBlockQueue(lifetimeStore,"server","owner",true);
        WorkBlockTransport lifetimeTransport=new WorkBlockTransport(lifetimeQueue,(path,body)->{
            check(path.equals("/api/work-blocks")); // New coordinator allocation must avoid a status RTT.
            return object("status","reserved","block",block,"valid_for_seconds",600);
        },true);
        lifetimeTransport.allocate();check(lifetimeQueue.next()!=null);
        check(new WorkBlockQueue(lifetimeStore,"server","owner",true).next()==null); // Restart still needs status.
        List<String> requests=new ArrayList<>();boolean[] lose={true};int[] mode={0};Set<Long> received=new HashSet<>();
        WorkBlockTransport transport=new WorkBlockTransport(queue,(path,body)->{
            if(path.equals("/api/work-blocks")) {
                requests.add((String)body.get("request_id"));
                if(lose[0]){lose[0]=false;throw new java.io.IOException("Allocation response lost");}
                return object("status","reserved","block",block);
            }
            if(path.endsWith("/status"))return object("blocks",Arrays.asList(object("block_id","b","status","reserved","valid_for_seconds",600)));
            if(path.endsWith("/release"))return object("block_id","b","released",true);
            check(path.endsWith("/result-groups"));check(WorkBlockTransport.GROUP_FORMAT.equals(body.get("format")));
            List<Object> ack=new ArrayList<>();
            for(Object group:(List<?>)body.get("groups")) {
                check(((List<?>)group).size()<=8);
                for(Object raw:(List<?>)group) {
                    long unit=((Number)((Map<?,?>)raw).get("unit")).longValue();received.add(unit);
                    if(mode[0]==2&&unit%2!=0)continue;
                    ack.add(object("unit",unit,"status",mode[0]==3?"conflict":mode[0]==5?"expired":"received"));
                }
            }
            if(mode[0]==1)throw new java.io.IOException("Upload response lost");
            if(mode[0]==4)ack.add(object("unit",999L,"status","received"));
            return object("block_id","b","results",ack);
        },true);
        try{transport.allocate();throw new AssertionError();}catch(java.io.IOException expected){}
        transport.allocate();check(requests.size()==2&&requests.get(0).equals(requests.get(1)));
        for(int n=0;n<16;n++)queue.complete("b",n,object("fixture",n),.05);
        mode[0]=1;try{transport.upload();throw new AssertionError();}catch(java.io.IOException expected){}
        check(queue.pending().size()==16&&received.size()==16&&transport.acknowledgedReceipts()==0);
        mode[0]=4;try{transport.upload();throw new AssertionError();}catch(IllegalArgumentException expected){}
        check(queue.pending().size()==16);
        mode[0]=2;check(transport.upload()==8&&queue.pending().size()==8&&received.size()==16&&transport.acknowledgedReceipts()==8);
        mode[0]=3;try{transport.upload();throw new AssertionError();}catch(WorkBlockTransport.ReceiptRejected expected){}
        check(queue.pending().size()==8);
        mode[0]=0;check(transport.upload()==8&&queue.pending().isEmpty()&&received.size()==16&&transport.acknowledgedReceipts()==16);
        queue.retire();transport.releaseReady();check(queue.identities().isEmpty());
        transport.allocate();queue.complete("b",0,object("fixture","retained"),.05);
        mode[0]=5;storage.fail=true;
        try{transport.upload();throw new AssertionError("Lost archive write ignored");}catch(java.io.IOException expected){}
        storage.fail=false;check(queue.pending().size()==1&&queue.expiredReceiptCount()==0);
        check(transport.upload()==0&&queue.pending().isEmpty()&&queue.expiredReceiptCount()==1&&transport.acknowledgedReceipts()==16);
        transport.releaseReady();check(queue.identities().isEmpty());
        WorkBlockQueue afterRestart=new WorkBlockQueue(storage,"server","owner",true);
        check(afterRestart.expiredReceiptCount()==1&&afterRestart.pending().isEmpty());
        check(WorkBlockJson.json(storage.state).contains("retained"));
        mode[0]=0;transport.allocate();check(queue.identities().size()==1);
        queue.complete("b",0,object("fixture","new"),.05);check(transport.upload()==1);
        check(queue.expiredReceiptCount()==1);
        System.out.println("PASS allocation replay, grouped upload loss, partial acknowledgements, malformed ack, terminal retention and release");
    }
}
