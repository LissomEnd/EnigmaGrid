package org.enigmagrid.android;

import android.content.Context;
import org.json.*;
import org.enigmagrid.core.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Device-side full receipt checks using independently generated synthetic fixtures. */
final class EngineQualification {
    static int run(Context context) throws Exception {
        return run(context,()->Thread.currentThread().isInterrupted());
    }
    static int run(Context context,java.util.function.BooleanSupplier control) throws Exception {
        return run(context,control,null);
    }
    static int run(Context context,java.util.function.BooleanSupplier control,BoundedCrib.RowProvider provider) throws Exception {
        ByteArrayOutputStream data=new ByteArrayOutputStream();
        try(InputStream input=context.getAssets().open("crib-fixtures.json")) {
            byte[] buffer=new byte[4096];int n;while((n=input.read(buffer))!=-1)data.write(buffer,0,n);
        }
        JSONArray fixtures=new JSONArray(new String(data.toByteArray(),StandardCharsets.UTF_8));
        for(int i=0;i<fixtures.length();i++) {
            JSONObject fixture=fixtures.getJSONObject(i);
            try(Scanner in=new Scanner(fixture.getString("input"))) {
                String cipher=in.next(),crib=in.next();int offset=in.nextInt(),pairs=in.nextInt(),nodes=in.nextInt(),boards=in.nextInt(),completions=in.nextInt(),candidates=in.nextInt(),count=in.nextInt();
                long[] indices=new long[count];for(int j=0;j<count;j++)indices[j]=in.nextLong();
                Map<String,Object> receipt=BoundedCrib.search(cipher,crib,offset,indices,pairs,nodes,boards,completions,candidates,control,provider);
                if(!Canonical.digest(receipt).equals(fixture.getString("receipt_sha256")))throw new IllegalStateException("Receipt mismatch at fixture "+i);
            }
        }
        CredentialStore storage=new CredentialStore(context,true);
        Map<String,Object> synthetic=Canonical.object("device_token","synthetic-test-not-a-credential","sequence",1);
        storage.save(synthetic);
        if(!Canonical.json(synthetic).equals(Canonical.json(storage.load())))throw new IllegalStateException("Keystore round trip failed");
        synthetic.put("sequence",2);storage.save(synthetic);
        if(!Canonical.json(synthetic).equals(Canonical.json(storage.load())))throw new IllegalStateException("Keystore replacement failed");
        CredentialStore pending=storage.pendingResults();
        char[] payload=new char[256*1024];Arrays.fill(payload,'A');
        Map<String,Object> large=Canonical.object("submission",new String(payload),"sequence",3);
        try {
            pending.save(large);
            if(!Canonical.json(large).equals(Canonical.json(storage.pendingResults().load())))throw new IllegalStateException("Durable result round trip failed");
            if(!Canonical.json(synthetic).equals(Canonical.json(storage.load())))throw new IllegalStateException("Result storage altered credentials");
        } finally {pending.clear();}
        if(pending.load()!=null)throw new IllegalStateException("Acknowledged result cleanup failed");
        return fixtures.length();
    }
}
