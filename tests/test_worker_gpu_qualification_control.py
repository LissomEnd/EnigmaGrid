import sys,tempfile
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'worker'),str(root/'solver/runtime/src')]
import worker
import bounded_gpu_qualification as gpu

with tempfile.TemporaryDirectory() as tmp:
    state=Path(tmp)/'client.json';state.write_bytes(b'identity-must-not-change')
    record=state.with_name('bounded-gpu-qualification.json');record.write_bytes(b'previous-valid-record')
    settings=dict(cpu_percent=100,gpu_percent=100,allow_cpu=True,allow_gpu=True)
    calls=[]
    def qualify(*args,checkpoint):
        calls.append('started');checkpoint();return {'gpu_cores':64}
    with patch.object(worker,'acquire_worker_mutex',return_value=True),patch.object(worker,'load_state',return_value={'settings':settings}),patch.object(worker,'_thermal_probe',return_value=('',{})),patch.object(gpu,'qualify',side_effect=qualify),patch.object(gpu,'hardware_fingerprint',return_value='test'),patch.object(gpu,'load_qualification',return_value=None):
        assert worker.qualify_bounded_gpu_client(state,2)['qualified'] is False
        assert record.read_bytes()==b'previous-valid-record'
        with patch.object(gpu,'load_qualification',return_value={'qualified':True}):
            assert worker.qualify_bounded_gpu_client(state,2)['qualified']
        assert state.read_bytes()==b'identity-must-not-change'
        for probe in [('hot',{}),('',{'paused':True}),('',{'stop_requested':True})]:
            count=len(calls)
            with patch.object(worker,'_thermal_probe',return_value=probe):
                try:worker.qualify_bounded_gpu_client(state,2)
                except InterruptedError:pass
                else:raise AssertionError('Protection ignored')
            assert len(calls)==count
        for field,value in [('gpu_percent',0),('cpu_percent',50),('allow_gpu',False)]:
            with patch.object(worker,'load_state',return_value={'settings':dict(settings,**{field:value})}):
                try:worker.qualify_bounded_gpu_client(state,2)
                except InterruptedError:pass
                else:raise AssertionError('Settings overridden')
        with patch.object(worker,'acquire_worker_mutex',return_value=False):
            try:worker.qualify_bounded_gpu_client(state,2)
            except RuntimeError:pass
            else:raise AssertionError('Concurrent qualification accepted')
print('PASS qualification controls, worker exclusion, identity preservation and failed-gate record preservation')

with tempfile.TemporaryDirectory() as tmp:
    base=Path(tmp);state=base/'client.json'
    for name in ('worker/native/enigmagrid_solver.dll','worker/native/bounded_solver.spv','solver/runtime/src/search/vulkan_bounded.py'):
        path=base/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
    runtime={'settings':settings,'enabled':True};calls=[]
    def attempt(*args,**kwargs):
        assert kwargs['owned_runtime'] is runtime
        calls.append(args[1]);return {'qualified':False}
    with patch.object(worker,'ROOT',base),patch.object(worker,'heartbeat_once'),patch.object(worker,'constrained_process_limit',return_value=4),patch.object(worker,'publish_health'),patch.object(worker,'load_bounded_gpu'),patch.object(gpu,'hardware_fingerprint',return_value='device'),patch.object(worker,'qualify_bounded_gpu_client',side_effect=attempt):
        worker.maybe_qualify_bounded_gpu(state,{},runtime)
        worker.maybe_qualify_bounded_gpu(state,{},runtime)
        assert calls==[4], 'Failed performance comparison repeated without changes'
        (base/'worker/native/bounded_solver.spv').write_bytes(b'updated-shader')
        worker.maybe_qualify_bounded_gpu(state,{},runtime)
        assert calls==[4,4], 'Changed shader did not invalidate previous comparison'
        runtime['settings']=dict(settings,gpu_percent=0)
        worker.maybe_qualify_bounded_gpu(state,{},runtime)
        assert calls==[4,4]
print('PASS automatic qualification uses actual CPU pool size, caches comparison and invalidates changed code')

with tempfile.TemporaryDirectory() as tmp:
    state=Path(tmp)/'client.json'
    runtime={'settings':settings,'enabled':True}
    def revoke(*args,checkpoint):
        for _ in range(100):checkpoint()
        runtime['enabled']=False
        checkpoint()
        raise AssertionError('Revoked qualification continued')
    with patch.object(worker,'_thermal_probe',return_value=('',{})) as probe,patch.object(worker,'load_state',side_effect=AssertionError('Stale disk preferences used')),patch.object(worker,'publish_health'),patch.object(worker.time,'monotonic',return_value=100),patch.object(gpu,'qualify',side_effect=revoke):
        try:worker.qualify_bounded_gpu_client(state,2,owned_runtime=runtime)
        except InterruptedError:pass
        else:raise AssertionError('Coordinator revocation ignored')
        assert probe.call_count==1,'Sensor/disk polling polluted benchmark'
    assert not state.with_name('bounded-gpu-qualification.json').exists()
print('PASS live coordinator revocation, authoritative settings and bounded sensor polling')

# A transient prerequisite must not permanently disable automatic GPU tuning.
runtime={}
with patch.object(worker.time,'monotonic',return_value=100),patch.object(worker,'maybe_qualify_bounded_gpu',return_value=False) as attempt:
    worker.check_bounded_gpu_qualification(None,{},runtime)
    worker.check_bounded_gpu_qualification(None,{},runtime)
    assert attempt.call_count==1
    assert not runtime.get('_gpu_qualification_considered')
with patch.object(worker.time,'monotonic',return_value=161),patch.object(worker,'maybe_qualify_bounded_gpu',return_value=True) as attempt:
    worker.check_bounded_gpu_qualification(None,{},runtime)
    assert attempt.call_count==1 and runtime['_gpu_qualification_considered']
with patch.object(worker.time,'monotonic',return_value=1000),patch.object(worker,'maybe_qualify_bounded_gpu',side_effect=AssertionError('Settled comparison repeated')):
    worker.check_bounded_gpu_qualification(None,{},runtime)
print('PASS deferred qualification retries after bounded delay and settled comparisons do not repeat')
with tempfile.TemporaryDirectory() as tmp:
    base=Path(tmp);state=base/'client.json'
    for name in ('worker/native/enigmagrid_solver.dll','worker/native/bounded_solver.spv','solver/runtime/src/search/vulkan_bounded.py'):
        path=base/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
    runtime={'settings':settings,'enabled':True}
    with patch.object(worker,'ROOT',base),patch.object(worker,'heartbeat_once'),patch.object(worker,'constrained_process_limit',return_value=0),patch.object(worker,'qualify_bounded_gpu_client',side_effect=AssertionError('Low memory tuning started')):
        assert worker.maybe_qualify_bounded_gpu(state,{},runtime) is False
        assert 'insufficient free memory' in runtime['bounded_backend']
        runtime['settings']=dict(settings,cpu_percent=50)
        assert worker.maybe_qualify_bounded_gpu(state,{},runtime) is False
        assert '100%' in runtime['bounded_backend']
print('PASS actual low-memory and reduced-slider prerequisites remain deferred without starting a benchmark')
