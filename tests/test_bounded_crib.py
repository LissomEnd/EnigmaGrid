"""Bounded unknown-plugboard recovery; deliberately NOT a full-keyspace break."""
import json
import random
import sys
import time
from dataclasses import replace, asdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'solver/runtime/src'))
from search.c3_models import Key, crypt, normalize
from search.bounded_crib import search, completions, observations

# Synthetic naval-style controls, not proposed target cribs or historical quotes.
TEXTS=[
    'ANALLEBOOTEVVVFUNKSPRUCHPRUEFENXPOSITIONMELDENXWETTERBERICHTFOLGTXENDEXABCDE',
    'VVVTESTNACHRICHTXKEINEECHTEANWEISUNGXABCDEFGHIJKLMNOPQRSTUVWXYZXENDEXABCDE',
]

def main():
    partial=list(range(26));partial[:4]=[-1]*4
    boards,cut=completions(partial,2,100)
    assert len(boards)==3 and not cut
    assert completions(partial,2,1)[1]
    assert observations('ABC','omission',1)==[0,None,1,2]
    assert observations('ABC','substitution',1)==[0,None,2]
    rng=random.Random(831039)
    results=[]
    for case, text in enumerate(TEXTS):
        text=(text+'X'*72)[:72]
        abc=list('ABCDEFGHIJKLMNOPQRSTUVWXYZ');rng.shuffle(abc)
        plugs=tuple(''.join(abc[2*i:2*i+2]) for i in range(10))
        truth=Key('Bthin' if case==0 else 'Cthin','Gamma',
            ('IV','III','VIII') if case==0 else ('VI','VII','II'),
            'AACU' if case==0 else 'AAMZ','VYAA' if case==0 else 'QAME',plugs)
        cipher=crypt(text,truth)
        base=replace(truth,plugboard=())
        # Unknown identity among three supplied cores; no plugboard is supplied.
        cores=[base,replace(base,positions='AZZZ'),replace(base,rings='AAZZ')]
        rng.shuffle(cores)
        for model in ('clean','substitution','omission'):
            ix=None if model=='clean' else 17
            observed=cipher
            if model=='substitution':observed=cipher[:17]+('A' if cipher[17]!='A' else 'B')+cipher[18:]
            if model=='omission':observed=cipher[:17]+cipher[18:]
            started=time.perf_counter()
            r=search(observed,text[:48],0,cores,model=model,index=ix)
            found=any(Key.from_dict(c['key'])==normalize(truth) for c in r['candidates'])
            assert found,(case,model,r['status'])
            # Compare all non-missing plaintext independently to the reference.
            for c in r['candidates']:
                k=Key.from_dict(c['key'])
                actual=crypt(text,k)
                if k==normalize(truth):
                    assert all(actual[i]==x for i,x in enumerate(cipher))
            results.append(dict(case=case,model=model,recovered=found,status=r['status'],
                seconds=round(time.perf_counter()-started,4),candidates=len(r['candidates']),scope_hash=r['scope_hash']))
        # Unsatisfiable, wrong-crib control (self encryption forbidden).
        neg=search(cipher,cipher[:48],0,cores)
        assert neg['status']=='complete_negative' and not neg['candidates']
        # Budget exhaustion must never certify a negative.
        limited=search(cipher,text[:8],0,cores,node_limit=1)
        assert limited['status']=='unknown_budget' and not limited['complete']
        # Clean arm must not silently repair an observed mismatch within the crib.
        corrupted=cipher[:17]+('A' if cipher[17]!='A' else 'B')+cipher[18:]
        mismatch=search(corrupted,text[:48],0,[base])
        assert not any(Key.from_dict(c['key'])==normalize(truth) for c in mismatch['candidates'])
    print(json.dumps(dict(scope='synthetic 48-letter crib, 3 mechanical cores, 10 unknown cables; not blind full-key search',
        cases=results,gate='RESEARCH_ONLY: realistic short-crib recovery and broad-keyspace runtime remain unqualified'),indent=2))

if __name__=='__main__':main()
