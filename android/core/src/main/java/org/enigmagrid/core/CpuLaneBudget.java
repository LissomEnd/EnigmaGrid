package org.enigmagrid.core;

/** Bounded per-job CPU stripes within a hardware-sized shared executor. */
public final class CpuLaneBudget {
    private CpuLaneBudget(){}
    public static int forLane(int processors,int parallelJobs,boolean independentGpuLane,boolean gpuLane){
        if(processors<1||parallelJobs!=1&&parallelJobs!=2&&parallelJobs!=4)
            throw new IllegalArgumentException("Invalid lane capacity");
        if(independentGpuLane&&parallelJobs<2)throw new IllegalArgumentException("GPU lane needs a CPU lane");
        if(gpuLane&&!independentGpuLane)throw new IllegalArgumentException("GPU lane not enabled");
        int total=Math.min(32,processors);
        if(independentGpuLane&&!gpuLane){
            int feeder=total>1?1:0;
            return Math.max(1,(total-feeder)/(parallelJobs-1));
        }
        // GPU lane CPU fallback is conservative. When GPU replies are cached,
        // GpuWorkCohort uses one reducer worker regardless of this budget.
        return Math.max(1,total/parallelJobs);
    }
}
