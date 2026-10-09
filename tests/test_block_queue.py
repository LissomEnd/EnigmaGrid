import copy,json,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'worker'),str(ROOT/'solver/runtime/src')]
from block_queue import BlockQueue
from search.work_block import FORMAT
from search.crib_work import run
import worker
with tempfile.TemporaryDirectory() as folder:
    path=Path(folder)/'blocks';owner=dict(server='test',device_id='device')
    block=dict(format=FORMAT,block_id='test',engine='bounded_crib_v1',start_unit=0,end_unit=12,
      config=dict(requires=['cpu','bounded_crib_v1'],program=dict(ciphertext='BDZGO',hypotheses=[dict(text='BD',legal_clean_offsets=[0])],chunk=3,ordinal_base=0,candidate_limit=3)))
    q=BlockQueue(path,owner,worker.load_state,worker.save_state);q.add(block,valid_for_seconds=7200);q.add(block,valid_for_seconds=7200)
    before=path.read_bytes();sample=q.qualification_sample()
    assert [x['start_unit'] for x in sample]==list(range(12))
    assert path.read_bytes()==before and not q.claims and q.computing_block is None
    key,unit=q.next_unit();result=run(unit)
    assert q.qualification_sample()==[],'Qualification raced with active compute'
    def full_disk(*args):raise OSError('disk full')
    failed=BlockQueue(path,owner,worker.load_state,full_disk)
    try:failed.complete(key,0,result,.1)
    except OSError:pass
    else:raise AssertionError('Disk failure ignored')
    assert q.next_unit()[1]['start_unit']==0 and q.pending()==[]
    for n in range(8):
        key,unit=q.next_unit();assert unit['start_unit']==n
        q.complete(key,n,run(unit),.1)
        q=BlockQueue(path,owner,worker.load_state,worker.save_state)
        q.update_status({'test':dict(status='reserved',valid_for_seconds=7200)})
    assert q.next_unit() is None and len(q.pending())==8
    q.acknowledge(key,[0,2]);assert len(q.pending())==6
    assert q.next_unit()[1]['start_unit']==8
    q.acknowledge('another',[1]);assert len(q.pending())==6
    q.acknowledge(key,[0,2]);assert len(q.pending())==6
    try:BlockQueue(path,dict(server='other',device_id='device'),worker.load_state,worker.save_state).pending()
    except ValueError:pass
    else:raise AssertionError('Cross-account queue accepted')
    if sys.platform=='win32':assert json.loads(path.read_text())['_format']=='dpapi-v1'
print('PASS encrypted block cursor, atomic receipt/cursor recovery, disk failure, partial ack and account isolation')

with tempfile.TemporaryDirectory() as folder:
    path=Path(folder)/'folded';writes=[]
    def counted_save(destination,value):
        worker.save_state(destination,value);writes.append(1)
    q=BlockQueue(path,owner,worker.load_state,counted_save);q.add(block,valid_for_seconds=7200)
    key,unit=q.next_unit();q.complete(key,0,run(unit),.1)
    key,unit=q.next_unit();before=len(writes)
    q.acknowledge(key,[0]);assert q.pending()==[] and len(writes)==before
    assert len(BlockQueue(path,owner,worker.load_state,worker.save_state).pending())==1
    q.save=full_disk
    try:q.complete(key,1,run(unit),.1)
    except OSError:pass
    else:raise AssertionError('Disk failure ignored during folded completion')
    assert len(BlockQueue(path,owner,worker.load_state,worker.save_state).pending())==1
    q.save=counted_save;q.complete(key,1,run(unit),.1)
    assert len(writes)==before+1
    durable=BlockQueue(path,owner,worker.load_state,worker.save_state).pending()
    assert len(durable)==1 and durable[0]['unit']==1
print('PASS folded acknowledgement saves once and safely replays after crash or failed save')

