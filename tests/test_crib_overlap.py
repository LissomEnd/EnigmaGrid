import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_crib_overlap import classify,audit
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
print('CRIB_OVERLAP_DIRECTION_AND_NO_UNPROVEN_EXCLUSION_OK')
