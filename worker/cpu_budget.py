"""Measured quota shared by the parent and all computation children."""
from collections import deque
import math
import threading

class CpuBudget:
    def __init__(self):
        self.at=None;self.sample_at=None;self.percent=None;self.credit=0.0
        self.history=deque()
        self.lock=threading.Lock()

    def delay(self,now,percent,sample_at,observed):
        with self.lock:
            return self._delay(now,percent,sample_at,observed)

    def _delay(self,now,percent,sample_at,observed):
        if not 1<=percent<=100:raise ValueError('CPU quota must be 1..100')
        if self.at is None:self.at=now;self.sample_at=sample_at;self.percent=percent
        # Concurrent callers can acquire the gate in a different order than
        # their clock samples. Never mint credit by moving its clock backwards.
        now=max(now,self.at)
        self.credit+=max(0,now-self.at)*percent/100;self.at=now
        if percent!=self.percent:
            self.credit=0;self.percent=percent;self.sample_at=sample_at
        if sample_at is not None and (self.sample_at is None or sample_at>self.sample_at):
            if isinstance(observed,(int,float)) and math.isfinite(observed) and self.sample_at is not None:
                elapsed=sample_at-self.sample_at
                self.credit=min(.05,self.credit-max(0,min(100,observed))/100*elapsed)
                self.history.append((sample_at,elapsed,observed))
                while self.history and sample_at-self.history[0][0]>10:self.history.popleft()
            self.sample_at=sample_at
        if percent==100:self.credit=0;return 0.0
        return min(.1,max(0,-self.credit/(percent/100)))

    def measured_percent(self):
        with self.lock:
            elapsed=sum(x[1] for x in self.history)
            return sum(x[1]*x[2] for x in self.history)/elapsed if elapsed else None
