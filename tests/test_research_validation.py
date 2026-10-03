"""Untrusted experimental receipts cannot change scope or certify partial work."""
import copy,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'solver/runtime/src')]
from prepare_research_campaign import prepare
from search.research_program import job_at
from search.crib_pilot import execute
from search.research_validation import verify
job=job_at(prepare(),0,chunk=4)
receipt=json.loads(json.dumps(execute(job)))
good=verify(job,receipt)
assert good['computation_matches'] and not good['credit_issued'] and not good['historical_solution']
for field,value in [('scope_hash','wrong'),('nodes',-1),('complete',1),('historical_solution',True),('candidates',[{}]),('extra','unexpected')]:
    altered=copy.deepcopy(receipt);altered[field]=value
    try:verify(job,altered)
    except ValueError:pass
    else:raise AssertionError(field)
try:verify(job_at(prepare(),1,chunk=4),receipt)
except ValueError:pass
else:raise AssertionError('Accepted a different job')
for bad in ([],{'bad':float('nan')},{'bad':'x'*(2*1024*1024+1)}):
    try:verify(job,bad)
    except ValueError:pass
    else:raise AssertionError('Invalid receipt accepted')
class Cancelled(Exception):pass
def stop(done,total):raise Cancelled()
try:verify(job,receipt,checkpoint=stop)
except Cancelled:pass
else:raise AssertionError('Cancelled verifier certified work')
limited=dict(engine='bounded_crib_v1',model='clean',ciphertext='A'*72,crib='B',
    offset=0,core_indices=[0],pairs=10,
    budgets=dict(node_limit=1,board_limit=1,completion_limit=1,candidate_limit=1))
partial=execute(limited)
checked=verify(limited,partial)
assert checked['status']=='unknown_budget' and not checked['complete'] and not checked['credit_issued']
partial.update(complete=True,status='complete_negative')
try:verify(limited,partial)
except ValueError:pass
else:raise AssertionError('Partial search was certified negative')
print('RESEARCH_RECEIPT_RECOMPUTATION_AND_TAMPERING_OK')
