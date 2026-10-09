package org.enigmagrid.android;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Context;
import android.os.Bundle;
import android.os.SystemClock;
import java.util.*;
import java.util.function.BooleanSupplier;
import org.enigmagrid.core.*;

public final class RowsSpeedQualification extends Instrumentation {
    public void onCreate(Bundle ignored){super.onCreate(ignored);start();}
    private static Map<String,Object> fixture(int ordinal){
        String cipher="QWERTZUIOPASDFGHJKLYXCVBNM";
        char[] letters="ABCDEFGHIJKLMNOPQRSTUVWX".toCharArray();
        for(int i=0;i<letters.length;i++)if(letters[i]==cipher.charAt(i))
            letters[i]=(char)('A'+(letters[i]-'A'+1)%26);
        List<Long> cores=new ArrayList<>();
        for(int i=0;i<128;i++)cores.add((ordinal*128L+i)*7919L);
        return Canonical.object("engine","bounded_crib_v1","start_unit",ordinal,"end_unit",ordinal+1,
            "config",Canonical.object("requires",Arrays.asList("cpu","bounded_crib_v1"),
                "job",Canonical.object("engine","bounded_crib_v1","ciphertext",cipher,
                    "crib",new String(letters),"offset",0,"core_indices",cores,"model","clean",
                    "pairs",10,"budgets",Canonical.object("node_limit",5000,
                        "board_limit",64,"completion_limit",256,"candidate_limit",32))));
    }
    public void onStart(){
        Bundle result=new Bundle();int code=Activity.RESULT_CANCELED;
        try{
            Context app=getTargetContext();
            if(!"org.enigmagrid.android.lab".equals(app.getPackageName()))
                throw new IllegalStateException("Lab only");
            int cpus=Math.max(1,Math.min(8,Runtime.getRuntime().availableProcessors()/2));
            double[] cpu=new double[4],gpuNanos=new double[4],gpuWideNanos=new double[4];
            BooleanSupplier stop=()->Thread.currentThread().isInterrupted();
            try(GpuProcess gpu=new GpuProcess(app)){
                BatchedRows backend=new BatchedRows(gpu::rows,stop,64);
                BatchedRows wide=new BatchedRows(gpu::rows,stop,128);
                for(int i=0;i<4;i++){
                    Map<String,Object> job=fixture(i);
                    long begin=System.nanoTime();
                    String reference=Canonical.json(WorkEnvelope.run(job,stop,null,cpus));
                    cpu[i]=(System.nanoTime()-begin)/1e6;
                    begin=System.nanoTime();
                    String accelerated=Canonical.json(WorkEnvelope.run(job,stop,backend,cpus));
                    gpuNanos[i]=(System.nanoTime()-begin)/1e6;
                    if(!reference.equals(accelerated))throw new AssertionError("64-key receipt mismatch at "+i);
                    begin=System.nanoTime();
                    String wider=Canonical.json(WorkEnvelope.run(job,stop,wide,cpus));
                    gpuWideNanos[i]=(System.nanoTime()-begin)/1e6;
                    if(!reference.equals(wider))throw new AssertionError("128-key receipt mismatch at "+i);
                }
            }
            double cpuMean=(cpu[1]+cpu[2]+cpu[3])/3.0;
            double gpuMean=(gpuNanos[1]+gpuNanos[2]+gpuNanos[3])/3.0;
            double gpuWideMean=(gpuWideNanos[1]+gpuWideNanos[2]+gpuWideNanos[3])/3.0;
            code=Activity.RESULT_OK;
            result.putString("result","PASS full receipts equal; CPU mean "+cpuMean+
                "ms; Vulkan rows64 mean "+gpuMean+"ms; Vulkan rows128 mean "+gpuWideMean+
                "ms; ratios="+(gpuMean/cpuMean)+","+(gpuWideMean/cpuMean)+
                "; per-job cpu="+Arrays.toString(cpu)+" gpu64="+Arrays.toString(gpuNanos)+
                " gpu128="+Arrays.toString(gpuWideNanos));
        }catch(Throwable e){result.putString("result","FAIL "+e.getClass().getSimpleName()+" "+e.getMessage());}
        finish(code,result);
    }
}
