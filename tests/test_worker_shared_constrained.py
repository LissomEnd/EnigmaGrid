"""Full receipt parity and cooperative shutdown through the worker shared path."""
import multiprocessing
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'worker'),str(root/'solver/runtime/src')]
import worker
from search.c3_models import solve_board


def dispatch(data):
    count,length,pairs,nodes,limit=data[:5];base=5+count*length*26
    edges=[tuple(data[base+i*3:base+i*3+3]) for i in range(length)]
    output=[0xffffffff,count]
    for core in range(count):
        rows=[data[5+(core*length+i)*26:5+(core*length+i+1)*26] for i in range(length)]
        result=solve_board(rows,edges,max_pairs=pairs,node_limit=nodes,solution_limit=limit)
        output.extend([('unsatisfiable','satisfiable','unknown_budget').index(result['status']),result['nodes'],len(result['partial_boards'])])
        for board in result['partial_boards']:output.extend(x&0xffffffff for x in board)
    return output


def main():
    job=dict(engine='bounded_crib_v1',ciphertext='A'*72,crib='B'*24,offset=0,
             core_indices=list(range(32)),model='clean',pairs=10,
             budgets=dict(node_limit=10,board_limit=1,completion_limit=1,candidate_limit=1))
    lease=dict(engine='bounded_crib_v1',start_unit=0,end_unit=1,
               config=dict(job=job,requires=['cpu','bounded_crib_v1']))
    runtime=dict(settings=dict(cpu_percent=100,allow_cpu=True,gpu_percent=100,allow_gpu=True),
                 enabled=True,_parallel_constrained=True)
    with tempfile.TemporaryDirectory() as folder, \
         patch.object(worker.os,'cpu_count',return_value=2), \
         patch.object(worker,'constrained_process_limit',return_value=2), \
         patch.object(worker.windows_telemetry.SystemTelemetry,'sample',return_value={}):
        state=Path(folder)/'state.json';worker.write_control(state,{})
        expected=worker.run_constrained(lease,dict(settings=runtime['settings']),state)
        assert worker.prepare_shared_constrained(runtime)
        owner=runtime['_shared_constrained_pool']
        runtime['_block_stop_event']=threading.Event()
        try:
            for lanes in (1,2,4):
                barrier=threading.Barrier(lanes)
                def compute(_):
                    barrier.wait(timeout=5)
                    return worker.run_constrained(lease,runtime,state)
                with ThreadPoolExecutor(lanes) as callers:
                    assert all(value==expected for value in callers.map(compute,range(lanes)))
                assert runtime['_shared_constrained_pool'] is owner
                assert len(multiprocessing.active_children())<=2
            runtime['settings']=dict(runtime['settings'],cpu_percent=25)
            assert worker.run_constrained(lease,runtime,state)==expected
            assert owner.percent.value==25,'Concurrent jobs multiplied the quota'
            runtime['settings']=dict(runtime['settings'],cpu_percent=100)
            worker.write_control(state,{'paused':True})
            with ThreadPoolExecutor(4) as callers:
                tasks=[callers.submit(worker.run_constrained,lease,runtime,state) for _ in range(4)]
                time.sleep(.2)
                assert not any(task.done() for task in tasks)
                runtime['_block_stop_event'].set()
                for task in tasks:
                    try:task.result(timeout=3)
                    except InterruptedError:pass
                    else:raise AssertionError('Stopped job completed')
        finally:worker.release_shared_constrained(runtime)
        worker.write_control(state,{})
        runtime.pop('_bounded_gpu_qualification',None)
        runtime['_qualified_gpu_lane']=True
        runtime['_bounded_gpu_lane_qualification']=dict(qualified=True,cpu_workers=2,
            scope=(32,24,'clean',10,10,1,1),dispatch=dispatch)
        assert worker.prepare_shared_constrained(runtime)
        gpu=runtime['_shared_gpu_solver']
        try:
            with ThreadPoolExecutor(2) as callers:
                cpu=callers.submit(worker.run_constrained,lease,runtime,state,'cpu')
                accelerated=callers.submit(worker.run_constrained,lease,runtime,state,'gpu')
                assert cpu.result()==expected and accelerated.result()==expected
            assert runtime['_shared_gpu_solver'] is gpu and not gpu.failed and gpu.budget.calls>0
            assert runtime['resource']=='CPU + GPU'
            runtime['settings']['gpu_percent']=0
            assert worker.run_constrained(lease,runtime,state,'gpu')==expected
            assert 'safe fallback' in runtime['bounded_backend']
            runtime['settings']['gpu_percent']=100
            runtime['_bounded_gpu_lane_qualification']['scope']=(99,24,'clean',10,10,1,1)
            assert worker.run_constrained(lease,runtime,state,'gpu')==expected
            assert 'safe fallback' in runtime['bounded_backend']
            runtime['_bounded_gpu_lane_qualification']['scope']=(32,24,'clean',10,10,1,1)
            runtime['_block_stop_event']=threading.Event();runtime['_block_stop_event'].set()
            try:worker.run_constrained(lease,runtime,state,'gpu')
            except InterruptedError:pass
            else:raise AssertionError('Stopped GPU lane returned a receipt')
            runtime['_block_stop_event'].clear()
        finally:worker.release_shared_constrained(runtime)
        runtime.pop('_bounded_gpu_lane_qualification',None)
        runtime['_qualified_gpu_lane']=False
        runtime['_bounded_gpu_qualification']=dict(qualified=True,cpu_workers=2,
            scope=(32,24,'clean',10,10,1,1),dispatch=dispatch,gpu_cores=16)
        assert worker.prepare_shared_constrained(runtime)
        gpu=runtime['_shared_gpu_solver']
        try:
            with ThreadPoolExecutor(4) as callers:
                results=list(callers.map(lambda _:worker.run_constrained(lease,runtime,state),range(4)))
            assert all(result==expected for result in results)
            assert runtime['_shared_gpu_solver'] is gpu and not gpu.closed.is_set()
            assert runtime['bounded_backend']=='CPU + Vulkan bounded solver'
            assert '_constrained_hybrid' not in runtime,'Per-job owner leaked into global state'
        finally:worker.release_shared_constrained(runtime)
        runtime.pop('_bounded_gpu_qualification',None)
        def broken_dispatch(_):raise RuntimeError('Synthetic backend failure')
        runtime['_bounded_gpu_lane_qualification']=dict(qualified=True,cpu_workers=2,
            scope=(32,24,'clean',10,10,1,1),dispatch=broken_dispatch)
        assert worker.prepare_shared_constrained(runtime)
        try:
            assert worker.run_constrained(lease,runtime,state,'gpu')==expected
            assert runtime['_shared_gpu_solver'].failed
            assert 'Vulkan lane failed' in runtime['bounded_gpu_reason']
            assert worker.run_constrained(lease,runtime,state,'gpu')==expected
        finally:worker.release_shared_constrained(runtime)
    assert not multiprocessing.active_children()
    print('PASS worker shared 1/2/4 receipt parity, process cap, live quota, stop, hybrid and independent GPU job lane with GPU-off/scope fallback')


if __name__=='__main__':main()
