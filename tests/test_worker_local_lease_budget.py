"""Local receipt acknowledgement lag must not overfill a reservation window."""
import sys,tempfile,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
import worker
from receipt_outbox import ReceiptOutbox
with tempfile.TemporaryDirectory() as directory:
 path=Path(directory)/'outbox.json'
 def load(p):return json.loads(p.read_text()) if p.exists() else None
 def save(p,v):p.write_text(json.dumps(v))
 q=ReceiptOutbox(path,{'server':'test','device_id':'test'},load,save)
 q.append({'lease_id':'uploading','work_token':'fixture'})
 assert q.reserve('executing')
 runtime={'_uploader':SimpleNamespace(queue=q)}
 with patch.object(worker,'meta',return_value={}):
  assert worker.batch_request_payload(runtime)=={'meta':{},'count':30}
  runtime['_new_lease_limit']=True
  assert worker.batch_request_payload(runtime)=={'meta':{},'count':32,'max_new':30}
  runtime['_lease_queue']=[{'id':str(i)} for i in range(24)]
  assert worker.batch_request_payload(runtime)['max_new']==6
  runtime['_new_lease_limit']=False
  assert worker.batch_request_payload(runtime)['count']==6
  runtime['_new_lease_limit']=True
  runtime['_lease_queue']=[{'id':str(i)} for i in range(30)]
  assert worker.batch_request_payload(runtime)['max_new']==0
  runtime['_batch_requests']=True
  worker.start_batch_prefetch({'server':'https://test.invalid','device_token':'test'},runtime)
  assert '_batch_pending' not in runtime,'Full window issued another reservation request'
  runtime['_lease_queue']=[]
  q.confirm('uploading')
  assert worker.batch_request_payload(runtime)['max_new']==31
  assert 'uploading' in q.computed_ids(),'Replay protection lost after acknowledgement'
print('PASS Windows allocation budget includes executing and unacknowledged work, preserves replay history')
