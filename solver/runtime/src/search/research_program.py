"""Offline long-horizon work program. No production database or network.

An indexed permutation visits mechanical cores without replacement within each
crib/offset hypothesis. A stable prefix survives changes in estimated capacity.
Calendar horizons estimate capacity; they never authorize production compute.
"""
import math
from hashlib import sha256
from search.crib_pilot import DOMAIN
from search.bounded_crib import digest

VERSION='constrained_program_v1'

def hypotheses(proposal):
    rows={(h['text'],o) for h in proposal['hypotheses'] for o in h['legal_clean_offsets']}
    if not rows:raise ValueError('Empty hypothesis set')
    return sorted(rows)

def job_count(proposal, chunk=128):
    if type(chunk) is not int or not 1<=chunk<=128:
        raise ValueError('Invalid chunk')
    return len(hypotheses(proposal))*((DOMAIN+chunk-1)//chunk)

def core_indices(identity, start, count):
    if type(start) is not int or type(count) is not int or start<0 or not 1<=count<=128 or start+count>DOMAIN:
        raise ValueError('Invalid finite range')
    raw=int.from_bytes(sha256(identity.encode()).digest(),'big')
    stride=(raw//DOMAIN)%DOMAIN or 1
    while math.gcd(stride,DOMAIN)!=1:stride+=1
    shift=raw%DOMAIN
    return [(shift+stride*i)%DOMAIN for i in range(start,start+count)]

def job_at(proposal, ordinal, chunk=128):
    if type(ordinal) is not int or ordinal<0 or type(chunk) is not int or not 1<=chunk<=128:
        raise ValueError('Invalid job ordinal/chunk')
    rows=hypotheses(proposal)
    wave,h=divmod(ordinal,len(rows));start=wave*chunk
    if start>=DOMAIN:raise ValueError('Program domain exhausted')
    crib,offset=rows[h]
    identity=digest(dict(version=VERSION,ciphertext=proposal['ciphertext'],crib=crib,offset=offset,pairs=10))
    job=dict(engine='bounded_crib_v1',ciphertext=proposal['ciphertext'],crib=crib,offset=offset,
        core_indices=core_indices(identity,start,min(chunk,DOMAIN-start)),model='clean',pairs=10,
        budgets=dict(node_limit=5000,board_limit=64,completion_limit=256,candidate_limit=2048))
    return dict(job,id=digest(job),program=VERSION,ordinal=ordinal)

def plan(proposal, *, days=90, cores_per_second, concurrent_devices=1, duty_fraction=.1, executions_per_job=2):
    if type(days) is not int or not 1<=days<=365:raise ValueError('Horizon must be 1..365 days')
    if not math.isfinite(cores_per_second) or cores_per_second<=0:raise ValueError('Measured throughput required')
    if type(concurrent_devices) is not int or concurrent_devices<1 or not 0<duty_fraction<=1:
        raise ValueError('Invalid capacity assumption')
    if type(executions_per_job) is not int or executions_per_job<2:
        raise ValueError('Budget must include at least one separate recomputation')
    n=len(hypotheses(proposal));maximum=n*math.ceil(DOMAIN/128)
    effective_rate=cores_per_second*concurrent_devices*duty_fraction/executions_per_job
    count=min(maximum,int(days*86400*effective_rate/128))
    scope=n*DOMAIN;covered=min(scope,count*128)
    return dict(schema=VERSION,horizon_days=days,activation_allowed=False,
        production_changes='NONE',hypotheses=n,estimated_jobs=count,cores_per_job=128,
        capacity_assumptions=dict(cores_per_second=cores_per_second,devices=concurrent_devices,
            duty_fraction=duty_fraction,executions_per_job=executions_per_job),
        coverage=dict(total_core_hypothesis_pairs=scope,scheduled_pairs_upper_bound=covered,
            fraction_upper_bound=covered/scope,
            ideal_full_scope_years=scope/effective_rate/(365.25*86400),
            interpretation='Scheduling coverage only, not solution probability; cutoffs and retries reduce certified coverage'),
        checkpoint='Persist job ID and receipt; resume ordinal, never repeat completed work',
        weekly_review=['Historical recovery on held-out keys','Useful candidate rate and independent replay',
            'Throughput and verifier backlog','Prior-work overlap and hypothesis evidence'],
        stop_conditions=['Regression in historical controls','Resource budget exceeded','Evidence that the hypothesis is invalid'],
        promotion='Requires demonstrated research benefit and compatible tested worker/validator; duration alone is insufficient',
        caveats=['Illustrative capacity, not an ETA or allocated volunteer budget',
            'Permutation has no within-hypothesis repeats; prior external searches still require overlap review',
            'No full-domain exclusion until every core completes without budget cutoffs'])
