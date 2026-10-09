"""Local compute with independent bounded allocation and upload executors."""
import time
import math
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from queue import Queue, Empty, Full
from search.work_block import prefetch_due
from block_transport import ReceiptRejected
from block_queue import QueueCapacityError

class BlockPipeline:
    def __init__(self,queue,transport,execute,*,lanes=1,gpu_execute=None):
        if type(lanes) is not int or lanes not in (1,2,3,4):raise ValueError('Compute lanes must be 1..4')
        if gpu_execute is not None and (not callable(gpu_execute) or lanes<2):
            raise ValueError('GPU lane requires at least one CPU lane')
        self.queue=queue;self.transport=transport;self.execute=execute
        self.lanes=lanes;self.stop_event=threading.Event();self.running={}
        self.gpu_execute=gpu_execute;self.gpu_running=set()
        self.solvers=ThreadPoolExecutor(max_workers=lanes-(gpu_execute is not None),thread_name_prefix='block-compute')
        self.gpu_solvers=(ThreadPoolExecutor(max_workers=1,thread_name_prefix='block-gpu-job')
                          if gpu_execute is not None else None)
        self.writer=ThreadPoolExecutor(max_workers=1,thread_name_prefix='block-persist')
        self.waiting_writes=Queue(maxsize=2*lanes)
        self.writes=[];self.writes_lock=threading.Lock();self.allow_next=True
        self.fetcher=ThreadPoolExecutor(max_workers=1,thread_name_prefix='block-prefetch')
        self.controller=ThreadPoolExecutor(max_workers=1,thread_name_prefix='block-control')
        self.control=None;self.next_control=0
        self.status_reader=ThreadPoolExecutor(max_workers=1,thread_name_prefix='block-status')
        self.status=None;self.next_status=0
        self.sender=ThreadPoolExecutor(max_workers=1,thread_name_prefix='block-upload')
        self.fetch=None;self.upload=None;self.next_fetch=0;self.next_upload=0
        # Fill the first available two-block window toward 30 minutes before
        # switching to the ordinary ten-minute successor threshold.
        self.initial_fill=True
        self.initial_fill_samples=[]
        self.initial_fill_latch_rate=0
        self.empty_fetches=0
        self.upload_latency=.25;self.upload_started=0
        self.upload_seconds=0.0;self.lease_seconds=0.0
        self.rate=0;self.closed=False;self.shutdown_complete=False;self.shutdown_error=None
        self.last_error=None;self.wait_reason=None;self.terminal_error=None
        self.fill_rate_hint=0

    def _timed_upload(self):
        began=time.monotonic()
        result=self.transport.upload()
        elapsed=max(.001,time.monotonic()-began)
        self.upload_seconds+=elapsed
        return result,elapsed

    def _timed_allocate(self):
        began=time.monotonic()
        try:return self.transport.allocate()
        finally:self.lease_seconds+=max(0,time.monotonic()-began)

    @property
    def computing(self):return any(not task.done() for task in self.running)

    def _persist(self,completion):
        durable=Future()
        # Reservations, including their byte budget, already exist before compute.
        # Do not wait for storage on a solver thread until its second job finishes.
        try:self.waiting_writes.put_nowait((completion,durable))
        except Full:raise RuntimeError('Bounded writer reservations exceeded')
        with self.writes_lock:self.writes.append(durable)
        self.writer.submit(self._flush_ready)
        return durable

    def _flush_ready(self):
        batch=[]
        for _ in range(4):
            try:batch.append(self.waiting_writes.get_nowait())
            except Empty:break
        if not batch:return
        try:self.queue.complete_batch([completion for completion,_ in batch])
        except BaseException as error:
            for _,durable in batch:durable.set_exception(error)
        else:
            for _,durable in batch:durable.set_result(None)

    def _compute(self,batch,execute=None):
        execute=execute or self.execute
        persisted=[];seconds=0;count=0
        for identity,envelope in batch:
            if self.stop_event.is_set() or not self.allow_next:break
            for durable in persisted:
                if durable.done():durable.result()
            began=time.monotonic();result=execute(envelope)
            elapsed=max(.000001,time.monotonic()-began)
            # Stop racing with a completed calculation must still save its receipt.
            persisted.append(self._persist((identity,envelope['start_unit'],result,elapsed)))
            seconds+=elapsed;count+=1
        for durable in persisted:durable.result()
        return max(.000001,seconds/count) if count else None

    def _release(self,batch):
        for identity,envelope in batch:self.queue.release_claim(identity,envelope['start_unit'])

    def poll_control(self, refresh):
        """Return completed controls without making the compute thread wait on HTTP."""
        if self.closed:raise RuntimeError('Pipeline closed')
        now=time.monotonic();response=None
        if self.control is not None and self.control.done():
            try:response=self.control.result()
            except (OSError,TimeoutError) as error:
                self.last_error=type(error).__name__
            finally:self.control=None;self.next_control=now+20
        if self.control is None and now>=self.next_control:
            self.control=self.controller.submit(refresh)
        return response

    def poll_status(self):
        """Reservation status must not hold up an already received disable command."""
        if self.closed:raise RuntimeError('Pipeline closed')
        now=time.monotonic()
        if self.status is not None and self.status.done():
            try:self.status.result()
            except (OSError,TimeoutError) as error:self.last_error=type(error).__name__
            finally:self.status=None;self.next_status=now+20
        if self.status is None and now>=self.next_status:
            self.status=self.status_reader.submit(self.transport.refresh_status)

    def tick(self,*,allow_compute=True):
        if self.closed:raise RuntimeError('Pipeline closed')
        self.allow_next=allow_compute
        now=time.monotonic()
        for attr,deadline in (('fetch','next_fetch'),('upload','next_upload')):
            task=getattr(self,attr)
            if task is not None and task.done():
                try:
                    response=task.result()
                    if attr=='upload':
                        # Measure in the sender, not after a long computation or
                        # thermal pause finally returns control to this loop.
                        response,elapsed=response
                        self.upload_latency=max(elapsed,.8*self.upload_latency+.2*elapsed)
                    if attr=='fetch':
                        self.wait_reason=response.get('wait_reason')
                        if not response.get('block'):
                            # Respect the server's retry floor and back off
                            # when there is no eligible successor.
                            self.empty_fetches=min(8,self.empty_fetches+1)
                            try:delay=float(response.get('retry_after_seconds',0))
                            except (TypeError,ValueError):delay=1
                            if not math.isfinite(delay):delay=0
                            # Empty responses must not become a 1 Hz poll while
                            # the first block is short and no successor exists.
                            self.next_fetch=now+min(300,max(delay,min(30,2**(self.empty_fetches-1))))
                        else:
                            self.empty_fetches=0
                            block=response['block'];estimate=response.get('estimated_seconds')
                            if (isinstance(block,dict) and type(estimate) in (int,float)
                                    and math.isfinite(estimate) and estimate>0):
                                start,end=block.get('start_unit'),block.get('end_unit')
                                if type(start) is int and type(end) is int and end>start:
                                    # A server-observed estimate lets the first
                                    # successor arrive before the first job ends.
                                    hint=(end-start)/estimate
                                    if math.isfinite(hint) and hint>0:self.fill_rate_hint=hint
                except ReceiptRejected as error:
                    self.terminal_error=str(error)
                except QueueCapacityError:
                    # A refill can race with receipt persistence. Keep its durable
                    # request ID and replay it after the independent uploader drains.
                    if attr!='fetch':raise
                    self.wait_reason='result_storage_full';self.next_fetch=now+1
                except (OSError,TimeoutError) as error:
                    self.last_error=type(error).__name__;setattr(self,deadline,now+5)
                finally:setattr(self,attr,None)
        if self.terminal_error:return False
        remaining,blocks=self.queue.remaining()
        pending=self.queue.pending()
        reserve_rate=self.rate if self.rate>0 else self.fill_rate_hint
        # A server estimate may be a default for an uncalibrated validator;
        # only several stable, distinct durable completions can close fill.
        initial_due=(remaining==0 or (reserve_rate>0 and remaining/reserve_rate<1800))
        refill_due=initial_due if self.initial_fill else prefetch_due(remaining,self.rate)
        # A full durable outbox cannot consume another reservation. Upload is
        # independent and will reopen this path after an acknowledgement.
        if (allow_compute and self.fetch is None and blocks<2 and now>=self.next_fetch
                and len(pending)<getattr(self.queue,'max_pending',8) and refill_due):
            self.fetch=self.fetcher.submit(self._timed_allocate)
        if pending and self.upload is None and now>=self.next_upload:
            # Aggregate tiny units for up to a second; a full outbox is sent now.
            capacity=getattr(self.queue,'max_pending',8)
            headroom=min(capacity-1,max(1,math.ceil(self.upload_latency*self.rate)+1))
            if len(pending)>=capacity-headroom or not remaining or now>=getattr(self,'flush_at',0):
                self.upload_started=now
                self.upload=self.sender.submit(self._timed_upload);self.flush_at=now+1
        if not allow_compute:return False
        worked=False
        for task in list(self.running):
            if not task.done():continue
            seconds=task.result();self._release(self.running.pop(task))
            self.gpu_running.discard(task)
            if seconds is not None:
                measured=self.lanes/seconds
                self.rate=measured if self.rate==0 else .8*self.rate+.2*measured
                self._observe_initial_fill()
            worked=True
        with self.writes_lock:
            for durable in list(self.writes):
                if durable.done():durable.result();self.writes.remove(durable)
        free_cpu=self.lanes-(self.gpu_solvers is not None)-(len(self.running)-len(self.gpu_running))
        free_gpu=(1-len(self.gpu_running)) if self.gpu_solvers is not None else 0
        if free_cpu or free_gpu:
            routes=[]
            if free_cpu:routes.append(('cpu',[]));free_cpu-=1
            if free_gpu:routes.append(('gpu',[]))
            routes.extend(('cpu',[]) for _ in range(free_cpu))
            # Reserve the complete window before launching any persistence writer.
            for _ in range(2):
                for _,batch in routes:
                    current=self.queue.claim_prefetched(self.lanes)
                    if current is not None:batch.append(current)
            for route,batch in routes:
                if not batch:continue
                executor=self.gpu_solvers if route=='gpu' else self.solvers
                execute=self.gpu_execute if route=='gpu' else self.execute
                try:
                    task=executor.submit(self._compute,batch,execute)
                    self.running[task]=batch
                    if route=='gpu':self.gpu_running.add(task)
                except BaseException:
                    self._release(batch);raise
        return worked

    def _observe_initial_fill(self):
        if self.rate<=0:return
        remaining,_=self.queue.remaining()
        # The first stable, slow jobs can overstate how long a block will last.
        # Reopen the initial target only after a material measured rate increase;
        # ordinary, comparable rates retain the ten-minute refill threshold.
        if not self.initial_fill:
            if (self.initial_fill_latch_rate>0
                    and self.rate>self.initial_fill_latch_rate*1.15
                    and remaining/self.rate<1800):
                self.initial_fill=True
                self.initial_fill_samples.clear()
            return
        if remaining/self.rate<1800:
            self.initial_fill_samples.clear();return
        self.initial_fill_samples.append(self.rate)
        self.initial_fill_samples=self.initial_fill_samples[-3:]
        if len(self.initial_fill_samples)==3 and max(self.initial_fill_samples)/min(self.initial_fill_samples)<=1.15:
            self.initial_fill=False
            self.initial_fill_latch_rate=self.rate

    def close(self):
        if self.shutdown_complete:
            if self.shutdown_error is not None:raise self.shutdown_error
            return
        self.closed=True;self.allow_next=False;self.stop_event.set()
        # The engine's cooperative checkpoint observes stop_event. A completed
        # result remains owned by the writer even when the next job is cancelled.
        self.solvers.shutdown(wait=True,cancel_futures=True)
        if self.gpu_solvers is not None:self.gpu_solvers.shutdown(wait=True,cancel_futures=True)
        self.writer.shutdown(wait=True,cancel_futures=False)
        failure=None
        with self.writes_lock:
            for durable in self.writes:
                try:durable.result()
                except BaseException as error:
                    if failure is None:failure=error
            self.writes.clear()
        for batch in self.running.values():self._release(batch)
        self.running.clear()
        self.gpu_running.clear()
        self.controller.shutdown(wait=True,cancel_futures=True)
        self.status_reader.shutdown(wait=True,cancel_futures=True)
        self.fetcher.shutdown(wait=True,cancel_futures=True)
        self.sender.shutdown(wait=True,cancel_futures=True)
        self.shutdown_error=failure;self.shutdown_complete=True
        if failure is not None:raise failure
