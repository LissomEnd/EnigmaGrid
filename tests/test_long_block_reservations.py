"""Long reservations are disjoint, idempotent and atomic under concurrency."""
import concurrent.futures
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'server'),str(ROOT/'solver/runtime/src')]
import work_blocks as w

with tempfile.TemporaryDirectory() as folder:
    db=Path(folder)/'isolated.sqlite3'
    def connect():
        c=sqlite3.connect(db,timeout=5,isolation_level=None);c.row_factory=sqlite3.Row;return c
    c=connect()
    c.executescript("""CREATE TABLE devices(id TEXT PRIMARY KEY,enabled INTEGER,quarantined INTEGER);
      CREATE TABLE campaigns(id TEXT PRIMARY KEY,status TEXT);
      CREATE TABLE requeue(segment_id TEXT,start_unit INTEGER,end_unit INTEGER,queued_at REAL);
      CREATE TABLE segments(id TEXT PRIMARY KEY,campaign_id TEXT,engine TEXT,start_unit INTEGER,
        end_unit INTEGER,next_unit INTEGER,priority INTEGER,config_json TEXT);
      INSERT INTO devices VALUES('a',1,0),('b',1,0),('disabled',0,0),('quarantined',1,1);
      INSERT INTO campaigns VALUES('campaign','running');""")
    cfg=dict(requires=['cpu','bounded_crib_v1'],program=dict(ciphertext='BDZGO',
        hypotheses=[dict(text='BD',legal_clean_offsets=[0])],chunk=3,ordinal_base=0,candidate_limit=3))
    c.execute("INSERT INTO segments VALUES('s','campaign','bounded_crib_v1',0,100000,0,10,?)",(json.dumps(cfg),))
    w.init_schema(c)
    def reserve(device,request):
        con=connect()
        try:return w.reserve(con,device,request,observed_rate=6.08,timestamp=1000,eligible=lambda d,s:True)
        finally:con.close()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        same=list(pool.map(lambda _:reserve('a','same-request'),range(4)))
    assert len({x['block']['block_id'] for x in same})==1
    assert sum(not x['replay'] for x in same)==1
    assert all(x['valid_for_seconds']==7200 for x in same)
    assert all(x['reserved_exposure_units']==10944 for x in same)
    assert c.execute('SELECT next_unit FROM segments').fetchone()[0]==10944
    assert same[0]['block']['end_unit']-same[0]['block']['start_unit']==10944
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        more=list(pool.map(lambda args:reserve(*args),[('a','next'),('b','first')]))
    ranges=sorted((x['block']['start_unit'],x['block']['end_unit']) for x in [same[0],*more])
    assert all(a[1]<=b[0] for a,b in zip(ranges,ranges[1:]))
    assert reserve('a','too-many')['wait_reason']=='current_and_next_reserved'
    for device in ['missing','disabled','quarantined']:
        try:reserve(device,'denied')
        except ValueError:pass
        else:raise AssertionError('Unauthorised device reserved work')
    before=c.execute('SELECT next_unit FROM segments').fetchone()[0]
    c.execute("CREATE TRIGGER reject_cursor BEFORE UPDATE ON segments BEGIN SELECT RAISE(ABORT,'simulated failure'); END")
    try:reserve('b','rollback')
    except sqlite3.IntegrityError:pass
    else:raise AssertionError('Injected failure absent')
    assert c.execute("SELECT count(*) FROM work_blocks WHERE request_id='rollback'").fetchone()[0]==0
    assert c.execute('SELECT next_unit FROM segments').fetchone()[0]==before
    c.execute('DROP TRIGGER reject_cursor')
    # Exercise the real Windows durable cursor -> server intake -> individual ack.
    sys.path.insert(0,str(ROOT/'worker'))
    from block_queue import BlockQueue
    from search.crib_work import run
    import worker
    queue=BlockQueue(Path(folder)/'client-queue',dict(server='isolated',device_id='a'),worker.load_state,worker.save_state)
    queue.add(same[0]['block'],valid_for_seconds=7200)
    for _ in range(8):
        identity,envelope=queue.next_unit()
        queue.complete(identity,envelope['start_unit'],run(envelope),.05)
    pending=queue.pending()
    payload=dict(format=w.FORMAT,block_id=identity,receipts=[{k:v for k,v in x.items() if k!='block_id'} for x in pending])
    first=w.receive_partial(c,'a',payload,timestamp=1010)
    # Simulate a lost HTTP response: retain local results and resend after restart.
    queue=BlockQueue(Path(folder)/'client-queue',dict(server='isolated',device_id='a'),worker.load_state,worker.save_state)
    again=w.receive_partial(c,'a',payload,timestamp=1011)
    assert first==again and len(queue.pending())==8
    assert c.execute('SELECT count(*) FROM block_receipts').fetchone()[0]==8
    assert c.execute('SELECT received_units FROM work_blocks WHERE id=?',(identity,)).fetchone()[0]==8
    assert w.reserved_exposure_units(c,'a')==more[0]['reserved_exposure_units']-8
    assert c.execute("SELECT count(*) FROM block_receipts WHERE verification_status!='pending'").fetchone()[0]==0
    queue.acknowledge(identity,[x['unit'] for x in again['results'] if x['status']=='received'])
    queue.update_status({identity:dict(status='reserved',valid_for_seconds=7200)})
    assert not queue.pending() and queue.next_unit()[1]['start_unit']==same[0]['block']['start_unit']+8
    try:w.receive_partial(c,'b',payload,timestamp=1012)
    except ValueError:pass
    else:raise AssertionError('Cross-device receipt accepted')
    original_end=same[0]['block']['end_unit']
    w.release(c,'a',identity);w.release(c,'a',identity)
    ranges=c.execute('SELECT start_unit,end_unit FROM block_requeue WHERE source_block=?',(identity,)).fetchall()
    assert [tuple(x) for x in ranges]==[(8,original_end)]
    recovered=reserve('b','recover-missing')['block']
    assert (recovered['start_unit'],recovered['end_unit'])==(8,original_end)
    assert c.execute('SELECT count(*) FROM block_receipts').fetchone()[0]==8
    assert not c.execute('SELECT 1 FROM block_requeue WHERE source_block=?',(identity,)).fetchone()
    # An expired reservation is replayed as expired, never silently renewed.
    c.execute('BEGIN IMMEDIATE');w.expire(c,9000);c.commit()
    assert c.execute("SELECT count(*) FROM work_blocks WHERE status='reserved'").fetchone()[0]==0
    assert c.execute('SELECT count(*) FROM block_receipts').fetchone()[0]==8
    c.close()
    expired_replay=reserve('a','same-request')
    assert expired_replay['block']==same[0]['block'] and expired_replay['valid_for_seconds']==0