# The performance cache must not hide a recovery write or expose mutable state.
with tempfile.TemporaryDirectory() as folder:
    path=Path(folder)/'cached'
    cached=BlockQueue(path,owner,worker.load_state,worker.save_state);cached.add(block,valid_for_seconds=7200)
    assert cached.pending()==[]
    recovery=BlockQueue(path,owner,worker.load_state,worker.save_state)
    recovery.update_status({'test':dict(status='reserved',valid_for_seconds=7200)})
    key,unit=recovery.next_unit();recovery.complete(key,0,run(unit),.1)
    exposed=cached.pending();assert len(exposed)==1
    exposed[0]['result']['mutated_by_reader']=True;exposed.clear()
    assert len(cached.pending())==1 and 'mutated_by_reader' not in cached.pending()[0]['result']
    def committed_then_failed(destination,value):
        worker.save_state(destination,value)
        raise OSError('Error reported after atomic replacement')
    cached.save=committed_then_failed
    key,unit=cached.next_unit()
    try:cached.complete(key,1,run(unit),.1)
    except OSError:pass
    else:raise AssertionError('Expected reported persistence failure')
    assert len(cached.pending())==2 and cached.next_unit()[1]['start_unit']==2
    replacement=worker.load_state(path);replacement['owner']=dict(server='other',device_id='device')
    worker.save_state(path,replacement)
    try:cached.pending()
    except ValueError:pass
    else:raise AssertionError('Cached state concealed account replacement')
print('PASS cache invalidation after recovery, post-commit failure, mutable result isolation and account replacement')

# Status refresh and prefetch use independent threads. A response for the old
# queue must not reject or retire a block added while HTTP was in flight.
from block_transport import BlockTransport
with tempfile.TemporaryDirectory() as folder:
    q=BlockQueue(Path(folder)/'race',owner,worker.load_state,worker.save_state)
    q.add(block,valid_for_seconds=7200)
    second=copy.deepcopy(block);second['block_id']='next'
    def request(endpoint,payload):
        assert payload['blocks']==['test']
        q.add(second,valid_for_seconds=7200)
        return {'blocks':[{'block_id':'test','status':'expired','valid_for_seconds':0}]}
    BlockTransport(q,request).refresh_status()
    assert q.next_unit()[0]=='next'
    assert q.releasable()==['test']
    assert q.identities()==['test','next']
print('PASS status response racing with next-block prefetch')

with tempfile.TemporaryDirectory() as folder:
    q=BlockQueue(Path(folder)/'terminal-replay',owner,worker.load_state,worker.save_state)
    identity=q.allocation_request()
    q.add(block,valid_for_seconds=7200)  # Crash after descriptor write, before request ID was cleared.
    key,unit=q.next_unit();q.complete(key,unit['start_unit'],run(unit),.1)
    before=q.pending()
    q.allocation_retired(identity,block)
    assert q.pending()==before and q.next_unit() is None
    assert q.allocation_request()!=identity
    assert q.releasable()==[]  # Receipt cannot be discarded to release the block.
print('PASS terminal allocation replay preserves pending results atomically')

with tempfile.TemporaryDirectory() as folder:
    q=BlockQueue(Path(folder)/'groups',owner,worker.load_state,worker.save_state,grouped=True)
    large=copy.deepcopy(block);large['end_unit']=100;q.add(large,valid_for_seconds=7200)
    for ordinal in range(64):
        key,unit=q.next_unit();q.complete(key,ordinal,run(unit),.05)
    assert q.next_unit() is None and len(q.pending())==64
    calls=[]
    def grouped_request(path,payload):
        assert path=='/api/work-blocks/result-groups'
        assert len(payload['groups'])<=8 and all(len(g)<=8 for g in payload['groups'])
        calls.append(payload)
        # Partial acknowledgement leaves every other original unit durable.
        return dict(block_id='test',results=[dict(unit=r['unit'],status='received')
                    for g in payload['groups'] for r in g if r['unit']%2==0])
    assert BlockTransport(q,grouped_request,grouped=True).upload()==32
    assert len(calls)==1 and len(q.pending())==32
    legacy=BlockQueue(q.path,owner,worker.load_state,worker.save_state)
    assert legacy.next_unit() is None
    legacy.acknowledge('test',[r['unit'] for r in legacy.pending()[:8]])
    assert len(legacy.pending())==24  # Safe drain after capability downgrade.
