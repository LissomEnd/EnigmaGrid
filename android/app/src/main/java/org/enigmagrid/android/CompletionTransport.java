package org.enigmagrid.android;

import java.util.*;
import java.nio.charset.StandardCharsets;
import org.enigmagrid.core.Canonical;
import static org.enigmagrid.core.Canonical.object;

/** One uploader owns negotiation; only explicit per-lease success is acknowledged. */
final class CompletionTransport {
    interface Ack {void accepted(String leaseId) throws Exception;}
    private final CoordinatorClient client;
    private Map<String,Object> capabilities;
    CompletionTransport(CoordinatorClient client){this.client=client;}
    @SuppressWarnings("unchecked")
    void send(List<Map<String,Object>> pending,String token,Ack acknowledge) throws Exception {
        if(capabilities==null){
            try{capabilities=client.request("/api/capabilities",null,null);}
            catch(CoordinatorClient.HttpFailure error){
                if(error.status!=404&&error.status!=405)throw error;
                capabilities=Collections.emptyMap();
            }
        }
        if(!Boolean.TRUE.equals(capabilities.get("batch_completions"))){
            for(Map<String,Object> receipt:pending){
                Map<String,Object> result=client.request("/api/complete",receipt,token);
                if(!Boolean.TRUE.equals(result.get("ok")))throw new IllegalStateException("Receipt not acknowledged");
                acknowledge.accepted((String)receipt.get("lease_id"));
            }
            return;
        }
        int count=limit("max_completion_count",8,8),bytes=limit("max_body_bytes",262144,4*1024*1024);
        int position=0;
        while(position<pending.size()){
            List<Map<String,Object>> batch=new ArrayList<>();
            while(position+batch.size()<pending.size()&&batch.size()<count){
                batch.add(pending.get(position+batch.size()));
                if(Canonical.json(object("submissions",batch)).getBytes(StandardCharsets.UTF_8).length>bytes){batch.remove(batch.size()-1);break;}
            }
            if(batch.isEmpty())throw new IllegalStateException("Saved receipt exceeds coordinator body limit; retained");
            Map<String,Object> response;
            try{response=client.request("/api/completions",object("submissions",batch),token);}
            catch(CoordinatorClient.HttpFailure error){
                if(error.status!=404&&error.status!=405)throw error;
                capabilities=Collections.emptyMap();send(pending.subList(position,pending.size()),token,acknowledge);return;
            }
            Object raw=response.get("results");
            if(!(raw instanceof List)||((List<?>)raw).size()!=batch.size())throw new IllegalStateException("Incomplete batch acknowledgement");
            Set<String> expected=new HashSet<>(),seen=new HashSet<>();
            for(Map<String,Object> item:batch)expected.add((String)item.get("lease_id"));
            for(Object value:(List<?>)raw){
                if(!(value instanceof Map))throw new IllegalStateException("Invalid batch result");
                Map<?,?> item=(Map<?,?>)value;Object id=item.get("lease_id"),status=item.get("status");
                if(!(id instanceof String)||!expected.contains(id)||!seen.add((String)id)||!(status instanceof Number)||!(item.get("result") instanceof Map))throw new IllegalStateException("Invalid batch result");
                double number=((Number)status).doubleValue();if(!Double.isFinite(number)||number!=Math.rint(number)||number<100||number>599)throw new IllegalStateException("Invalid result status");
            }
            int failure=0;
            for(Object value:(List<?>)raw){
                Map<?,?> item=(Map<?,?>)value;int status=((Number)item.get("status")).intValue();
                if(status>=200&&status<300&&Boolean.TRUE.equals(((Map<?,?>)item.get("result")).get("ok")))acknowledge.accepted((String)item.get("lease_id"));
                else if(failure==0)failure=status>=400?status:503;
            }
            if(failure!=0)throw new CoordinatorClient.HttpFailure(failure);
            position+=batch.size();
        }
    }
    private int limit(String key,int fallback,int maximum){
        Object value=capabilities.get(key);if(value==null)return fallback;
        if(!(value instanceof Number))throw new IllegalStateException("Invalid coordinator limits");
        double number=((Number)value).doubleValue();
        if(!Double.isFinite(number)||number!=Math.rint(number)||number<1||number>maximum)throw new IllegalStateException("Invalid coordinator limits");
        return (int)number;
    }
}
