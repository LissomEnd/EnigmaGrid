package org.enigmagrid.core;

import java.util.*;
import static org.enigmagrid.core.Canonical.object;

/** Indexed block intake; authorization and execution credits remain server-owned. */
public final class WorkBlock {
    public static final String FORMAT="bounded_work_block_v2";
    public static final int MAX_UNITS=1_000_000;
    private WorkBlock() {}
    private static long integer(Object value) {
        if(!(value instanceof Integer)&&!(value instanceof Long))throw new IllegalArgumentException("Integer required");
        return ((Number)value).longValue();
    }
    private static Object copy(Object value) {
        if(value instanceof Map) {
            Map<String,Object> result=new LinkedHashMap<>();
            for(Map.Entry<?,?> e:((Map<?,?>)value).entrySet()) {
                if(!(e.getKey() instanceof String))throw new IllegalArgumentException("String key required");
                result.put((String)e.getKey(),copy(e.getValue()));
            }
            return result;
        }
        if(value instanceof List) {
            List<Object> result=new ArrayList<>();
            for(Object item:(List<?>)value)result.add(copy(item));
            return result;
        }
        if(value instanceof String||value instanceof Integer||value instanceof Long||value instanceof Boolean||value==null)return value;
        throw new IllegalArgumentException("Unsupported block value");
    }
    private static Map<String,Object> unit(Map<String,Object> block,long ordinal) {
        return object("engine","bounded_crib_v1","start_unit",ordinal,"end_unit",ordinal+1,"config",copy(block.get("config")));
    }
    public static void validate(Map<String,Object> block) {
        if(block==null||!block.keySet().equals(new HashSet<>(Arrays.asList("format","block_id","engine","start_unit","end_unit","config"))))throw new IllegalArgumentException("Invalid block fields");
        if(!FORMAT.equals(block.get("format"))||!"bounded_crib_v1".equals(block.get("engine")))throw new IllegalArgumentException("Unsupported block");
        Object id=block.get("block_id");
        if(!(id instanceof String)||!((String)id).matches("[A-Za-z0-9_-]{1,128}"))throw new IllegalArgumentException("Invalid block identity");
        long start=integer(block.get("start_unit")),end=integer(block.get("end_unit"));
        if(start<0||end<=start||end-start>MAX_UNITS)throw new IllegalArgumentException("Invalid block range");
        Object config=block.get("config");
        if(!(config instanceof Map)||!((Map<?,?>)config).keySet().equals(new HashSet<>(Arrays.asList("program","requires"))))throw new IllegalArgumentException("Indexed program required");
        WorkEnvelope.validate(unit(block,start));
        WorkEnvelope.validate(unit(block,end-1));
        Map<?,?> program=(Map<?,?>)((Map<?,?>)config).get("program");
        int length=((String)program.get("ciphertext")).length();
        for(Object raw:(List<?>)program.get("hypotheses")) {
            Map<?,?> hypothesis=(Map<?,?>)raw;
            for(Object offset:(List<?>)hypothesis.get("legal_clean_offsets"))
                if(integer(offset)+((String)hypothesis.get("text")).length()>length)
                    throw new IllegalArgumentException("Block contains a crib outside ciphertext");
        }
    }
    /** Queue-private validated snapshot; no mutable descriptor or unchecked API escapes. */
    static final class Prepared {
        private final Map<String,Object> descriptor;
        @SuppressWarnings("unchecked") Prepared(Map<String,Object> block){
            descriptor=(Map<String,Object>)copy(block);validate(descriptor);
        }
        boolean matches(Map<String,Object> block){return descriptor.equals(block);}
        Map<String,Object> envelope(long ordinal){
            if(ordinal<integer(descriptor.get("start_unit"))||ordinal>=integer(descriptor.get("end_unit")))throw new IllegalArgumentException("Unit outside block");
            Map<String,Object> result=unit(descriptor,ordinal);
            // Keep strict selected-unit validation here and again at execution.
            WorkEnvelope.validate(result);return result;
        }
    }
    public static Map<String,Object> unitEnvelope(Map<String,Object> block,long ordinal) {
        validate(block);
        if(ordinal<integer(block.get("start_unit"))||ordinal>=integer(block.get("end_unit")))throw new IllegalArgumentException("Unit outside block");
        Map<String,Object> result=unit(block,ordinal);
        WorkEnvelope.validate(result);
        return result;
    }
}
