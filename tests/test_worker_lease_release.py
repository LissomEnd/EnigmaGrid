import sys,time,urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
import worker
state={'server':'https://example.invalid','device_token':'test'}
lease={'id':'unused','work_token':'test'}
runtime={'_lease_queue':[lease]}
with patch.object(worker,'get_json',return_value={'release_leases':True}),patch.object(worker,'post',side_effect=TimeoutError):
    assert not worker.release_unused_work(state,runtime)
    assert runtime['_lease_queue']==[lease]
runtime['_release_retry_at']=0
with patch.object(worker,'post',return_value={'ok':True,'released':['unused']}) as post:
    assert worker.release_unused_work(state,runtime)
    assert post.call_args.args[2]=={'leases':[{'lease_id':'unused','work_token':'test'}]}
    assert runtime['_lease_queue']==[]
    assert worker.release_unused_work(state,runtime)
    assert post.call_count==1
runtime={'_lease_queue':[lease]}
with patch.object(worker,'get_json',side_effect=urllib.error.HTTPError('https://test',404,'missing',{},None)),patch.object(worker,'post') as post:
    assert not worker.release_unused_work(state,runtime)
    assert runtime['_lease_queue']==[lease]
    post.assert_not_called()
print('PASS unused lease release, timeout retention, idempotent local drain and legacy fallback')
