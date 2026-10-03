"""Offline client adapter. Not advertised or routed by the production worker.

Uses one CPU thread with a duty budget, checked between bounded cores. No GPU
support is claimed. Cancellation raises instead of certifying partial work.
"""
import time
from search.crib_pilot import execute, validate_job


class ResearchStopped(Exception):
    pass


def run(job, *, settings, control, progress=lambda done, total: None,
        checkpoint=None, clock=time.monotonic, sleep=time.sleep):
    validate_job(job)
    percent=settings.get('cpu_percent',0)
    if type(percent) is not int or not 1<=percent<=100 or not settings.get('allow_cpu',True):
        raise ValueError('Experimental CPU work requires an enabled CPU budget')
    last=clock()

    def check(done,total):
        nonlocal last
        now=clock()
        # Throttle the one computational thread, conservatively interpreting
        # the configured percentage as a fraction of one core.
        remaining=max(0,now-last)*(100-percent)/percent if done else 0
        while True:
            if checkpoint is not None:checkpoint(done,total)
            state=control()
            if state.get('stop_requested'):raise ResearchStopped('Research work stopped without a receipt')
            if state.get('paused'):
                sleep(.05)
                continue
            if remaining<=0:break
            wait=min(.05,remaining);before=clock();sleep(wait)
            remaining-=max(0,clock()-before)
        progress(done,total)
        last=clock()

    return execute(job,checkpoint=check)
