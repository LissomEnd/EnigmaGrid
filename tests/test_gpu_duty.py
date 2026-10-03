"""A slow scorer at 5% must rest beyond one second and keep polling controls."""
import json,sys
from pathlib import Path
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'solver/runtime/src'))
from search import portable_search as engine
text=json.loads((ROOT/'solver/runtime/data/messages/p1030680.json').read_text())['ciphertext']
now=[0.0];waits=[];checks=[]
def scorer(keys):
    now[0]+=.2
    return np.zeros(len(keys),dtype=np.int32)
def sleep(delay):
    waits.append(delay);now[0]+=delay
def checkpoint(offset,iteration):checks.append(now[0])
with patch.object(engine.time,'perf_counter',lambda:now[0]),patch.object(engine.time,'sleep',sleep):
    slow=engine.search(text,777,count=2,iterations=1,backend='opencl',percent=5,scorer=scorer,checkpoint=checkpoint)
assert sum(waits)>=3.8-1e-8,sum(waits)
assert max(waits)<=.1 and len(checks)>=38
assert slow==engine.search(text,777,count=2,iterations=1,backend='cpu',scorer=scorer)
class Cancelled(Exception):pass
now[0]=0;waits.clear()
def cancel(offset,iteration):
    if waits:raise Cancelled()
with patch.object(engine.time,'perf_counter',lambda:now[0]),patch.object(engine.time,'sleep',sleep):
    try:engine.search(text,777,count=2,iterations=1,backend='opencl',percent=5,scorer=scorer,checkpoint=cancel)
    except Cancelled:pass
    else:raise AssertionError('Cancellation during rest was ignored')
assert sum(waits)<=.1
print('GPU_DUTY_SLOW_SCORER_REST_AND_CHECKPOINT_OK')
