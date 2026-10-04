"""Headless regression checks: no native dialogs and no executable launches."""
import sys,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'worker'),str(ROOT/'solver/runtime/src')]
import worker,updater,updater_apply
G=1024**3
assert worker.constrained_process_limit(32,available_bytes=12*G,total_bytes=16*G)==8
assert worker.constrained_process_limit(32,available_bytes=5*G,total_bytes=16*G)==2
assert worker.constrained_process_limit(32,available_bytes=3*G,total_bytes=16*G)==0
assert worker.constrained_process_limit(1,available_bytes=12*G,total_bytes=16*G)==1
assert worker.constrained_process_limit(8,available_bytes=4*G,total_bytes=16*G,existing_workers=4)==4
assert worker.constrained_process_limit(8,available_bytes=3*G,total_bytes=16*G,existing_workers=4)==2
class Pool:
 workers=4
 closed=False
 def close(self):self.closed=True
p=Pool();runtime={'_constrained_pool':p};worker.release_constrained_pool(runtime);assert p.closed and '_constrained_pool' not in runtime
with patch.object(worker,'constrained_process_limit',return_value=0),patch.object(worker,'run_constrained',return_value=('serial',0)) as serial:
 runtime={'settings':{'cpu_percent':100,'allow_cpu':True},'_constrained_pool':Pool()}
 assert worker.run_constrained_parallel({},runtime,None)==('serial',0)
 assert serial.call_args.args[1]['_parallel_constrained'] is False
with tempfile.TemporaryDirectory() as d:
 root=Path(d)
 for n in ('EnigmaGrid.exe','EnigmaGridWorker.exe','EnigmaGridUpdater.exe'):(root/n).write_bytes(b'MZ'+b'0'*100001)
 with patch.object(updater_apply.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
  updater_apply.preflight(root,'frozen')
  if sys.platform=='win32':assert run.call_args.kwargs['creationflags'] & updater_apply.subprocess.CREATE_NO_WINDOW
 manager=updater.UpdateManager('0.4.4',root/'client.json','https://example.org');manager.apply_requested=True;manager.pending={'asset':'a','manifest':'m','signature':'s'}
 with patch.object(updater.subprocess,'Popen') as launch:
  assert manager.launch_apply(root)
  if sys.platform=='win32':
   flags=launch.call_args.kwargs['creationflags'];assert flags & updater.subprocess.CREATE_NO_WINDOW and not flags & updater.subprocess.DETACHED_PROCESS
print('HEADLESS_MEMORY_LIMIT_SERIAL_FALLBACK_POOL_RELEASE_AND_HIDDEN_UPDATER_OK')
