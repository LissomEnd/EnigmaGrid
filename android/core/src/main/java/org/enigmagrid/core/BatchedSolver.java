package org.enigmagrid.core;

import java.util.*;
import java.util.concurrent.CancellationException;
import java.util.function.BooleanSupplier;

/** Search-local GPU solver batches; the canonical receipt reduction stays in BoundedCrib. */
public final class BatchedSolver implements BoundedCrib.RowProvider {
    public interface Dispatch { int[] run(int[] packed); }
    private final BoundedCrib.RowProvider rows;
    private final Dispatch dispatch;
    private final BooleanSupplier cancel;
    private List<BoundedCrib.Key> keys=Collections.emptyList();
    private final Map<BoundedCrib.Key,BoardSolver.Result> cache=new IdentityHashMap<>();
    private int offset,length;
    private final boolean qualifiedScopeOnly;
    private long rowNanos,packNanos,dispatchNanos,unpackNanos,dispatchCount,inputBytes,outputBytes;
    private Dispatch keyDispatch;
    private boolean hybrid;private int gpuCores=64,batchSize=64;
    public BatchedSolver withBatchSize(int size){
        if(size!=64&&size!=128)throw new IllegalArgumentException("Solver dispatch size must be 64 or 128");
        batchSize=size;return this;
    }
    public BatchedSolver withCpuShare(){return withCpuShare(64);}
    public BatchedSolver withCpuShare(int gpuCores){
        if(gpuCores<1||gpuCores>64)throw new IllegalArgumentException("GPU partition must be 1..64 cores");
        this.gpuCores=gpuCores;hybrid=true;return this;
    }
    /** A dedicated GPU lane must not occupy the shared CPU solver pool while waiting. */
    public BatchedSolver withGpuOnly(){gpuCores=Integer.MAX_VALUE;hybrid=true;return this;}
    public boolean hybrid(){return hybrid;}
    public boolean accelerates(BoundedCrib.Key key){int index=keys.indexOf(key);return index>=0&&(!hybrid||index<Math.min(gpuCores,keys.size()));}
    public BatchedSolver withKeyDispatch(Dispatch combined){this.keyDispatch=Objects.requireNonNull(combined);return this;}
    /** Cumulative, non-overlapping wall stages; dispatch includes IPC and GPU wait. */
    public Map<String,Object> timings(){
        return Canonical.object("rows_ns",rowNanos,"pack_ns",packNanos,"dispatch_ns",dispatchNanos,
            "unpack_ns",unpackNanos,"dispatches",dispatchCount,"input_bytes",inputBytes,"output_bytes",outputBytes);
    }
    public BatchedSolver(BoundedCrib.RowProvider rows,Dispatch dispatch,BooleanSupplier cancel){
        this(rows,dispatch,cancel,false);
    }
    public BatchedSolver(BoundedCrib.RowProvider rows,Dispatch dispatch,BooleanSupplier cancel,boolean qualifiedScopeOnly){
        this.rows=rows;this.dispatch=dispatch;this.cancel=cancel;
        this.qualifiedScopeOnly=qualifiedScopeOnly;
    }
    public BoundedCrib.RowProvider newSearch(){
        BatchedSolver child=new BatchedSolver(rows.newSearch(),dispatch,cancel,qualifiedScopeOnly);
        child.withBatchSize(batchSize);
        if(keyDispatch!=null)child.withKeyDispatch(keyDispatch);
        if(hybrid){if(gpuCores==Integer.MAX_VALUE)child.withGpuOnly();else child.withCpuShare(gpuCores);}
        return child;
    }
    private void check(){if(Thread.currentThread().isInterrupted()||cancel.getAsBoolean())throw new CancellationException();}
    public void prepare(List<BoundedCrib.Key> keys,int offset,int length){
        check();this.keys=new ArrayList<>(keys);this.offset=offset;this.length=length;cache.clear();
        rows.prepare(keys,offset,length);
    }
    public int[][] rows(BoundedCrib.Key key,int offset,int length){return rows.rows(key,offset,length);}
    public boolean cached(BoundedCrib.Key key,int offset,int length){return this.offset==offset&&this.length==length&&cache.containsKey(key);}
    public BoardSolver.Result solve(BoundedCrib.Key key,int offset,int length,int[][] edges,int pairs,int nodes,int boards){
        if(qualifiedScopeOnly&&(keys.size()!=128||(length<22||length>24)||pairs!=10||nodes!=5000||boards!=64))return null;
        check();int index=keys.indexOf(key);
        if(index<0||offset!=this.offset||length!=this.length)throw new IllegalStateException("Solver scope mismatch");
        BoardSolver.Result ready=cache.get(key);if(ready!=null)return ready;
        // Never include CPU-owned cores in a GPU batch, including partial batches.
        if(hybrid&&!accelerates(key))return null;
        int first=index/batchSize*batchSize,last=Math.min(keys.size(),Math.min(hybrid?gpuCores:Integer.MAX_VALUE,first+batchSize));
        if(keyDispatch!=null){
            long start=System.nanoTime();
            int[] request=SolverKeyBatch.pack(keys.subList(first,last),offset,length,edges,pairs,nodes,boards);
            packNanos+=System.nanoTime()-start;inputBytes+=request.length*4L;start=System.nanoTime();
            int[] response=keyDispatch.run(request);
            dispatchNanos+=System.nanoTime()-start;dispatchCount++;outputBytes+=response==null?0:response.length*4L;start=System.nanoTime();
            List<BoardSolver.Result> results=SolverKeyBatch.unpack(response,request);
            unpackNanos+=System.nanoTime()-start;check();
            for(int i=first;i<last;i++)cache.put(keys.get(i),results.get(i-first));
            return cache.get(key);
        }
        int[][][] batch=new int[last-first][][];
        long start=System.nanoTime();
        for(int i=first;i<last;i++){check();batch[i-first]=rows.rows(keys.get(i),offset,length);}
        rowNanos+=System.nanoTime()-start;start=System.nanoTime();
        int[] input=SolverBatch.pack(batch,edges,pairs,nodes,boards);
        packNanos+=System.nanoTime()-start;inputBytes+=input.length*4L;start=System.nanoTime();
        int[] output=dispatch.run(input);
        dispatchNanos+=System.nanoTime()-start;dispatchCount++;outputBytes+=output==null?0:output.length*4L;start=System.nanoTime();
        List<BoardSolver.Result> results=SolverBatch.unpack(output,input);
        unpackNanos+=System.nanoTime()-start;check();
        for(int i=first;i<last;i++)cache.put(keys.get(i),results.get(i-first));
        return cache.get(key);
    }
}
