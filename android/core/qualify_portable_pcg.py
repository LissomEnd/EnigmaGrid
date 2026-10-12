"""Offline unsigned-limb PCG64 parity versus BigInteger and NumPy plus host benchmark."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
JAVA=r'''
import java.util.*;import java.math.*;import java.nio.file.*;
import org.enigmagrid.core.PortablePcg64;
public class PcgLimbCheck {
 static final BigInteger MASK=BigInteger.ONE.shiftLeft(128).subtract(BigInteger.ONE);
 static final BigInteger MUL=new BigInteger("2360ed051fc65da44385df649fccf645",16);
 static volatile long sink;
 static class Ref {
  BigInteger s,inc;boolean cached;long cache;
  Ref(String s,String inc){this.s=new BigInteger(s);this.inc=new BigInteger(inc);}
  long raw(){s=s.multiply(MUL).add(inc).and(MASK);return Long.rotateRight(s.shiftRight(64).xor(s).longValue(),s.shiftRight(122).intValue()&63);}
  long u32(){if(cached){cached=false;return cache;}long x=raw();cache=x>>>32;cached=true;return x&0xffffffffL;}
  int bounded(int n){long threshold=((1L<<32)-n)%n;while(true){long p=u32()*n;if((p&0xffffffffL)>=threshold)return(int)(p>>>32);}}
  int[] permutation(){int[] a=new int[26];for(int i=0;i<26;i++)a[i]=i;for(int i=25;i>0;i--){long mask=(1L<<(32-Integer.numberOfLeadingZeros(i)))-1;int k;do{k=(int)(u32()&mask);}while(k>i);int hold=a[i];a[i]=a[k];a[k]=hold;}return a;}
 }
 static void check(boolean ok,String reason){if(!ok)throw new AssertionError(reason);}
 public static void main(String[] args)throws Exception{
  List<String> lines=Files.readAllLines(Paths.get(args[0]));int cases=0;
  for(String line:lines){String[] parts=line.split(" ");PortablePcg64 p=new PortablePcg64(parts[0],parts[1]);
   for(int i=2;i<parts.length;i++)check(p.nextUint64()==Long.parseUnsignedLong(parts[i]),"NumPy raw64");
   p=new PortablePcg64(parts[0],parts[1]);Ref r=new Ref(parts[0],parts[1]);
   int[] bounds={1,2,3,6,17,26,100,1344,2501,38001,(1<<29)+1,(1<<30)-1,1<<30};
   for(int i=0;i<600;i++){
    check(p.nextUint32()==r.u32(),"Cached half");
    check(p.nextUint64()==r.raw(),"Mixed raw64/cache");
    for(int b:bounds)check(p.bounded(b)==r.bounded(b),"Bounded/rejection");
    check(Arrays.equals(p.permutation26(),r.permutation()),"Permutation");
   }
   cases++;
  }
  for(String[] bad:new String[][]{{"-1","1"},{BigInteger.ONE.shiftLeft(128).toString(),"1"},{"0","0"},{"0","2"},{"0",BigInteger.ONE.shiftLeft(128).add(BigInteger.ONE).toString()}}){
   try{new PortablePcg64(bad[0],bad[1]);throw new AssertionError("Invalid state accepted");}catch(IllegalArgumentException ok){}
  }
  long[] fast=new long[7],slow=new long[7];int draws=1000000;
  for(int round=-2;round<7;round++){
   PortablePcg64 p=new PortablePcg64("340282366920938463463374607431768211455","340282366920938463463374607431768211455");
   Ref r=new Ref("340282366920938463463374607431768211455","340282366920938463463374607431768211455");
   long x=0,start=System.nanoTime();for(int i=0;i<draws;i++)x^=p.bounded(100);long f=System.nanoTime()-start;sink=x;
   x=0;start=System.nanoTime();for(int i=0;i<draws;i++)x^=r.bounded(100);long s=System.nanoTime()-start;sink=x;
   if(round>=0){fast[round]=f;slow[round]=s;}
  }
  Arrays.sort(fast);Arrays.sort(slow);
  System.out.println("{\"status\":\"PASS\",\"cases\":"+cases+",\"draws_per_sample\":"+draws+",\"limb_median_ms\":"+fast[3]/1e6+",\"bigint_median_ms\":"+slow[3]/1e6+",\"host_speedup\":"+(double)slow[3]/fast[3]+"}");
 }
}
'''
def main():
 p=argparse.ArgumentParser();p.add_argument('--jdk',type=Path,required=True);p.add_argument('--report',type=Path);a=p.parse_args()
 states=[0,1,2**32-1,2**32,2**63-1,2**63,2**64-1,2**64,2**127,2**128-1]
 incs=[1,2**32-1,2**63+1,2**64-1,2**64+1,2**127+1,2**128-1]
 pairs=[(s,i) for s in states for i in incs]
 for seed in range(10):
  st=np.random.PCG64(seed).state['state'];pairs.append((st['state'],st['inc']))
 lines=[]
 for state,inc in pairs:
  bg=np.random.PCG64();bg.state={'bit_generator':'PCG64','state':{'state':state,'inc':inc},'has_uint32':0,'uinteger':0}
  lines.append(' '.join(map(str,[state,inc,*map(int,bg.random_raw(128))])))
 with tempfile.TemporaryDirectory(prefix='enigma-pcg-') as tmp:
  root=Path(tmp);cli=root/'PcgLimbCheck.java';cli.write_text(JAVA);vec=root/'vectors.txt';vec.write_text('\n'.join(lines))
  subprocess.run([str(a.jdk/'bin/javac.exe'),'-d',tmp,str(ROOT/'android/core/src/main/java/org/enigmagrid/core/PortablePcg64.java'),str(cli)],check=True)
  run=subprocess.run([str(a.jdk/'bin/java.exe'),'-Xmx256m','-cp',tmp,'PcgLimbCheck',str(vec)],check=True,capture_output=True,text=True,timeout=180)
  report=json.loads(run.stdout);report['oracle']='NumPy PCG64 raw64 plus independent BigInteger mixed calls/rejection/permutation'
  if a.report:a.report.write_text(json.dumps(report,indent=2)+'\n')
  print(json.dumps(report,indent=2))
if __name__=='__main__':main()
