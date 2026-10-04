package org.enigmagrid.core;

import java.util.*;
import java.util.function.BooleanSupplier;
import static org.enigmagrid.core.Canonical.*;

/** Strict bounded-work intake. Never infers capabilities from a server response. */
public final class WorkEnvelope {
    private static final String ENGINE="bounded_crib_v1";
    @SuppressWarnings("unchecked")
    private static Map<String,Object> map(Object value){if(!(value instanceof Map))throw new IllegalArgumentException("Object required");return (Map<String,Object>)value;}
    private static List<?> list(Object value){if(!(value instanceof List))throw new IllegalArgumentException("Array required");return (List<?>)value;}
    private static String string(Object value){if(!(value instanceof String))throw new IllegalArgumentException("String required");return (String)value;}
    private static long number(Object value,long min,long max) {
        if(!(value instanceof Integer)&&!(value instanceof Long))throw new IllegalArgumentException("Integer required");
        long n=((Number)value).longValue();if(n<min||n>max)throw new IllegalArgumentException("Integer range");return n;
    }
    private static void exact(Map<String,Object> map,String... names){if(!map.keySet().equals(new HashSet<>(Arrays.asList(names))))throw new IllegalArgumentException("Unexpected fields");}
    private static String text(Object value){String s=string(value);if(!s.matches("[A-Z]{1,72}"))throw new IllegalArgumentException("Invalid letters");return s;}
    public static Map<String,Object> validate(Map<String,Object> lease) {
        if(!ENGINE.equals(lease.get("engine")))throw new IllegalArgumentException("Unsupported engine");
        long start=number(lease.get("start_unit"),0,Long.MAX_VALUE-1);
        if(number(lease.get("end_unit"),1,Long.MAX_VALUE)!=start+1)throw new IllegalArgumentException("One unit required");
        Map<String,Object> config=map(lease.get("config"));
        if(!Arrays.asList("cpu",ENGINE).equals(config.get("requires")))throw new IllegalArgumentException("Capability mismatch");
        Map<String,Object> job;
        if(config.containsKey("program")) {
            exact(config,"program","requires");Map<String,Object> program=map(config.get("program"));
            exact(program,"ciphertext","hypotheses","chunk","ordinal_base","candidate_limit");
            String cipher=text(program.get("ciphertext"));
            long base=number(program.get("ordinal_base"),0,Long.MAX_VALUE-start);
            int chunk=(int)number(program.get("chunk"),1,128),limit=(int)number(program.get("candidate_limit"),1,32);
            List<?> rows=list(program.get("hypotheses"));if(rows.isEmpty()||rows.size()>128)throw new IllegalArgumentException("Hypothesis count");
            List<ResearchProgram.Hypothesis> hypotheses=new ArrayList<>();
            for(Object raw:rows) {
                Map<String,Object> row=map(raw);exact(row,"text","legal_clean_offsets");String crib=text(row.get("text"));
                List<?> offsets=list(row.get("legal_clean_offsets"));if(offsets.isEmpty()||offsets.size()>72)throw new IllegalArgumentException("Offset count");
                for(Object offset:offsets)hypotheses.add(new ResearchProgram.Hypothesis(crib,(int)number(offset,0,72-crib.length())));
            }
            job=ResearchProgram.jobAt(cipher,hypotheses,base+start,chunk,limit);
        } else {exact(config,"job","requires");job=new LinkedHashMap<>(map(config.get("job")));}
        Set<String> allowed=new HashSet<>(Arrays.asList("engine","ciphertext","crib","offset","core_indices","model","pairs","budgets","id","program","ordinal"));
        if(!allowed.containsAll(job.keySet())||!ENGINE.equals(job.get("engine"))||!"clean".equals(job.get("model")))throw new IllegalArgumentException("Unsupported job");
        String cipher=text(job.get("ciphertext")),crib=text(job.get("crib"));number(job.get("offset"),0,cipher.length()-crib.length());number(job.get("pairs"),0,13);
        List<?> indices=list(job.get("core_indices"));if(indices.isEmpty()||indices.size()>128)throw new IllegalArgumentException("Domain size");
        Set<Long> seen=new HashSet<>();for(Object index:indices)if(!seen.add(number(index,0,BoundedCrib.DOMAIN-1)))throw new IllegalArgumentException("Duplicate core");
        Map<String,Object> budgets=map(job.get("budgets"));exact(budgets,"node_limit","board_limit","completion_limit","candidate_limit");
        number(budgets.get("node_limit"),1,5000);number(budgets.get("board_limit"),1,64);number(budgets.get("completion_limit"),1,256);number(budgets.get("candidate_limit"),1,2048);
        if(job.containsKey("id")&&!digest(body(job)).equals(job.get("id")))throw new IllegalArgumentException("Job identity mismatch");
        return job;
    }
    private static Map<String,Object> body(Map<String,Object> job){Map<String,Object> body=new LinkedHashMap<>(job);body.remove("id");body.remove("program");body.remove("ordinal");return body;}
    public static Map<String,Object> run(Map<String,Object> lease,BooleanSupplier cancel) {
        return run(lease,cancel,null);
    }
    public static Map<String,Object> run(Map<String,Object> lease,BooleanSupplier cancel,BoundedCrib.RowProvider provider) {
        return run(lease,cancel,provider,1);
    }
    public static Map<String,Object> run(Map<String,Object> lease,BooleanSupplier cancel,BoundedCrib.RowProvider provider,int workers) {
        Map<String,Object> job=validate(lease),budget=map(job.get("budgets"));
        List<?> values=list(job.get("core_indices"));long[] indices=new long[values.size()];for(int i=0;i<indices.length;i++)indices[i]=((Number)values.get(i)).longValue();
        Map<String,Object> receipt=BoundedCrib.search((String)job.get("ciphertext"),(String)job.get("crib"),((Number)job.get("offset")).intValue(),indices,((Number)job.get("pairs")).intValue(),((Number)budget.get("node_limit")).intValue(),((Number)budget.get("board_limit")).intValue(),((Number)budget.get("completion_limit")).intValue(),((Number)budget.get("candidate_limit")).intValue(),cancel,provider,workers);
        return object("summary",object("engine",ENGINE,"units",1,"job_hash",digest(body(job)),"status",receipt.get("status"),"exhaustive_within_scope",receipt.get("complete")),"receipt",receipt);
    }
}
