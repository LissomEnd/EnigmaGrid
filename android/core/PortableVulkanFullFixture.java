package org.enigmagrid.core;
import java.io.*;import java.util.*;
/** Offline complete-unit fixture; CPU reference uses canonical sampler, not GPU tape decisions. */
public class PortableVulkanFullFixture {
 static void put(DataOutputStream o,int x)throws Exception{o.writeInt(Integer.reverseBytes(x));}
 public static void main(String[] a)throws Exception{
 Scanner seeds=new Scanner(new File(a[3]));List<PortableSearchJob.SeedState> states=new ArrayList<>();while(seeds.hasNext())states.add(new PortableSearchJob.SeedState(seeds.next(),seeds.next()));
 int[] cipher=PortableEventScore.ciphertext(a[2]),q=new int[456976],w=new int[625],kinds={1,2,3,4,5,6};EnigmaM4.copyRowTables(w);
 try(DataInputStream in=new DataInputStream(new FileInputStream(a[0]))){for(int i=0;i<q.length;i++)q[i]=in.readInt();}
 int min=Integer.parseInt(a[4]),max=Integer.parseInt(a[5]),n=states.size()*256;
 PortableRandomTape tape=new PortableRandomTape(states,min,max,kinds,512);PortableKeySampler[] samplers=new PortableKeySampler[states.size()];int[][] keys=new int[n][],best=new int[n][];int[] cost=new int[n],bc=new int[n];
 for(int c=0;c<states.size();c++){PortableSearchJob.SeedState s=states.get(c);samplers[c]=new PortableKeySampler(new PortablePcg64(s.state,s.increment),min,max,kinds);int[][] initial=samplers[c].initial();for(int i=0;i<256;i++){int t=c*256+i;keys[t]=initial[i];best[t]=keys[t].clone();cost[t]=bc[t]=PortableEventScore.score(cipher,keys[t],q);}}
 try(DataOutputStream o=new DataOutputStream(new BufferedOutputStream(new FileOutputStream(a[1])))){
 for(int x:cipher)put(o,x);for(int x:w)put(o,x);for(int x:q)put(o,x);put(o,n);put(o,min);put(o,max);
 for(int[] key:tape.initialKeys()){for(int x:key)put(o,x);for(int j=0;j<44;j++)put(o,0);}
 for(int step=0;step<512;step+=16){for(int x:tape.next(16))put(o,x);
 for(int inner=0;inner<16;inner++)for(int c=0;c<states.size();c++){int[][] current=Arrays.copyOfRange(keys,c*256,(c+1)*256),next=samplers[c].mutate(current);int temp=Math.max(2500,38000*(512-step-inner)/512);
 for(int i=0;i<256;i++){int t=c*256+i,candidate=PortableEventScore.score(cipher,next[i],q),allowance=samplers[c].coolingAllowance(temp+1);if(candidate<=cost[t]+allowance){keys[t]=next[i];cost[t]=candidate;}if(cost[t]<bc[t]){bc[t]=cost[t];best[t]=keys[t].clone();}}}
 for(int i=0;i<n;i++){for(int x:keys[i])put(o,x);for(int x:best[i])put(o,x);put(o,cost[i]);put(o,bc[i]);}
 }
 }
 System.out.println("CPU fixture PASS trajectories="+n+" iterations=512 pairs="+min+".."+max);
 }
}
