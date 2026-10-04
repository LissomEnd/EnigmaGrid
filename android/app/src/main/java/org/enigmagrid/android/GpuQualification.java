package org.enigmagrid.android;
import android.content.Context;
import java.io.*;
import java.util.Arrays;
import org.enigmagrid.core.EnigmaM4;

final class GpuQualification {
    static String run(Context context) throws Exception {
        try(GpuProcess gpu=new GpuProcess(context)){
        String[] rotors={"I","II","III","IV","V","VI","VII","VIII"};int checked=0;
        long start=System.nanoTime();
        for(int sample=0;sample<12;sample++) {
            if(Thread.currentThread().isInterrupted())throw new java.util.concurrent.CancellationException();
            String[] moving={rotors[sample%8],rotors[(sample+1)%8],rotors[(sample+3)%8]};
            String reflector=sample%2==0?"Bthin":"Cthin",greek=sample%3==0?"Gamma":"Beta";
            String positions=sample%2==0?"AEVZ":"ZMZM",rings=sample%2==0?"AZMN":"DCBA";
            int offset=sample*3,length=16;
            int[] rows=gpu.rows(EnigmaM4.rowInputs(reflector,greek,moving,positions,rings,offset,length));
            if(rows.length!=length*26)throw new IllegalStateException("GPU result size");
            for(int x=0;x<26;x++) {
                char[] text=new char[offset+length];Arrays.fill(text,(char)(65+x));
                String expected=EnigmaM4.crypt(new String(text),reflector,greek,moving,positions,rings,new String[0]);
                for(int i=0;i<length;i++){if(rows[i*26+x]!=expected.charAt(offset+i)-65)throw new IllegalStateException("GPU/CPU mismatch");checked++;}
            }
        }
        for(int count:new int[]{1,2,16})for(int length:new int[]{1,2,3,16,71,72}){
            if(Thread.currentThread().isInterrupted())throw new java.util.concurrent.CancellationException();
            java.util.List<org.enigmagrid.core.BoundedCrib.Key> keys=new java.util.ArrayList<>();
            for(int i=0;i<count;i++)keys.add(org.enigmagrid.core.BoundedCrib.coreAt((i*271828183L)%org.enigmagrid.core.BoundedCrib.DOMAIN));
            int[][][] actual=org.enigmagrid.core.RowBatch.unpack(gpu.rows(org.enigmagrid.core.RowBatch.pack(keys,72-length,length)),count,length);
            for(int k=0;k<count;k++){
                int[][] expected=org.enigmagrid.core.BoundedCrib.cpuRows(keys.get(k),72-length,length);
                for(int r=0;r<length;r++){if(!Arrays.equals(actual[k][r],expected[r]))throw new IllegalStateException("Batch GPU/CPU mismatch");checked+=26;}
            }
        }
        java.util.concurrent.atomic.AtomicInteger dispatches=new java.util.concurrent.atomic.AtomicInteger();
        org.enigmagrid.core.BatchedRows batched=new org.enigmagrid.core.BatchedRows(packed->{dispatches.incrementAndGet();return gpu.rows(packed);},()->Thread.currentThread().isInterrupted());
        int receipts=EngineQualification.run(context,()->Thread.currentThread().isInterrupted(),batched);
        long[] indices=new long[128];for(int i=0;i<indices.length;i++)indices[i]=i*100003L;
        java.util.Map<String,Object> cpu=org.enigmagrid.core.BoundedCrib.search("BDZGO","AAAAA",0,indices,0,5000,64,256,2048,()->Thread.currentThread().isInterrupted(),null,8);
        dispatches.set(0);
        java.util.Map<String,Object> accelerated=org.enigmagrid.core.BoundedCrib.search("BDZGO","AAAAA",0,indices,0,5000,64,256,2048,()->Thread.currentThread().isInterrupted(),batched,8);
        if(!org.enigmagrid.core.Canonical.json(cpu).equals(org.enigmagrid.core.Canonical.json(accelerated)))throw new IllegalStateException("Batched receipt mismatch");
        if(dispatches.get()!=8)throw new IllegalStateException("Expected eight GPU batches: "+dispatches.get());
        return "Isolated Vulkan compute. Passed "+checked+" contact comparisons and "+receipts+" full GPU-assisted receipts plus 128-core/eight-dispatch parity in "+((System.nanoTime()-start)/1000000)+" ms. GPU is ready for compatible grid work.";
        }
    }
}
