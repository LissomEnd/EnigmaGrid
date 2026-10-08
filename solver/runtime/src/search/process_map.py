"""Bounded ordered process batches; caller supplies control checks and lifetime."""
from collections import deque
from concurrent.futures import ProcessPoolExecutor, TimeoutError, CancelledError
from itertools import islice
import multiprocessing
import os
import time
import threading


_generation = None
_percent = None

def _initialize(generation, percent):
    global _generation, _percent
    _generation, _percent = generation, percent

def _gate(generation, started=None, elapsed=0):
    while True:
        current = _generation[generation[0]] if isinstance(generation,tuple) else _generation.value
        expected = generation[1] if isinstance(generation,tuple) else generation
        if current != expected:
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


class ConcurrentProcessMaps:
    """Search-local cancellation over one app-wide process pool and CPU duty.

    Views are single-search iterators. Finishing one view invalidates only its
    own slot; it must never cancel another job using the same process pool.
    """
    def __init__(self,workers,max_searches=4,chunk_size=8):
        if type(workers) is not int or not 1<=workers<=32:raise ValueError('Invalid process count')
        if type(max_searches) is not int or max_searches not in (1,2,4):raise ValueError('Invalid search count')
        if type(chunk_size) is not int or not 1<=chunk_size<=32:raise ValueError('Invalid chunk size')
        if os.name=='nt':
            from search.windows_spawn import HiddenSpawnContext
            context=HiddenSpawnContext()
        else:context=multiprocessing.get_context('spawn')
        self.workers=workers;self.chunk_size=chunk_size;self.max_searches=max_searches
        self.generation=context.Array('Q',max_searches);self.percent=context.Value('i',100)
        self.condition=threading.Condition();self.available=list(range(max_searches));self.closed=False
        self.pool=ProcessPoolExecutor(max_workers=workers,mp_context=context,
            initializer=_initialize,initargs=(self.generation,self.percent))

    def set_percent(self,percent):
        if type(percent) is not int or not 0<=percent<=100:raise ValueError('Invalid CPU duty')
        self.percent.value=percent

    def view(self,check=lambda:None):
        return _ConcurrentSearch(self,check)

    def _acquire(self,check):
        while True:
            check()
            with self.condition:
                if self.closed:raise CancelledError('Process maps closed')
                if self.available:
                    slot=self.available.pop()
                    with self.generation.get_lock():
                        self.generation[slot]+=1;ticket=self.generation[slot]
                    return slot,ticket
                self.condition.wait(.05)

    def _release(self,slot):
        with self.condition:
            with self.generation.get_lock():self.generation[slot]+=1
            self.available.append(slot);self.condition.notify()

    def close(self):
        with self.condition:
            self.closed=True
            with self.generation.get_lock():
                for slot in range(self.max_searches):self.generation[slot]+=1
            self.condition.notify_all()
        self.pool.shutdown(wait=True,cancel_futures=True)

    def __enter__(self):return self
    def __exit__(self,*exc):self.close()


class _ConcurrentSearch:
    def __init__(self,owner,check):
        self.owner=owner;self.check=check;self.lock=threading.Lock()
    def __call__(self,fn,iterable):
        if not self.lock.acquire(blocking=False):raise RuntimeError('Search view already active')
        generation=None;pending=deque();exhausted=False
        try:
            source=iter(iterable)
            generation=self.owner._acquire(self.check)
            while pending or not exhausted:
                self.check()
                while not exhausted and len(pending)<self.owner.workers:
                    items=list(islice(source,self.owner.chunk_size))
                    if not items:exhausted=True;break
                    pending.append(self.owner.pool.submit(_batch,fn,items,generation))
                if not pending:break
                while True:
                    self.check()
                    try:values=pending[0].result(timeout=.05);break
                    except TimeoutError:
                        if pending[0].done():values=pending[0].result();break
                pending.popleft()
                for value in values:self.check();yield value
        finally:
            if generation is not None:self.owner._release(generation[0])
            for future in pending:future.cancel()
            self.lock.release()
