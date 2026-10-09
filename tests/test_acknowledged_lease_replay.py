"""Late allocation snapshots must not re-run an already acknowledged lease."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'worker'))
import worker

with tempfile.TemporaryDirectory() as tmp:
    state = {'server': 'https://example.invalid', 'device_id': 'test', 'device_token': 'test'}
    queue = worker.result_outbox(Path(tmp) / 'client.json', state)
    receipt = {'lease_id': 'completed', 'work_token': 'test', 'result': {}}
    assert queue.reserve('completed')
    queue.append(receipt)
    queue.confirm('completed')
    queue.flush_confirmed()
    assert not queue.pending()
    assert 'completed' in queue.computed_ids()
    assert not queue.reserve('completed')
    assert queue.reserve('next')
print('PASS: an accepted receipt is not recomputed from a stale prefetched response')
