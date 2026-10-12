package org.enigmagrid.core;

import java.util.ArrayDeque;

/** Completed work per wall second; no estimates of unfinished work. */
public final class CompletedWorkRate {
    private final ArrayDeque<long[]> samples=new ArrayDeque<>();
    private final long windowNanos;
    public CompletedWorkRate(int seconds){
        if(seconds<1)throw new IllegalArgumentException("Positive window required");
        windowNanos=seconds*1_000_000_000L;
    }
    public synchronized void reset(){samples.clear();}
    public synchronized double[] sample(long now,long units,long jobs){
        long[] last=samples.peekLast();
        if(last!=null&&(now<=last[0]||units<last[1]||jobs<last[2]))samples.clear();
        samples.addLast(new long[]{now,units,jobs});
        // Retain a measured boundary immediately before the requested window.
        while(samples.size()>2){
            long[] first=samples.removeFirst();
            if(samples.peekFirst()[0]>now-windowNanos){samples.addFirst(first);break;}
        }
        long[] first=samples.peekFirst();
        double elapsed=(now-first[0])/1e9;
        return elapsed<=0?new double[]{0,0}:new double[]{(units-first[1])/elapsed,(jobs-first[2])/elapsed};
    }
}
