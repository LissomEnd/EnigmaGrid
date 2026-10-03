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

# A small finite domain exercises the last partial chunk and restart at its end.
with tempfile.TemporaryDirectory() as d, patch('search.research_program.DOMAIN',129):
    tiny=dict(p,hypotheses=[dict(text='TEST',legal_clean_offsets=[0])])
    before=len(calls)
    result=run(tiny,d,max_jobs=8,executor=fake)
    assert result['processed']==2 and result['schedule_exhausted']
    assert result['unknown_budget']==2, 'Schedule exhaustion must not certify unknown work'
    saved=Path(d,'checkpoint.json').read_bytes()
    again=run(tiny,d,max_jobs=8,executor=fake)
    assert again['processed']==0 and again['schedule_exhausted'] and len(calls)==before+2
    assert Path(d,'checkpoint.json').read_bytes()==saved
    for ordinal in (-1,True,3):
        state=json.loads(saved);state['next_ordinal']=ordinal
        Path(d,'checkpoint.json').write_text(json.dumps(state))
        try:run(tiny,d,executor=fake)
        except ValueError:pass
        else:raise AssertionError('Invalid checkpoint accepted')
print('FINITE_SCHEDULE_END_AND_NO_REPLAY_OK')
