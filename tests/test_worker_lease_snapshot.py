"""One request on new coordinators; safe control refresh on legacy servers."""
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
import worker
state={'server':'http://localhost','device_token':'test'}
settings={'cpu_percent':23,'gpu_percent':41,'allow_cpu':True,'allow_gpu':True}
for modern in (False,True):
 for enabled in (False,True):
  calls=[];runtime={}
  control={'settings':settings,'enabled':enabled,'quarantined':not enabled,'update_required':True}
  lease={'lease':None,'update_required':True}
  if modern:lease.update(control)
  def post(server,path,body,token):
   calls.append(path)
   return lease if path=='/api/lease' else control
  with patch.object(worker,'post',post),patch.object(worker,'meta',lambda runtime:{}):
   got,hb=worker.request_work(state,runtime)
  assert calls==(['/api/lease'] if modern else ['/api/lease','/api/heartbeat']),calls
  assert runtime['settings']==settings and runtime['enabled']==enabled
  assert runtime['quarantined']==(not enabled) and hb['update_required']
print('PASS combined lease snapshot, legacy fallback, settings, disabled/quarantine and update signal')
