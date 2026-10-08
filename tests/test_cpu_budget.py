import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
from cpu_budget import CpuBudget

for capacity in (12.5,25,50,100):
    for quota in (25,50,75,100):
        budget=CpuBudget();now=0;cpu=0;previous_cpu=0;sample=0;observed=0;warm=0
        for step in range(4000):
            now=step*.01
            if step%100==0:
                observed=(cpu-previous_cpu)*100;previous_cpu=cpu;sample=now
            delay=budget.delay(now,quota,sample,observed)
            if quota==100:assert delay==0
            if not delay:cpu+=.01*capacity/100
            if step==999:warm=cpu
        actual=(cpu-warm)/30*100
        assert abs(actual-min(capacity,quota))<=5,(capacity,quota,actual)
        assert budget.delay(now+.01,100,sample,observed)==0
        assert budget.measured_percent() is not None
print('PASS measured aggregate Windows quota across capacity/concurrency, stable30s tolerance and immediate100%')

from concurrent.futures import ThreadPoolExecutor
budget=CpuBudget()
budget.delay(0,50,0,0)
with ThreadPoolExecutor(4) as callers:
    list(callers.map(lambda _:budget.delay(1,50,1,100),range(100)))
assert len(budget.history)==1,'Same process-tree sample charged more than once'
assert budget.measured_percent()==100
credit=budget.credit
budget.delay(.5,50,1,100)
assert budget.at==1 and budget.credit==credit,'Out-of-order clock created credit'
assert budget.delay(1,100,1,100)==0
print('PASS concurrent quota callers, sample deduplication and monotonic credit')
