import sys,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'worker'),str(ROOT/'solver/runtime/src')]
from block_pipeline import BlockPipeline
class Queue:
    def __init__(self):self.count=1;self.finished=0;self.claims=set();self.max_pending=8
    # This fixture exercises compute/upload overlap with an already filled
    # two-reservation window. Initial refill policy is tested separately.
    def remaining(self):return 50000,2
    def pending(self):return [dict(unit=n) for n in range(self.count)]
    def next_unit(self):return ('block',dict(start_unit=self.finished)) if self.count<8 else None
    def claim_prefetched(self,lanes):
        if self.count+len(self.claims)>=8 or len(self.claims)>=2*lanes:return None
        unit=self.finished
        while unit in self.claims:unit+=1
        self.claims.add(unit);return 'block',dict(start_unit=unit)
    def complete_batch(self,items):
        for identity,unit,result,seconds in items:
            self.count+=1;self.finished+=1;self.claims.remove(unit)
    def release_claim(self,identity=None,unit=None):self.claims.discard(unit)
class Transport:
    def __init__(self):self.entered=threading.Event();self.release=threading.Event()
    def upload(self):self.entered.set();assert self.release.wait(5);return 0
    def allocate(self):raise AssertionError('Unneeded refill')
q=Queue();t=Transport();p=BlockPipeline(q,t,lambda job:(time.sleep(.02) or {}))
try:
    p.tick();assert t.entered.wait(2)
    deadline=time.monotonic()+3
    while q.finished<7 and time.monotonic()<deadline:p.tick();time.sleep(.001)
    assert q.finished==7 and q.count==8
    p.tick();assert q.finished==7,'Outbox bound exceeded'
    assert not p.tick(allow_compute=False)
finally:t.release.set();p.close()
assert q.count==8,'Unacknowledged results lost on close'
print('PASS upload stall overlaps local compute, bounded outbox and pause prevents new work')

q=Queue();q.count=8;t=Transport();t.release.set();p=BlockPipeline(q,t,lambda job:{})
try:
    p.tick(allow_compute=False)
    _,actual=p.upload.result(timeout=2)
    # A compute/thermal pause delays polling, not the already finished HTTP call.
    p.upload_started=time.monotonic()-120
    p.tick(allow_compute=False)
    assert p.upload_latency==max(actual,.8*.25+.2*actual)
finally:p.close()
print('PASS completed upload latency excludes delayed compute-thread polling')

from block_transport import ReceiptRejected
class RejectedTransport:
    def __init__(self):self.calls=0
    def upload(self):self.calls+=1;raise ReceiptRejected('expired')
    def allocate(self):raise AssertionError('Refill after rejection')
q=Queue();q.count=8;t=RejectedTransport();p=BlockPipeline(q,t,lambda job:(_ for _ in ()).throw(AssertionError('Computed after rejection')))
try:
    p.tick()
    deadline=time.monotonic()+2
    while not p.upload.done() and time.monotonic()<deadline:time.sleep(.001)
    for _ in range(20):assert not p.tick()
    assert p.terminal_error=='expired' and t.calls==1 and q.count==8
finally:p.close()
print('PASS terminal receipt refusal retains results without upload/refill retry storm')

q=Queue();t=Transport();p=BlockPipeline(q,t,lambda job:(time.sleep(.02) or {}))
control_started=threading.Event();control_release=threading.Event();calls=[]
def slow_control():
    calls.append(1);control_started.set()
    assert control_release.wait(5)
    return {'enabled':False}
try:
    assert p.poll_control(slow_control) is None
    assert control_started.wait(2)
    deadline=time.monotonic()+3
    while q.finished<7 and time.monotonic()<deadline:
        assert p.poll_control(slow_control) is None
        p.tick();time.sleep(.001)
    assert q.finished==7 and len(calls)==1
    control_release.set()
    deadline=time.monotonic()+2
    while not p.control.done() and time.monotonic()<deadline:time.sleep(.001)
    reply=p.poll_control(slow_control)
    assert reply=={'enabled':False}
    assert not p.tick(allow_compute=reply['enabled'])
    assert q.finished==7
finally:
    control_release.set();t.release.set();p.close()
