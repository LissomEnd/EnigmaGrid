"""Focused isolated checks for Windows long-block refill policy."""
import importlib.util
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / 'worker'), str(REPO / 'solver/runtime/src')]
import block_pipeline as module


class Queue:
    max_pending = 8

    def __init__(self, units=1500, blocks=1, pending=0):
        self.units = units
        self.blocks = blocks
        self.receipts = pending

    def remaining(self):
        return self.units, self.blocks

    def pending(self):
        return [{} for _ in range(self.receipts)]

    def claim_prefetched(self, _lanes):
        return None


class Transport:
    def __init__(self):
        self.calls = 0
        self.called = threading.Event()

    def allocate(self):
        self.calls += 1
        self.called.set()
        return {'block': None, 'wait_reason': 'no_compatible_work', 'retry_after_seconds': 10}

    def upload(self):
        return 0


def case(units, blocks=1, pending=0, rate=1, expect=False, paused=False):
    queue = Queue(units, blocks, pending)
    transport = Transport()
    pipeline = module.BlockPipeline(queue, transport, lambda _job: {})
    pipeline.rate = rate
    if pending:
        pipeline.next_upload = time.monotonic() + 60
    try:
        pipeline.tick(allow_compute=not paused)
        assert transport.called.wait(.2) == expect, (units, blocks, pending, rate, paused)
        assert transport.calls == int(expect)
        return pipeline.initial_fill
    finally:
        pipeline.close()


assert case(1500, expect=True) is True
assert case(1800, expect=False) is True
assert case(2000, expect=False) is True
assert case(1500, blocks=2, expect=False) is True
assert case(1500, pending=8, expect=False) is True
assert case(1500, rate=0, expect=False) is True
assert case(0, rate=0, expect=True) is True
assert case(1500, paused=True, expect=False) is True

queue = Queue(2000)
transport = Transport()
pipeline = module.BlockPipeline(queue, transport, lambda _job: {})
pipeline.rate = 1
try:
    for _ in range(3):
        pipeline._observe_initial_fill()
    pipeline.tick()
    assert not pipeline.initial_fill and transport.calls == 0
    queue.units = 601
    pipeline.tick()
    assert transport.calls == 0
    queue.units = 600
    pipeline.tick()
    assert transport.called.wait(.2) and transport.calls == 1
finally:
    pipeline.close()

# A single slow completion cannot close initial fill; a faster following
# completion must reopen the second reservation before the 600 s threshold.
queue = Queue(1000)
transport = Transport()
pipeline = module.BlockPipeline(queue, transport, lambda _job: {})
try:
    pipeline.rate = .5
    pipeline._observe_initial_fill()
    assert pipeline.initial_fill
    pipeline.rate = 1
    pipeline._observe_initial_fill()
    pipeline.tick()
    assert pipeline.initial_fill and transport.called.wait(.2)
finally:
    pipeline.close()

queue = Queue(1000)
transport = Transport()
pipeline = module.BlockPipeline(queue, transport, lambda _job: {})
try:
    for observed in (.5,.62,.74):
        pipeline.rate=observed
        pipeline._observe_initial_fill()
    assert pipeline.initial_fill # The three observations were not stable.
finally:
    pipeline.close()

# Three stable durable observations close initial fill; the normal 600 s
# threshold then applies. An absent server retry must back off progressively.
queue = Queue(1000)
transport = Transport()
pipeline = module.BlockPipeline(queue, transport, lambda _job: {})
try:
    pipeline.rate = .5
    for _ in range(3):
        pipeline._observe_initial_fill()
    assert not pipeline.initial_fill
    pipeline.rate = .56  # 12% faster: 1,786 s, but keep ordinary refill.
    pipeline._observe_initial_fill()
    pipeline.tick()
    assert not pipeline.initial_fill and transport.calls == 0
    pipeline.rate = 1  # 100% faster: the original 30-minute target is no longer met.
    pipeline._observe_initial_fill()
    pipeline.tick()
    assert pipeline.initial_fill and transport.called.wait(.2) and transport.calls == 1
finally:
    pipeline.close()

queue = Queue(0, blocks=0)
transport = Transport()
transport.allocate = lambda: {'block': None, 'wait_reason': 'verification_pending', 'retry_after_seconds': 17}
pipeline = module.BlockPipeline(queue, transport, lambda _job: {})
try:
    pipeline.tick()
    deadline=time.monotonic()+1
    while pipeline.fetch is not None and not pipeline.fetch.done() and time.monotonic()<deadline:
        time.sleep(.001)
    pipeline.tick()
    assert pipeline.next_fetch-time.monotonic()>16.8
finally:
    pipeline.close()

queue = Queue(0, blocks=0)
transport = Transport()
transport.allocate = lambda: {'block': None, 'wait_reason': 'no_compatible_work'}
pipeline = module.BlockPipeline(queue, transport, lambda _job: {})
try:
    delays=[]
    for _ in range(4):
        pipeline.next_fetch=0
        pipeline.tick()
        deadline=time.monotonic()+1
        while pipeline.fetch is not None and not pipeline.fetch.done() and time.monotonic()<deadline:
            time.sleep(.001)
        pipeline.tick()
        delays.append(pipeline.next_fetch-time.monotonic())
    assert all(a-.1<=b for a,b in zip((1,2,4,8),delays)), delays
    assert pipeline.empty_fetches==4
finally:
    pipeline.close()

queue = Queue(1500)
transport = Transport()
pipeline = module.BlockPipeline(queue, transport, lambda _job: {})
pipeline.fill_rate_hint = .5  # Server estimates 3000 s without device calibration.
try:
    pipeline.tick()
    assert transport.calls == 0 and pipeline.initial_fill
    pipeline.rate = 1  # Local computation shows only 1500 s of ready work.
    pipeline.tick()
    assert transport.called.wait(.2) and transport.calls == 1 and pipeline.initial_fill
finally:
    pipeline.close()

queue = Queue(1500, pending=8)
transport = Transport()
pipeline = module.BlockPipeline(queue, transport, lambda _job: {})
pipeline.rate = 1
pipeline.next_upload = time.monotonic() + 60
try:
    pipeline.tick()
    assert transport.calls == 0
    queue.receipts = 0
    pipeline.tick()
    assert transport.called.wait(.2) and transport.calls == 1
finally:
    pipeline.close()

queue = Queue(0, blocks=0)
transport = Transport()

def hinted_allocate():
    transport.calls += 1
    if transport.calls == 1:
        queue.units, queue.blocks = 1500, 1
        return {'status': 'reserved', 'block': {'start_unit': 0, 'end_unit': 1500},
                'estimated_seconds': 1500}
    transport.called.set()
    return {'block': None, 'wait_reason': 'no_compatible_work', 'retry_after_seconds': 10}

transport.allocate = hinted_allocate
pipeline = module.BlockPipeline(queue, transport, lambda _job: {})
try:
    pipeline.tick()
    deadline = time.monotonic() + 1
    while transport.calls < 1 and time.monotonic() < deadline:
        time.sleep(.001)
    assert transport.calls == 1
    pipeline.tick()  # Server-observed rate starts successor fetch before first compute.
    assert transport.called.wait(.2) and transport.calls == 2 and pipeline.rate == 0
finally:
    pipeline.close()

print('PASS Windows initial fill, 600s refill, pause, two-block and outbox bounds')
