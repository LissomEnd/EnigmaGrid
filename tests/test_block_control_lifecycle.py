"""Coordinator changes quiesce the old pipeline before another job can start."""
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'worker'),str(root/'solver/runtime/src')]
import worker


class Pipeline:
    def __init__(self,response):
        self.response=response;self.stop_event=threading.Event();self.joined=False
        self.retired=False;self.released=False;self.results=[{'receipt':'preserved'}]
        self.queue=self;self.transport=self
        self.thread=threading.Thread(target=self.stop_event.wait);self.thread.start()
    def poll_control(self,refresh):return self.response
    def close(self):
        self.stop_event.set();self.thread.join(timeout=2)
        assert not self.thread.is_alive();self.joined=True
    def retire(self):assert self.joined;self.retired=True
    def pending(self):return self.results
    def upload(self):return False  # Network unavailable: preserve the result.
    def release_ready(self):assert self.joined;self.released=True
    def poll_status(self):raise AssertionError('Control change did not quiesce old pipeline')


with tempfile.TemporaryDirectory() as folder:
    state_path=Path(folder)/'state.json'
    for response in ({'enabled':False}, {'enabled':True,'settings':{'cpu_percent':0,'gpu_percent':0}},
                     {'enabled':True,'settings':{'cpu_percent':25,'gpu_percent':100}}):
        worker.write_control(state_path,{})
        settings=dict(allow_cpu=True,cpu_percent=100,allow_gpu=True,gpu_percent=100)
        pipeline=Pipeline(response)
        runtime=dict(settings=settings,enabled=True,_block_pipeline=pipeline,
                     _block_settings=(True,100,True,100),_block_stop_event=pipeline.stop_event)
        try:
            with patch.object(worker,'post',side_effect=AssertionError('Unexpected HTTP')):
                assert worker.long_block_tick(state_path,{},runtime)
            assert pipeline.joined and pipeline.retired and pipeline.released
            assert pipeline.results==[{'receipt':'preserved'}]
            assert '_block_pipeline' not in runtime and '_block_stop_event' not in runtime
            assert worker.read_control(state_path)['stop_requested']==(response['enabled'] is False)
            assert runtime['running_jobs']==0
        finally:pipeline.close()
print('PASS disable/zero/change quota joins compute, preserves unsent receipt and retires unused work')
