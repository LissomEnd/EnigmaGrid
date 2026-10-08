"""Bounded local receipt-parity/throughput comparison; never grants grid credit."""
from concurrent.futures import ThreadPoolExecutor
import math
import statistics
import time

ORDERS=((1,2,4),(2,4,1),(4,1,2))


def select_lanes(trials):
    if len(trials)!=9:raise ValueError('Incomplete concurrency comparison')
    by_lane={1:[],2:[],4:[]}
    for index,trial in enumerate(trials):
        seconds=trial.get('seconds')
        if (trial.get('lanes')!=ORDERS[index//3][index%3] or
            trial.get('receipt_equal') is not True or
            type(seconds) not in (int,float) or not math.isfinite(seconds) or seconds<=0):
            raise ValueError('Invalid concurrency comparison')
        by_lane[trial['lanes']].append(seconds)
    # Require a repeatable gain; a lucky fast round must not qualify a slowdown.
    eligible=[1]+[lanes for lanes in (2,4)
        if all(b<=a*1.05 for a,b in zip(by_lane[1],by_lane[lanes]))
        and statistics.median(by_lane[lanes])<statistics.median(by_lane[1])*.95]
    return min(eligible,key=lambda lanes:(statistics.median(by_lane[lanes]),lanes))


def qualify(envelopes,reference,execute,checkpoint=lambda:None,clock=time.monotonic,
            cancel_running=lambda:None):
    if len(envelopes)!=12:raise ValueError('Expected twelve bounded qualification jobs')
    expected=[]
    for envelope in envelopes:
        checkpoint();expected.append(reference(envelope))
    # Warm the same executor/backend that every measured lane count will share.
    for envelope,result in zip(envelopes,expected):
        checkpoint()
        if execute(envelope)!=result:raise ValueError('Warm receipt parity failed')
    trials=[]
    with ThreadPoolExecutor(4,thread_name_prefix='concurrency-check') as callers:
        for order in ORDERS:
            for lanes in order:
                checkpoint();began=clock();pending={};next_index=0;matched=0
                try:
                    while pending or next_index<len(envelopes):
                        checkpoint()
                        while len(pending)<lanes and next_index<len(envelopes):
                            pending[callers.submit(execute,envelopes[next_index])]=next_index
                            next_index+=1
                        completed=[future for future in pending if future.done()]
                        if not completed:
                            time.sleep(.002);continue
                        for future in completed:
                            index=pending.pop(future)
                            if future.result()!=expected[index]:raise ValueError('Concurrent receipt parity failed')
                            matched+=1
                    trials.append(dict(lanes=lanes,seconds=max(.000001,clock()-began),
                                       receipt_equal=matched==len(envelopes)))
                finally:
                    if pending:cancel_running()
                    for future in pending:future.cancel()
    return dict(format='local-concurrency-v1',lanes=select_lanes(trials),trials=trials,
                jobs_per_trial=12,parity_checks=12*10,verification='local CPU receipt comparison; no grid credit')
