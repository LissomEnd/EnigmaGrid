import sys
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'worker'),str(root/'solver/runtime/src')]
import worker
from search.c3_models import solve_board
class Pool:
    workers=2
    check=lambda self:None
    def __init__(self,*a,**kw):pass
    def set_percent(self,p):pass
    def __call__(self,fn,tasks):
        for task in tasks:self.check();yield fn(task)
    def close(self):pass
calls=[]
def dispatch(data):
    count,length,pairs,nodes,limit=data[:5];calls.append(count);base=5+count*length*26
    edges=[tuple(data[base+i*3:base+i*3+3]) for i in range(length)];output=[0xffffffff,count]
    for c in range(count):
        rows=[data[5+(c*length+i)*26:5+(c*length+i+1)*26] for i in range(length)]
        r=solve_board(rows,edges,max_pairs=pairs,node_limit=nodes,solution_limit=limit)
        output.extend([('unsatisfiable','satisfiable','unknown_budget').index(r['status']),r['nodes'],len(r['partial_boards'])])
        for board in r['partial_boards']:output.extend(x&0xffffffff for x in board)
    return output
job=dict(engine='bounded_crib_v1',ciphertext='A'*72,crib='B'*24,offset=0,core_indices=list(range(8)),model='clean',pairs=10,budgets=dict(node_limit=10,board_limit=1,completion_limit=1,candidate_limit=1))
lease=dict(engine='bounded_crib_v1',start_unit=0,end_unit=1,config=dict(job=job,requires=['cpu','bounded_crib_v1']))
runtime={'settings':{'cpu_percent':100,'allow_cpu':True,'gpu_percent':100,'allow_gpu':True}}
with patch('search.process_map.OrderedProcessMap',Pool),patch.object(worker,'constrained_process_limit',return_value=2),patch.object(worker,'publish_health'):
    expected=worker.run_constrained_parallel(lease,runtime,None)
    assert not calls
    assert 'qualification not available' in runtime['bounded_backend']
    worker.bounded_cpu_reason(runtime,'Vulkan comparison did not qualify')
    assert worker.run_constrained_parallel(lease,runtime,None)==expected
    assert 'comparison did not qualify' in runtime['bounded_backend']
    runtime['_bounded_gpu_qualification']=dict(qualified=True,cpu_workers=2,scope=(8,24,'clean',10,10,1,1),dispatch=dispatch,gpu_cores=4)
    try:
        assert worker.run_constrained_parallel(lease,runtime,None)==expected
        assert calls==[4] and runtime['bounded_backend']=='CPU + Vulkan bounded solver'
        runtime['settings']['allow_gpu']=False
        assert worker.run_constrained_parallel(lease,runtime,None)==expected and calls==[4]
        assert 'GPU disabled in settings' in runtime['bounded_backend']
        runtime['settings']['allow_gpu']=True
        runtime['_bounded_gpu_qualification']['cpu_workers']=8
        assert worker.run_constrained_parallel(lease,runtime,None)==expected and calls==[4]
        assert 'different CPU pool size' in runtime['bounded_backend']
        runtime['_bounded_gpu_qualification']['cpu_workers']=2
        runtime['_bounded_gpu_qualification']['scope']=(99,24,'clean',10,10,1,1)
        assert worker.run_constrained_parallel(lease,runtime,None)==expected and calls==[4]
        assert 'outside qualified Vulkan scope' in runtime['bounded_backend']
    finally:worker.release_constrained_pool(runtime)
assert '_constrained_hybrid' not in runtime
print('PASS worker hybrid routing, scope/worker qualification gate, GPU settings, receipt parity and shutdown')


with patch.object(worker,'constrained_process_limit',return_value=0):
    assert worker.run_constrained_parallel(lease,runtime,None)==expected
    assert 'insufficient free memory' in runtime['bounded_backend']
print('PASS memory fallback preserves receipt and exposes allocation constraint')
