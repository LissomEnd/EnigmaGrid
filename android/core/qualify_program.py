"""Compare indexed jobs including last partial chunks and 64-bit ordinals."""
import argparse,pathlib,subprocess,sys,tempfile,json,random
root=pathlib.Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'solver/runtime/src'))
from search.research_program import job_at
from search.crib_pilot import DOMAIN
from search.bounded_crib import digest
p=argparse.ArgumentParser();p.add_argument('--jdk',required=True);a=p.parse_args();jdk=pathlib.Path(a.jdk)/'bin'
rng=random.Random(45);lines=[];expected=[]
proposal={'ciphertext':'ABCDEFGHIJKLMNOPQRSTUVWXYZ'*2,'hypotheses':[{'text':'WETTER','legal_clean_offsets':[12,0,12]},{'text':'BERICHT','legal_clean_offsets':[1,5]}]}
for chunk in (1,3,64,127,128):
    maxordinal=((DOMAIN+chunk-1)//chunk)*4
    for ordinal in (0,1,3,4,maxordinal-1,maxordinal-4,rng.randrange(maxordinal)):
        limit=1+ordinal%32;job=job_at(proposal,ordinal,chunk)
        job['budgets']['candidate_limit']=limit;job['id']=digest({k:v for k,v in job.items() if k not in ('id','program','ordinal')})
        expected.append(json.dumps(job,sort_keys=True,separators=(',',':')))
        lines.append(f"{proposal['ciphertext']} {ordinal} {chunk} {limit} 5 WETTER 12 WETTER 0 WETTER 12 BERICHT 1 BERICHT 5")
with tempfile.TemporaryDirectory() as tmp:
    sources=list((root/'android/core/src/main/java/org/enigmagrid/core').glob('*.java'))
    subprocess.run([str(jdk/'javac.exe'),'-d',tmp,*map(str,sources),str(root/'android/core/ProgramCli.java')],check=True)
    got=subprocess.run([str(jdk/'java.exe'),'-cp',tmp,'ProgramCli'],input='\n'.join(lines),text=True,capture_output=True,check=True).stdout.splitlines()
    assert len(got)==len(expected)
    for i,(x,y) in enumerate(zip(got,expected)):assert x==y,(i,x,y)
print(f'PASS: {len(expected)} indexed jobs match Python canonical bytes, including domain boundaries')
