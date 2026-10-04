package org.enigmagrid.android;

import android.app.Service;
import android.content.Intent;
import android.os.*;
import java.io.*;
import java.util.concurrent.*;

/** Native driver calls live outside the UI/worker process. Not exported. */
public final class GpuService extends Service {
    private final Handler main=new Handler(Looper.getMainLooper());
    private final ExecutorService executor=Executors.newSingleThreadExecutor();
    private boolean busy;
    private final Messenger endpoint=new Messenger(new Handler(Looper.getMainLooper(),message->{
        if(message.what!=1||message.replyTo==null)return true;
        final Messenger reply=message.replyTo;final int id=message.arg1;
        if(busy){send(reply,id,null,"GPU busy");return true;}
        int[] input=message.getData().getIntArray("input");
        if(input==null||input.length>1273){send(reply,id,null,"Invalid GPU request");return true;}
        busy=true;
        // A wedged native driver cannot indefinitely retain the main app's worker.
        Runnable deadline=()->android.os.Process.killProcess(android.os.Process.myPid());
        main.postDelayed(deadline,8000);
        executor.execute(()->{
            int[] rows=null;String error=null;
            try{rows=VulkanBackend.rows(input,shader());}catch(Exception|LinkageError e){error=e.getClass().getSimpleName();}
            final int[] result=rows;final String failure=error;
            main.post(()->{main.removeCallbacks(deadline);busy=false;send(reply,id,result,failure);});
        });return true;
    }));
    private byte[] code;
    private byte[] shader()throws IOException{
        if(code==null)try(InputStream in=getAssets().open("shaders/enigma_rows.comp.spv");ByteArrayOutputStream out=new ByteArrayOutputStream()){
            byte[] chunk=new byte[4096];int n;while((n=in.read(chunk))!=-1)out.write(chunk,0,n);code=out.toByteArray();
        }return code;
    }
    private void send(Messenger target,int id,int[] rows,String error){
        Message response=Message.obtain(null,1,id,0);Bundle data=new Bundle();
        if(error==null)data.putIntArray("rows",rows);else data.putString("error",error);response.setData(data);
        try{target.send(response);}catch(RemoteException ignored){}
    }
    @Override public IBinder onBind(Intent intent){return endpoint.getBinder();}
    @Override public void onDestroy(){executor.shutdownNow();super.onDestroy();}
}
