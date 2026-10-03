"""Crash recovery, proposal isolation and stored-receipt corruption checks."""
import json,sys,tempfile
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from prepare_research_campaign import prepare
from run_research_program import run
p=prepare();calls=[]
def fake(job,checkpoint=None):
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
with tempfile.TemporaryDirectory() as d:
    folder=Path(d);clock=[0.0];attempts=[]
    def slow(job,checkpoint):
        attempts.append(job['id'])
        checkpoint(0,len(job['core_indices']))
        clock[0]=2.0
        checkpoint(1,len(job['core_indices']))
        raise AssertionError('Expired work continued')
    with patch('run_research_program.time.monotonic',side_effect=lambda:clock[0]):
        result=run(p,d,max_seconds=1,executor=slow)
    assert result['interrupted_job'] and result['next_ordinal']==0 and result['processed']==0
    assert not list(folder.iterdir()), 'Interrupted work left a receipt or lock'
    result=run(p,d,max_jobs=1,executor=fake)
    assert result['next_ordinal']==1 and calls[-1]==attempts[0]
print('RESEARCH_PROGRAM_RESUME_AND_INTEGRITY_OK')
