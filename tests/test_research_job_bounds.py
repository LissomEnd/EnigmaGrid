"""Reject altered/unbounded work before search; cancellation cannot certify it."""
import copy,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'solver/runtime/src')]
from prepare_research_campaign import prepare
from search.research_program import job_at
from search.crib_pilot import execute,validate_job
job=job_at(prepare(),0,chunk=4)
for field,bad in [('core_indices',[]),('core_indices',[True]),('core_indices',[0,0]),('offset',True),('pairs',-1),('ciphertext','A'*73),('budgets',{'node_limit':10**12})]:
    altered=copy.deepcopy(job);altered[field]=bad
    try:validate_job(altered)
    except ValueError:pass
    else:raise AssertionError(field)
altered=copy.deepcopy(job);altered['offset']+=1
try:validate_job(altered)
except ValueError:pass
else:raise AssertionError('Identity mismatch accepted')
class Cancelled(Exception):pass
def cancel(done,total):raise Cancelled()
try:execute(job,checkpoint=cancel)
except Cancelled:pass
else:raise AssertionError('Cancelled work returned a receipt')
visited=[]
def cancel_after_core(done,total):
    visited.append(done)
    if done==1:raise Cancelled()
try:execute(job,checkpoint=cancel_after_core)
except Cancelled:pass
else:raise AssertionError('Partially evaluated work returned a receipt')
assert visited==[0,1]
progress=[]
a=execute(job,checkpoint=lambda done,total:progress.append((done,total)))
assert a==execute(job) and progress[0]==(0,4) and progress[-1]==(4,4)
print('RESEARCH_JOB_BOUNDS_IDENTITY_AND_CANCELLATION_OK')
