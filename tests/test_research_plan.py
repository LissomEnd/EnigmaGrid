"""The proposal is inert, reproducible and not a production campaign manifest."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from prepare_research_campaign import prepare
sys.path.insert(0,str(ROOT/'solver/runtime/src'))
from search.crib_pilot import jobs,core_at,index_of,execute,DOMAIN
from search.c3_models import Key,normalize
from dataclasses import replace
import json
a=prepare();b=prepare()
assert a==b
assert a['state']=='prepared_not_approved' and a['activation_allowed'] is False
assert a['promotion_gates']['user_confirmation'] is False
assert 'campaign' not in a and 'segments' not in a
assert a['full_domain']['canonical_cores_per_crib']==415182802944
assert DOMAIN==415182802944
planned=list(jobs(a))
assert planned==list(jobs(b))
assert len(planned)==a['full_domain']['legal_clean_placements']
assert len({j['id'] for j in planned})==len(planned)
for j in planned:
    assert len(set(j['core_indices']))==128
    assert all(core_at(i).rings.startswith('AA') for i in j['core_indices'])
for i in (0,1,25,26,26**4,DOMAIN//2,DOMAIN-1):assert index_of(core_at(i))==i
fixture=json.loads((ROOT/'tests/fixtures/historical_m4.json').read_text())[0]
truth=Key.from_dict(fixture['key'])
job=dict(engine='bounded_crib_v1',model='clean',ciphertext=fixture['ciphertext'][:72],
    crib=fixture['plaintext'][:32],offset=0,pairs=10,
    core_indices=[index_of(replace(truth,plugboard=()))],budgets=dict(node_limit=5000,board_limit=64,completion_limit=256,candidate_limit=2048))
receipt=execute(job)
assert receipt['complete'] and any(Key.from_dict(c['key'])==normalize(truth) for c in receipt['candidates'])
for item in a['hypotheses']:
    for offset in item['legal_clean_offsets']:
        assert all(x!=y for x,y in zip(item['text'],a['ciphertext'][offset:]))
print('OFFLINE_RESEARCH_PLAN_REPRODUCIBILITY_AND_ACTIVATION_GATES_OK')
