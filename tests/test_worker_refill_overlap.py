"""Real worker loop refills while its independent uploader is blocked."""
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
import worker

controls={'enabled':True,'quarantined':False,'settings':{'cpu_percent':100,
          'gpu_percent':100,'allow_cpu':True,'allow_gpu':True}}
upload_entered=threading.Event()
second_computed=threading.Event()
computed=[];uploaded=[];allocations=[];overlap=[]
deadline=time.monotonic()+10
leases=[dict(id=str(i),work_token='test',expires_at=time.time()+900,
             engine='bounded_crib_v1',resource_class='cpu',resource_percent=100,
             purpose='validation',segment_label='test',start_unit=i,end_unit=i+1)
        for i in range(2)]

def transport(server,path,payload,token,**kwargs):
    if path=='/api/leases':
        allocations.append(path)
        # Replay the uploading lease on refill, just as the real coordinator can.
        return dict(controls,leases=leases[:1] if len(allocations)==1 else leases)
    if path=='/api/complete':
        if payload['lease_id']=='0':
            upload_entered.set()
            overlap.append(second_computed.wait(3))
        uploaded.append(payload['lease_id'])
        return {'ok':True}
    if path=='/api/leases/release':return {'ok':True,'released':[]}
    return controls

def execute(lease,*args):
    computed.append(lease['id'])
    if lease['id']=='1':
        assert upload_entered.wait(2),'Uploader never started'
        second_computed.set()
    return {'receipt':'fixture'},0

with tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/'client.json'
    with patch.object(worker,'post',side_effect=transport),patch.object(worker,'meta',return_value={}), \
         patch.object(worker,'get_json',return_value={}),patch.object(worker,'UpdateManager',None), \
         patch.object(worker,'acquire_worker_mutex',return_value=True),patch.object(worker,'publish_health'), \
         patch.object(worker,'apply_cpu_limit',return_value=2),patch.object(worker,'execute',side_effect=execute), \
         patch.object(worker,'read_control',side_effect=lambda p:dict(stop_requested=second_computed.is_set() or time.monotonic()>deadline,paused=False,check_update=False)):
        assert worker.work(SimpleNamespace(state=str(path),once=False,idle_seconds=.01),
                           {'server':'https://example.invalid','device_token':'test','device_id':'test'})==0
    assert computed==['0','1'],computed
    assert overlap==[True],'Refill waited for upload acknowledgement'
    assert len(allocations)==3,allocations
    pending=worker.result_outbox(path,{'server':'https://example.invalid','device_id':'test'}).pending()
    assert set(uploaded)|{p['lease_id'] for p in pending}=={'0','1'},'Receipt lost during stop'
print('PASS real worker refill overlaps blocked upload, replay is excluded, stop preserves receipts')
