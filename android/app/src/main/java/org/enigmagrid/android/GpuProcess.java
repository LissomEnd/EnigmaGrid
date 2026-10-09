package org.enigmagrid.android;

import android.content.*;
import android.os.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicBoolean;

/** Bounded IPC waits; native crash or timeout leaves CPU fallback available. */
final class GpuProcess implements AutoCloseable {
    private static long observedCpu,lastCpu;private static int lastPid;
    private static final long diagnosticsStarted=SystemClock.elapsedRealtime();
    private static final long[] successfulWidths=new long[5],successfulElapsedNanos=new long[5],failedWidths=new long[5],failedElapsedNanos=new long[5];
    private static int widthBucket(int cores){return cores==128?0:cores==256?1:cores==384?2:cores==512?3:4;}
    private static synchronized void recordDispatch(int cores,long elapsed,boolean success){
        int bucket=widthBucket(cores);
        (success?successfulWidths:failedWidths)[bucket]++;
        (success?successfulElapsedNanos:failedElapsedNanos)[bucket]+=Math.max(0,elapsed);
    }
    /** Process-lifetime aggregates only: no jobs, account IDs, keys or receipt contents. */
    static synchronized String dispatchDiagnostics(){
        String[] labels={"128","256","384","512","other"};
        StringBuilder value=new StringBuilder("{\"process_id\":").append(android.os.Process.myPid())
            .append(",\"started_elapsed_ms\":").append(diagnosticsStarted)
            .append(",\"sample_elapsed_ms\":").append(SystemClock.elapsedRealtime()).append(",\"widths\":{");
        for(int i=0;i<labels.length;i++){
            if(i>0)value.append(',');value.append('"').append(labels[i]).append("\":{\"success\":").append(successfulWidths[i])
                .append(",\"success_elapsed_ns\":").append(successfulElapsedNanos[i]).append(",\"errors\":").append(failedWidths[i])
                .append(",\"error_elapsed_ns\":").append(failedElapsedNanos[i]).append('}');
        }
        return value.append("},\"cohort\":")
            .append(org.enigmagrid.core.WorkBlockJson.json(org.enigmagrid.core.GpuWorkCohort.diagnostics()))
            .append('}').toString();
    }
    static synchronized long cpuMillis(){return observedCpu;}
    private static synchronized void observeCpu(Bundle data){
        int pid=data.getInt("process_id",0);long value=data.getLong("process_cpu_ms",0);
        if(pid!=0){observedCpu+=pid==lastPid?Math.max(0,value-lastCpu):value;lastPid=pid;lastCpu=value;}
    }
    static String qualificationKey(){return "ipc-v8-bounded-cohort-512:"+BuildConfig.VERSION_CODE+":"+Build.FINGERPRINT;}
    private final Context context;
    private final Handler main=new Handler(Looper.getMainLooper());
    private final HandlerThread callbacks=new HandlerThread("gpu-replies");
    private final CompletableFuture<Messenger> ready=new CompletableFuture<>();
    private final ConcurrentHashMap<Integer,CompletableFuture<int[]>> pending=new ConcurrentHashMap<>();
    private final ConcurrentHashMap<Integer,AtomicBoolean> serviceReplies=new ConcurrentHashMap<>();
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
            Bundle data=message.getData();
            AtomicBoolean reply=serviceReplies.remove(message.arg1);if(reply!=null)reply.set(true);
            CompletableFuture<int[]> future=pending.remove(message.arg1);
            if(future==null){GpuSharedTransport.discard(data,"rows");return true;}
            observeCpu(data);String error=data.getString("error");
            if(error!=null){GpuSharedTransport.discard(data,"rows");future.completeExceptionally(new IllegalStateException(error));}
            else try{future.complete(GpuSharedTransport.read(data,"rows",GpuSharedTransport.MAX_INTS));}
            catch(Exception failure){future.completeExceptionally(failure);}return true;
        }));
        main.post(()->{if(closed)return;try{bound=this.context.bindService(new Intent(this.context,GpuService.class),connection,Context.BIND_AUTO_CREATE);if(!bound)fail("GPU bind failed");}catch(RuntimeException e){fail("GPU bind failed");}});
    }
    int[] rows(int[] input){return dispatch(1,input);}
    int[] solve(int[] input){return dispatch(2,input);}
    int[] solveKeys(int[] input){return dispatch(3,input);}
    private int[] dispatch(int kind,int[] input){
        if(Looper.myLooper()==Looper.getMainLooper())throw new IllegalStateException("GPU call on UI thread");
        if(closed)throw new IllegalStateException("GPU session closed");
        // Binding may take seconds on a cold process. Do not hold the sole RPC
        // permit while waiting for this session's Messenger to become ready.
        Messenger remote;
        try{remote=ready.get(3,TimeUnit.SECONDS);}
        catch(InterruptedException stopped){Thread.currentThread().interrupt();throw new CancellationException();}
        catch(Exception failure){close();throw new IllegalStateException("GPU process unavailable",failure);}
        // GpuService admits only one request across all sessions. Qualification
        // may own a different GpuProcess from production; per-instance locking
        // would let the service reject one of their requests as "GPU busy".
        // Acquire before touching per-request state so a canceled waiter has no
        // pending reply to recover. This wait is interruptible and fair.
        try(GpuRpcGate.Permit ignored=GpuRpcGate.acquire()){
        if(closed)throw new IllegalStateException("GPU session closed");
        int id=sequence.incrementAndGet();CompletableFuture<int[]> result=new CompletableFuture<>();AtomicBoolean replyObserved=new AtomicBoolean();pending.put(id,result);serviceReplies.put(id,replyObserved);
        long dispatchStarted=System.nanoTime(),sentNs=0;boolean succeeded=false;
        try {
            Message request=Message.obtain(null,kind,id,0);request.replyTo=replies;Bundle data=new Bundle();
            SharedMemory shared=GpuSharedTransport.put(data,"input",input);
            try{request.setData(data);remote.send(request);sentNs=System.nanoTime();}finally{GpuSharedTransport.close(shared);}
            int[] rows=result.get(6,TimeUnit.SECONDS);if(rows==null)throw new IllegalStateException("Empty GPU response");succeeded=true;return rows;
        }catch(InterruptedException e){if(sentNs!=0&&!replyObserved.get())ignored.holdUntilServiceDeadline(sentNs);Thread.currentThread().interrupt();close();throw new CancellationException();}
         catch(Exception e){if(sentNs!=0&&!replyObserved.get())ignored.holdUntilServiceDeadline(sentNs);close();throw new IllegalStateException("GPU process unavailable",e);}
        finally{pending.remove(id);serviceReplies.remove(id);if(kind==3&&input!=null&&input.length>0)recordDispatch(input[0],System.nanoTime()-dispatchStarted,succeeded);}
        }catch(InterruptedException stopped){Thread.currentThread().interrupt();throw new CancellationException();}
    }
    private void fail(String reason){IllegalStateException error=new IllegalStateException(reason);ready.completeExceptionally(error);for(CompletableFuture<int[]> item:pending.values())item.completeExceptionally(error);}
    public void close(){closed=true;fail("GPU session closed");main.post(()->{if(bound){context.unbindService(connection);bound=false;}callbacks.quitSafely();});}
}
