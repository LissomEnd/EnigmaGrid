import org.enigmagrid.core.*;
import java.util.*;
import java.util.concurrent.*;
public class ParallelChecks {
 public static void main(String[] args){
  long[] indices=new long[128];for(int i=0;i<indices.length;i++)indices[i]=i*7919;
  Set<Long> threads=ConcurrentHashMap.newKeySet();
  for(int limit:new int[]{1,16,128}){
   Map<String,Object> serial=BoundedCrib.search("QWERTZUIOPASDFGHJKLYXCVBNM","WETT",0,indices,2,100,8,8,limit,()->false);
   Map<String,Object> parallel=BoundedCrib.search("QWERTZUIOPASDFGHJKLYXCVBNM","WETT",0,indices,2,100,8,8,limit,()->{threads.add(Thread.currentThread().getId());return false;},null,8);
   if(!Canonical.json(serial).equals(Canonical.json(parallel)))throw new AssertionError("receipt parity");
  }
  if(threads.size()<3)throw new AssertionError("parallel workers absent");
  try{BoundedCrib.search("QWERTZ","WETT",0,indices,2,100,8,8,16,()->true,null,8);throw new AssertionError("cancel ignored");}catch(CancellationException expected){}
  java.util.concurrent.atomic.AtomicInteger checks=new java.util.concurrent.atomic.AtomicInteger();
  try{BoundedCrib.search("QWERTZUIOPASDFGHJKLYXCVBNM","WETT",0,indices,2,5000,64,256,128,()->checks.incrementAndGet()>30,null,8);throw new AssertionError("running cancellation ignored");}catch(CancellationException expected){}
  try{BoundedCrib.search("QWERTZUIOPASDFGHJKLYXCVBNM","WETT",0,indices,2,5000,64,256,128,()->false,(k,o,n)->{throw new IllegalStateException("backend test failure");},8);throw new AssertionError("backend failure ignored");}catch(IllegalStateException expected){if(!"backend test failure".equals(expected.getMessage()))throw expected;}
  for(Thread thread:Thread.getAllStackTraces().keySet())if(thread.isAlive()&&thread.getName().startsWith("pool-"))throw new AssertionError("search worker leaked: "+thread.getName());
  System.out.println("PASS 128-core receipt parity, candidate caps, concurrent execution, running cancellation, backend failure and worker cleanup; threads="+threads.size());
 }
}
