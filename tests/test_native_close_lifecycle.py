"""Host checks for final Vulkan ownership; no device or network I/O."""
import contextlib
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo / 'worker'))
import worker


def run_worker_case(active_owner):
    events = []

    def fake_work(_args, _state, runtime):
        if active_owner:
            runtime['_shared_gpu_solver'] = object()
        return 17

    replacements = {
        '_work': fake_work,
        'suspend_long_blocks': lambda runtime: events.append('blocks'),
        'release_portable_executor': lambda runtime: events.append('portable'),
        'release_unused_work': lambda state, runtime: events.append('leases'),
        'release_constrained_pool': lambda runtime: events.append('constrained'),
        'close_global_opencl_scorers': lambda: events.append('opencl'),
        'close_global_native_solvers': lambda: events.append('native'),
        'disable_global_native_auto_close': lambda: events.append('disable_auto'),
    }
    with contextlib.ExitStack() as stack:
        for name, replacement in replacements.items():
            stack.enter_context(patch.object(worker, name, replacement))
        if active_owner:
            try:
                worker.work(SimpleNamespace(), {})
            except RuntimeError as error:
                assert 'vulkan:owners_active' in str(error), str(error)
            else:
                raise AssertionError('Active native owner was closed')
            assert 'native' not in events and 'disable_auto' in events, events
        else:
            assert worker.work(SimpleNamespace(), {}) == 17
            assert events.index('native') > events.index('constrained'), events
            assert 'disable_auto' not in events, events


run_worker_case(False)
run_worker_case(True)

with patch.object(worker, 'qualify_bounded_gpu_client', return_value={'qualified': False}), \
     patch.object(worker, 'close_global_native_solvers') as native, \
     patch.object(sys, 'argv', ['worker.py', '--qualify-bounded-gpu']):
    with contextlib.redirect_stdout(io.StringIO()):
        worker.main()
    native.assert_called_once_with()

print('PASS: native close follows joined owners; unsafe owner suppresses close; standalone qualification finalizes')
