"""Replay published indicator examples; do not use failed decrypts as cribs.

Sources:
https://enigma.hoerenberg.com/index.php?cat=Unbroken&page=P1030680
https://enigma.hoerenberg.com/index.php?cat=The+U534+messages&page=The+Kenngruppen+System
"""
import json,sys
from dataclasses import replace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'solver/runtime/src'))
from search.c3_models import Key,crypt
raw=json.loads((ROOT/'tests/fixtures/historical_m4.json').read_text())[1]['key']
raw['moving_rotors']=tuple(raw['moving_rotors'])
raw['plugboard']=tuple(raw['plugboard'])
# Original indicator positions require original rings, not the equivalent
# message-specific settings used for the solved plaintext fixture.
key=Key(**dict(raw,rings='VCCH'))
for position,cipher,expected in [('MNNS','OEDM','ELKC'),('DGUG','SEDM','PUYY'),
                               ('PUYY','JCRSAJ','IPZAYK'),('IBFK','YMUZ','ODFF')]:
    assert crypt(cipher,replace(key,positions=position))==expected
assert crypt('JCRSAJ',replace(key,rings='AACU',positions='PUYY'))!='IPZAYK'
print('HISTORICAL_INDICATOR_REPLAY_OK_NOT_A_TARGET_DECRYPT')
