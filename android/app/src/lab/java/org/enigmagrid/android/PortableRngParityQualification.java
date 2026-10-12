package org.enigmagrid.android;

import android.app.Activity;
import android.app.Instrumentation;
import android.os.Bundle;
import android.os.SystemClock;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.enigmagrid.core.PortablePcg64;
import org.enigmagrid.core.PortableKeySampler;
import org.json.JSONObject;
import org.json.JSONArray;

/** Canonical PCG64 raw, initial 256 keys and two mutation step hashes. */
public final class PortableRngParityQualification extends Instrumentation {
    public void onCreate(Bundle args){super.onCreate(args);start();}
    public void onStart(){
        Bundle result=new Bundle();int outcome=Activity.RESULT_CANCELED;
        long begin=SystemClock.elapsedRealtime();
        try{
            if(!"org.enigmagrid.android.lab".equals(getTargetContext().getPackageName()))
                throw new IllegalStateException("Lab app only");
            String text;
            try(InputStream in=getTargetContext().getAssets().open("portable_pcg64_reference_v1.json")){
                text=new String(readFully(in),StandardCharsets.UTF_8);
            }
            JSONArray profiles=new JSONObject(text).getJSONArray("profiles");
            int rawVerified=0,initialVerified=0,mutationsVerified=0;
            int[] kinds={1,2,3,4,5,6};
            for(int i=0;i<profiles.length();i++){
                JSONObject item=profiles.getJSONObject(i);
                String state=item.getString("state"),inc=item.getString("inc");
                PortablePcg64 raw=new PortablePcg64(state,inc);
                JSONArray expectedRaw=item.getJSONArray("first_24_uint64");
                for(int j=0;j<expectedRaw.length();j++){
                    String actual=Long.toUnsignedString(raw.nextUint64());
                    if(!actual.equals(expectedRaw.getString(j)))
                        throw new AssertionError("PCG64 bit mismatch profile="+i+" draw="+j+
                            " actual="+actual+" reference="+expectedRaw.getString(j));
                    rawVerified++;
                }
                PortableKeySampler sampler=new PortableKeySampler(
                    new PortablePcg64(state,inc),
                    item.getInt("min_pairs"),item.getInt("max_pairs"),kinds);
                JSONArray hashes=item.getJSONArray("hashes");
                int[][] keys=sampler.initial();
                if(!hash(keys).equals(hashes.getString(0)))
                    throw new AssertionError("First 256 keys differ profile="+i+" actual="+hash(keys));
                initialVerified++;
                for(int j=1;j<hashes.length();j++){
                    keys=sampler.mutate(keys);
                    String actual=hash(keys);
                    if(!actual.equals(hashes.getString(j)))
                        throw new AssertionError("Mutation differs profile="+i+" step="+j+" actual="+actual);
                    mutationsVerified++;
                }
            }
            if(profiles.length()!=3||rawVerified!=72||initialVerified!=3||mutationsVerified!=6)
                throw new AssertionError("Missing reference coverage");
            outcome=Activity.RESULT_OK;
            result.putString("result","PASS "+rawVerified+" PCG64 unsigned64 stream words, "+
                (initialVerified*256)+" initial keys and "+(mutationsVerified*256)+
                " mutated keys, all byte-for-byte matching NumPy/Numba; elapsed_ms="+
                (SystemClock.elapsedRealtime()-begin));
        }catch(Throwable e){
            result.putString("result","FAIL "+e.getClass().getSimpleName()+": "+e.getMessage()
                +" elapsed_ms="+(SystemClock.elapsedRealtime()-begin));
        }
        finish(outcome,result);
    }
    private static String hash(int[][] keys) throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        ByteBuffer buffer=ByteBuffer.allocate(42*256*4).order(ByteOrder.LITTLE_ENDIAN);
        for(int[] row:keys){
            if(row.length!=42)throw new IllegalArgumentException("Invalid key row");
            for(int v:row)buffer.putInt(v);
        }
        byte[] hashed=digest.digest(buffer.array());
        StringBuilder hex=new StringBuilder();
        for(byte b:hashed)hex.append(Character.forDigit((b>>4)&15,16))
                .append(Character.forDigit(b&15,16));
        return hex.toString();
    }
    private static byte[] readFully(InputStream source) throws java.io.IOException {
        ByteArrayOutputStream sink=new ByteArrayOutputStream();
        byte[] block=new byte[8192];int n;
        while((n=source.read(block))!=-1)sink.write(block,0,n);
        return sink.toByteArray();
    }
}
