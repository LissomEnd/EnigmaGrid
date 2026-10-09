import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'worker'),str(ROOT/'solver/runtime/src')]
import worker
import concurrency_qualification
import gpu_lane_qualification
from search.vulkan_bounded import SharedGpuSolver
import search.vulkan_bounded as vulkan

orders=concurrency_qualification.ORDERS
trials=[]
for order in orders:
    for lanes in order:
        trials.append(dict(lanes=lanes,seconds={1:1.0,2:.75,4:.9}[lanes],receipt_equal=True))
cpu_report=dict(format='local-concurrency-v1',lanes=2,trials=trials,
                jobs_per_trial=12,parity_checks=120)
gpu_report=dict(format=gpu_lane_qualification.FORMAT,jobs_per_trial=12,
                cpu_lanes=2,mixed_cpu_lanes=2,qualified=True,
                trials=[dict(trial=i,receipt_equal=True,cpu_seconds=1.0,mixed_seconds=.8,gpu_jobs=4)
                        for i in range(3)])
assert concurrency_qualification.select_lanes(trials)==2
assert gpu_lane_qualification.select_profile(gpu_report['trials'],2)

with tempfile.TemporaryDirectory() as directory:
    state=Path(directory)/'client.json'
    envelopes=[dict(config=dict(job=dict(unit=i))) for i in range(12)]
    parity=dict(qualified=True,dispatch=lambda data:data,scope=(128,24,'clean',10,5000,64,256))
    pipeline=SimpleNamespace(lanes=1,gpu_execute=None)
    def runtime():
        return dict(settings=dict(allow_cpu=True,cpu_percent=100,allow_gpu=True,gpu_percent=100),
                    enabled=True,_shared_constrained_pool=SimpleNamespace(workers=2))
    first=runtime()
    with patch.object(worker,'constrained_process_limit',return_value=2) as memory_limit, \
         patch.object(worker,'_thermal_probe',return_value=('',{})), \
         patch.object(worker,'bounded_lane_parity',return_value=parity), \
         patch.object(concurrency_qualification,'qualify',return_value=cpu_report) as cpu, \
         patch.object(gpu_lane_qualification,'qualify',return_value=gpu_report) as gpu:
        assert worker.maybe_qualify_block_concurrency(state,{},first,pipeline,
            envelopes=envelopes,shared_pool=True)
        assert cpu.call_count==1 and gpu.call_count==1
        assert memory_limit.call_args.kwargs['existing_workers']==2
        assert first['_qualified_block_lanes']==2 and first['_qualified_gpu_lane']
        assert first['_bounded_gpu_lane_qualification']['cpu_workers']==2
        assert '_shared_gpu_solver' not in first
        saved=json.loads(state.with_name('block-concurrency-qualification.json').read_text())
        assert saved['report']['gpu_lane']['qualified']
        second=runtime()
        assert worker.maybe_qualify_block_concurrency(state,{},second,pipeline,
            envelopes=envelopes,shared_pool=True)
        assert cpu.call_count==1 and gpu.call_count==1
        assert second['_qualified_gpu_lane']
        saved['report']['gpu_lane']['trials'][1]['mixed_seconds']=1.1
        state.with_name('block-concurrency-qualification.json').write_text(json.dumps(saved))
        third=runtime()
        assert worker.maybe_qualify_block_concurrency(state,{},third,pipeline,
            envelopes=envelopes,shared_pool=True)
        assert third['_qualified_gpu_lane'] and third['_qualified_block_lanes']==2
        assert cpu.call_count==2 and gpu.call_count==2
        state.with_name('bounded-gpu-comparison.json').write_text('new parity source hash')
        fourth=runtime()
        assert worker.maybe_qualify_block_concurrency(state,{},fourth,pipeline,
            envelopes=envelopes,shared_pool=True)
        assert fourth['_qualified_gpu_lane'] and cpu.call_count==3 and gpu.call_count==3
        fifth=runtime();fifth['settings']['gpu_percent']=0
        assert worker.maybe_qualify_block_concurrency(state,{},fifth,pipeline,
            envelopes=envelopes,shared_pool=True)
        assert not fifth.get('_qualified_gpu_lane') and gpu.call_count==3
        state.with_name('block-concurrency-qualification.json').unlink()
        prior=SharedGpuSolver(parity['dispatch'])
        sixth=runtime();sixth['_shared_gpu_solver']=prior
        try:
            with patch.object(vulkan,'SharedGpuSolver',side_effect=AssertionError('Second GPU owner')):
                assert worker.maybe_qualify_block_concurrency(state,{},sixth,pipeline,
                    envelopes=envelopes,shared_pool=True)
            assert sixth['_shared_gpu_solver'] is prior and not prior.closed.is_set()
            assert sixth['_bounded_gpu_lane_qualification']['dispatch'] is prior.budget.dispatch
        finally:prior.close()

print('PASS aggregate GPU lane profile loads only with exact cached proof and requests safe pipeline promotion')
