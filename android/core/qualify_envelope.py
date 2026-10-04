"""Full work envelopes and malformed-intake rejection against coordinator reference."""
import argparse,pathlib,subprocess,sys,tempfile,json,copy
root=pathlib.Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'solver/runtime/src'))
from search.crib_work import run,validate_envelope
p=argparse.ArgumentParser();p.add_argument('--jdk',required=True);a=p.parse_args();jdk=pathlib.Path(a.jdk)/'bin'
job={'engine':'bounded_crib_v1','model':'clean','ciphertext':'BDZGO','crib':'AAAAA','offset':0,'pairs':0,'core_indices':[0], 'budgets':{'node_limit':5000,'board_limit':64,'completion_limit':256,'candidate_limit':32}}
direct={'engine':'bounded_crib_v1','start_unit':0,'end_unit':1,'config':{'requires':['cpu','bounded_crib_v1'],'job':job}}
program={'engine':'bounded_crib_v1','start_unit':4,'end_unit':5,'config':{'requires':['cpu','bounded_crib_v1'],'program':{'ciphertext':'BDZGO','hypotheses':[{'text':'BD','legal_clean_offsets':[0]}],'chunk':3,'ordinal_base':2,'candidate_limit':3}}}
cases=[direct,program];expected=[json.dumps(run(c),sort_keys=True,separators=(',',':')) for c in cases]
for path,value in [(('engine',),'other'),(('end_unit',),2),(('start_unit',),True),(('config','requires'),['cpu']),(('config','job','id'),'bad'),(('config','job','extra'),1),(('config','job','core_indices'),[0,0]),(('config','job','core_indices'),[0.0]),(('config','job','budgets','node_limit'),5001),(('config','job','offset'),-1),(('config','job','pairs'),14),(('config','job','model'),'omission')]:
    c=copy.deepcopy(direct);target=c
    for k in path[:-1]:target=target[k]
    target[path[-1]]=value
    try:validate_envelope(c)
    except (ValueError,TypeError):pass
    else:raise AssertionError(('Reference accepted invalid case',path))
    cases.append(c);expected.append('INVALID')
def java(v):
    if v is None:return 'null'
    if type(v) is bool:return str(v).lower()
    if type(v) is int:return str(v)+'L'
    if type(v) is float:return str(v)+'d'
    if type(v) is str:return json.dumps(v)
    if isinstance(v,list):return 'Arrays.asList('+','.join(java(x) for x in v)+')'
    return 'Canonical.object('+','.join(java(x) for k,val in v.items() for x in (k,val))+')'
source='import java.util.*;import org.enigmagrid.core.*;public class EnvelopeFixtures {public static void main(String[] args){'
for c in cases:source+='try{System.out.println(Canonical.json(WorkEnvelope.run('+java(c)+',()->false)));}catch(IllegalArgumentException e){System.out.println("INVALID");}'
source+='int[] dispatches={0};System.out.println(Canonical.json(WorkEnvelope.run('+java(direct)+',()->false,(k,o,n)->{dispatches[0]++;return BoundedCrib.cpuRows(k,o,n);})));if(dispatches[0]==0)throw new AssertionError("Backend not used");'
expected.append(expected[0])
source+='AdaptiveRows fallback=new AdaptiveRows((k,o,n)->{throw new UnsatisfiedLinkError();},()->100,()->false,new WorkControl.SystemTiming());System.out.println(Canonical.json(WorkEnvelope.run('+java(direct)+',()->false,fallback)));if(!fallback.failed())throw new AssertionError("Fallback not used");'
expected.append(expected[0])
source+='try{WorkEnvelope.run('+java(direct)+',()->true);throw new AssertionError("Cancellation ignored");}catch(java.util.concurrent.CancellationException expected){System.out.println("CANCELLED");}}}'
expected.append('CANCELLED')
with tempfile.TemporaryDirectory() as tmp:
    file=pathlib.Path(tmp)/'EnvelopeFixtures.java';file.write_text(source)
    sources=list((root/'android/core/src/main/java/org/enigmagrid/core').glob('*.java'))
    subprocess.run([str(jdk/'javac.exe'),'-d',tmp,*map(str,sources),str(file)],check=True)
    got=subprocess.run([str(jdk/'java.exe'),'-cp',tmp,'EnvelopeFixtures'],capture_output=True,text=True,check=True).stdout.splitlines()
    assert got==expected,(got,expected)
print(f'PASS: {len(expected)} envelope, rejection and cancellation checks')
