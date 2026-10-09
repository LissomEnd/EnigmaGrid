"""Explicit grouped transport; each unit retains its original scientific receipt.

Groups are transport containers, never verification or credit units. Receivers
must authenticate block ownership and charge every contained unit independently.
"""
import json
from search.work_block import FORMAT as BLOCK_FORMAT, validate_partial_results

FORMAT = 'bounded_result_groups_v1'
MAX_GROUPS = 8
UNITS_PER_GROUP = 8
# A grouped packet can contain eight individually bounded partial packets.
# Keep the ordinary partial-result limit in work_block.py unchanged.
MAX_BODY_BYTES = 768 * 1024


def validate_groups(block, payload):
    if not isinstance(payload, dict) or set(payload) != {'format', 'block_id', 'groups'}:
        raise ValueError('Invalid grouped result fields')
    if payload['format'] != FORMAT or payload['block_id'] != block['block_id']:
        raise ValueError('Grouped results do not belong to block')
    if len(json.dumps(payload, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()) > MAX_BODY_BYTES:
        raise ValueError('Grouped result body too large')
    groups = payload['groups']
    if not isinstance(groups, list) or not 1 <= len(groups) <= MAX_GROUPS:
        raise ValueError('Invalid group count')
    seen = set()
    for group in groups:
        partial = dict(format=BLOCK_FORMAT, block_id=block['block_id'], receipts=group)
        validate_partial_results(block, partial)
        for receipt in group:
            if receipt['unit'] in seen:
                raise ValueError('Duplicate unit across groups')
            seen.add(receipt['unit'])
    return len(seen)


def partials(payload):
    """Use only after validate_groups; legacy intake retains per-unit idempotency."""
    return [dict(format=BLOCK_FORMAT, block_id=payload['block_id'], receipts=group)
            for group in payload['groups']]
