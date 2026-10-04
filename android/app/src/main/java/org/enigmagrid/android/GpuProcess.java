package org.enigmagrid.android;

import android.content.*;
import android.os.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

/** Bounded IPC waits; native crash or timeout leaves CPU fallback available. */
final class GpuProcess implements AutoCloseable {
    static String qualificationKey(){return "ipc-v1:"+Build.FINGERPRINT;}
    private final Context context;
    private final Handler main=new Handler(Looper.getMainLooper());
    private final HandlerThread callbacks=new HandlerThread("gpu-replies");
    private final CompletableFuture<Messenger> ready=new CompletableFuture<>();
    private final ConcurrentHashMap<Integer,CompletableFuture<int[]>> pending=new ConcurrentHashMap<>();
    private final AtomicInteger sequence=new AtomicInteger();
    private final Messenger replies;
    private volatile boolean closed;
    private boolean bound;
    private final ServiceConnection connection=new ServiceConnection(){
        public void onServiceConnected(ComponentName name,IBinder binder){if(!closed)ready.complete(new Messenger(binder));}
        public void onServiceDisconnected(ComponentName name){fail("GPU process disconnected");}
        public void onBindingDied(ComponentName name){fail("GPU binding died");}
        public void onNullBinding(ComponentName name){fail("GPU binding unavailable");}
    };
    GpuProcess(Context context){
        this.context=context.getApplicationContext();callbacks.start();
        replies=new Messenger(new Handler(callbacks.getLooper(),message->{
            CompletableFuture<int[]> future=pending.remove(message.arg1);if(future==null)return true;
            Bundle data=message.getData();String error=data.getString("error");
            if(error!=null)future.completeExceptionally(new IllegalStateException(error));
            else future.complete(data.getIntArray("rows"));return true;
        }));
        main.post(()->{if(closed)return;try{bound=this.context.bindService(new Intent(this.context,GpuService.class),connection,Context.BIND_AUTO_CREATE);if(!bound)fail("GPU bind failed");}catch(RuntimeException e){fail("GPU bind failed");}});
    }
    int[] rows(int[] input){
        if(Looper.myLooper()==Looper.getMainLooper())throw new IllegalStateException("GPU call on UI thread");
        if(closed)throw new IllegalStateException("GPU session closed");
        int id=sequence.incrementAndGet();CompletableFuture<int[]> result=new CompletableFuture<>();pending.put(id,result);
        try {
            Messenger remote=ready.get(3,TimeUnit.SECONDS);
            Message request=Message.obtain(null,1,id,0);request.replyTo=replies;Bundle data=new Bundle();data.putIntArray("input",input);request.setData(data);remote.send(request);
            int[] rows=result.get(6,TimeUnit.SECONDS);if(rows==null)throw new IllegalStateException("Empty GPU response");return rows;
        }catch(InterruptedException e){Thread.currentThread().interrupt();close();throw new CancellationException();}
         catch(ExecutionException|TimeoutException|RemoteException e){close();throw new IllegalStateException("GPU process unavailable",e);}
        finally{pending.remove(id);}
    }
    private void fail(String reason){IllegalStateException error=new IllegalStateException(reason);ready.completeExceptionally(error);for(CompletableFuture<int[]> item:pending.values())item.completeExceptionally(error);}
    public void close(){closed=true;fail("GPU session closed");main.post(()->{if(bound){context.unbindService(connection);bound=false;}callbacks.quitSafely();});}
}
