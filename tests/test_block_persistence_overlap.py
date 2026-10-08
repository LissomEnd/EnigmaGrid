"""Bounded compute overlaps durable storage without exposing volatile receipts."""
import copy,sys,tempfile,threading,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'worker'),str(ROOT/'solver/runtime/src')]
import worker
from block_queue import BlockQueue
from block_pipeline import BlockPipeline
from search.work_block import FORMAT
from search.crib_work import run

owner=dict(server='isolated',device_id='device')
block=dict(format=FORMAT,block_id='current',engine='bounded_crib_v1',start_unit=0,end_unit=1000,
 config=dict(requires=['cpu','bounded_crib_v1'],program=dict(ciphertext='BDZGO',hypotheses=[dict(text='BD',legal_clean_offsets=[0])],chunk=3,ordinal_base=0,candidate_limit=3)))
class Transport:
    def allocate(self):raise AssertionError('Unexpected allocation')
    def upload(self):return 0

for lanes in (1,2,4):
 with tempfile.TemporaryDirectory() as folder:
    path=Path(folder)/'queue';entered=threading.Event();release=threading.Event();all_computed=threading.Event();computed=[]
    def save(destination,value):
        if value['pending']:
            entered.set();assert release.wait(5),'Test did not unblock storage'
        worker.save_state(destination,value)
    q=BlockQueue(path,owner,worker.load_state,save,grouped=True)
    q.add(block);second=copy.deepcopy(block);second['block_id']='next';q.add(second)
    lock=threading.Lock()
    def compute(envelope):
        result=run(envelope)
        with lock:
            computed.append(envelope['start_unit'])
            if len(computed)==2*lanes:all_computed.set()
        return result
    p=BlockPipeline(q,Transport(),compute,lanes=lanes)
    p.tick();assert entered.wait(2)
    assert all_computed.wait(2),'Solver waited for first durable write before second job'
    assert len(computed)==2*lanes and len(set(computed))==2*lanes
    # Read durable storage directly: volatile completions must not be uploadable.
    assert worker.load_state(path)['pending']==[]
    closer=ThreadPoolExecutor(max_workers=1)
    stop=closer.submit(p.close)
    try:
        time.sleep(.03);assert not stop.done(),'Stop returned before receipt flush'
        release.set();stop.result(timeout=3)
    finally:release.set();closer.shutdown(wait=True)
    recovered=BlockQueue(path,owner,worker.load_state,worker.save_state,grouped=True)
    assert sorted(x['unit'] for x in recovered.pending())==list(range(2*lanes))
    assert recovered.claim_next(lanes)[1]['start_unit']==2*lanes
    assert not q.claims and q.reserved_bytes==0
print('PASS 1/2/4 physical lanes compute a bounded second job during blocked storage; stop flushes every result')

for failure_type in (OSError,RuntimeError):
 with tempfile.TemporaryDirectory() as folder:
    path=Path(folder)/'queue';entered=threading.Event();release=threading.Event();computed=threading.Event();count=[]
    def failed_save(destination,value):
        if value['pending']:
            entered.set();assert release.wait(5)
            raise failure_type('Injected persistence failure')
        worker.save_state(destination,value)
    q=BlockQueue(path,owner,worker.load_state,failed_save,grouped=True)
    q.add(block);second=copy.deepcopy(block);second['block_id']='next';q.add(second)
    def compute(envelope):
        result=run(envelope);count.append(envelope['start_unit'])
        if len(count)==2:computed.set()
        return result
    p=BlockPipeline(q,Transport(),compute,lanes=1);p.tick()
    assert entered.wait(2) and computed.wait(2)
    release.set()
    try:p.close()
    except failure_type:pass
    else:raise AssertionError('Persistence failure concealed on close')
    recovered=BlockQueue(path,owner,worker.load_state,worker.save_state)
    assert not recovered.pending() and recovered.next_unit()[1]['start_unit']==0
    assert not q.claims and q.reserved_bytes==0
print('PASS storage failures propagate on close and restart replays unsaved units')

with tempfile.TemporaryDirectory() as folder:
 path=Path(folder)/'queue';writes=[]
 def save(destination,value):worker.save_state(destination,value);writes.append(1)
 q=BlockQueue(path,owner,worker.load_state,save,grouped=True);q.add(block)
 claims=[q.claim_prefetched(2) for _ in range(4)]
 assert [x[1]['start_unit'] for x in claims]==[0,1,2,3] and q.claim_prefetched(2) is None
 values=[(key,e['start_unit'],run(e),.1) for key,e in claims]
 before=path.read_bytes();number=len(writes)
 invalid=list(values);invalid[2]=('missing',2,values[2][2],.1)
 try:q.complete_batch(invalid)
 except ValueError:pass
 else:raise AssertionError('Invalid batch partially accepted')
 assert path.read_bytes()==before and len(q.claims)==4 and len(writes)==number
 q.complete_batch(list(reversed(values)))
 assert len(writes)==number+1 and not q.claims and q.reserved_bytes==0
 recovered=BlockQueue(path,owner,worker.load_state,worker.save_state,grouped=True)
 assert len(recovered.pending())==4 and recovered.next_unit()[1]['start_unit']==4
 assert worker.load_state(path)['version']==1
print('PASS completion batch validates all rows before one atomic cursor/receipt save')
