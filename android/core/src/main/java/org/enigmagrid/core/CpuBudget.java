package org.enigmagrid.core;

import java.util.ArrayDeque;
import java.util.function.LongSupplier;

/** One measured CPU budget for the entire application, shared by every worker. */
public final class CpuBudget {
    private final LongSupplier cpuNanos;
    private final int cores;
    private final ArrayDeque<long[]> history=new ArrayDeque<>();
    private long sampledAt=-1,previousCpu,balanceAt;
    private double credit;
    private int percent=100;
    public CpuBudget(LongSupplier cpuNanos,int cores){
        if(cores<1)throw new IllegalArgumentException("CPU count");
        this.cpuNanos=cpuNanos;this.cores=cores;
    }
    public synchronized long delayMillis(long now,int requested){
        if(requested<1||requested>100)throw new IllegalArgumentException("CPU quota");
        if(sampledAt<0){sampledAt=balanceAt=now;previousCpu=cpuNanos.getAsLong();history.add(new long[]{now,previousCpu});percent=requested;return 0;}
        double capacity=cores*requested/100.0;
        credit+=Math.max(0,now-balanceAt)*capacity;balanceAt=now;
        if(requested!=percent){credit=0;percent=requested;previousCpu=cpuNanos.getAsLong();sampledAt=now;}
        if(now-sampledAt>=1_000_000_000L){
            long cpu=cpuNanos.getAsLong();credit=Math.min(cores*50_000_000.0,credit-Math.max(0,cpu-previousCpu));previousCpu=cpu;sampledAt=now;
            history.add(new long[]{now,cpu});
            while(history.size()>2&&now-history.peekFirst()[0]>10_000_000_000L)history.removeFirst();
        }
        if(requested==100){credit=0;return 0;}
        return credit<0?Math.max(1,Math.min(100,(long)Math.ceil(-credit/capacity/1_000_000.0))):0;
    }
    public synchronized Double measuredPercent(){
        if(history.size()<2)return null;
        long[] first=history.peekFirst(),last=history.peekLast();long elapsed=last[0]-first[0];
        return elapsed>0?Math.max(0,Math.min(100,100.0*(last[1]-first[1])/elapsed/cores)):null;
    }
}
