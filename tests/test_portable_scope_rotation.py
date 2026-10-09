"""Isolated regression: rotating real portable scopes must not cancel one pilot."""
import importlib.util
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

ROOT=Path(os.environ.get("ENIGMAGRID_SOURCE_ROOT",Path(__file__).resolve().parents[1]))
WORKER_DIR=ROOT/"worker"
sys.path.insert(0,str(WORKER_DIR))
source=Path(os.environ.get("WORKER_UNDER_TEST",WORKER_DIR/"worker.py"))
spec=importlib.util.spec_from_file_location("staged_scope_worker",source)
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
import portable_batch_qualification as qualification


class FakeProcess:
    def __init__(self):self.alive=True
    def is_alive(self):return self.alive
    def terminate(self):self.alive=False
    def kill(self):self.alive=False
    def join(self,seconds):pass


class FakePipe:
    def __init__(self,report):self.ready=threading.Event();self.report=report
    def poll(self):return self.ready.is_set()
    def recv(self):return self.report
    def close(self):pass


def lease(bounds):
    return {"config":{"count_per_unit":4096,"min_pairs":bounds[0],"max_pairs":bounds[1]},
            "start_unit":0}


def test_scope_rotation():
    settings={"cpu_percent":100,"gpu_percent":100,"allow_cpu":True,"allow_gpu":True}
    runtime={"settings":settings,"enabled":True,"telemetry":{"available_gb":4},
             "_portable_last_unit_seconds":1}
    spawned=[]
    def fake_spawn(run_portable,sample_lease,settings,scope,hardware,assets,seconds):
        assert not any(process.is_alive() for process,_ in spawned),"more than one qualification child"
        report={"format":qualification.FORMAT,"hardware":hardware,"assets":assets,"scope":scope,
                "parity_passed":True,"selected_blocks":8,
                "trials":[{"trial":i,"receipt_equal":True,
                           "seconds":{"4":100.0,"8":90.0,"16":95.0}} for i in range(3)]}
        item=(FakeProcess(),FakePipe(report));spawned.append(item);return item
    control={"paused":False,"stop_requested":False,"max_cpu_temp_c":80,"max_gpu_temp_c":75}
    with tempfile.TemporaryDirectory() as folder,\
            patch.object(qualification,"device_fingerprint",return_value="device"),\
            patch.object(qualification,"asset_fingerprint",return_value="assets"),\
            patch.object(qualification,"spawn_qualification",side_effect=fake_spawn),\
            patch.object(worker,"read_control",return_value=control),\
            patch.object(worker,"_thermal_probe",return_value=("",control)):
        state=Path(folder)/"state.json"
        a,b,c=lease((0,3)),lease((4,10)),lease((11,13))
        assert worker.portable_batch_blocks(a,runtime,state,"cipher",True,[object()])==4
        first=runtime["_portable_batch_qualification"]
        assert worker.portable_batch_blocks(b,runtime,state,"cipher",True,[object()])==4
        assert worker.portable_batch_blocks(c,runtime,state,"cipher",True,[object()])==4
        time.sleep(.45)  # Allow the watchdog to inspect two scope rotations.
        assert len(spawned)==1 and not first["cancel"].is_set()
        assert spawned[0][0].is_alive(),"a different live scope must not kill the captured pilot"
        spawned[0][1].ready.set()
        first["thread"].join(3)
        assert not first["thread"].is_alive(),"pilot should finish after result"
        assert runtime["_portable_batch_profile_key"]!=first["identity"]
        assert runtime["_portable_batch_blocks"]==4,"other scope must retain its default"
        assert "Checking" not in runtime["portable_batch_reason"],"completed other-scope pilot cannot leave stale Checking"
        assert worker.portable_batch_profile_path(state,first["identity"]).exists()
        assert worker.portable_batch_blocks(a,runtime,state,"cipher",True,[object()])==8
        assert len(spawned)==1,"matching scope must load its durable profile"
        assert worker.portable_batch_blocks(b,runtime,state,"cipher",True,[object()])==4
        assert len(spawned)==2,"second scope may qualify only after first child exits"
        second=runtime["_portable_batch_qualification"]
        second["cancel"].set();spawned[1][0].terminate();second["thread"].join(3)
        assert not second["thread"].is_alive()
        legacy=state.with_name("portable-gpu-batch-qualification.json")
        qualification.save_profile(legacy,spawned[1][1].report)
        assert worker.portable_batch_blocks(a,runtime,state,"cipher",True,[object()])==8
        assert worker.portable_batch_blocks(b,runtime,state,"cipher",True,[object()])==8
        assert len(spawned)==2,"legacy exact profile loads without another child"
        for index in range(36):
            candidate=state.with_name(f"portable-gpu-batch-qualification-{index:024x}.json")
            candidate.write_text("{}",encoding="utf-8")
            os.utime(candidate,(index+1,index+1))
        current=worker.portable_batch_profile_path(state,first["identity"])
        oldest=state.with_name("portable-gpu-batch-qualification-"+"0"*24+".json")
        worker.prune_portable_batch_profiles(current,protected=(oldest,),maximum=32)
        assert len(list(state.parent.glob("portable-gpu-batch-qualification-"+"[0-9a-f]"*24+".json")))==32
        assert current.exists() and oldest.exists() and legacy.exists(),"pruning must retain session and legacy profiles"


def test_protections_after_rotation():
    for protection in ("thermal","settings"):
        settings={"cpu_percent":100,"gpu_percent":100,"allow_cpu":True,"allow_gpu":True}
        runtime={"settings":settings,"enabled":True,"telemetry":{"available_gb":4},
                 "_portable_last_unit_seconds":1}
        reason=[""];children=[]
        def fake_spawn(run_portable,sample_lease,settings,scope,hardware,assets,seconds):
            item=(FakeProcess(),FakePipe(None));children.append(item);return item
        control={"paused":False,"stop_requested":False,"max_cpu_temp_c":80,"max_gpu_temp_c":75}
        with tempfile.TemporaryDirectory() as folder,\
                patch.object(qualification,"device_fingerprint",return_value="device"),\
                patch.object(qualification,"asset_fingerprint",return_value="assets"),\
                patch.object(qualification,"spawn_qualification",side_effect=fake_spawn),\
                patch.object(worker,"read_control",return_value=control),\
                patch.object(worker,"_thermal_probe",side_effect=lambda *_:(reason[0],control)):
            state=Path(folder)/"state.json"
            worker.portable_batch_blocks(lease((0,3)),runtime,state,"cipher",True,[object()])
            active=runtime["_portable_batch_qualification"]
            worker.portable_batch_blocks(lease((4,10)),runtime,state,"cipher",True,[object()])
            if protection=="thermal":reason[0]="CPU cooling"
            else:runtime["settings"]["gpu_percent"]=50
            active["thread"].join(3)
            assert not active["thread"].is_alive(),"protection must stop the pilot"
            assert not children[0][0].is_alive(),"owned child must terminate"
            assert not worker.portable_batch_profile_path(state,active["identity"]).exists()
            assert "_portable_batch_qualification" not in runtime


if __name__=="__main__":
    test_scope_rotation();test_protections_after_rotation()
    print("PASS portable scope rotation, scoped cache and thermal/settings cancellation")
