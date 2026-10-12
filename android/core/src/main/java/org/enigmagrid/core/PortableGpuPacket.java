package org.enigmagrid.core;

import java.util.Arrays;

/** Bounded wire envelope for the isolated portable GPU service. */
public final class PortableGpuPacket {
    public static final int REFERENCE_INTS=697+PortableEventScore.QUADGRAM_ITEMS;
    public static final int MAX_TRAJECTORIES=4096, STATE_STRIDE=86, MAX_ITERATIONS=16;
    public static final int MAX_BEGIN=12+REFERENCE_INTS+MAX_TRAJECTORIES*STATE_STRIDE;
    public static final int MAX_STEP=2+MAX_TRAJECTORIES*MAX_ITERATIONS*5;
    private PortableGpuPacket(){}
    public static int trajectories(int[] params){
        if(params==null||params.length!=12||params[0]<256||params[0]>MAX_TRAJECTORIES
                ||params[0]%256!=0||params[1]!=0||params[2]!=1
                ||params[3]<0||params[4]>13||params[3]>params[4]
                ||params[5]<1||params[5]>6)throw new IllegalArgumentException("Invalid portable GPU parameters");
        for(int i=0;i<params[5];i++)if(params[6+i]<1||params[6+i]>6)
            throw new IllegalArgumentException("Invalid portable GPU event");
        return params[0];
    }
    public static int[] begin(int[] reference,int[] state,int[] params){
        int count=trajectories(params);
        if(reference==null||reference.length!=REFERENCE_INTS||state==null||state.length!=count*STATE_STRIDE)
            throw new IllegalArgumentException("Invalid portable GPU buffers");
        int[] result=new int[12+reference.length+state.length];
        System.arraycopy(params,0,result,0,12);System.arraycopy(reference,0,result,12,reference.length);
        System.arraycopy(state,0,result,12+reference.length,state.length);return result;
    }
    public static int[][] unpackBegin(int[] packet){
        if(packet==null||packet.length<12||packet.length>MAX_BEGIN)
            throw new IllegalArgumentException("Invalid portable begin packet");
        int[] params=Arrays.copyOf(packet,12);int count=trajectories(params);
        if(packet.length!=12+REFERENCE_INTS+count*STATE_STRIDE)
            throw new IllegalArgumentException("Invalid portable begin length");
        return new int[][]{Arrays.copyOfRange(packet,12,12+REFERENCE_INTS),
            Arrays.copyOfRange(packet,12+REFERENCE_INTS,packet.length),params};
    }
    public static int[] step(int session,int[] tape,int iterations){
        if(session<=0||iterations<1||iterations>MAX_ITERATIONS||tape==null
                ||tape.length<256*iterations*5||tape.length>MAX_TRAJECTORIES*iterations*5
                ||tape.length%(256*iterations*5)!=0)
            throw new IllegalArgumentException("Invalid portable GPU step");
        int[] result=new int[tape.length+2];result[0]=session;result[1]=iterations;
        System.arraycopy(tape,0,result,2,tape.length);return result;
    }
    public static int[] session(int id){if(id<=0)throw new IllegalArgumentException("Invalid portable session");return new int[]{id};}
}
