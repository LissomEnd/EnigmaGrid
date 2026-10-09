package org.enigmagrid.android;
import java.util.*;
import static org.enigmagrid.core.Canonical.object;

public final class CompletionTransportChecks {
    static final class Server extends CoordinatorClient {
        boolean legacy, malformed, mixed, endpointGone;int batchCalls,singleCalls;int bytes=262144;
        @SuppressWarnings("unchecked")
        Map<String,Object> request(String path,Map<String,Object> payload,String token)throws Exception {
            if(path.equals("/api/capabilities")){
                if(legacy)throw new HttpFailure(404);
                return object("batch_completions",true,"max_completion_count",8,"max_body_bytes",bytes);
            }
            if(path.equals("/api/complete")){singleCalls++;return object("ok",true);}
            if(!path.equals("/api/completions"))throw new AssertionError(path);
            if(endpointGone)throw new HttpFailure(404);
            batchCalls++;
            List<Map<String,Object>> results=new ArrayList<>();
            for(Map<String,Object> item:(List<Map<String,Object>>)payload.get("submissions")){
                boolean ok=!mixed||!"b".equals(item.get("lease_id"));
                results.add(object("lease_id",malformed?"other":item.get("lease_id"),"status",ok?200:422,"result",object("ok",ok)));
            }
            return object("results",results);
        }
    }
    public static void main(String[] args)throws Exception {
        List<Map<String,Object>> receipts=Arrays.asList(object("lease_id","a","work_token","test"),object("lease_id","b","work_token","test"));
        List<String> accepted=new ArrayList<>();Server server=new Server();server.mixed=true;
        try{new CompletionTransport(server).send(receipts,"token",accepted::add);throw new AssertionError();}
        catch(CoordinatorClient.HttpFailure error){if(error.status!=422)throw error;}
        if(!accepted.equals(Arrays.asList("a")))throw new AssertionError("Partial receipt removed incorrectly");
        server=new Server();server.malformed=true;accepted.clear();
        try{new CompletionTransport(server).send(receipts,"token",accepted::add);throw new AssertionError();}
        catch(IllegalStateException expected){}
        if(!accepted.isEmpty())throw new AssertionError("Malformed response partially acknowledged");
        for(boolean disappeared:new boolean[]{false,true}){
            server=new Server();server.legacy=!disappeared;server.endpointGone=disappeared;accepted.clear();
            new CompletionTransport(server).send(receipts,"token",accepted::add);
            if(accepted.size()!=2||server.singleCalls!=2)throw new AssertionError("Legacy fallback");
        }
        server=new Server();server.bytes=70;accepted.clear();
        new CompletionTransport(server).send(receipts,"token",accepted::add);
        if(server.batchCalls!=2||accepted.size()!=2)throw new AssertionError("Body bound ignored");
        server=new Server();server.bytes=1;accepted.clear();
        try{new CompletionTransport(server).send(receipts,"token",accepted::add);throw new AssertionError();}
        catch(IllegalStateException expected){}
        if(!accepted.isEmpty()||server.batchCalls!=0)throw new AssertionError("Oversized receipt sent");
        System.out.println("PASS completion capabilities, partial acknowledgement, malformed reply, body bound and fallback");
    }
}
