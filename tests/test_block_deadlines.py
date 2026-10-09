"""A block never becomes executable without a current server lifetime."""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "worker"), str(ROOT / "solver/runtime/src")]
from block_queue import BlockQueue
from block_transport import BlockTransport
from search.work_block import FORMAT


def load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def save(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


block = dict(
    format=FORMAT, block_id="b", engine="bounded_crib_v1", start_unit=0, end_unit=12,
    config=dict(requires=["cpu", "bounded_crib_v1"], program=dict(
        ciphertext="BDZGO", hypotheses=[dict(text="BD", legal_clean_offsets=[0])],
        chunk=3, ordinal_base=0, candidate_limit=3)),
)
owner = dict(server="https://example.invalid", device_id="device")

with tempfile.TemporaryDirectory() as folder:
    path = Path(folder) / "queue.json"
    queue = BlockQueue(path, owner, load, save)
    request_id = queue.allocation_request()
    calls = []

    def modern(endpoint, payload):
        calls.append(endpoint)
        assert payload["request_id"] == request_id
        return dict(block=block, status="reserved", valid_for_seconds=600)

    assert BlockTransport(queue, modern).allocate()["block"] == block
    assert calls == ["/api/work-blocks"], "modern allocation added a status round trip"
    assert queue.next_unit()[1]["start_unit"] == 0
    queue.release_claim()
    queue.deadlines["b"] = time.monotonic() - 1
    assert queue.next_unit() is None, "expired local deadline permitted new work"

    # A persisted wall-clock value from an older client cannot renew authority.
    stored = load(path)
    stored["blocks"][0]["expires_local"] = time.time() + 999999
    save(path, stored)
    restarted = BlockQueue(path, owner, load, save)
    assert restarted.next_unit() is None, "restart trusted a stale local lifetime"
    restarted.update_status({"b": dict(status="reserved", valid_for_seconds=30)})
    assert restarted.next_unit()[1]["start_unit"] == 0
    restarted.release_claim()

with tempfile.TemporaryDirectory() as folder:
    queue = BlockQueue(Path(folder) / "queue.json", owner, load, save)
    calls = []

    def legacy(endpoint, payload):
        calls.append(endpoint)
        if endpoint == "/api/work-blocks":
            return dict(block=block, status="reserved")
        assert endpoint == "/api/work-blocks/status"
        return dict(blocks=[dict(block_id="b", status="reserved", valid_for_seconds=30)])

    BlockTransport(queue, legacy).allocate()
    assert calls == ["/api/work-blocks", "/api/work-blocks/status"]
    assert queue.next_unit() is not None

with tempfile.TemporaryDirectory() as folder:
    queue = BlockQueue(Path(folder) / "queue.json", owner, load, save)

    def invalid(endpoint, payload):
        return dict(block=block, status="reserved", valid_for_seconds=7201)

    try:
        BlockTransport(queue, invalid).allocate()
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid lifetime was accepted")
    assert queue.identities() == [] and queue.allocation_request(), "invalid response changed durable allocation"

print("PASS authoritative monotonic block deadlines, recovery hold, legacy fallback and lifetime bounds")
