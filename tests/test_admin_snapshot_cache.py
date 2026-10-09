"""Check that slow dashboard snapshots are single-flight and stale-safe, without production DB access."""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="admin-cache-test-") as folder:
    os.environ["GRID_DATA_DIR"] = folder
    os.environ["GRID_DB"] = str(Path(folder) / "fixture.sqlite3")
    os.environ["GRID_CONFIG"] = str(Path(folder) / "fixture.json")
    sys.path.insert(0, str(root / "server"))
    import operations as op

    gate = threading.Event()
    started = threading.Event()
    calls = []
    def fake_snapshot():
        calls.append(len(calls) + 1)
        started.set()
        assert gate.wait(5), "Cache computation remained blocked"
        return {"time": time.time(), "version": len(calls)}

    op.snapshot = fake_snapshot
    assert op.cached_snapshot() is None
    assert started.wait(2)
    for _ in range(12):
        assert op.cached_snapshot() is None
    assert len(calls) == 1, "Concurrent browser requests created duplicate full snapshots"
    gate.set()
    for _ in range(100):
        current = op.cached_snapshot()
        if current is not None:
            break
        time.sleep(.01)
    assert current["version"] == 1 and current["snapshot_age_seconds"] >= 0

    gate.clear()
    started.clear()
    with op._SNAPSHOT_CACHE_LOCK:
        op._SNAPSHOT_REFRESHED_AT -= 31
    previous = op.cached_snapshot()
    assert previous["version"] == 1, "A stale snapshot should remain available"
    assert started.wait(2)
    for _ in range(12):
        assert op.cached_snapshot()["version"] == 1
    assert len(calls) == 2, "Stale snapshot triggered duplicate queries"
    gate.set()
    for _ in range(100):
        updated = op.cached_snapshot()
        if updated["version"] == 2:
            break
        time.sleep(.01)
    assert updated["version"] == 2
    assert updated["snapshot_age_seconds"] < 30
    print("PASS admin cache single-flight, fast stale response, refreshed result; production DB untouched")
