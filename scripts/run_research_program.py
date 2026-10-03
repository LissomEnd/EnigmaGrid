"""Bounded, resumable OFFLINE program runner; never connects to volunteers.

The state directory is private local output and must not be committed. A stopped
batch can repeat at most its in-flight job. Completed receipts are immutable.
"""
import argparse,json,math,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'solver/runtime/src'))
from search.research_program import job_at,job_count,VERSION
from search.crib_pilot import execute
from search.bounded_crib import digest

class TimeBudgetExpired(Exception):
    """The in-flight job must be retried; it has no completed receipt."""

def atomic(path,value):
    tmp=path.with_suffix('.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        json.dump(value,f,sort_keys=True);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)

def run(proposal,state_dir,*,max_jobs=8,max_seconds=30,executor=execute):
    if type(max_jobs) is not int or not 1<=max_jobs<=10000 or not math.isfinite(max_seconds) or not 0<max_seconds<=3600:
        raise ValueError('Explicit bounded budget required')
    folder=Path(state_dir);folder.mkdir(parents=True,exist_ok=True)
    lock=folder/'runner.lock'
    # Do not steal another process's lock or guess whether a stale run is safe.
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.close(fd)
    try:
        manifest=digest(dict(version=VERSION,proposal=proposal))
        checkpoint=folder/'checkpoint.json'
        state=json.loads(checkpoint.read_text()) if checkpoint.exists() else dict(manifest=manifest,next_ordinal=0)
        if state['manifest']!=manifest:raise ValueError('Proposal changed; use a separate state directory')
        total_jobs=job_count(proposal)
        if type(state['next_ordinal']) is not int or not 0<=state['next_ordinal']<=total_jobs:
            raise ValueError('Invalid checkpoint ordinal')
        start=time.monotonic();processed=0;resumed=0;unknown=0;interrupted=False
        def check_time(done,total):
            if time.monotonic()-start>=max_seconds:raise TimeBudgetExpired()
        while processed+resumed<max_jobs and time.monotonic()-start<max_seconds:
            if state['next_ordinal']==total_jobs:break
            ordinal=state['next_ordinal'];job=job_at(proposal,ordinal)
            path=folder/(job['id']+'.json')
            if path.exists():
                record=json.loads(path.read_text())
                if record['job']!=job or digest(record['receipt'])!=record['receipt_hash']:
                    raise ValueError('Stored receipt integrity mismatch')
                resumed+=1
            else:
                try:
                    receipt=executor(job,checkpoint=check_time)
                    check_time(0,0)
                except TimeBudgetExpired:
                    interrupted=True
                    break
                record=dict(job=job,receipt=receipt,receipt_hash=digest(receipt))
                atomic(path,record);processed+=1
            unknown+=int(not record['receipt']['complete'])
            state['next_ordinal']=ordinal+1;atomic(checkpoint,state)
        return dict(processed=processed,resumed=resumed,unknown_budget=unknown,
            next_ordinal=state['next_ordinal'],seconds=time.monotonic()-start,
            production_changed=False,interrupted_job=interrupted,
            schedule_exhausted=state['next_ordinal']==total_jobs,total_jobs=total_jobs,
            exhaustion_note='All scheduled jobs visited does not certify coverage: inspect unknown/cutoff receipts',
            budget_note='Time checked between mechanical cores; one bounded core and checkpoint I/O may overshoot')
    finally:lock.unlink()

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--proposal',required=True);ap.add_argument('--state-dir',required=True)
    ap.add_argument('--max-jobs',type=int,default=8);ap.add_argument('--max-seconds',type=float,default=30)
    a=ap.parse_args();print(json.dumps(run(json.loads(Path(a.proposal).read_text()),a.state_dir,
        max_jobs=a.max_jobs,max_seconds=a.max_seconds),indent=2))
