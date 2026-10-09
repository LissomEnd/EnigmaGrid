import copy
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'worker'))
from gpu_lane_qualification import qualify,select_profile

rows=[dict(trial=i,receipt_equal=True,cpu_seconds=.12,mixed_seconds=.075,gpu_jobs=4) for i in range(3)]
assert select_profile(rows,1)
for field,value in [('mixed_seconds',.12),('cpu_seconds',float('nan')),
                    ('receipt_equal',False),('trial',4),('gpu_jobs',0)]:
    broken=copy.deepcopy(rows);broken[1][field]=value
    if field=='mixed_seconds':
        assert not select_profile(broken,1)
    else:
        try:select_profile(broken,1)
        except ValueError:pass
        else:raise AssertionError('Invalid GPU qualification accepted')

envelopes=[dict(start_unit=index) for index in range(12)]
def expected(envelope):return dict(receipt=dict(unit=envelope['start_unit']))
def cpu(envelope):time.sleep(.008);return expected(envelope)
def gpu(envelope):time.sleep(.012);return expected(envelope)
report=qualify(envelopes,expected,cpu,gpu,1)
assert report['qualified'] and report['jobs_per_trial']==12
assert report['mixed_cpu_lanes']==1 and select_profile(report['trials'],1)
assert all(row['mixed_seconds']<row['cpu_seconds'] for row in report['trials'])
assert all(row['gpu_jobs']>0 for row in report['trials'])
try:qualify(envelopes,expected,cpu,lambda _:dict(receipt='wrong'),1)
except ValueError:pass
else:raise AssertionError('Wrong GPU receipt accepted')
calls=[0];cancelled=[False]
def wrong_after_warm(envelope):
    calls[0]+=1
    return expected(envelope) if calls[0]==1 else dict(receipt='wrong')
try:qualify(envelopes,expected,cpu,wrong_after_warm,1,
            cancel_running=lambda:cancelled.__setitem__(0,True))
except ValueError:pass
else:raise AssertionError('Wrong concurrent GPU receipt accepted')
assert cancelled[0]
print('PASS independent GPU lane can qualify on aggregate gain despite slower single GPU job; exact receipts required')
