package org.enigmagrid.android;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Context;
import android.os.Bundle;
import android.os.SystemClock;

/** Isolated fixture-only GPU solver benchmark, no production account or credits. */
public final class SolverPilotQualification extends Instrumentation {
    public void onCreate(Bundle arguments){super.onCreate(arguments);start();}
    @Override public void onStart(){
        Bundle result=new Bundle();
        long began=SystemClock.elapsedRealtime();
        try{
            Context app=getTargetContext();
            if(!"org.enigmagrid.android.lab".equals(app.getPackageName()))
                throw new IllegalStateException("Lab package required");
            ResourceGuard guard=new ResourceGuard(app,app.getSharedPreferences("worker-settings",0));
            guard.setChargingOnly(false);
            try(GpuProcess gpu=new GpuProcess(app)){
                AutomaticSolverQualification.Report report=AutomaticSolverQualification.run(gpu,guard);
                result.putString("result","PASS: measured CPU+GPU solver; solverFaster="+report.solverFaster
                    +", mixedFaster="+report.mixedFaster+", reason="+report.reason
                    +", elapsed_ms="+(SystemClock.elapsedRealtime()-began));
            }
            finish(Activity.RESULT_OK,result);
        }catch(Throwable problem){
            StringBuilder chain=new StringBuilder();
            for(Throwable cause=problem;cause!=null&&chain.length()<600;cause=cause.getCause()){
                if(chain.length()!=0)chain.append(" -> ");
                chain.append(cause.getClass().getSimpleName());
                if(cause.getMessage()!=null)
                    chain.append("(").append(cause.getMessage().replaceAll("[^A-Za-z0-9 _:.\u002d]","?"),0,
                        Math.min(110,cause.getMessage().length())).append(")");
            }
            result.putString("result","FAIL: "+chain+" elapsed_ms="+(SystemClock.elapsedRealtime()-began));
            finish(Activity.RESULT_CANCELED,result);
        }
    }
}
