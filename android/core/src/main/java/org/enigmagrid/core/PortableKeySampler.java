package org.enigmagrid.core;

import java.util.Arrays;

/** Exact key initialization and mutation draws for the fixed portable_event_v1
 * 256-trajectory search block. Not yet an enrolling/executing worker.
 */
public final class PortableKeySampler {
    public static final int TRAJECTORIES=256;
    private static final int SHELL_COUNT=1344;
    private final PortablePcg64 random;
    private final int[] allowedKinds;
    private final int minPairs,maxPairs;

    public PortableKeySampler(PortablePcg64 random,int minPairs,int maxPairs,int[] allowedKinds){
        if(random==null||minPairs<0||maxPairs>13||minPairs>maxPairs
                ||allowedKinds==null||allowedKinds.length<1||allowedKinds.length>6)
            throw new IllegalArgumentException("Invalid search profile");
        for(int kind:allowedKinds)if(kind<1||kind>6)
            throw new IllegalArgumentException("Invalid event kind");
        this.random=random;this.minPairs=minPairs;this.maxPairs=maxPairs;
        this.allowedKinds=allowedKinds.clone();
    }
    public int[][] initial(){
        int[][] keys=new int[TRAJECTORIES][PortableEventScore.KEY_LENGTH];
        // NumPy draws entire arrays before advancing to the next column slice.
        for(int i=0;i<TRAJECTORIES;i++)keys[i][0]=random.bounded(SHELL_COUNT);
        for(int i=0;i<TRAJECTORIES;i++)for(int j=2;j<9;j++)
            keys[i][j]=random.bounded(26);
        for(int i=0;i<TRAJECTORIES;i++)for(int j=35;j<39;j++)
            keys[i][j]=random.bounded(26);
        for(int i=0;i<TRAJECTORIES;i++)
            keys[i][39]=allowedKinds[random.bounded(allowedKinds.length)];
        for(int i=0;i<TRAJECTORIES;i++)
            keys[i][40]=(1+random.bounded(17))*4;
        for(int i=0;i<TRAJECTORIES;i++)
            keys[i][41]=1+random.bounded(4);
        for(int i=0;i<TRAJECTORIES;i++){
            final int[] k=keys[i];
            for(int j=0;j<26;j++)k[9+j]=j;
            int[] perm=random.permutation26();
            int n=minPairs+random.bounded(maxPairs-minPairs+1);
            for(int j=0;j<n;j++){
                int a=perm[2*j],b=perm[2*j+1];
                k[9+a]=b;
                k[9+b]=a;
            }
        }
        return keys;
    }
    public int coolingAllowance(int exclusiveUpper){return random.bounded(exclusiveUpper);}
    public int[][] mutate(int[][] keys){
        if(keys==null||keys.length!=TRAJECTORIES)
            throw new IllegalArgumentException("Must mutate a complete 256-key block");
        int[][] copy=new int[TRAJECTORIES][];
        int[] operations=new int[TRAJECTORIES],a=new int[TRAJECTORIES],
            b=new int[TRAJECTORIES],values=new int[TRAJECTORIES];
        for(int i=0;i<TRAJECTORIES;i++)operations[i]=random.bounded(100);
        for(int i=0;i<TRAJECTORIES;i++)a[i]=random.bounded(26);
        for(int i=0;i<TRAJECTORIES;i++)b[i]=random.bounded(26);
        for(int i=0;i<TRAJECTORIES;i++)values[i]=random.bounded(1<<30);
        for(int i=0;i<TRAJECTORIES;i++){
            int[] original=keys[i];
            if(original.length!=PortableEventScore.KEY_LENGTH)
                throw new IllegalArgumentException("Invalid key length");
            int[] k=original.clone();copy[i]=k;
            int op=operations[i],v=values[i];
            if(op<58){
                int x=a[i],y=b[i];
                if(x==y)y=(y+1)%26;
                int px=k[9+x],py=k[9+y];
                k[9+x]=x;k[9+px]=px;k[9+y]=y;k[9+py]=py;
                if(v%3!=0){k[9+x]=y;k[9+y]=x;}
                int plugged=0;
                for(int j=0;j<26;j++)if(k[9+j]!=j)plugged++;
                int pairs=plugged/2;
                if(pairs<minPairs||pairs>maxPairs)
                    System.arraycopy(original,9,k,9,26);
            }else if(op<70){
                k[5+v%4]=a[i];
            }else if(op<78){
                k[2+v%3]=a[i];
            }else if(op<82){
                k[0]=v%SHELL_COUNT;
            }else if(op<88){
                k[39]=allowedKinds[v%allowedKinds.length];
            }else if(op<94){
                k[40]=(1+v%17)*4;
            }else if(op<97){
                k[41]=1+v%4;
            }else{
                k[35+v%4]=a[i];
            }
        }
        return copy;
    }
}
