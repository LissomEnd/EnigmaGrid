import org.enigmagrid.core.*;
import java.util.*;
public class CpuRowsChecks {
 static volatile int sink;
 static int[][] reference(String ref,String greek,String[] moving,String positions,String rings,int offset,int length){
  int[][] rows=new int[length][26];
  for(int x=0;x<26;x++){
   char[] input=new char[offset+length];Arrays.fill(input,(char)(65+x));
   String out=EnigmaM4.crypt(new String(input),ref,greek,moving,positions,rings,new String[0]);
   for(int j=0;j<length;j++)rows[j][x]=out.charAt(offset+j)-65;
  }
  return rows;
 }
 static String letters(Random rng){char[] v=new char[4];for(int i=0;i<4;i++)v[i]=(char)(65+rng.nextInt(26));return new String(v);}
 public static void main(String[] args){
  String[] names={"I","II","III","IV","V","VI","VII","VIII"};Random rng=new Random(73182);int count=0;
  for(String a:names)for(String b:names)for(String c:names)if(!a.equals(b)&&!a.equals(c)&&!b.equals(c))
   for(String greek:new String[]{"Beta","Gamma"})for(String ref:new String[]{"Bthin","Cthin"}){
    int offset=rng.nextInt(72),length=1+rng.nextInt(72-offset);String positions=letters(rng),rings=letters(rng);String[] moving={a,b,c};
    if(!Arrays.deepEquals(reference(ref,greek,moving,positions,rings,offset,length),EnigmaM4.rows(ref,greek,moving,positions,rings,offset,length)))throw new AssertionError("row mismatch "+count);
    count++;
   }
  String[] moving={"I","II","III"};
  for(int offset:new int[]{0,1,25,71}){
   int length=72-offset;
   if(!Arrays.deepEquals(reference("Bthin","Beta",moving,"AADV","BCDE",offset,length),EnigmaM4.rows("Bthin","Beta",moving,"AADV","BCDE",offset,length)))throw new AssertionError("double step");
  }
  System.out.println("PASS "+count+" rotor/reflector configurations, randomized rings and windows, explicit double step and boundary windows");
  if(args.length>0&&args[0].equals("--benchmark")){
   for(int round=0;round<6;round++){
    long[] times=new long[2];
    for(int pass=0;pass<2;pass++){int mode=(pass+round)%2;long start=System.nanoTime();
     for(int i=0;i<500;i++){int[][] r=mode==0?reference("Bthin","Beta",moving,"AADV","BCDE",24,24):EnigmaM4.rows("Bthin","Beta",moving,"AADV","BCDE",24,24);sink+=r[i%24][i%26];}
     times[mode]=System.nanoTime()-start;
    }
    System.out.println("sample "+round+" reference_ns="+times[0]+" optimized_ns="+times[1]);
   }
  }
 }
}
