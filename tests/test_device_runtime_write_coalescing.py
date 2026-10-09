"""Direct, isolated regression for authenticated device liveness writes."""
import json
import os
import sqlite3
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import coordinator as c


def connect(path):
    con = sqlite3.connect(path, isolation_level=None, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def main():
    old_cfg, old_data, old_db, old_now = c.CFG, c.DATA, c.DB, c.now
    old_mode = os.environ.get('GRID_TEST_MODE')
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        try:
            os.environ['GRID_TEST_MODE'] = '1'
            c.DATA = root / 'state'
            c.DATA.mkdir()
            c.DB = c.DATA / 'fixture.sqlite3'
            c.CFG = root / 'server.json'
            c.CFG.write_text(json.dumps({'min_worker_version': '0.5.0'}), encoding='utf-8')
            clock = [100.0]
            c.now = lambda: clock[0]
            con = connect(c.DB)
            con.execute('''CREATE TABLE devices (
                id TEXT PRIMARY KEY, last_seen REAL, meta_json TEXT NOT NULL,
                capabilities_json TEXT NOT NULL, enabled INTEGER NOT NULL,
                quarantined INTEGER NOT NULL)''')
            con.execute("INSERT INTO devices VALUES('d',100,'{}','[]',1,0)")
            current = lambda: con.execute("SELECT * FROM devices WHERE id='d'").fetchone()
            statements = []
            con.set_trace_callback(lambda sql: statements.append(sql))

            # A high-rate request burst must not take the SQLite writer.
            for step in range(1,500):
                clock[0] = 100 + step / 100.0
                c.update_device_runtime(con, current(), {})
            assert con.total_changes == 1, con.total_changes  # initial INSERT only
            assert not any(sql.lstrip().lower().startswith('update devices') for sql in statements)
            assert con.execute("SELECT last_seen FROM devices WHERE id='d'").fetchone()[0] == 100
            clock[0] = 105.0
            c.update_device_runtime(con, current(), {})
            assert con.total_changes == 2
            clock[0] = 102.0  # host clock adjustment cannot move liveness backward
            c.update_device_runtime(con, current(), {})
            assert con.total_changes == 2
            assert con.execute("SELECT last_seen FROM devices WHERE id='d'").fetchone()[0] == 105

            # Version/capability changes bypass the refresh window immediately.
            clock[0] = 105.1
            old_meta = {'worker_version': '0.4.18', 'platform': 'Windows',
                        'capabilities': ['cpu']}
            c.update_device_runtime(con, current(), {'meta': old_meta})
            assert c.worker_update_required(con.execute("SELECT * FROM devices WHERE id='d'").fetchone())[0]
            new_meta = {**old_meta, 'worker_version': '0.5.0',
                        'capabilities': ['cpu', 'gpu']}
            clock[0] = 105.2
            c.update_device_runtime(con, current(), {'meta': new_meta})
            row = con.execute("SELECT * FROM devices WHERE id='d'").fetchone()
            assert not c.worker_update_required(row)[0]
            assert 'gpu' in json.loads(row['capabilities_json'])
            assert row['last_seen'] == 105.2
            changed = con.total_changes
            clock[0] = 105.3
            c.update_device_runtime(con, current(), {'meta': new_meta})
            c.update_device_runtime(con, current(), {})
            assert con.total_changes == changed

            # Metadata changes during a backward clock step still take effect,
            # without replacing the greater server timestamp.
            clock[0] = 103.0
            c.update_device_runtime(con, current(), {'meta': old_meta})
            row = con.execute("SELECT * FROM devices WHERE id='d'").fetchone()
            assert row['last_seen'] == 105.2
            assert c.worker_update_required(row)[0]

            # No implicit commit: callers retain their transaction semantics.
            clock[0] = 111.0
            con.execute('BEGIN IMMEDIATE')
            c.update_device_runtime(con, current(), {})
            assert con.in_transaction
            assert con.execute("SELECT last_seen FROM devices WHERE id='d'").fetchone()[0] == 111.0
            con.rollback()
            assert con.execute("SELECT last_seen FROM devices WHERE id='d'").fetchone()[0] == 105.2
            con.close()

            # Two connections starting from the same stale device view must
            # produce one actual UPDATE, not one write per HTTP thread.
            race_db = root / 'race.sqlite3'
            setup = connect(race_db)
            setup.execute('CREATE TABLE devices (id TEXT PRIMARY KEY,last_seen REAL)')
            setup.execute("INSERT INTO devices VALUES('d',0)")
            setup.close()
            clock[0] = 200.0
            gate = threading.Barrier(2)

            def contender():
                peer = connect(race_db)
                snapshot = peer.execute("SELECT * FROM devices WHERE id='d'").fetchone()
                gate.wait(timeout=5)
                c.update_device_runtime(peer, snapshot, {})
                count = peer.total_changes
                peer.close()
                return count

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: contender(), range(2)))
            assert sorted(results) == [0, 1], results
            check = connect(race_db)
            assert check.execute("SELECT last_seen FROM devices WHERE id='d'").fetchone()[0] == 200
            check.close()
        finally:
            c.CFG, c.DATA, c.DB, c.now = old_cfg, old_data, old_db, old_now
            if old_mode is None:
                os.environ.pop('GRID_TEST_MODE', None)
            else:
                os.environ['GRID_TEST_MODE'] = old_mode
    print('PASS device runtime coalesces unchanged writes, updates metadata immediately, and preserves monotonic liveness')


if __name__ == '__main__':
    main()
