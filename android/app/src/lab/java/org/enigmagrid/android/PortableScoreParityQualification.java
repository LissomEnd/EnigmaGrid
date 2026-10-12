package org.enigmagrid.android;

import android.app.Activity;
import android.app.Instrumentation;
import android.os.Bundle;
import android.os.SystemClock;
import java.io.DataInputStream;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Arrays;
import org.json.JSONArray;
import org.json.JSONObject;
import org.enigmagrid.core.PortableEventScore;

/** Isolated portable-event scoring parity. Never enrolls or requests work. */
public final class PortableScoreParityQualification extends Instrumentation {
    public void onCreate(Bundle args){super.onCreate(args);start();}
    public void onStart(){
        Bundle result=new Bundle();int outcome=Activity.RESULT_CANCELED;
        long start=SystemClock.elapsedRealtime();
        try{
            if(!getTargetContext().getPackageName().equals("org.enigmagrid.android.lab"))
                throw new IllegalStateException("Lab instrumentation required");
            byte[] tableBytes;
            try(InputStream in=getTargetContext().getAssets().open("portable_qint_v1.bin")){
                tableBytes=readFully(in);
            }
            if(tableBytes.length!=PortableEventScore.QUADGRAM_ITEMS*4)
                throw new IllegalArgumentException("Invalid quadgram byte length");
            String digest=hex(MessageDigest.getInstance("SHA-256").digest(tableBytes));
            String fixtureText;
            try(InputStream in=getTargetContext().getAssets().open("portable_score_reference_v1.json")){
                fixtureText=new String(readFully(in),StandardCharsets.UTF_8);
            }
            JSONObject fixture=new JSONObject(fixtureText);
            if(!digest.equals(fixture.getString("quadgram_sha256")))
                throw new IllegalStateException("Quadgram SHA256 mismatch");
            int[] costs=new int[PortableEventScore.QUADGRAM_ITEMS];
            try(DataInputStream in=new DataInputStream(new java.io.ByteArrayInputStream(tableBytes))){
                for(int i=0;i<costs.length;i++)costs[i]=in.readInt();
            }
            int[] ciphertext=PortableEventScore.ciphertext(fixture.getString("ciphertext"));
            JSONArray groups=fixture.getJSONArray("scope");
            int total=0;
            long begin=System.nanoTime();
            for(int grp=0;grp<groups.length();grp++){
                JSONObject item=groups.getJSONObject(grp);
                JSONArray keys=item.getJSONArray("keys"),expected=item.getJSONArray("scores");
                if(keys.length()!=expected.length())throw new AssertionError("Fixture size mismatch");
                for(int sample=0;sample<keys.length();sample++){
                    JSONArray row=keys.getJSONArray(sample);
                    int[] key=new int[row.length()];
                    for(int j=0;j<key.length;j++)key[j]=row.getInt(j);
                    int actual=PortableEventScore.score(ciphertext,key,costs);
                    int correct=expected.getInt(sample);
                    if(actual!=correct)throw new AssertionError("Mismatch profile="+grp+" index="+sample+" computed="+actual+" reference="+correct);
                    total++;
                }
            }
            if(total!=288)throw new AssertionError("Missing score fixtures");
            double scoresPerSecond=total*1e9/Math.max(1,System.nanoTime()-begin);
            result.putString("result","PASS 288 exact int32 scores against NumPy/Numba all 6 event kinds, 72 event offsets, three plugboard profiles; score_per_second="+Math.round(scoresPerSecond)+" duration_ms="+(SystemClock.elapsedRealtime()-start));
            outcome=Activity.RESULT_OK;
        }catch(Throwable failure){
            result.putString("result","FAIL "+failure.getClass().getSimpleName()+": "+failure.getMessage()+" duration_ms="+(SystemClock.elapsedRealtime()-start));
        }
        finish(outcome,result);
    }
    private static byte[] readFully(InputStream input) throws java.io.IOException{
        ByteArrayOutputStream buffer=new ByteArrayOutputStream();
        byte[] chunk=new byte[16384];int n;
        while((n=input.read(chunk))!=-1)buffer.write(chunk,0,n);
        return buffer.toByteArray();
    }
    private static String hex(byte[] bytes){
        StringBuilder s=new StringBuilder(bytes.length*2);
        for(byte b:bytes)s.append(Character.forDigit((b>>4)&15,16)).append(Character.forDigit(b&15,16));
        return s.toString();
    }
}
