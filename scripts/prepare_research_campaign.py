"""Prepare an offline, bounded qualification plan; never access the live DB.

This is not a production manifest. Human confirmation and scientific gates
remain required before producing any replacement volunteer campaign.
"""
import argparse
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def prepare():
    target=json.loads((ROOT/'solver/runtime/data/messages/p1030680.json').read_text())
    fixtures=json.loads((ROOT/'tests/fixtures/historical_m4.json').read_text())
    source=next(x for x in fixtures if x['id']=='P1030684')
    # Exact historical windows are hypotheses, never asserted target plaintext.
    # Keep malformed P1030683 text as a control, not a source of corrected cribs.
    windows=[]
    for start in (0,20,40,60,80):
        crib=source['plaintext'][start:start+24]
        if len(crib)!=24:continue
        placements=[off for off in range(72-len(crib)+1)
                    if all(a!=b for a,b in zip(crib,target['ciphertext'][off:]))]
        windows.append(dict(text=crib,source=source['source'],source_start=start,
            legal_clean_offsets=placements,overlap_with_prior_searches='UNVERIFIED',
            evidence='Exact source window; occurrence in target is an untested hypothesis'))
    # Canonical Greek and left rings, all middle/right rings and start positions.
    shells=2*2*8*7*6
    space=shells*26**2*26**4
    hypotheses=sum(len(w['legal_clean_offsets']) for w in windows)
    return dict(schema='enigmagrid-research-proposal-v1',id='p1030680-constrained-v2-proposal',
        state='prepared_not_approved',activation_allowed=False,
        production_changes='NONE; keep p1030680-portable-v1 running',
        engine='bounded_crib_v1',resource='CPU only; no OpenCL qualification claimed',
        target=target['id'],ciphertext=target['ciphertext'],
        ciphertext_sha256=hashlib.sha256(target['ciphertext'].encode()).hexdigest(),
        hypotheses=windows,
        qualification=dict(historical_fixture_ids=[x['id'] for x in fixtures],
            models=['clean','substitution','omission'],crib_lengths=[24,32],
            mechanical_domain_size=128,cables=10,
            scope='Known true mechanical core hidden among finite alternatives; not full-keyspace recovery'),
        work_contract=dict(core_chunk_size=128,nodes_per_core=5000,boards_per_core=64,
            completions_per_board=256,candidate_limit=2048,
            cutoff_result='unknown_budget',deduplication='exact scope hash plus solver version',
            correction_indices='explicit individual hypothesis; never silently repair ciphertext',
            correction_policy='qualify injected errors first; target errors require separately reviewed hypothesis'),
        capped_pilot=dict(purpose='Candidate-rate and runtime pilot, not full-space elimination',
            cores_per_placement=128,total_core_hypothesis_pairs=128*hypotheses,
            sampling_seed='p1030680-constrained-v2-pilot-20261003',
            model='clean',cables=10,execution='not_started; explicit user approval required'),
        full_domain=dict(canonical_cores_per_crib=space,legal_clean_placements=hypotheses,
            core_hypothesis_pairs=space*hypotheses,
            warning='This size is an estimate of scope, not a scheduled or feasible job allocation'),
        promotion_gates=dict(user_confirmation=False,production_worker_integration=False,
            throughput_budget_approved=False,prior_work_overlap_reviewed=False,
            independent_algorithm_review=False),
        next_decision='Review the capped pilot and prior overlap; explicit approval is required before execution; do not import this proposal into production')

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);a=ap.parse_args()
    plan=prepare();Path(a.output).write_text(json.dumps(plan,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'state':plan['state'],'activation_allowed':False,'domain':plan['full_domain']},indent=2))
