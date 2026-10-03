"""Offline diagnostic: known mechanical core, no plaintext-guided selection."""
import argparse, hashlib, json, sys, time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'solver/runtime/src'))
from search.c3_models import Key,stream,board,crypt
from search.portable_search import QTAB_INT
args=argparse.ArgumentParser()
args.add_argument('--trigrams',type=Path)
args.add_argument('--bigrams',type=Path,help='Enable IC/bigram/trigram stages; requires --trigrams')
args.add_argument('--variable-cables',action='store_true',help='Test remove-and-connect neighbors with at most ten cables')
args.add_argument('--output',type=Path,required=True)
options=args.parse_args()
if options.bigrams and not options.trigrams:args.error('--bigrams requires --trigrams')
BI=None
if options.bigrams:
    counts={p[0]:int(p[1]) for line in options.bigrams.read_text().splitlines() if len(p:=line.split())==2}
    assert all(len(k)==2 and k.isascii() and k.isalpha() and k.isupper() and v>=0 for k,v in counts.items())
    total=sum(counts.values()); BI=np.full(676,-np.log10(.01/total))
    for k,v in counts.items():
        if v:BI[(ord(k[0])-65)*26+ord(k[1])-65]=-np.log10(v/total)
    BI=np.rint(BI*1000).astype(np.int32)
TRI=None
if options.trigrams:
    counts={p[0]:int(p[1]) for line in options.trigrams.read_text().splitlines() if len(p:=line.split())==2}
    assert all(len(k)==3 and k.isascii() and k.isalpha() and k.isupper() and v>=0 for k,v in counts.items())
    total=sum(counts.values())
    TRI=np.full(26**3,-np.log10(.01/total))
    for k,v in counts.items():
        if v:TRI[(ord(k[0])-65)*676+(ord(k[1])-65)*26+ord(k[2])-65]=-np.log10(v/total)
    TRI=np.rint(TRI*1000).astype(np.int32)

def probe(f):
    # The mechanical key is deliberately supplied. Never call this blind recovery.
    k=Key.from_dict({**f['key'],'plugboard':[]})
    rows=np.array(stream(k,72,include_plugs=False),dtype=np.int32)
    cipher=np.array([ord(x)-65 for x in f['ciphertext'][:72]])
    permutations=[]
    for a in range(26):
        for b in range(a+1,26):
            p=np.arange(26);p[a],p[b]=b,a;permutations.append(p)
    swaps=np.array(permutations)
    def evaluate(boards,stage='final'):
        inner=boards[:,cipher]
        mid=rows[np.arange(72)[None,:],inner]
        out=np.take_along_axis(boards,mid,axis=1)
        if stage=='ic':
            frequencies=np.stack([(out==letter).sum(axis=1) for letter in range(26)],axis=1)
            return -(frequencies*(frequencies-1)).sum(axis=1),out
        if stage=='bi':return BI[out[:,:-1]*26+out[:,1:]].sum(axis=1),out
        if TRI is not None:
            ids=(out[:,:-2]*26+out[:,1:-1])*26+out[:,2:]
            return TRI[ids].sum(axis=1),out
        ids=((out[:,:-3]*26+out[:,1:-2])*26+out[:,2:-1])*26+out[:,3:]
        return QTAB_INT[ids].sum(axis=1),out
    # Test vectorized scoring/decryption against reference, before optimization.
    truth=np.array(board(f['key']['plugboard']))
    truth_scores,decoded=evaluate(truth[None,:])
    assert ''.join(chr(65+int(x)) for x in decoded[0])==crypt(f['ciphertext'][:72],Key.from_dict(f['key']))
    rng=np.random.default_rng(20261003)
    best=None; evaluations=0; cpu_work=0.; started=time.monotonic()
    for restart in range(16):
        p=np.arange(26); order=rng.permutation(26)
        cables=restart%11 if options.variable_cables else 10
        for a,b in order[:2*cables].reshape(cables,2):p[a],p[b]=b,a
        stage_index=0; stage_round=0; stages=['ic','bi','final'] if BI is not None else ['final']
        for iteration in range(64*len(stages)):
            tick=time.monotonic()
            candidates=np.take_along_axis(swaps,p[swaps],axis=1)
            if options.variable_cables:
                changes=[]
                for a in range(26):
                    for b in range(a+1,26):
                        q=p.copy();pa,pb=int(p[a]),int(p[b])
                        q[a]=a;q[pa]=pa;q[b]=b;q[pb]=pb
                        if pa!=b:q[a]=b;q[b]=a
                        if np.count_nonzero(q!=np.arange(26))<=20:changes.append(q)
                # Retain conjugation neighbors too: they can rewire two cables
                # without reducing cable count and preserve graph connectivity.
                candidates=np.concatenate([candidates,np.array(changes)])
            candidates=np.concatenate([p[None,:],candidates])
            assert np.all(np.take_along_axis(candidates,candidates,axis=1)==np.arange(26))
            counts=np.count_nonzero(candidates!=np.arange(26),axis=1)
            assert np.all(counts<=20) if options.variable_cables else np.all(counts==20)
            scores,texts=evaluate(candidates,stages[stage_index]);evaluations+=len(candidates)
            win=int(np.argmin(scores));p=candidates[win].copy()
            if stages[stage_index]=='final' and (best is None or int(scores[win])<best['cost']):
                best=dict(cost=int(scores[win]),plaintext=''.join(chr(65+int(x)) for x in texts[win]),restart=restart,iteration=iteration)
            elapsed=time.monotonic()-tick;cpu_work+=elapsed
            time.sleep(elapsed*9) # Approximate 10% duty on this one-thread probe.
            stage_round+=1
            if win==0 or stage_round==64:
                if stage_index==len(stages)-1:break
                stage_index+=1;stage_round=0
    return dict(id=f['id'],seed=20261003,restarts=16,neighbors='conjugations plus remove/connect; zero to ten cables' if options.variable_cables else 'all 325 letter conjugations; exactly ten cables',
        evaluations=evaluations,compute_section_seconds=cpu_work,elapsed_seconds=time.monotonic()-started,
        best=best,true_plaintext_cost=int(truth_scores[0]),
        objective_prefers_truth=int(truth_scores[0])<best['cost'],
        recovered=best['plaintext']==f['plaintext'][:72],known_core=True)

fixtures=json.loads((ROOT/'tests/fixtures/historical_m4.json').read_text())
fixtures+=json.loads((ROOT/'tests/fixtures/historical_m4_independent.json').read_text())
report=dict(scope='Known-core diagnostic only. Plaintext and true plugboard used for oracle check and final evaluation, never search selection. Two messages share a daily key. No production changes.',results=[probe(f) for f in fixtures])
report['model']='1941 military trigrams, log counts with .01 unseen floor' if TRI is not None else 'generic German quadgrams'
report['stages']=['ic','bi','final'] if BI is not None else ['final']
if options.bigrams:report['bigram_sha256']=hashlib.sha256(options.bigrams.read_bytes()).hexdigest()
report['scope']='Known-core diagnostic only; no plaintext-guided search selection. Four messages, three daily keys. No production changes. Absolute costs cannot be compared across models.'
table_path=options.trigrams or ROOT/'solver/runtime/data/language/german_quadgrams.txt'
report['table_sha256']=hashlib.sha256(table_path.read_bytes()).hexdigest()
options.output.write_text(json.dumps(report,indent=2))
print(json.dumps(report))

