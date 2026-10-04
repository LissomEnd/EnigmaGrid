"""Opt-in hardware parity check; never leases production work."""
import json
import sys
from pathlib import Path

import numpy as np
import numba

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'worker'), str(ROOT / 'solver/runtime/src')]
from scoring_pool import OrderedScorers
from search.portable_search import opencl_devices, qualify_device, search

numba.set_num_threads(1)
text = json.loads((ROOT / 'solver/runtime/data/messages/p1030680.json').read_text())['ciphertext']
devices = opencl_devices()
if not devices:
    raise SystemExit('No OpenCL devices: hardware qualification not performed')
scorers = [qualify_device(device, text) for device in devices]
pool = OrderedScorers(scorers)
try:
    for count in (1, 17, 257):
        args = dict(count=count, iterations=2, topk=8)
        reference = search(text, 73021, **args)
        result = search(text, 73021, backend='opencl',
                        scorer=lambda keys: np.concatenate(pool.score(keys)), **args)
        if reference != result:
            raise AssertionError(f'CPU/GPU receipt mismatch for {count} keys')
finally:
    pool.close()
# Exercise the real worker integration, including the hybrid CPU/GPU split.
import worker
worker._GPU_SCORERS = scorers
for count in (1, 17, 257):
    lease = {'config': {'count_per_unit': count, 'iterations': 2, 'topk': 8},
             'start_unit': 0, 'end_unit': 1}
    cpu = worker.run_portable(lease, {'settings': {'cpu_percent': 1, 'gpu_percent': 0}})
    for cpu_percent in (0, 1):
        actual = worker.run_portable(lease, {'settings': {'cpu_percent': cpu_percent, 'gpu_percent': 100}})
        if actual != cpu:
            raise AssertionError(f'Worker receipt mismatch: count={count}, cpu={cpu_percent}')
print(json.dumps({'qualified_devices': [d.name for d in devices],
                  'receipt_parity_counts': [1, 17, 257],
                  'worker_modes': ['CPU', 'GPU', 'CPU + GPU'],
                  'multiple_physical_devices_tested': len(devices) > 1}))