print('PASS negotiated grouped outbox bound, partial acknowledgements and downgrade drain')

# Reserve result bytes before computation; concurrent prefetch must not consume
# them, and a failed persistence must leave both the cursor and reservation.
import block_queue as queue_module
with tempfile.TemporaryDirectory() as folder:
    q=BlockQueue(Path(folder)/'byte-bound',owner,worker.load_state,worker.save_state,grouped=True)
    q.add(block,valid_for_seconds=7200)
    original_limit=queue_module.MAX_BYTES
    used=len(json.dumps(q._read(),allow_nan=False).encode())
    try:
        queue_module.MAX_BYTES=used+queue_module.RESULT_RESERVE-1
        assert q.next_unit() is None and not q.pending()
        queue_module.MAX_BYTES+=1
        key,unit=q.next_unit()
        try:q.add(second,valid_for_seconds=7200)
        except ValueError:pass
        else:raise AssertionError('Prefetch consumed reserved result space')
        assert q.identities()==['test']
        saved=q.save;q.save=full_disk
        try:q.complete(key,0,run(unit),.1)
        except OSError:pass
        else:raise AssertionError('Persistence failure ignored')
        assert q.reserved_bytes==queue_module.RESULT_RESERVE and not q.pending()
        q.save=saved;q.complete(key,0,run(unit),.1)
        assert q.reserved_bytes==0 and len(q.pending())==1
    finally:queue_module.MAX_BYTES=original_limit
print('PASS result byte reservation, concurrent prefetch exclusion and failed-write retry')

with tempfile.TemporaryDirectory() as folder:
    q=BlockQueue(Path(folder)/'active-release',owner,worker.load_state,worker.save_state)
    q.add(block,valid_for_seconds=7200);key,unit=q.next_unit()
    q.update_status({key:dict(status='expired',valid_for_seconds=0)})
    assert not q.releasable()
    try:q.released(key)
    except ValueError:pass
    else:raise AssertionError('Released descriptor during computation')
    q.complete(key,unit['start_unit'],run(unit),.1)
    assert len(q.pending())==1 and not q.releasable()
    q.acknowledge(key,[unit['start_unit']]);assert q.releasable()==[key]
print('PASS expiry during computation retains descriptor and unacknowledged receipt')

for lanes in (2,4):
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'concurrent'
        q=BlockQueue(path,owner,worker.load_state,worker.save_state);q.add(block,valid_for_seconds=7200)
        claims=[q.claim_next(lanes) for _ in range(lanes)]
        assert [entry[1]['start_unit'] for entry in claims]==list(range(lanes))
        assert q.claim_next(lanes) is None
        assert q.monitor_snapshot()['ready_units']==12-lanes
        saved=q.save;q.save=full_disk
        key,unit=claims[-1]
        try:q.complete(key,unit['start_unit'],run(unit),.1)
        except OSError:pass
        else:raise AssertionError('Failed concurrent write accepted')
        assert q.reserved_bytes==lanes*queue_module.RESULT_RESERVE and not q.pending()
        q.save=saved
        for key,unit in reversed(claims[1:]):q.complete(key,unit['start_unit'],run(unit),.1)
        assert worker.load_state(path)['version']==2 and q.remaining()[0]==12-(lanes-1)
        q.release_claim('test',0);q.acknowledge('test',list(range(1,lanes)))
        recovered=BlockQueue(path,owner,worker.load_state,worker.save_state)
        assert not recovered.pending()
        assert recovered.claim_next(lanes) is None  # Recovery needs fresh server status.
        recovered.update_status({'test':dict(status='reserved',valid_for_seconds=7200)})
        first=recovered.claim_next(lanes);second=recovered.claim_next(lanes)
        assert first[1]['start_unit']==0 and second[1]['start_unit']==lanes
        recovered.complete(first[0],0,run(first[1]),.1)
        assert worker.load_state(path)['version']==1
        recovered.update_status({'test':dict(status='expired',valid_for_seconds=0)})
        recovered.acknowledge('test',[0]);assert not recovered.releasable()
        recovered.release_claim('test',lanes);assert recovered.releasable()==['test']
