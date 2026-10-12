"""Offline injected software kernel parity/lifecycle check; no Vulkan activation."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from qualify_portable_tape import JAVA as TAPE_JAVA
ROOT=Path(__file__).resolve().parents[2]
JAVA=r'''
import java.util.*;import java.util.concurrent.*;import java.util.concurrent.atomic.*;import java.io.*;
import org.enigmagrid.core.*;
public class PortableGpuRunnerCheck {
 static final List<PortableSearchJob.SeedState> SEEDS=Arrays.asList(new PortableSearchJob.SeedState("121416849826178189842829416578566957609","54424835272139916671769879696161322297"));
 static int[] cipher,table;static int[] kinds={1,2,3,4,5,6};
 static class Software implements PortableGpuSearch.Backend {
  int[] state,p;int steps,closes;boolean bad,fail;AtomicBoolean stop;
  public int begin(int[] ref,int[] s,int[] params){
   PortableTapeCheck.check(ref.length==697+table.length&&Arrays.equals(Arrays.copyOfRange(ref,0,72),cipher),"Reference layout");
   state=s;p=params;PortableTapeCheck.check(p.length==12&&p[0]==256&&p[1]==0&&p[2]==1,"Params");
   for(int i=0;i<p[0];i++){int b=i*86;int cost=PortableEventScore.score(cipher,Arrays.copyOfRange(state,b,b+42),table);state[b+84]=cost;state[b+85]=cost;}
   return 71;
  }
  public void step(int session,int[] t,int n){
   PortableTapeCheck.check(session==71&&n==16&&t.length==n*p[0]*5,"Step layout");steps++;
   if(fail)throw new IllegalStateException("Injected dispatch failure");
   if(stop!=null){stop.set(true);return;}
   for(int iter=0;iter<n;iter++)for(int i=0;i<p[0];i++){
    int b=i*86,at=(iter*p[0]+i)*5;int[] old=Arrays.copyOfRange(state,b,b+42);
    int[] proposed=PortableTapeCheck.mutate(old,t,at,p[3],p[4],Arrays.copyOfRange(p,6,6+p[5]));
    int cost=PortableEventScore.score(cipher,proposed,table);
    if(cost<=state[b+84]+t[at+4]){System.arraycopy(proposed,0,state,b,42);state[b+84]=cost;}
    if(state[b+84]<state[b+85]){System.arraycopy(state,b,state,b+42,42);state[b+85]=state[b+84];}
   }
  }
  public int[] finish(int session){PortableTapeCheck.check(steps==32,"Iteration count");if(bad)state[85]++;return state;}
  public void close(int session){PortableTapeCheck.check(session==71,"Close handle");closes++;}
 }
 static List<PortableSearchJob.Hit> run(Software backend,int min,int max,java.util.function.BooleanSupplier stop)throws Exception {
  return PortableGpuSearch.run(cipher,table,71000000000L,256,8,min,max,kinds,SEEDS,stop,backend);
 }
 public static void main(String[] args)throws Exception {
  cipher=PortableEventScore.ciphertext(args[1]);table=new int[PortableEventScore.QUADGRAM_ITEMS];
  try(DataInputStream in=new DataInputStream(new FileInputStream(args[0]))){for(int i=0;i<table.length;i++)table[i]=in.readInt();}
  for(int[] range:new int[][]{{0,3},{4,10},{11,13}}){
   Software backend=new Software();List<PortableSearchJob.Hit> actual=run(backend,range[0],range[1],()->false);
   List<PortableSearchJob.Hit> expected=PortableSearchJob.run(cipher,table,71000000000L,256,512,8,range[0],range[1],kinds,SEEDS,()->false);
   for(int i=0;i<8;i++)PortableTapeCheck.check(actual.get(i).attempt==expected.get(i).attempt&&actual.get(i).cost==expected.get(i).cost&&Arrays.equals(actual.get(i).key,expected.get(i).key),"Complete state receipt parity");
   PortableTapeCheck.check(backend.closes==1,"Success close");
  }
  Software cancel=new Software();AtomicBoolean stopped=new AtomicBoolean();cancel.stop=stopped;
  try{run(cancel,0,3,stopped::get);throw new AssertionError("Cancellation ignored");}catch(CancellationException expected){}
  PortableTapeCheck.check(cancel.closes==1&&cancel.steps==1,"Cancellation cleanup");
  Software failure=new Software();failure.fail=true;
  try{run(failure,0,3,()->false);throw new AssertionError("Failure ignored");}catch(IllegalStateException expected){PortableTapeCheck.check(expected.getMessage().contains("Injected"),"Failure masked");}
  PortableTapeCheck.check(failure.closes==1,"Failure cleanup");
  Software bad=new Software();bad.bad=true;
  try{run(bad,0,3,()->false);throw new AssertionError("Corrupt state accepted");}catch(IllegalStateException expected){}
  PortableTapeCheck.check(bad.closes==1,"Invalid result cleanup");
  System.out.println("PASS resident runner512 iterations exact top8 keys/costs/attempts for3pairranges; cancellation, dispatchfailure, corruptstate close exactlyonce");
 }
}
'''
def main():
 import json
 p=argparse.ArgumentParser();p.add_argument('--jdk',type=Path,required=True);a=p.parse_args()
 names=['EnigmaM4','PortableEventScore','PortablePcg64','PortableKeySampler','PortableSearchJob','PortableRandomTape','PortableGpuSearch']
 core=ROOT/'android/core/src/main/java/org/enigmagrid/core';assets=ROOT/'android/app/src/main/assets'
 with tempfile.TemporaryDirectory(prefix='enigma-gpu-runner-') as tmp:
  cli=Path(tmp)/'PortableGpuRunnerCheck.java';cli.write_text(JAVA)
  helper=Path(tmp)/'PortableTapeCheck.java';helper.write_text(TAPE_JAVA)
  subprocess.run([str(a.jdk/'bin/javac.exe'),'-d',tmp,*[str(core/(n+'.java')) for n in names],str(cli),str(helper)],check=True)
  text=json.loads((assets/'portable_c3_scope_v1.json').read_text())['ciphertext']
  subprocess.run([str(a.jdk/'bin/java.exe'),'-Xmx256m','-cp',tmp,'PortableGpuRunnerCheck',str(assets/'portable_qint_v1.bin'),text],check=True,timeout=180)
if __name__=='__main__':main()
