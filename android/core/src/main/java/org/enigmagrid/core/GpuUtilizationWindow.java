package org.enigmagrid.core;
import java.util.ArrayDeque;
/** Time-weighted hardware samples; zero-duration reads do not mean idle. */
public final class GpuUtilizationWindow {
    private final ArrayDeque<double[]> samples=new ArrayDeque<>();
    public synchronized float add(long nowMs,double busy,double total){
        while(!samples.isEmpty()&&nowMs-samples.peekFirst()[0]>=10000)samples.removeFirst();
        if(Double.isFinite(busy)&&Double.isFinite(total)&&total>0&&busy>=0&&busy<=total)
            samples.addLast(new double[]{nowMs,busy,total});
        double sumBusy=0,sumTotal=0;
        for(double[] sample:samples){sumBusy+=sample[1];sumTotal+=sample[2];}
        return sumTotal>0?(float)(100*sumBusy/sumTotal):Float.NaN;
    }
}
