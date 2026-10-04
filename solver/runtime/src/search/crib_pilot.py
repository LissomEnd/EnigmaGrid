"""Offline deterministic pilot jobs; no database, network or worker routing."""
from hashlib import sha256
from itertools import permutations
from search.c3_models import Key, normalize
from search.bounded_crib import search, digest

ROTORS=('I','II','III','IV','V','VI','VII','VIII')
ORDERS=tuple(permutations(ROTORS,3))
DOMAIN=4*len(ORDERS)*26**6

def core_at(index):
    if type(index) is not int or not 0<=index<DOMAIN:raise ValueError('Core index out of domain')
    values=[]
    for _ in range(6):
        values.append(index%26);index//=26
    order=ORDERS[index%len(ORDERS)];index//=len(ORDERS)
    return Key(('Bthin','Cthin')[index//2],('Beta','Gamma')[index%2],order,
        'AA'+''.join(chr(65+x) for x in values[4:6]),''.join(chr(65+x) for x in values[:4]))

def index_of(core):
    if core.plugboard:raise ValueError('Mechanical core only')
    k=normalize(core)
    prefix=(('Bthin','Cthin').index(k.reflector)*2+('Beta','Gamma').index(k.greek))*len(ORDERS)+ORDERS.index(k.moving_rotors)
    for c in reversed(k.positions+k.rings[2:]):prefix=prefix*26+ord(c)-65
    return prefix

def jobs(plan):
    if plan.get('schema')!='enigmagrid-research-proposal-v1':raise ValueError('Unsupported proposal')
    count=plan['capped_pilot']['cores_per_placement']
    if type(count) is not int or not 1<=count<=128:raise ValueError('Unbounded pilot')
    for h in plan['hypotheses']:
        for offset in h['legal_clean_offsets']:
            indices=[];seen=set();counter=0
            # Rejection sampling removes modulo bias; duplicate cores are skipped.
            ceiling=(1<<256)//DOMAIN*DOMAIN
            while len(indices)<count:
                raw=int.from_bytes(sha256(f"{plan['capped_pilot']['sampling_seed']}|{h['text']}|{offset}|{counter}".encode()).digest(),'big');counter+=1
                if raw>=ceiling:continue
                index=raw%DOMAIN
                if index not in seen:indices.append(index);seen.add(index)
            job=dict(engine='bounded_crib_v1',ciphertext=plan['ciphertext'],crib=h['text'],offset=offset,
                core_indices=indices,model='clean',pairs=10,
                budgets=dict(node_limit=5000,board_limit=64,completion_limit=256,candidate_limit=2048))
            yield dict(job,id=digest(job))

def validate_job(job):
    if not isinstance(job,dict):raise ValueError('Job must be an object')
    if job.get('engine')!='bounded_crib_v1' or job.get('model')!='clean':raise ValueError('Unsupported pilot')
    for name in ('ciphertext','crib'):
        text=job.get(name)
        if not isinstance(text,str) or not 1<=len(text)<=72 or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' for c in text):
            raise ValueError('Invalid '+name)
    offset=job.get('offset')
    if type(offset) is not int or not 0<=offset<=len(job['ciphertext'])-len(job['crib']):raise ValueError('Invalid offset')
    indices=job.get('core_indices')
    if not isinstance(indices,list) or not 1<=len(indices)<=128 or any(type(i) is not int or not 0<=i<DOMAIN for i in indices):
        raise ValueError('Invalid bounded domain')
    if len(set(indices))!=len(indices):raise ValueError('Duplicate cores')
    if type(job.get('pairs')) is not int or not 0<=job['pairs']<=13:raise ValueError('Invalid cable count')
    limits=dict(node_limit=5000,board_limit=64,completion_limit=256,candidate_limit=2048)
    budgets=job.get('budgets')
    if not isinstance(budgets,dict) or set(budgets)!=set(limits) or any(type(budgets[k]) is not int or not 1<=budgets[k]<=v for k,v in limits.items()):
        raise ValueError('Invalid work budget')
    if 'id' in job:
        body={k:v for k,v in job.items() if k not in ('id','program','ordinal')}
        if digest(body)!=job['id']:raise ValueError('Job identity mismatch')

def execute(job,checkpoint=None,solve_map=None):
    validate_job(job)
    return search(job['ciphertext'],job['crib'],job['offset'],[core_at(i) for i in job['core_indices']],
        model='clean',pairs=job['pairs'],checkpoint=checkpoint,solve_map=solve_map,**job['budgets'])
