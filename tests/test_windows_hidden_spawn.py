"""No GUI: mock WinAPI flags, then exercise one hidden child without a solver."""
import os,sys,subprocess,multiprocessing
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'solver/runtime/src'))
def child(q):
 import ctypes
 q.put(bool(ctypes.windll.kernel32.GetConsoleWindow()))
def main():
 if os.name!='nt':return
 from search.windows_spawn import HiddenSpawnContext,_HiddenWinAPI,_private_globals
 from multiprocessing import popen_spawn_win32
 api=Mock();startup=subprocess.STARTUPINFO();facade=_HiddenWinAPI(api)
 facade.CreateProcess('app','cmd',None,None,False,subprocess.DETACHED_PROCESS,None,None,startup)
 args=api.CreateProcess.call_args.args
 assert args[5]&subprocess.CREATE_NO_WINDOW and not args[5]&subprocess.DETACHED_PROCESS
 assert args[8].dwFlags&subprocess.STARTF_USESHOWWINDOW and args[8].wShowWindow==subprocess.SW_HIDE
 assert popen_spawn_win32.Popen.__init__.__globals__['_winapi'] is not _private_globals['_winapi']
 ctx=HiddenSpawnContext();q=ctx.Queue();p=ctx.Process(target=child,args=(q,));p.start()
 try:assert q.get(timeout=10) is False,'Child unexpectedly owns a console';p.join(10);assert p.exitcode==0
 finally:
  if p.is_alive():p.terminate();p.join()
  q.close();q.join_thread()
 print('WINDOWS_PRIVATE_SPAWN_FLAGS_AND_REAL_CONSOLE_FREE_CHILD_OK')
if __name__=='__main__':multiprocessing.freeze_support();main()
