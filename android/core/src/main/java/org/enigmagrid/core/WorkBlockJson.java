package org.enigmagrid.core;

import java.util.*;

/** Transport JSON for block timings; never used for scientific receipt hashes. */
public final class WorkBlockJson {
    private WorkBlockJson() {}
    public static String json(Object value) {
        if(value instanceof Double || value instanceof Float) {
            double number=((Number)value).doubleValue();
            if(!Double.isFinite(number))throw new IllegalArgumentException("Non-finite block timing");
            return value.toString();
        }
        if(value instanceof Map) {
            StringJoiner out=new StringJoiner(",","{","}");
            for(Map.Entry<?,?> entry:((Map<?,?>)value).entrySet()) {
                if(!(entry.getKey() instanceof String))throw new IllegalArgumentException("String key required");
                out.add(Canonical.json(entry.getKey())+":"+json(entry.getValue()));
            }
            return out.toString();
        }
        if(value instanceof Iterable) {
            StringJoiner out=new StringJoiner(",","[","]");
            for(Object entry:(Iterable<?>)value)out.add(json(entry));
            return out.toString();
        }
        return Canonical.json(value);
    }
}
