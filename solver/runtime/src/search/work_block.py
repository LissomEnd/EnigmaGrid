"""Versioned long-work descriptors and bounded partial receipts.

This is computation/shape validation, not lease authorization. The coordinator
must authenticate ownership, expiry and the verification budget separately.
Legacy single-unit endpoints must not accept these descriptors implicitly.
"""
import copy
import json
import math

from search.crib_work import CAPABILITY, validate_envelope, validate_receipt_shape

FORMAT = 'bounded_work_block_v2'
MAX_UNITS = 1_000_000
TARGET_SECONDS = 1800
PREFETCH_SECONDS = 600
MAX_RECEIPTS = 8
MAX_BODY_BYTES = 256 * 1024
MAX_INTEGER = (1 << 63) - 1


def authorize_units(verified_units_per_second, remaining_units, *,
                    pending_units, reserved_units, verification_limit,
                    target_seconds=TARGET_SECONDS):
    """Bound a proposed block by outstanding *units*, never container count.

    All accounting arguments must come from the coordinator transaction, not
    client telemetry. Callers must reserve the returned units atomically and
    retain reservations across replay. Upload acknowledgement alone does not
    free verification credit. This helper does not authorize a lease itself.
    """
    for value in (pending_units, reserved_units, verification_limit):
        if type(value) is not int or not 0 <= value <= MAX_INTEGER:
            raise ValueError('Invalid server verification accounting')
    proposed = choose_units(verified_units_per_second, remaining_units,
                            target_seconds=target_seconds)
    available = max(0, verification_limit - pending_units - reserved_units)
    return min(proposed, available)


def choose_units(verified_units_per_second, remaining_units, *, target_seconds=TARGET_SECONDS):
    """Server-observed rate only; a client cannot prescribe its allocation size."""
    if type(remaining_units) is not int or remaining_units < 0:
        raise ValueError('Invalid remaining domain')
    if type(target_seconds) is not int or not TARGET_SECONDS <= target_seconds <= 7200:
        raise ValueError('Invalid target duration')
    if type(verified_units_per_second) not in (int, float) or not math.isfinite(verified_units_per_second) or verified_units_per_second <= 0:
        raise ValueError('Invalid measured throughput')
    # Never silently advertise a 30-minute block after truncating it to a cap.
    capacity_rate = MAX_UNITS / target_seconds
    if verified_units_per_second > capacity_rate:
        raise ValueError('Measured rate exceeds block capacity; larger protocol required')
    requested = max(1, math.ceil(verified_units_per_second * target_seconds))
    return min(remaining_units, requested)


def prefetch_due(remaining_units, observed_units_per_second, *, request_seconds=0):
    """Refill with ten minutes left, or earlier for a slow connection.

    This is a local scheduling decision, never server authorization. The caller
    must deduplicate in-flight requests and durably retain the returned block.
    """
    if type(remaining_units) is not int or remaining_units < 0:
        raise ValueError('Invalid remaining units')
    for value in (observed_units_per_second, request_seconds):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('Invalid refill timing')
    if observed_units_per_second == 0:
        return remaining_units == 0
    return remaining_units / observed_units_per_second <= max(PREFETCH_SECONDS, 2 * request_seconds)


def _unit(block, ordinal):
    return dict(engine=CAPABILITY, start_unit=ordinal, end_unit=ordinal + 1,
                config=copy.deepcopy(block['config']))


def validate_block(block):
    if not isinstance(block, dict) or set(block) != {'format', 'block_id', 'engine', 'start_unit', 'end_unit', 'config'}:
        raise ValueError('Invalid block fields')
    if block['format'] != FORMAT or block['engine'] != CAPABILITY:
        raise ValueError('Unsupported block format')
    identity = block['block_id']
    if not isinstance(identity, str) or not 1 <= len(identity) <= 128 or not identity.isascii() or not all(c.isalnum() or c in '-_' for c in identity):
        raise ValueError('Invalid block identity')
    start, end = block['start_unit'], block['end_unit']
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= MAX_INTEGER or end - start > MAX_UNITS:
        raise ValueError('Invalid block range')
    cfg = block['config']
    if not isinstance(cfg, dict) or set(cfg) != {'program', 'requires'}:
        raise ValueError('Long blocks require an indexed program')
    # Validate both boundaries, including program ordinal/domain overflow.
    for ordinal in {start, end - 1}:
        validate_envelope(_unit(block, ordinal))
    # Boundaries alone do not validate intermediate hypotheses in the cycle.
    program = cfg['program']
    for hypothesis in program['hypotheses']:
        if any(offset + len(hypothesis['text']) > len(program['ciphertext'])
               for offset in hypothesis['legal_clean_offsets']):
            raise ValueError('Block contains a crib outside ciphertext')
    return block


def unit_envelope(block, ordinal):
    validate_block(block)
    if type(ordinal) is not int or not block['start_unit'] <= ordinal < block['end_unit']:
        raise ValueError('Unit outside assigned block')
    result = _unit(block, ordinal)
    validate_envelope(result)
    return result


def validate_partial_results(block, payload):
    validate_block(block)
    if not isinstance(payload, dict) or set(payload) != {'format', 'block_id', 'receipts'} or payload['format'] != FORMAT or payload['block_id'] != block['block_id']:
        raise ValueError('Partial results do not belong to this block')
    encoded = json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode()
    if len(encoded) > MAX_BODY_BYTES:
        raise ValueError('Partial result body too large')
    receipts = payload['receipts']
    if not isinstance(receipts, list) or not 1 <= len(receipts) <= MAX_RECEIPTS:
        raise ValueError('Invalid partial result count')
    seen = set()
    for entry in receipts:
        if not isinstance(entry, dict) or set(entry) != {'unit', 'compute_seconds', 'result'}:
            raise ValueError('Invalid partial receipt fields')
        ordinal = entry['unit']
        if type(ordinal) is not int or ordinal in seen:
            raise ValueError('Invalid or duplicate unit')
        if not block['start_unit'] <= ordinal < block['end_unit']:
            raise ValueError('Unit outside assigned block')
        seen.add(ordinal)
        seconds = entry['compute_seconds']
        if type(seconds) not in (float, int) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError('Invalid compute duration')
        # The entire descriptor was checked above, including intermediate
        # hypotheses. Shape validation itself validates this unit's envelope;
        # calling unit_envelope here would repeat both checks for every receipt.
        # Keep a private config copy, and never cache a receipt validation result.
        validate_receipt_shape(_unit(block, ordinal), entry['result'])
    return payload
