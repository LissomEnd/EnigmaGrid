package org.enigmagrid.core;

import java.util.function.BooleanSupplier;
import java.util.function.Supplier;

/** Cooperative per-thread duty gate. Pauses preserve the current search stack. */
public final class WorkControl implements BooleanSupplier {
    public interface Timing {long nanos();void sleep(long millis) throws InterruptedException;}
    public static final class SystemTiming implements Timing {
        public long nanos(){return System.nanoTime();}
        public void sleep(long millis)throws InterruptedException{Thread.sleep(millis);}
    }
    private final Timing timing;
    private final Supplier<String> restriction;
    private volatile boolean stopped,paused;
    private volatile int percent=25;
    private volatile String status="ready";
    private static final class Slice {long sliceStart=-1,restUntil;}
    private final ThreadLocal<Slice> slices=ThreadLocal.withInitial(Slice::new);
    public WorkControl(Timing timing,Supplier<String> restriction){this.timing=timing;this.restriction=restriction;}
    public void setPercent(int percent){if(percent<1||percent>100)throw new IllegalArgumentException("CPU duty must be 1..100");this.percent=percent;}
    public void pause(){paused=true;}
    public void resume(){paused=false;}
    public void stop(){stopped=true;}
    public String status(){return status;}
    @Override public boolean getAsBoolean() {
        Slice slice=slices.get();
        while(true) {
            if(stopped||Thread.currentThread().isInterrupted()){status="stopped";return true;}
            String reason=restriction.get();
            if(paused||reason!=null){status=paused?"paused":reason;slice.sliceStart=-1;slice.restUntil=0;if(!sleep(100))return true;continue;}
            long now=timing.nanos();
            if(slice.restUntil>now){status="CPU duty rest";if(!sleep(Math.max(1,Math.min(100,(slice.restUntil-now+999999)/1000000))))return true;continue;}
            if(slice.sliceStart<0){slice.sliceStart=now;status="computing";return false;}
            long elapsed=now-slice.sliceStart;
            if(elapsed>=20_000_000L) {
                int duty=percent;
                long rest=elapsed*(100-duty)/duty;
                slice.sliceStart=-1;
                if(rest>0){slice.restUntil=now+rest;continue;}
            }
            status="computing";return false;
        }
    }
    private boolean sleep(long millis){try{timing.sleep(millis);return true;}catch(InterruptedException e){Thread.currentThread().interrupt();status="stopped";return false;}}
}
