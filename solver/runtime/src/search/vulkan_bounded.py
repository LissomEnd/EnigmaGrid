"""Bounded Vulkan ABI adapter. Activation requires device-local qualification."""
import ctypes
import struct
from pathlib import Path
from search.bounded_crib import crib_rows


def pack(rows, edges, pairs, nodes, boards):
    if not 1 <= len(rows) <= 64 or not 1 <= len(edges) <= 72:
        raise ValueError('Solver batch bounds')
    if any(type(v) is not int for v in (pairs,nodes,boards)) or not 0<=pairs<=13 or not 1<=nodes<=5000 or not 1<=boards<=64:
        raise ValueError('Solver budgets')
    data=[len(rows),len(edges),pairs,nodes,boards]
    for core in rows:
        if len(core)!=len(edges):raise ValueError('Solver row count')
        for row in core:
            if len(row)!=26 or any(type(x) is not int or not 0<=x<26 for x in row):raise ValueError('Solver row')
            if any(row[row[x]]!=x for x in range(26)):raise ValueError('Solver involution')
            data.extend(row)
    for edge in edges:
        if len(edge)!=3 or any(type(x) is not int for x in edge) or not 0<=edge[0]<len(edges) or any(not 0<=x<26 for x in edge[1:]):raise ValueError('Solver edge')
        data.extend(edge)
    return data


def unpack(output, data):
    count,length,pairs,nodes,limit=data[:5]
    if len(output)<2 or output[:2]!=[0xffffffff,count]:raise ValueError('Solver compact header')
    cursor=2;results=[]
    for core in range(count):
        if cursor+3>len(output):raise ValueError('Truncated solver header')
        status,visited,answers=output[cursor:cursor+3];cursor+=3
        if status not in (0,1,2) or not 1<=visited<=nodes or not 0<=answers<=limit or (status==0 and answers) or (status==1 and not answers):raise ValueError('Solver output bounds')
        boards=[];seen=set()
        for _ in range(answers):
            if cursor+26>len(output):raise ValueError('Truncated solver board')
            board=[-1 if x==0xffffffff else x for x in output[cursor:cursor+26]];cursor+=26
            if any(not -1<=x<26 for x in board) or any(y>=0 and board[y]!=x for x,y in enumerate(board)):raise ValueError('Invalid solver board')
            if sum(y>x for x,y in enumerate(board))>pairs or tuple(board) in seen:raise ValueError('Duplicate or excessive pairs')
            seen.add(tuple(board))
            for e in range(length):
                base=5+count*length*26+e*3;position,a,b=data[base:base+3]
                if board[a]<0 or board[b]<0 or data[5+core*length*26+position*26+board[a]]!=board[b]:raise ValueError('Solver constraint mismatch')
            boards.append(board)
        results.append(dict(status=('unsatisfiable','satisfiable','unknown_budget')[status],nodes=visited,partial_boards=boards,full_key_search=False,historical_solution=False))
    if cursor!=len(output):raise ValueError('Trailing solver data')
    return results


