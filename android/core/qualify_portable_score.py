"""Offline score parity and alternating host A/B against the prior scalar implementation."""
import argparse,json,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
JAVA=r'''
import java.util.*;import java.io.*;import org.enigmagrid.core.*;
public class PortableScoreCheck{
 static volatile long sink;
 public static void main(String[]args)throws Exception{
  int[] cipher=PortableEventScore.ciphertext(args[1]),table=new int[PortableEventScore.QUADGRAM_ITEMS];
  try(DataInputStream in=new DataInputStream(new FileInputStream(args[0]))){for(int i=0;i<table.length;i++)table[i]=in.readInt();}
  List<int[]> keys=new ArrayList<>();
  for(int[] pairs:new int[][]{{0,3},{4,10},{11,13}}){
   PortableKeySampler sampler=new PortableKeySampler(new PortablePcg64("121416849826178189842829416578566957609","54424835272139916671769879696161322297"),pairs[0],pairs[1],new int[]{1,2,3,4,5,6});
   int[][] batch=sampler.initial();
   for(int j=0;j<32;j++){batch=sampler.mutate(batch);for(int[] original:batch){int[] key=original.clone();int i=keys.size();key[0]=i%1344;key[39]=1+i%6;key[40]=i%72;key[41]=1+i%4;keys.add(key);}}
  }
  for(int[] key:keys)if(PortableEventScore.score(cipher,key,table)!=PortableEventScoreReference.score(cipher,key,table))throw new AssertionError("Score parity");
  int[] signed=table.clone();for(int i=0;i<signed.length;i++)signed[i]-=7000;
  for(int i=0;i<keys.size();i+=17)if(PortableEventScore.score(cipher,keys.get(i),signed)!=PortableEventScoreReference.score(cipher,keys.get(i),signed))throw new AssertionError("Signed floor parity");
  long[] candidate=new long[7],baseline=new long[7];
  for(int round=-2;round<7;round++)for(int pass=0;pass<2;pass++){
   boolean fast=((round+pass)&1)==0;long start=System.nanoTime(),sum=0;
   for(int[] key:keys)sum+=fast?PortableEventScore.score(cipher,key,table):PortableEventScoreReference.score(cipher,key,table);
   long elapsed=System.nanoTime()-start;sink=sum;if(round>=0)(fast?candidate:baseline)[round]=elapsed;
  }
  Arrays.sort(candidate);Arrays.sort(baseline);
  System.out.println("{\"status\":\"PASS\",\"keys\":"+keys.size()+",\"baseline_median_ms\":"+baseline[3]/1e6+",\"candidate_median_ms\":"+candidate[3]/1e6+",\"host_score_speedup\":"+(double)baseline[3]/candidate[3]+"}");
 }
}
'''
def main():
 p=argparse.ArgumentParser();p.add_argument('--jdk',type=Path,required=True);p.add_argument('--report',type=Path);a=p.parse_args()
 core=ROOT/'android/core/src/main/java/org/enigmagrid/core';assets=ROOT/'android/app/src/main/assets'
 with tempfile.TemporaryDirectory(prefix='enigma-score-ab-') as tmp:
  cli=Path(tmp)/'PortableScoreCheck.java';cli.write_text(JAVA)
  names=['EnigmaM4','PortableEventScore','PortablePcg64','PortableKeySampler']
  subprocess.run([str(a.jdk/'bin/javac.exe'),'-d',tmp,*[str(core/(n+'.java')) for n in names],str(ROOT/'android/core/src/test/java/org/enigmagrid/core/PortableEventScoreReference.java'),str(cli)],check=True)
  cipher=json.loads((assets/'portable_c3_scope_v1.json').read_text())['ciphertext']
  run=subprocess.run([str(a.jdk/'bin/java.exe'),'-Xmx256m','-cp',tmp,'PortableScoreCheck',str(assets/'portable_qint_v1.bin'),cipher],check=True,capture_output=True,text=True,timeout=180)
  report=json.loads(run.stdout);report['scope']='Host scalar score A/B, not Android throughput';
  if a.report:a.report.write_text(json.dumps(report,indent=2)+'\n')
  print(json.dumps(report,indent=2))
if __name__=='__main__':main()
