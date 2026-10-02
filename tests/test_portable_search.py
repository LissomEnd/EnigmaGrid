"""Real OpenCL parity when a GPU exists; mandatory CPU determinism everywhere."""
import json
import sys
from pathlib import Path

import numpy as np
from numba import set_num_threads

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'solver/runtime/src'))
from search.portable_search import search, opencl_devices, qualify_device, initial_keys, mutate


def main():
    text = json.loads((ROOT/'solver/runtime/data/messages/p1030680.json').read_text())['ciphertext']
    set_num_threads(2)
    for bounds, kinds in [((0,3),(1,2,3,4,5)), ((4,10),(6,)), ((11,13),(1,2,3,4,5,6))]:
        args = dict(count=32, iterations=12, topk=4, min_pairs=bounds[0], max_pairs=bounds[1], event_kinds=kinds)
        cpu = search(text, 71000000001, **args)
        assert cpu == search(text, 71000000001, **args)
        for c in cpu:
            assert bounds[0] <= len(c['key']['plugboard']) <= bounds[1]
        for device in opencl_devices():
            scorer = qualify_device(device,text)
            gpu = search(text,71000000001,backend='opencl',scorer=scorer,**args)
            assert gpu == cpu, device.name
            print('PORTABLE_GPU_PARITY_OK', device.vendor, device.name, bounds, kinds, flush=True)
    rng = np.random.Generator(np.random.PCG64(77))
    keys = initial_keys(rng,32,4,10,np.arange(1,7))
    for _ in range(100):
        keys = mutate(rng,keys,4,10,np.arange(1,7))
        for k in keys:
            p = k[9:35]
            assert np.array_equal(p[p], np.arange(26))
            assert 4 <= np.count_nonzero(p != np.arange(26))//2 <= 10
    print('PORTABLE_SEARCH_CPU_OK', flush=True)
    if not opencl_devices():
        print('GPU_NOT_AVAILABLE: real GPU validation must run on release hardware', flush=True)


if __name__ == '__main__':
    main()
