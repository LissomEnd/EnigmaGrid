"""Experimental server validator is explicit opt-in and bound to its lease."""
import sys,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'server'),str(ROOT/'scripts'),str(ROOT/'solver/runtime/src')]
from validator import validate_result
from prepare_research_campaign import prepare
from search.research_program import job_at
from search.crib_pilot import execute
job=job_at(prepare(),0,chunk=4)
lease=dict(start_unit=0,end_unit=1,config=dict(research_job=job))
result=dict(receipt=execute(job))
try:validate_result('bounded_crib_v1',result,lease)
except ValueError as exc:assert str(exc)=='unsupported_engine'
else:raise AssertionError('Experimental engine accepted without opt-in')
clean,fp=validate_result('bounded_crib_v1',result,lease,allow_experimental=True)
assert clean==result and len(fp)==64
wrong=copy.deepcopy(lease);wrong['config']['research_job']=job_at(prepare(),1,chunk=4)
for bad in (wrong,dict(lease,end_unit=2),dict(lease,start_unit=False)):
    try:validate_result('bounded_crib_v1',result,bad,allow_experimental=True)
    except ValueError:pass
    else:raise AssertionError('Mismatched lease accepted')
print('RESEARCH_SERVER_OPT_IN_AND_LEASE_BINDING_OK')
