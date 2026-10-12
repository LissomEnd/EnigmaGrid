package org.enigmagrid.core;

import java.util.Arrays;

/** Exact integer scoring primitive for portable_event_v1, independent of NumPy.
 * This is not yet a runnable portable worker: PCG64 generation and the mutation
 * sequence must independently pass byte-for-byte cross-platform tests first.
 */
public final class PortableEventScore {
    public static final int QUADGRAM_ITEMS = 26 * 26 * 26 * 26;
    public static final int KEY_LENGTH = 42;
    private static final int[] WIRES = new int[625];
    private static final boolean[][] NOTCH = new boolean[8][26];
    static {
        EnigmaM4.copyRowTables(WIRES);
        String[] notch = {"Q","E","V","J","Z","ZM","ZM","ZM"};
        for(int rotor=0;rotor<8;rotor++)
            for(int i=0;i<notch[rotor].length();i++)
                NOTCH[rotor][notch[rotor].charAt(i)-'A']=true;
    }
    private PortableEventScore() {}
    private static int mod(int a){
        a%=26;
        return a<0?a+26:a;
    }
    private static int forward(int rotor,int x,int position,int ring){
        final int shift=position-ring;
        return mod(WIRES[1+rotor*26+mod(x+shift)]-shift);
    }
    private static int reverse(int rotor,int x,int position,int ring){
        final int shift=position-ring;
        return mod(WIRES[313+rotor*26+mod(x+shift)]-shift);
    }
    private static void step(int[] position,int middle,int right){
        boolean middleNotch=NOTCH[middle][position[2]];
        boolean rightNotch=NOTCH[right][position[3]];
        if(middleNotch)position[1]=mod(position[1]+1);
        if(middleNotch||rightNotch)position[2]=mod(position[2]+1);
        position[3]=mod(position[3]+1);
    }
    public static int[] ciphertext(String text){
        if(text==null||text.length()!=72)throw new IllegalArgumentException("72-letter ciphertext required");
        int[] out=new int[72];
        for(int i=0;i<72;i++){
            char c=text.charAt(i);
            if(c<'A'||c>'Z')throw new IllegalArgumentException("ciphertext must be A-Z");
            out[i]=c-'A';
        }
        return out;
    }
    private static int[] shell(int index){
        if(index<0||index>=1344)throw new IllegalArgumentException("Invalid shell index");
        int k=index;
        int rightOrdinal=k%6;k/=6;
        int middleOrdinal=k%7;k/=7;
        int left=k%8;k/=8;
        int greek=8+(k%2);k/=2;
        int reflector=10+k;
        int middle=-1,right=-1;
        for(int a=0;a<8;a++){
            if(a==left)continue;
            if(middleOrdinal--==0){middle=a;break;}
        }
        for(int a=0;a<8;a++){
            if(a==left||a==middle)continue;
            if(rightOrdinal--==0){right=a;break;}
        }
        if(middle<0||right<0)throw new IllegalStateException("Invalid deterministic rotor shell");
        return new int[]{reflector,greek,left,middle,right};
    }
    public static int score(int[] cipher,int[] key,int[] quadgrams){
        if(cipher==null||cipher.length!=72||key==null||key.length!=KEY_LENGTH
                ||quadgrams==null||quadgrams.length!=QUADGRAM_ITEMS)
            throw new IllegalArgumentException("Invalid score inputs");
        final int[] shell=shell(key[0]);
        final int reflector=shell[0],greek=shell[1],left=shell[2],middle=shell[3],right=shell[4];
        int[] position=Arrays.copyOfRange(key,5,9);
        int[] out=new int[72];
        final int kind=key[39],at=key[40],param=key[41];
        if(kind<1||kind>6||at<0||at>71||param<1||param>4)
            throw new IllegalArgumentException("Invalid dynamic event");
        for(int i=0;i<72;i++){
            int steps=1;
            if(i==at){
                if(kind==1)steps=0;
                else if(kind==2)steps=2;
                else if(kind==3){
                    int d=Math.min(4,Math.max(1,param));
                    for(int j=0;j<d;j++)step(position,middle,right);
                    position[3]=mod(position[3]-d);
                }else if(kind==4)position[2]=mod(position[2]+1);
                else if(kind==5)position[2]=mod(position[2]-1);
                else if(kind==6)position=Arrays.copyOfRange(key,35,39);
            }
            for(int j=0;j<steps;j++)step(position,middle,right);
            int x=key[9+cipher[i]];
            x=forward(right,x,position[3],key[4]);
            x=forward(middle,x,position[2],key[3]);
            x=forward(left,x,position[1],key[2]);
            x=forward(greek,x,position[0],key[1]);
            x=WIRES[1+reflector*26+x];
            x=reverse(greek,x,position[0],key[1]);
            x=reverse(left,x,position[1],key[2]);
            x=reverse(middle,x,position[2],key[3]);
            x=reverse(right,x,position[3],key[4]);
            out[i]=key[9+x];
        }
        long full=0,leftCost=0,rightCost=0;
        for(int i=0;i<69;i++){
            int z=((out[i]*26+out[i+1])*26+out[i+2])*26+out[i+3];
            int cost=quadgrams[z];
            full+=cost;
            if(i+3<at)leftCost+=cost;
            if(i>=at)rightCost+=cost;
        }
        long ll=at>3?Math.floorDiv(leftCost,at-3):20000;
        long rr=at<69?Math.floorDiv(rightCost,69-at):20000;
        return Math.toIntExact(72*Math.floorDiv(full,69)+28*Math.max(ll,rr));
    }
}
