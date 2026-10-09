import sys
import threading
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'worker'),str(ROOT/'solver/runtime/src')]
from block_pipeline import BlockPipeline

class Queue:
    max_pending=32
    def __init__(self):
        self.next=0;self.claims=set();self.receipts=[];self.lock=threading.Lock()
    def remaining(self):return 100,1
    def pending(self):return []
    def claim_prefetched(self,lanes):
        with self.lock:
            if self.next>=12:return None
            unit=self.next;self.next+=1;self.claims.add(unit)
            return 'block',dict(start_unit=unit)
    def complete_batch(self,items):
        with self.lock:
            for _,unit,result,_ in items:
                assert result==dict(unit=unit)
                self.receipts.append(unit)
    def release_claim(self,_,unit):
        with self.lock:self.claims.discard(unit)

class Transport:
    def allocate(self):return {'block':None,'wait_reason':'none'}
    def upload(self):return 0

q=Queue();routes={'cpu':[],'gpu':[]};lock=threading.Lock()
def execute(route):
    def run(envelope):
        time.sleep(.006 if route=='cpu' else .009)
        with lock:routes[route].append(envelope['start_unit'])
        return dict(unit=envelope['start_unit'])
    return run
p=BlockPipeline(q,Transport(),execute('cpu'),lanes=3,gpu_execute=execute('gpu'))
try:
    deadline=time.monotonic()+3
    while len(q.receipts)<12 and time.monotonic()<deadline:
        p.tick();time.sleep(.002)
    assert sorted(q.receipts)==list(range(12))
    assert routes['cpu'] and routes['gpu']
    assert set(routes['cpu']).isdisjoint(routes['gpu'])
    assert p.gpu_solvers is not None and p.lanes==3
finally:p.close()
assert not q.claims
print('PASS distinct CPU/GPU job lanes keep one receipt per original envelope and release all claims')