print('PASS stalled control HTTP does not stall compute; completed disable prevents next unit')

from block_queue import QueueCapacityError
from concurrent.futures import Future
q=Queue();t=Transport();p=BlockPipeline(q,t,lambda job:{})
try:
    p.fetch=Future();p.fetch.set_exception(QueueCapacityError('Full during refill'))
    p.tick()
    assert t.entered.wait(2), 'Capacity failure prevented independent upload'
    assert p.fetch is None and p.next_fetch>time.monotonic()
    assert p.wait_reason=='result_storage_full' and p.terminal_error is None
    deadline=time.monotonic()+2
    while q.finished<2 and time.monotonic()<deadline:time.sleep(.001)
    assert q.finished==2
finally:t.release.set();p.close()
print('PASS refill capacity backpressure preserves compute and independent upload')

q=Queue();t=Transport();p=BlockPipeline(q,t,lambda job:{})
status_started=threading.Event();status_release=threading.Event()
def stalled_status():
    status_started.set()
    assert status_release.wait(5)
    raise TimeoutError('Status connection lost')
t.refresh_status=stalled_status
try:
    p.poll_status();assert status_started.wait(2)
    p.poll_control(lambda:{'enabled':False})
    deadline=time.monotonic()+2
    while not p.control.done() and time.monotonic()<deadline:time.sleep(.001)
    reply=p.poll_control(lambda:(_ for _ in ()).throw(AssertionError('Extra heartbeat')))
    assert reply=={'enabled':False} and not p.status.done()
    assert not p.tick(allow_compute=reply['enabled']) and q.finished==0
    status_release.set()
    deadline=time.monotonic()+2
    while not p.status.done() and time.monotonic()<deadline:time.sleep(.001)
    p.poll_status()
    assert p.last_error=='TimeoutError' and p.status is None
finally:status_release.set();t.release.set();p.close()
print('PASS disabled heartbeat applied while reservation status is stalled or fails')

import tempfile,copy
from block_queue import BlockQueue
from search.work_block import FORMAT
from search.crib_work import run
import worker
for lanes in (2,3,4):
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'parallel';owner=dict(server='isolated',device_id='device')
        q=BlockQueue(path,owner,worker.load_state,worker.save_state,grouped=True)
        block=dict(format=FORMAT,block_id='current',engine='bounded_crib_v1',start_unit=0,end_unit=1000,
          config=dict(requires=['cpu','bounded_crib_v1'],program=dict(ciphertext='BDZGO',hypotheses=[dict(text='BD',legal_clean_offsets=[0])],chunk=3,ordinal_base=0,candidate_limit=3)))
        q.add(block,valid_for_seconds=7200);other=copy.deepcopy(block);other['block_id']='next';q.add(other,valid_for_seconds=7200)
        together=threading.Barrier(lanes);started=set();lock=threading.Lock()
        def compute(envelope):
            unit=envelope['start_unit']
            with lock:
                assert unit not in started;started.add(unit)
            if unit<lanes:together.wait(timeout=3)
            if unit==0:
                assert p.stop_event.wait(5)
                raise InterruptedError('Stopped before completion')
            return run(envelope)
        p=BlockPipeline(q,Transport(),compute,lanes=lanes,
                        gpu_execute=compute if lanes==3 else None)
        try:
            assert not p.tick()
            deadline=time.monotonic()+3
            while len(q.pending())!=2*(lanes-1) and time.monotonic()<deadline:time.sleep(.005)
            assert len(q.pending())==2*(lanes-1) and len(started)==2*lanes-1 and p.computing
        finally:p.close()
        recovered=BlockQueue(path,owner,worker.load_state,worker.save_state,grouped=True)
        assert len(recovered.pending())==2*(lanes-1) and not q.claims and q.reserved_bytes==0
        recovered.update_status({identity:dict(status='reserved',valid_for_seconds=7200) for identity in recovered.identities()})
        assert recovered.claim_next(lanes)[1]['start_unit']==0
        assert recovered.claim_next(lanes)[1]['start_unit']==lanes
print('PASS 2/3/4 concurrent block jobs retain completed receipts on stop and recover only the unfinished gap')
