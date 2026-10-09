package org.enigmagrid.core;

import java.util.concurrent.CancellationException;
import java.util.function.BooleanSupplier;
import java.util.function.IntSupplier;

/** Search-local cache with a shared serialized GPU budget and failure latch. */
public final class AdaptiveRows implements BoundedCrib.RowProvider {
    private final BoundedCrib.RowProvider accelerator;
    private final IntSupplier percent;
    private final BooleanSupplier cancel;
    private final WorkControl.Timing timing;
    private static final class Shared {
        volatile boolean failed; volatile long dispatches; long finished,duration;
    }
    private final Shared shared;
    public AdaptiveRows(BoundedCrib.RowProvider accelerator,IntSupplier percent,BooleanSupplier cancel,WorkControl.Timing timing){
        this(accelerator,percent,cancel,timing,new Shared());
    }
    private AdaptiveRows(BoundedCrib.RowProvider accelerator,IntSupplier percent,BooleanSupplier cancel,WorkControl.Timing timing,Shared shared){
        this.accelerator=accelerator;this.percent=percent;this.cancel=cancel;this.timing=timing;this.shared=shared;
    }
    public BoundedCrib.RowProvider newSearch(){return new AdaptiveRows(accelerator.newSearch(),percent,cancel,timing,shared);}
    public void prepare(java.util.List<BoundedCrib.Key> keys,int offset,int length){
        check();if(shared.failed)return;
        try{accelerator.prepare(keys,offset,length);}
        catch(CancellationException e){throw e;}
        catch(RuntimeException|LinkageError e){shared.failed=true;check();}
    }
    public boolean failed(){return shared.failed;}
    public long dispatches(){return shared.dispatches;}
    public boolean available(){return !shared.failed&&percent.getAsInt()>0;}
    public boolean hybrid(){return accelerator.hybrid();}
    public boolean accelerates(BoundedCrib.Key key){return !shared.failed&&percent.getAsInt()>0&&accelerator.accelerates(key);}
    private void check(){if(Thread.currentThread().isInterrupted()||cancel.getAsBoolean())throw new CancellationException();}
    private int awaitDuty(boolean cached){
        while(true){
            check();int duty=percent.getAsInt();
            if(duty<0||duty>100)throw new IllegalArgumentException("GPU duty must be 0..100");
            if(cached||duty==0||duty==100)return duty;
            long delay=shared.finished+shared.duration*(100-duty)/duty-timing.nanos();
            if(delay<=0)return duty;
            try{timing.sleep(Math.max(1,Math.min(20,(delay+999999)/1000000)));}
            catch(InterruptedException e){Thread.currentThread().interrupt();throw new CancellationException();}
        }
    }
    /** The cohort shares exactly the same duty budget, cancellation and failure latch. */
    public int[] dispatchCohort(int[] input,BatchedSolver.Dispatch dispatch){
        synchronized(shared){
            check();if(shared.failed||awaitDuty(false)==0)return null;
            long start=timing.nanos();
            try{
                int[] result=dispatch.run(input);if(result==null)throw new IllegalStateException("Missing cohort result");
                long end=timing.nanos();shared.finished=end;shared.duration=Math.max(0,end-start);shared.dispatches++;
                check();return result;
            }catch(CancellationException e){throw e;}
            catch(RuntimeException|LinkageError e){shared.failed=true;check();return null;}
        }
    }
    public BoardSolver.Result solve(BoundedCrib.Key key,int offset,int length,int[][] edges,int pairs,int nodes,int boards){
        synchronized(shared){
        check();int duty=percent.getAsInt();
        if(duty<0||duty>100)throw new IllegalArgumentException("GPU duty must be 0..100");
        if(shared.failed||duty==0||!(accelerator instanceof BatchedSolver))return null;
        boolean cached=((BatchedSolver)accelerator).cached(key,offset,length);
        duty=awaitDuty(cached);if(duty==0)return null;
        long start=timing.nanos();
        try{
            BoardSolver.Result result=accelerator.solve(key,offset,length,edges,pairs,nodes,boards);
            long end=timing.nanos();if(!cached&&result!=null){shared.finished=end;shared.duration=Math.max(0,end-start);shared.dispatches++;}
            check();return result;
        }catch(CancellationException e){throw e;}
        catch(RuntimeException|LinkageError e){shared.failed=true;check();return null;}
    }
    }
    public int[][] rows(BoundedCrib.Key key,int offset,int length){
        synchronized(shared){
        check();int duty=percent.getAsInt();
        if(duty<0||duty>100)throw new IllegalArgumentException("GPU duty must be 0..100");
        if(shared.failed||duty==0)return BoundedCrib.cpuRows(key,offset,length);
        boolean cached=accelerator instanceof BatchedRows&&((BatchedRows)accelerator).cached(key,offset,length);
        duty=awaitDuty(cached);if(duty==0)return BoundedCrib.cpuRows(key,offset,length);
        check();long start=timing.nanos();
        try {
            long before=accelerator instanceof BatchedRows?((BatchedRows)accelerator).dispatches():0;
            int[][] rows=accelerator.rows(key,offset,length);
            if(rows==null||rows.length!=length)throw new IllegalStateException("GPU row count");
            for(int[] row:rows){
                if(row==null||row.length!=26)throw new IllegalStateException("GPU contact count");
                for(int x=0;x<26;x++)if(row[x]<0||row[x]>=26||row[x]==x||row[row[x]]!=x)throw new IllegalStateException("Invalid GPU permutation");
            }
            long end=timing.nanos();if(!cached){shared.finished=end;shared.duration=Math.max(0,end-start);}
            check();shared.dispatches+=accelerator instanceof BatchedRows?((BatchedRows)accelerator).dispatches()-before:1;return rows;
        } catch(CancellationException e){throw e;}
          catch(RuntimeException|LinkageError e){shared.failed=true;check();return BoundedCrib.cpuRows(key,offset,length);}
        }
    }
}
