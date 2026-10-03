"""Small equal-wall-time blind comparison; no inference about full keyspace."""
import argparse,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'solver/runtime/src'))
from numba import set_num_threads
from search.portable_standard import search as clean
from search.portable_search import search as event

def run(seconds):
    set_num_threads(1)
    fixtures=json.loads((ROOT/'tests/fixtures/historical_m4.json').read_text())
    text=fixtures[0]['ciphertext'][:72]
    clean(text,888,count=8,iterations=8);event(text,888,count=8,iterations=8)
    rows=[]
    for f in fixtures:
        for repeat in range(3):
            methods=[('clean',clean,{}),('event_v1',event,dict(min_pairs=4,max_pairs=10))]
            if repeat%2:methods.reverse()
            for name,fn,kwargs in methods:
                start=time.perf_counter();batches=0;found=False
                while time.perf_counter()-start < seconds:
                    hits=fn(f['ciphertext'][:72],900000+repeat*100000+batches*256,count=32,iterations=32,**kwargs)
                    found|=any(h['plaintext']==f['plaintext'][:72] for h in hits)
                    batches+=1
                rows.append(dict(id=f['id'],repeat=repeat,method=name,recovered=found,
                    seconds=time.perf_counter()-start,batches=batches,trajectories=batches*32))
    return dict(scope='Two historical 72-letter prefixes; blind search, no key/crib supplied. Same wall-time budget, bounded one-batch overshoot. Shared daily key limits independence.',
        budget_seconds=seconds,iterations_per_trajectory=32,results=rows)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--seconds',type=float,default=2);ap.add_argument('--output',required=True);a=ap.parse_args()
    if not 0<a.seconds<=30:raise SystemExit('Budget must be within 0..30 seconds per trial')
    result=run(a.seconds);Path(a.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'trials':len(result['results']),'recoveries':sum(r['recovered'] for r in result['results'])}))
