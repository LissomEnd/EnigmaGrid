package org.enigmagrid.core;
import java.io.*;import java.nio.*;import java.nio.file.*;import java.util.*;import org.enigmagrid.core.*;
public class PortableVulkanFixture {
 static void put(DataOutputStream out,int v)throws Exception{out.writeInt(Integer.reverseBytes(v));}
 public static void main(String[] args)throws Exception{
 int[] cipher=PortableEventScore.ciphertext(args[2]),q=new int[456976],w=new int[625];EnigmaM4.copyRowTables(w);
 try(DataInputStream in=new DataInputStream(new FileInputStream(args[0]))){for(int i=0;i<q.length;i++)q[i]=in.readInt();}
 try(DataOutputStream o=new DataOutputStream(new BufferedOutputStream(new FileOutputStream(args[1])))){
 for(int x:cipher)put(o,x);for(int x:w)put(o,x);for(int x:q)put(o,x);
 put(o,18);
 for(int[] pair:new int[][]{{0,3},{4,10},{11,13}})for(int kind=1;kind<=6;kind++){
 String seed="121416849826178189842829416578566957609",inc="54424835272139916671769879696161322297";
 int[] kinds={kind};PortableRandomTape tape=new PortableRandomTape(Arrays.asList(new PortableSearchJob.SeedState(seed,inc)),pair[0],pair[1],kinds,512);
 PortableKeySampler sampler=new PortableKeySampler(new PortablePcg64(seed,inc),pair[0],pair[1],kinds);
 int[][] keys=sampler.initial(),best=new int[256][];int[] cost=new int[256],bc=new int[256];
 put(o,pair[0]);put(o,pair[1]);put(o,kind);put(o,4);
 for(int[] key:tape.initialKeys()){for(int x:key)put(o,x);for(int j=0;j<44;j++)put(o,0);}
 int step=0;
 for(int chunk:new int[]{0,1,7,24}){
 put(o,chunk);if(chunk>0)for(int x:tape.next(chunk))put(o,x);
 if(chunk==0)for(int i=0;i<256;i++){cost[i]=bc[i]=PortableEventScore.score(cipher,keys[i],q);best[i]=keys[i].clone();}
 for(int s=0;s<chunk;s++,step++){
 int[][] next=sampler.mutate(keys);int temp=Math.max(2500,38000*(512-step)/512);
 for(int i=0;i<256;i++){int c=PortableEventScore.score(cipher,next[i],q);int allowance=sampler.coolingAllowance(temp+1);if(c<=cost[i]+allowance){keys[i]=next[i];cost[i]=c;}if(cost[i]<bc[i]){bc[i]=cost[i];best[i]=keys[i].clone();}}
 }
 for(int i=0;i<256;i++){for(int x:keys[i])put(o,x);for(int x:best[i])put(o,x);put(o,cost[i]);put(o,bc[i]);}
 }
 }
 }
 }
}

