"""Independent enumeration of every zero/one-cable board on finite cores.

The oracle uses reference electrical rows, never CSP propagation, its completion
routine or statistical pruning. This checks small domains, not a full M4 break.
"""
import sys,random,json
from dataclasses import replace,asdict
from itertools import combinations
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'solver/runtime/src'))
from search.c3_models import Key,stream,normalize,crypt
from search.bounded_crib import search

def identity(key):return json.dumps(asdict(normalize(key)),sort_keys=True)
rng=random.Random(1030680);cases=0
for trial in range(4):
    base=Key(rng.choice(('Bthin','Cthin')),rng.choice(('Beta','Gamma')),
        tuple(rng.sample(('I','II','III','IV','V','VI','VII','VIII'),3)),
        'AA'+''.join(rng.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ',k=2)),
        ''.join(rng.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ',k=4)))
    cores=[base,replace(base,positions='AMMZ')]
    for pairs in (0,1):
        plain='TESTNACHRICHT';cipher=crypt(plain,replace(base,plugboard=('AZ',) if pairs else ()))
        for model in ('clean','substitution','omission'):
            ix=None if model=='clean' else 5
            observed=cipher if model!='omission' else cipher[:5]+cipher[6:]
            obs=[ord(c)-65 for c in observed]
            if model=='omission':obs.insert(5,None)
            if model=='substitution':obs[5]=None
            offset=3;crib=plain[offset:offset+4];expected=set()
            for core in cores:
                rows=stream(core,len(obs),include_plugs=False)
                options=combinations(range(26),2) if pairs else [None]
                for pair in options:
                    board=list(range(26));plugs=()
                    if pair:
                        a,b=pair;board[a]=b;board[b]=a;plugs=(chr(65+a)+chr(65+b),)
                    if all(obs[offset+j] is None or
                        board[rows[offset+j][board[obs[offset+j]]]]==ord(letter)-65
                        for j,letter in enumerate(crib)):
                        expected.add(identity(replace(core,plugboard=plugs)))
            result=search(observed,crib,offset,cores,model=model,index=ix,pairs=pairs,
                node_limit=100000,board_limit=10000,completion_limit=10000,candidate_limit=10000)
            actual={identity(Key.from_dict(c['key'])) for c in result['candidates']}
            assert result['complete'] and actual==expected,(trial,pairs,model,len(actual),len(expected))
            cases+=1
print(f'EXHAUSTIVE_SMALL_DOMAIN_ORACLE_OK: {cases} cases')
