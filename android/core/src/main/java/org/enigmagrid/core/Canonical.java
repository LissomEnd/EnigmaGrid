package org.enigmagrid.core;

import java.util.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/** Python-compatible canonical JSON for the integer/ASCII work protocol. */
public final class Canonical {
    private Canonical() {}
    public static String json(Object value) {
        if(value==null)return "null";
        if(value instanceof Boolean || value instanceof Integer || value instanceof Long)return value.toString();
        if(value instanceof String) {
            StringBuilder s=new StringBuilder("\"");
            for(char c:((String)value).toCharArray()) {
                switch(c) {
                    case '"':s.append("\\\"");break;
                    case '\\':s.append("\\\\");break;
                    case '\b':s.append("\\b");break;
                    case '\f':s.append("\\f");break;
                    case '\n':s.append("\\n");break;
                    case '\r':s.append("\\r");break;
                    case '\t':s.append("\\t");break;
                    default:if(c<32 || c>126)s.append(String.format(Locale.ROOT,"\\u%04x",(int)c));else s.append(c);
                }
            }
            return s.append('"').toString();
        }
        if(value instanceof Map) {
            TreeMap<String,Object> sorted=new TreeMap<>();
            for(Map.Entry<?,?> e:((Map<?,?>)value).entrySet()) {
                if(!(e.getKey() instanceof String))throw new IllegalArgumentException("String keys only");
                sorted.put((String)e.getKey(),e.getValue());
            }
            StringJoiner out=new StringJoiner(",","{","}");
            for(Map.Entry<String,Object> e:sorted.entrySet())out.add(json(e.getKey())+":"+json(e.getValue()));
            return out.toString();
        }
        if(value instanceof Iterable) {
            StringJoiner out=new StringJoiner(",","[","]");for(Object v:(Iterable<?>)value)out.add(json(v));return out.toString();
        }
        throw new IllegalArgumentException("Unsupported JSON type");
    }
    public static String sha256(String text) {
        try {
            byte[] bytes=MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8));
            StringBuilder s=new StringBuilder();for(byte b:bytes)s.append(String.format(Locale.ROOT,"%02x",b&255));return s.toString();
        }catch(java.security.NoSuchAlgorithmException e){throw new IllegalStateException(e);}
    }
    public static String digest(Object value){return sha256(json(value));}
    public static Map<String,Object> object(Object... entries) {
        Map<String,Object> m=new LinkedHashMap<>();for(int i=0;i<entries.length;i+=2)m.put((String)entries[i],entries[i+1]);return m;
    }
}
