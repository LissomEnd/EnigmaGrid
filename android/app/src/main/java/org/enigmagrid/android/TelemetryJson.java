package org.enigmagrid.android;

import java.util.Map;
import java.util.StringJoiner;
import java.util.TreeMap;
import org.enigmagrid.core.Canonical;

/** JSON for disposable diagnostics, which contain finite decimal sensor readings.
 * The scientific work protocol deliberately keeps its integer-only serializer. */
final class TelemetryJson {
    private TelemetryJson() {}

    static String json(Object value) {
        if(value instanceof Double) {
            double number=(Double)value;
            if(!Double.isFinite(number))throw new IllegalArgumentException("Non-finite telemetry reading");
            return Double.toString(number);
        }
        if(value instanceof Float) {
            float number=(Float)value;
            if(!Float.isFinite(number))throw new IllegalArgumentException("Non-finite telemetry reading");
            return Float.toString(number);
        }
        if(value instanceof Map) {
            TreeMap<String,Object> sorted=new TreeMap<>();
            for(Map.Entry<?,?> entry:((Map<?,?>)value).entrySet()) {
                if(!(entry.getKey() instanceof String))throw new IllegalArgumentException("String telemetry keys only");
                sorted.put((String)entry.getKey(),entry.getValue());
            }
            StringJoiner out=new StringJoiner(",","{","}");
            for(Map.Entry<String,Object> entry:sorted.entrySet())
                out.add(Canonical.json(entry.getKey())+":"+json(entry.getValue()));
            return out.toString();
        }
        if(value instanceof Iterable) {
            StringJoiner out=new StringJoiner(",","[","]");
            for(Object item:(Iterable<?>)value)out.add(json(item));
            return out.toString();
        }
        return Canonical.json(value);
    }
}
