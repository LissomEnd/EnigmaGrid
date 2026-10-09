"""Local aggregate-throughput proof for one independent bounded GPU job lane.

Trial receipts never enter a production queue.  The caller owns the shared CPU
pool, the single GPU owner, thermal checks, and the qualification deadline.
"""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import math
import statistics
import threading
import time

FORMAT = 'bounded-gpu-lanes-v1'
JOBS = 12
TRIALS = 3


def select_profile(rows, cpu_lanes):
    if type(cpu_lanes) is not int or cpu_lanes not in (1, 2, 4):
        raise ValueError('Invalid CPU baseline')
    if not isinstance(rows, list) or len(rows) != TRIALS:
        raise ValueError('Incomplete GPU lane comparison')
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or row.get('trial') != index or row.get('receipt_equal') is not True:
            raise ValueError('Invalid GPU lane receipt comparison')
        for field in ('cpu_seconds', 'mixed_seconds'):
            value = row.get(field)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError('Invalid GPU lane timing')
        if type(row.get('gpu_jobs')) is not int or not 1 <= row['gpu_jobs'] <= JOBS:
            raise ValueError('GPU lane did not receive timed work')
    # A GPU lane must win repeatedly, not merely improve one lucky sample.
    return (all(row['mixed_seconds'] <= row['cpu_seconds'] * .95 for row in rows)
            and statistics.median(row['mixed_seconds'] for row in rows)
                < statistics.median(row['cpu_seconds'] for row in rows) * .95)


def _run_profile(envelopes, expected, cpu_execute, gpu_execute, cpu_lanes,
                 checkpoint, clock, cancel_running):
    next_index = 0
    claimed = threading.Lock()
    matched = [0]
    gpu_jobs = [0]

    def lane(execute, is_gpu=False):
        nonlocal next_index
        while True:
            checkpoint()
            with claimed:
                if next_index >= len(envelopes):
                    return
                index = next_index
                next_index += 1
            actual = execute(envelopes[index])
            if actual != expected[index]:
                raise ValueError('GPU lane full receipt parity failed')
            with claimed:
                matched[0] += 1
                if is_gpu:gpu_jobs[0] += 1

    began = clock()
    with ThreadPoolExecutor(max_workers=cpu_lanes + (gpu_execute is not None),
                            thread_name_prefix='gpu-lane-check') as executor:
        futures = []
        if gpu_execute is not None:
            futures.append(executor.submit(lane, gpu_execute, True))
        futures.extend(executor.submit(lane, cpu_execute) for _ in range(cpu_lanes))
        pending = set(futures)
        try:
            while pending:
                checkpoint()
                done, pending = wait(pending, timeout=.02, return_when=FIRST_COMPLETED)
                for task in done:
                    task.result()
        except BaseException:
            cancel_running()
            for task in pending:task.cancel()
            raise
    if matched[0] != len(envelopes):
        raise ValueError('Incomplete GPU lane comparison')
    return max(.000001, clock() - began),gpu_jobs[0]


def qualify(envelopes, reference, cpu_execute, gpu_execute, cpu_lanes,
            checkpoint=lambda: None, clock=time.monotonic,cancel_running=lambda:None):
    if len(envelopes) != JOBS:
        raise ValueError('Expected twelve bounded GPU lane jobs')
    if type(cpu_lanes) is not int or cpu_lanes not in (1, 2, 4):
        raise ValueError('Invalid CPU baseline')
    expected = []
    for envelope in envelopes:
        checkpoint()
        expected.append(reference(envelope))
    # Warm and validate both paths before collecting timings.
    for execute in (cpu_execute, gpu_execute):
        checkpoint()
        if execute(envelopes[0]) != expected[0]:
            raise ValueError('GPU lane warm receipt parity failed')
    mixed_cpu_lanes = min(cpu_lanes, 3)
    rows = []
    for trial in range(TRIALS):
        checkpoint()
        paths = (('cpu_seconds', cpu_lanes, None),
                 ('mixed_seconds', mixed_cpu_lanes, gpu_execute))
        if trial % 2:
            paths = tuple(reversed(paths))
        row = {'trial': trial, 'receipt_equal': True}
        for name, count, gpu in paths:
            elapsed,gpu_jobs = _run_profile(envelopes, expected, cpu_execute, gpu,
                                             count, checkpoint, clock, cancel_running)
            row[name] = elapsed
            if gpu is not None:row['gpu_jobs']=gpu_jobs
        rows.append(row)
    return {'format': FORMAT, 'jobs_per_trial': JOBS, 'cpu_lanes': cpu_lanes,
            'mixed_cpu_lanes': mixed_cpu_lanes, 'trials': rows,
            'qualified': select_profile(rows, cpu_lanes),
            'verification': 'local full receipt equality; no grid credit'}
