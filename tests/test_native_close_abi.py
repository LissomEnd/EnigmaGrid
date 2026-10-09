"""Host check: old DLLs fail before the first native dispatch."""
import struct
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo / 'solver/runtime/src'))
from search import vulkan_bounded

with tempfile.TemporaryDirectory() as temporary:
    dll = Path(temporary) / 'old.dll'
    shader = Path(temporary) / 'shader.spv'
    dll.write_bytes(b'placeholder')
    shader.write_bytes(struct.pack('<5I', 0x07230203, 0, 0, 0, 0))
    solve = Mock()
    with patch.object(vulkan_bounded.ctypes, 'CDLL', return_value=SimpleNamespace(enigmagrid_solve=solve)):
        try:
            vulkan_bounded.NativeSolver(dll, shader)
        except RuntimeError as error:
            assert 'explicit close ABI' in str(error), str(error)
        else:
            raise AssertionError('Old DLL accepted without close ABI')
    solve.assert_not_called()
    assert not vulkan_bounded._NATIVE_LIBRARIES

print('PASS: old native DLL rejected before dispatch')
