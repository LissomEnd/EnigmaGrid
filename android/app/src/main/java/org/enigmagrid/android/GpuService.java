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
        if((message.what!=1&&message.what!=2&&message.what!=3)||message.replyTo==null){GpuSharedTransport.discard(message.getData(),"input");return true;}
        final boolean combined=message.what==3;
        final boolean solver=message.what==2;
        final Messenger reply=message.replyTo;final int id=message.arg1;
        if(busy){GpuSharedTransport.discard(message.getData(),"input");send(reply,id,null,"GPU busy");return true;}
        final int[] input;
        try{
            input=GpuSharedTransport.read(message.getData(),"input",combined?org.enigmagrid.core.SolverKeyBatch.MAX_INPUT:solver?5+512*72*26+72*3:org.enigmagrid.core.RowBatch.MAX_INPUT);
            if((combined||solver)&&input[0]>128){
                android.app.ActivityManager.MemoryInfo memory=new android.app.ActivityManager.MemoryInfo();
                ((android.app.ActivityManager)getSystemService(ACTIVITY_SERVICE)).getMemoryInfo(memory);
                if(memory.lowMemory||memory.availMem<256L*1024*1024)throw new IllegalStateException("Insufficient memory for GPU cohort");
            }
        }catch(Exception failure){send(reply,id,null,"Invalid or unavailable GPU request");return true;}
        busy=true;
        // A wedged native driver cannot indefinitely retain the main app's worker.
        Runnable deadline=()->android.os.Process.killProcess(android.os.Process.myPid());
        main.postDelayed(deadline,8000);
        executor.execute(()->{
            int[] rows=null;String error=null;
            try{
                if(combined){byte[] rowCode=shader(),solveCode=solverShader();rows=org.enigmagrid.core.SolverKeyBatch.execute(input,p->VulkanBackend.rows(p,rowCode),p->VulkanBackend.solve(p,solveCode));}
                else rows=solver?VulkanBackend.solve(input,solverShader()):VulkanBackend.rows(input,shader());
            }catch(Exception|LinkageError e){error=e.getClass().getSimpleName();}
            final int[] result=rows;final String failure=error;
            main.post(()->{main.removeCallbacks(deadline);busy=false;send(reply,id,result,failure);});
        });return true;
    }));
    private byte[] code;
    private byte[] solverCode;
    private byte[] solverShader()throws IOException{
        if(solverCode==null)try(InputStream in=getAssets().open("shaders/bounded_solver.comp.spv");ByteArrayOutputStream out=new ByteArrayOutputStream()){
            byte[] chunk=new byte[4096];int n;while((n=in.read(chunk))!=-1)out.write(chunk,0,n);solverCode=out.toByteArray();
        }return solverCode;
    }
    private byte[] shader()throws IOException{
        if(code==null)try(InputStream in=getAssets().open("shaders/enigma_rows.comp.spv");ByteArrayOutputStream out=new ByteArrayOutputStream()){
            byte[] chunk=new byte[4096];int n;while((n=in.read(chunk))!=-1)out.write(chunk,0,n);code=out.toByteArray();
        }return code;
    }
    private void send(Messenger target,int id,int[] rows,String error){
        Message response=Message.obtain(null,1,id,0);Bundle data=new Bundle();
        data.putLong("process_cpu_ms",android.os.Process.getElapsedCpuTime());data.putInt("process_id",android.os.Process.myPid());
        SharedMemory shared=null;
        try{
            if(error==null)shared=GpuSharedTransport.put(data,"rows",rows);else data.putString("error",error);
            response.setData(data);target.send(response);
        }catch(Exception failure){
            // No oversized Binder retry: return a small error and preserve CPU fallback.
            if(!(failure instanceof RemoteException)){
                Message rejected=Message.obtain(null,1,id,0);Bundle info=new Bundle();info.putString("error","GPU result transport failed");rejected.setData(info);
                try{target.send(rejected);}catch(RemoteException ignored){}
            }
        }finally{GpuSharedTransport.close(shared);}
    }
    @Override public IBinder onBind(Intent intent){return endpoint.getBinder();}
    @Override public void onDestroy(){executor.shutdownNow();super.onDestroy();}
}
