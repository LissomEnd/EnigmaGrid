"""Real crib execution through client budgets, pause and stop controls."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'worker'),str(ROOT/'scripts'),str(ROOT/'solver/runtime/src')]
from research_executor import run,ResearchStopped
from prepare_research_campaign import prepare
from search.research_program import job_at
from search.crib_pilot import execute

job=job_at(prepare(),0,chunk=4)
expected=execute(job)
for percent in (0,False,101):
    try:run(job,settings={'cpu_percent':percent},control=lambda:{})
    except ValueError:pass
    else:raise AssertionError('Invalid CPU budget accepted')
try:run(job,settings={'cpu_percent':50},control=lambda:{'stop_requested':True})
except ResearchStopped:pass
else:raise AssertionError('Stopped work returned a receipt')
state={'paused':True};seen=[];waits=[];now=[0.0]
def sleep(delay):
    waits.append(delay);now[0]+=delay
    assert not seen,'Work progressed while initially paused'
    state['paused']=False
receipt=run(job,settings={'cpu_percent':100},control=lambda:state,
    progress=lambda done,total:seen.append(done),clock=lambda:now[0],sleep=sleep)
assert receipt==expected and waits and seen==[0,1,2,3,4]
# Simulated elapsed compute time exercises throttling without a timing-sensitive
# CPU-utilization assertion; the search and receipt remain real.
now=[0.0];waits=[]
def clock():now[0]+=.001;return now[0]
def throttle(delay):waits.append(delay);now[0]+=delay
assert run(job,settings={'cpu_percent':25},control=lambda:{},clock=clock,sleep=throttle)==expected
assert waits and max(waits)<=.05
state={};now=[0.0]
def stop_during_throttle(delay):
    now[0]+=delay;state['stop_requested']=True
try:run(job,settings={'cpu_percent':25},control=lambda:state,clock=clock,sleep=stop_during_throttle)
except ResearchStopped:pass
else:raise AssertionError('Stop during cooldown returned a receipt')
print('RESEARCH_CLIENT_PAUSE_STOP_BUDGET_AND_RECEIPT_OK')
