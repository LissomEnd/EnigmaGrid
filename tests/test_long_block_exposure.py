"""Bounded verification liability follows reserved, received and promoted units."""
import json
import sqlite3
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'server'),str(ROOT/'solver/runtime/src')]
import work_blocks as w


def connection():
    con=sqlite3.connect(':memory:',isolation_level=None)
    con.row_factory=sqlite3.Row
    con.executescript("""CREATE TABLE devices(id TEXT PRIMARY KEY,enabled INTEGER,quarantined INTEGER);
      CREATE TABLE campaigns(id TEXT PRIMARY KEY,status TEXT);
      CREATE TABLE requeue(segment_id TEXT,start_unit INTEGER,end_unit INTEGER,queued_at REAL);
      CREATE TABLE segments(id TEXT PRIMARY KEY,campaign_id TEXT,engine TEXT,start_unit INTEGER,
        end_unit INTEGER,next_unit INTEGER,priority INTEGER,config_json TEXT);
      CREATE TABLE submissions(id TEXT PRIMARY KEY,lease_id TEXT UNIQUE,segment_id TEXT,start_unit INTEGER,
        end_unit INTEGER,device_id TEXT,status TEXT);
      INSERT INTO devices VALUES('a',1,0);
      INSERT INTO campaigns VALUES('campaign','running');""")
    return con


con=connection()
try:
    # Simulate a database written by the previous, additive protocol version.
    con.executescript("""CREATE TABLE work_blocks(
      id TEXT PRIMARY KEY,device_id TEXT NOT NULL,request_id TEXT NOT NULL,
      segment_id TEXT NOT NULL,start_unit INTEGER NOT NULL,end_unit INTEGER NOT NULL,
      config_json TEXT NOT NULL,created_at REAL NOT NULL,expires_at REAL NOT NULL,
      status TEXT NOT NULL DEFAULT 'reserved',worker_version TEXT NOT NULL DEFAULT '',
      UNIQUE(device_id,request_id));
      CREATE TABLE block_receipts(block_id TEXT NOT NULL,unit INTEGER NOT NULL,
        fingerprint TEXT NOT NULL,result_json TEXT NOT NULL,compute_seconds REAL NOT NULL,
        received_at REAL NOT NULL,verification_status TEXT NOT NULL DEFAULT 'pending',
        PRIMARY KEY(block_id,unit));
      INSERT INTO work_blocks VALUES('old','a','old-request','s',0,3,'{}',1000,8200,'reserved','0.4.66');
      INSERT INTO block_receipts VALUES('old',0,'f','{}',0.1,1000,'pending');
      INSERT INTO block_receipts VALUES('old',1,'f','{}',0.1,1000,'pending');
      INSERT INTO block_receipts VALUES('old',2,'f','{}',0.1,1000,'pending');""")
    con.execute("INSERT INTO segments VALUES('s','campaign','bounded_crib_v1',0,3000000,3,10,'{}')")
    con.execute("INSERT INTO submissions VALUES('exact',?,'s',0,1,'a','pending')",(w._lease_identity('old',0),))
    con.execute("INSERT INTO submissions VALUES('different',?,'s',1,2,'a','accepted_trusted')",(w._lease_identity('other',1),))
    w.init_schema(con)
    old=con.execute("SELECT received_units FROM work_blocks WHERE id='old'").fetchone()
    exposure=con.execute("SELECT pending_units,unpromoted_units FROM device_work_exposure WHERE device_id='a'").fetchone()
    assert old['received_units']==3 and tuple(exposure)==(1,2),tuple(exposure)
    assert con.execute("SELECT promoted_at FROM block_receipts WHERE unit=0").fetchone()[0]==-1
    assert con.execute("SELECT count(*) FROM block_receipts WHERE promoted_at IS NULL").fetchone()[0]==2
    w.init_schema(con)
    assert tuple(con.execute("SELECT pending_units,unpromoted_units FROM device_work_exposure WHERE device_id='a'").fetchone())==(1,2)
    # Scientific admission shifts liability from durable intake to pending
    # without freeing capacity or counting the same unit twice.
    con.execute("BEGIN IMMEDIATE")
    con.execute("INSERT INTO submissions VALUES('promoted',?,'s',1,2,'a','pending')",(w._lease_identity('old',1),))
    con.execute("UPDATE block_receipts SET promoted_at=1001 WHERE block_id='old' AND unit=1")
    con.commit()
    assert tuple(con.execute("SELECT pending_units,unpromoted_units FROM device_work_exposure WHERE device_id='a'").fetchone())==(2,1)
    con.execute("UPDATE submissions SET status='accepted_trusted' WHERE id='promoted'")
    assert tuple(con.execute("SELECT pending_units,unpromoted_units FROM device_work_exposure WHERE device_id='a'").fetchone())==(1,1)
    con.execute("BEGIN IMMEDIATE")
    con.execute("INSERT INTO submissions VALUES('rollback',?,'s',2,3,'a','pending')",(w._lease_identity('old',2),))
    con.execute("UPDATE block_receipts SET promoted_at=1002 WHERE block_id='old' AND unit=2")
    con.rollback()
    assert tuple(con.execute("SELECT pending_units,unpromoted_units FROM device_work_exposure WHERE device_id='a'").fetchone())==(1,1)
    con.execute("UPDATE work_blocks SET status='expired' WHERE id='old'")
    assert w.reserved_exposure_units(con,'a')==0
    assert tuple(con.execute("SELECT pending_units,unpromoted_units FROM device_work_exposure WHERE device_id='a'").fetchone())==(1,1)
    # A device already at the two-million-unit scientific backlog boundary
    # cannot reserve new primary work. Validation endpoints remain independent.
    con.execute("INSERT INTO submissions VALUES('huge','h','s',0,1999998,'a','pending')")
    assert con.execute("SELECT pending_units+unpromoted_units FROM device_work_exposure WHERE device_id='a'").fetchone()[0]==2*w.MAX_UNITS
    reply=w.reserve(con,'a','blocked',observed_rate=1,timestamp=1000,eligible=lambda d,s:True)
    assert reply['block'] is None and reply['wait_reason']=='verification_backlog_budget'
    assert reply['pending_verification_units']==2*w.MAX_UNITS-1 and reply['unpromoted_receipt_units']==1
    con.execute("UPDATE submissions SET status='verified' WHERE id='huge'")
    assert con.execute("SELECT pending_units+unpromoted_units FROM device_work_exposure WHERE device_id='a'").fetchone()[0]==2
    # Privacy tombstone moves only unpromoted exposure; deleting the original
    # submission removes its pending liability without deleting the receipt.
    con.execute("UPDATE work_blocks SET device_id='deleted_test' WHERE id='old'")
    con.execute("DELETE FROM submissions WHERE device_id='a'")
    assert con.execute("SELECT pending_units+unpromoted_units FROM device_work_exposure WHERE device_id='a'").fetchone()[0]==0
    assert con.execute("SELECT unpromoted_units FROM device_work_exposure WHERE device_id='deleted_test'").fetchone()[0]==1
