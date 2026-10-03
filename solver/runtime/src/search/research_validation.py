"""Offline recomputation of experimental receipts, without issuing credit.

Agreement detects modified outputs; it is not independent algorithm validation
and does not establish a historical solution or production readiness.
"""
import json
from search.crib_pilot import execute,validate_job


def canonical(receipt):
    if not isinstance(receipt,dict):raise ValueError('Receipt must be an object')
    try:
        encoded=json.dumps(receipt,sort_keys=True,separators=(',',':'),allow_nan=False)
    except (ValueError,TypeError,RecursionError) as exc:
        raise ValueError('Receipt is not bounded JSON') from exc
    if len(encoded)>2*1024*1024:raise ValueError('Receipt too large')
    return encoded


def verify(job,receipt,*,checkpoint=None):
    validate_job(job)
    supplied=canonical(receipt)
    expected=execute(job,checkpoint=checkpoint)
    if supplied!=canonical(expected):raise ValueError('Research receipt does not match recomputation')
    return dict(computation_matches=True,complete=expected['complete'],
        scope_hash=expected['scope_hash'],status=expected['status'],
        candidates=len(expected['candidates']),credit_issued=False,
        historical_solution=False,independent_algorithm_validation=False)
