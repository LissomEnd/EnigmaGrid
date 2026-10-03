"""Post-implementation historical controls, bounded domain; never full-key claims."""
import json
import random
import sys
import time
from pathlib import Path
from dataclasses import replace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'solver/runtime/src'))
from search.c3_models import Key,crypt,normalize
from search.bounded_crib import search
from reference.enigma_m4 import crypt as independent

def run():
    results=[];rng=random.Random(20261003)
    fixtures=json.loads((ROOT/'tests/fixtures/historical_m4.json').read_text())
    for fixture in fixtures:
        truth=Key.from_dict(fixture['key'])
        full=fixture['ciphertext'];published=fixture['plaintext']
        assert crypt(full,truth)==published
        assert independent(full,truth.reflector,truth.greek,truth.moving_rotors,truth.positions,truth.rings,truth.plugboard)==published
        cores=[replace(truth,plugboard=())]
        for _ in range(127):
            cores.append(Key(rng.choice(['Bthin','Cthin']),rng.choice(['Beta','Gamma']),
                tuple(rng.sample(['I','II','III','IV','V','VI','VII','VIII'],3)),
                'AA'+''.join(rng.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ',k=2)),
                ''.join(rng.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ',k=4))))
        rng.shuffle(cores)
        cipher=full[:72];plain=published[:72]
        for length in (24,32):
            for model in ('clean','substitution','omission'):
                at=None if model=='clean' else 17
                observed=cipher
                if model=='substitution':observed=cipher[:17]+('Z' if cipher[17]!='Z' else 'A')+cipher[18:]
                if model=='omission':observed=cipher[:17]+cipher[18:]
                start=time.perf_counter()
                receipt=search(observed,plain[:length],0,cores,model=model,index=at,
                    node_limit=5000,completion_limit=256,candidate_limit=2048)
                hits=[c for c in receipt['candidates'] if Key.from_dict(c['key'])==normalize(truth)]
                assert hits,(fixture['id'],length,model,receipt['status'])
                assert receipt['complete'],receipt['status']
                results.append(dict(id=fixture['id'],crib_length=length,model=model,recovered=True,
                    candidates=len(receipt['candidates']),seconds=round(time.perf_counter()-start,4),
                    scope_hash=receipt['scope_hash']))
    return dict(scope='Two historical messages sharing a daily key, 72-letter prefixes; true core hidden among 128 supplied mechanical configurations; unknown ten-cable plugboard. Corruptions are injected test cases, not source claims.',results=results)

if __name__=='__main__':print(json.dumps(run(),indent=2))