finally:
    con.close()
print('PASS exact historical promotion migration, pending/receipt transitions, rollback, expiry, budget and tombstone')

# Roll back to the previous coordinator after the additive migration. Its
# receipt INSERT omits both new columns. A crash before promotion must still
# consume reserved capacity; a later exact submission clears only its own
# unpromoted exposure on the next candidate boot.
con=connection()
try:
    con.executescript("""CREATE TABLE work_blocks(
      id TEXT PRIMARY KEY,device_id TEXT NOT NULL,request_id TEXT NOT NULL,
      segment_id TEXT NOT NULL,start_unit INTEGER NOT NULL,end_unit INTEGER NOT NULL,
      config_json TEXT NOT NULL,created_at REAL NOT NULL,expires_at REAL NOT NULL,
      status TEXT NOT NULL DEFAULT 'reserved',worker_version TEXT NOT NULL DEFAULT '',
      UNIQUE(device_id,request_id));
      CREATE TABLE block_receipts(block_id TEXT NOT NULL,unit INTEGER NOT NULL,
      fingerprint TEXT NOT NULL,result_json TEXT NOT NULL,compute_seconds REAL NOT NULL,
      received_at REAL NOT NULL,verification_status TEXT NOT NULL DEFAULT 'pending',
      PRIMARY KEY(block_id,unit));
      INSERT INTO segments VALUES('s','campaign','bounded_crib_v1',0,3,0,10,'{}');
      INSERT INTO work_blocks VALUES('rollback-block','a','request','s',0,3,'{}',1,7201,'reserved','0.4.66');""")
    w.init_schema(con)
    legacy="""INSERT OR IGNORE INTO block_receipts(
        block_id,unit,fingerprint,result_json,compute_seconds,received_at)
        VALUES('rollback-block',?,'f','{}',0.1,?)"""
    con.execute(legacy,(0,2))
    assert con.execute("SELECT received_units FROM work_blocks WHERE id='rollback-block'").fetchone()[0]==1
    assert con.execute("SELECT promoted_at FROM block_receipts WHERE unit=0").fetchone()[0] is None
    assert con.execute("SELECT unpromoted_units FROM device_work_exposure WHERE device_id='a'").fetchone()[0]==1
    assert con.execute("SELECT value FROM work_exposure_meta WHERE key='legacy_receipts_dirty'").fetchone()[0]=='1'
    con.execute(legacy,(0,2))  # A replay cannot charge the same receipt twice.
    w.init_schema(con)  # Crash before promotion: fail closed and keep exposure.
    assert con.execute("SELECT unpromoted_units FROM device_work_exposure WHERE device_id='a'").fetchone()[0]==1
    con.execute(legacy,(1,3))
    con.execute("INSERT INTO submissions VALUES('old-promoted',?,'s',1,2,'a','pending')",
                (w._lease_identity('rollback-block',1),))
    w.init_schema(con)
    assert con.execute("SELECT received_units FROM work_blocks WHERE id='rollback-block'").fetchone()[0]==2
    assert con.execute("SELECT promoted_at FROM block_receipts WHERE unit=1").fetchone()[0]==3
    assert con.execute("SELECT unpromoted_units FROM device_work_exposure WHERE device_id='a'").fetchone()[0]==1
    assert con.execute("SELECT value FROM work_exposure_meta WHERE key='legacy_receipts_dirty'").fetchone()[0]=='0'
    # Current code explicitly writes NULL, then updates received_units itself.
    con.execute("""INSERT INTO block_receipts(block_id,unit,fingerprint,result_json,
        compute_seconds,received_at,promoted_at) VALUES('rollback-block',2,'f','{}',0.1,4,NULL)""")
    con.execute("UPDATE work_blocks SET received_units=received_units+1 WHERE id='rollback-block'")
    assert con.execute("SELECT received_units FROM work_blocks WHERE id='rollback-block'").fetchone()[0]==3
    assert con.execute("SELECT unpromoted_units FROM device_work_exposure WHERE device_id='a'").fetchone()[0]==2
finally:
    con.close()
print('PASS rollback legacy intake, crash, exact promotion reconciliation and no double charge')
