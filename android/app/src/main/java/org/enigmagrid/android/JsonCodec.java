package org.enigmagrid.android;

import org.json.*;
import java.util.*;

final class JsonCodec {
    static Map<String,Object> object(String text) throws JSONException {
        return convertObject(new JSONObject(text));
    }
    private static Map<String,Object> convertObject(JSONObject object) throws JSONException {
        Map<String,Object> out=new LinkedHashMap<>();Iterator<String> keys=object.keys();
        while(keys.hasNext()){String key=keys.next();out.put(key,convert(object.get(key)));}return out;
    }
    private static Object convert(Object value) throws JSONException {
        if(value==JSONObject.NULL)return null;
        if(value instanceof JSONObject)return convertObject((JSONObject)value);
        if(value instanceof JSONArray){List<Object> out=new ArrayList<>();JSONArray a=(JSONArray)value;for(int i=0;i<a.length();i++)out.add(convert(a.get(i)));return out;}
        return value;
    }
}
