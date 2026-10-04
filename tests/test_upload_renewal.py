"""Keep lease renewal alive until completion upload succeeds or fails."""
import sys,tempfile,threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
import worker

def main():
 for failure in (False,True):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'state.json'
   state=dict(server='https://example.invalid',device_id='test',device_token='test')
   settings=dict(allow_cpu=True,cpu_percent=50,allow_gpu=False,gpu_percent=0)
   runtime=dict(enabled=True,settings=settings)
   lease=dict(id='lease',work_token='work',engine='bounded_crib_v1',purpose='validation',
              resource_class='cpu',resource_percent=50,segment_label='test',start_unit=0,end_unit=1)
   started=threading.Event();finished=threading.Event();events=[]
   def renew(stop,*args):
    events.append(stop);started.set();stop.wait(5);finished.set()
   def upload(*args,**kwargs):
    assert started.wait(2)
    assert not events[0].is_set(),'Renewal stopped before upload acknowledgement'
    assert worker.pending_path(path).exists(),'Upload preceded durable save'
    if failure:raise TimeoutError('injected slow acknowledgement')
    return {'ok':True}
   with patch.object(worker,'acquire_worker_mutex',return_value=True), \
        patch.object(worker,'UpdateManager',None),patch.object(worker,'publish_health'), \
        patch.object(worker,'request_work',return_value=({'lease':lease},{})), \
        patch.object(worker,'apply_cpu_limit',return_value=2), \
        patch.object(worker,'execute',return_value=({'receipt':'test'},1)), \
        patch.object(worker,'meta',return_value={}), \
        patch.object(worker,'heartbeat_loop',side_effect=renew), \
        patch.object(worker,'post',side_effect=upload):
    assert worker._work(SimpleNamespace(state=str(path),once=True,idle_seconds=1),state,runtime)==(2 if failure else 0)
   assert finished.wait(1) and events[0].is_set(),'Renewal leaked after upload'
   assert worker.pending_path(path).exists()==failure
 print('PASS upload renewal lifetime, cleanup and durable timeout recovery')

if __name__=='__main__':main()
