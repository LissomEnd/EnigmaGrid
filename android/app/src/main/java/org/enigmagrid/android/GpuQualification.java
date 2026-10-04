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
        int receipts=EngineQualification.run(context,()->Thread.currentThread().isInterrupted(),(key,offset,length)->{
            int[] flat=gpu.rows(EnigmaM4.rowInputs(key.reflector,key.greek,key.moving,key.positions,key.rings,offset,length));
            if(flat.length!=length*26)throw new IllegalStateException("GPU row count");
            int[][] rows=new int[length][26];for(int i=0;i<length;i++)System.arraycopy(flat,i*26,rows[i],0,26);return rows;
        });
        return "Isolated Vulkan compute. Passed "+checked+" contact comparisons and "+receipts+" full GPU-assisted receipts in "+((System.nanoTime()-start)/1000000)+" ms. Network worker integration remains pending.";
        }
    }
}
