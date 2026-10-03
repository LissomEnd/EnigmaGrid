"""Deterministic CPU/OpenCL event search with bounded, interruptible GPU batches.

Search decisions use integer quadgram costs, never device-dependent floats.
PCG64 generation and the fixed 256-trajectory block size are part of engine v1.
CPU and GPU score the same keys; final candidates use the reference decryptor.
"""
import time
from pathlib import Path

import numpy as np
from numba import njit, prange
from search.cpu_numba import FW, RV, NOTCH, encode
from search.event_stochastic import SHELLS, QTAB, _candidate, decrypt_score_event

BLOCK = 256
QTAB_INT = np.rint(-QTAB.astype(np.float64)*1000).astype(np.int32)


@njit(cache=True, parallel=True)
def _score_cpu(inp, keys, shells, qfloat, qint):
    result = np.empty(len(keys), dtype=np.int32)
    for t in prange(len(keys)):
        k = keys[t]
        _, _, _, out = decrypt_score_event(inp, shells[k[0]], k[1:5], k[5:9],
                                          k[9:35], qfloat, k[39], k[40], k[41], k[35:39])
        at = k[40]
        full = 0
        left = 0
        right = 0
        for i in range(69):
            z = ((int(out[i])*26+int(out[i+1]))*26+int(out[i+2]))*26+int(out[i+3])
            q = qint[z]
            full += q
            if i+3 < at:
                left += q
            if i >= at:
                right += q
        l = left//(at-3) if at > 3 else 20000
        r = right//(69-at) if at < 69 else 20000
        result[t] = 72*(full//69)+28*max(l, r)
    return result


def score_cpu(inp, keys):
    return _score_cpu(inp, keys, SHELLS, QTAB, QTAB_INT)


def opencl_devices():
    try:
        import pyopencl as cl
        found = []
        for platform in cl.get_platforms():
            for device in platform.get_devices(device_type=cl.device_type.GPU):
                if device.available and device.compiler_available and device.global_mem_size >= 64*1024*1024:
                    found.append(device)
        return found
    except Exception:
        return []


class OpenCLScorer:
    def __init__(self, inp, device=None):
        import pyopencl as cl
        devices = opencl_devices() if device is None else [device]
        if not devices:
            raise RuntimeError('No compatible OpenCL GPU and driver found')
        self.cl = cl
        self.device = devices[0]
        self.context = cl.Context([self.device])
        self.queue = cl.CommandQueue(self.context)
        source = Path(__file__).with_name('portable_score.cl').read_text(encoding='utf-8')
        self.program = cl.Program(self.context, source).build(options=['-cl-std=CL1.2'])
        self.kernel = cl.Kernel(self.program, 'score_keys')
        mf = cl.mem_flags
        arrays = (np.asarray(inp, np.uint8), np.asarray(SHELLS, np.int16),
                  np.asarray(FW, np.uint8), np.asarray(RV, np.uint8),
                  np.asarray(NOTCH, np.uint8), QTAB_INT)
        self.constants = [cl.Buffer(self.context, mf.READ_ONLY | mf.COPY_HOST_PTR,
                                    hostbuf=np.ascontiguousarray(a)) for a in arrays]
        self.key_buffer = cl.Buffer(self.context, mf.READ_ONLY, BLOCK*42*4)
        self.score_buffer = cl.Buffer(self.context, mf.WRITE_ONLY, BLOCK*4)

    def __call__(self, keys):
        if not 0 < len(keys) <= BLOCK:
            raise ValueError('GPU batch outside bounded size')
        scores = np.empty(len(keys), dtype=np.int32)
        self.cl.enqueue_copy(self.queue, self.key_buffer, np.ascontiguousarray(keys, np.int32))
        self.kernel(self.queue, (len(keys),), None, *self.constants, self.key_buffer, self.score_buffer)
        self.cl.enqueue_copy(self.queue, scores, self.score_buffer).wait()
        return scores


def initial_keys(rng, count, min_pairs, max_pairs, kinds):
    keys = np.zeros((count, 42), dtype=np.int32)
    keys[:, 0] = rng.integers(0, len(SHELLS), count)
    keys[:, 2:9] = rng.integers(0, 26, (count, 7))
    keys[:, 35:39] = rng.integers(0, 26, (count, 4))
    keys[:, 39] = rng.choice(kinds, count)
    keys[:, 40] = rng.integers(1, 18, count)*4
    keys[:, 41] = rng.integers(1, 5, count)
    for row in keys:
        row[9:35] = np.arange(26)
        letters = rng.permutation(26)
        n = int(rng.integers(min_pairs, max_pairs+1))
        for j in range(n):
            a, b = letters[2*j:2*j+2]
            row[9+a], row[9+b] = b, a
    return keys


@njit(cache=True)
def _mutate(keys, min_pairs, max_pairs, kinds, ops, a, b, values):
    nxt = keys.copy()
    n = len(keys)
    for i in range(n):
        k = nxt[i]
        op = ops[i]
        v = values[i]
        if op < 58:
            pl = k[9:35]
            x, y = int(a[i]), int(b[i])
            if x == y:
                y = (y+1) % 26
            px, py = int(pl[x]), int(pl[y])
            pl[x] = x; pl[px] = px; pl[y] = y; pl[py] = py
            if v % 3 != 0:
                pl[x] = y; pl[y] = x
            pairs = int(np.count_nonzero(pl != np.arange(26)))//2
            if pairs < min_pairs or pairs > max_pairs:
                k[9:35] = keys[i, 9:35]
        elif op < 70:
            k[5+v % 4] = a[i]
        elif op < 78:
            k[2+v % 3] = a[i]
        elif op < 82:
            k[0] = v % len(SHELLS)
        elif op < 88:
            k[39] = kinds[v % len(kinds)]
        elif op < 94:
            k[40] = (1+v % 17)*4
        elif op < 97:
            k[41] = 1+v % 4
        else:
            k[35+v % 4] = a[i]
    return nxt


def mutate(rng, keys, min_pairs, max_pairs, kinds):
    n = len(keys)
    return _mutate(keys, min_pairs, max_pairs, kinds, rng.integers(0,100,n),
                   rng.integers(0,26,n), rng.integers(0,26,n), rng.integers(0,2**30,n))


def search(text, start_seed, count=4096, iterations=512, topk=8,
           min_pairs=0, max_pairs=13, event_kinds=(1,2,3,4,5,6),
           backend='cpu', percent=100, checkpoint=None, scorer=None):
    if len(text) != 72 or not 1 <= count <= 32768 or not 1 <= iterations <= 2000:
        raise ValueError('Unsupported portable search workload')
    if not 0 <= min_pairs <= max_pairs <= 13 or not 1 <= topk <= 32:
        raise ValueError('Invalid search bounds')
    kinds = np.asarray(event_kinds, np.int32)
    if not len(kinds) or not np.all((kinds >= 1) & (kinds <= 6)):
        raise ValueError('Invalid event model')
    inp = encode(text)
    if scorer is None:
        scorer = OpenCLScorer(inp) if backend == 'opencl' else lambda keys: score_cpu(inp, keys)
    winners = []
    for offset in range(0, count, BLOCK):
        size = min(BLOCK, count-offset)
        rng = np.random.Generator(np.random.PCG64(int(start_seed)+offset))
        keys = initial_keys(rng, size, min_pairs, max_pairs, kinds)
        costs = scorer(keys)
        best_keys, best_costs = keys.copy(), costs.copy()
        for iteration in range(iterations):
            if checkpoint:
                checkpoint(offset, iteration)
            started = time.perf_counter()
            nxt = mutate(rng, keys, min_pairs, max_pairs, kinds)
            proposed = scorer(nxt)
            # Integer threshold cooling: reproducible across CPU and GPU vendors.
            temperature = max(2500, 38000*(iterations-iteration)//iterations)
            allowance = rng.integers(0, temperature+1, size)
            accept = proposed <= costs+allowance
            keys[accept], costs[accept] = nxt[accept], proposed[accept]
            better = costs < best_costs
            best_keys[better], best_costs[better] = keys[better], costs[better]
            if backend == 'opencl' and percent < 100:
                elapsed = time.perf_counter()-started
                # Slow GPUs may need more than one second of rest to honor a
                # small duty budget. Poll controls without truncating that rest.
                deadline = time.perf_counter()+elapsed*(100-max(1, percent))/max(1, percent)
                while True:
                    if checkpoint:
                        checkpoint(offset, iteration)
                    remaining = deadline-time.perf_counter()
                    if remaining <= 0:
                        break
                    time.sleep(min(.1, remaining))
        ids = np.lexsort((np.arange(size), best_costs))[:topk]
        winners.extend((int(best_costs[i]), start_seed+offset+int(i), best_keys[i].copy()) for i in ids)
    winners.sort(key=lambda row: (row[0], row[1]))
    result = []
    for cost, attempt, k in winners[:topk]:
        obj,q,bal,_ = decrypt_score_event(inp,SHELLS[k[0]],k[1:5],k[5:9],k[9:35],QTAB,k[39],k[40],k[41],k[35:39])
        c = _candidate(inp,obj,q,bal,k[0],k[1:5],k[5:9],k[9:35],k[39],k[40],k[41],k[35:39],
                       ('portable_integer_v1',),attempt)
        c['metrics']['search_cost'] = cost
        result.append(c)
    return result


def qualify_device(device, text):
    inp = encode(text)
    scorer = OpenCLScorer(inp, device)
    keys = initial_keys(np.random.Generator(np.random.PCG64(73021)), 96, 0, 13, np.arange(1,7))
    # All event types, boundaries, and rewind distances must agree bit for bit.
    keys[:,39] = np.arange(96) % 6+1
    keys[:,40] = np.arange(96) % 72
    keys[:,41] = np.arange(96) % 4+1
    if not np.array_equal(scorer(keys), score_cpu(inp, keys)):
        raise RuntimeError('GPU failed independent CPU scoring check')
    return scorer
