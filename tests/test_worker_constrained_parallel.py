import sys,tempfile,multiprocessing
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'worker'),str(root/'solver/runtime/src')]
import worker

def main():
 job=dict(engine='bounded_crib_v1',ciphertext='A'*72,crib='B'*24,offset=0,core_indices=list(range(32)),model='clean',pairs=10,budgets=dict(node_limit=10,board_limit=1,completion_limit=1,candidate_limit=1))
 lease=dict(engine='bounded_crib_v1',start_unit=0,end_unit=1,config=dict(job=job,requires=['cpu','bounded_crib_v1']))
 runtime={'settings':{'cpu_percent':100,'allow_cpu':True},'_parallel_constrained':True}
 # Resource-limit policy is covered separately; parity needs a deterministic
 # two-child fixture regardless of the test host's free RAM.
 with tempfile.TemporaryDirectory() as tmp,patch.object(worker.os,'cpu_count',return_value=2),patch.object(worker,'constrained_process_limit',side_effect=lambda requested,**kw:min(2,requested)):
  state=Path(tmp)/'state.json';worker.write_control(state,{})
  try:
   expected=worker.run_constrained(lease,{'settings':runtime['settings']},state)
   assert worker.run_constrained(lease,runtime,state)==expected
   pool=runtime['_constrained_pool']
   assert worker.run_constrained(lease,runtime,state)==expected and runtime['_constrained_pool'] is pool
   # Exercise the real parent callback while preferences change during pause.
   controls=iter([{'paused':True},{'paused':False}])
   def change_limit(seconds):runtime['settings']={'cpu_percent':25,'allow_cpu':True}
   with patch.object(worker,'read_control',side_effect=lambda path:next(controls)),patch.object(worker.time,'sleep',side_effect=change_limit):
    pool.check()
   assert pool.percent.value==25,'Stale pre-pause duty restored'
   assert worker.run_constrained(lease,runtime,state)==expected
   assert runtime['_constrained_pool'].workers==1 and runtime['_constrained_pool'] is not pool
   assert runtime['_constrained_pool'].percent.value==50,'Fractional aggregate CPU limit'
   pool=runtime['_constrained_pool']
   controls=iter([{'paused':True},{'paused':False}])
   def disable(seconds):runtime['settings']={'cpu_percent':0,'allow_cpu':False}
   with patch.object(worker,'read_control',side_effect=lambda path:next(controls)),patch.object(worker.time,'sleep',side_effect=disable):
    try:pool.check()
    except InterruptedError:pass
    else:raise AssertionError('CPU disabled during pause ignored')
   assert pool.percent.value==0
   runtime['settings']={'cpu_percent':25,'allow_cpu':True}
   worker.write_control(state,{'stop_requested':True})
   try:worker.run_constrained(lease,runtime,state)
   except InterruptedError:pass
   else:raise AssertionError('stop ignored')
  finally:
   if runtime.get('_constrained_pool'):runtime['_constrained_pool'].close()
 class PoolProbe:
  closed=False
  def close(self):self.closed=True
 for fail in (False,True):
  probe=PoolProbe()
  def loop(args,state,runtime):
   assert runtime['_parallel_constrained']
   runtime['_constrained_pool']=probe
   if fail:raise RuntimeError('injected')
   return 0
  with patch.object(worker,'_work',side_effect=loop):
   try:assert worker.work(None,{'settings':{}})==0
   except RuntimeError:assert fail
  assert probe.closed,'Pool leaked on client exit'
 assert not multiprocessing.active_children()
 print('PASS client parallel routing, receipt parity, pool reuse and stop')
if __name__=='__main__':main()
