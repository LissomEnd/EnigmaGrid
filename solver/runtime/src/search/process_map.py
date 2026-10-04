"""Bounded ordered process batches; caller supplies control checks and lifetime."""
from collections import deque
from concurrent.futures import ProcessPoolExecutor, TimeoutError, CancelledError
from itertools import islice
import multiprocessing
import os
import time


_generation = None
_percent = None

def _initialize(generation, percent):
    global _generation, _percent
    _generation, _percent = generation, percent

def _gate(generation, started=None, elapsed=0):
    while True:
        if _generation.value != generation:
            raise CancelledError('Obsolete search batch')
        percent = _percent.value
        if percent:
            rest = elapsed * (100-percent) / percent
            if started is None or time.monotonic()-started >= rest:
                return
        time.sleep(.02)

def _batch(fn, items, generation):
    values = []
    for item in items:
        _gate(generation)
        started=time.monotonic()
        values.append(fn(item))
        elapsed=time.monotonic()-started
        _gate(generation,time.monotonic(),elapsed)
    return values


class OrderedProcessMap:
    def __init__(self, workers, chunk_size=16, check=lambda: None):
        if type(workers) is not int or not 1 <= workers <= 32:
            raise ValueError('Invalid process count')
        if type(chunk_size) is not int or not 1 <= chunk_size <= 32:
            raise ValueError('Invalid chunk size')
        self.workers, self.chunk_size, self.check = workers, chunk_size, check
        if os.name == 'nt':
            from search.windows_spawn import HiddenSpawnContext
            context = HiddenSpawnContext()
        else:
            context = multiprocessing.get_context('spawn')
        self.generation = context.Value('Q', 0)
        self.percent = context.Value('i', 100)
        self.active = False
        self.pool = ProcessPoolExecutor(max_workers=workers, mp_context=context,
            initializer=_initialize, initargs=(self.generation,self.percent))

    def set_percent(self, percent):
        if type(percent) is not int or not 0 <= percent <= 100:
            raise ValueError('Invalid CPU duty')
        self.percent.value = percent

    def __call__(self, fn, iterable):
        if self.active:
            raise RuntimeError('A search is already active')
        self.active = True
        with self.generation.get_lock():
            self.generation.value += 1
            generation = self.generation.value
        pending = deque()
        source = iter(iterable)
        exhausted = False
        try:
            while pending or not exhausted:
                self.check()
                while not exhausted and len(pending) < self.workers:
                    items = list(islice(source, self.chunk_size))
                    if not items:
                        exhausted = True
                        break
                    pending.append(self.pool.submit(_batch, fn, items, generation))
                if not pending:
                    break
                while True:
                    self.check()
                    try:
                        values = pending[0].result(timeout=0.05)
                        break
                    except TimeoutError:
                        if pending[0].done():
                            # Completion can race the polling deadline. Retrieve the
                            # terminal result, propagating only a real task failure.
                            values = pending[0].result()
                            break
                pending.popleft()
                for value in values:
                    self.check()
                    yield value
        finally:
            # Running batches finish at most their current core; they do not
            # continue all remaining cores after a candidate cap or stop.
            with self.generation.get_lock():
                self.generation.value += 1
            self.active = False
            for future in pending:
                future.cancel()

    def close(self):
        with self.generation.get_lock():
            self.generation.value += 1
        self.pool.shutdown(wait=True, cancel_futures=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
