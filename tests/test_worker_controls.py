"""Check real search checkpoints and resource routing without requiring a GPU."""
import json
import sys
import tempfile
import threading
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'worker'),str(ROOT/'solver/runtime/src')]
import worker
from search import portable_search
from search.cpu_numba import encode

text=json.loads((ROOT/'solver/runtime/data/messages/p1030680.json').read_text())['ciphertext']
inp=encode(text)
lease={'engine':'portable_event_v1','start_unit':0,'end_unit':2,
       'config':{'count_per_unit':8,'iterations':4,'topk':2,'base_attempt':71000000000}}
original=portable_search.score_cpu
calls={'cpu':0,'gpu':0}
def cpu_score(inp,keys):
    calls['cpu']+=len(keys)
    return original(inp,keys)
def gpu_score(keys):
    calls['gpu']+=len(keys)
    return original(inp,keys)
portable_search.score_cpu=cpu_score
worker._GPU_SCORERS=[gpu_score]
try:
    outputs=[]
    for cpu,gpu in [(25,0),(0,100),(25,100)]:
        calls.update(cpu=0,gpu=0)
        runtime={'settings':worker.normalize_settings({'cpu_percent':cpu,'gpu_percent':gpu})}
        outputs.append(worker.run_portable(lease,runtime)[0])
        assert bool(calls['cpu'])==bool(cpu),calls
        assert bool(calls['gpu'])==bool(gpu),calls
        assert runtime['progress']==1
    assert outputs[0]==outputs[1]==outputs[2]
    with tempfile.TemporaryDirectory(prefix='enigma-controls-') as temp:
        state=Path(temp)/'client.json';health=state.with_name('worker-health.json')
        worker.write_control(state,{'paused':True})
        runtime={'settings':worker.normalize_settings({'cpu_percent':25,'gpu_percent':0}),
                 'health_path':health,'started':time.time()}
        result=[];errors=[]
        def run():
            try:result.append(worker.run_portable(lease,runtime,state)[0])
            except Exception as exc:errors.append(exc)
        thread=threading.Thread(target=run,daemon=True);thread.start()
        try:
            deadline=time.monotonic()+30
            while runtime.get('status')!='paused':
                assert thread.is_alive(),errors
                assert time.monotonic()<deadline,'pause checkpoint not reached'
                time.sleep(.05)
            paused_calls=dict(calls);time.sleep(.35)
            assert calls==paused_calls,'computation continued while paused'
            worker.write_control(state,{'paused':False,'stop_requested':True})
            thread.join(30)
            assert not thread.is_alive(), 'safe stop failed to finish current job'
            assert not errors,errors
            assert result==[outputs[0]]
            assert worker.read_control(state)['stop_requested']
        finally:
            worker.write_control(state,{'paused':False,'stop_requested':True})
            thread.join(30)
finally:
    portable_search.score_cpu=original
    worker._GPU_SCORERS=[]
print('WORKER_CONTROLS_OK: routing, deterministic results, pause, resume-to-safe-stop')
