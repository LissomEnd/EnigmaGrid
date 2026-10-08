"""Long block subdivision preserves existing unit receipts and bounded intake."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'solver/runtime/src'))
from search.crib_work import run, validate_envelope
from search.work_block import *


def rejects(action):
    try:
        action()
    except (ValueError, TypeError):
        return
    raise AssertionError('Malformed block/result accepted')


block = dict(format=FORMAT, block_id='block-test', engine=CAPABILITY,
             start_unit=4, end_unit=12,
             config=dict(requires=['cpu', CAPABILITY], program=dict(
                 ciphertext='BDZGO', hypotheses=[dict(text='BD', legal_clean_offsets=[0])],
                 chunk=3, ordinal_base=2, candidate_limit=3)))
validate_block(block)
intermediate=copy.deepcopy(block)
intermediate.update(start_unit=0,end_unit=3)
intermediate['config']['program'].update(ordinal_base=0,hypotheses=[
    dict(text='A',legal_clean_offsets=[0]),
    dict(text='BB',legal_clean_offsets=[4]),
    dict(text='C',legal_clean_offsets=[0])])
rejects(lambda: validate_block(intermediate))
rejects(lambda: validate_envelope(block))  # No silent legacy protocol upgrade.
receipts = []
for ordinal in range(4, 12):
    lease = unit_envelope(block, ordinal)
    expected = dict(engine=CAPABILITY, start_unit=ordinal, end_unit=ordinal+1,
                    config=copy.deepcopy(block['config']))
    assert run(lease) == run(expected)
    receipts.append(dict(unit=ordinal, compute_seconds=.1, result=run(lease)))
payload = dict(format=FORMAT, block_id=block['block_id'], receipts=receipts)
validate_partial_results(block, payload)
validate_partial_results(block, dict(payload, receipts=list(reversed(receipts))))
for ordinal in (True, 3, 12, 4.0):
    rejects(lambda: unit_envelope(block, ordinal))
for change in ({'end_unit': MAX_UNITS+5}, {'start_unit': True}, {'engine': 'other'},
               {'block_id': '../other'}, {'format': 'future'}, {'extra': 1}):
    rejects(lambda: validate_block(dict(block, **change)))
rejects(lambda: validate_partial_results(block, dict(payload, block_id='another')))
rejects(lambda: validate_partial_results(block, dict(payload, receipts=receipts + receipts[:1])))
rejects(lambda: validate_partial_results(block, dict(payload, receipts=[receipts[0], receipts[0]])))
# Even a valid receipt for a different unit cannot escape the assigned block.
# Partial intake validates the descriptor once, but still bounds every ordinal.
for ordinal in (3, 12):
    outside = dict(unit=ordinal, compute_seconds=.1, result=run(dict(
        engine=CAPABILITY, start_unit=ordinal, end_unit=ordinal+1,
        config=copy.deepcopy(block['config']))))
    rejects(lambda: validate_partial_results(block, dict(payload, receipts=[outside])))
invalid_middle = copy.deepcopy(intermediate)
rejects(lambda: validate_partial_results(invalid_middle, dict(
    format=FORMAT, block_id=invalid_middle['block_id'], receipts=[receipts[0]])))
bad = copy.deepcopy(payload);bad['receipts'][0]['unit'] = 5
bad['receipts'] = bad['receipts'][:1]
rejects(lambda: validate_partial_results(block, bad))  # Receipt cannot move to another ordinal.
for seconds in (float('nan'), float('inf'), -1, True):
    bad = copy.deepcopy(payload);bad['receipts'][0]['compute_seconds'] = seconds
    rejects(lambda: validate_partial_results(block, bad))
oversized = copy.deepcopy(payload);oversized['receipts'][0]['result']['padding'] = 'x' * MAX_BODY_BYTES
rejects(lambda: validate_partial_results(block, oversized))
child = unit_envelope(block, 4);child['config']['program']['chunk'] = 1
assert block['config']['program']['chunk'] == 3
assert choose_units(20, 100000) == 36000
assert choose_units(6.08, 100000) == 10944
rejects(lambda: choose_units(1e100, 10000))
assert choose_units(20, 5) == 5
assert choose_units(20, 0) == 0
for rate in (True, -1, float('inf'), float('nan')):
    rejects(lambda: choose_units(rate, 100))
assert authorize_units(20, 10000, pending_units=7, reserved_units=9,
                       verification_limit=32) == 16
assert authorize_units(20, 10000, pending_units=32, reserved_units=0,
                       verification_limit=32) == 0
assert authorize_units(20, 10000, pending_units=31, reserved_units=8,
                       verification_limit=32) == 0
# Two block requests in one transaction consume the same unit budget.
reserved = 0
for _ in range(4):
    issued = authorize_units(20, 10000, pending_units=3,
                             reserved_units=reserved, verification_limit=32)
    reserved += issued
assert reserved == 29
# Uploading moves work from reserved to pending; it cannot renew the budget.
assert authorize_units(20, 10000, pending_units=11, reserved_units=21,
                       verification_limit=32) == 0
for value in (True, -1, 1.0, None, MAX_INTEGER + 1):
    for field in ('pending_units', 'reserved_units', 'verification_limit'):
        accounting = dict(pending_units=0, reserved_units=0, verification_limit=32)
        accounting[field] = value
        rejects(lambda: authorize_units(20, 10000, **accounting))
print('PASS block subdivision, unit receipt parity, partial batches, scope rejection and allocation cap')

assert prefetch_due(12000, 20)
assert not prefetch_due(12001, 20)
assert prefetch_due(16000, 20, request_seconds=400)
assert not prefetch_due(1, 0)
assert prefetch_due(0, 0)
for invalid in (True, -1, float('nan'), float('inf')):
    rejects(lambda: prefetch_due(1, invalid))
rejects(lambda: choose_units(20, 100000, target_seconds=120))
print('PASS 30-minute sizing, explicit capacity failure and ten-minute prefetch threshold')
