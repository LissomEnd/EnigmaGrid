"""Bounded public work envelope. Capability is enabled only by integrated clients."""
from search.crib_pilot import execute, validate_job
from search.bounded_crib import digest
from functools import lru_cache
import json

CAPABILITY = 'bounded_crib_v1'


@lru_cache(maxsize=128)
def _receipt_core_json(indices):
    """Cache only deterministic assigned cores, never a validation decision.

    Intake and promotion inspect the same unit repeatedly. Immutable serialized
    values keep callers from changing cached scope data; the bounded cache holds
    at most two full transport batches of core sets.
    """
    from dataclasses import asdict
    from search.crib_pilot import core_at
    cores = {}
    for index in indices:
        # Indexed cores already have AA in the two normalized ring positions
        # and an empty plugboard. Re-normalizing constructs and validates a
        # second identical Key for each core; candidate keys still require the
        # general normalization below when checking domain membership.
        core = asdict(core_at(index))
        cores[digest(core)] = core
    return json.dumps(cores, sort_keys=True, separators=(',', ':'))


def validate_envelope(lease):
    if lease.get('engine') != CAPABILITY:
        raise ValueError('Unsupported constrained engine')
    start, end = lease.get('start_unit'), lease.get('end_unit')
    if type(start) is not int or type(end) is not int or start < 0 or end != start + 1:
        raise ValueError('Constrained leases require exactly one unit')
    cfg = lease.get('config')
    if not isinstance(cfg, dict) or set(cfg) not in ({'job', 'requires'},{'program','requires'}):
        raise ValueError('Invalid constrained configuration')
    if cfg['requires'] != ['cpu', CAPABILITY]:
        raise ValueError('Constrained capability required')
    if 'program' in cfg:
        from search.research_program import job_at
        program=cfg['program']
        if not isinstance(program,dict) or set(program)!={'ciphertext','hypotheses','chunk','ordinal_base','candidate_limit'}:
            raise ValueError('Invalid program fields')
        if type(program['ordinal_base']) is not int or program['ordinal_base']<0:
            raise ValueError('Invalid program base')
        if type(program['candidate_limit']) is not int or not 1<=program['candidate_limit']<=32:
            raise ValueError('Invalid program candidate limit')
        rows=program['hypotheses']
        if not isinstance(rows,list) or not 1<=len(rows)<=128:
            raise ValueError('Invalid program hypotheses')
        for h in rows:
            if not isinstance(h,dict) or set(h)!={'text','legal_clean_offsets'}:
                raise ValueError('Invalid hypothesis fields')
            if not isinstance(h['text'],str) or not 1<=len(h['text'])<=72 or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' for c in h['text']):
                raise ValueError('Invalid program crib')
            if not isinstance(h['legal_clean_offsets'],list) or not 1<=len(h['legal_clean_offsets'])<=72 or any(type(o) is not int or not 0<=o<=72-len(h['text']) for o in h['legal_clean_offsets']):
                raise ValueError('Invalid program offsets')
        job=job_at(program,program['ordinal_base']+start,chunk=program['chunk'])
        job['budgets']['candidate_limit']=program['candidate_limit']
        job['id']=digest({k:v for k,v in job.items() if k not in ('id','program','ordinal')})
    else:
        job = cfg['job']
    validate_job(job)
    allowed = {'engine','ciphertext','crib','offset','core_indices','model','pairs','budgets','id','program','ordinal'}
    if set(job) - allowed:
        raise ValueError('Unexpected job fields')
    return job


def run(lease, checkpoint=None, solve_map=None):
    job = validate_envelope(lease)
    receipt = execute(job, checkpoint=checkpoint, solve_map=solve_map)
    # Preserve unknown_budget verbatim: submission is not proof of elimination.
    body = {k: v for k, v in job.items() if k not in ('id','program','ordinal')}
    return {'summary': {'engine': CAPABILITY, 'units': 1,
                        'job_hash': digest(body), 'status': receipt['status'],
                        'exhaustive_within_scope': receipt['complete']},
            'receipt': receipt}


def verify_result(lease, supplied, checkpoint=None):
    """Offline full reproduction; never invoke inside a database transaction."""
    from search.research_validation import canonical
    validate_envelope(lease)
    if not isinstance(supplied,dict) or set(supplied)!={'summary','receipt'}:
        raise ValueError('Invalid constrained result envelope')
    encoded=canonical(supplied)
    expected=run(lease,checkpoint=checkpoint)
    if encoded!=canonical(expected):
        raise ValueError('Constrained result does not match recomputation')
    return expected,digest(expected)


