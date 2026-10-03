"""Crash recovery, proposal isolation and stored-receipt corruption checks."""
import json,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from prepare_research_campaign import prepare
from run_research_program import run
p=prepare();calls=[]
def fake(job):
    calls.append(job['id']);return dict(complete=False,status='unknown_budget')
with tempfile.TemporaryDirectory() as d:
    folder=Path(d)
    a=run(p,d,max_jobs=2,executor=fake)
    assert a['next_ordinal']==2 and a['unknown_budget']==2
    cp=folder/'checkpoint.json';s=json.loads(cp.read_text());s['next_ordinal']=1;cp.write_text(json.dumps(s))
    b=run(p,d,max_jobs=2,executor=fake)
    assert b['resumed']==1 and b['processed']==1 and len(calls)==3
    changed=dict(p,ciphertext='A'*72)
    try:run(changed,d,executor=fake)
    except ValueError:pass
    else:raise AssertionError('Mixed different programs')
    s['next_ordinal']=0;cp.write_text(json.dumps(s))
    path=folder/(calls[0]+'.json');r=json.loads(path.read_text());r['receipt']['complete']=True;path.write_text(json.dumps(r))
    try:run(p,d,executor=fake)
    except ValueError:pass
    else:raise AssertionError('Accepted corrupted receipt')
    assert not (folder/'runner.lock').exists()
print('RESEARCH_PROGRAM_RESUME_AND_INTEGRITY_OK')
