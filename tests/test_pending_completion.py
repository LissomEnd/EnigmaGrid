"""Offline regression for lost acknowledgements and durable receipt recovery."""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
import worker

def main():
    state=dict(server='https://example.invalid',device_id='test-device',device_token='test-token')
    payload=dict(lease_id=42,work_token='test-work',result={'receipt':'canonical'})
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'state.json'
        # Existing installations may have the old single-result format.
        worker.save_state(worker.pending_path(path),{'server':state['server'],'device_id':state['device_id'],'payload':payload})
        saved=worker.pending_path(path)
        assert saved.exists()
        try:worker.persist_completion(path,state,{'lease_id':43})
        except RuntimeError:pass
        else:raise AssertionError('Overwrote pending work')
        with patch.object(worker,'post',side_effect=TimeoutError('lost acknowledgement')):
            try:worker.deliver_pending(path,state)
            except TimeoutError:pass
            else:raise AssertionError('Expected network failure')
        assert worker.result_outbox(path,state).pending()==[payload]
        with patch.object(worker,'post') as post:
            for changed in ({**state,'device_id':'other'},{**state,'server':'https://other.invalid'}):
                try:worker.deliver_pending(path,changed)
                except RuntimeError:pass
                else:raise AssertionError('Cross-account replay')
            post.assert_not_called()
        for ack in ({'ok':False},{'ok':1},None):
            with patch.object(worker,'post',return_value=ack):
                try:worker.deliver_pending(path,state)
                except RuntimeError:pass
                else:raise AssertionError('Unacknowledged result discarded')
            assert saved.exists()
        with patch.object(worker,'post',return_value={'ok':True,'duplicate':True}) as post:
            assert worker.deliver_pending(path,state)['duplicate']
            assert post.call_args.args[2]==payload
        assert not saved.exists()
        assert worker.deliver_pending(path,state) is None
        # A fresh worker invocation must recover before asking for another lease.
        worker.persist_completion(path,state,payload)
        args=SimpleNamespace(state=str(path),once=True,idle_seconds=1)
        with patch.object(worker,'acquire_worker_mutex',return_value=True), \
             patch.object(worker,'UpdateManager',None), \
             patch.object(worker,'publish_health'), \
             patch.object(worker,'post',return_value={'ok':True}), \
             patch.object(worker,'request_work') as request:
            assert worker._work(args,state,{})==0
            request.assert_not_called()
        assert not saved.exists()
    print('PASS durable completion: timeout, identity binding, ack validation, duplicate recovery')

if __name__=='__main__':main()