print('PASS 30-minute reservation, concurrent retry replay, disjoint allocation, two-block cap, revocation and atomic rollback')

print("PASS Windows durable queue to server intake, lost-response replay, individual ack and pending verification")

print("PASS release retry, missing-only reassignment, expiry and retained receipts")

with tempfile.TemporaryDirectory() as folder:
    c=sqlite3.connect(':memory:',isolation_level=None);c.row_factory=sqlite3.Row
    c.executescript("""CREATE TABLE devices(id TEXT PRIMARY KEY,enabled INTEGER,quarantined INTEGER);
      CREATE TABLE campaigns(id TEXT PRIMARY KEY,status TEXT);
      CREATE TABLE requeue(segment_id TEXT,start_unit INTEGER,end_unit INTEGER,queued_at REAL);
      CREATE TABLE segments(id TEXT PRIMARY KEY,campaign_id TEXT,engine TEXT,start_unit INTEGER,
        end_unit INTEGER,next_unit INTEGER,priority INTEGER,config_json TEXT);
      INSERT INTO devices VALUES('a',1,0);
      INSERT INTO campaigns VALUES('campaign','running');""")
    c.execute("INSERT INTO segments VALUES('bounded','campaign','bounded_crib_v1',0,100000,0,11,?)",(json.dumps(cfg),))
    c.execute("INSERT INTO segments VALUES('portable','campaign','portable_event_v1',0,100000,0,10,'{}')")
    w.init_schema(c)
    reply=w.reserve(c,'a','priority',observed_rate=6.08,timestamp=1000,eligible=lambda d,s:True)
    assert reply['wait_reason']=='legacy_priority_work'
    assert c.execute('SELECT sum(next_unit) FROM segments').fetchone()[0]==0
    # Exhausting fresh work must not bypass higher-priority returned ranges.
    c.execute("UPDATE segments SET next_unit=end_unit WHERE id='portable'")
    c.execute("INSERT INTO requeue VALUES('portable',0,1,999)")
    assert w.reserve(c,'a','returned-priority',observed_rate=6.08,timestamp=1000,eligible=lambda d,s:True)['wait_reason']=='legacy_priority_work'
    reply=w.reserve(c,'a','priority',observed_rate=6.08,timestamp=1000,eligible=lambda d,s:s['engine']=='bounded_crib_v1')
    assert reply['block']['end_unit']==10944
    # Regression: after bounded work is exhausted, legacy portable work must
    # still trigger a safe client fallback instead of permanent idle polling.
    c.execute("UPDATE segments SET next_unit=end_unit WHERE id='bounded'")
    c.execute("UPDATE segments SET next_unit=0 WHERE id='portable'")
    c.execute("DELETE FROM requeue WHERE segment_id='portable'")
    assert w.reserve(c,'a','portable-only',observed_rate=6.08,timestamp=1000,eligible=lambda d,s:True)['wait_reason']=='legacy_priority_work'
    c.execute("UPDATE segments SET next_unit=end_unit WHERE id='portable'")
    assert w.reserve(c,'a','all-exhausted',observed_rate=6.08,timestamp=1000,eligible=lambda d,s:True)['wait_reason']=='no_compatible_work'
    c.close()
