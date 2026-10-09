package org.enigmagrid.android;

import java.util.*;
import java.util.function.BooleanSupplier;
import org.enigmagrid.core.*;
import static org.enigmagrid.core.Canonical.object;

/** Device qualification of four original scopes in one 512-core GPU transport. */
final class CohortQualification {
    static void run(GpuProcess gpu,BooleanSupplier cancel)throws Exception {
        List<Map<String,Object>> envelopes=new ArrayList<>();List<String> expected=new ArrayList<>();
        for(int job=0;job<4;job++){
            if(cancel.getAsBoolean())throw new java.util.concurrent.CancellationException();
            List<Long> cores=new ArrayList<>();for(int i=0;i<128;i++)cores.add((job*128L+i)*7919L);
            Map<String,Object> envelope=object("engine","bounded_crib_v1","start_unit",job,"end_unit",job+1,"config",object("requires",Arrays.asList("cpu","bounded_crib_v1"),"job",object(
                "engine","bounded_crib_v1","ciphertext","QWERTZUIOPASDFGHJKLYXCVBNM","crib","ABCDEFGHIJKLMNOPQRSTUVWX","offset",0,"core_indices",cores,"model","clean","pairs",10,
                "budgets",object("node_limit",5000,"board_limit",64,"completion_limit",256,"candidate_limit",32))));
            envelopes.add(envelope);expected.add(Canonical.json(WorkEnvelope.run(envelope,cancel,null,8)));
        }
        int[] dispatches={0},delivered={0};
        GpuWorkCohort.run(envelopes,input->{if(input[0]!=512)throw new IllegalStateException("Cohort dispatch width");dispatches[0]++;return gpu.solveKeys(input);},cancel,8,(index,result,seconds)->{
            if(index!=delivered[0]||!expected.get(index).equals(Canonical.json(result)))throw new IllegalStateException("GPU cohort receipt mismatch");delivered[0]++;
        });
        if(dispatches[0]!=1||delivered[0]!=4)throw new IllegalStateException("Incomplete GPU cohort qualification");
        if(cancel.getAsBoolean())throw new java.util.concurrent.CancellationException();
        // Exercise >Binder-sized input and output at the accepted row boundary.
        List<BoundedCrib.Key> keys=new ArrayList<>();for(int i=0;i<512;i++)keys.add(BoundedCrib.coreAt(i*7919L));
        int[][][] result=RowBatch.unpack(gpu.rows(RowBatch.pack(keys,0,72)),512,72);
        for(int i=0;i<512;i++){
            if(cancel.getAsBoolean())throw new java.util.concurrent.CancellationException();
            if(!Arrays.deepEquals(result[i],BoundedCrib.cpuRows(keys.get(i),0,72)))throw new IllegalStateException("512-core shared row parity");
        }
    }
}
