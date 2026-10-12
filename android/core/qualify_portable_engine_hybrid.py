"""Host-stub orchestration test only: deterministic core/native math has separate qualifications."""
import argparse,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
FILES={
'android/content/Context.java':r'''package android.content; public class Context {private final String root;public Context(String r){root=r;}public android.content.res.AssetManager getAssets(){return new android.content.res.AssetManager(root);}}''',
'android/content/res/AssetManager.java':r'''package android.content.res;public class AssetManager{private final String root;public AssetManager(String r){root=r;}public java.io.InputStream open(String name)throws Exception{return new java.io.FileInputStream(root+"/"+name);}}''',
'org/json/JSONObject.java':r'''package org.json;public class JSONObject{private final String s;public JSONObject(String x){s=x;}public String getString(String key){java.util.regex.Matcher m=java.util.regex.Pattern.compile("\\\""+key+"\\\"\\s*:\\s*\\\"([^\\\"]*)\\\"").matcher(s);if(!m.find())throw new IllegalArgumentException(key);return m.group(1);}}''',
'org/enigmagrid/core/Canonical.java':r'''package org.enigmagrid.core;public class Canonical{public static java.util.Map<String,Object> object(Object...v){java.util.Map<String,Object> m=new java.util.LinkedHashMap<>();for(int i=0;i<v.length;i+=2)m.put((String)v[i],v[i+1]);return m;}}''',
'org/enigmagrid/core/PortableEventScore.java':r'''package org.enigmagrid.core;public class PortableEventScore{public static final int QUADGRAM_ITEMS=456976;public static int[] ciphertext(String text){return new int[72];}}''',
'org/enigmagrid/core/PortableSelfTest.java':r'''package org.enigmagrid.core;public class PortableSelfTest{public static void verify(int[]a,int[]b){}}''',
'org/enigmagrid/core/PortableSearchJob.java':r'''
package org.enigmagrid.core;import java.util.*;import java.util.function.*;
public class PortableSearchJob{
 public static final List<String> calls=Collections.synchronizedList(new ArrayList<>());
 public static class SeedState{public final String state,increment;public SeedState(String s,String i){state=s;increment=i;}}
 public static class Hit{public final long attempt;public final int cost;public final int[] key;public Hit(long a,int c){attempt=a;cost=c;key=new int[]{(int)(a%1000)};}}
 public static List<Hit> hits(long start,int count,int k,List<SeedState> states){
  if(states.size()!=count/256)throw new AssertionError("cohort states count");
  int first=(int)((start-71000000000L)/256);for(int i=0;i<states.size();i++)if(!states.get(i).state.equals(""+(1000+first+i)))throw new AssertionError("PCG hint offset");
  List<Hit> hits=new ArrayList<>();for(int i=0;i<count;i++)hits.add(new Hit(start+i,(int)((start+i)%97)));
  hits.sort((a,b)->{int d=Integer.compare(a.cost,b.cost);return d!=0?d:Long.compare(a.attempt,b.attempt);});return new ArrayList<>(hits.subList(0,k));
 }
 public static List<Hit> run(int[]c,int[]q,long start,int count,int iterations,int k,int min,int max,int[]kinds,List<SeedState>states,BooleanSupplier stop,int workers){
  calls.add(start+":"+count);long end=System.nanoTime()+count/256*10000000L;
  while(System.nanoTime()<end){if(stop.getAsBoolean()||Thread.currentThread().isInterrupted())throw new java.util.concurrent.CancellationException();try{Thread.sleep(1);}catch(InterruptedException e){Thread.currentThread().interrupt();throw new java.util.concurrent.CancellationException();}}
  return hits(start,count,k,states);
 }
}
''',
'org/enigmagrid/core/PortableGpuSearch.java':r'''
package org.enigmagrid.core;import java.util.*;import java.util.function.*;
public class PortableGpuSearch{
 public interface Backend{int begin(int[]r,int[]s,int[]p)throws Exception;void step(int h,int[]t,int n)throws Exception;int[]finish(int h)throws Exception;void close(int h)throws Exception;}
 public static List<PortableSearchJob.Hit> run(int[]c,int[]q,long start,int count,int k,int min,int max,int[]kinds,List<PortableSearchJob.SeedState>states,BooleanSupplier stop,Backend b)throws Exception{
  if(stop.getAsBoolean())throw new java.util.concurrent.CancellationException();
  int h=b.begin(c,q,new int[]{count});try{
   b.step(h,new int[]{count},16);if(stop.getAsBoolean())throw new java.util.concurrent.CancellationException();
   int[] delta=b.finish(h);List<PortableSearchJob.Hit> hits=PortableSearchJob.hits(start,count,k,states);
   if(delta[0]!=0)hits.set(0,new PortableSearchJob.Hit(hits.get(0).attempt+1,hits.get(0).cost));return hits;
  }finally{b.close(h);}
 }
}
''',
'org/enigmagrid/android/PortableEngineHybridCheck.java':r'''
package org.enigmagrid.android;import java.util.*;import java.util.concurrent.*;import java.util.concurrent.atomic.*;import org.enigmagrid.core.*;import static org.enigmagrid.core.Canonical.object;
public class PortableEngineHybridCheck{
 static void check(boolean v,String m){if(!v)throw new AssertionError(m);}
 static class Backend implements PortableGpuSearch.Backend{
  int calls,closes;boolean bad,fail,slow,wait;volatile boolean entered;AtomicBoolean eligible;
  public int begin(int[]r,int[]s,int[]p){calls++;return 9;}
  public void step(int h,int[]t,int n)throws Exception{entered=true;if(fail)throw new IllegalStateException("backend");if(eligible!=null)eligible.set(false);if(wait)Thread.sleep(10000);Thread.sleep(slow?300:t[0]/256);}
  public int[]finish(int h){return new int[]{bad?1:0};}public void close(int h){closes++;}
 }
 static Map<String,Object> lease(){List<Object> states=new ArrayList<>();for(int i=0;i<16;i++)states.add(object("offset",i*256,"state",""+(1000+i),"inc","1"));
  return object("engine","portable_event_v1","segment_id","portable-low-v1","start_unit",0,"end_unit",1,"portable_rng_states",states,
  "config",object("base_attempt",71000000000L,"count_per_unit",4096,"iterations",512,"topk",8,"min_pairs",0,"max_pairs",3,"replicas_required",2,"requires",Arrays.asList("cpu"),"event_kinds",Arrays.asList(1,2,3,4,5,6)));}
 static PortableJobEngine create(String assets)throws Exception{return new PortableJobEngine(new android.content.Context(assets));}
 public static void main(String[]args)throws Exception{
  Map<String,Object> lease=lease();PortableJobEngine plain=create(args[0]);Map<String,Object> expected=plain.run(lease,()->false);
  PortableJobEngine hybrid=create(args[0]);Backend b=new Backend();AtomicBoolean eligible=new AtomicBoolean(false);hybrid.configureGpu(()->b,eligible::get,()->false);
  check(hybrid.run(lease,()->false).equals(expected)&&b.calls==0,"lower sliders must defer");
  eligible.set(true);check(hybrid.run(lease,()->false).equals(expected),"qualification CPU receipt");check(hybrid.diagnostics().get("state").equals("qualified"),"qualification timing gate");
  PortableSearchJob.calls.clear();check(hybrid.run(lease,()->false).equals(expected),"hybrid receipt");
  int cpu=((Number)hybrid.diagnostics().get("cpu_cohorts")).intValue(),gpu=((Number)hybrid.diagnostics().get("gpu_cohorts")).intValue();
  check(cpu+gpu==16&&cpu>0&&gpu>0&&PortableSearchJob.calls.size()==1,"disjoint work split");
  b.fail=true;PortableSearchJob.calls.clear();check(hybrid.run(lease,()->false).equals(expected),"GPU failure partial CPU fallback");check(PortableSearchJob.calls.size()==2,"only GPU subset recomputed");
  int calls=b.calls;Object historical=hybrid.diagnostics().get("gpu_seconds");Object stages=hybrid.diagnostics().get("last_gpu_stages");hybrid.run(lease,()->false);check(b.calls==calls,"failed qualification not repeated");
  check(historical.equals(hybrid.diagnostics().get("gpu_seconds"))&&stages.equals(hybrid.diagnostics().get("last_gpu_stages")),"fallback preserves measured timings");check(b.closes==b.calls,"all sessions closed");
  PortableJobEngine bad=create(args[0]);Backend wrong=new Backend();wrong.bad=true;bad.configureGpu(()->wrong,()->true,()->false);
  check(bad.run(lease,()->false).equals(expected),"invalid GPU never emitted");bad.run(lease,()->false);check(wrong.calls==1,"parity failure cached");
  PortableJobEngine slow=create(args[0]);Backend sluggish=new Backend();sluggish.slow=true;slow.configureGpu(()->sluggish,()->true,()->false);
  check(slow.run(lease,()->false).equals(expected),"cold qualification receipt");check(slow.diagnostics().get("state").equals("warm_trial_pending"),"cold compile not permanently rejected");
  slow.run(lease,()->false);check(sluggish.calls==2&&slow.diagnostics().get("state").equals("slower"),"one slower warm GPU trial disabled");slow.run(lease,()->false);check(sluggish.calls==2,"no repeated warm trial");
  PortableJobEngine warmed=create(args[0]);Backend cold=new Backend();cold.slow=true;warmed.configureGpu(()->cold,()->true,()->false);warmed.run(lease,()->false);cold.slow=false;
  check(warmed.run(lease,()->false).equals(expected)&&cold.calls==2&&warmed.diagnostics().get("state").equals("qualified"),"cold shader then warm gain qualifies");
  PortableJobEngine deferred=create(args[0]);Backend changing=new Backend();AtomicBoolean enabled=new AtomicBoolean(true);changing.eligible=enabled;deferred.configureGpu(()->changing,enabled::get,()->false);
  check(deferred.run(lease,()->false).equals(expected),"eligibility change fallback");changing.eligible=null;enabled.set(true);deferred.run(lease,()->false);check(changing.calls==1,"native cleanup cooldown");
  java.lang.reflect.Field deadline=PortableJobEngine.class.getDeclaredField("gpuRetryAfterNanos");deadline.setAccessible(true);deadline.setLong(deferred,0L);
  deferred.run(lease,()->false);check(changing.calls==2,"deferred eligibility retries after cleanup");
  PortableJobEngine cancelled=create(args[0]);Backend blocked=new Backend();blocked.wait=true;cancelled.configureGpu(()->blocked,()->true,()->false);AtomicBoolean stop=new AtomicBoolean();AtomicBoolean gotCancel=new AtomicBoolean();
  Thread caller=new Thread(()->{try{cancelled.run(lease,stop::get);}catch(CancellationException e){gotCancel.set(true);}});caller.start();
  long until=System.nanoTime()+2000000000L;while(!blocked.entered&&System.nanoTime()<until)Thread.sleep(1);stop.set(true);caller.join(2000);
  check(!caller.isAlive()&&gotCancel.get()&&blocked.closes==1,"cancel closes and joins GPU");
  System.out.println("PASS defaultCPU,100percent gate, exactqualification, adaptive disjointsplit, GPUsubset fallback, cachedparity/backend/slow rejection, deferredeligibility, cancellation no danglingthread");
 }
}
'''
}
def main():
 p=argparse.ArgumentParser();p.add_argument('--jdk',type=Path,required=True);a=p.parse_args()
 with tempfile.TemporaryDirectory(prefix='portable-engine-hybrid-') as tmp:
  paths=[]
  for name,content in FILES.items():
   path=Path(tmp)/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content);paths.append(str(path))
  actual=ROOT/'android/app/src/main/java/org/enigmagrid/android/PortableJobEngine.java'
  subprocess.run([str(a.jdk/'bin/javac.exe'),'-d',tmp,*paths,str(actual)],check=True)
  subprocess.run([str(a.jdk/'bin/java.exe'),'-Xmx128m','-cp',tmp,'org.enigmagrid.android.PortableEngineHybridCheck',str(ROOT/'android/app/src/main/assets')],check=True,timeout=60)
if __name__=='__main__':main()
