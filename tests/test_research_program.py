"""Long programs retain stable prefixes and never wrap a finite domain."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'solver/runtime/src')]
from prepare_research_campaign import prepare
from search.research_program import core_indices,job_at,plan,hypotheses
from search.crib_pilot import DOMAIN,execute
p=prepare();n=len(hypotheses(p));seen=set()
for wave in range(100):
    job=job_at(p,wave*n)
    assert not seen.intersection(job['core_indices'])
    seen.update(job['core_indices'])
assert len(seen)==12800
assert job_at(p,13)==job_at(p,13)
assert core_indices('test',0,128)==core_indices('test',0,64)+core_indices('test',64,64)
assert len(core_indices('test',DOMAIN-1,1))==1
for bad in (-1,DOMAIN):
    try:core_indices('test',bad,128)
    except ValueError:pass
    else:raise AssertionError('Range wrapped')
a=plan(p,days=90,cores_per_second=250);b=plan(p,days=180,cores_per_second=250)
assert b['estimated_jobs']==a['estimated_jobs']*2
assert not a['activation_allowed'] and a['production_changes']=='NONE'
receipt=execute(job_at(p,0,chunk=4))
assert receipt['core_count']==4 and receipt['complete']
print('LONG_HORIZON_PREFIX_AND_NONOVERLAP_OK')
