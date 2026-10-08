"""ABI layout and complete receipt parity using a CPU-backed dispatch double.
This does not qualify a physical Vulkan device.
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'solver/runtime/src'))
from search.vulkan_bounded import pack,unpack,SolverMap
from search.c3_models import solve_board
from search.crib_work import run
calls=[]
def dispatch(data):
    count,length,pairs,nodes,limit=data[:5];calls.append(count)
    base=5+count*length*26
    edges=[tuple(data[base+i*3:base+i*3+3]) for i in range(length)]
    output=[0xffffffff,count]
    for core in range(count):
        rows=[data[5+(core*length+i)*26:5+(core*length+i+1)*26] for i in range(length)]
        result=solve_board(rows,edges,max_pairs=pairs,node_limit=nodes,solution_limit=limit)
        boards=result['partial_boards']
        output.extend([('unsatisfiable','satisfiable','unknown_budget').index(result['status']),result['nodes'],len(boards)])
        for board in boards:output.extend(x&0xffffffff for x in board)
    return output
job=dict(engine='bounded_crib_v1',ciphertext='A'*72,crib='B'*24,offset=0,core_indices=list(range(65)),model='clean',pairs=10,budgets=dict(node_limit=10,board_limit=1,completion_limit=1,candidate_limit=1))
lease=dict(engine='bounded_crib_v1',start_unit=0,end_unit=1,config=dict(job=job,requires=['cpu','bounded_crib_v1']))
assert run(lease,solve_map=SolverMap(dispatch))==run(lease)
assert calls==[64,1],calls
# Decode validation must reject truncated, extra, and impossible native data.
rows=[[[x^1 for x in range(26)]]]
data=pack(rows,[(0,0,1)],0,32,4)
out=dispatch(data)
assert unpack(out,data)
for bad in (out[:-1],out+[0],[0xffffffff,2], [0xffffffff,1,1,0,0], [0xffffffff,1,0,1,1]+[0]*26):
    try:unpack(bad,data)
    except ValueError:pass
    else:raise AssertionError('Malformed native output accepted')
# Cancellation is checked before any native dispatch.
def stopped():raise InterruptedError('stop')
try:run(lease,solve_map=SolverMap(dispatch,stopped))
except InterruptedError:pass
else:raise AssertionError('Cancellation ignored')
print('PASS native layout, ordered 64+1 batching, full receipt parity, malformed results and cancellation; CPU dispatch double only')

from search.vulkan_bounded import HybridSolverMap
for share in (1,32,64,96,128):
    hybrid=HybridSolverMap(dispatch,map,share)
    try:assert run(lease,solve_map=hybrid)==run(lease)
    finally:hybrid.close()
print('PASS hybrid disjoint core shares and full receipt parity')

failures=[]
def broken(data):raise RuntimeError('native failure')
hybrid=HybridSolverMap(broken,map,32,on_failure=lambda error:failures.append(str(error)))
try:
    assert run(lease,solve_map=hybrid)==run(lease)
    assert run(lease,solve_map=hybrid)==run(lease)
    assert failures==['native failure'] and hybrid.failed
finally:hybrid.close()
hybrid=HybridSolverMap(lambda data:(_ for _ in ()).throw(AssertionError('Disabled GPU dispatched')),map,gpu_enabled=lambda:False)
try:assert run(lease,solve_map=hybrid)==run(lease)
finally:hybrid.close()
def cpu_stopped(fn,tasks):raise InterruptedError('CPU stop preserved')
hybrid=HybridSolverMap(broken,cpu_stopped,32)
try:
    try:run(lease,solve_map=hybrid)
    except InterruptedError as error:assert str(error)=='CPU stop preserved'
    else:raise AssertionError('Stop swallowed')
finally:hybrid.close()
print('PASS hybrid native failure fallback, one-time disable, GPU disabled and original stop preservation')

from search.vulkan_bounded import BudgetedDispatch
clock=[0.0];rests=[];percent=[100];cancel=[False]
def advance(seconds):rests.append(seconds);clock[0]+=seconds
def native_time(data):clock[0]+=.1;return data
budget=BudgetedDispatch(native_time,lambda:percent[0],lambda:cancel[0],lambda:clock[0],advance)
for _ in range(4):budget([1])
assert not rests and abs(clock[0]-.4)<1e-8,'100% inserted duty rest'
percent[0]=25;budget([2])
assert abs(sum(rests)-.3)<1e-8,'25% backend duty incorrect'
rests.clear();clock[0]+=2;budget([3]);assert not rests,'Idle counted twice'
percent[0]=25
# A live increase to100 interrupts an existing rest at the next poll.
def raise_limit(seconds):advance(seconds);percent[0]=100
budget.sleep=raise_limit;budget([4]);assert len(rests)==1 and rests[0]<=.02
cancel[0]=True
try:budget([5])
except InterruptedError:pass
else:raise AssertionError('GPU cancellation ignored')
cancel[0]=False;percent[0]=0
try:budget([6])
except InterruptedError:pass
else:raise AssertionError('Disabled GPU ran')
print('PASS shared backend duty: continuous100, proportional25, idle credit, live slider and cancellation')

# Concurrent jobs share the same native queue and budget, while cancellation
# belongs to each job. These are dispatch doubles, not hardware qualification.
from search.vulkan_bounded import SharedGpuSolver
from concurrent.futures import ThreadPoolExecutor
import threading
import time
active=[0];peak=[0];guard=threading.Lock()
def serialized_dispatch(data):
    with guard:
        active[0]+=1;peak[0]=max(peak[0],active[0])
    try:
        time.sleep(.005)
        return dispatch(data)
    finally:
        with guard:active[0]-=1
service=SharedGpuSolver(serialized_dispatch)
expected=run(lease)
try:
    for lanes in (2,4):
        barrier=threading.Barrier(lanes)
        def search(_):
            hybrid=HybridSolverMap(None,map,32,gpu_service=service)
            try:
                barrier.wait(timeout=5)
                return run(lease,solve_map=hybrid)
            finally:hybrid.close()
        with ThreadPoolExecutor(lanes) as callers:
            assert all(result==expected for result in callers.map(search,range(lanes)))
    assert peak[0]==1,'Native backend entered concurrently'
    assert not service.closed.is_set(),'Closing one job closed shared backend'
finally:service.close()

entered=threading.Event();release=threading.Event();dispatches=[]
def blocked_dispatch(data):
    dispatches.append(1);entered.set()
    assert release.wait(5)
    return dispatch(data)
service=SharedGpuSolver(blocked_dispatch)
cancelled=threading.Event();cancelled.set()
captured=[]
def capture(reference,tasks):
    tasks=list(tasks);captured.append((reference,tasks))
    return map(reference,tasks)
run(lease,solve_map=capture)
reference,tasks=captured[0]
try:
    # Occupy the sole executor, queue a cancelled job, then a live job.
    first=service.submit(reference,tasks[:1],lambda:False)
    assert entered.wait(5)
    stopped=service.submit(reference,tasks[:1],cancelled.is_set)
    survivor=service.submit(reference,tasks[:1],lambda:False)
    release.set()
    assert first.result(timeout=5)==[reference(tasks[0])]
    try:stopped.result(timeout=5)
    except InterruptedError:pass
    else:raise AssertionError('Cancelled GPU job dispatched')
    assert survivor.result(timeout=5)==[reference(tasks[0])]
    assert len(dispatches)==2 and not service.failed
finally:
    release.set();service.close()
print('PASS shared GPU executor: 2/4 job receipt parity, serialization and isolated cancellation')
