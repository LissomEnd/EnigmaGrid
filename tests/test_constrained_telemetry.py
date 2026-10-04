"""Constrained progress must not synchronously write one file per mechanical core."""
import ast
import pathlib
import sys
import types
from unittest.mock import patch

root=pathlib.Path(__file__).resolve().parents[1]
tree=ast.parse((root/'worker/worker.py').read_text())
fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_constrained')
class Clock:
    now=0.0
    def monotonic(self): return self.now
    def sleep(self,n): self.now+=n
clock=Clock();writes=[];reads=[]
def control(path):
    reads.append(path)
    return {'paused':False,'stop_requested':False}
def fake_run(lease,checkpoint):
    for i in range(129):
        clock.now+=0.001
        checkpoint(i,128)
    return {'receipt':{'candidates':[]}}
module=types.ModuleType('search.crib_work');module.run=fake_run
namespace={'time':clock,'read_control':control,'publish_health':lambda runtime,status:writes.append((clock.now,runtime.get('progress')))}
exec(compile(ast.Module(body=[fn],type_ignores=[]),'<worker function>','exec'),namespace)
with patch.dict(sys.modules,{'search':types.ModuleType('search'),'search.crib_work':module}):
    runtime={'settings':{'allow_cpu':True,'cpu_percent':100}}
    namespace['run_constrained']({},runtime,'state')
    assert len(writes)==2,writes
    assert len(reads)==129,'Control responsiveness reduced'
    assert writes[-1][1]==1.0,'Final progress lost'
    namespace['read_control']=lambda path:{'paused':False,'stop_requested':True}
    try: namespace['run_constrained']({},runtime,'state')
    except InterruptedError: pass
    else: raise AssertionError('Stop ignored')
print('PASS bounded telemetry writes, every-core controls, final progress and stop')
