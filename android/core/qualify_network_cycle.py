"""Check actual NetworkWorker retry/state transitions with controlled adapters."""
import argparse,pathlib,subprocess,tempfile
p=argparse.ArgumentParser();p.add_argument('--jdk',required=True);a=p.parse_args();jdk=pathlib.Path(a.jdk)/'bin'
root=pathlib.Path(__file__).resolve().parents[1]
sources={
'org/enigmagrid/android/CoordinatorClient.java':'''package org.enigmagrid.android;import java.util.*;import java.io.*;import static org.enigmagrid.core.Canonical.object;
class CoordinatorClient{List<String> calls=new ArrayList<>();boolean failSettings,failComplete,disabled,required;boolean idle;String origin(){return "https://test";}CoordinatorClient fork(){return this;}void cancel(){}Map<String,Object> request(String path,Map<String,Object> b,String t)throws Exception{org.enigmagrid.core.Canonical.json(b);calls.add(path);if(path.endsWith("settings")&&failSettings)throw new IOException();if(path.endsWith("complete")&&failComplete)throw new IOException();if(path.endsWith("lease"))return object("enabled",!disabled,"update_required",required,"lease",idle?null:object("id","lease","work_token","secret"));return object("ok",true);}int count(String suffix){return (int)calls.stream().filter(s->s.endsWith(suffix)).count();}}
''',
'org/enigmagrid/android/CredentialStore.java':'''package org.enigmagrid.android;import java.util.*;class CredentialStore{Map<String,Object> value;CredentialStore pending;Map<String,Object> load(){return value;}void save(Map<String,Object> v){value=v;}void clear(){value=null;}CredentialStore pendingResults(){if(pending==null)pending=new CredentialStore();return pending;}}''',
'org/enigmagrid/android/Enrollment.java':'''package org.enigmagrid.android;import java.util.*;class Enrollment{static Map<String,Object> metadata(){return new HashMap<>();}}''',
'org/enigmagrid/core/WorkEnvelope.java':'''package org.enigmagrid.core;import java.util.*;import java.util.function.*;import static org.enigmagrid.core.Canonical.object;public class WorkEnvelope{public static void validate(Map<String,Object> m){}public static Map<String,Object> run(Map<String,Object> l,BooleanSupplier c,BoundedCrib.RowProvider r,int n){return object("receipt",object("candidates",new ArrayList<>()));}}''',
'org/enigmagrid/android/NetworkCycleChecks.java':'''package org.enigmagrid.android;import java.util.*;import java.io.*;import static org.enigmagrid.core.Canonical.object;
public class NetworkCycleChecks{static void check(boolean b){if(!b)throw new AssertionError();}public static void main(String[] args)throws Exception{
CoordinatorClient c=new CoordinatorClient();CredentialStore s=new CredentialStore();s.save(object("server",c.origin(),"device_token","token"));NetworkWorker w=new NetworkWorker(c,s);Map<String,Object> settings=object("cpu_percent",100);
w.once(()->false,settings);w.once(()->false,settings);check(c.count("settings")==1&&c.count("heartbeat")==0&&c.count("complete")==2);
c.idle=true;w.once(()->false,settings);check(!w.acknowledgedWork());c.idle=false;
settings.put("cpu_percent",50);c.failSettings=true;try{w.once(()->false,settings);throw new AssertionError();}catch(IOException expected){}c.failSettings=false;w.once(()->false,settings);check(c.count("settings")==3);
c.failComplete=true;try{w.once(()->false,settings);throw new AssertionError();}catch(IOException expected){}check(s.pendingResults().load()!=null&&!w.acknowledgedWork());int leases=c.count("lease");c.failComplete=false;w.once(()->false,settings);check(s.pendingResults().load()==null&&w.acknowledgedWork()&&c.count("lease")==leases);
int completed=c.count("complete");c.disabled=true;try{w.once(()->false,settings);throw new AssertionError();}catch(IllegalStateException expected){}check(!w.acknowledgedWork()&&c.count("complete")==completed);c.disabled=false;c.required=true;try{w.once(()->false,settings);throw new AssertionError();}catch(IllegalStateException expected){}check(c.count("complete")==completed);
System.out.println("PASS: repeated work, idle reset, settings retry, durable replay, disable, mandatory update");}}
'''
}
with tempfile.TemporaryDirectory(prefix='enigma-network-cycle-') as folder:
 d=pathlib.Path(folder);files=[]
 for name,source in sources.items():
  f=d/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(source,encoding='utf-8');files.append(str(f))
 files += [str(f) for f in (root/'core/src/main/java').rglob('*.java') if f.name!='WorkEnvelope.java']
 files.append(str(root/'app/src/main/java/org/enigmagrid/android/NetworkWorker.java'))
 subprocess.run([str(jdk/'javac.exe'),'-encoding','UTF-8','-d',str(d),*files],check=True)
 subprocess.run([str(jdk/'java.exe'),'-cp',str(d),'org.enigmagrid.android.NetworkCycleChecks'],check=True)
