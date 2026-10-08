import copy,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'solver/runtime/src'))
from search import work_result_groups as groups
from search.work_block import FORMAT, unit_envelope
from search.crib_work import run
block=dict(format=FORMAT,block_id='test',engine='bounded_crib_v1',start_unit=0,end_unit=100,
 config=dict(requires=['cpu','bounded_crib_v1'],program=dict(ciphertext='BDZGO',
 hypotheses=[dict(text='BD',legal_clean_offsets=[0])],chunk=3,ordinal_base=0,candidate_limit=3)))
receipts=[dict(unit=n,compute_seconds=.05,result=run(unit_envelope(block,n))) for n in range(16)]
payload=dict(format=groups.FORMAT,block_id='test',groups=[receipts[:8],receipts[8:]])
assert groups.validate_groups(block,payload)==16
assert [r for p in groups.partials(payload) for r in p['receipts']]==receipts
for mutate in [lambda p:p['groups'][1].__setitem__(0,p['groups'][0][0]),
               lambda p:p.update(block_id='other'),
               lambda p:p['groups'][0].extend(p['groups'][1]),
               lambda p:p.update(groups=p['groups']*5),
               lambda p:p['groups'][1][0].update(unit=100)]:
 bad=copy.deepcopy(payload);mutate(bad)
 try:groups.validate_groups(block,bad)
 except ValueError:pass
 else:raise AssertionError('Malformed groups accepted')
assert groups.MAX_BODY_BYTES==256*1024
print('PASS grouped receipts preserve unit results; duplicate, scope and count bounds enforced')
