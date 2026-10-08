"""Exercise negotiation, bounded batches and uncertain/mixed acknowledgements."""
import sys, tempfile, time, urllib.error
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
from completion_transport import CompletionTransport
from receipt_outbox import OutboxUploader
import worker

items=[{'lease_id':str(i),'work_token':'test','result':{'value':i}} for i in range(8)]
caps={'batch_completions':True,'max_completion_count':8,'max_body_bytes':262144}
calls=[]
def mixed(path,body):
    calls.append((path,body))
    return {'results':[{'lease_id':p['lease_id'],'status':200 if i%2==0 else 422,
                       'result':{'ok':i%2==0}} for i,p in enumerate(body['submissions'])]}
t=CompletionTransport(lambda path:caps,mixed)
with tempfile.TemporaryDirectory() as tmp:
    state={'server':'https://example.invalid','device_id':'test'}
    queue=worker.result_outbox(Path(tmp)/'client.json',state)
    for item in items:queue.append(item)
    uploader=OutboxUploader(queue,None,t.send)
    uploader.thread.join(2)
    try:
        assert uploader.terminal
        assert [p['lease_id'] for p in queue.pending()]==['1','3','5','7']
    finally:uploader.close()
assert len(calls)==1 and len(calls[0][1]['submissions'])==8
for broken in [[],[{'lease_id':'other','status':200,'result':{'ok':True}}],
               [{'lease_id':'0','status':200,'result':{'ok':True}}]*8]:
    t=CompletionTransport(lambda path:caps,lambda path,body:{'results':broken})
    try:t.send(items)
    except ValueError:pass
    else:raise AssertionError('Malformed acknowledgement accepted')
def old(path):raise urllib.error.HTTPError('https://test',404,'missing',{},None)
calls=[]
t=CompletionTransport(old,lambda path,body:calls.append(path) or {'ok':True})
assert t.send(items)==[('0',{'ok':True})]
assert calls==['/api/complete']
calls=[]
small={**caps,'max_body_bytes':180}
t=CompletionTransport(lambda path:small,mixed)
assert 1<=len(t.send(items))<8
assert len(calls[0][1]['submissions'])<8
print('PASS batch size, legacy fallback, malformed response retention and partial acknowledgement')
