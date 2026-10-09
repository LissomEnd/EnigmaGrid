package org.enigmagrid.android;

import org.enigmagrid.core.QualificationProtection;

public final class AutomaticSolverQualificationChecks {
    private static void check(boolean ok){if(!ok)throw new AssertionError();}
    public static void main(String[] args)throws Exception {
        long[] cpuPair={20_000_000,21_000_000},mixedPair={12_000_000,13_000_000};
        long[] cpuJob={10_000_000,11_000_000},gpuJob={12_000_000,13_000_000};
        AutomaticSolverQualification.Report aggregate=AutomaticSolverQualification.select(cpuPair,mixedPair,cpuJob,gpuJob);
        check(aggregate.mixedFaster&&!aggregate.solverFaster);
        check(aggregate.reason.contains("Independent CPU + GPU"));
        check(!AutomaticSolverQualification.select(cpuPair,new long[]{20_000_000,22_000_000},cpuJob,gpuJob).mixedFaster);
        check(!AutomaticSolverQualification.select(cpuPair,new long[]{12_000_000,22_000_000},cpuJob,gpuJob).mixedFaster);
        AutomaticSolverQualification.Report isolated=AutomaticSolverQualification.select(
            cpuPair,new long[]{22_000_000,23_000_000},cpuJob,new long[]{7_000_000,8_000_000});
        check(isolated.solverFaster&&!isolated.mixedFaster);
        try{AutomaticSolverQualification.select(cpuPair,new long[]{0,13_000_000},cpuJob,gpuJob);throw new AssertionError("Invalid timing accepted");}
        catch(IllegalArgumentException expected){}
        try{AutomaticSolverQualification.check("canonical receipt","different receipt");throw new AssertionError("Parity mismatch accepted");}
        catch(IllegalStateException expected){}
        for(String restriction:new String[]{"Thermal protection","Qualification memory headroom"}){
            try{AutomaticSolverQualification.run(new GpuProcess(),()->restriction);throw new AssertionError("Protection ignored");}
            catch(QualificationProtection expected){}
        }
        System.out.println("PASS: aggregate mixed gain with slower GPU job; regression, parity, cancellation and memory protection");
    }
}
