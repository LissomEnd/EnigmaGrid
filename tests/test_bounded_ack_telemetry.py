"""Isolated ACK accounting, replay and mixed-engine telemetry regression."""
import copy
import json
import sys
import tempfile
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(REPO/'worker'),str(REPO/'solver/runtime/src')]
from block_queue import AckCounter,BlockQueue
from block_transport import BlockTransport
from performance_telemetry import DeviceTelemetry
from search.crib_work import run
from search.work_block import FORMAT

class Storage:
    def __init__(self):self.value=None;self.fail_next=False
    def load(self,_path):return copy.deepcopy(self.value)
    def save(self,_path,value):
        if self.fail_next:self.fail_next=False;raise OSError('Injected atomic-save failure')
        self.value=copy.deepcopy(value)

def block(name):
    return dict(format=FORMAT,block_id=name,engine='bounded_crib_v1',start_unit=0,end_unit=12,
                config=dict(requires=['cpu','bounded_crib_v1'],program=dict(ciphertext='BDZGO',
                hypotheses=[dict(text='BD',legal_clean_offsets=[0])],chunk=3,ordinal_base=0,candidate_limit=3)))

def compute_one(queue):
    identity,envelope=queue.next_unit()
    queue.complete(identity,envelope['start_unit'],run(envelope),.01)

def transport(queue):
    def request(path,body):
        assert path.endswith('/result-groups'),path
        units=[row['unit'] for group in body['groups'] for row in group]
        return dict(block_id=body['block_id'],results=[dict(unit=u,status='received') for u in units])
    return BlockTransport(queue,request,grouped=True)

with tempfile.TemporaryDirectory() as folder:
    owner=dict(server='fixture',device_id='fixture')
    counter=AckCounter();store=Storage()
    queue=BlockQueue(Path(folder)/'queue',owner,store.load,store.save,grouped=True,ack_counter=counter)
    queue.add(block('first'),valid_for_seconds=7200)
    compute_one(queue)
    assert counter.value()==0
    link=transport(queue)
    assert link.upload()==1 and counter.value()==1 and queue.pending()==[]
    assert link.upload()==0 and counter.value()==1 # Replayed HTTP 200 cannot add a local ACK.

    # With another claimed unit, the accepted receipt is filtered in memory,
    # then counted only after the next successful durable save removes it.
    compute_one(queue)
    claimed=queue.claim_next(2)
    assert claimed and claimed[1]['start_unit']==2
    assert link.upload()==1 and counter.value()==1 and queue.pending()==[]
    assert link.upload()==0 and counter.value()==1
    queue.complete('first',2,run(claimed[1]),.01)
    assert counter.value()==2 and len(queue.pending())==1
    assert link.upload()==1 and counter.value()==3

    # A failed local save does not count or forget an ACK; retry may receive
    # the server's idempotent `received` response and retire it once.
    compute_one(queue)
    store.fail_next=True
    try:link.upload()
    except OSError:pass
    else:raise AssertionError('Failed durable ACK save accepted')
    assert counter.value()==3 and len(queue.pending())==1
    assert link.upload()==1 and counter.value()==4

    runtime=dict(active_engine='portable_event_v1',_legacy_receipts_acked=1,
                 _bounded_ack_counter=counter)
    telemetry=DeviceTelemetry(runtime,lambda:{},lambda *_:None,lambda:{},lambda *_:{},'0.5.0')
    snapshot=telemetry._snapshot()
    assert snapshot['receipts_acked']==1 and snapshot['block_receipts_acked']==4
    telemetry._add_sample({},snapshot)
    assert telemetry._finish(telemetry.current)['receipts_acked']==5
    telemetry._add_sample({},telemetry._snapshot())
    assert telemetry._finish(telemetry.current)['receipts_acked']==5

    # The shared counter continues across block-pipeline replacement while
    # legacy work is active. It remains distinct from the legacy counter.
    replacement=BlockQueue(Path(folder)/'queue',owner,store.load,store.save,
                           grouped=True,ack_counter=counter)
    replacement.update_status({'first':dict(status='reserved',valid_for_seconds=7200)})
    compute_one(replacement)
    assert transport(replacement).upload()==1 and counter.value()==5
    runtime['_legacy_receipts_acked']=2
    telemetry._add_sample({},telemetry._snapshot())
    assert telemetry._finish(telemetry.current)['receipts_acked']==7

    compute_one(replacement)
    def expired(path,body):
        if path.endswith('/result-groups'):
            unit=body['groups'][0][0]['unit']
            return dict(block_id='first',results=[dict(unit=unit,status='expired')])
        assert path.endswith('/release')
        return dict(block_id='first',released=True)
    assert BlockTransport(replacement,expired,grouped=True).upload()==0
    assert counter.value()==5 # Explicit expiry is archived, not an ACK.

    crash_store=Storage();before_crash=AckCounter()
    interrupted=BlockQueue(Path(folder)/'crash',owner,crash_store.load,crash_store.save,
                           grouped=True,ack_counter=before_crash)
    interrupted.add(block('crash-block'),valid_for_seconds=7200)
    compute_one(interrupted)
    hold=interrupted.claim_next(2)
    assert hold and transport(interrupted).upload()==1
    assert before_crash.value()==0 and interrupted.pending()==[]
    # A process crash loses the unpersisted in-memory confirmation. Its saved
    # receipt is replayed and counted by the successor only after removal.
    after_crash=AckCounter()
    resumed=BlockQueue(Path(folder)/'crash',owner,crash_store.load,crash_store.save,
                       grouped=True,ack_counter=after_crash)
    assert len(resumed.pending())==1 and transport(resumed).upload()==1
    assert before_crash.value()==0 and after_crash.value()==1

print('PASS bounded ACK counted once after durable removal; deferred, retry and mixed-engine telemetry')
