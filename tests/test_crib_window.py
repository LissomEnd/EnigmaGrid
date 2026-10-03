"""Window optimization must preserve stepping and all bounded receipts."""
import sys,random
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'solver/runtime/src'))
from search.c3_models import Key,stream,crypt
from search.bounded_crib import crib_rows,search
rng=random.Random(11203)
for i in range(60):
    letters=lambda: ''.join(rng.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ') for _ in range(4))
    key=Key('Bthin','Gamma',('VI','II','VIII'),letters(),letters())
    offset=rng.randrange(49)
    assert crib_rows(key,offset,24)==stream(key,72,include_plugs=False)[offset:offset+24]
key=Key('Cthin','Beta',('VIII','VII','VI'),'AAZZ','AMMZ')
plain='ABCDEFGHIJKLMNOPQRSTUVWXYZ'*3
cipher=crypt(plain,key)
for model,index,observed in [('clean',None,cipher),('substitution',28,cipher),('omission',28,cipher[:28]+cipher[29:])]:
    args=dict(model=model,index=index,pairs=0)
    fast=search(observed,plain[20:60],20,[key],**args)
    with patch('search.bounded_crib.crib_rows',side_effect=lambda k,o,n:stream(k,o+n,include_plugs=False)[o:]):
        reference=search(observed,plain[20:60],20,[key],**args)
    assert fast==reference and fast['candidates']
print('CRIB_WINDOW_REFERENCE_EQUIVALENCE_OK')
