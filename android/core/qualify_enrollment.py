"""Exercise registration transaction ordering with isolated transport/storage doubles."""
import argparse, pathlib, subprocess, tempfile
p=argparse.ArgumentParser();p.add_argument('--jdk',required=True);a=p.parse_args()
root=pathlib.Path(__file__).resolve().parents[2];jdk=pathlib.Path(a.jdk)/'bin'
files={
'Build.java':"package android.os; public class Build {public static String[] SUPPORTED_ABIS={\"test\"};public static class VERSION {public static String RELEASE=\"test\";}}",
'CredentialStore.java':"""package org.enigmagrid.android;import java.util.*;class CredentialStore {Map<String,Object> value;CredentialStore attempt;boolean failSave;CredentialStore(){this(false);}CredentialStore(boolean child){if(!child)attempt=new CredentialStore(true);}Map<String,Object> load(){return value;}void save(Map<String,Object> v)throws Exception{if(failSave)throw new java.io.IOException();value=v;}void clear(){value=null;}CredentialStore registrationAttempt(){return attempt;}}""",
'CoordinatorClient.java':"""package org.enigmagrid.android;import java.util.*;import static org.enigmagrid.core.Canonical.object;class CoordinatorClient{static class HttpFailure extends java.io.IOException{int status;HttpFailure(int status){this.status=status;}}int posts,mode;boolean visible;String origin(){return "https://isolated.invalid";}Map<String,Object> request(String path,Map<String,Object> payload,String token)throws Exception{if(path.endsWith("challenge"))return object("nonce","test","difficulty_bits",0);posts++;visible=Boolean.TRUE.equals(payload.get("public_credit"));if(mode==1)throw new java.io.IOException("lost response");if(mode==2)throw new HttpFailure(403);return object("device_id","device","device_token","synthetic-token","contributor_id","contributor");}}""",
'EnrollmentChecks.java':"""package org.enigmagrid.android;import java.util.*;class EnrollmentChecks{
static void enroll(CoordinatorClient c,CredentialStore s)throws Exception{Enrollment.register(c,s,"Test","",Collections.emptyMap(),()->false);}
public static void main(String[] args)throws Exception{
CoordinatorClient ok=new CoordinatorClient();CredentialStore s=new CredentialStore();enroll(ok,s);if(s.load()==null||s.attempt.load()!=null)throw new AssertionError("commit");try{enroll(ok,s);throw new AssertionError();}catch(IllegalStateException expected){}if(ok.posts!=1)throw new AssertionError("duplicate");
if(ok.visible)throw new AssertionError("private default");CoordinatorClient pub=new CoordinatorClient();Enrollment.register(pub,new CredentialStore(),"Public","",Collections.emptyMap(),true,()->false);if(!pub.visible)throw new AssertionError("public consent ignored");
CoordinatorClient lost=new CoordinatorClient();lost.mode=1;CredentialStore pending=new CredentialStore();try{enroll(lost,pending);throw new AssertionError();}catch(java.io.IOException expected){}if(pending.attempt.load()==null)throw new AssertionError("lost intent");try{enroll(lost,pending);throw new AssertionError();}catch(IllegalStateException expected){}if(lost.posts!=1)throw new AssertionError("ambiguous retry");
CoordinatorClient denied=new CoordinatorClient();denied.mode=2;CredentialStore rejected=new CredentialStore();try{enroll(denied,rejected);throw new AssertionError();}catch(CoordinatorClient.HttpFailure expected){}if(rejected.attempt.load()!=null)throw new AssertionError("definite rejection");
CredentialStore disk=new CredentialStore();disk.failSave=true;CoordinatorClient committed=new CoordinatorClient();try{enroll(committed,disk);throw new AssertionError();}catch(java.io.IOException expected){}if(disk.attempt.load()==null)throw new AssertionError("disk failure lost intent");
CredentialStore cancelled=new CredentialStore();CoordinatorClient unused=new CoordinatorClient();try{Enrollment.register(unused,cancelled,"Test","",Collections.emptyMap(),()->true);throw new AssertionError();}catch(java.util.concurrent.CancellationException expected){}if(unused.posts!=0||cancelled.attempt.load()!=null)throw new AssertionError("cancelled registration posted");
System.out.println("PASS: registration commit, duplicate guard, ambiguous response retention, definite rejection, credential write failure, cancellation");}}
"""}
with tempfile.TemporaryDirectory() as tmp:
    paths=[]
    for name,source in files.items():
        f=pathlib.Path(tmp)/name;f.write_text(source,encoding='utf-8');paths.append(str(f))
    sources=[root/'android/app/src/main/java/org/enigmagrid/android/Enrollment.java',root/'android/core/src/main/java/org/enigmagrid/core/Canonical.java']
    subprocess.run([str(jdk/'javac.exe'),'-d',tmp,*paths,*map(str,sources)],check=True)
    subprocess.run([str(jdk/'java.exe'),'-cp',tmp,'org.enigmagrid.android.EnrollmentChecks'],check=True)
