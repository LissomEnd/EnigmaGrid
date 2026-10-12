"""Offline exact random tape/chunk parity; no production state or GPU required."""
import argparse
from pathlib import Path
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[2]
JAVA=r'''
import java.util.*;
import org.enigmagrid.core.*;
public class PortableTapeCheck {
 static final String STATE="121416849826178189842829416578566957609";
 static final String INC="54424835272139916671769879696161322297";
 static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
 static int[] mutate(int[] old,int[] t,int at,int min,int max,int[] kinds){
  int[] k=old.clone();int op=t[at],a=t[at+1],b=t[at+2],v=t[at+3];
  if(op<58){int x=a,y=b;if(x==y)y=(y+1)%26;int px=k[9+x],py=k[9+y];
   k[9+x]=x;k[9+px]=px;k[9+y]=y;k[9+py]=py;
   if(v%3!=0){k[9+x]=y;k[9+y]=x;}
   int n=0;for(int j=0;j<26;j++)if(k[9+j]!=j)n++;
   if(n/2<min||n/2>max)System.arraycopy(old,9,k,9,26);
  }else if(op<70)k[5+v%4]=a;
  else if(op<78)k[2+v%3]=a;
  else if(op<82)k[0]=v%1344;
  else if(op<88)k[39]=kinds[v%kinds.length];
  else if(op<94)k[40]=(1+v%17)*4;
  else if(op<97)k[41]=1+v%4;
  else k[35+v%4]=a;
  return k;
 }
 public static void main(String[] ignored){
  List<PortableSearchJob.SeedState> states=Arrays.asList(
   new PortableSearchJob.SeedState(STATE,INC),
   new PortableSearchJob.SeedState("208321120469391775965813620669216293656","331920061597555133829835660021216857471"));
  boolean[] seen=new boolean[100];int profiles=0;
  for(int[] range:new int[][]{{0,3},{4,10},{11,13}})for(int kind=0;kind<=6;kind++){
   int[] kinds=kind==0?new int[]{1,2,3,4,5,6}:new int[]{kind};
   PortableRandomTape tape=new PortableRandomTape(states,range[0],range[1],kinds,512);
   PortableKeySampler[] refs=new PortableKeySampler[2];int[][][] keys=new int[2][][];
   int[][] initial=tape.initialKeys();initial[0][0]=-999;
   check(tape.initialKeys()[0][0]!=-999,"Initial keys exposed");initial=tape.initialKeys();
   for(int c=0;c<2;c++){
    refs[c]=new PortableKeySampler(new PortablePcg64(states.get(c).state,states.get(c).increment),range[0],range[1],kinds);
    keys[c]=refs[c].initial();
    for(int i=0;i<256;i++)check(Arrays.equals(keys[c][i],initial[c*256+i]),"Initial keys differ");
   }
   for(int chunk=0;chunk<2;chunk++){
    int[] t=tape.next(16);
    for(int step=0;step<16;step++)for(int c=0;c<2;c++){
     int[][] proposed=refs[c].mutate(keys[c]);
     int temperature=Math.max(2500,38000*(512-chunk*16-step)/512);
     for(int i=0;i<256;i++){
      int at=(step*512+c*256+i)*5;seen[t[at]]=true;
      check(Arrays.equals(proposed[i],mutate(keys[c][i],t,at,range[0],range[1],kinds)),"Mutation differs");
      check(t[at+4]==refs[c].coolingAllowance(temperature+1),"RNG stream/allowance differs");
      if((i+step)%3!=0)keys[c][i]=proposed[i];
     }
    }
   }
   profiles++;
  }
  for(boolean value:seen)check(value,"Operation interval untested");
  PortableRandomTape whole=new PortableRandomTape(states,0,3,new int[]{1,2,3,4,5,6},512);
  PortableRandomTape chunks=new PortableRandomTape(states,0,3,new int[]{1,2,3,4,5,6},512);
  int[] expected=whole.next(512);int offset=0;
  try{chunks.next(0);throw new AssertionError("Zero accepted");}catch(IllegalArgumentException ok){}
  try{chunks.next(513);throw new AssertionError("Oversize accepted");}catch(IllegalArgumentException ok){}
  check(chunks.nextIteration()==0,"Invalid request advanced state");
  for(int n=0;n<32;n++){int[] actual=chunks.next(16);for(int x:actual)check(x==expected[offset++],"Chunk boundary changed stream");}
  check(offset==expected.length&&chunks.nextIteration()==512,"Tape length");
  try{chunks.next(1);throw new AssertionError("Overrun accepted");}catch(IllegalArgumentException ok){}
  System.out.println("PASS "+profiles+" pair/event profiles; all100 operation values; exact mutations and cooling; 512 contiguous equals32x16 chunks; validation bounds");
 }
}
'''
def main():
 p=argparse.ArgumentParser();p.add_argument('--jdk',type=Path,required=True);a=p.parse_args()
 names=['EnigmaM4','PortableEventScore','PortablePcg64','PortableKeySampler','PortableSearchJob','PortableRandomTape']
 core=ROOT/'android/core/src/main/java/org/enigmagrid/core'
 with tempfile.TemporaryDirectory(prefix='enigma-tape-') as tmp:
  cli=Path(tmp)/'PortableTapeCheck.java';cli.write_text(JAVA)
  subprocess.run([str(a.jdk/'bin/javac.exe'),'-d',tmp,*[str(core/(n+'.java')) for n in names],str(cli)],check=True)
  subprocess.run([str(a.jdk/'bin/java.exe'),'-Xmx256m','-cp',tmp,'PortableTapeCheck'],check=True,timeout=180)
if __name__=='__main__':main()
