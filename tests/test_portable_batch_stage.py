"""No-device host checks for the private Windows GPU batch prototype."""
import importlib.util
import json
import os
import sys
import tempfile
import threading
import multiprocessing
from pathlib import Path
from unittest.mock import patch

STAGE=Path(__file__).resolve().parent
ROOT=Path(os.environ.get("ENIGMAGRID_SOURCE_ROOT",STAGE.parent)).resolve()
sys.path[:0]=[str(STAGE),str(ROOT/"worker"),str(ROOT/"solver/runtime/src")]
from portable_batch_qualification import (FORMAT,choose,qualify,load_profile,save_profile)
from search import portable_search
import numpy as np

rows=[]
for trial in range(3):
    rows.append(dict(trial=trial,receipt_equal=True,
                     seconds={"4":.100+trial*.001,"8":.085+trial*.001,
                              "16":.080+trial*.001}))
assert choose(rows)==16
bad=json.loads(json.dumps(rows));bad[0]["receipt_equal"]=False
try:choose(bad)
except ValueError:pass
else:raise AssertionError("Missing parity was accepted")
with tempfile.TemporaryDirectory() as temporary:
    record=Path(temporary)/"profile.json"
    scope=dict(count=4096,iterations=32,mode="joint")
    report=dict(format=FORMAT,hardware="device+driver",assets="code+data",
                scope=scope,parity_passed=True,trials=rows,selected_blocks=16)
    save_profile(record,report)
    assert load_profile(record,"device+driver","code+data",scope)==16
    assert load_profile(record,"other driver","code+data",scope) is None
    assert load_profile(record,"device+driver","other code",scope) is None
    assert load_profile(record,"device+driver","code+data",dict(scope,iterations=64)) is None

clock=[0.0]
def execute(blocks,checkpoint):
    checkpoint()
    clock[0]+={1:.12,4:.10,8:.085,16:.08}[blocks]
    return {"summary":{"engine":"portable_event_v1","units":1},
            "candidates":[{"attempt":71000000000,"score":1}]}
qualified=qualify(execute,scope,"device+driver","code+data",clock=lambda:clock[0])
assert qualified["selected_blocks"]==16
assert all(row["receipt_equal"] for row in qualified["trials"])
interrupted=[False]
def abort():
    interrupted[0]=True
    raise InterruptedError("pause")
try:qualify(execute,scope,"device+driver","code+data",checkpoint=abort,clock=lambda:clock[0])
except InterruptedError:pass
else:raise AssertionError("Cancelled qualification continued")
assert interrupted[0]

worker_path=STAGE/"worker.py"
if not worker_path.is_file(): worker_path=ROOT/"worker"/"worker.py"
spec=importlib.util.spec_from_file_location("worker_portable_stage",worker_path)
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
worker.ROOT=ROOT
message=json.loads((ROOT/"solver/runtime/data/messages/p1030680.json").read_text())["ciphertext"]
seen=[];seen_lock=threading.Lock()
def fake_search(_text,start_seed,*,count,backend,cohort_blocks,topk,checkpoint,**_kwargs):
    checkpoint(0,0)
    with seen_lock:seen.append((start_seed,start_seed+count,backend,cohort_blocks))
    return [{"attempt":start_seed+i,"score":-(start_seed+i),
             "metrics":{"search_cost":start_seed+i}}
            for i in range(0,count,256)][:topk]
lease={"start_unit":0,"end_unit":1,
       "config":{"count_per_unit":4096,"iterations":1,"topk":8,
                 "base_attempt":71000000000}}
receipts=[]
for blocks in (1,4,8,16):
    seen.clear()
    runtime={"settings":{"allow_cpu":True,"allow_gpu":True,
                         "cpu_percent":100,"gpu_percent":100}}
    with patch.object(portable_search,"search",fake_search):
        result,_=worker.run_portable(lease,runtime,None,
            gpu_scorers=[lambda keys:keys],gpu_blocks_override=blocks)
    worker.release_portable_executor(runtime)
    cursor=71000000000
    for left,right,backend,group in sorted(seen):
        assert left==cursor,(blocks,cursor,left,right)
        assert group <= blocks if backend=="opencl" else group==1
        cursor=right
    assert cursor==71000000000+4096
    assert {backend for _,_,backend,_ in seen}=={"cpu","opencl"}
    receipts.append(result)
