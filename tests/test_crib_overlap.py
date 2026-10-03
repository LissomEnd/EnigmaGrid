import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_crib_overlap import classify,audit,attach_execution_log
assert classify('ABCDE',3,'ABCDE',3)=='identical_constraints'
assert classify('ABCDE',3,'BCD',4)=='proposal_implies_prior_constraints'
assert classify('BCD',4,'ABCDE',3)=='prior_implies_proposal_constraints'
assert classify('ABCDE',3,'BCX',4) is None
assert classify('ABCDE',3,'XYZ',12) is None
p=dict(ciphertext='XYZ',hypotheses=[dict(text='ABC',legal_clean_offsets=[0])])
c=dict(ciphertext='XYZ',cribs=[dict(text='ABC',offsets=[0])])
r=audit(p,c)
assert r['placements'][0]['matches'] and not r['placements'][0]['exclusion_allowed']
try:audit(p,dict(c,ciphertext='XYY'))
except ValueError:pass
else:raise AssertionError('Mixed different transcripts')
log='  [7] ABC@0 planned only\n  [7/9·1] ABC@1 wrong offset\n  [8/9·2] ABC@0 dead at the board\n  [8/9·2] ABC@0 repeated report\n'
r=attach_execution_log(audit(p,c),log.encode())
assert r['execution_log']['reported_rows']==3 and r['execution_log']['mapped_placements']==1
assert len(r['placements'][0]['matches'][0]['reported_execution_rows'])==2
assert not r['placements'][0]['exclusion_allowed']
assert not r['execution_log']['exclusion_allowed']
assert attach_execution_log(audit(p,c),b'[7] ABC@0 planned')['execution_log']['mapped_placements']==0
print('CRIB_OVERLAP_DIRECTION_AND_NO_UNPROVEN_EXCLUSION_OK')
