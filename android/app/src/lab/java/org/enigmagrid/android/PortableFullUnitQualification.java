package org.enigmagrid.android;

import android.app.Activity;
import android.app.Instrumentation;
import android.os.Bundle;
import android.os.SystemClock;
import java.util.*;
import java.nio.charset.StandardCharsets;
import java.io.*;
import org.json.*;
import static org.enigmagrid.core.Canonical.object;

/** Replay one historically verified full 4096x512 C3 unit, never submit it. */
public final class PortableFullUnitQualification extends Instrumentation {
    public void onCreate(Bundle args){super.onCreate(args);start();}
    public void onStart(){
        Bundle out=new Bundle();int result=Activity.RESULT_CANCELED;
        long began=SystemClock.elapsedRealtime();
        try{
            if(!getTargetContext().getPackageName().equals("org.enigmagrid.android.lab"))
                throw new IllegalStateException("Lab-only unit replay");
            StringBuilder text=new StringBuilder();
            try(InputStream src=getTargetContext().getAssets().open("portable_fullunit_v1.json")){
                byte[] data=new byte[4096];int n;
                while((n=src.read(data))!=-1)text.append(new String(data,0,n,StandardCharsets.UTF_8));
            }
            JSONObject fixture=new JSONObject(text.toString()),rawCfg=fixture.getJSONObject("config");
            List<Object> kinds=Arrays.asList(1,2,3,4,5,6);
            Map<String,Object> cfg=object("base_attempt",rawCfg.getLong("base_attempt"),
                "count_per_unit",4096,"iterations",512,"topk",8,
                "min_pairs",rawCfg.getInt("min_pairs"),"max_pairs",rawCfg.getInt("max_pairs"),
                "event_kinds",kinds,"requires",Collections.singletonList("cpu"),
                "replicas_required",2);
            List<Object> seeds=new ArrayList<>();
            JSONArray states=fixture.getJSONArray("pcg_states");
            for(int i=0;i<states.length();i++){
                JSONObject state=states.getJSONObject(i);
                seeds.add(object("offset",state.getInt("offset"),
                                 "state",state.getString("state"),"inc",state.getString("inc")));
            }
            Map<String,Object> lease=object("engine","portable_event_v1",
                    "segment_id",fixture.getString("segment_id"),
                    "start_unit",0,"end_unit",1,"config",cfg,"portable_rng_states",seeds);
            PortableJobEngine engine=new PortableJobEngine(getTargetContext());
            long searchStarted=System.nanoTime();
            Map<String,Object> actual=engine.run(lease,()->Thread.currentThread().isInterrupted());
            double seconds=Math.max(1,System.nanoTime()-searchStarted)/1e9;
            JSONArray expected=fixture.getJSONArray("expected_top8");
            Object unknown=actual.get("portable_key_rows");
            if(!(unknown instanceof List))throw new AssertionError("Invalid receipt shape");
            List<?> rows=(List<?>)unknown;
            if(rows.size()!=expected.length())throw new AssertionError("Incorrect candidate count");
            for(int i=0;i<rows.size();i++){
                if(!(rows.get(i) instanceof Map))throw new AssertionError("Bad compact row");
                Map<?,?> item=(Map<?,?>)rows.get(i);
                JSONObject expectedRow=expected.getJSONObject(i);
                if(((Number)item.get("attempt")).longValue()!=expectedRow.getLong("attempt")
                   ||((Number)item.get("cost")).intValue()!=expectedRow.getInt("cost"))
                    throw new AssertionError("Incorrect 4096x512 result at rank="+i+
                       " expected="+expectedRow+" actual="+item);
            }
            result=Activity.RESULT_OK;
            out.putString("result","PASS full 4096-trajectory x 512-iteration C3 portable job; "+
                rows.size()+" historical verified winners matched; cost+attempt exact; seconds="+
                String.format(java.util.Locale.US,"%.1f",seconds)+
                " trajectories_per_second="+Math.round(4096.0/seconds)+
                "; no results submitted or duplicated");
        }catch(Throwable e){
            out.putString("result","FAIL "+e.getClass().getSimpleName()+": "+
                e.getMessage()+" elapsed_ms="+(SystemClock.elapsedRealtime()-began));
        }
        finish(result,out);
    }
}
