import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
import worker
runtime={}
with patch.object(worker.time,'monotonic',return_value=100):
    worker.record_throughput(runtime,2,.05)
    worker.record_throughput(runtime,3,.1)
    assert worker.throughput_snapshot(runtime)['units_per_second']==1
    assert worker.throughput_snapshot(runtime)['jobs_per_second']==.4
with patch.object(worker.time,'monotonic',return_value=106):
    sample=worker.throughput_snapshot(runtime)
    assert sample['units_per_second']==sample['jobs_per_second']==0
    assert sample['completed_units']==5 and sample['completed_jobs']==2
    assert abs(sample['compute_seconds']-.15)<1e-9
print('PASS wall-time throughput includes idle and preserves session totals')
