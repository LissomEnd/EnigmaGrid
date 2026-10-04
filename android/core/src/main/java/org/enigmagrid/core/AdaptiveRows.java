package org.enigmagrid.core;

import java.util.concurrent.CancellationException;
import java.util.function.BooleanSupplier;
import java.util.function.IntSupplier;

/** Single-worker optional accelerator, with independent submission duty and CPU fallback. */
public final class AdaptiveRows implements BoundedCrib.RowProvider {
    private final BoundedCrib.RowProvider accelerator;
    private final IntSupplier percent;
    private final BooleanSupplier cancel;
    private final WorkControl.Timing timing;
    private boolean failed;
    private long nextDispatch;
    public AdaptiveRows(BoundedCrib.RowProvider accelerator,IntSupplier percent,BooleanSupplier cancel,WorkControl.Timing timing){
        this.accelerator=accelerator;this.percent=percent;this.cancel=cancel;this.timing=timing;
    }
    public boolean failed(){return failed;}
    private void check(){if(Thread.currentThread().isInterrupted()||cancel.getAsBoolean())throw new CancellationException();}
    public int[][] rows(BoundedCrib.Key key,int offset,int length){
        check();int duty=percent.getAsInt();
        if(duty<0||duty>100)throw new IllegalArgumentException("GPU duty must be 0..100");
        if(failed||duty==0)return BoundedCrib.cpuRows(key,offset,length);
        while(timing.nanos()<nextDispatch){
            check();if(percent.getAsInt()==0)return BoundedCrib.cpuRows(key,offset,length);
            try{timing.sleep(Math.max(1,Math.min(50,(nextDispatch-timing.nanos()+999999)/1000000)));}
            catch(InterruptedException e){Thread.currentThread().interrupt();throw new CancellationException();}
        }
        check();long start=timing.nanos();
        try {
            int[][] rows=accelerator.rows(key,offset,length);
            if(rows==null||rows.length!=length)throw new IllegalStateException("GPU row count");
            for(int[] row:rows){
                if(row==null||row.length!=26)throw new IllegalStateException("GPU contact count");
                for(int x=0;x<26;x++)if(row[x]<0||row[x]>=26||row[x]==x||row[row[x]]!=x)throw new IllegalStateException("Invalid GPU permutation");
            }
            long end=timing.nanos();nextDispatch=end+Math.max(0,end-start)*(100-duty)/duty;
            check();return rows;
        } catch(CancellationException e){throw e;}
          catch(RuntimeException|LinkageError e){failed=true;check();return BoundedCrib.cpuRows(key,offset,length);}
    }
}
