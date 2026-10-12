package org.enigmagrid.android;

import android.app.Activity;
import android.app.Instrumentation;
import android.os.Bundle;
import android.os.SystemClock;
import java.io.InputStream;
import java.io.DataInputStream;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.json.JSONObject;
import org.json.JSONArray;
import org.enigmagrid.core.PortablePcg64;
import org.enigmagrid.core.PortableKeySampler;
import org.enigmagrid.core.PortableEventScore;
import org.enigmagrid.core.PortableSearchPrefix;

/** Bit-for-bit search prefix verification, no registration or production work. */
public final class PortableSearchPrefixQualification extends Instrumentation{
    public void onCreate(Bundle args){super.onCreate(args);start();}
    public void onStart(){
        Bundle result=new Bundle();int outcome=Activity.RESULT_CANCELED;
        long begin=SystemClock.elapsedRealtime();
        try{
            if(!"org.enigmagrid.android.lab".equals(getTargetContext().getPackageName()))
                throw new IllegalStateException("Lab only");
            JSONObject prefix=new JSONObject(new String(asset("portable_search_prefix_v1.json"),StandardCharsets.UTF_8));
            JSONObject pcg=new JSONObject(new String(asset("portable_pcg64_reference_v1.json"),StandardCharsets.UTF_8));
            JSONObject scores=new JSONObject(new String(asset("portable_score_reference_v1.json"),StandardCharsets.UTF_8));
            JSONArray gold=prefix.getJSONArray("profiles"),seeds=pcg.getJSONArray("profiles");
            if(gold.length()!=seeds.length()||gold.length()!=3)
                throw new IllegalArgumentException("Cross-reference profile mismatch");
            byte[] rawTable=asset("portable_qint_v1.bin");
            if(rawTable.length!=PortableEventScore.QUADGRAM_ITEMS*4)
                throw new IllegalArgumentException("Invalid table");
            int[] table=new int[PortableEventScore.QUADGRAM_ITEMS];
            try(DataInputStream stream=new DataInputStream(new ByteArrayInputStream(rawTable))){
                for(int i=0;i<table.length;i++)table[i]=stream.readInt();
            }
            int[] cipher=PortableEventScore.ciphertext(scores.getString("ciphertext"));
            int verified=0;
            long measured=System.nanoTime();
            for(int i=0;i<gold.length();i++){
                JSONObject profile=gold.getJSONObject(i),ref=seeds.getJSONObject(i);
                if(profile.getLong("seed")!=ref.getLong("seed"))
                    throw new AssertionError("Different C3 seed");
                PortablePcg64 stream=new PortablePcg64(ref.getString("state"),ref.getString("inc"));
                PortableKeySampler sampler=new PortableKeySampler(stream,
                    ref.getInt("min_pairs"),ref.getInt("max_pairs"),
                    new int[]{1,2,3,4,5,6});
                String[] generated=PortableSearchPrefix.simulate(cipher,table,sampler,512,prefix.getInt("tested_prefix_iterations"));
                JSONArray expected=profile.getJSONArray("snapshots");
                if(expected.length()!=generated.length)throw new AssertionError("Incomplete stage coverage");
                for(int j=0;j<generated.length;j++){
                    if(!generated[j].equals(expected.getString(j)))
                        throw new AssertionError("C3 prefix mismatch profile="+i+" iteration="+j+
                            " actual="+generated[j]+" expected="+expected.getString(j));
                    verified++;
                }
                // Full 512-step trajectory winners must agree, including tie ordering.
                JSONArray top=profile.getJSONArray("top8");
                java.util.List<org.enigmagrid.core.PortableSearchJob.Hit> candidates=
                    org.enigmagrid.core.PortableSearchJob.run(cipher,table,
                        ref.getLong("seed"),256,512,8,
                        ref.getInt("min_pairs"),ref.getInt("max_pairs"),
                        new int[]{1,2,3,4,5,6},
                        java.util.Collections.singletonList(new org.enigmagrid.core.PortableSearchJob.SeedState(
                            ref.getString("state"),ref.getString("inc"))),()->false);
                if(candidates.size()!=top.length())throw new AssertionError("Winner size");
                for(int k=0;k<top.length();k++){
                    JSONObject goldWinner=top.getJSONObject(k);
                    org.enigmagrid.core.PortableSearchJob.Hit actual=candidates.get(k);
                    if(actual.attempt!=goldWinner.getLong("attempt")||
                            actual.cost!=goldWinner.getInt("cost"))
                        throw new AssertionError("Winner mismatch profile="+i+" rank="+k);
                    JSONArray original=goldWinner.getJSONArray("key");
                    for(int pos=0;pos<actual.key.length;pos++)
                        if(actual.key[pos]!=original.getInt(pos))
                            throw new AssertionError("Winner key mismatch profile="+i+" rank="+k+" byte="+pos);
                }
            }
            double seconds=Math.max(1,System.nanoTime()-measured)/1e9;
            outcome=Activity.RESULT_OK;
            result.putString("result","PASS "+verified+" end-to-end search checkpoints exact NumPy/Numba, "+
                "256 candidates * (iterations+1) * 3 profiles; scores/s="+Math.round(256*(prefix.getInt("tested_prefix_iterations")+1)*3/seconds)+
                " elapsed_ms="+(SystemClock.elapsedRealtime()-begin));
        }catch(Throwable e){
            result.putString("result","FAIL "+e.getClass().getSimpleName()+": "+e.getMessage()+
                " elapsed_ms="+(SystemClock.elapsedRealtime()-begin));
        }
        finish(outcome,result);
    }
    private byte[] asset(String name) throws java.io.IOException {
        try(InputStream input=getTargetContext().getAssets().open(name)){
            ByteArrayOutputStream output=new ByteArrayOutputStream();
            byte[] buffer=new byte[16384];int n;
            while((n=input.read(buffer))!=-1)output.write(buffer,0,n);
            return output.toByteArray();
        }
    }
}
