import copy
import json
import multiprocessing
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'worker'),str(root/'solver/runtime/src')]
import worker


def main():
    job=dict(engine='bounded_crib_v1',ciphertext='A'*72,crib='B'*24,offset=0,
        core_indices=list(range(8)),model='clean',pairs=10,
        budgets=dict(node_limit=10,board_limit=1,completion_limit=1,candidate_limit=1))
    lease=dict(engine='bounded_crib_v1',start_unit=0,end_unit=1,
        config=dict(job=job,requires=['cpu','bounded_crib_v1']))
    envelopes=[copy.deepcopy(lease) for _ in range(12)]
    pipeline=SimpleNamespace(running={},lanes=1,queue=SimpleNamespace(qualification_sample=lambda:envelopes))
    runtime=dict(enabled=True,settings=dict(cpu_percent=100,allow_cpu=True,gpu_percent=0,allow_gpu=False),
        _parallel_constrained=True,_block_stop_event=threading.Event())
    prior=runtime['_block_stop_event']
    with tempfile.TemporaryDirectory() as folder, \
         patch.object(worker.os,'cpu_count',return_value=2), \
         patch.object(worker,'constrained_process_limit',return_value=2), \
         patch.object(worker.windows_telemetry.SystemTelemetry,'sample',return_value={}), \
         patch.object(worker,'heartbeat_loop',side_effect=lambda stop,*_:stop.wait()):
        state=Path(folder)/'state.json';worker.write_control(state,{})
        worker.maybe_qualify_block_concurrency(state,{},runtime,pipeline)
        record=json.loads(state.with_name('block-concurrency-qualification.json').read_text())
        assert len(record['report']['trials'])==9 and record['report']['parity_checks']==120
        selected=runtime['_qualified_block_lanes'];assert selected in (1,2,4)
        assert runtime['_block_stop_event'] is prior and not prior.is_set()
        assert '_shared_constrained_pool' not in runtime and '_qualification_check' not in runtime
        runtime.pop('_block_concurrency_considered')
        with patch('concurrency_qualification.qualify',side_effect=AssertionError('Repeated cached qualification')):
            worker.maybe_qualify_block_concurrency(state,{},runtime,pipeline)
        assert runtime['_qualified_block_lanes']==selected
        # A changed quota invalidates the record. Pause must interrupt the new
        # comparison without replacing the last valid evidence or stop token.
        runtime.pop('_block_concurrency_considered')
        runtime['settings']=dict(runtime['settings'],cpu_percent=25)
        worker.write_control(state,{'paused':True})
        previous=state.with_name('block-concurrency-qualification.json').read_bytes()
        try:worker.maybe_qualify_block_concurrency(state,{},runtime,pipeline)
        except InterruptedError:pass
        else:raise AssertionError('Changed quota reused cached qualification or ignored pause')
        assert state.with_name('block-concurrency-qualification.json').read_bytes()==previous
        assert runtime['_block_stop_event'] is prior and not prior.is_set()
        assert '_shared_constrained_pool' not in runtime and '_qualification_check' not in runtime
    assert not multiprocessing.active_children()
    print('PASS integrated worker qualification,120 receipt comparisons, cache reuse/invalidation, pause and owner cleanup')


if __name__=='__main__':main()
