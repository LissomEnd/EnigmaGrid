"""Summary must not report absent GPUs simply because its process has not probed."""
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
import worker
state=dict(server='https://example.invalid',device_id='mine',dashboard_token='test',settings={})
devices=[dict(id='other',settings={},meta=dict(cpu_count=99,gpus=['wrong'])),
         dict(id='mine',settings={},meta=dict(cpu_count=8,gpus=[{'name':'test GPU'}],capabilities=['cpu','gpu']))]
with patch.object(worker,'_HW',None), patch.object(worker,'load_state',return_value=state), \
     patch.object(worker,'get_json',return_value={}), patch.object(worker,'post',return_value={'devices':devices}), \
     patch.object(worker,'hardware',side_effect=AssertionError('Summary triggered expensive probe')):
    result=worker.client_summary('unused')
    assert result['hardware']['cpu_count']==8 and result['hardware']['gpus']==[{'name':'test GPU'}]
    assert result['hardware']['source']=='last_server_report'
    with patch.object(worker,'post',side_effect=OSError('offline')),patch.object(worker.os,'cpu_count',return_value=8):
        result=worker.client_summary('unused')
        assert result['hardware']['cpu_count']==8 and not result['hardware']['detection_complete']
        assert result['hardware']['source']=='not_probed'
    with patch.object(worker,'_HW',dict(cpu_count=4,gpus=[],capabilities=['cpu'])):
        result=worker.client_summary('unused')
        assert result['hardware']['cpu_count']==4 and result['hardware']['source']=='local_probe'
print('CLIENT_SUMMARY_HARDWARE_PROVENANCE_OK')
