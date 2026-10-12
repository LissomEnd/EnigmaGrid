package org.enigmagrid.android;

import android.content.Context;
import java.util.*;
import java.util.function.BooleanSupplier;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.json.JSONObject;
import org.enigmagrid.core.PortableSearchJob;
import org.enigmagrid.core.PortableEventScore;
import org.enigmagrid.core.PortableSelfTest;
import static org.enigmagrid.core.Canonical.object;

/** Conservative, CPU-only Android portable_event_v1 implementation.
 *
 * Production calls require a canonical versioned asset checksum and NumPy
 * PCG64 stream states from the coordinator. All work is independently
 * replicated and canonicalized by the Python server; a failed qualification
 * must leave the bounded worker available.
 */
final class PortableJobEngine {
    private final int[] cipher,quadgrams;

    PortableJobEngine(Context context) throws Exception {
        byte[] contents=read(context,"portable_c3_scope_v1.json");
        JSONObject scope=new JSONObject(new String(contents,StandardCharsets.UTF_8));
        if(!"portable_event_v1".equals(scope.getString("engine")))
            throw new IllegalArgumentException("Wrong search engine");
        String text=scope.getString("ciphertext");
        cipher=PortableEventScore.ciphertext(text);
        byte[] table=read(context,"portable_qint_v1.bin");
        if(table.length!=PortableEventScore.QUADGRAM_ITEMS*4)
            throw new IllegalArgumentException("Unexpected fixed table size");
        byte[] digest=MessageDigest.getInstance("SHA-256").digest(table);
        StringBuilder hex=new StringBuilder(64);
        for(byte b:digest)hex.append(Character.forDigit((b>>4)&15,16)).append(Character.forDigit(b&15,16));
        if(!hex.toString().equals(scope.getString("quadgram_sha256")))
            throw new IllegalStateException("Portable reference quadgrams integrity failure");
        quadgrams=new int[PortableEventScore.QUADGRAM_ITEMS];
        try(DataInputStream stream=new DataInputStream(new ByteArrayInputStream(table))){
            for(int i=0;i<quadgrams.length;i++)quadgrams[i]=stream.readInt();
        }
        PortableSelfTest.verify(cipher,quadgrams);
    }
    private static byte[] read(Context context,String name) throws Exception {
        try(InputStream in=context.getAssets().open(name)){
            ByteArrayOutputStream out=new ByteArrayOutputStream();
            byte[] bytes=new byte[16384];int n;
            while((n=in.read(bytes))!=-1){
                if(out.size()>2*1024*1024)throw new IllegalArgumentException("Oversized asset");
                out.write(bytes,0,n);
            }
            return out.toByteArray();
        }
    }
    private static Map<?,?> asMap(Object x) {
        if(!(x instanceof Map))throw new IllegalArgumentException("Expected object");
        return (Map<?,?>)x;
    }
    private static long range(Object x,long min,long max){
        if(!(x instanceof Integer)&&!(x instanceof Long))
            throw new IllegalArgumentException("Expected exact integral number");
        long value=((Number)x).longValue();
        if(value<min||value>max)throw new IllegalArgumentException("Number outside scope");
        return value;
    }
    static final class Plan {
        final long unit,seed;
        final int minPairs,maxPairs,topk;
        final List<PortableSearchJob.SeedState> states;
        Plan(long unit,long seed,int min,int max,int k,List<PortableSearchJob.SeedState> states){
            this.unit=unit;this.seed=seed;this.minPairs=min;this.maxPairs=max;topk=k;this.states=states;
        }
    }
    static Plan validate(Map<String,Object> lease) {
        if(!"portable_event_v1".equals(lease.get("engine")))
            throw new IllegalArgumentException("Unsupported portable engine");
        String segment=String.valueOf(lease.get("segment_id"));
        long expectedBase;int min,max;
        if("portable-low-v1".equals(segment)){expectedBase=71000000000L;min=0;max=3;}
        else if("portable-normal-v1".equals(segment)){expectedBase=72000000000L;min=4;max=10;}
        else if("portable-extended-v1".equals(segment)){expectedBase=73000000000L;min=11;max=13;}
        else throw new IllegalArgumentException("Unknown canonical C3 segment");
        long unit=range(lease.get("start_unit"),0,24999);
        if(range(lease.get("end_unit"),1,25000)!=unit+1)
            throw new IllegalArgumentException("One unit per Android lease");
        Map<?,?> cfg=asMap(lease.get("config"));
        if(range(cfg.get("base_attempt"),expectedBase,expectedBase)!=expectedBase
                ||range(cfg.get("count_per_unit"),4096,4096)!=4096
                ||range(cfg.get("iterations"),512,512)!=512
                ||range(cfg.get("topk"),8,8)!=8
                ||range(cfg.get("min_pairs"),min,min)!=min
                ||range(cfg.get("max_pairs"),max,max)!=max
                ||range(cfg.get("replicas_required"),2,2)!=2)
            throw new IllegalArgumentException("Unexpected C3 search parameters");
        if(!(cfg.get("requires") instanceof List) ||
                !Arrays.asList("cpu").equals(cfg.get("requires")))
            throw new IllegalArgumentException("Portable requires CPU");
        if(!(cfg.get("event_kinds") instanceof List)
                ||!Arrays.asList(1,2,3,4,5,6).equals(cfg.get("event_kinds")))
            throw new IllegalArgumentException("Unqualified event models");
        if(!(lease.get("portable_rng_states") instanceof List))
            throw new IllegalArgumentException("Missing PCG64 seed hints");
        List<?> raw=(List<?>)lease.get("portable_rng_states");
        if(raw.size()!=16)throw new IllegalArgumentException("Expected 16 deterministic 256-key cohorts");
        List<PortableSearchJob.SeedState> states=new ArrayList<>();
        for(int i=0;i<16;i++){
            Map<?,?> item=asMap(raw.get(i));
            if(range(item.get("offset"),i*256,i*256)!=i*256)
                throw new IllegalArgumentException("PCG64 hint offset mismatch");
            if(!(item.get("state") instanceof String)||!(item.get("inc") instanceof String))
                throw new IllegalArgumentException("PCG64 hints must be decimal strings");
            String state=(String)item.get("state"),inc=(String)item.get("inc");
            if(!state.matches("[0-9]{1,39}")||!inc.matches("[0-9]{1,39}"))
                throw new IllegalArgumentException("Invalid PCG64 decimal state");
            states.add(new PortableSearchJob.SeedState(state,inc));
        }
        return new Plan(unit,expectedBase+unit*4096L,min,max,8,states);
    }
    Map<String,Object> run(Map<String,Object> lease,BooleanSupplier cancel){
        Plan job=validate(lease);
        List<PortableSearchJob.Hit> hits=PortableSearchJob.run(
                cipher,quadgrams,job.seed,4096,512,job.topk,job.minPairs,job.maxPairs,
                new int[]{1,2,3,4,5,6},job.states,cancel,
                Math.max(1,Math.min(16,Runtime.getRuntime().availableProcessors())));
        List<Object> compact=new ArrayList<>();
        for(PortableSearchJob.Hit h:hits){
            List<Integer> key=new ArrayList<>(h.key.length);
            for(int value:h.key)key.add(value);
            compact.add(object("unit",job.unit,"attempt",h.attempt,"cost",h.cost,"key",key));
        }
        if(compact.size()!=8)throw new IllegalStateException("Incomplete portable result");
        return object("summary",object("engine","portable_event_v1","units",1),
                "portable_key_rows",compact);
    }
}
