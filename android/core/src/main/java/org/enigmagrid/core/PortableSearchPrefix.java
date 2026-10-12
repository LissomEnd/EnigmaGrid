package org.enigmagrid.core;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.security.MessageDigest;
import java.util.Arrays;

/** Canonical bounded-prefix search proof for portable C3 v1.
 * Works only with 256-trajectory blocks and an independently supplied PCG64
 * state. This research fixture never claims a production lease or credits.
 */
public final class PortableSearchPrefix {
    private PortableSearchPrefix(){}
    private static final int BLOCK=PortableKeySampler.TRAJECTORIES;
    public static String[] simulate(int[] cipher,int[] table,PortableKeySampler sampler,
                                    int totalIterations,int prefixIterations) throws Exception{
        if(cipher.length!=72||table.length!=PortableEventScore.QUADGRAM_ITEMS
                ||totalIterations!=512||prefixIterations<0||prefixIterations>totalIterations)
            throw new IllegalArgumentException("Invalid C3 prefix scope");
        int[][] keys=sampler.initial();
        int[] costs=evaluate(cipher,table,keys);
        int[][] best=copy(keys);
        int[] bestCosts=costs.clone();
        String[] snapshots=new String[prefixIterations+1];
        snapshots[0]=digest(keys,costs,best,bestCosts);
        for(int iteration=0;iteration<prefixIterations;iteration++){
            int[][] mutated=sampler.mutate(keys);
            int[] proposed=evaluate(cipher,table,mutated);
            int temp=Math.max(2500,38000*(totalIterations-iteration)/totalIterations);
            // NumPy draws the *entire array* before evaluating each acceptance.
            int[] allowance=new int[BLOCK];
            for(int t=0;t<BLOCK;t++)allowance[t]=sampler.coolingAllowance(temp+1);
            for(int t=0;t<BLOCK;t++){
                if((long)proposed[t]<=(long)costs[t]+allowance[t]){
                    keys[t]=mutated[t];
                    costs[t]=proposed[t];
                }
                if(costs[t]<bestCosts[t]){
                    best[t]=keys[t].clone();
                    bestCosts[t]=costs[t];
                }
            }
            snapshots[iteration+1]=digest(keys,costs,best,bestCosts);
        }
        return snapshots;
    }
    private static int[] evaluate(int[] cipher,int[] table,int[][] keys){
        int[] costs=new int[BLOCK];
        for(int i=0;i<BLOCK;i++)costs[i]=PortableEventScore.score(cipher,keys[i],table);
        return costs;
    }
    private static int[][] copy(int[][] src){
        int[][] result=new int[src.length][];
        for(int i=0;i<src.length;i++)result[i]=src[i].clone();
        return result;
    }
    private static String digest(int[][] keys,int[] costs,int[][] best,int[] bestCosts)
            throws Exception {
        ByteBuffer b=ByteBuffer.allocate((2*BLOCK*PortableEventScore.KEY_LENGTH+2*BLOCK)*4)
            .order(ByteOrder.LITTLE_ENDIAN);
        for(int[] row:keys)for(int v:row)b.putInt(v);
        for(int v:costs)b.putInt(v);
        for(int[] row:best)for(int v:row)b.putInt(v);
        for(int v:bestCosts)b.putInt(v);
        byte[] raw=MessageDigest.getInstance("SHA-256").digest(b.array());
        StringBuilder out=new StringBuilder(64);
        for(byte x:raw)out.append(Character.forDigit((x>>4)&15,16))
                      .append(Character.forDigit(x&15,16));
        return out.toString();
    }
}