class NativeSolver:
    def __init__(self, library, shader):
        shader=Path(shader).read_bytes()
        if not 20<=len(shader)<=1024*1024 or len(shader)%4:raise ValueError('Invalid shader size')
        words=struct.unpack('<'+'I'*(len(shader)//4),shader)
        if words[0]!=0x07230203:raise ValueError('Invalid shader magic')
        self.code=(ctypes.c_uint32*len(words))(*words)
        self.library=ctypes.CDLL(str(Path(library).resolve(strict=True)))
        self.solve=self.library.enigmagrid_solve
        u32=ctypes.POINTER(ctypes.c_uint32)
        self.solve.argtypes=[u32,ctypes.c_size_t,u32,ctypes.c_size_t,u32,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_char),ctypes.c_size_t]
        self.solve.restype=ctypes.c_int
    def __call__(self,data):
        source=(ctypes.c_uint32*len(data))(*data)
        capacity=2+data[0]*(3+data[4]*26)
        output=(ctypes.c_uint32*capacity)();written=ctypes.c_size_t();error=ctypes.create_string_buffer(512)
        status=self.solve(source,len(data),self.code,len(self.code),output,capacity,ctypes.byref(written),error,len(error))
        if status:raise RuntimeError(error.value.decode('utf-8',errors='replace') or 'Vulkan solver failed')
        if written.value>capacity:raise ValueError('Invalid native output length')
        return list(output[:written.value])


class SolverMap:
    """Ordered map hook for bounded_crib.search; no implicit production activation."""
    def __init__(self,dispatch,checkpoint=lambda:None):
        self.dispatch=dispatch;self.checkpoint=checkpoint
    def __call__(self,reference,tasks):
        tasks=iter(tasks)
        while True:
            batch=[]
            for _ in range(64):
                try:batch.append(next(tasks))
                except StopIteration:break
            if not batch:return
            self.checkpoint()
            _,offset,length,edges,pairs,nodes,boards=batch[0]
            if len(edges)!=length or any(task[1:]!=batch[0][1:] for task in batch) or nodes>5000 or boards>64:
                # Unsupported scopes retain the existing reference semantics.
                for task in batch:
                    self.checkpoint();yield reference(task)
                continue
            data=pack([crib_rows(t[0],offset,length) for t in batch],edges,pairs,nodes,boards)
            results=unpack(self.dispatch(data),data)
            self.checkpoint()
            yield from results


class BudgetedDispatch:
    """One backend-time duty budget; this is not hardware GPU utilization."""
    def __init__(self,dispatch,percent=lambda:100,cancelled=lambda:False,clock=None,sleep=None):
        import time,threading
        self.dispatch=dispatch;self.percent=percent;self.cancelled=cancelled
        self.clock=clock or time.monotonic;self.sleep=sleep or time.sleep
        self.lock=threading.Lock();self.finished=None;self.duration=0
    def __call__(self,data):
        return self.call(data)

    def call(self,data,cancelled=lambda:False):
        def stopped():return self.cancelled() or cancelled()
        while not self.lock.acquire(timeout=.02):
            if stopped():raise InterruptedError('GPU dispatch cancelled')
        try:
            while True:
                if stopped():raise InterruptedError('GPU dispatch cancelled')
                pct=self.percent()
                if type(pct) is not int or not 0<=pct<=100:raise ValueError('GPU duty must be 0..100')
                if pct==0:raise InterruptedError('GPU disabled')
                # Recompute at every poll: raising to100 cancels any owed rest.
                delay=0 if pct==100 or self.finished is None else self.finished+self.duration*(100-pct)/pct-self.clock()
                if delay<=0:break
                self.sleep(min(.02,delay))
            began=self.clock()
            try:return self.dispatch(data)
            finally:self.finished=self.clock();self.duration=max(0,self.finished-began)
        finally:self.lock.release()


class SharedGpuSolver:
    """One native executor and duty budget for every concurrent local job."""
    def __init__(self,dispatch,percent=lambda:100):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        self.closed=threading.Event();self.failed=False
        self.budget=BudgetedDispatch(dispatch,percent,self.closed.is_set)
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='bounded-gpu')

    def submit(self,reference,items,cancelled):
        def solve():
            if self.failed:raise RuntimeError('Shared GPU backend failed')
            def check():
                if self.closed.is_set() or cancelled():raise InterruptedError('GPU search cancelled')
            solver=SolverMap(lambda data:self.budget.call(data,cancelled),check)
            try:return list(solver(reference,items))
            except (RuntimeError,ValueError):
                self.failed=True
                raise
        return self.pool.submit(solve)

    def close(self):
        self.closed.set()
        self.pool.shutdown(wait=True,cancel_futures=True)


class HybridSolverMap:
    """Disjoint CPU/GPU work with deterministic reduction and caller-owned CPU map."""
    def __init__(self,dispatch,cpu_map,gpu_cores=64,checkpoint=lambda:None,
                 gpu_enabled=lambda:True,on_failure=lambda error:None,gpu_percent=lambda:100,
                 gpu_service=None):
        if type(gpu_cores) is not int or not 1<=gpu_cores<=128:raise ValueError('Invalid GPU share')
        import threading
        self.cancelled=threading.Event()
        self.service=gpu_service or SharedGpuSolver(dispatch,gpu_percent)
        self.owns_service=gpu_service is None
        self.cpu=cpu_map;self.gpu_cores=gpu_cores
        self.checkpoint=checkpoint;self.gpu_enabled=gpu_enabled;self.on_failure=on_failure
    @property
    def failed(self):return self.service.failed
    def __call__(self,reference,tasks):
        from itertools import islice
        from concurrent.futures import TimeoutError
        self.cancelled.clear()
        source=iter(tasks)
        while True:
            batch=list(islice(source,128))
            if not batch:return
            self.checkpoint()
            _,offset,length,edges,pairs,nodes,boards=batch[0]
            supported=(len(edges)==length and 1<=length<=72 and nodes<=5000 and boards<=64
                       and all(task[1:]==batch[0][1:] for task in batch))
            if self.failed or not self.gpu_enabled() or not supported:
                yield from self.cpu(reference,batch)
                continue
            self.cancelled.clear()
            split=min(self.gpu_cores,len(batch))
            future=self.service.submit(reference,batch[:split],self.cancelled.is_set)
            try:
                cpu_results=list(self.cpu(reference,batch[split:])) if batch[split:] else []
                while not future.done():
                    self.checkpoint()
                    try:future.result(timeout=.05)
                    except TimeoutError:
                        if not future.done():continue
                    except (RuntimeError,ValueError):break
                try:gpu_results=future.result()
                except (RuntimeError,ValueError) as error:
                    self.on_failure(error)
                    # CPU map is now idle; replay only the failed GPU partition.
                    gpu_results=list(self.cpu(reference,batch[:split]))
                self.checkpoint()
                yield from gpu_results
                yield from cpu_results
            finally:
                self.cancelled.set()
                # Join bounded native work, preserving the original stop or CPU
                # failure instead of replacing it with a secondary GPU exception.
                if not future.cancel():
                    try:future.result()
                    except Exception:pass
    def close(self):
        self.cancelled.set()
        if self.owns_service:self.service.close()
