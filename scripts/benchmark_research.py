"""Reproducible bounded pilots. Does not connect to or change the grid."""
import argparse
import json
import random
import sys
import time
from pathlib import Path
from dataclasses import replace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'solver/runtime/src'))
sys.path.insert(0,str(ROOT/'tests'))
from numba import set_num_threads
from test_bounded_crib import TEXTS
from search.c3_models import Key, crypt, normalize
from search.bounded_crib import search as constrained
from search.portable_standard import search as standard
from search.portable_search import search as event

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);args=ap.parse_args()
    set_num_threads(1)
    rng=random.Random(8342)
    key=Key('Bthin','Gamma',('IV','III','VIII'),'AACU','VYAA',tuple('CH EJ NV OU TY LG SZ PK DI QB'.split()))
    cipher=crypt((TEXTS[0]+'X'*72)[:72],key)
    standard(cipher,987,count=2,iterations=1);event(cipher,987,count=2,iterations=1)
    blind=[];cribs=[];negatives=[]
    for case,text in enumerate(TEXTS):
        text=(text+'X'*72)[:72];cipher=crypt(text,key)
        for name,fn,extra in [('standard',standard,{}),('event_v1',event,{'min_pairs':4,'max_pairs':10})]:
            for seed in (91601,91602,91603):
                started=time.perf_counter()
                hits=fn(cipher,seed,count=256,iterations=128,topk=8,**extra)
                blind.append(dict(case=case,engine=name,seed=seed,recovered=any(h['plaintext']==text for h in hits),seconds=time.perf_counter()-started))
        cores=[replace(key,plugboard=())]+[Key('Bthin','Gamma',('IV','III','VIII'),'AACU',''.join(rng.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ',k=4))) for _ in range(31)]
        rng.shuffle(cores)
        for length in (16,24,32):
            started=time.perf_counter()
            r=constrained(cipher,text[:length],0,cores,node_limit=3000,completion_limit=64)
            cribs.append(dict(case=case,crib_length=length,core_count=32,
                recovered=any(Key.from_dict(c['key'])==normalize(key) for c in r['candidates']),
                status=r['status'],candidates=len(r['candidates']),seconds=time.perf_counter()-started,scope_hash=r['scope_hash']))
        # Stronger nulls deliberately avoid the trivial self-encryption filter.
        for trial in range(5):
            null=''.join(rng.choice([c for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' if i>=24 or c!=text[i]]) for i in range(72))
            r=constrained(null,text[:24],0,cores,node_limit=3000,completion_limit=64)
            negatives.append(dict(case=case,trial=trial,status=r['status'],candidates=len(r['candidates']),visited_cores=r['visited_cores']))
    result=dict(scope='Synthetic bounded pilot, not historical target recovery or full-keyspace qualification',
        blind_budget='256 trajectories x 128 iterations per trial; equal counts, unequal wall time; JIT warmup excluded',
        blind=blind,constrained=cribs,negatives=negatives,
        production_gate='NOT_QUALIFIED: representative historical held-out corpus, broad-domain throughput, fair equal-time comparison and independent review still required')
    Path(args.output).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(blind_recoveries=sum(r['recovered'] for r in blind),blind_trials=len(blind),
        constrained_recoveries=sum(r['recovered'] for r in cribs),constrained_trials=len(cribs),
        null_candidates=sum(r['candidates'] for r in negatives),null_unknown=sum(r['status']=='unknown_budget' for r in negatives),
        gate=result['production_gate']),indent=2))

if __name__=='__main__':main()
