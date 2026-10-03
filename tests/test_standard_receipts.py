"""Every experimental search hit must be independently replayable."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'solver/runtime/src'))
from numba import set_num_threads
from search.portable_standard import search
from search.c3_models import Key,crypt
set_num_threads(1)
fixture=json.loads((ROOT/'tests/fixtures/historical_m4.json').read_text())[0]
cipher=fixture['ciphertext'][:72]
hits=search(cipher,142,count=12,iterations=8,topk=4)
assert hits==search(cipher,142,count=12,iterations=8,topk=4)
for hit in hits:
    key=Key.from_dict(hit['key'])
    assert len(key.plugboard)==10 and key.rings.startswith('AA')
    assert crypt(cipher,key)==hit['plaintext']
    assert hit['historical_solution'] is False and hit['model']=='clean'
print('STANDARD_RESEARCH_RECEIPTS_REPLAY_OK')
