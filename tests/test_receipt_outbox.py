"""Concurrent append/ack and legacy recovery without production state."""
import sys,tempfile,threading
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
import worker
from receipt_outbox import ReceiptOutbox,MAX_BYTES
state={'server':'https://example.invalid','device_id':'test','device_token':'test'}
with tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/'client.json'
    q=worker.result_outbox(path,state)
    payload=lambda i:{'lease_id':str(i),'work_token':'test','result':{'n':i}}
    threads=[threading.Thread(target=lambda i=i:worker.result_outbox(path,state).append(payload(i))) for i in range(8)]
    for t in threads:t.start()
    for t in threads:t.join()
    assert len(q.pending())==8
    try:q.append(payload(8))
    except RuntimeError:pass
    else:raise AssertionError('Count limit bypassed')
    before=q.pending()
    with patch.object(q,'save',side_effect=OSError('disk full')):
        try:q.acknowledge('0')
        except OSError:pass
        else:raise AssertionError('Write failure ignored')
    assert q.pending()==before
    q.acknowledge('0');q.append(payload(8))
    assert {p['lease_id'] for p in q.pending()}==set(map(str,range(1,9)))
    # A network failure after a successful prefix keeps the remaining suffix.
    with patch.object(worker,'post',side_effect=[{'ok':True},TimeoutError()]):
        try:worker.deliver_pending(path,state)
        except TimeoutError:pass
        else:raise AssertionError()
    assert len(q.pending())==7
    with patch.object(worker,'post',return_value={'ok':True,'duplicate':True}):worker.deliver_pending(path,state)
    assert not q.pending()
    large={**payload(9),'result':'x'*MAX_BYTES}
    try:q.append(large)
    except RuntimeError:pass
    else:raise AssertionError('Byte limit bypassed')
    assert q.pending()==[]
    from receipt_outbox import OutboxUploader
    entered=threading.Event();release=threading.Event()
    def blocked_send(payload):
        entered.set();assert release.wait(2)
        raise TimeoutError('Uncertain acknowledgement')
    q.append(payload(10));sender=OutboxUploader(q,blocked_send)
    try:
        assert entered.wait(1)
        q.append(payload(11))
        assert len(q.pending())==2,'Blocked upload must not block durable computation output'
    finally:release.set();sender.close()
    assert len(q.pending())==2,'Shutdown lost uncertain receipts'
    q.confirm('10')
    assert len(worker.result_outbox(path,state).pending())==2,'Crash must replay the accepted predecessor until durable replacement'
    with patch.object(q,'save',side_effect=OSError('disk full')):
        try:q.append(payload(12))
        except OSError:pass
        else:raise AssertionError('Failed coalesced write accepted')
    assert len(worker.result_outbox(path,state).pending())==2
    with patch.object(q,'save',wraps=q.save) as writes:
        q.append(payload(12))
        assert writes.call_count==1
    assert {x['lease_id'] for x in worker.result_outbox(path,state).pending()}=={'11','12'}
print('PASS concurrent outbox, bounded size, failed-write retention and partial replay')

with tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/'client.json'
    q=worker.result_outbox(path,state)
    peer=worker.result_outbox(path,state)
    for i in range(8):assert q.reserve(str(i))
    assert not peer.has_capacity() and not peer.reserve('8')
    try:peer.append(payload(8))
    except RuntimeError:pass
    else:raise AssertionError('Unreserved producer stole reserved capacity')
    with patch.object(q,'save',side_effect=OSError('disk full')):
        try:q.append(payload(0))
        except OSError:pass
        else:raise AssertionError('Write failure ignored')
    assert not peer.reserve('0') and len(q.reserved)==8
    errors=[]
    def producer(i):
        try:peer.append(payload(i))
        except Exception as e:errors.append(e)
    threads=[threading.Thread(target=producer,args=(i,)) for i in range(8)]
    for thread in threads:thread.start()
    for thread in threads:thread.join()
    assert not errors and len(q.pending())==8 and not q.reserved
    q.acknowledge('0');assert peer.reserve('8')
    peer.release_reservation('8')
    assert q.has_capacity() and len(q.pending())==7
print('PASS pre-compute reservations across queue instances, concurrent producers and failed-write retention')
