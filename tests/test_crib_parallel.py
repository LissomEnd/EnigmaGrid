"""Spawn-process computation preserves complete canonical receipts and caps."""
import sys
import multiprocessing
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'solver/runtime/src'))
from search.bounded_crib import search
from search.crib_pilot import core_at
from search.process_map import OrderedProcessMap

def slow_identity(value):
    import time
    time.sleep(.1)
    return value

def task_timeout(value):
    raise TimeoutError('task failure')

def marked_work(item):
    import time
    directory,index=item
    marker=Path(directory)/str(index)
    marker.write_text('started')
    if index==0:
        deadline=time.monotonic()+5
        while not (Path(directory)/'8').exists():
            if time.monotonic()>deadline:raise RuntimeError('Second process did not start')
            time.sleep(.005)
    if index>=8:time.sleep(.15)
    return index

def main():
    class RacingFuture:
        def __init__(self):self.first=True
        def result(self,timeout=None):
            if self.first:self.first=False;raise TimeoutError('poll expired')
            return [42]
        def done(self):return True
        def cancel(self):return False
    class FakeExecutor:
        def __init__(self,**kwargs):pass
        def submit(self,*args):return RacingFuture()
        def shutdown(self,**kwargs):pass
    with patch('search.process_map.ProcessPoolExecutor',FakeExecutor):
        with OrderedProcessMap(1) as mapper:
            assert list(mapper(abs,[-42]))==[42],'Completion at deadline lost'
    import search.process_map as process_map
    from types import SimpleNamespace
    class Clock:
        now=0.0
        def monotonic(self):return self.now
        def sleep(self,duration):self.now+=duration
    clock=Clock()
    with patch.object(process_map,'time',clock),patch.object(process_map,'_generation',SimpleNamespace(value=1)),patch.object(process_map,'_percent',SimpleNamespace(value=25)):
        process_map._gate(1,0,.1)
        assert .3<=clock.now<.33,'CPU duty not applied'
        process_map._percent.value=100
        previous=clock.now;process_map._gate(1,clock.now,.1)
        assert clock.now==previous,'100 percent adds rest'
    import time
    with OrderedProcessMap(1) as paused_pool:
        # Warm the process before observing a paused dispatch.
        assert list(paused_pool(abs,[-1]))==[1]
        paused_pool.set_percent(0);started=time.monotonic();checks=[0]
        def resume():
            checks[0]+=1
            if time.monotonic()-started>=.2:paused_pool.set_percent(100)
        paused_pool.check=resume
        assert list(paused_pool(abs,[-2]))==[2]
        assert time.monotonic()-started>=.2 and checks[0]>=3,'Pause did not hold work'
    cores=[core_at(i*7919) for i in range(16)]
    count=0
    with OrderedProcessMap(2,chunk_size=4) as pool:
        for crib in ['W','WETT','Q']:
            for limit in [1,16]:
                for nodes in [1,100]:
                    args=('QWERTZUIOPASDFGHJKLYXCVBNM',crib,0,cores)
                    kwargs=dict(pairs=2,node_limit=nodes,board_limit=8,completion_limit=8,candidate_limit=limit)
                    expected=search(*args,**kwargs)
                    actual=search(*args,**kwargs,solve_map=pool)
                    assert actual==expected,(crib,limit,nodes)
                    count+=1
    consumed=[];checks=[0]
    def source():
        for i in range(1000):consumed.append(i);yield i
    def stop():
        checks[0]+=1
        if checks[0]>4:raise InterruptedError('requested')
    with OrderedProcessMap(2,chunk_size=2,check=stop) as pool:
        try:list(pool(slow_identity,source()))
        except InterruptedError:pass
        else:raise AssertionError('Stop ignored')
    assert len(consumed)<=4,consumed
    with OrderedProcessMap(1) as pool:
        try:list(pool(task_timeout,[1]))
        except TimeoutError as error:assert str(error)=='task failure'
        else:raise AssertionError('Task exception swallowed')
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        with OrderedProcessMap(2,chunk_size=8) as pool:
            iterator=pool(marked_work,[(directory,i) for i in range(16)])
            assert next(iterator)==0
            iterator.close()
            assert list(pool(abs,[-3,-4]))==[3,4],'Pool not reusable after cancellation'
        assert not (Path(directory)/'15').exists(),'Obsolete batch ran all remaining cores'
    assert not multiprocessing.active_children(),'Process leaked'
    print('PASS',count,'serial/spawn-process receipts, candidate caps, conflict and cleanup')
if __name__=='__main__':main()