print('PASS 2/4-lane out-of-order durable completion, failed save, acknowledged gap recovery and safe release')

with tempfile.TemporaryDirectory() as folder:
    q=BlockQueue(Path(folder)/'gap-bound',owner,worker.load_state,worker.save_state);q.add(block,valid_for_seconds=7200)
    first=q.claim_next(2);assert first[1]['start_unit']==0
    for unit in range(1,8):
        key,envelope=q.claim_next(2);assert envelope['start_unit']==unit
        q.complete(key,unit,run(envelope),.1);q.acknowledge(key,[unit])
    assert not q.pending() and q.claim_next(2) is None
    q.complete('test',0,run(first[1]),.1)
    assert q.claim_next(2)[1]['start_unit']==8
print('PASS acknowledged completions cannot grow an unfinished gap without bound')

with tempfile.TemporaryDirectory() as folder:
    path=Path(folder)/'expired';q=BlockQueue(path,owner,worker.load_state,worker.save_state);q.add(block,valid_for_seconds=7200)
    key,envelope=q.next_unit();receipt=run(envelope);q.complete(key,0,receipt,.1)
    original=q.save;q.save=full_disk
    try:q.archive_expired(key,[0])
    except OSError:pass
    else:raise AssertionError('Failed archive lost receipt')
    q.save=original;assert len(q.pending())==1
    q.archive_expired(key,[0]);assert not q.pending() and q.releasable()==[key]
    recovered=BlockQueue(path,owner,worker.load_state,worker.save_state)
    preserved=worker.load_state(path)['expired_receipts']
    assert len(preserved)==1 and preserved[0]['result']==receipt
    snapshot=recovered.monitor_snapshot()
    assert snapshot['expired_results']==1 and snapshot['outbox_count']==0 and snapshot['ready_units']==0
    recovered.released(key);assert not recovered.identities()
    recovered.add(block,valid_for_seconds=7200);assert recovered.next_unit() is not None
print('PASS encrypted expired receipt archive, failed write retention and resumed allocation')

with tempfile.TemporaryDirectory() as folder:
    from block_transport import BlockTransport,ReceiptRejected
    q=BlockQueue(Path(folder)/'transport-expiry',owner,worker.load_state,worker.save_state);q.add(block,valid_for_seconds=7200)
    key,envelope=q.next_unit();q.complete(key,0,run(envelope),.1)
    mode=['invalid']
    def reply(route,payload):
        if route.endswith('/release'):return dict(block_id=key,released=True)
        rows=[dict(unit=0,status='expired' if mode[0]!='conflict' else 'conflict')]
        if mode[0]=='invalid':rows.append(dict(unit=99,status='received'))
        return dict(block_id=key,results=rows)
    transport=BlockTransport(q,reply)
    try:transport.upload()
    except ValueError:pass
    else:raise AssertionError('Malformed expiry response accepted')
    assert len(q.pending())==1 and not worker.load_state(q.path).get('expired_receipts')
    mode[0]='conflict'
    try:transport.upload()
    except ReceiptRejected:pass
    else:raise AssertionError('Conflict did not stop')
    assert len(q.pending())==1
    mode[0]='expired';assert transport.upload()==0 and not q.pending()
    assert len(worker.load_state(q.path)['expired_receipts'])==1 and not q.identities()
print('PASS validated per-item expiry archive; malformed replies and conflicts preserve pending receipt')
