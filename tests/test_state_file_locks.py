"""Reproduce Windows reader locks without allowing telemetry to kill work."""
import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'worker'))
import worker
from file_state import atomic_write

with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / 'worker-health.json'
    atomic_write(path, b'{"previous":true}')
    runtime = {'health_path': path, 'progress': 0.5}
    with patch('file_state.Path.replace', side_effect=PermissionError('locked')):
        assert worker.publish_health(runtime, 'computing') is False
        assert json.loads(path.read_text()) == {'previous': True}
        try:
            worker.save_plain_json(path, {'control': True})
            raise AssertionError('Durable writes must report persistent failure')
        except PermissionError:
            pass
    assert not list(Path(directory).glob('*.tmp'))
    assert worker.publish_health(runtime, 'computing')
    assert json.loads(path.read_text())['progress'] == 0.5
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
            ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        # Sharing read/write but not DELETE reproduces Get-Content/AV readers.
        handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0, None)
        assert handle not in (None, ctypes.c_void_p(-1).value)
        timer = threading.Timer(0.12, lambda: kernel.CloseHandle(handle))
        timer.start()
        try:
            assert worker.publish_health(runtime, 'paused')
        finally:
            timer.join()
        assert json.loads(path.read_text())['status'] == 'paused'
    assert not list(Path(directory).glob('*.tmp'))
print('STATE_FILE_LOCK_RECOVERY_OK')
