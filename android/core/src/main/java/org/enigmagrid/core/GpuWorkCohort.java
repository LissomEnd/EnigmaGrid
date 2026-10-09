package org.enigmagrid.core;

import java.util.*;
import java.util.concurrent.CancellationException;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicLongArray;
import java.util.function.BooleanSupplier;
import static org.enigmagrid.core.Canonical.*;

/** Coalesce real bounded jobs for transport, never enlarge an individual search scope. */
public final class GpuWorkCohort {
    public static final int MAX_JOBS=4,MAX_CORES=512;
    private static final AtomicLong runs=new AtomicLong(),jobs=new AtomicLong(),scopeNanos=new AtomicLong(),
        packNanos=new AtomicLong(),ipcNanos=new AtomicLong(),unpackNanos=new AtomicLong(),queueNanos=new AtomicLong(),
        reductionNanos=new AtomicLong(),callbackNanos=new AtomicLong(),fallbackNanos=new AtomicLong(),
        runNanos=new AtomicLong();
    private static final AtomicLongArray groupSizes=new AtomicLongArray(MAX_JOBS);
    // A process-wide single dispatch worker prevents a second simultaneous
    // GpuService RPC. The single queue slot bounds the one-request lookahead.
    private static final ThreadPoolExecutor DISPATCH_EXECUTOR=new ThreadPoolExecutor(
        1,1,0L,TimeUnit.MILLISECONDS,new ArrayBlockingQueue<>(1),task->{
            Thread thread=new Thread(task,"cohort-gpu-dispatch");thread.setDaemon(true);return thread;
        },new ThreadPoolExecutor.AbortPolicy());
    private GpuWorkCohort(){}
    /** Process-lifetime stage totals; no job contents, identities, or receipt values. */
    public static Map<String,Object> diagnostics(){
        return object("runs",runs.get(),"jobs",jobs.get(),"scope_ns",scopeNanos.get(),
            "pack_ns",packNanos.get(),"gpu_ipc_ns",ipcNanos.get(),"unpack_ns",unpackNanos.get(),"gpu_dispatch_queue_ns",queueNanos.get(),
            "receipt_reduction_ns",reductionNanos.get(),"callback_ns",callbackNanos.get(),
            "cpu_fallback_ns",fallbackNanos.get(),"run_ns",runNanos.get(),
            "gpu_groups_1",groupSizes.get(0),"gpu_groups_2",groupSizes.get(1),
            "gpu_groups_3",groupSizes.get(2),"gpu_groups_4",groupSizes.get(3));
    }
    public interface Receipt {void accept(int index,Map<String,Object> receipt,double seconds)throws Exception;}
    private static void check(BooleanSupplier cancel){if(Thread.currentThread().isInterrupted()||cancel.getAsBoolean())throw new CancellationException();}
    private static final class Scope {
        final Map<String,Object> envelope,job;final List<BoundedCrib.Key> keys;
        final int offset,length,pairs,nodes,boards;final int[][] edges;final boolean conflict;
        @SuppressWarnings("unchecked") Scope(Map<String,Object> envelope){
            this.envelope=envelope;job=WorkEnvelope.validate(envelope);
            List<Number> indices=(List<Number>)job.get("core_indices");long[] values=new long[indices.size()];
            for(int i=0;i<values.length;i++)values[i]=indices.get(i).longValue();keys=BoundedCrib.canonicalKeys(values);
            String cipher=(String)job.get("ciphertext"),crib=(String)job.get("crib");
            offset=((Number)job.get("offset")).intValue();length=crib.length();pairs=((Number)job.get("pairs")).intValue();
            Map<String,Object> budget=(Map<String,Object>)job.get("budgets");nodes=((Number)budget.get("node_limit")).intValue();boards=((Number)budget.get("board_limit")).intValue();
            edges=new int[length][3];boolean same=false;
            for(int i=0;i<length;i++){edges[i]=new int[]{i,crib.charAt(i)-65,cipher.charAt(offset+i)-65};same|=edges[i][1]==edges[i][2];}conflict=same;
        }
        String group(){return json(object("offset",offset,"length",length,"pairs",pairs,"nodes",nodes,"boards",boards,"edges",Arrays.deepToString(edges)));}
    }
    private static String key(BoundedCrib.Key key){return key.reflector+"/"+key.greek+"/"+String.join(",",key.moving)+"/"+key.rings+"/"+key.positions;}
    private static final class Cached implements BoundedCrib.RowProvider {
        final Scope scope;final Map<String,BoardSolver.Result> results=new HashMap<>();
        Cached(Scope scope,List<BoardSolver.Result> values){
            this.scope=scope;if(values.size()!=scope.keys.size())throw new IllegalStateException("Cohort result count");
            for(int i=0;i<values.size();i++)results.put(key(scope.keys.get(i)),values.get(i));
        }
        public void prepare(List<BoundedCrib.Key> keys,int offset,int length){
            if(offset!=scope.offset||length!=scope.length||keys.size()!=scope.keys.size())throw new IllegalStateException("Cohort scope mismatch");
            for(int i=0;i<keys.size();i++)if(!key(keys.get(i)).equals(key(scope.keys.get(i))))throw new IllegalStateException("Cohort key order mismatch");
        }
        public int[][] rows(BoundedCrib.Key key,int offset,int length){throw new IllegalStateException("Missing cohort result");}
        public BoardSolver.Result solve(BoundedCrib.Key core,int offset,int length,int[][] edges,int pairs,int nodes,int boards){
            if(offset!=scope.offset||length!=scope.length||pairs!=scope.pairs||nodes!=scope.nodes||boards!=scope.boards||!Arrays.deepEquals(edges,scope.edges))throw new IllegalStateException("Cohort budget mismatch");
            BoardSolver.Result value=results.get(key(core));if(value==null)throw new IllegalStateException("Foreign cohort key");return value;
        }
    }
    private static final class Group {
        final int first,end;final Scope head;final List<BoundedCrib.Key> keys;
        Group(int first,int end,Scope head,List<BoundedCrib.Key> keys){
            this.first=first;this.end=end;this.head=head;this.keys=keys;
        }
    }
    private static List<Group> groups(List<Scope> scopes){
        List<Group> groups=new ArrayList<>();
        for(int first=0;first<scopes.size();){
            Scope head=scopes.get(first);int end=first+1;
            List<BoundedCrib.Key> keys=new ArrayList<>(head.keys);
            if(!head.conflict){
                String signature=head.group();
                while(end<scopes.size()&&!scopes.get(end).conflict&&signature.equals(scopes.get(end).group())){
                    keys.addAll(scopes.get(end).keys);end++;
                }
                if(keys.size()>MAX_CORES)throw new IllegalStateException("Cohort core bound");
            }
            groups.add(new Group(first,end,head,keys));first=end;
        }
        return groups;
    }
    private static final class DispatchResult {
        final int[] packed,response;final long packNs,ipcNs,elapsedNs;
        DispatchResult(int[] packed,int[] response,long packNs,long ipcNs,long elapsedNs){
            this.packed=packed;this.response=response;this.packNs=packNs;this.ipcNs=ipcNs;this.elapsedNs=elapsedNs;
        }
    }
    private static FutureTask<DispatchResult> submit(Group group,BatchedSolver.Dispatch dispatch,BooleanSupplier cancel,boolean optionalAhead){
        check(cancel);
        final long enqueuedNs=System.nanoTime();
        FutureTask<DispatchResult> task=new FutureTask<>(()->{
            check(cancel);long started=System.nanoTime();queueNanos.addAndGet(Math.max(0,started-enqueuedNs));
            int[] packed=SolverKeyBatch.pack(group.keys,group.head.offset,group.head.length,
                group.head.edges,group.head.pairs,group.head.nodes,group.head.boards);
            long packedNs=System.nanoTime()-started;packNanos.addAndGet(packedNs);
            check(cancel);started=System.nanoTime();
            int[] response=dispatch.run(packed);
            long ipcNs=System.nanoTime()-started;ipcNanos.addAndGet(ipcNs);check(cancel);
            return new DispatchResult(packed,response,packedNs,ipcNs,System.nanoTime()-enqueuedNs);
        });
        for(;;){
            check(cancel);
            try{DISPATCH_EXECUTOR.execute(task);return task;}
            catch(RejectedExecutionException full){
                if(DISPATCH_EXECUTOR.isShutdown())throw full;
                if(optionalAhead)return null; // Reduce/persist current receipt first.
                // Qualification and production can both issue cohorts. One
                // running RPC plus one queued request is the strict bound;
                // wait with cancellation rather than fail a production batch.
                try{Thread.sleep(20);}catch(InterruptedException stopped){
                    Thread.currentThread().interrupt();throw new CancellationException();
                }
            }
        }
    }
    private static DispatchResult await(Future<DispatchResult> future,BooleanSupplier cancel)throws Exception {
        for(;;){
            check(cancel);
            try{return future.get(100,TimeUnit.MILLISECONDS);}
            catch(TimeoutException expected){}
            catch(InterruptedException interrupted){Thread.currentThread().interrupt();throw new CancellationException();}
            catch(ExecutionException failed){
                Throwable cause=failed.getCause();
                if(cause instanceof Exception)throw (Exception)cause;
                if(cause instanceof Error)throw (Error)cause;
                throw new IllegalStateException(cause);
            }
        }
    }
    /** Dispatch immediately with the available compatible jobs; callback keeps original order. */
    public static void run(List<Map<String,Object>> envelopes,BatchedSolver.Dispatch dispatch,BooleanSupplier cancel,int workers,Receipt receipt)throws Exception {
        Objects.requireNonNull(dispatch);Objects.requireNonNull(cancel);Objects.requireNonNull(receipt);
        if(envelopes==null||envelopes.isEmpty()||envelopes.size()>MAX_JOBS)throw new IllegalArgumentException("Cohort must contain 1..4 jobs");
        long runStarted=System.nanoTime();runs.incrementAndGet();
        try {
        long scopeStarted=System.nanoTime();
        List<Scope> scopes=new ArrayList<>();for(Map<String,Object> envelope:envelopes){check(cancel);scopes.add(new Scope(envelope));}
        scopeNanos.addAndGet(System.nanoTime()-scopeStarted);
        // One future request overlaps the current receipt reduction. Claims,
        // callbacks and durable receipt delivery remain in their original order.
        List<Group> planned=groups(scopes);FutureTask<DispatchResult> ahead=null,inFlight=null;
        try {for(int groupIndex=0;groupIndex<planned.size();groupIndex++){
            check(cancel);Group group=planned.get(groupIndex);Scope head=group.head;
            if(head.conflict){
                long began=System.nanoTime();Map<String,Object> result=WorkEnvelope.run(head.envelope,cancel,null,workers);
                long reduced=System.nanoTime()-began;fallbackNanos.addAndGet(reduced);
                long callbackStarted=System.nanoTime();receipt.accept(group.first,result,Math.max(.000001,reduced/1e9));
                callbackNanos.addAndGet(System.nanoTime()-callbackStarted);jobs.incrementAndGet();continue;
            }
            inFlight=ahead==null?submit(group,dispatch,cancel,false):ahead;ahead=null;
            DispatchResult batch=await(inFlight,cancel);inFlight=null;
            long unpackStarted=System.nanoTime();
            List<BoardSolver.Result> solved=batch.response==null?null:SolverKeyBatch.unpack(batch.response,batch.packed);
            long unpackNs=System.nanoTime()-unpackStarted;unpackNanos.addAndGet(unpackNs);
            // Only the next compatible GPU group may be in flight; a conflict
            // remains synchronous CPU fallback and cannot reorder callbacks.
            if(groupIndex+1<planned.size()&&!planned.get(groupIndex+1).head.conflict)
                ahead=submit(planned.get(groupIndex+1),dispatch,cancel,true);
            // Per-job elapsed includes queue/admission wait. This may overlap
            // the previous receipt's reduction and is not a partition of wall
            // time; excluding it would overstate a contended GPU lane's rate.
            int at=0;double dispatchShare=(batch.elapsedNs+unpackNs)/1e9/(group.end-group.first);
            if(solved!=null)groupSizes.incrementAndGet(group.end-group.first-1);
            for(int i=group.first;i<group.end;i++){
                check(cancel);Scope scope=scopes.get(i);int count=scope.keys.size();
                BoundedCrib.RowProvider provider=solved==null?null:new Cached(scope,solved.subList(at,at+count));at+=count;
                // GPU-solved cores are immutable cached lookups. Running 128
                // lookups through the shared CPU solver pool queues behind a
                // concurrent CPU job and idles this GPU lane needlessly.
                // Keep the configured workers for a real CPU fallback.
                long began=System.nanoTime();Map<String,Object> result=WorkEnvelope.run(scope.envelope,cancel,provider,provider==null?workers:1);
                long reduced=System.nanoTime()-began;reductionNanos.addAndGet(reduced);
                long callbackStarted=System.nanoTime();
                receipt.accept(i,result,Math.max(.000001,dispatchShare+reduced/1e9));
                callbackNanos.addAndGet(System.nanoTime()-callbackStarted);jobs.incrementAndGet();
            }
        }}finally{
            if(inFlight!=null){inFlight.cancel(true);DISPATCH_EXECUTOR.remove(inFlight);}
            if(ahead!=null){ahead.cancel(true);DISPATCH_EXECUTOR.remove(ahead);}
        }
        }finally{runNanos.addAndGet(System.nanoTime()-runStarted);}
    }
}