print('PASS cross-engine campaign priority and capability-specific allocation')

with tempfile.TemporaryDirectory() as folder:
    c=sqlite3.connect(':memory:',isolation_level=None);c.row_factory=sqlite3.Row
    c.executescript("""CREATE TABLE devices(id TEXT PRIMARY KEY,enabled INTEGER,quarantined INTEGER);
      CREATE TABLE campaigns(id TEXT PRIMARY KEY,status TEXT);
      CREATE TABLE requeue(segment_id TEXT,start_unit INTEGER,end_unit INTEGER,queued_at REAL);
      CREATE TABLE segments(id TEXT PRIMARY KEY,campaign_id TEXT,engine TEXT,start_unit INTEGER,
        end_unit INTEGER,next_unit INTEGER,priority INTEGER,config_json TEXT);
      INSERT INTO devices VALUES('a',1,0);
      INSERT INTO campaigns VALUES('campaign','running');""")
    c.execute("INSERT INTO segments VALUES('s','campaign','bounded_crib_v1',0,3000000,0,10,?)",(json.dumps(cfg),))
    w.init_schema(c)
    capacity_rate=w.MAX_UNITS/w.TARGET_SECONDS
    first=w.reserve(c,'a','million-1',observed_rate=capacity_rate,timestamp=1000,eligible=lambda d,s:True)
    second=w.reserve(c,'a','million-2',observed_rate=capacity_rate,timestamp=1000,eligible=lambda d,s:True)
    assert first['block']['end_unit']-first['block']['start_unit']==w.MAX_UNITS
    assert second['reserved_exposure_units']==w.MAX_UNRECEIVED_RESERVED_UNITS_PER_DEVICE
    assert w.reserve(c,'a','million-3',observed_rate=capacity_rate,timestamp=1000,eligible=lambda d,s:True)['wait_reason']=='current_and_next_reserved'
    c.close()
print('PASS explicit two-million-unit unreceived reservation boundary')
