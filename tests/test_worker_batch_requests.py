import sys,time,urllib.error,tempfile
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
import worker

def main():
 state={'server':'https://example.invalid','device_token':'test'}
 settings={'cpu_percent':50,'gpu_percent':0,'allow_cpu':True,'allow_gpu':False}
 controls={'settings':settings,'enabled':True,'quarantined':False}
 leases=[{'id':str(i),'work_token':'test','expires_at':time.time()+900} for i in range(8)]
 runtime={'_batch_requests':True};calls=[]
 def post(server,path,payload,token):
  calls.append(path)
  return {'leases':leases,**controls} if path=='/api/leases' else controls
 with patch.object(worker,'post',side_effect=post),patch.object(worker,'meta',return_value={}):
  assert [worker.request_work(state,runtime)[0]['lease']['id'] for _ in range(8)]==list(map(str,range(8)))
  assert calls==['/api/leases']
  worker.request_work(state,runtime)
  runtime['_batch_controls_at']=0
  controls['enabled']=False
  assert worker.request_work(state,runtime)[0]['lease'] is None
  assert not runtime['_lease_queue'] and calls[-1]=='/api/heartbeat'
 controls['enabled']=True
 # A long pause invalidates the local reservation snapshot before dispatch.
 runtime={'_batch_requests':True};calls=[]
 with patch.object(worker,'post',side_effect=post),patch.object(worker,'meta',return_value={}):
  worker.request_work(state,runtime)
  runtime['_lease_queue'][0]={**runtime['_lease_queue'][0],'expires_at':0}
  assert worker.request_work(state,runtime)[0]['lease']['id']=='0'
  assert calls==['/api/leases','/api/leases']
  runtime['_batch_controls_at']=0
  controls['update_required']=True
  assert worker.request_work(state,runtime)[0]['lease'] is None
  assert not runtime['_lease_queue']
 controls.pop('update_required')
 for invalid in (leases+[leases[0]],[leases[0],leases[0]],[{**leases[0],'expires_at':float('nan')} ],[{**leases[0],'expires_at':0}]):
  with patch.object(worker,'post',return_value={'leases':invalid,**controls}),patch.object(worker,'meta',return_value={}):
   try:worker.request_work(state,{'_batch_requests':True})
   except ValueError:pass
   else:raise AssertionError('Invalid batch accepted')
 runtime={'_batch_requests':True};calls=[]
 def legacy(server,path,payload,token):
  calls.append(path)
  if path=='/api/leases':raise urllib.error.HTTPError(server,404,'unsupported',{},None)
  return {'lease':None,**controls}
 with patch.object(worker,'post',side_effect=legacy),patch.object(worker,'meta',return_value={}):
  worker.request_work(state,runtime);worker.request_work(state,runtime)
 assert calls==['/api/leases','/api/lease','/api/lease']
 # Network/server errors must not silently switch protocols or lose reservations.
 runtime={'_batch_requests':True}
 with patch.object(worker,'post',side_effect=urllib.error.HTTPError(state['server'],503,'unavailable',{},None)),patch.object(worker,'meta',return_value={}):
  try:worker.request_work(state,runtime)
  except urllib.error.HTTPError as error:assert error.code==503
  else:raise AssertionError('Server failure hidden')
 assert runtime['_batch_requests']
 # Exercise the complete worker loop: eight completions, one allocation request,
 # durable outbox drained, then an explicit stop with no additional allocation.
 with tempfile.TemporaryDirectory() as tmp:
  complete=[];allocated=[]
  full=[{**l,'engine':'bounded_crib_v1','resource_class':'cpu','resource_percent':50,
         'purpose':'validation','segment_label':'test','start_unit':i,'end_unit':i+1} for i,l in enumerate(leases)]
  def transport(server,path,payload,token,**kwargs):
   if path=='/api/leases':allocated.append(path);return {'leases':full,**controls}
   if path=='/api/complete':complete.append(payload['lease_id']);return {'ok':True}
   return controls
  path=Path(tmp)/'client.json'
  with patch.object(worker,'post',side_effect=transport),patch.object(worker,'meta',return_value={}), \
       patch.object(worker,'UpdateManager',None),patch.object(worker,'acquire_worker_mutex',return_value=True), \
       patch.object(worker,'publish_health'),patch.object(worker,'apply_cpu_limit',return_value=2), \
       patch.object(worker,'execute',return_value=({'receipt':'test'},1)), \
       patch.object(worker,'read_control',side_effect=lambda p:dict(stop_requested=len(complete)==8,paused=False,check_update=False)):
   assert worker.work(SimpleNamespace(state=str(path),once=False,idle_seconds=1),{**state,'device_id':'test'})==0
  assert complete==list(map(str,range(8))) and len(allocated)==1
  assert not worker.pending_path(path).exists()
 print('PASS bounded batch consumption, controls refresh, revocation, malformed batches, legacy fallback')

if __name__=='__main__':main()
