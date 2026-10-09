"""Grouped GPU dispatch must preserve every deterministic portable result."""
import json
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'solver/runtime/src'))
from search.portable_search import search

text=json.loads((root/'solver/runtime/data/messages/p1030680.json').read_text())['ciphertext']
for count in (1,257,1024):
    arguments=dict(start_seed=71000000000,count=count,iterations=4,topk=8,
                   min_pairs=0,max_pairs=13,event_kinds=(1,2,3,4,5,6),backend='cpu')
    reference=search(text,**arguments)
    for cohort in (2,4,8):
        actual=search(text,**arguments,cohort_blocks=cohort)
        assert actual==reference,(count,cohort)
print('PASS portable cohort replay parity for partial/full blocks and 2/4/8-block groups')
