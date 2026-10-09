"""A slow local qualification cannot hold up durable grid-compute ticks."""
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'worker'),str(ROOT/'solver/runtime/src')]
import worker


class Queue:
    def __init__(self):self.retired=False
    def qualification_sample(self):return [dict(config={'program':{'scope':'fixture'}}) for _ in range(12)]
    def monitor_snapshot(self):return {'ready_units':12,'outbox_count':0}
    def retire(self):self.retired=True
    def pending(self):return []


class Pipeline:
    def __init__(self):
        self.queue=Queue();self.running={};self.lanes=1;self.ticks=0;self.closed=False
    @property
    def computing(self):return False
    def poll_control(self,refresh):return None
    def poll_status(self):pass
    def tick(self,*,allow_compute):
        assert allow_compute
        self.ticks+=1
        return True
    def close(self):self.closed=True


with tempfile.TemporaryDirectory(prefix='enigma-async-qual-') as folder:
    state=Path(folder)/'state.json';worker.write_control(state,{})
    pipeline=Pipeline();started=threading.Event();release=threading.Event()
    settings=dict(cpu_percent=100,allow_cpu=True,gpu_percent=100,allow_gpu=True)
    runtime=dict(settings=settings,enabled=True,_block_pipeline=pipeline,
                 _block_settings=tuple(settings[k] for k in ('allow_cpu','cpu_percent','allow_gpu','gpu_percent')),
                 _shared_constrained_pool=SimpleNamespace(workers=2),_block_stop_event=threading.Event())

    def slow_check(_path,_state,candidate,_pipeline,*,cancel_event,**kwargs):
        started.set()
        assert release.wait(5) or cancel_event.is_set()
        if cancel_event.is_set():return False
        candidate['_qualified_block_lanes']=2
        candidate['_qualified_block_config']={'program':{'scope':'fixture'}}
        candidate['_block_concurrency_considered']=True
        return True

    with patch.object(worker,'maybe_qualify_block_concurrency',side_effect=slow_check),\
         patch.object(worker,'release_shared_constrained'):
        assert worker.long_block_tick(state,{},runtime)
        assert started.wait(2) and pipeline.ticks==1 and not pipeline.closed
        assert worker.long_block_tick(state,{},runtime)
        assert pipeline.ticks==2 and runtime['_block_pipeline'] is pipeline
        release.set();runtime['_block_qualification']['thread'].join(2)
        assert worker.long_block_tick(state,{},runtime)
        assert pipeline.closed and runtime['_qualified_block_lanes']==2
        assert '_block_pipeline' not in runtime and not pipeline.queue.retired

    # Stop joins the qualification owner before the shared pool is released.
    pipeline=Pipeline();started.clear();release.clear()
    runtime.update(_block_pipeline=pipeline,_block_concurrency_considered=False,
                   _block_stop_event=threading.Event())
    with patch.object(worker,'maybe_qualify_block_concurrency',side_effect=slow_check),\
         patch.object(worker,'release_shared_constrained'):
        assert worker.long_block_tick(state,{},runtime)
        assert started.wait(2)
        worker.suspend_long_blocks(runtime)
        assert pipeline.closed and pipeline.queue.retired
        assert '_block_qualification' not in runtime

print('PASS grid compute ticks continue during bounded qualification; promotion waits for unit boundary; stop joins owner')
