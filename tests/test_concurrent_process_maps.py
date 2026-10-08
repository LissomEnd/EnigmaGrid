"""Real spawned-process qualification for shared CPU search views."""
import multiprocessing
import os
import sys
import threading
import time
from concurrent.futures import CancelledError, ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'solver/runtime/src'))
from search.process_map import ConcurrentProcessMaps


def work(value):
    time.sleep(.005)
    return value * value, os.getpid()


def main():
    with ConcurrentProcessMaps(2, chunk_size=2) as owner:
        for lanes in (1, 2, 4):
            barrier = threading.Barrier(lanes)
            def search():
                barrier.wait(timeout=10)
                return list(owner.view()(work, range(24)))
            with ThreadPoolExecutor(lanes) as callers:
                results = list(callers.map(lambda _: search(), range(lanes)))
            assert all([v for v, pid in result] == [v*v for v in range(24)] for result in results)
            assert len({pid for result in results for v, pid in result}) <= 2
        # An invalid iterable must not permanently lock the reusable view.
        view = owner.view()
        try:
            list(view(work, None))
        except TypeError:
            pass
        else:
            raise AssertionError('Invalid iterable accepted')
        assert list(view(work, [3]))[0][0] == 9

        cancel = threading.Event()
        checked = threading.Event()
        def check():
            checked.set()
            if cancel.is_set():
                raise CancelledError()
        owner.set_percent(0)
        with ThreadPoolExecutor(2) as callers:
            stopped = callers.submit(lambda: list(owner.view(check)(work, range(100))))
            survivor = callers.submit(lambda: list(owner.view()(work, range(16))))
            assert checked.wait(5)
            time.sleep(.15)
            assert not survivor.done(), 'Paused pool executed work'
            cancel.set()
            try:
                stopped.result(timeout=5)
            except CancelledError:
                pass
            else:
                raise AssertionError('Cancellation ignored')
            owner.set_percent(100)
            assert [v for v, pid in survivor.result(timeout=10)] == [v*v for v in range(16)]
        # Closing while paused must wake child gates rather than deadlock.
        owner.set_percent(0)
        with ThreadPoolExecutor(1) as callers:
            pending = callers.submit(lambda: list(owner.view()(work, range(100))))
            time.sleep(.15)
            owner.close()
            try:
                pending.result(timeout=5)
            except (CancelledError, RuntimeError):
                pass
            else:
                raise AssertionError('Closed search completed unexpectedly')
    assert not multiprocessing.active_children(), 'Worker process leaked'
    print('PASS 1/2/4 searches, shared process bound, isolated cancellation, pause/resume and close')


if __name__ == '__main__':
    main()
