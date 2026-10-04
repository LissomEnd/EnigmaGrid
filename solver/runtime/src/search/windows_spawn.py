"""Windows spawn context that never allocates a child console.

Uses CPython's own spawn constructor with a private WinAPI facade. Its globals
are copied, never patched in place: other multiprocessing users are unaffected.
Handle transfer, frozen/venv startup and teardown remain the stdlib behavior.
"""
import types
import multiprocessing.context
from multiprocessing import popen_spawn_win32
import subprocess


class _HiddenWinAPI:
    def __init__(self, api):self.api=api
    def __getattr__(self, name):return getattr(self.api,name)
    def CreateProcess(self, application, command, process_security, thread_security,
                      inherit, flags, environment, directory, startup):
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        flags = (flags & ~subprocess.DETACHED_PROCESS) | subprocess.CREATE_NO_WINDOW
        return self.api.CreateProcess(application,command,process_security,
            thread_security,inherit,flags,environment,directory,startup)


_original_init=popen_spawn_win32.Popen.__init__
_private_globals=dict(_original_init.__globals__)
_private_globals['_winapi']=_HiddenWinAPI(_private_globals['_winapi'])
_hidden_init=types.FunctionType(_original_init.__code__,_private_globals,
                              _original_init.__name__,_original_init.__defaults__,
                              _original_init.__closure__)


class HiddenPopen(popen_spawn_win32.Popen):
    __init__=_hidden_init


class HiddenSpawnProcess(multiprocessing.context.SpawnProcess):
    @staticmethod
    def _Popen(process_obj):return HiddenPopen(process_obj)


class HiddenSpawnContext(multiprocessing.context.SpawnContext):
    Process=HiddenSpawnProcess
