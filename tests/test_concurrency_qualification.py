import sys
import threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
from concurrency_qualification import qualify,select_lanes,ORDERS

def trials(times):
    return [dict(lanes=lane,seconds=times[lane][round],receipt_equal=True)
            for round,order in enumerate(ORDERS) for lane in order]
assert select_lanes(trials({1:[1]*3,2:[.6]*3,4:[.4]*3}))==4
assert select_lanes(trials({1:[1]*3,2:[.6]*3,4:[.7]*3}))==2
assert select_lanes(trials({1:[1]*3,2:[.98]*3,4:[.4,.4,1.2]}))==1
for invalid in ([],trials({1:[1]*3,2:[float('nan')]*3,4:[.4]*3})):
    try:select_lanes(invalid)
    except ValueError:pass
    else:raise AssertionError('Incomplete or nonfinite comparison accepted')
count=[0];lock=threading.Lock()
def execute(value):
    with lock:count[0]+=1
    return {'receipt':value*value}
result=qualify(list(range(12)),execute,execute)
assert count[0]==132 and result['parity_checks']==120 and len(result['trials'])==9
count[0]=0
def broken(value):
    with lock:count[0]+=1;n=count[0]
    return {'receipt':value*value+(1 if n>12 else 0)}
try:qualify(list(range(12)),lambda value:{'receipt':value*value},broken)
except ValueError:pass
else:raise AssertionError('Mismatched concurrent receipt qualified')
print('PASS rotated 1/2/4 qualification, parity gate, repeatable gain selection and invalid evidence rejection')
