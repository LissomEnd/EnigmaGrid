"""No-server regression for truthful legacy lease/upload/ACK telemetry."""
import importlib.util
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

STAGE=Path(__file__).resolve().parent
ROOT=Path(os.environ.get("ENIGMAGRID_SOURCE_ROOT",STAGE.parent)).resolve()
sys.path[:0]=[str(STAGE),str(ROOT/"worker"),str(ROOT/"solver/runtime/src")]
from performance_telemetry import DeviceTelemetry
from receipt_outbox import OutboxUploader

worker_path=STAGE/"worker.py"
if not worker_path.is_file(): worker_path=ROOT/"worker"/"worker.py"
spec=importlib.util.spec_from_file_location("worker_legacy_telemetry_stage",worker_path)
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)

runtime={"active_engine":"portable_event_v1","resource":"CPU + GPU"}
telemetry=DeviceTelemetry(runtime,lambda:{},lambda *_:None,lambda:{},lambda *_:{},"0.5.0")
before=telemetry._snapshot()
assert before["upload_seconds"] is None and before["lease_seconds"] is None
assert before["receipts_acked"] is None
telemetry._add_sample({},before)
assert not any(key in telemetry._finish(telemetry.current)
               for key in ("upload_ms","lease_ms","receipts_acked"))
worker.record_legacy_metric(runtime,"_legacy_lease_seconds",.012)
worker.record_legacy_metric(runtime,"_legacy_upload_seconds",.027)
worker.record_legacy_metric(runtime,"_legacy_receipts_acked",1)
telemetry._add_sample({},telemetry._snapshot())
bucket=telemetry._finish(telemetry.current)
assert bucket["lease_ms"]==12 and bucket["upload_ms"]==27
assert bucket["receipts_acked"]==1
telemetry._add_sample({},telemetry._snapshot())
assert telemetry._finish(telemetry.current)["receipts_acked"]==1

calls=[]
def broken_post(*_args,**_kwargs):
    raise RuntimeError("fixture offline")
with patch.object(worker,"post",side_effect=broken_post):
    try:worker.timed_batch_request({"server":"https://fixture","device_token":"fixture"},
                                   {},lambda value:calls.append(value))
    except RuntimeError:pass
    else:raise AssertionError("Fixture request unexpectedly succeeded")
assert len(calls)==1 and calls[0]>=0

class Queue:
    def __init__(self):self.done=False
    def pending(self):return [] if self.done else [{"lease_id":"fixture-lease"}]
    def confirm(self,lease_id):
        assert lease_id=="fixture-lease"
        self.done=True
        return True
    def flush_confirmed(self):pass

acked=[];done=threading.Event()
uploader=OutboxUploader(Queue(),None,
    send_batch=lambda items:[(items[0]["lease_id"],{"ok":True})],
    on_ack=lambda lease_id,ack:(acked.append((lease_id,ack)),done.set()))
uploader.notify()
assert done.wait(2)
uploader.close()
assert acked==[("fixture-lease",{"ok":True})]
duplicate_queue=Queue(); duplicate_seen=[]; duplicate_done=threading.Event()
duplicate=OutboxUploader(duplicate_queue,None,
    send_batch=lambda items:[(items[0]["lease_id"],{"ok":True,"duplicate":True})],
    on_ack=lambda lease_id,ack:(duplicate_seen.append(ack),duplicate_done.set()))
duplicate.notify()
assert duplicate_done.wait(2)
duplicate.close()
assert duplicate_queue.done and duplicate_seen==[{"ok":True,"duplicate":True}]
with patch.object(worker,"post",return_value={"ok":True,"duplicate":True}):
    class ReplayQueue:
        def pending(self):return [{"lease_id":"fixture-lease"}]
        def acknowledge(self,lease_id):self.acknowledged=lease_id;return True
    replay=ReplayQueue()
    with patch.object(worker,"result_outbox",return_value=replay):
        worker.deliver_pending("fixture",{"server":"https://fixture","device_token":"fixture"},runtime)
assert replay.acknowledged=="fixture-lease"
assert runtime["_legacy_receipts_acked"]==2  # Duplicate replay still retires one local item.
anchor=DeviceTelemetry(runtime,lambda:{},lambda *_:None,lambda:{},lambda *_:{},"0.5.0")
anchor.clock_anchor=(int(time.time()*1000),time.monotonic())
anchor._add_sample({},anchor._snapshot())
assert anchor._finish(anchor.current)["receipts_acked"]==2
def changed_clock():
    anchor.stop_event.set()
    return {"device_telemetry":"device_telemetry_v1",
            "server_time_ms":anchor.clock_anchor[0]+5000}
anchor.capabilities=changed_clock
anchor.wake.set();anchor._send_loop()
assert anchor.current is None and anchor.last_totals["receipts_acked"]==2
anchor._add_sample({},anchor._snapshot())
assert "receipts_acked" not in anchor._finish(anchor.current)
assert "lease_ms" not in anchor._finish(anchor.current)
assert "upload_ms" not in anchor._finish(anchor.current)
switch_runtime={"active_engine":"portable_event_v1","_legacy_upload_seconds":.027,
                "_legacy_lease_seconds":.012}
switch=DeviceTelemetry(switch_runtime,lambda:{},lambda *_:None,lambda:{},lambda *_:{},"0.5.0")
switch._add_sample({},switch._snapshot())
pipeline=SimpleNamespace(upload_seconds=.5,lease_seconds=.2)
switch_runtime.update(active_engine="bounded_crib_v1",_block_pipeline=pipeline)
switch._add_sample({},switch._snapshot())
switch_runtime.update(active_engine="portable_event_v1",_legacy_upload_seconds=.037,
                      _legacy_lease_seconds=.022)
switch._add_sample({},switch._snapshot())
switch_runtime["active_engine"]="bounded_crib_v1"
pipeline.upload_seconds=.51;pipeline.lease_seconds=.21
switch._add_sample({},switch._snapshot())
switched=switch._finish(switch.current)
assert switched["upload_ms"]==547 and switched["lease_ms"]==232,switched
print("PASS legacy lease/upload first event, no fabricated zero, ACK only after success")
