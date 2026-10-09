package org.enigmagrid.android;

import android.os.*;
import java.nio.*;

/** Bounded arrays in either direction; large payloads never enter Binder inline. */
final class GpuSharedTransport {
    static final int MAX_INTS=2*1024*1024; // 8 MiB: includes worst 512-core combined response.
    private GpuSharedTransport(){}
    static SharedMemory put(Bundle data,String key,int[] values)throws Exception {
        if(values==null||values.length<1||values.length>MAX_INTS)throw new IllegalArgumentException("GPU transport size");
        if(Build.VERSION.SDK_INT<27){
            if(values.length>196608)throw new IllegalStateException("Legacy GPU transport bound");
            data.putIntArray(key,values);return null;
        }
        if(values.length<=65536){data.putIntArray(key,values);return null;}
        return putSharedApi27(data,key,values);
    }
    @android.annotation.TargetApi(27)
    private static SharedMemory putSharedApi27(Bundle data,String key,int[] values)throws Exception {
        SharedMemory shared=SharedMemory.create("enigmagrid-gpu-"+key,values.length*4);
        try{
            ByteBuffer mapped=shared.mapReadWrite();
            try{mapped.order(ByteOrder.LITTLE_ENDIAN).asIntBuffer().put(values);}
            finally{SharedMemory.unmap(mapped);}
            if(!shared.setProtect(android.system.OsConstants.PROT_READ))
                throw new IllegalStateException("Cannot protect GPU data");
            data.putParcelable("shared_"+key,shared);data.putInt(key+"_count",values.length);
            return shared;
        }catch(Exception|Error failure){shared.close();throw failure;}
    }
    static int[] read(Bundle data,String key,int limit)throws Exception {
        if(limit<1||limit>MAX_INTS)throw new IllegalArgumentException("GPU transport bound");
        if(Build.VERSION.SDK_INT>=27){
            SharedMemory shared=data.getParcelable("shared_"+key);
            if(shared!=null)return readSharedApi27(data,key,limit,shared);
        }
        int[] result=data.getIntArray(key);
        if(result==null||result.length<1||result.length>Math.min(limit,196608))
            throw new IllegalStateException("Invalid inline GPU data");
        return result;
    }
    @android.annotation.TargetApi(27)
    private static int[] readSharedApi27(Bundle data,String key,int limit,SharedMemory shared)throws Exception {
        try{
            int count=data.getInt(key+"_count",0);
            if(count<1||count>limit||shared.getSize()!=count*4||data.containsKey(key))
                throw new IllegalStateException("Invalid GPU shared size");
            ByteBuffer mapped=shared.mapReadOnly();
            try{
                int[] result=new int[count];
                mapped.order(ByteOrder.LITTLE_ENDIAN).asIntBuffer().get(result);
                return result;
            }finally{SharedMemory.unmap(mapped);}
        }finally{shared.close();}
    }
    /** SharedMemory is unavailable on API 26; an inline-only packet returns null. */
    static void close(SharedMemory shared){
        if(shared!=null&&Build.VERSION.SDK_INT>=27)shared.close();
    }
    static void discard(Bundle data,String key){if(Build.VERSION.SDK_INT>=27){SharedMemory shared=data.getParcelable("shared_"+key);if(shared!=null)shared.close();}}
}