def validate_receipt_shape(lease, supplied):
    """Bounded intake only. Consensus/full reproduction must follow acceptance."""
    from dataclasses import asdict, replace
    from hashlib import sha256
    from search.crib_pilot import core_at
    from search.c3_models import normalize, Key, stream
    from search.research_validation import canonical
    job=validate_envelope(lease)
    canonical(supplied)
    if not isinstance(supplied,dict) or set(supplied)!={'summary','receipt'}:
        raise ValueError('Invalid constrained result envelope')
    r=supplied['receipt']
    fields={'engine','scope_hash','cipher_sha256','status','complete','historical_solution',
            'core_count','visited_cores','nodes','candidates','budgets','model','index','crib','offset','pairs'}
    if not isinstance(r,dict) or set(r)!=fields:
        raise ValueError('Invalid receipt fields')
    cores=json.loads(_receipt_core_json(tuple(job['core_indices'])))
    scope=dict(engine=CAPABILITY,ciphertext=job['ciphertext'],crib=job['crib'],offset=job['offset'],
               model='clean',index=None,pairs=job['pairs'],cores=[cores[h] for h in sorted(cores)])
    fixed=dict(engine=CAPABILITY,scope_hash=digest(scope),cipher_sha256=sha256(job['ciphertext'].encode()).hexdigest(),
               core_count=len(cores),historical_solution=False,model='clean',index=None,
               crib=job['crib'],offset=job['offset'],pairs=job['pairs'],
               budgets=dict(nodes_per_core=job['budgets']['node_limit'],boards_per_core=job['budgets']['board_limit'],
                            completions_per_board=job['budgets']['completion_limit'],candidates=job['budgets']['candidate_limit']))
    if any(canonical({'value':r[k]})!=canonical({'value':v}) for k,v in fixed.items()):
        raise ValueError('Receipt scope does not match assigned job')
    if type(r['visited_cores']) is not int or not 0<=r['visited_cores']<=len(cores):
        raise ValueError('Invalid visited count')
    if type(r['nodes']) is not int or not 0<=r['nodes']<=len(cores)*(job['budgets']['node_limit']+1):
        raise ValueError('Invalid node count')
    if not isinstance(r['candidates'],list) or len(r['candidates'])>job['budgets']['candidate_limit']:
        raise ValueError('Invalid candidate count')
    seen=set()
    for candidate in r['candidates']:
        if not isinstance(candidate,dict) or set(candidate)!={'key','plaintext','unknown_slots'} or candidate['unknown_slots']!=[]:
            raise ValueError('Invalid clean candidate')
        raw=candidate['key']
        if not isinstance(raw,dict) or set(raw)!={'reflector','greek','moving_rotors','rings','positions','plugboard'}:
            raise ValueError('Invalid candidate key fields')
        try:key=Key.from_dict(raw)
        except (ValueError,TypeError,KeyError) as exc:raise ValueError('Invalid candidate key') from exc
        if len(key.plugboard)!=job['pairs'] or digest(asdict(normalize(replace(key,plugboard=())))) not in cores:
            raise ValueError('Candidate outside assigned domain')
        rows=stream(key,len(job['ciphertext']))
        plain=''.join(chr(65+rows[i][ord(c)-65]) for i,c in enumerate(job['ciphertext']))
        if candidate['plaintext']!=plain or plain[job['offset']:job['offset']+len(job['crib'])]!=job['crib']:
            raise ValueError('Candidate replay mismatch')
        identity=digest(raw)
        if identity in seen:raise ValueError('Duplicate candidate key')
        seen.add(identity)
    expected_status=('complete_candidates' if r['candidates'] else 'complete_negative') if r['complete'] is True else 'unknown_budget'
    if type(r['complete']) is not bool or r['status']!=expected_status:
        raise ValueError('Inconsistent completion status')
    conflict=any(a==b for a,b in zip(job['crib'],job['ciphertext'][job['offset']:]))
    if r['complete'] and not conflict and r['visited_cores']!=len(cores):
        raise ValueError('Unvisited domain marked complete')
    body={k:v for k,v in job.items() if k not in ('id','program','ordinal')}
    summary=dict(engine=CAPABILITY,units=1,job_hash=digest(body),status=r['status'],exhaustive_within_scope=r['complete'])
    if canonical(supplied['summary'])!=canonical(summary):
        raise ValueError('Summary does not match receipt')
    return supplied,digest(supplied)
