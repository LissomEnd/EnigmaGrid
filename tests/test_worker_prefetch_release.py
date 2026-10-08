"""Allocation overlaps computation; stop drains and releases late assignments."""
import sys, time, tempfile, threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
import worker

with tempfile.TemporaryDirectory() as tmp:
    state={'server':'https://example.invalid','device_id':'test','device_token':'test'}
    q=worker.result_outbox(Path(tmp)/'client.json',state)
    assert q.reserve('running')
    runtime={'_batch_requests':True,'_lease_queue':[dict(id='already-queued',work_token='test',expires_at=time.time()+600)], '_mean_job_seconds':.05,'_allocation_seconds':.2, '_uploader':SimpleNamespace(queue=q)}
    entered=threading.Event();finish=threading.Event();released=[]
    controls={'enabled':True,'quarantined':False,'settings':{'cpu_percent':100}}
    def post(server,path,payload,token,**kwargs):
        if path=='/api/leases':
            entered.set()
            assert finish.wait(3),'Client waited for allocation before computing'
            return dict(controls,leases=[dict(id=i,work_token='test',expires_at=time.time()+600)
                                        for i in ('running','unused')])
        if path=='/api/leases/release':
            released.extend(x['lease_id'] for x in payload['leases'])
            return {'ok':True}
        raise AssertionError(path)
    with patch.object(worker,'post',side_effect=post),patch.object(worker,'meta',return_value={}),patch.object(worker,'get_json',return_value={'release_leases':True}):
        try:
            worker.start_batch_prefetch(state,runtime)
            assert entered.wait(1)
            # Simulate a completed and acknowledged receipt while HTTP is in flight.
            q.append({'lease_id':'running','work_token':'test','result':{}})
            q.acknowledge('running')
            finish.set()
            assert worker.release_unused_work(state,runtime)
            assert released==['already-queued','unused'],released
            assert not runtime['_lease_queue'] and not runtime.get('_batch_pending')
        finally:
            finish.set()
            runtime['_allocation_pool'].shutdown(wait=True)
print('PASS early allocation with nonempty queue, acknowledgement race excludes replay, stop drains and releases both queues')

# A delayed allocation cannot undo revocation/settings delivered by heartbeat.
with tempfile.TemporaryDirectory() as tmp:
    q=worker.result_outbox(Path(tmp)/'client.json',state)
    assert q.reserve('running')
    runtime={'_batch_requests':True,'_lease_queue':[], '_uploader':SimpleNamespace(queue=q)}
    old_reply=dict(controls,leases=[dict(id='unused',work_token='test',expires_at=time.time()+600)])
    revoked=dict(controls,enabled=False,settings={'cpu_percent':25})
    paths=[]
    def delayed(server,path,payload,token,**kwargs):
        paths.append(path)
        return old_reply if path=='/api/leases' else revoked
    with patch.object(worker,'post',side_effect=delayed),patch.object(worker,'meta',return_value={}):
        try:
            worker.start_batch_prefetch(state,runtime)
            runtime['_batch_pending'][0].result(timeout=2)
            worker.apply_coordinator_state(revoked,runtime)
            got,control=worker.request_batch_work(state,runtime)
            assert got['lease'] is None and not runtime['enabled']
            assert runtime['settings']['cpu_percent']==25
            assert paths==['/api/leases','/api/heartbeat'],paths
        finally:runtime['_allocation_pool'].shutdown(wait=True)
print('PASS late allocation cannot overwrite newer coordinator revocation or settings')
