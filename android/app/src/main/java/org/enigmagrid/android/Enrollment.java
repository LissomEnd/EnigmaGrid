package org.enigmagrid.android;

import android.os.Build;
import java.math.BigInteger;
import java.util.*;
import java.util.function.BooleanSupplier;
import java.util.concurrent.CancellationException;
import org.enigmagrid.core.Canonical;
import static org.enigmagrid.core.Canonical.object;

/** Explicit enrollment only; never called automatically on app launch. */
final class Enrollment {
    static Map<String,Object> metadata(){return object("worker_version","0.4.8","platform","Android "+Build.VERSION.RELEASE,"machine",Build.SUPPORTED_ABIS[0],"cpu_count",Runtime.getRuntime().availableProcessors(),"gpus",Collections.emptyList(),"capabilities",Arrays.asList("cpu","bounded_crib_v1"),"supported_engines",Arrays.asList("bounded_crib_v1"));}
    static synchronized Map<String,Object> register(CoordinatorClient client,CredentialStore store,String name,String joinKey,Map<String,Object> settings,BooleanSupplier cancel) throws Exception {
        return register(client,store,name,joinKey,settings,false,cancel);
    }
    static synchronized Map<String,Object> register(CoordinatorClient client,CredentialStore store,String name,String joinKey,Map<String,Object> settings,boolean publicCredit,BooleanSupplier cancel) throws Exception {
        if(store.load()!=null)throw new IllegalStateException("An account is already saved");
        CredentialStore attempt=store.registrationAttempt();
        if(attempt.load()!=null)throw new IllegalStateException("An earlier registration has an unknown outcome; do not register again");
        Map<String,Object> challenge=client.request("/api/register-challenge",null,null);
        Object nonceValue=challenge.get("nonce"),bitsValue=challenge.get("difficulty_bits");
        if(!(nonceValue instanceof String)||!(bitsValue instanceof Number))throw new IllegalArgumentException("Invalid registration challenge");
        String nonce=(String)nonceValue;int bits=((Number)bitsValue).intValue();
        if(nonce.length()>512||bits<0||bits>22)throw new IllegalArgumentException("Unsupported challenge budget");
        long counter=0;long deadline=System.nanoTime()+60_000_000_000L;
        while(true) {
            if(Thread.currentThread().isInterrupted()||cancel.getAsBoolean())throw new CancellationException();
            if(System.nanoTime()>deadline)throw new IllegalStateException("Registration challenge timed out");
            if(new BigInteger(Canonical.sha256(nonce+":"+counter),16).shiftRight(256-bits).signum()==0)break;
            counter++;
        }
        Map<String,Object> payload=object("display_name",name.trim().isEmpty()?"Anonymous volunteer":name.trim(),"device_label","Android device","public_credit",publicCredit,"meta",metadata(),"settings",settings,"pow_nonce",nonce,"pow_counter",counter);
        if(joinKey!=null&&!joinKey.trim().isEmpty())payload.put("contributor_key",joinKey.trim());
        // A timeout here is ambiguous: caller must not automatically register again.
        attempt.save(object("server",client.origin(),"started_at",System.currentTimeMillis()));
        Map<String,Object> response;
        try{response=client.request("/api/register",payload,null);}
        catch(CoordinatorClient.HttpFailure e){
            // These responses reject the request before account creation in this protocol.
            if(e.status==400||e.status==403||e.status==404||e.status==429)attempt.clear();
            throw e;
        }
        for(String key:Arrays.asList("device_id","device_token","contributor_id"))if(!(response.get(key) instanceof String))throw new IllegalArgumentException("Incomplete registration response");
        Map<String,Object> state=object("server",client.origin(),"device_id",response.get("device_id"),"device_token",response.get("device_token"),"contributor_id",response.get("contributor_id"));
        if(response.get("contributor_key") instanceof String)state.put("contributor_key",response.get("contributor_key"));
        if(response.get("dashboard_token") instanceof String)state.put("dashboard_token",response.get("dashboard_token"));
        store.save(state);attempt.clear();return state;
    }
}