assert receipts[0]==receipts[1]==receipts[2]==receipts[3]

runtime={"settings":{"allow_cpu":True,"allow_gpu":True,
                     "cpu_percent":100,"gpu_percent":100}}
calls=[0]
def stop_on_checkpoint():
    calls[0]+=1
    raise InterruptedError("qualification cancelled")
try:
    with patch.object(portable_search,"search",fake_search):
        worker.run_portable(lease,runtime,None,gpu_scorers=[lambda keys:keys],
                            gpu_blocks_override=16,qualification_check=stop_on_checkpoint)
except InterruptedError:pass
else:raise AssertionError("Cancelled unit was accepted")
finally:worker.release_portable_executor(runtime)
assert calls[0]>=1

# The first real scope starts an automatic background check; a complete,
# device-bound report is applied only to the next unit without blocking this
# unit. A fake scorer prevents any physical GPU use in this host regression.
class DummyDevice:
    vendor="Fixture";name="GPU";version="1";driver_version="1";global_mem_size=2**30
class DummyScorer:
    device=DummyDevice()
    def __init__(self,*_args):pass
    def __call__(self,keys):return np.zeros(len(keys),dtype=np.int32)
with tempfile.TemporaryDirectory() as temporary:
    runtime={"settings":{"allow_cpu":True,"allow_gpu":True,
                         "cpu_percent":100,"gpu_percent":100},
             "telemetry":{"available_gb":8},"_portable_last_unit_seconds":4.0}
    saved=[]
    class FakeProcess:
        def is_alive(self):return False
        def join(self,_timeout=None):pass
    def fake_spawn(_run,_lease,_settings,scope,hardware,assets,seconds):
        assert 60<=seconds<=180
        receive,send=multiprocessing.get_context("spawn").Pipe(duplex=False)
        send.send(dict(format=FORMAT,hardware=hardware,assets=assets,scope=scope,
                       parity_passed=True,trials=rows,selected_blocks=16))
        send.close()
        return FakeProcess(),receive
    with patch("portable_batch_qualification.asset_fingerprint",return_value="assets"),\
         patch("portable_batch_qualification.device_fingerprint",return_value="gpu"),\
         patch("portable_batch_qualification.load_profile",return_value=None),\
         patch("portable_batch_qualification.save_profile",side_effect=lambda *_:saved.append(1)),\
         patch("portable_batch_qualification.spawn_qualification",side_effect=fake_spawn),\
         patch.object(portable_search,"search",fake_search),\
         patch.object(worker,"_thermal_probe",return_value=("",{"paused":False,"stop_requested":False})):
        first=worker.portable_batch_blocks(lease,runtime,Path(temporary)/"state.json",
                                           message,True,[DummyScorer()])
        assert first==4
        active=runtime["_portable_batch_qualification"]
        active["thread"].join(3)
        assert not active["thread"].is_alive()
        assert "_portable_batch_qualification" not in runtime
        assert saved==[1] and runtime["_portable_batch_profile_valid"]
        assert worker.portable_batch_blocks(lease,runtime,Path(temporary)/"state.json",
                                             message,True,[DummyScorer()])==16
        assert len(runtime["_portable_batch_attempted"])==1
    worker.release_portable_executor(runtime)

# Stop and pause must terminate the owned qualifier before the worker waits.
for first_control in ({"stop_requested":True}, {"paused":True}):
    class RunningChild:
        def __init__(self):self.running=True;self.terminated=False
        def is_alive(self):return self.running
        def terminate(self):self.terminated=True;self.running=False
        def join(self,_timeout=None):pass
    child=RunningChild()
    gate_runtime={"_portable_batch_qualification":{
        "cancel":threading.Event(),"process":child,"process_lock":threading.Lock()}}
    controls=[("",first_control),("",{"stop_requested":True})]
    with patch.object(worker,"_thermal_probe",side_effect=controls),\
         patch.object(worker,"publish_health"),\
         patch.object(worker.time,"sleep",return_value=None):
        try:worker.cooperative_gate(gate_runtime,Path("fixture.json"))
        except InterruptedError:pass
        else:raise AssertionError("Stop did not interrupt work")
    assert child.terminated and gate_runtime["_portable_batch_qualification"]["cancel"].is_set()
print("PASS private cohort 1/4/8/16 full-coverage and receipt parity, profile guards, cancellation")
