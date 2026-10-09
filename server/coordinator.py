import hashlib
import math
import json
import os
import secrets
import sqlite3
import sys
import tempfile
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import heapq
from pathlib import Path
from urllib.parse import urlparse

from validator import validate_result
import trusted_sampling
import work_blocks
import device_telemetry
from search import work_result_groups
import backlog_control

ROOT=Path(__file__).resolve().parents[1]
CFG=Path(os.environ.get("GRID_CONFIG",str(ROOT/"config"/"server.json")))
DATA=Path(os.environ.get("GRID_DATA_DIR",str(ROOT/"state")))
DB=Path(os.environ.get("GRID_DB",str(DATA/"grid.sqlite3")))
WEB=ROOT/"web"/"index.html"
RATE=defaultdict(deque)
RATE_SALT=secrets.token_bytes(32)
RATE_LOCK=threading.Lock()
GLOBAL_RATE=deque()
REGISTER_RATE=deque()
LAST_PRUNE=0.0
PUBLIC_STATUS_LOCK=threading.Lock()
PUBLIC_STATUS_CACHE=(None,0.0,None)
PUBLIC_STATUS_TTL_SECONDS=10
PERSONAL_STATS_LOCK=threading.Lock()
PERSONAL_STATS_CACHE={}
PERSONAL_STATS_TTL_SECONDS=10
PERSONAL_STATS_BUSY=object()
CFG_CACHE_LOCK=threading.Lock()
CFG_CACHE=(None,None)
PROMOTION_WAKE=threading.Event()
ALLOCATION_GATE=threading.Lock()
ALLOCATION_ACTIVE=set()
MAX_CONCURRENT_ALLOCATIONS=4
ALLOCATION_PATHS=frozenset(('/api/leases','/api/lease','/api/work-blocks'))
VALIDATION_FAIR_LOCK=threading.Lock()
VALIDATION_SELECTIONS=defaultdict(int)

def enter_allocation(device_id):
    """Bound slow assignment work without holding a DB lock or blocking intake."""
    with ALLOCATION_GATE:
        if device_id in ALLOCATION_ACTIVE or len(ALLOCATION_ACTIVE)>=MAX_CONCURRENT_ALLOCATIONS:
            return False
        ALLOCATION_ACTIVE.add(device_id)
        return True

def leave_allocation(device_id):
    with ALLOCATION_GATE:
        ALLOCATION_ACTIVE.discard(device_id)


def private_stack_census_snapshot(frames=None,timestamp_ms=None):
    """Bounded function/line histogram; never inspect frame arguments or locals."""
    if frames is None:frames=sys._current_frames()
    frame=None
    try:
        total=len(frames)
        histogram=defaultdict(int)
        for ident in sorted(frames)[:64]:
            frame=frames[ident]
            for _ in range(6):
                if frame is None:break
                # Basenames only: no user paths, request data, SQL or frame locals.
                key=(Path(frame.f_code.co_filename).name[:64],
                     frame.f_code.co_name[:64],int(frame.f_lineno))
                histogram[key]+=1
                frame=frame.f_back
        ranked=sorted(histogram.items(),key=lambda item:(-item[1],item[0]))[:64]
        return {'timestamp_ms':int(time.time()*1000) if timestamp_ms is None else int(timestamp_ms),
                'python_thread_count':total,'sampled_threads':min(total,64),
                'histogram':[{'module':key[0],'function':key[1],'line':key[2],
                              'count':count} for key,count in ranked]}
    finally:
        # _current_frames() owns references to live stacks until this scope ends.
        frame=None
        frames=None


def private_stack_census_worker(stop):
    """Optional local diagnostic; the shared server stop event ends it."""
    target=DATA/'coordinator-stack-diagnostics.json'
    staging=DATA/'.coordinator-stack-diagnostics.json.tmp'
    while not stop.wait(30):
        try:
            snapshot=private_stack_census_snapshot()
            staging.write_text(json.dumps(snapshot,separators=(',',':')),encoding='utf-8')
            os.replace(staging,target)
        except Exception as error:
            # The class name is sufficient to diagnose a disposable metric.
            print(json.dumps({'private_stack_diagnostics_error':type(error).__name__}),flush=True)

def _assert_test_paths():
    """Refuse production paths before any test-mode configuration or DB access."""
    if os.environ.get("GRID_TEST_MODE")!="1":
        return
    temporary_root=Path(tempfile.gettempdir()).resolve()
    data_path=DATA.resolve()
    database_path=DB.resolve()
    config_path=CFG.resolve()
    if (data_path==temporary_root or not data_path.is_relative_to(temporary_root)
            or database_path==data_path or not database_path.is_relative_to(data_path)
            or config_path==temporary_root or not config_path.is_relative_to(temporary_root)):
        raise RuntimeError("GRID_TEST_MODE requires DATA, DB and CFG inside the system temporary directory, with DB inside DATA")

def require_database_runtime():
    """Fail closed on the production writer; isolated TEMP tests keep their SQLite."""
    _assert_test_paths()
    if os.environ.get("GRID_TEST_MODE")=="1":
        return None
    from enigmagrid_sqlite_runtime_guard import require_patched_sqlite
    bundle=ROOT/'.venv-server'/'Lib'/'site-packages'/'enigmagrid_sqlite35304'
    return require_patched_sqlite(str(bundle))

def load_cfg():
    _assert_test_paths()
    # Group completion can consult policy more than once per receipt. Keep hot
    # reads in memory while still detecting local configuration edits by mtime.
    global CFG_CACHE
    stat=CFG.stat();fingerprint=(str(CFG),stat.st_mtime_ns,stat.st_size)
    with CFG_CACHE_LOCK:
        if CFG_CACHE[0]!=fingerprint:
            CFG_CACHE=(fingerprint,json.loads(CFG.read_text(encoding="utf-8")))
        cfg=CFG_CACHE[1].copy()
    if os.environ.get("GRID_HOST"): cfg["host"]=os.environ["GRID_HOST"]
    if os.environ.get("GRID_PORT"): cfg["port"]=int(os.environ["GRID_PORT"])
    if os.environ.get("GRID_REGISTRATION_CODE") is not None:
        cfg["registration_code"]=os.environ["GRID_REGISTRATION_CODE"]
    if os.environ.get("GRID_REGISTRATION_OPEN") is not None:
        cfg["registration_open"]=os.environ["GRID_REGISTRATION_OPEN"].lower() in {"1","true","yes","on"}
    if os.environ.get("GRID_TRUST_PROXY") is not None:
        cfg["trust_proxy"]=os.environ["GRID_TRUST_PROXY"].lower() in {"1","true","yes","on"}
    return cfg

def db():
    _assert_test_paths()
    if os.environ.get("GRID_TEST_MODE")!="1":
        require_database_runtime()
    DATA.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(DB,timeout=30,isolation_level=None)
    con.row_factory=sqlite3.Row
    # WAL is a database-level setting and is established once in init_db().
    # Reissuing journal_mode on every HTTP connection can wait for schema/write
    # locks and stall otherwise read-only requests such as status and lease fetches.
    con.execute("pragma foreign_keys=ON")
    con.execute("pragma busy_timeout=5000")
    return con

def now(): return time.time()
def sha(value):
    import hashlib
    if not isinstance(value,str):raise ValueError('invalid_secret_type')
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def rid(prefix): return prefix+"_"+secrets.token_urlsafe(12)

def ensure_column(con,table,name,decl):
    cols={r["name"] for r in con.execute(f"pragma table_info({table})")}
    if name not in cols: con.execute(f"alter table {table} add column {name} {decl}")

def init_calibration_match_order(con):
    """Materialize the exact matched-sample order without scanning device history.

    The original evidence and submissions remain authoritative. Persistent SQL
    triggers also maintain this additive index during a code-only rollback.
    The one-time backfill and its marker commit atomically before serving HTTP.
    """
    if con.in_transaction:raise ValueError('Calibration migration requires its own transaction')
    con.execute('BEGIN IMMEDIATE')
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS calibration_match_order(
            submission_id TEXT PRIMARY KEY,device_id TEXT NOT NULL,
            submitted_at REAL NOT NULL)""")
        con.execute("CREATE TABLE IF NOT EXISTS calibration_match_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        if not con.execute("SELECT 1 FROM calibration_match_meta WHERE key='backfilled_v1'").fetchone():
            con.execute('DELETE FROM calibration_match_order')
            con.execute("""INSERT INTO calibration_match_order(submission_id,device_id,submitted_at)
                SELECT e.submission_id,s.device_id,s.submitted_at
                FROM sampling_evidence e JOIN submissions s ON s.id=e.submission_id
                WHERE e.engine='bounded_crib_v1' AND e.outcome='match' AND s.compute_seconds>0""")
            con.execute("INSERT INTO calibration_match_meta(key,value) VALUES('backfilled_v1','1')")
        con.execute("CREATE INDEX IF NOT EXISTS ix_calibration_match_device_recent ON calibration_match_order(device_id,submitted_at DESC)")
        con.execute("""CREATE TRIGGER IF NOT EXISTS tr_calibration_evidence_insert
            AFTER INSERT ON sampling_evidence BEGIN
              DELETE FROM calibration_match_order WHERE submission_id=NEW.submission_id;
              INSERT INTO calibration_match_order(submission_id,device_id,submitted_at)
                SELECT NEW.submission_id,s.device_id,s.submitted_at FROM submissions s
                WHERE s.id=NEW.submission_id AND NEW.engine='bounded_crib_v1'
                  AND NEW.outcome='match' AND s.compute_seconds>0;
            END""")
        con.execute("""CREATE TRIGGER IF NOT EXISTS tr_calibration_evidence_update
            AFTER UPDATE OF submission_id,engine,outcome ON sampling_evidence BEGIN
              DELETE FROM calibration_match_order WHERE submission_id=OLD.submission_id;
              DELETE FROM calibration_match_order WHERE submission_id=NEW.submission_id;
              INSERT INTO calibration_match_order(submission_id,device_id,submitted_at)
                SELECT NEW.submission_id,s.device_id,s.submitted_at FROM submissions s
                WHERE s.id=NEW.submission_id AND NEW.engine='bounded_crib_v1'
                  AND NEW.outcome='match' AND s.compute_seconds>0;
            END""")
        con.execute("""CREATE TRIGGER IF NOT EXISTS tr_calibration_evidence_delete
            AFTER DELETE ON sampling_evidence BEGIN
              DELETE FROM calibration_match_order WHERE submission_id=OLD.submission_id;
            END""")
        # Refresh these definitions transactionally on upgrades as well as the
        # first install; IF NOT EXISTS would retain an older trigger body.
        con.execute('DROP TRIGGER IF EXISTS tr_calibration_submission_insert')
        con.execute('DROP TRIGGER IF EXISTS tr_calibration_submission_update')
        con.execute("""CREATE TRIGGER tr_calibration_submission_insert
            AFTER INSERT ON submissions BEGIN
              DELETE FROM calibration_match_order WHERE submission_id=NEW.id;
              INSERT OR REPLACE INTO calibration_match_order(submission_id,device_id,submitted_at)
                SELECT NEW.id,NEW.device_id,NEW.submitted_at FROM sampling_evidence e
                WHERE e.submission_id=NEW.id AND e.engine='bounded_crib_v1'
                  AND e.outcome='match' AND NEW.compute_seconds>0;
            END""")
        con.execute("""CREATE TRIGGER tr_calibration_submission_update
            AFTER UPDATE OF id,device_id,submitted_at,compute_seconds ON submissions BEGIN
              DELETE FROM calibration_match_order WHERE submission_id=OLD.id;
              DELETE FROM calibration_match_order WHERE submission_id=NEW.id;
              INSERT INTO calibration_match_order(submission_id,device_id,submitted_at)
                SELECT NEW.id,NEW.device_id,NEW.submitted_at FROM sampling_evidence e
                WHERE e.submission_id=NEW.id AND e.engine='bounded_crib_v1'
                  AND e.outcome='match' AND NEW.compute_seconds>0;
            END""")
        con.execute("""CREATE TRIGGER IF NOT EXISTS tr_calibration_submission_delete
            AFTER DELETE ON submissions BEGIN
              DELETE FROM calibration_match_order WHERE submission_id=OLD.id;
            END""")
        con.commit()
    except BaseException:
        if con.in_transaction:con.rollback()
        raise

def init_db():
    con=db()
    con.execute("pragma journal_mode=WAL")
    con.executescript("""
    create table if not exists contributors(
      id text primary key, display_name text not null, public_credit integer not null default 1,
      join_key_hash text not null unique, dashboard_token_hash text not null unique, created real not null);
    create table if not exists devices(
      id text primary key, contributor_id text not null references contributors(id),
      label text not null, token_hash text not null unique, enabled integer not null default 1,
      last_seen real, meta_json text not null default '{}', created real not null);
    create table if not exists campaigns(
      id text primary key, name text not null, version text not null, status text not null,
      created real not null, notes text not null default '');
    """)
    con.executescript("""
    create table if not exists segments(
      id text primary key, campaign_id text not null references campaigns(id),
      label text not null, engine text not null, start_unit integer not null,
      end_unit integer not null, next_unit integer not null, chunk_size integer not null,
      priority integer not null default 100, config_json text not null default '{}');
    create table if not exists leases(
      id text primary key, segment_id text not null references segments(id),
      device_id text not null references devices(id), start_unit integer not null,
      end_unit integer not null, work_token text not null, status text not null,
      leased_at real not null, expires_at real not null, completed_at real);
    create index if not exists ix_leases_device on leases(device_id,status);
    create table if not exists requeue(
      segment_id text not null, start_unit integer not null, end_unit integer not null,
      queued_at real not null, primary key(segment_id,start_unit,end_unit));
    create table if not exists done_ranges(
      segment_id text not null, start_unit integer not null, end_unit integer not null,
      lease_id text not null, device_id text not null, completed_at real not null,
      result_json text not null, primary key(segment_id,start_unit,end_unit));
    """)
    con.executescript("""
    create table if not exists contributions(
      contributor_id text not null, device_id text not null,
      units integer not null default 0, jobs integer not null default 0,
      compute_seconds real not null default 0, candidates integer not null default 0,
      primary key(contributor_id,device_id));
    create table if not exists validations(
      segment_id text not null, start_unit integer not null, end_unit integer not null,
      base_required integer not null, target_replicas integer not null, max_replicas integer not null,
      status text not null default 'pending', canonical_fingerprint text,
      created real not null, verified_at real,
      primary key(segment_id,start_unit,end_unit));
    create table if not exists submissions(
      id text primary key, lease_id text not null unique, segment_id text not null,
      start_unit integer not null, end_unit integer not null, device_id text not null,
      contributor_id text not null, fingerprint text not null, result_json text not null,
      compute_seconds real not null, candidate_count integer not null,
      status text not null default 'pending', credited integer not null default 0,
      submitted_at real not null);
    """)
    con.executescript("""
    create index if not exists ix_sub_range on submissions(segment_id,start_unit,end_unit,status);
    create index if not exists ix_submissions_recent on submissions(submitted_at desc);
    create index if not exists ix_submissions_device_recent on submissions(device_id,submitted_at desc);
    create index if not exists ix_validation_segment_pending on validations(segment_id,status);
    create table if not exists audit_log(
      id integer primary key autoincrement, created real not null, kind text not null,
      device_id text, detail_json text not null default '{}');
    create index if not exists ix_audit_created on audit_log(created);
    create table if not exists registration_nonces(
      nonce text primary key, expires real not null, used integer not null default 0);
    create index if not exists ix_registration_expiry on registration_nonces(expires);
    """)
    ensure_column(con,"devices","settings_json","text not null default '{}'")
    ensure_column(con,"devices","capabilities_json","text not null default '[]'")
    ensure_column(con,"devices","trust_score","real not null default 1.0")
    ensure_column(con,"devices","quarantined","integer not null default 0")
    ensure_column(con,"devices","valid_jobs","integer not null default 0")
    ensure_column(con,"devices","invalid_jobs","integer not null default 0")
    ensure_column(con,"submissions","worker_version","text not null default ''")
    ensure_column(con,"done_ranges","verification_status","text not null default 'verified'")
    con.execute("create index if not exists ix_done_verification on done_ranges(verification_status,segment_id,start_unit,end_unit)")
    trusted_sampling.init_schema(con)
    init_calibration_match_order(con)
    # Selection walks ordered metadata instead of sorting the entire backlog.
    con.execute("CREATE INDEX IF NOT EXISTS ix_validation_selection_order ON validations(segment_id,status,created,start_unit,end_unit)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_sampling_selected_audit ON sampling_decisions(reason,submission_id) WHERE reason IN ('random_audit','burst_limit')")
    con.execute("CREATE INDEX IF NOT EXISTS ix_submission_negative_identity ON submissions(device_id,worker_version,segment_id,start_unit,end_unit,id) WHERE candidate_count=0 AND worker_version!=''")
    con.execute("CREATE INDEX IF NOT EXISTS ix_submission_pending_segment_contributor ON submissions(segment_id,contributor_id) WHERE status='pending'")
    # Selection needs only outstanding audit ranges and identities which have
    # produced a negative result. Rebuilding both from millions of historical
    # rows for every lease blocks otherwise idle workers for seconds.
    con.execute("""CREATE TABLE IF NOT EXISTS selection_audit_queue(
        submission_id TEXT PRIMARY KEY,segment_id TEXT NOT NULL,
        start_unit INTEGER NOT NULL,end_unit INTEGER NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS selection_negative_identities(
        device_id TEXT NOT NULL,worker_version TEXT NOT NULL,segment_id TEXT NOT NULL,
        PRIMARY KEY(device_id,worker_version,segment_id))""")
    con.execute("CREATE TABLE IF NOT EXISTS selection_cache_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    con.executescript("""
      CREATE TRIGGER IF NOT EXISTS tr_selection_audit_insert AFTER INSERT ON sampling_decisions
      WHEN NEW.action='verify' AND NEW.reason IN ('random_audit','burst_limit')
      BEGIN
        INSERT OR IGNORE INTO selection_audit_queue(submission_id,segment_id,start_unit,end_unit)
        SELECT NEW.submission_id,s.segment_id,s.start_unit,s.end_unit FROM submissions s
        WHERE s.id=NEW.submission_id AND NOT EXISTS(
          SELECT 1 FROM sampling_evidence e WHERE e.submission_id=NEW.submission_id);
      END;
      CREATE TRIGGER IF NOT EXISTS tr_selection_audit_resolved AFTER INSERT ON sampling_evidence
      BEGIN DELETE FROM selection_audit_queue WHERE submission_id=NEW.submission_id; END;
      CREATE TRIGGER IF NOT EXISTS tr_selection_audit_decision_update
      AFTER UPDATE OF submission_id,action,reason ON sampling_decisions
      BEGIN
        DELETE FROM selection_audit_queue WHERE submission_id=OLD.submission_id;
        INSERT OR IGNORE INTO selection_audit_queue(submission_id,segment_id,start_unit,end_unit)
        SELECT NEW.submission_id,s.segment_id,s.start_unit,s.end_unit FROM submissions s
        WHERE s.id=NEW.submission_id AND NEW.action='verify'
          AND NEW.reason IN ('random_audit','burst_limit')
          AND NOT EXISTS(SELECT 1 FROM sampling_evidence e WHERE e.submission_id=NEW.submission_id);
      END;
      CREATE TRIGGER IF NOT EXISTS tr_selection_audit_decision_deleted AFTER DELETE ON sampling_decisions
      BEGIN DELETE FROM selection_audit_queue WHERE submission_id=OLD.submission_id; END;
      CREATE TRIGGER IF NOT EXISTS tr_selection_audit_evidence_deleted AFTER DELETE ON sampling_evidence
      BEGIN
        INSERT OR IGNORE INTO selection_audit_queue(submission_id,segment_id,start_unit,end_unit)
        SELECT d.submission_id,s.segment_id,s.start_unit,s.end_unit FROM sampling_decisions d
        JOIN submissions s ON s.id=d.submission_id WHERE d.submission_id=OLD.submission_id
          AND d.action='verify' AND d.reason IN ('random_audit','burst_limit')
          AND NOT EXISTS(SELECT 1 FROM sampling_evidence e WHERE e.submission_id=OLD.submission_id);
      END;
      CREATE TRIGGER IF NOT EXISTS tr_selection_audit_evidence_update
      AFTER UPDATE OF submission_id ON sampling_evidence
      BEGIN
        DELETE FROM selection_audit_queue WHERE submission_id=NEW.submission_id;
        INSERT OR IGNORE INTO selection_audit_queue(submission_id,segment_id,start_unit,end_unit)
        SELECT d.submission_id,s.segment_id,s.start_unit,s.end_unit FROM sampling_decisions d
        JOIN submissions s ON s.id=d.submission_id WHERE d.submission_id=OLD.submission_id
          AND d.action='verify' AND d.reason IN ('random_audit','burst_limit')
          AND NOT EXISTS(SELECT 1 FROM sampling_evidence e WHERE e.submission_id=OLD.submission_id);
      END;
      CREATE TRIGGER IF NOT EXISTS tr_selection_submission_deleted AFTER DELETE ON submissions
      BEGIN
        DELETE FROM selection_audit_queue WHERE submission_id=OLD.id;
        DELETE FROM selection_negative_identities WHERE device_id=OLD.device_id
          AND worker_version=OLD.worker_version AND segment_id=OLD.segment_id
          AND NOT EXISTS(SELECT 1 FROM submissions s INDEXED BY ix_submission_negative_identity
            WHERE s.device_id=OLD.device_id AND s.worker_version=OLD.worker_version
              AND s.segment_id=OLD.segment_id AND s.candidate_count=0 AND s.worker_version!='');
      END;
      CREATE TRIGGER IF NOT EXISTS tr_selection_negative_insert AFTER INSERT ON submissions
      WHEN NEW.candidate_count=0 AND NEW.worker_version!=''
      BEGIN
        INSERT OR IGNORE INTO selection_negative_identities(device_id,worker_version,segment_id)
        VALUES(NEW.device_id,NEW.worker_version,NEW.segment_id);
      END;
      CREATE TRIGGER IF NOT EXISTS tr_selection_audit_submission_insert AFTER INSERT ON submissions
      BEGIN
        INSERT OR IGNORE INTO selection_audit_queue(submission_id,segment_id,start_unit,end_unit)
        SELECT NEW.id,NEW.segment_id,NEW.start_unit,NEW.end_unit FROM sampling_decisions d
        WHERE d.submission_id=NEW.id AND d.action='verify'
          AND d.reason IN ('random_audit','burst_limit')
          AND NOT EXISTS(SELECT 1 FROM sampling_evidence e WHERE e.submission_id=NEW.id);
      END;
      CREATE TRIGGER IF NOT EXISTS tr_selection_submission_update
      AFTER UPDATE OF id,device_id,worker_version,segment_id,start_unit,end_unit,candidate_count ON submissions
      BEGIN
        DELETE FROM selection_audit_queue WHERE submission_id=OLD.id;
        INSERT OR IGNORE INTO selection_audit_queue(submission_id,segment_id,start_unit,end_unit)
        SELECT NEW.id,NEW.segment_id,NEW.start_unit,NEW.end_unit FROM sampling_decisions d
        WHERE d.submission_id=NEW.id AND d.action='verify'
          AND d.reason IN ('random_audit','burst_limit')
          AND NOT EXISTS(SELECT 1 FROM sampling_evidence e WHERE e.submission_id=NEW.id);
        DELETE FROM selection_negative_identities WHERE device_id=OLD.device_id
          AND worker_version=OLD.worker_version AND segment_id=OLD.segment_id
          AND NOT EXISTS(SELECT 1 FROM submissions s INDEXED BY ix_submission_negative_identity
            WHERE s.device_id=OLD.device_id AND s.worker_version=OLD.worker_version
              AND s.segment_id=OLD.segment_id AND s.candidate_count=0 AND s.worker_version!='');
        INSERT OR IGNORE INTO selection_negative_identities(device_id,worker_version,segment_id)
        SELECT NEW.device_id,NEW.worker_version,NEW.segment_id
        WHERE NEW.candidate_count=0 AND NEW.worker_version!='';
      END;
    """)
    if not con.execute("SELECT 1 FROM selection_cache_meta WHERE key='v1_backfilled'").fetchone():
        con.execute('SAVEPOINT selection_cache_backfill')
        try:
            con.execute("""INSERT OR IGNORE INTO selection_audit_queue
              SELECT d.submission_id,s.segment_id,s.start_unit,s.end_unit
              FROM sampling_decisions d INDEXED BY ix_sampling_selected_audit
              JOIN submissions s ON s.id=d.submission_id
              WHERE d.reason IN ('random_audit','burst_limit') AND d.action='verify'
                AND NOT EXISTS(SELECT 1 FROM sampling_evidence e WHERE e.submission_id=d.submission_id)""")
            con.execute("""INSERT OR IGNORE INTO selection_negative_identities
              SELECT DISTINCT device_id,worker_version,segment_id
              FROM submissions INDEXED BY ix_submission_negative_identity
              WHERE candidate_count=0 AND worker_version!=''""")
            con.execute("INSERT INTO selection_cache_meta VALUES('v1_backfilled','1')")
            con.execute('RELEASE selection_cache_backfill')
        except BaseException:
            con.execute('ROLLBACK TO selection_cache_backfill')
            con.execute('RELEASE selection_cache_backfill')
            raise
    # A bounded-only contributor cannot independently validate its own work.
    # The exact source-integrity flag makes the fast exclusion fail closed if a
    # manual import ever introduces a pending validation without a pending
    # source submission. It is populated once and invalidated transactionally.
    con.executescript("""
      CREATE TRIGGER IF NOT EXISTS tr_selection_source_validation_insert AFTER INSERT ON validations
      WHEN NEW.status='pending' AND (SELECT engine FROM segments WHERE id=NEW.segment_id)='bounded_crib_v1'
       AND NOT EXISTS(SELECT 1 FROM submissions s WHERE s.segment_id=NEW.segment_id
         AND s.start_unit=NEW.start_unit AND s.end_unit=NEW.end_unit AND s.status='pending')
      BEGIN UPDATE selection_cache_meta SET value='0' WHERE key='pending_sources_bounded_v1'; END;
      CREATE TRIGGER IF NOT EXISTS tr_selection_source_validation_update AFTER UPDATE OF status ON validations
      WHEN NEW.status='pending' AND OLD.status!='pending'
       AND (SELECT engine FROM segments WHERE id=NEW.segment_id)='bounded_crib_v1'
       AND NOT EXISTS(SELECT 1 FROM submissions s WHERE s.segment_id=NEW.segment_id
         AND s.start_unit=NEW.start_unit AND s.end_unit=NEW.end_unit AND s.status='pending')
      BEGIN UPDATE selection_cache_meta SET value='0' WHERE key='pending_sources_bounded_v1'; END;
      CREATE TRIGGER IF NOT EXISTS tr_selection_source_validation_keys_update
      AFTER UPDATE OF segment_id,start_unit,end_unit ON validations
      WHEN NEW.status='pending' AND (SELECT engine FROM segments WHERE id=NEW.segment_id)='bounded_crib_v1'
       AND NOT EXISTS(SELECT 1 FROM submissions s WHERE s.segment_id=NEW.segment_id
         AND s.start_unit=NEW.start_unit AND s.end_unit=NEW.end_unit AND s.status='pending')
      BEGIN UPDATE selection_cache_meta SET value='0' WHERE key='pending_sources_bounded_v1'; END;
      CREATE TRIGGER IF NOT EXISTS tr_selection_source_segment_engine_update
      AFTER UPDATE OF engine ON segments
      WHEN NEW.engine='bounded_crib_v1' AND OLD.engine!=NEW.engine
       AND EXISTS(SELECT 1 FROM validations v WHERE v.segment_id=NEW.id AND v.status='pending'
         AND NOT EXISTS(SELECT 1 FROM submissions s WHERE s.segment_id=v.segment_id
           AND s.start_unit=v.start_unit AND s.end_unit=v.end_unit AND s.status='pending'))
      BEGIN UPDATE selection_cache_meta SET value='0' WHERE key='pending_sources_bounded_v1'; END;
      CREATE TRIGGER IF NOT EXISTS tr_selection_source_submission_delete AFTER DELETE ON submissions
      WHEN OLD.status='pending' AND (SELECT engine FROM segments WHERE id=OLD.segment_id)='bounded_crib_v1'
       AND EXISTS(SELECT 1 FROM validations v WHERE v.segment_id=OLD.segment_id
         AND v.start_unit=OLD.start_unit AND v.end_unit=OLD.end_unit AND v.status='pending')
       AND NOT EXISTS(SELECT 1 FROM submissions s WHERE s.segment_id=OLD.segment_id
         AND s.start_unit=OLD.start_unit AND s.end_unit=OLD.end_unit AND s.status='pending')
      BEGIN UPDATE selection_cache_meta SET value='0' WHERE key='pending_sources_bounded_v1'; END;
      CREATE TRIGGER IF NOT EXISTS tr_selection_source_submission_update
      AFTER UPDATE OF status,segment_id,start_unit,end_unit ON submissions
      WHEN OLD.status='pending' AND (SELECT engine FROM segments WHERE id=OLD.segment_id)='bounded_crib_v1'
       AND EXISTS(SELECT 1 FROM validations v WHERE v.segment_id=OLD.segment_id
         AND v.start_unit=OLD.start_unit AND v.end_unit=OLD.end_unit AND v.status='pending')
       AND NOT EXISTS(SELECT 1 FROM submissions s WHERE s.segment_id=OLD.segment_id
         AND s.start_unit=OLD.start_unit AND s.end_unit=OLD.end_unit AND s.status='pending')
      BEGIN UPDATE selection_cache_meta SET value='0' WHERE key='pending_sources_bounded_v1'; END;
    """)
    if not con.execute("SELECT 1 FROM selection_cache_meta WHERE key='pending_sources_bounded_v1'").fetchone():
        intact=not con.execute("""SELECT 1 FROM validations v JOIN segments seg ON seg.id=v.segment_id
          WHERE v.status='pending' AND seg.engine='bounded_crib_v1'
          AND NOT EXISTS(SELECT 1 FROM submissions s WHERE s.segment_id=v.segment_id
            AND s.start_unit=v.start_unit AND s.end_unit=v.end_unit AND s.status='pending') LIMIT 1""").fetchone()
        con.execute("INSERT INTO selection_cache_meta(key,value) VALUES('pending_sources_bounded_v1',?)",('1' if intact else '0',))
    ensure_column(con,"leases","purpose","text not null default 'primary'")
    con.execute("""create table if not exists server_verifications(
      segment_id text not null, start_unit integer not null, end_unit integer not null,
      status text not null, updated real not null, fingerprint text,
      compute_seconds real not null default 0, detail text not null default '',
      primary key(segment_id,start_unit,end_unit))""")
    if load_cfg().get('long_work_blocks_enabled',False):work_blocks.init_schema(con)
    con.close()

def audit(con,kind,device_id=None,**detail):
    con.execute("insert into audit_log(created,kind,device_id,detail_json) values(?,?,?,?)",
                (now(),kind,device_id,json.dumps(detail,separators=(",",":"))))

def new_registration_challenge(con):
    t=now();con.execute("delete from registration_nonces where expires<?",(t-60,))
    nonce=secrets.token_urlsafe(18);expires=t+300
    con.execute("insert into registration_nonces(nonce,expires,used) values(?,?,0)",(nonce,expires))
    bits=max(12,min(24,int(load_cfg().get("registration_pow_bits",18))))
    return {"nonce":nonce,"difficulty_bits":bits,"expires_at":expires}

def verify_registration_pow(con,b):
    nonce=str(b.get("pow_nonce",""));counter=str(b.get("pow_counter",""))
    row=con.execute("select expires,used from registration_nonces where nonce=?",(nonce,)).fetchone()
    if not row or row["used"] or row["expires"]<now():return False
    bits=max(12,min(24,int(load_cfg().get("registration_pow_bits",18))))
    digest=hashlib.sha256((nonce+":"+counter).encode("utf-8")).digest()
    if (int.from_bytes(digest,"big")>>(256-bits))!=0:return False
    cur=con.execute("update registration_nonces set used=1 where nonce=? and used=0",(nonce,))
    return cur.rowcount==1
def normalize_settings(v):
    v=v if isinstance(v,dict) else {}
    cpu=max(0,min(100,int(v.get("cpu_percent",50))))
    gpu=max(0,min(100,int(v.get("gpu_percent",0))))
    return {"cpu_percent":cpu,"gpu_percent":gpu,
            "allow_cpu":bool(v.get("allow_cpu",cpu>0)),
            "allow_gpu":bool(v.get("allow_gpu",gpu>0))}

def sanitize_meta(meta):
    meta=meta if isinstance(meta,dict) else {}
    gpus=[]
    for g in (meta.get("gpus") or [])[:4]:
        if not isinstance(g,dict): continue
        gpus.append({"vendor":str(g.get("vendor",""))[:32],
                     "name":str(g.get("name",""))[:96],
                     "memory_mb":max(0,int(g.get("memory_mb",0) or 0))})
    out={"worker_version":str(meta.get("worker_version",""))[:32],
         "platform":str(meta.get("platform",""))[:128],
         "machine":str(meta.get("machine",""))[:32],
         "cpu_count":max(1,min(1024,int(meta.get("cpu_count",1) or 1))),
         "gpus":gpus,
         "capabilities":[x for x in (meta.get("capabilities") or []) if x in {"cpu","cuda","rocm","gpu","opencl","bounded_crib_v1"}]}
    if "supported_engines" in meta:
        engines=meta.get("supported_engines")
        out["supported_engines"]=[x for x in engines if x in {"portable_event_v1","bounded_crib_v1"}] if isinstance(engines,list) else []
    if isinstance(meta.get("effective_settings"),dict):
        out["effective_settings"]=normalize_settings(meta["effective_settings"])
    if "cpu_threads_effective" in meta:
        out["cpu_threads_effective"]=max(0,min(1024,int(meta.get("cpu_threads_effective",0) or 0)))
    return out

def capabilities_from_meta(meta):
    meta=sanitize_meta(meta)
    caps={"cpu"}
    for x in meta.get("capabilities",[]) or []:
        if x in {"cpu","cuda","rocm","gpu","opencl","bounded_crib_v1"}: caps.add(x)
    if meta.get("gpus"):
        caps.add("gpu")
        if any(str(g.get("vendor","")).lower()=="nvidia" for g in meta["gpus"] if isinstance(g,dict)):
            caps.add("cuda")
    return sorted(caps)

def device_from_token(con,token):
    if not token:return None
    return con.execute("""select d.*,c.display_name,c.public_credit from devices d
                          join contributors c on c.id=d.contributor_id
                          where d.token_hash=?""",(sha(token),)).fetchone()

def parse_json(v,default):
    try:return json.loads(v) if v else default
    except Exception:return default

def version_tuple(value):
    parts=[]
    for raw in str(value or "").strip().split("."):
        digits=""
        for ch in raw:
            if ch.isdigit():digits+=ch
            else:break
        parts.append(int(digits or 0))
    while len(parts)<3:parts.append(0)
    return tuple(parts[:4])

def worker_update_required(dev):
    cfg=load_cfg()
    meta=parse_json(dev["meta_json"],{})
    key="min_android_worker_version" if str(meta.get("platform","")).lower().startswith("android") else "min_worker_version"
    minimum=str(cfg.get(key,cfg.get("min_worker_version","")) or "").strip()
    if not minimum:return False,""
    current=str(meta.get("worker_version","") or "").strip()
    if not current:return True,minimum
    return version_tuple(current)<version_tuple(minimum),minimum

def update_device_runtime(con,dev,body):
    # Most short block/status/upload requests need no SQL write at all. The
    # authenticated row was fetched immediately before this call; a second
    # SQLite predicate closes the race when another thread refreshes it first.
    # Never move a timestamp backwards.
    seen_at=now()
    refresh_before=seen_at-5
    prior_seen=dev['last_seen'] if 'last_seen' in dev.keys() else None
    supplied=body.get("meta") if isinstance(body,dict) else None
    if isinstance(supplied,dict) and supplied:
        meta=sanitize_meta(supplied)
        caps=capabilities_from_meta(meta)
        meta_json=json.dumps(meta,separators=(",",":"))
        capabilities_json=json.dumps(caps,separators=(",",":"))
        if (prior_seen is not None and prior_seen>refresh_before
                and 'meta_json' in dev.keys() and dev['meta_json']==meta_json
                and 'capabilities_json' in dev.keys() and dev['capabilities_json']==capabilities_json):
            return
        con.execute("""update devices set
                       last_seen=case when last_seen is null or last_seen<? then ? else last_seen end,
                       meta_json=?,capabilities_json=?
                       where id=? and (last_seen is null or last_seen<=?
                           or meta_json is not ? or capabilities_json is not ?)""",
                    (seen_at,seen_at,meta_json,capabilities_json,dev["id"],
                     refresh_before,meta_json,capabilities_json))
    else:
        if prior_seen is not None and prior_seen>refresh_before:
            return
        con.execute("""update devices set last_seen=? where id=?
                       and (last_seen is null or last_seen<=?)""",
                    (seen_at,dev["id"],refresh_before))

def trust_penalty(con,device_id,severe=False,reason="invalid"):
    delta=0.35 if severe else 0.15
    con.execute("""update devices set invalid_jobs=invalid_jobs+1,
                  trust_score=max(0.0,trust_score-?) where id=?""",(delta,device_id))
    row=con.execute("select trust_score,invalid_jobs from devices where id=?",(device_id,)).fetchone()
    if row and (row["trust_score"]<0.5 or row["invalid_jobs"]>=3):
        con.execute("update devices set quarantined=1,enabled=0 where id=?",(device_id,))
        audit(con,"device_quarantined",device_id,reason=reason,trust=row["trust_score"])
    else:audit(con,"trust_penalty",device_id,reason=reason,delta=delta)

def trust_reward(con,device_id):
    con.execute("""update devices set valid_jobs=valid_jobs+1,
                  trust_score=min(1.0,trust_score+0.01) where id=?""",(device_id,))

def expire_leases(con):
    t=now()
    rows=con.execute("""select id,segment_id,start_unit,end_unit,purpose from leases
                        where status='leased' and purpose!='block_receipt' and expires_at<?""",(t,)).fetchall()
    for r in rows:
        con.execute("update leases set status='expired' where id=?",(r["id"],))
        if r["purpose"]=="primary":
            done=con.execute("""select 1 from done_ranges where segment_id=? and start_unit=? and end_unit=?""",
                             (r["segment_id"],r["start_unit"],r["end_unit"])).fetchone()
            if not done:
                con.execute("""insert or ignore into requeue(segment_id,start_unit,end_unit,queued_at)
                               values(?,?,?,?)""",(r["segment_id"],r["start_unit"],r["end_unit"],t))
def segment_config(row):
    return parse_json(row["config_json"],{})

def device_eligible(dev,seg):
    if not dev["enabled"] or dev["quarantined"]:return False,None,0
    meta=parse_json(dev["meta_json"],{}) if "meta_json" in dev.keys() else {}
    supported=meta.get("supported_engines")
    if supported is not None and (not isinstance(supported,list) or seg["engine"] not in supported):
        return False,None,0
    # Android clients before engine negotiation must update instead of receiving legacy work.
    if supported is None and str(meta.get("platform","")).startswith("Android"):
        return False,None,0
    settings=normalize_settings(parse_json(dev["settings_json"],{}))
    caps=set(parse_json(dev["capabilities_json"],["cpu"]))
    # Engine support is mandatory even if an imported segment omits requires.
    if seg['engine']=='bounded_crib_v1' and 'bounded_crib_v1' not in caps:
        return False,None,0
    cfg=segment_config(seg); req=set(cfg.get("requires",["cpu"]))
    if not req.issubset(caps):return False,None,0
    if seg["engine"]=="portable_event_v1":
        use_cpu=settings["allow_cpu"] and settings["cpu_percent"]>0
        use_gpu="opencl" in caps and settings["allow_gpu"] and settings["gpu_percent"]>0
        if use_gpu:return True,"hybrid" if use_cpu else "gpu",settings["gpu_percent"]
        if use_cpu:return True,"cpu",settings["cpu_percent"]
        return False,None,0
    if "cuda" in req or "gpu" in req or "rocm" in req:
        if not settings["allow_gpu"] or settings["gpu_percent"]<=0:return False,None,0
        return True,"gpu",settings["gpu_percent"]
    if not settings["allow_cpu"] or settings["cpu_percent"]<=0:return False,None,0
    return True,"cpu",settings["cpu_percent"]

def make_lease(con,dev,seg,start,end,purpose,ttl):
    lid=rid("lease"); work=secrets.token_urlsafe(18); t=now()
    con.execute("""insert into leases(id,segment_id,device_id,start_unit,end_unit,work_token,status,
                  leased_at,expires_at,purpose) values(?,?,?,?,?,?,'leased',?,?,?)""",
                (lid,seg["id"],dev["id"],start,end,work,t,t+ttl,purpose))
    row=con.execute("""select l.*,s.engine,s.label,s.config_json from leases l
                       join segments s on s.id=l.segment_id where l.id=?""",(lid,)).fetchone()
    ok,resource,pct=device_eligible(dev,seg)
    return lease_obj(row,resource,pct)

def lease_obj(r,resource,pct):
    return {"id":r["id"],"segment_id":r["segment_id"],"segment_label":r["label"],
            "engine":r["engine"],"start_unit":r["start_unit"],"end_unit":r["end_unit"],
            "work_token":r["work_token"],"expires_at":r["expires_at"],"purpose":r["purpose"],
            "resource_class":resource,"resource_percent":pct,
            "config":parse_json(r["config_json"],{})}
def validation_priority_sql():
    # Selected audits unblock sampled work. Query trust evidence through the
    # identity index instead of rebuilding a full evidence-count CTE per batch.
    return """case
      when exists(select 1 from submissions t INDEXED BY ix_sub_range cross join sampling_decisions d on d.submission_id=t.id
        where t.segment_id=v.segment_id and t.start_unit=v.start_unit and t.end_unit=v.end_unit
        and d.reason in ('random_audit','burst_limit') and not exists(
          select 1 from sampling_evidence e where e.submission_id=t.id)) then 0
      when exists(select 1 from submissions t where t.segment_id=v.segment_id
        and t.start_unit=v.start_unit and t.end_unit=v.end_unit and t.worker_version!=''
        and t.candidate_count=0
        and not exists(select 1 from sampling_evidence bad
          where bad.device_id=t.device_id and bad.outcome='mismatch')
        and coalesce((select st.independent_verified from sampling_state st
          where st.device_id=t.device_id and st.engine=s.engine and st.worker_version=t.worker_version),
          (select count(*) from sampling_evidence e where e.device_id=t.device_id
          and e.engine=s.engine and e.worker_version=t.worker_version and e.outcome='match'))<100) then 1
      else 2 end"""


def _has_validation_block_claim_schema(con):
    """Account for existing claims even if the long-block feature is disabled."""
    block_columns={row[1] for row in con.execute('PRAGMA table_info(work_blocks)')}
    if 'purpose' not in block_columns:
        return False
    receipt_columns={row[1] for row in con.execute('PRAGMA table_info(block_receipts)')}
    if not {'id','segment_id','start_unit','end_unit','status','expires_at'}.issubset(block_columns) or not {'block_id','unit','promoted_at','verification_status'}.issubset(receipt_columns):
        raise RuntimeError('Incomplete validation block claim schema')
    return True


def validation_candidates(con,dev):
    if load_cfg().get('volunteer_validation_enabled',True) is False:
        return
    priority=validation_priority_sql() if load_cfg().get('trusted_sampling_enabled',False) else '(0+0)'
    meta=parse_json(dev["meta_json"],{}) if "meta_json" in dev.keys() else {}
    supported=meta.get("supported_engines")
    params=[]
    engine_clause=""
    if supported is not None:
        if not isinstance(supported,list) or not supported or any(not isinstance(x,str) for x in supported):
            return
        if supported==['bounded_crib_v1']:
            intact=con.execute("SELECT value FROM selection_cache_meta WHERE key='pending_sources_bounded_v1'").fetchone()
            if intact and intact[0]=='1':
                bounded=con.execute("""SELECT s.id FROM segments s JOIN campaigns c ON c.id=s.campaign_id
                    WHERE c.status='running' AND s.engine='bounded_crib_v1'""").fetchall()
                own=dev['contributor_id'];foreign=False
                for segment in bounded:
                    for comparison in ('<','>'):
                        if con.execute(f"""SELECT 1 FROM submissions INDEXED BY ix_submission_pending_segment_contributor
                            WHERE segment_id=? AND status='pending' AND contributor_id{comparison}? LIMIT 1""",
                            (segment['id'],own)).fetchone():
                            foreign=True;break
                    if foreign:break
                if not foreign:return
        engine_clause=" and s.engine in ("+",".join("?" for _ in supported)+")"
        params.extend(supported)
    engine_param_count=len(params)
    selected_at=now()
    # A legacy primary-only work_blocks table has no purpose column; a fully
    # migrated table can still contain live claims after the flag is disabled.
    has_block_claims=_has_validation_block_claim_schema(con)
    params.extend((dev['contributor_id'],dev['contributor_id']))
    if has_block_claims:params.extend((selected_at,dev['contributor_id'],dev['contributor_id']))
    params.append(selected_at-15)
    if has_block_claims:params.append(selected_at)
    # The two claim sets are disjoint: a received unit is no longer an
    # unreceived reservation. Seek the tiny reserved set separately from
    # pending durable receipts; never scan all historical submitted blocks.
    block_own_clause="""and not exists(select 1 from work_blocks ownb INDEXED BY ix_work_blocks_validation_reserved_claim
                            join devices bd on bd.id=ownb.device_id
                            where ownb.segment_id=v.segment_id and ownb.purpose='validation'
                              and ownb.status='reserved' and ownb.start_unit<=v.start_unit
                              and ownb.end_unit>=v.end_unit and ownb.expires_at>?
                              and bd.contributor_id=?
                              and not exists(select 1 from block_receipts br
                                  where br.block_id=ownb.id and br.unit=v.start_unit))
                         and not exists(select 1 from block_receipts br INDEXED BY ix_block_receipts_pending_unit
                            cross join work_blocks ownb on ownb.id=br.block_id
                            join devices bd on bd.id=ownb.device_id
                            where br.unit=v.start_unit and br.promoted_at is null
                              and br.verification_status='pending'
                              and ownb.segment_id=v.segment_id and ownb.purpose='validation'
                              and ownb.start_unit<=v.start_unit and ownb.end_unit>=v.end_unit
                              and bd.contributor_id=?)""" if has_block_claims else ''
    block_count_clause="""+ (select count(*) from work_blocks ab INDEXED BY ix_work_blocks_validation_reserved_claim
                              where ab.segment_id=v.segment_id
                              and ab.purpose='validation' and ab.status='reserved'
                              and ab.start_unit<=v.start_unit and ab.end_unit>=v.end_unit
                              and ab.expires_at>?
                              and not exists(select 1 from block_receipts br
                                  where br.block_id=ab.id and br.unit=v.start_unit))
                          + (select count(*) from block_receipts br INDEXED BY ix_block_receipts_pending_unit
                              cross join work_blocks ab on ab.id=br.block_id
                              where br.unit=v.start_unit and br.promoted_at is null
                                and br.verification_status='pending'
                                and ab.segment_id=v.segment_id and ab.purpose='validation'
                                and ab.start_unit<=v.start_unit and ab.end_unit>=v.end_unit)""" if has_block_claims else ''
    # Filter incompatible engines before evaluating per-range replica/audit
    # subqueries. This matters when a CPU-only backlog dominates the queue.
    validation_from=('segments s cross join validations v on s.id=v.segment_id'
                     if supported is not None and len(supported)==1
                     else 'validations v join segments s on s.id=v.segment_id')
    base=f"""select s.*,v.start_unit v_start,v.end_unit v_end,
                        v.target_replicas v_target,v.max_replicas v_max,v.created v_created
                        from {validation_from}
                        join campaigns c on c.id=s.campaign_id
                        where v.status='pending' and c.status='running'{engine_clause}
                        and not exists(select 1 from submissions own
                            where own.segment_id=v.segment_id and own.start_unit=v.start_unit
                              and own.end_unit=v.end_unit and own.contributor_id=?)
                        and not exists(select 1 from leases al join devices ad on ad.id=al.device_id
                            where al.segment_id=v.segment_id and al.start_unit=v.start_unit
                              and al.end_unit=v.end_unit and al.status='leased' and ad.contributor_id=?)
                        {block_own_clause}
                        and not exists(select 1 from server_verifications sv
                            where sv.segment_id=v.segment_id and sv.start_unit=v.start_unit
                              and sv.end_unit=v.end_unit and sv.status='running' and sv.updated>?)
                        and ((select count(*) from submissions p where p.segment_id=v.segment_id
                              and p.start_unit=v.start_unit and p.end_unit=v.end_unit)
                          + case when exists(select 1 from server_verifications sd
                              where sd.segment_id=v.segment_id and sd.start_unit=v.start_unit
                                and sd.end_unit=v.end_unit and sd.status='done') then 1 else 0 end
                          + (select count(*) from leases av where av.segment_id=v.segment_id
                              and av.start_unit=v.start_unit and av.end_unit=v.end_unit
                              and av.status='leased' and av.purpose='validation')
                          {block_count_clause}) < v.target_replicas
"""
    def ordered_rows():
        sampling=load_cfg().get('trusted_sampling_enabled',False)
        order=' order by s.priority,v.created,v.segment_id,v.start_unit,v.end_unit'
        if sampling:
            # Start with selected audit metadata, not every pending range.
            audit_keys="""WITH selected AS MATERIALIZED (
                SELECT DISTINCT segment_id,start_unit,end_unit FROM selection_audit_queue) """
            keyed='selected k CROSS JOIN validations v ON v.segment_id=k.segment_id AND v.start_unit=k.start_unit AND v.end_unit=k.end_unit CROSS JOIN segments s ON s.id=v.segment_id'
            key_base=base.split('and not exists(select 1 from leases al')[0]
            key_params=params[:engine_param_count+1]
            query=audit_keys+key_base.replace(validation_from,keyed)+order
            cursor=con.execute(query,key_params)
            try:
                for row in cursor:yield row,True
            finally:cursor.close()
            # DISTINCT uses a covering identity index; evaluate reputation once
            # per identity/segment, then seek only its negative submissions.
            probation_keys="""WITH identities AS MATERIALIZED (
                SELECT device_id,worker_version,segment_id FROM selection_negative_identities),
              probation AS MATERIALIZED (
                SELECT i.* FROM identities i JOIN segments ps ON ps.id=i.segment_id
                WHERE NOT EXISTS(SELECT 1 FROM sampling_evidence bad WHERE bad.device_id=i.device_id AND bad.outcome='mismatch')
                AND COALESCE((SELECT st.independent_verified FROM sampling_state st WHERE st.device_id=i.device_id AND st.engine=ps.engine AND st.worker_version=i.worker_version),
                    (SELECT count(*) FROM sampling_evidence e WHERE e.device_id=i.device_id AND e.engine=ps.engine AND e.worker_version=i.worker_version AND e.outcome='match'))<100),
              selected AS MATERIALIZED (
                SELECT DISTINCT t.segment_id,t.start_unit,t.end_unit FROM probation i
                CROSS JOIN submissions t INDEXED BY ix_submission_negative_identity
                ON t.device_id=i.device_id AND t.worker_version=i.worker_version AND t.segment_id=i.segment_id
                WHERE t.candidate_count=0 AND t.worker_version!='') """
            # The probation keys already prove tier 1; only audit overlap must
            # be excluded, without recalculating reputation for every range.
            audit_cte=audit_keys[len('WITH '):].replace('selected AS MATERIALIZED','audit_ranges AS MATERIALIZED',1).strip()
            probation_query=probation_keys.replace('WITH identities', 'WITH '+audit_cte+', identities',1)
            exclude_audit=' and not exists(select 1 from audit_ranges ar where ar.segment_id=v.segment_id and ar.start_unit=v.start_unit and ar.end_unit=v.end_unit)'
            cursor=con.execute(probation_query+key_base.replace(validation_from,keyed)+exclude_audit+order,key_params)
            try:
                for row in cursor:yield row,True
            finally:cursor.close()
        # Remaining work is already ordered by a per-segment index. Merge only
        # equal-priority segment heads; never materialize/sort the full backlog.
        segments=con.execute("SELECT s.* FROM segments s JOIN campaigns c ON c.id=s.campaign_id WHERE c.status='running' ORDER BY s.priority,s.id").fetchall()
        eligible=[seg for seg in segments if device_eligible(dev,seg)[0]]
        for rank in sorted({seg['priority'] for seg in eligible}):
            cursors=[];heads=[]
            try:
                for seg in eligible:
                    if seg['priority']!=rank:continue
                    source='segments s CROSS JOIN validations v INDEXED BY ix_validation_selection_order ON s.id=v.segment_id'
                    query=base.replace(validation_from,source)+' and s.id=?'
                    if sampling:query+=f' and ({priority})=2'
                    query+=' order by v.created,v.start_unit,v.end_unit'
                    cursor=con.execute(query,[*params,seg['id']]);index=len(cursors);cursors.append(cursor)
                    row=cursor.fetchone()
                    if row is not None:heapq.heappush(heads,((row['v_created'],row['id'],row['v_start'],row['v_end']),index,row))
                while heads:
                    _,index,row=heapq.heappop(heads);yield row,False
                    next_row=cursors[index].fetchone()
                    if next_row is not None:heapq.heappush(heads,((next_row['v_created'],next_row['id'],next_row['v_start'],next_row['v_end']),index,next_row))
            finally:
                for cursor in cursors:cursor.close()
    rows=ordered_rows()
    try:
        # Selected-audit and probation CTEs intentionally use only a partial
        # predicate; preserve their per-row checks. The ordinary queue query
        # applies all predicates already and is rechecked under the writer at
        # assignment. Avoid repeating five cold point-lookups for each row.
        for r,needs_recheck in rows:
            ok,resource,pct=device_eligible(dev,r)
            if not ok:continue
            if not needs_recheck:
                yield r,resource,pct
                continue
            local=con.execute("""select status,updated from server_verifications
                where segment_id=? and start_unit=? and end_unit=?""",
                (r['id'],r['v_start'],r['v_end'])).fetchone()
            if local and local['status']=='running' and local['updated']>now()-15:continue
            prior=con.execute("""select count(*) n from submissions where segment_id=? and start_unit=? and end_unit=?""",
                              (r["id"],r["v_start"],r["v_end"])).fetchone()["n"]
            if local and local['status']=='done':prior+=1
            active=con.execute("""select count(*) n from leases where segment_id=? and start_unit=? and end_unit=?
                                  and status='leased' and purpose='validation'""",
                               (r["id"],r["v_start"],r["v_end"])).fetchone()["n"]
            if has_block_claims:active+=work_blocks.validation_claims(con,r['id'],r['v_start'],r['v_end'],timestamp=now())
            if prior+active>=r["v_target"]:continue
            same=con.execute("""select 1 from submissions where segment_id=? and start_unit=? and end_unit=?
                                and contributor_id=? limit 1""",
                             (r["id"],r["v_start"],r["v_end"],dev["contributor_id"])).fetchone()
            if same:continue
            active_same=con.execute("""select 1 from leases l join devices d on d.id=l.device_id
                                       where l.segment_id=? and l.start_unit=? and l.end_unit=? and l.status='leased'
                                       and d.contributor_id=? limit 1""",
                                    (r["id"],r["v_start"],r["v_end"],dev["contributor_id"])).fetchone()
            if active_same:continue
            if has_block_claims and work_blocks.validation_claims(con,r['id'],r['v_start'],r['v_end'],
                                             timestamp=now(),contributor_id=dev['contributor_id']):continue
            yield r,resource,pct
    finally:
        rows.close()

def recheck_validation_candidate(con,dev,candidate):
    """Revalidate an advisory read-side candidate under the assignment writer."""
    if load_cfg().get('volunteer_validation_enabled',True) is False:
        return None,None,None
    key=(candidate['id'],candidate['v_start'],candidate['v_end'])
    row=con.execute("""select s.*,v.start_unit v_start,v.end_unit v_end,
        v.target_replicas v_target,v.max_replicas v_max from validations v
        join segments s on s.id=v.segment_id join campaigns c on c.id=s.campaign_id
        where v.segment_id=? and v.start_unit=? and v.end_unit=?
          and v.status='pending' and c.status='running'""",key).fetchone()
    if row is None or any(row[k]!=candidate[k] for k in ('engine','config_json')):
        return None,None,None
    ok,resource,pct=device_eligible(dev,row)
    if not ok:return None,None,None
    if con.execute('select 1 from done_ranges where segment_id=? and start_unit=? and end_unit=?',key).fetchone():
        return None,None,None
    local=con.execute('select status,updated from server_verifications where segment_id=? and start_unit=? and end_unit=?',key).fetchone()
    if local and local['status']=='running' and local['updated']>now()-15:
        return None,None,None
    prior=con.execute('select count(*) from submissions where segment_id=? and start_unit=? and end_unit=?',key).fetchone()[0]
    if local and local['status']=='done':prior+=1
    active=con.execute("select count(*) from leases where segment_id=? and start_unit=? and end_unit=? and status='leased' and purpose='validation'",key).fetchone()[0]
    has_block_claims=_has_validation_block_claim_schema(con)
    if has_block_claims:active+=work_blocks.validation_claims(con,*key,timestamp=now())
    if prior+active>=min(row['v_target'],row['v_max']):return None,None,None
    if con.execute('select 1 from submissions where segment_id=? and start_unit=? and end_unit=? and contributor_id=? limit 1',(*key,dev['contributor_id'])).fetchone():
        return None,None,None
    if con.execute("""select 1 from leases l join devices d on d.id=l.device_id
        where l.segment_id=? and l.start_unit=? and l.end_unit=? and l.status='leased'
          and d.contributor_id=? limit 1""",(*key,dev['contributor_id'])).fetchone():
        return None,None,None
    if has_block_claims and work_blocks.validation_claims(con,*key,timestamp=now(),contributor_id=dev['contributor_id']):
        return None,None,None
    return row,resource,pct


def recheck_validation_run(con,dev,first,end_unit):
    """Writer-side, set-level check of a contiguous bounded validation prefix."""
    if not con.in_transaction:raise ValueError('Validation run requires writer transaction')
    start=first['v_start']
    if end_unit<=start or end_unit-start>work_blocks.MAX_VALIDATION_UNITS:return False
    row,_,_=recheck_validation_candidate(con,dev,first)
    if row is None:return False
    segment=first['id'];at=now();owner=dev['contributor_id']
    # Recheck ordinary-tier classification for every reordered unit under the
    # writer, while leaving audit/probation FIFO behavior unchanged.
    same_tier=(f" AND ({validation_priority_sql()})=2"
               if 'v_selection_tier' in first.keys() and first['v_selection_tier']==2 else '')
    good=con.execute(f"""SELECT count(*) FROM validations v JOIN segments s ON s.id=v.segment_id
        WHERE v.segment_id=? AND v.start_unit>=? AND v.start_unit<?
          AND v.end_unit=v.start_unit+1 AND v.status='pending' {same_tier}
          AND NOT EXISTS(SELECT 1 FROM done_ranges done
            WHERE done.segment_id=v.segment_id AND done.start_unit=v.start_unit
              AND done.end_unit=v.end_unit)
          AND NOT EXISTS(SELECT 1 FROM submissions own
            WHERE own.segment_id=v.segment_id AND own.start_unit=v.start_unit
              AND own.end_unit=v.end_unit AND own.contributor_id=?)
          AND NOT EXISTS(SELECT 1 FROM leases ownl JOIN devices od ON od.id=ownl.device_id
            WHERE ownl.segment_id=v.segment_id AND ownl.start_unit=v.start_unit
              AND ownl.end_unit=v.end_unit AND ownl.status='leased' AND od.contributor_id=?)
           AND NOT EXISTS(SELECT 1 FROM work_blocks ownb INDEXED BY ix_work_blocks_validation_reserved_claim
             JOIN devices obd ON obd.id=ownb.device_id
             WHERE ownb.segment_id=v.segment_id AND ownb.purpose='validation'
               AND ownb.status='reserved' AND ownb.start_unit<=v.start_unit
               AND ownb.end_unit>=v.end_unit AND ownb.expires_at>?
               AND obd.contributor_id=?
               AND NOT EXISTS(SELECT 1 FROM block_receipts br
                   WHERE br.block_id=ownb.id AND br.unit=v.start_unit))
           AND NOT EXISTS(SELECT 1 FROM block_receipts br INDEXED BY ix_block_receipts_pending_unit
             CROSS JOIN work_blocks ownb ON ownb.id=br.block_id
             JOIN devices obd ON obd.id=ownb.device_id
             WHERE br.unit=v.start_unit AND br.promoted_at IS NULL
               AND br.verification_status='pending'
               AND ownb.segment_id=v.segment_id AND ownb.purpose='validation'
               AND ownb.start_unit<=v.start_unit AND ownb.end_unit>=v.end_unit
               AND obd.contributor_id=?)
          AND NOT EXISTS(SELECT 1 FROM server_verifications sv
            WHERE sv.segment_id=v.segment_id AND sv.start_unit=v.start_unit
              AND sv.end_unit=v.end_unit AND sv.status='running' AND sv.updated>?)
          AND ((SELECT count(*) FROM submissions p WHERE p.segment_id=v.segment_id
                AND p.start_unit=v.start_unit AND p.end_unit=v.end_unit)
              + CASE WHEN EXISTS(SELECT 1 FROM server_verifications done
                WHERE done.segment_id=v.segment_id AND done.start_unit=v.start_unit
                  AND done.end_unit=v.end_unit AND done.status='done') THEN 1 ELSE 0 END
              + (SELECT count(*) FROM leases active WHERE active.segment_id=v.segment_id
                  AND active.start_unit=v.start_unit AND active.end_unit=v.end_unit
                  AND active.status='leased' AND active.purpose='validation')
               + (SELECT count(*) FROM work_blocks active INDEXED BY ix_work_blocks_validation_reserved_claim
                   WHERE active.segment_id=v.segment_id
                   AND active.purpose='validation' AND active.status='reserved'
                   AND active.start_unit<=v.start_unit AND active.end_unit>=v.end_unit
                   AND active.expires_at>?
                   AND NOT EXISTS(SELECT 1 FROM block_receipts br
                     WHERE br.block_id=active.id AND br.unit=v.start_unit))
               + (SELECT count(*) FROM block_receipts br INDEXED BY ix_block_receipts_pending_unit
                   CROSS JOIN work_blocks active ON active.id=br.block_id
                   WHERE br.unit=v.start_unit AND br.promoted_at IS NULL
                     AND br.verification_status='pending'
                     AND active.segment_id=v.segment_id AND active.purpose='validation'
                     AND active.start_unit<=v.start_unit AND active.end_unit>=v.end_unit))
              < min(v.target_replicas,v.max_replicas)""",
        (segment,start,end_unit,owner,owner,at,owner,owner,at-15,at)).fetchone()[0]
    return good==end_unit-start


def validation_candidate(con,dev):
    return next(validation_candidates(con,dev),(None,None,None))


def ordinary_validation_contiguous_preview(con, device_id, first, candidate_iter, limit):
    """Choose a bounded contiguous run from the first ordinary tier/segment.

    The generator already applies device, contributor and replica predicates.
    A bounded lookahead can reorder timestamps *within* the same tier/segment
    to combine adjacent units. Every eighth selection offers the oldest range
    instead, so singleton tails continue to receive assignment attempts. The
    writer still rechecks every unit independently before reservation.
    """
    if limit < 1 or limit > work_blocks.MAX_VALIDATION_UNITS:
        raise ValueError('Invalid validation preview bound')
    if not load_cfg().get('trusted_sampling_enabled',False):
        return None
    tier=validation_priority_sql()
    first_tier=con.execute(f"""SELECT ({tier}) FROM validations v JOIN segments s ON s.id=v.segment_id
        WHERE v.segment_id=? AND v.start_unit=? AND v.end_unit=?""",
        (first['id'],first['v_start'],first['v_end'])).fetchone()
    if first_tier is None or first_tier[0]!=2:
        return None
    first_page=min(512,work_blocks.MAX_VALIDATION_UNITS)
    lookahead=min(4096,work_blocks.MAX_VALIDATION_UNITS)
    rows={first['v_start']:first}
    scanned=1
    while scanned<lookahead:
        item=next(candidate_iter,None)
        if item is None:break
        row=item[0];scanned+=1
        # The generator is priority-ordered. Never reach a lower-priority
        # campaign, and never bundle another segment into this descriptor.
        if row['priority']>first['priority']:break
        if row['priority']==first['priority'] and row['id']==first['id'] and row['v_end']==row['v_start']+1:
            rows[row['v_start']]=row
        if scanned==first_page:
            units=sorted(rows)
            best=run=1
            for before,after in zip(units,units[1:]):
                run=run+1 if after==before+1 else 1
                best=max(best,run)
            # Do not scan thousands of extra candidates when one page already
            # gives a useful run, especially on a memory-constrained server.
            if best>=min(64,limit):break
    ordered=sorted(rows)
    runs=[];current=[]
    for unit in ordered:
        if current and unit!=current[-1]['v_start']+1:
            runs.append(current);current=[]
        current.append(rows[unit])
    if current:runs.append(current)
    oldest=next(run for run in runs if any(row['v_start']==first['v_start'] for row in run))
    global VALIDATION_SELECTIONS
    with VALIDATION_FAIR_LOCK:
        VALIDATION_SELECTIONS[device_id]+=1
        choose_oldest=VALIDATION_SELECTIONS[device_id]%8==0
    selected=(oldest if choose_oldest else
              max(runs,key=lambda run:(min(len(run),limit),-run[0]['v_start'])))
    return [dict(row,v_selection_tier=2) for row in selected[:limit]]

def next_primary(con,dev,diagnostics=None):
    # Private operator drain mode never changes client budgets or existing leases.
    if backlog_control.hold_primary(DATA,con):
        if diagnostics is not None:diagnostics.update(wait_reason='primary_held_for_verification',retry_after_seconds=5)
        return None,None,None,None,None,False
    sampling=load_cfg().get('trusted_sampling_enabled',False)
    try:raw_meta=dev['meta_json']
    except (KeyError,IndexError):raw_meta='{}'
    version=parse_json(raw_meta,{}).get('worker_version','')
    allowed_engines={}
    def can_issue(engine):
        if not sampling:return True
        if engine not in allowed_engines:
            reserved=con.execute("""select count(*) from leases l join segments s on s.id=l.segment_id
                where l.device_id=? and s.engine=? and l.status='leased' and l.purpose='primary'""",
                (dev['id'],engine)).fetchone()[0]
            allowed_engines[engine]=trusted_sampling.issuance_allowed(con,dev['id'],engine,version,
                quarantined=bool(dev['quarantined']),pending_primary_leases=reserved)
        if not allowed_engines[engine] and diagnostics is not None:
            diagnostics.update(wait_reason='verification_pending',retry_after_seconds=5)
        return allowed_engines[engine]
    choices=[]
    rq=con.execute("""select r.segment_id,r.start_unit,r.end_unit,s.* from requeue r
                      join segments s on s.id=r.segment_id join campaigns c on c.id=s.campaign_id
                      where c.status='running' order by s.priority,r.queued_at limit 500""").fetchall()
    for r in rq:
        ok,res,pct=device_eligible(dev,r)
        if ok and can_issue(r["engine"]): choices.append((r["priority"],0,r,r["start_unit"],r["end_unit"],res,pct,True))
    segs=con.execute("""select s.* from segments s join campaigns c on c.id=s.campaign_id
                        where c.status='running' and s.next_unit<s.end_unit
                        order by s.priority,
                          (s.next_unit-s.start_unit)*1.0/max(1,s.end_unit-s.start_unit),s.id limit 500""").fetchall()
    for s in segs:
        ok,res,pct=device_eligible(dev,s)
        if ok and can_issue(s["engine"]):
            start=s["next_unit"];end=min(s["end_unit"],start+s["chunk_size"])
            choices.append((s["priority"],1,s,start,end,res,pct,False))
    if not choices:
        if diagnostics is not None and 'wait_reason' not in diagnostics:
            diagnostics.update(wait_reason='no_compatible_work',retry_after_seconds=2)
        return None,None,None,None,None,False
    _,_,seg,start,end,res,pct,wasrq=min(choices,key=lambda x:(x[0],x[1]))
    return seg,start,end,res,pct,wasrq

def credit_submission(con,row,verified=True):
    current=con.execute("select credited,status from submissions where id=?",(row["id"],)).fetchone()
    if not current["credited"]:
        units=row["end_unit"]-row["start_unit"]
        con.execute("""insert into contributions(contributor_id,device_id,units,jobs,compute_seconds,candidates)
                       values(?,?,?,1,?,?) on conflict(contributor_id,device_id) do update set
                       units=units+excluded.units,jobs=jobs+1,
                       compute_seconds=compute_seconds+excluded.compute_seconds,
                       candidates=candidates+excluded.candidates""",
                    (row["contributor_id"],row["device_id"],units,row["compute_seconds"],row["candidate_count"]))
    status="verified" if verified else "accepted_trusted"
    con.execute("update submissions set credited=1,status=? where id=?",(status,row["id"]))
    if verified and current["status"]!="verified":trust_reward(con,row["device_id"])


def revoke_trusted_results(con,device_id):
    """Reopen provisional work and reverse its credit exactly once, preserving receipts."""
    rows=con.execute("select * from submissions where device_id=? and status='accepted_trusted'",(device_id,)).fetchall()
    for row in rows:
        key=(row["segment_id"],row["start_unit"],row["end_unit"])
        if row["credited"]:
            con.execute("""update contributions set units=units-?,jobs=jobs-1,
              compute_seconds=max(0,compute_seconds-?),candidates=candidates-?
              where contributor_id=? and device_id=?""",
              (row["end_unit"]-row["start_unit"],row["compute_seconds"],row["candidate_count"],row["contributor_id"],device_id))
        con.execute("update submissions set credited=0,status='pending' where id=?",(row["id"],))
        con.execute("delete from done_ranges where segment_id=? and start_unit=? and end_unit=? and verification_status='accepted_trusted'",key)
        con.execute("""update validations set status='pending',canonical_fingerprint=NULL,verified_at=NULL
                       where segment_id=? and start_unit=? and end_unit=? and status='accepted_trusted'""",key)
        con.execute("""update campaigns set status='running' where status='complete' and id=
                       (select campaign_id from segments where id=?)""",(row["segment_id"],))
    if rows:audit(con,"trusted_acceptance_revoked",device_id,submissions=len(rows))
    return len(rows)


def record_sampling_evidence(con,row,matched):
    engine=con.execute("select engine from segments where id=?",(row["segment_id"],)).fetchone()["engine"]
    trusted_sampling.record_independent_verification(con,row["id"],row["device_id"],engine,
        row["worker_version"],matched=matched,independent=True)
    if not matched:revoke_trusted_results(con,row["device_id"])

def reconcile(con,segid,start,end):
    owns_transaction=not con.in_transaction
    if owns_transaction:con.execute("begin immediate")
    try:
        result=_reconcile(con,segid,start,end)
        if owns_transaction:con.execute("commit")
        return result
    except Exception:
        if owns_transaction:con.execute("rollback")
        raise


def _reconcile(con,segid,start,end):
    v=con.execute("""select * from validations where segment_id=? and start_unit=? and end_unit=?""",
                  (segid,start,end)).fetchone()
    if not v or v["status"]!="pending":return v["status"] if v else "missing"
    rows=con.execute("""select * from submissions where segment_id=? and start_unit=? and end_unit=?
                        and status in ('pending','verified') order by submitted_at""",
                     (segid,start,end)).fetchall()
    counts=defaultdict(list)
    for r in rows:counts[r["fingerprint"]].append(r)
    local=con.execute("""select fingerprint from server_verifications where
        segment_id=? and start_unit=? and end_unit=? and status='done'""",(segid,start,end)).fetchone()
    local_fp=local['fingerprint'] if local else None
    # A contributor may own several devices: those are not independent votes.
    # Conflicting submissions by one contributor do not vote for either result.
    contributor_fps=defaultdict(set)
    for row in rows:contributor_fps[row["contributor_id"]].add(row["fingerprint"])
    def votes(fp,items):
        return len({row["contributor_id"] for row in items if len(contributor_fps[row["contributor_id"]])==1})+int(fp==local_fp)
    best_fp=None;best=[]
    for fp,items in counts.items():
        if best_fp is None or votes(fp,items)>votes(best_fp,best):best_fp,best=fp,items
    if best and votes(best_fp,best)>=v["base_required"]:
        canonical=best[0]
        con.execute("""insert or ignore into done_ranges(segment_id,start_unit,end_unit,lease_id,device_id,completed_at,result_json)
                       values(?,?,?,?,?,?,?)""",(segid,start,end,canonical["lease_id"],canonical["device_id"],now(),canonical["result_json"]))
        con.execute("update done_ranges set verification_status='verified' where segment_id=? and start_unit=? and end_unit=?",(segid,start,end))
        con.execute("""update validations set status='verified',canonical_fingerprint=?,verified_at=?
                       where segment_id=? and start_unit=? and end_unit=?""",(best_fp,now(),segid,start,end))
        for r in rows:
            if r["fingerprint"]==best_fp:
                credit_submission(con,r)
                record_sampling_evidence(con,r,True)
            elif r["status"]!="rejected":
                con.execute("update submissions set status='rejected' where id=?",(r["id"],))
                trust_penalty(con,r["device_id"],False,"consensus_mismatch")
                record_sampling_evidence(con,r,False)
        # Reconcile is also used by maintenance/tests outside the HTTP completion
        # path, so it must be able to close a campaign on its own.
        refresh_campaign_completion(con,segid)
        return "verified"
    total=len(contributor_fps)+int(local_fp is not None)
    if len(set(counts)|({local_fp} if local_fp else set()))>1 and v["target_replicas"]<v["max_replicas"]:
        con.execute("""update validations set target_replicas=max_replicas
                       where segment_id=? and start_unit=? and end_unit=?""",(segid,start,end))
        return "pending_tiebreak"
    if total>=v["max_replicas"]:
        con.execute("""update validations set status='manual_review' where segment_id=? and start_unit=? and end_unit=?""",
                    (segid,start,end))
        audit(con,"validation_manual_review",None,segment_id=segid,start=start,end=end,
              fingerprints={k:len(x) for k,x in counts.items()})
        return "manual_review"
    return "pending"
def refresh_campaign_completion(con,segment_id=None):
    if segment_id is None:
        campaigns=[r["id"] for r in con.execute("select id from campaigns where status='running'")]
    else:
        row=con.execute("""select c.id from campaigns c join segments s on s.campaign_id=c.id
                           where s.id=? and c.status='running'""",(segment_id,)).fetchone()
        campaigns=[row["id"]] if row else []
    for cid in campaigns:
        # Completion is rare; the hot submission path should be O(1) while any
        # primary, lease, validation or requeue work remains.
        if con.execute("select 1 from segments where campaign_id=? and next_unit<end_unit limit 1",(cid,)).fetchone():continue
        if con.execute("""select 1 from leases l join segments s on s.id=l.segment_id
                          where s.campaign_id=? and l.status='leased' limit 1""",(cid,)).fetchone():continue
        if con.execute("""select 1 from validations v join segments s on s.id=v.segment_id
                          where s.campaign_id=? and v.status in ('pending','manual_review') limit 1""",(cid,)).fetchone():continue
        if con.execute("""select 1 from requeue r join segments s on s.id=r.segment_id
                          where s.campaign_id=? limit 1""",(cid,)).fetchone():continue
        total=con.execute("select coalesce(sum(end_unit-start_unit),0) n from segments where campaign_id=?",(cid,)).fetchone()["n"]
        done=con.execute("""select coalesce(sum(dr.end_unit-dr.start_unit),0) n from done_ranges dr
                            join segments s on s.id=dr.segment_id where s.campaign_id=?""",(cid,)).fetchone()["n"]
        if total and done>=total:
            con.execute("update campaigns set status='complete' where id=?",(cid,))

def prune_private_data(con):
    global LAST_PRUNE
    t=now()
    if t-LAST_PRUNE<3600:return
    LAST_PRUNE=t
    con.execute("delete from registration_nonces where expires<?",(t,))
    con.execute("delete from audit_log where created<?",(t-30*86400,))
    con.execute("""update devices set meta_json='{}' where enabled=0
                   and last_seen is not null and last_seen<?""",(t-90*86400,))

def progress_payload(con, public_campaign_ids=None):
    # Public status is read-only. Lease expiry, retention pruning and campaign
    # completion run only inside write transactions, never on a dashboard GET.
    # A private allowlist keeps isolated diagnostic campaigns in the audit DB
    # without presenting their units or synthetic contributors as public work.
    if public_campaign_ids is not None:
        if (not isinstance(public_campaign_ids,list) or len(public_campaign_ids)>64
                or any(not isinstance(cid,str) or not cid or len(cid)>128 for cid in public_campaign_ids)
                or len(set(public_campaign_ids))!=len(public_campaign_ids)):
            raise ValueError('Invalid public campaign allowlist')
        campaign_ids=tuple(public_campaign_ids)
        campaign_scope=' and c.id in ('+','.join('?' for _ in campaign_ids)+')' if campaign_ids else ' and 0'
    else:
        campaign_ids=()
        campaign_scope=''
    total=con.execute("""select coalesce(sum(s.end_unit-s.start_unit),0) n from segments s
                         join campaigns c on c.id=s.campaign_id where c.status in ('running','complete','paused')"""+campaign_scope,campaign_ids).fetchone()["n"]
    done=con.execute("""select coalesce(sum(dr.end_unit-dr.start_unit),0) n from done_ranges dr
                        join segments s on s.id=dr.segment_id join campaigns c on c.id=s.campaign_id
                        where c.status in ('running','complete','paused')"""+campaign_scope,campaign_ids).fetchone()["n"]
    pending=con.execute("""select count(*) n from validations v join segments s on s.id=v.segment_id
                           join campaigns c on c.id=s.campaign_id where c.status in ('running','paused')
                           and v.status='pending'"""+campaign_scope,campaign_ids).fetchone()["n"]
    online_cut=now()-load_cfg().get("online_seconds",60)
    devs=con.execute("""select capabilities_json,settings_json from devices
                        where enabled=1 and quarantined=0 and last_seen>?""",(online_cut,)).fetchall()
    cpu=gpu=0
    for d in devs:
        st=normalize_settings(parse_json(d["settings_json"],{}));caps=set(parse_json(d["capabilities_json"],[]))
        if st["allow_cpu"] and st["cpu_percent"]>0 and "cpu" in caps:cpu+=1
        if st["allow_gpu"] and st["gpu_percent"]>0 and ("cuda" in caps or "gpu" in caps):gpu+=1
    if public_campaign_ids is None:
        leaders=[dict(r) for r in con.execute("""select c.display_name,sum(x.units) units,sum(x.jobs) jobs,
                  round(sum(x.compute_seconds),1) compute_seconds from contributions x join contributors c on c.id=x.contributor_id
                  where c.public_credit=1 group by c.id order by units desc,compute_seconds desc limit 20""")]
    else:
        # Only excluded segments are read. This preserves the cheap aggregate
        # contributions ledger for real work, while subtracting any diagnostic
        # submissions even if they accidentally used a real contributor ID.
        excluded_where='s.campaign_id not in ('+','.join('?' for _ in campaign_ids)+')' if campaign_ids else '1'
        leaders=[dict(r) for r in con.execute("""with excluded as (
                  select u.contributor_id,sum(u.end_unit-u.start_unit) units,count(*) jobs,
                         sum(u.compute_seconds) compute_seconds
                  from segments s cross join submissions u INDEXED BY ix_sub_range
                  where u.segment_id=s.id and """+excluded_where+""" and u.credited=1 group by u.contributor_id),
                totals as (select contributor_id,sum(units) units,sum(jobs) jobs,
                                  sum(compute_seconds) compute_seconds from contributions group by contributor_id)
                select c.display_name,t.units-coalesce(e.units,0) units,
                       t.jobs-coalesce(e.jobs,0) jobs,
                       round(t.compute_seconds-coalesce(e.compute_seconds,0),1) compute_seconds
                from totals t join contributors c on c.id=t.contributor_id
                left join excluded e on e.contributor_id=t.contributor_id
                where c.public_credit=1 and t.jobs>coalesce(e.jobs,0)
                order by units desc,compute_seconds desc limit 20""",campaign_ids)]
    camps=[dict(r) for r in con.execute("select id,name,version,status,created,notes from campaigns c where 1=1"+campaign_scope+" order by created desc",campaign_ids)]
    trusted_units=con.execute("""select coalesce(sum(dr.end_unit-dr.start_unit),0) from done_ranges dr
        join segments s on s.id=dr.segment_id join campaigns c on c.id=s.campaign_id
        where dr.verification_status='accepted_trusted' and c.status in ('running','complete','paused')"""+campaign_scope,campaign_ids).fetchone()[0]
    return {"total_units":total,"completed_units":done,"verified_units":done-trusted_units,"accepted_trusted_units":trusted_units,"progress_pct":round(done*100/total,6) if total else 0,
            "registration_open":bool(load_cfg().get('registration_open',False)),
            "online_devices":len(devs),"online_cpu_devices":cpu,"online_gpu_devices":gpu,
            "pending_validations":pending,"leaderboard":leaders,"campaigns":camps,"time":now()}


def public_status_payload():
    """Share one short read-only snapshot across dashboard polls.

    The cache lock serializes status refreshes only; health and compute
    endpoints never wait on the public aggregate query.
    """
    global PUBLIC_STATUS_CACHE
    cfg=load_cfg()
    # A missing private allowlist must never publish diagnostic/test campaigns.
    public_ids=cfg.get('public_campaign_ids',[])
    scope=(json.dumps(public_ids,sort_keys=True,separators=(',',':')),
           CFG.stat().st_mtime_ns,str(DB.resolve()))
    # A slow public aggregate may occupy one HTTP slot, never all dashboard
    # callers. A stale value is safe only for the exact same public scope.
    key,created,payload=PUBLIC_STATUS_CACHE
    if key==scope and payload is not None and time.monotonic()-created<PUBLIC_STATUS_TTL_SECONDS:
        return payload
    if not PUBLIC_STATUS_LOCK.acquire(blocking=False):
        key,created,payload=PUBLIC_STATUS_CACHE
        return payload if key==scope and payload is not None else None
    try:
        key,created,payload=PUBLIC_STATUS_CACHE
        if key==scope and payload is not None and time.monotonic()-created<PUBLIC_STATUS_TTL_SECONDS:
            return payload
        con=db()
        try:payload=progress_payload(con,public_ids)
        finally:con.close()
        PUBLIC_STATUS_CACHE=(scope,time.monotonic(),payload)
        return payload
    finally:
        PUBLIC_STATUS_LOCK.release()

def personal_stats_snapshot(con,contributor_id):
    """Return exact historical aggregates from one SQLite read snapshot."""
    own_transaction=not con.in_transaction
    if own_transaction:con.execute("BEGIN")
    observed_at=time.time()
    try:
        stats=dict(con.execute("""select coalesce(sum(units),0) units,coalesce(sum(jobs),0) jobs,
                                  coalesce(sum(compute_seconds),0) compute_seconds,
                                  coalesce(sum(candidates),0) candidates from contributions where contributor_id=?""",
                               (contributor_id,)).fetchone())
        stats["credited_units"]=stats["units"]
        stats["credited_jobs"]=stats["jobs"]
        for status,label in (("verified","verified"),("accepted_trusted","accepted_trusted")):
            split=con.execute("select coalesce(sum(end_unit-start_unit),0),count(*) from submissions where contributor_id=? and credited=1 and status=?",(contributor_id,status)).fetchone()
            stats[label+"_units"]=split[0];stats[label+"_jobs"]=split[1]
        stats["units"]=stats["verified_units"];stats["jobs"]=stats["verified_jobs"]
        pending=con.execute("""select coalesce(sum(end_unit-start_unit),0) n from submissions
                               where contributor_id=? and status='pending'""",(contributor_id,)).fetchone()["n"]
        return stats,pending,observed_at
    finally:
        if own_transaction:con.rollback()

def personal_stats_cached(con,contributor_id):
    """Coalesce hot dashboard polls without hiding the age of exact counts."""
    current=time.monotonic()
    with PERSONAL_STATS_LOCK:
        entry=PERSONAL_STATS_CACHE.get(contributor_id)
        if entry and entry.get("value") and (entry["running"] or current-entry["saved"]<PERSONAL_STATS_TTL_SECONDS):
            return entry["value"]
        if entry and entry["running"]:
            return PERSONAL_STATS_BUSY
        # Contributor ID is authenticated. Bound cache memory across accounts.
        if len(PERSONAL_STATS_CACHE)>=256 and contributor_id not in PERSONAL_STATS_CACHE:
            oldest=min((k for k,v in PERSONAL_STATS_CACHE.items() if not v["running"]),
                       key=lambda k:PERSONAL_STATS_CACHE[k]["saved"],default=None)
            if oldest is None:return PERSONAL_STATS_BUSY
            PERSONAL_STATS_CACHE.pop(oldest,None)
        PERSONAL_STATS_CACHE[contributor_id]={"running":True,"saved":entry["saved"] if entry else 0.0,
                                             "value":entry["value"] if entry else None}
    try:
        value=personal_stats_snapshot(con,contributor_id)
    except BaseException:
        with PERSONAL_STATS_LOCK:
            PERSONAL_STATS_CACHE[contributor_id]["running"]=False
        raise
    with PERSONAL_STATS_LOCK:
        PERSONAL_STATS_CACHE[contributor_id]={"running":False,"saved":time.monotonic(),"value":value}
    return value

def personal_payload(con,token):
    c=con.execute("select * from contributors where dashboard_token_hash=?",(sha(token or ""),)).fetchone()
    if not c:return None
    devs=[]
    for r in con.execute("""select id,label,enabled,last_seen,meta_json,settings_json,capabilities_json,
                            trust_score,quarantined,valid_jobs,invalid_jobs,created from devices
                            where contributor_id=? order by created""",(c["id"],)):
        x=dict(r);x["meta"]=parse_json(x.pop("meta_json"),{});x["settings"]=normalize_settings(parse_json(x.pop("settings_json"),{}))
        x["capabilities"]=parse_json(x.pop("capabilities_json"),[]);devs.append(x)
    snapshot=personal_stats_cached(con,c["id"])
    if snapshot is PERSONAL_STATS_BUSY:return PERSONAL_STATS_BUSY
    stats,pending,stats_as_of=snapshot
    return {"contributor_id":c["id"],"display_name":c["display_name"],"public_credit":bool(c["public_credit"]),
            "devices":devs,"stats":stats,"pending_units":pending,"stats_as_of":stats_as_of}

_COMPUTE_PATHS = frozenset({
    '/api/complete','/api/leases','/api/lease','/api/heartbeat',
    '/api/device/settings','/api/completions','/api/leases/release',
    '/api/work-blocks','/api/work-blocks/results','/api/work-blocks/release',
    '/api/work-blocks/status','/api/work-blocks/result-groups',
})

def rate_key(handler):
    token=handler.headers.get("X-Device-Token","").strip()
    path=urlparse(handler.path).path
    # Keep authenticated compute, telemetry, and account/dashboard budgets
    # independent while retaining one shared global cap for every request.
    category=("telemetry:" if path=="/api/device/telemetry/v1" else
              "compute:" if token and path in _COMPUTE_PATHS else "normal:")
    raw=category+(("token:"+token) if token else ("anon:"+str(handler.client_address[0])))
    return sha(RATE_SALT.hex()+raw)

def allowed_request(handler,cost=1):
    max_cost=64 if urlparse(handler.path).path=='/api/work-blocks/result-groups' else 8
    if type(cost) is not int or not 1<=cost<=max_cost:raise ValueError("Invalid request cost")
    cfg=load_cfg();limit=int(cfg.get("rate_limit_per_minute",180));key=rate_key(handler);t=now()
    path=urlparse(handler.path).path
    token=handler.headers.get('X-Device-Token','').strip()
    # High-throughput compute endpoints use a separate authenticated budget.
    # The global cap still bounds aggregate load, while dashboard/account paths
    # retain the tighter per-device limit.
    if token and path in _COMPUTE_PATHS:
        limit=int(cfg.get('compute_rate_limit_per_minute',3600))
    elif token and path=='/api/device/telemetry/v1':
        limit=int(cfg.get('telemetry_rate_limit_per_minute',12))
    # Funnel peers share a loopback address. Give anonymous dashboard reads a
    # shared budget; retain tighter registration and per-device limits below.
    if not token:
        limit=int(cfg.get('anonymous_rate_per_minute',6000))
    with RATE_LOCK:
        for window in (GLOBAL_RATE,REGISTER_RATE):
            while window and window[0]<t-60:window.popleft()
        if len(GLOBAL_RATE)+cost>int(cfg.get("global_rate_per_minute",12000)):return False
        registration=path in {"/api/register","/api/register-challenge"}
        if registration and len(REGISTER_RATE)>=int(cfg.get("registration_rate_per_minute",120)):return False
        if key not in RATE and len(RATE)>=4096:
            stale=[k for k,v in RATE.items() if not v or v[-1]<t-60]
            for k in stale:RATE.pop(k,None)
            if len(RATE)>=4096:return False
        q=RATE[key]
        while q and q[0]<t-60:q.popleft()
        if len(q)+cost>limit:return False
        GLOBAL_RATE.extend([t]*cost)
        if registration:REGISTER_RATE.append(t)
        q.extend([t]*cost);return True

class LimitedThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads=True
    request_queue_size=64
    allow_reuse_address=True
    def __init__(self,address,handler,max_workers=64):
        self._slots=threading.BoundedSemaphore(max_workers)
        super().__init__(address,handler)
    def process_request(self,request,client_address):
        if not self._slots.acquire(blocking=False):
            try:request.close()
            except Exception:pass
            return
        try:super().process_request(request,client_address)
        except Exception:
            self._slots.release();raise
    def process_request_thread(self,request,client_address):
        try:super().process_request_thread(request,client_address)
        finally:self._slots.release()

PORTABLE_PRIMARY_LEASE_LIMIT=3
PORTABLE_VALIDATION_LEASE_LIMIT=24

def portable_validation_lease_budget(rows,segment_id,ttl,at):
 """Bound buffered audits by independently verified server wall time.

 A client's requested count or reported compute_seconds is not calibration.
 Sparse or stale evidence retains the old three-lease window. The worker's
 20-second heartbeat renews active leases, but the budget leaves room within
 the original TTL if the worker disappears before another heartbeat.
 """
 if ttl<=0:return 1
 ages=sorted(max(.05,float(row['submitted_at'])-float(row['leased_at']))
             for row in rows if row['segment_id']==segment_id and row['status']=='verified'
             and 0<=at-float(row['submitted_at'])<=ttl and
             math.isfinite(float(row['submitted_at'])) and math.isfinite(float(row['leased_at']))
             and float(row['submitted_at'])>=float(row['leased_at']))
 if len(ages)<4:return min(PORTABLE_PRIMARY_LEASE_LIMIT,PORTABLE_VALIDATION_LEASE_LIMIT)
 p75=ages[math.ceil(.75*len(ages))-1]
 return max(1,min(PORTABLE_VALIDATION_LEASE_LIMIT,int((ttl*.4)/p75)))

def allocate_batch(con,device_id,count,max_new=None):
 if type(count) is not int or not 1<=count<=32:raise ValueError('batch count must be 1..32')
 if max_new is None:max_new=count
 if type(max_new) is not int or not 0<=max_new<=32:raise ValueError('new lease budget must be 0..32')
 # Ordering the validation backlog can take seconds. Do it without SQLite's
 # writer; candidates are advisory and all issuance constraints are checked again.
 perf_started=time.perf_counter()
 candidates=[];selection_exhausted=True;preview_limit=0
 # A preview must not authorize primary work if another connection creates
 # higher-priority validation after the preview but before the writer lock.
 selection_data_version=con.execute('PRAGMA data_version').fetchone()[0]
 preview=con.execute('select * from devices where id=?',(device_id,)).fetchone()
 if preview is None:raise ValueError('unknown device')
 if max_new and preview['enabled'] and not preview['quarantined'] and not worker_update_required(preview)[0]:
  existing=con.execute("select count(*) from leases where device_id=? and status='leased' and purpose!='block_receipt' and expires_at>=?",(device_id,now())).fetchone()[0]
  if existing<count:
   # The old fixed 33-row preview made even one successor wait for an entire
   # validation page. Keep race slack proportional to the number of new leases
   # actually requested; writer-side recheck remains authoritative.
   needed=min(max_new,count-existing)
   preview_limit=min(33,max(4,needed*2+1))
   selection=validation_candidates(con,preview)
   try:
    for candidate,_,_ in selection:
     candidates.append(candidate)
     if len(candidates)>preview_limit-1:
      candidates.pop();selection_exhausted=False;break
   finally:selection.close()
  else:selection_exhausted=False
 # Read only the latest bounded device window before the writer lock. Verified
 # timestamps are advisory speed evidence; the writer still checks all lease,
 # contributor, replica and pending-verification invariants transactionally.
 portable_timing_rows=[]
 if any(candidate['engine']=='portable_event_v1' for candidate in candidates):
  portable_timing_rows=con.execute("""SELECT s.segment_id,s.submitted_at,s.status,l.leased_at
      FROM submissions s INDEXED BY ix_submissions_device_recent
      JOIN leases l ON l.id=s.lease_id WHERE s.device_id=?
      ORDER BY s.submitted_at DESC LIMIT 64""",(device_id,)).fetchall()
 perf_selected=time.perf_counter()
 con.execute('begin immediate')
 perf_locked=time.perf_counter()
 try:
  selection_changed=con.execute('PRAGMA data_version').fetchone()[0]!=selection_data_version
  prune_private_data(con)
  dev=con.execute('select * from devices where id=?',(device_id,)).fetchone()
  if dev is None:raise ValueError('unknown device')
  if not dev['enabled'] or dev['quarantined']:
   con.commit();return {'enabled':False,'leases':[]}
  required,minimum=worker_update_required(dev)
  if required:
   con.commit();return {'enabled':True,'update_required':True,'min_worker_version':minimum,'leases':[]}
  expire_leases(con)
  current=con.execute("select l.*,s.engine,s.label,s.config_json from leases l join segments s on s.id=l.segment_id where l.device_id=? and l.status='leased' and l.purpose!='block_receipt' order by l.leased_at,l.id",(device_id,)).fetchall()
  result=[];diagnostics={}
  for old in current:
   seg=con.execute('select * from segments where id=?',(old['segment_id'],)).fetchone()
   ok,resource,pct=device_eligible(dev,seg)
   campaign=con.execute('select status from campaigns where id=?',(seg['campaign_id'],)).fetchone()
   if not ok or campaign is None or campaign['status']!='running':
    con.execute("update leases set status='expired',expires_at=? where id=?",(now(),old['id']))
    if old['purpose']=='primary':con.execute('insert or ignore into requeue values(?,?,?,?)',(old['segment_id'],old['start_unit'],old['end_unit'],now()))
   else:result.append(lease_obj(old,resource,pct))
  # Existing reservations are replayed, never hidden by a smaller retry request.
  ttl=int(load_cfg().get('lease_seconds',900))
  # Portable primary exposure stays at three. Independently verified server
  # wall timing may allow a larger validation buffer; the requested count is
  # only an upper bound and never calibrates that buffer.
  validation_iter=iter(candidates)
  selection_refreshed=False
  replay_count=len(result)
  portable_primary_count=sum(x['engine']=='portable_event_v1' and x['purpose']=='primary' for x in result)
  portable_validation_count=sum(x['engine']=='portable_event_v1' and x['purpose']=='validation' for x in result)
  portable_validation_by_segment={}
  for lease in result:
   if lease['engine']=='portable_event_v1' and lease['purpose']=='validation':
    segment_id=lease['segment_id']
    portable_validation_by_segment[segment_id]=portable_validation_by_segment.get(segment_id,0)+1
  portable_validation_budgets={}
  while len(result)-replay_count<max_new and len(result)<count:
   try:candidate=next(validation_iter)
   except StopIteration:candidate=None
   if candidate is not None:
    seg,resource,pct=recheck_validation_candidate(con,dev,candidate)
    if seg is not None:
     if seg['engine']=='portable_event_v1':
      segment_id=seg['id']
      if segment_id not in portable_validation_budgets:
       portable_validation_budgets[segment_id]=portable_validation_lease_budget(portable_timing_rows,segment_id,ttl,now())
      if (portable_validation_count>=PORTABLE_VALIDATION_LEASE_LIMIT or
          portable_validation_by_segment.get(segment_id,0)>=portable_validation_budgets[segment_id]):break
     result.append(make_lease(con,dev,seg,seg['v_start'],seg['v_end'],'validation',ttl))
     if seg['engine']=='portable_event_v1':
      portable_validation_count+=1
      portable_validation_by_segment[segment_id]=portable_validation_by_segment.get(segment_id,0)+1
    continue
   if portable_primary_count>=PORTABLE_PRIMARY_LEASE_LIMIT:break
   if selection_changed and selection_exhausted and not selection_refreshed:
    # This is the uncommon preview/writer race. Refresh only here, after the
    # bounded advisory page is exhausted, rather than forcing a network retry
    # for every unrelated receipt committed during normal high-rate intake.
    selection_refreshed=True
    refreshed=[]
    fresh_selection=validation_candidates(con,dev)
    try:
     for fresh,_,_ in fresh_selection:
      refreshed.append(fresh)
      if len(refreshed)>preview_limit-1:
       refreshed.pop();selection_exhausted=False;break
    finally:fresh_selection.close()
    validation_iter=iter(refreshed)
    continue
   if not selection_exhausted:
    # A competing allocator may have consumed this bounded page. Refresh on the
    # next request rather than scanning again under the writer or skipping audits.
    diagnostics.update(wait_reason='validation_selection_changed',retry_after_seconds=1)
    break
   seg,start,end,resource,pct,requeued=next_primary(con,dev,diagnostics)
   if seg is None:break
   if requeued:con.execute('delete from requeue where segment_id=? and start_unit=? and end_unit=?',(seg['id'],start,end))
   else:con.execute('update segments set next_unit=? where id=?',(end,seg['id']))
   result.append(make_lease(con,dev,seg,start,end,'primary',ttl))
   if seg['engine']=='portable_event_v1':portable_primary_count+=1
  # A partial batch can still be verification-limited. Report that cause without
  # preventing the client from computing the compatible leases already returned.
  con.commit()
  perf_finished=time.perf_counter()
  if perf_finished-perf_started>.25:
   print(json.dumps({'allocation_selection_ms':round((perf_selected-perf_started)*1000,1),
    'writer_wait_ms':round((perf_locked-perf_selected)*1000,1),
    'transaction_ms':round((perf_finished-perf_locked)*1000,1),'leases':len(result)},separators=(',',':')),flush=True)
  return {'enabled':True,'leases':result,'new_lease_limit':True,**diagnostics}
 except BaseException:
  if con.in_transaction:con.rollback()
  raise


def release_batch(con,device_id,items):
    if not isinstance(items,list) or not 1<=len(items)<=32:raise ValueError('Invalid release batch')
    ids=set()
    for item in items:
        if not isinstance(item,dict) or not isinstance(item.get('lease_id'),str) or not isinstance(item.get('work_token'),str) or item['lease_id'] in ids:raise ValueError('Invalid release entry')
        ids.add(item['lease_id'])
    con.execute('begin immediate')
    try:
        rows=[]
        for item in items:
            row=con.execute('select * from leases where id=? and device_id=?',(item['lease_id'],device_id)).fetchone()
            if row is None or row['work_token']!=item['work_token']:raise ValueError('Invalid lease ownership')
            rows.append(row)
        released=[]
        for row in rows:
            if row['status']=='leased':
                con.execute("update leases set status='expired',expires_at=? where id=?",(now(),row['id']))
                if row['purpose']=='primary':
                    con.execute('insert or ignore into requeue(segment_id,start_unit,end_unit,queued_at) values(?,?,?,?)',(row['segment_id'],row['start_unit'],row['end_unit'],now()))
                released.append(row['id'])
        con.commit();return {'ok':True,'released':released}
    except BaseException:
        if con.in_transaction:con.rollback()
        raise


class Handler(BaseHTTPRequestHandler):
    server_version="EnigmaVolunteerGrid"
    sys_version=""
    def setup(self):
        super().setup()
        self.request.settimeout(15)
    def version_string(self): return "EnigmaVolunteerGrid"
    def log_message(self,fmt,*args):
        # Do not log user-controlled URLs, IPs, headers or credentials.
        pass
    def security_headers(self):
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("X-Frame-Options","DENY")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Permissions-Policy","camera=(), microphone=(), geolocation=(), usb=(), payment=()")
        self.send_header("Cross-Origin-Opener-Policy","same-origin")
        self.send_header("Cross-Origin-Resource-Policy","same-origin")
        self.send_header("Strict-Transport-Security","max-age=31536000")
        self.send_header("Content-Security-Policy","default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
    def send_json(self,code,obj,*,retry_after=None):
        data=json.dumps(obj,separators=(",",":")).encode()
        self.send_response(code);self.send_header("Content-Type","application/json");self.send_header("Cache-Control","no-store")
        if retry_after is not None:self.send_header("Retry-After",str(int(retry_after)))
        self.security_headers();self.send_header("Content-Length",str(len(data)));self.end_headers()
        try:self.wfile.write(data)
        except (BrokenPipeError,ConnectionAbortedError,ConnectionResetError):
            pass  # Client disconnected; application failures must still propagate.
    def body(self):
        if self.headers.get("Transfer-Encoding"):raise ValueError("unsupported_transfer_encoding")
        if len(self.headers.get_all("Content-Length",[]))!=1:raise ValueError("content_length_required")
        if self.headers.get("Content-Type","").split(";",1)[0].strip().lower()!="application/json":
            raise ValueError("json_content_type_required")
        cfg=load_cfg();n=int(self.headers.get("Content-Length","0"))
        mx=int(cfg.get("max_body_bytes",262144))
        if urlparse(self.path).path=="/api/work-blocks/result-groups":
            # Only the bounded grouped transport needs room for 64 receipts.
            # A local setting may lower this ceiling, never raise the protocol cap.
            mx=min(int(cfg.get("max_result_group_body_bytes",work_result_groups.MAX_BODY_BYTES)),
                   work_result_groups.MAX_BODY_BYTES)
        elif urlparse(self.path).path=="/api/device/telemetry/v1":
            mx=device_telemetry.MAX_BODY_BYTES
        if n<0 or n>mx:raise ValueError("body_too_large")
        def reject_constant(value):raise ValueError("non_finite_json")
        obj=json.loads(self.rfile.read(n) or b"{}",parse_constant=reject_constant)
        if not isinstance(obj,dict):raise ValueError("json_object_required")
        return obj
    def token(self):return self.headers.get("X-Device-Token","").strip()
    def do_GET(self):
        if not allowed_request(self):return self.send_json(429,{"error":"rate_limited"})
        u=urlparse(self.path)
        if u.path=="/":
            data=WEB.read_bytes();self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Cache-Control","no-store");self.security_headers()
            self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data);return
        if u.path in {"/style.css","/app.js"}:
            p=ROOT/"web"/u.path.lstrip("/");data=p.read_bytes()
            ctype="text/css; charset=utf-8" if u.path.endswith(".css") else "text/javascript; charset=utf-8"
            self.send_response(200);self.send_header("Content-Type",ctype);self.send_header("Cache-Control","no-store")
            self.security_headers();self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data);return
        if u.path=="/api/capabilities":
            return self.send_json(200,{'server_time_ms':int(now()*1000),
                'batch_completions':True,'release_leases':True,
                'max_completion_count':8,'max_lease_count':32,'new_lease_limit':True,
                'work_result_groups':work_result_groups.FORMAT if load_cfg().get('long_work_blocks_enabled',False) else None,
                'long_work_blocks':work_blocks.FORMAT if load_cfg().get('long_work_blocks_enabled',False) else None,
                'device_telemetry':device_telemetry.FORMAT,'telemetry_interval_seconds':30,
                'telemetry_max_body_bytes':device_telemetry.MAX_BODY_BYTES,
                'max_body_bytes':int(load_cfg().get('max_body_bytes',262144))})
        if u.path=="/health":return self.send_json(200,{"ok":True,"version":"0.5.1","time":now()})
        if u.path=="/api/register-challenge":
            con=db()
            try:return self.send_json(200,new_registration_challenge(con))
            finally:con.close()
        if u.path=="/api/public/config":
            cfg=load_cfg()
            return self.send_json(200,{"github_repo":str(cfg.get("github_repo","")),
                                       "min_worker_version":str(cfg.get("min_worker_version","")),
                                       "min_android_worker_version":str(cfg.get("min_android_worker_version",cfg.get("min_worker_version",""))),
                                       "update_check_seconds":max(900,int(cfg.get("update_check_seconds",21600)))})
        if u.path=="/api/public/status":
            payload=public_status_payload()
            return (self.send_json(200,payload) if payload is not None else
                    self.send_json(503,{"error":"public_status_refreshing"},retry_after=1))
        return self.send_json(404,{"error":"not_found"})
    def do_POST(self):
        post_started=time.perf_counter()
        if not allowed_request(self):return self.send_json(429,{"error":"rate_limited"})
        try:b=self.body()
        except Exception:return self.send_json(400,{"error":"invalid_request_body"})
        u=urlparse(self.path);block_phase={'stage':'pre_route'} if u.path=='/api/work-blocks' else None
        con=db();allocation_device=None
        try:
            if u.path=="/api/register":return self.register(con,b)
            if u.path=="/api/me":
                p=personal_payload(con,b.get("dashboard_token",""))
                if p is PERSONAL_STATS_BUSY:
                    return self.send_json(503,{"error":"personal_stats_refreshing"},retry_after=1)
                return self.send_json(200,p) if p else self.send_json(403,{"error":"invalid_dashboard_token"})
            if u.path=="/api/me/settings":return self.me_settings(con,b)
            if u.path=="/api/me/delete":return self.delete_account(con,b)
            dev=device_from_token(con,self.token())
            if not dev:return self.send_json(403,{"error":"invalid_device_token"})
            if u.path in ALLOCATION_PATHS:
                if not enter_allocation(dev['id']):
                    return self.send_json(429,{"error":"allocation_busy","retry_after_seconds":1},retry_after=1)
                allocation_device=dev['id']
            if u.path=="/api/device/telemetry/v1":
                if not dev['enabled'] or dev['quarantined']:
                    return self.send_json(403,{"error":"device_disabled"})
                private_db=Path(os.environ.get('GRID_TELEMETRY_DB',str(DATA/'device-telemetry.sqlite3')))
                try:
                    result=device_telemetry.ingest(private_db,dev['id'],b)
                except device_telemetry.TelemetryError as exc:
                    code=409 if exc.code in {'stale_telemetry','conflicting_telemetry','out_of_order_telemetry'} else 400
                    return self.send_json(code,{"error":exc.code})
                return self.send_json(200,result)
            update_device_runtime(con,dev,b)
            dev=con.execute("""select d.*,c.display_name,c.public_credit from devices d join contributors c
                               on c.id=d.contributor_id where d.id=?""",(dev["id"],)).fetchone()
            if u.path=="/api/heartbeat":
                ttl=int(load_cfg().get("lease_seconds",900))
                con.execute("update leases set expires_at=? where device_id=? and status='leased'",(now()+ttl,dev["id"]))
                required,minimum=worker_update_required(dev)
                return self.send_json(200,{"ok":True,"enabled":bool(dev["enabled"] and not dev["quarantined"]),
                                           "settings":normalize_settings(parse_json(dev["settings_json"],{})),
                                           "trust_score":dev["trust_score"],"quarantined":bool(dev["quarantined"]),
                                           "update_required":required,"min_worker_version":minimum})
            if u.path=='/api/work-blocks/result-groups':
                if not load_cfg().get('long_work_blocks_enabled',False):return self.send_json(404,{'error':'not_found'})
                # Count for rate charging. The owned block and every scientific
                # receipt are validated once by receive_groups before intake.
                groups=b.get('groups')
                if not isinstance(groups,list) or not 1<=len(groups)<=work_result_groups.MAX_GROUPS:
                    raise ValueError('Invalid group count')
                if any(not isinstance(group,list) or not 1<=len(group)<=work_result_groups.UNITS_PER_GROUP
                       for group in groups):raise ValueError('Invalid group size')
                count=sum(len(group) for group in groups)
                if count>1 and not allowed_request(self,count-1):return self.send_json(429,{'error':'rate_limited'})
                grouped_started=time.perf_counter()
                ack=work_blocks.receive_groups(con,dev['id'],b,timestamp=now())
                # 200 acknowledges durable, replay-checked intake only. The
                # persistent receipt queue is promoted by one bounded worker;
                # no verification, trust or credit is implied by this ACK.
                if any(item['status']=='received' for item in ack['results']):PROMOTION_WAKE.set()
                grouped_received=time.perf_counter()
                if grouped_received-grouped_started>.25:
                    print(json.dumps(dict(slow_result_group_intake_ms=round((grouped_received-grouped_started)*1000,1),
                        receipts=count)),flush=True)
                return self.send_json(200,ack)
            if u.path in {'/api/work-blocks','/api/work-blocks/results','/api/work-blocks/release','/api/work-blocks/status'}:
                if not load_cfg().get('long_work_blocks_enabled',False):return self.send_json(404,{'error':'not_found'})
                if b.get('format')!=work_blocks.FORMAT:raise ValueError('Unsupported block protocol')
                if u.path=='/api/work-blocks/status':
                    return self.send_json(200,work_blocks.status(con,dev['id'],b.get('blocks'),timestamp=now()))
                if u.path=='/api/work-blocks/release':
                    return self.send_json(200,work_blocks.release(con,dev['id'],b.get('block_id')))
                if u.path=='/api/work-blocks/results':
                    receipts=b.get('receipts')
                    if not isinstance(receipts,list) or not 1<=len(receipts)<=8:raise ValueError('Invalid receipt count')
                    if len(receipts)>1 and not allowed_request(self,len(receipts)-1):return self.send_json(429,{'error':'rate_limited'})
                    acknowledgement=work_blocks.receive_partial(con,dev['id'],b,timestamp=now())
                    # Legacy partial uploads share the durable-ACK contract.
                    # Their receipts enter the same restart-safe drain.
                    if any(item['status']=='received' for item in acknowledgement['results']):PROMOTION_WAKE.set()
                    return self.send_json(200,acknowledgement)
                required,minimum=worker_update_required(dev)
                if required:return self.send_json(200,{'block':None,'update_required':True,'min_worker_version':minimum})
                # Rate is derived from stored independently matched work, never
                # from an allocation request's proposed count or rate.
                # A retry recovers its original reservation even if calibration
                # evidence has since been archived. reserve still checks revocation
                # and expiry transactionally; the supplied rate is unused on replay.
                previous=con.execute('SELECT 1 FROM work_blocks WHERE device_id=? AND request_id=?',
                                     (dev['id'],b.get('request_id'))).fetchone()
                if previous:
                    return self.send_json(200,work_blocks.reserve(con,dev['id'],b.get('request_id'),
                        observed_rate=1,timestamp=now(),eligible=lambda d,s:device_eligible(d,s)[0]))
                # Do not reserve another long primary range while this contributor
                # can independently validate existing work. Legacy allocation
                # rechecks replica counts and ownership transactionally.
                block_phase['pre_route_ms']=round((time.perf_counter()-post_started)*1000,1)
                block_phase['stage']='calibration'
                phase_started=time.perf_counter()
                samples=con.execute("""SELECT s.end_unit-s.start_unit AS units,s.compute_seconds
                    FROM calibration_match_order o CROSS JOIN submissions s ON s.id=o.submission_id
                    WHERE o.device_id=? ORDER BY o.submitted_at DESC LIMIT 32""",(dev['id'],)).fetchall()
                block_phase['calibration_ms']=round((time.perf_counter()-phase_started)*1000,1)
                # Uncalibrated devices may validate existing work; primary
                # reservation below still requires eight matched samples.
                rate=sum(x['units'] for x in samples)/sum(x['compute_seconds'] for x in samples) if samples else 1.0
                preview_limit=min(work_blocks.MAX_VALIDATION_UNITS,max(1,math.ceil(rate*work_blocks.TARGET_SECONDS)))
                block_phase['stage']='validation_preview'
                phase_started=time.perf_counter()
                candidate_iter=validation_candidates(con,dev)
                first=next(candidate_iter,None)
                if first is not None:
                    row=first[0]
                    if row['engine']!='bounded_crib_v1' or row['v_end']!=row['v_start']+1:
                        candidate_iter.close()
                        return self.send_json(200,{'block':None,'wait_reason':'legacy_validation_work'})
                    try:
                        prefix=ordinary_validation_contiguous_preview(con,dev['id'],row,candidate_iter,preview_limit)
                        if prefix is None:
                            # Audit/probation ordering remains unchanged.
                            prefix=[row];next_unit=row['v_end']
                            while len(prefix)<preview_limit:
                                item=next(candidate_iter,None)
                                if item is None:break
                                next_row=item[0]
                                if next_row['id']!=row['id'] or next_row['v_start']!=next_unit or next_row['v_end']!=next_unit+1:
                                    break
                                prefix.append(next_row);next_unit+=1
                        elif not prefix:
                            # Another writer took the advisory first range.
                            prefix=[row]
                    finally:candidate_iter.close()
                    block_phase['preview_ms']=round((time.perf_counter()-phase_started)*1000,1)
                    block_phase['stage']='reserve_validation'
                    phase_started=time.perf_counter()
                    return self.send_json(200,work_blocks.reserve_validation(con,dev['id'],b.get('request_id'),
                        prefix,observed_rate=rate,timestamp=now(),
                        eligible=lambda d,s:device_eligible(d,s)[0],recheck_run=recheck_validation_run))
                if len(samples)<8:return self.send_json(200,{'block':None,'wait_reason':'block_calibration_required'})
                rate=sum(x['units'] for x in samples)/sum(x['compute_seconds'] for x in samples)
                block_phase['preview_ms']=round((time.perf_counter()-phase_started)*1000,1)
                block_phase['stage']='reserve_primary'
                phase_started=time.perf_counter()
                return self.send_json(200,work_blocks.reserve(con,dev['id'],b.get('request_id'),
                    observed_rate=rate,timestamp=now(),eligible=lambda d,s:device_eligible(d,s)[0]))
            if u.path=="/api/leases":
                if not load_cfg().get("batch_leases_enabled",False):return self.send_json(404,{"error":"not_found"})
                lease_started=time.perf_counter()
                assignment=allocate_batch(con,dev["id"],b.get("count"),b.get("max_new"))
                lease_ms=(time.perf_counter()-lease_started)*1000
                if lease_ms>250:
                    print(json.dumps({"slow_allocate_ms":round(lease_ms,1),
                        "leases":len(assignment.get("leases",[]))},separators=(",",":")),flush=True)
                return self.send_json(200,assignment)
            if u.path=="/api/lease":return self.lease(con,dev)
            if u.path=="/api/complete":return self.complete(con,dev,b)
            if u.path=="/api/leases/release":return self.send_json(200,release_batch(con,dev['id'],b.get('leases')))
            if u.path=="/api/completions":
                items=b.get('submissions')
                if not isinstance(items,list) or not 1<=len(items)<=8:raise ValueError('Invalid completion batch')
                if any(not isinstance(x,dict) or not isinstance(x.get('lease_id'),str) for x in items):raise ValueError('Invalid completion')
                if len({x['lease_id'] for x in items})!=len(items):raise ValueError('Duplicate completion entry')
                if len(items)>1 and not allowed_request(self,len(items)-1):return self.send_json(429,{'error':'rate_limited'})
                results=[]
                for item in items:
                    # Refresh trust/quarantine after each independently committed item.
                    current=con.execute('select * from devices where id=?',(dev['id'],)).fetchone()
                    try:code,value=self.complete(con,current,item,respond=lambda code,value:(code,value))
                    except (TypeError,ValueError,KeyError,OverflowError):
                        if con.in_transaction:con.rollback()
                        code,value=400,{'error':'invalid_request_fields'}
                    except sqlite3.OperationalError:
                        if con.in_transaction:con.rollback()
                        code,value=503,{'error':'temporarily_unavailable'}
                    results.append({'lease_id':item['lease_id'],'status':code,'result':value})
                return self.send_json(200,{'results':results})
            if u.path=="/api/device/settings":
                st=normalize_settings(b.get("settings",{}));con.execute("update devices set settings_json=? where id=?",
                    (json.dumps(st,separators=(",",":")),dev["id"]));return self.send_json(200,{"ok":True,"settings":st})
            if u.path=="/api/device/disable":
                con.execute("update devices set enabled=0 where id=?",(dev["id"],));return self.send_json(200,{"ok":True,"enabled":False})
            return self.send_json(404,{"error":"not_found"})
        except (TypeError,ValueError,KeyError,OverflowError):
            if con.in_transaction:con.rollback()
            return self.send_json(400,{"error":"invalid_request_fields"})
        except sqlite3.OperationalError:
            if con.in_transaction:con.rollback()
            return self.send_json(503,{"error":"temporarily_unavailable"})
        finally:
            if block_phase is not None:
                elapsed_ms=(time.perf_counter()-post_started)*1000
                if elapsed_ms>250:
                    block_phase['slow_work_block_ms']=round(elapsed_ms,1)
                    if 'phase_started' in locals():
                        block_phase['active_stage_ms']=round((time.perf_counter()-phase_started)*1000,1)
                    try:print(json.dumps(block_phase,separators=(',',':')),flush=True)
                    except OSError:pass
            if allocation_device is not None:leave_allocation(allocation_device)
            con.close()
    def register(self,con,b):
        cfg=load_cfg()
        supplied=str(b.get("registration_code",""))
        secret=str(cfg.get("registration_code",""))
        secret_ok=bool(secret and secrets.compare_digest(supplied,secret))
        if not secret_ok:
            if not cfg.get("registration_open",False):
                return self.send_json(403,{"error":"registration_closed"})
            if not verify_registration_pow(con,b):
                return self.send_json(403,{"error":"registration_proof_invalid"})
        name=b.get("display_name") or "Anonymous volunteer"
        label=b.get("device_label") or "PC"
        if not isinstance(name,str) or not isinstance(label,str):raise ValueError('invalid_display_name')
        name=name.strip()[:80];label=label.strip()[:80];join=b.get("contributor_key");new_key=dash=None
        if join:
            contributor=con.execute("select * from contributors where join_key_hash=?",(sha(join),)).fetchone()
            if not contributor:return self.send_json(403,{"error":"invalid_contributor_key"})
        else:
            cid=rid("ctr");new_key=secrets.token_urlsafe(24);dash=secrets.token_urlsafe(24)
            con.execute("""insert into contributors(id,display_name,public_credit,join_key_hash,dashboard_token_hash,created)
                           values(?,?,?,?,?,?)""",(cid,name,1 if b.get("public_credit",False) else 0,sha(new_key),sha(dash),now()))
            contributor=con.execute("select * from contributors where id=?",(cid,)).fetchone()
        token=secrets.token_urlsafe(32);did=rid("dev");meta=sanitize_meta(b.get("meta",{}));st=normalize_settings(b.get("settings",{}))
        caps=capabilities_from_meta(meta)
        con.execute("""insert into devices(id,contributor_id,label,token_hash,enabled,last_seen,meta_json,created,
                     settings_json,capabilities_json) values(?,?,?,?,1,?,?,?,?,?)""",
                    (did,contributor["id"],label,sha(token),now(),json.dumps(meta,separators=(",",":")),now(),
                     json.dumps(st,separators=(",",":")),json.dumps(caps,separators=(",",":"))))
        audit(con,"device_registered",did,capabilities=caps,settings=st)
        return self.send_json(200,{"ok":True,"contributor_id":contributor["id"],"device_id":did,"device_token":token,
                                   "contributor_key":new_key,"dashboard_token":dash,"settings":st})
    def me_settings(self,con,b):
        c=con.execute("select * from contributors where dashboard_token_hash=?",(sha(b.get("dashboard_token","")),)).fetchone()
        if not c:return self.send_json(403,{"error":"invalid_dashboard_token"})
        dev=con.execute("select * from devices where id=? and contributor_id=?",(b.get("device_id"),c["id"])).fetchone()
        if not dev:return self.send_json(404,{"error":"device_not_found"})
        st=normalize_settings(b.get("settings",{}));con.execute("update devices set settings_json=? where id=?",
             (json.dumps(st,separators=(",",":")),dev["id"]))
        audit(con,"settings_changed",dev["id"],settings=st)
        return self.send_json(200,{"ok":True,"settings":st})

    def delete_account(self,con,b):
        if b.get("confirm")!="DELETE":return self.send_json(400,{"error":"confirmation_required"})
        c=con.execute("select * from contributors where dashboard_token_hash=?",(sha(b.get("dashboard_token","")),)).fetchone()
        if not c:return self.send_json(403,{"error":"invalid_dashboard_token"})
        ids=[r["id"] for r in con.execute("select id from devices where contributor_id=?",(c["id"],))]
        private_db=Path(os.environ.get('GRID_TELEMETRY_DB',str(DATA/'device-telemetry.sqlite3')))
        # The diagnostic database has its own writer. Purge it before acquiring
        # the campaign writer so a lock cannot strand a half-deleted account.
        device_telemetry.delete_devices(private_db,ids)
        con.execute("begin immediate")
        try:
            for did in ids:
                # Keep scientific block receipts and sampling evidence, but sever
                # their link to the deleted account with a new random tombstone.
                # Missing reserved units return to the live campaign before the
                # block loses its authenticated owner.
                anonymized='deleted_'+secrets.token_hex(16)
                if con.execute("select 1 from sqlite_master where type='table' and name='work_blocks'").fetchone():
                    for block in con.execute("select * from work_blocks where device_id=? and status='reserved'",(did,)).fetchall():
                        work_blocks._return_missing(con,block,'released')
                    con.execute("update work_blocks set device_id=? where device_id=?",(anonymized,did))
                for table in ('sampling_decisions','sampling_evidence','sampling_state'):
                    con.execute(f"update {table} set device_id=? where device_id=?",(anonymized,did))
                con.execute("delete from selection_negative_identities where device_id=?",(did,))
                for l in con.execute("""select segment_id,start_unit,end_unit,purpose from leases
                                        where device_id=? and status='leased'""",(did,)).fetchall():
                    if l["purpose"]=="primary":
                        con.execute("""insert or ignore into requeue(segment_id,start_unit,end_unit,queued_at)
                                       values(?,?,?,?)""",(l["segment_id"],l["start_unit"],l["end_unit"],now()))
                con.execute("update done_ranges set device_id='deleted' where device_id=?",(did,))
                con.execute("delete from audit_log where device_id=?",(did,))
                con.execute("delete from leases where device_id=?",(did,))
            con.execute("delete from submissions where contributor_id=?",(c["id"],))
            con.execute("delete from contributions where contributor_id=?",(c["id"],))
            con.execute("delete from devices where contributor_id=?",(c["id"],))
            con.execute("delete from contributors where id=?",(c["id"],))
            con.execute("commit")
            return self.send_json(200,{"ok":True,"deleted":True})
        except Exception:
            con.execute("rollback");raise
    def lease(self,con,dev):
        # Keep the single-lease wire format, but share read-side scheduling and
        # writer-side revalidation with the batch endpoint. Old clients must not
        # hold the global writer while sorting the validation backlog either.
        assignment=allocate_batch(con,dev['id'],1,max_new=1)
        current=con.execute('select * from devices where id=?',(dev['id'],)).fetchone()
        payload={key:value for key,value in assignment.items() if key not in ('leases','new_lease_limit')}
        payload['lease']=next(iter(assignment['leases']),None)
        payload.update(settings=normalize_settings(parse_json(current['settings_json'],{})),
                       trust_score=current['trust_score'],quarantined=bool(current['quarantined']))
        return self.send_json(200,payload)
    def _prepare_completion(self,con,dev,b):
        """Validate candidate evidence without owning SQLite's writer."""
        lid=b.get("lease_id");work=b.get("work_token")
        recorded_version=str(parse_json(dev["meta_json"],{}).get("worker_version","") or "")
        # Candidate replay may compile native kernels or take seconds. Never hold
        # SQLite's sole writer while doing this CPU work: heartbeats must proceed.
        snapshot=con.execute("""select l.*,s.engine,s.config_json,s.label from leases l join segments s
                                 on s.id=l.segment_id where l.id=? and l.device_id=?""",(lid,dev["id"])).fetchone()
        if not snapshot or snapshot["work_token"]!=work:
            return None,None,None,None
        if snapshot["status"]!="leased":
            return snapshot,None,None,None
        replay_error=None;clean=None;fp=None
        validation_lease={"segment_id":snapshot["segment_id"],"start_unit":snapshot["start_unit"],
                          "end_unit":snapshot["end_unit"],"config":segment_config(snapshot)}
        try:clean,fp=validate_result(snapshot["engine"],b.get("result",{}),validation_lease)
        except Exception as exc:replay_error=str(exc)
        return snapshot,clean,fp,replay_error

    def _apply_completion(self,con,dev,b,prepared,perf):
        """Apply one checked receipt inside the caller's explicit transaction."""
        if not con.in_transaction:raise ValueError('Completion writer transaction required')
        snapshot,clean,fp,replay_error=prepared
        respond=lambda code,value:(code,value)
        if snapshot is None:return respond(403,{'error':'invalid_lease'})
        lid=b.get('lease_id');work=b.get('work_token')
        recorded_version=str(parse_json(dev['meta_json'],{}).get('worker_version','') or '')
        perf_locked=time.perf_counter()
        lease=con.execute("""select l.*,s.engine,s.config_json,s.label from leases l join segments s
                             on s.id=l.segment_id where l.id=? and l.device_id=?""",(lid,dev["id"])).fetchone()
        if not lease or lease["work_token"]!=work:
            return respond(403,{"error":"invalid_lease"})
        if lease["status"]!="leased":
            return respond(200,{"ok":True,"duplicate":True,"credited":False})
        done=con.execute("""select 1 from done_ranges where segment_id=? and start_unit=? and end_unit=?""",
                         (lease["segment_id"],lease["start_unit"],lease["end_unit"])).fetchone()
        if done:
            con.execute("update leases set status='superseded',completed_at=? where id=?",(now(),lid))
            return respond(200,{"ok":True,"duplicate":True,"credited":False})
        if any(lease[k]!=snapshot[k] for k in ("segment_id","start_unit","end_unit","engine","config_json")):
            return respond(409,{"error":"lease_changed_retry"})
        cfg=segment_config(lease)
        if replay_error is not None:
            con.execute("update leases set status='rejected',completed_at=? where id=?",(now(),lid))
            trust_penalty(con,dev["id"],True,"server_validation:"+replay_error)
            trusted_sampling.record_independent_verification(con,"rejected:"+lid,dev["id"],lease["engine"],recorded_version,matched=False,independent=True)
            revoke_trusted_results(con,dev["id"])
            if lease["purpose"]=='primary' or (lease["purpose"]=='block_receipt' and not lid.startswith('blockvalidation_')):
                con.execute("""insert or ignore into requeue(segment_id,start_unit,end_unit,queued_at) values(?,?,?,?)""",
                            (lease["segment_id"],lease["start_unit"],lease["end_unit"],now()))
            return respond(422,{"error":"result_validation_failed","detail":replay_error,"credited":False})
        raw=json.dumps(clean,separators=(",",":"),sort_keys=True);sid=rid("sub")
        wall=max(0.0,now()-float(lease["leased_at"]))
        client_secs=max(0.0,float(b.get("compute_seconds",0) or 0))
        if not math.isfinite(client_secs):raise ValueError("invalid_compute_seconds")
        safe_secs=min(client_secs,wall+5.0)
        candidate_rows=clean.get("receipt",{}).get("candidates",[]) if lease["engine"]=="bounded_crib_v1" else clean.get("candidates",[])
        safe_candidates=len(candidate_rows) if isinstance(candidate_rows,list) else 0
        con.execute("""insert into submissions(id,lease_id,segment_id,start_unit,end_unit,device_id,contributor_id,
                      fingerprint,result_json,compute_seconds,candidate_count,status,credited,submitted_at,worker_version)
                      values(?,?,?,?,?,?,?,?,?,?,?,'pending',0,?,?)""",
                    (sid,lid,lease["segment_id"],lease["start_unit"],lease["end_unit"],dev["id"],dev["contributor_id"],
                     fp,raw,safe_secs,safe_candidates,now(),recorded_version))
        con.execute("update leases set status='submitted',completed_at=? where id=?",(now(),lid))
        base=max(2,int(cfg.get("replicas_required",load_cfg().get("replicas_required",2))))
        mx=max(base,int(cfg.get("max_replicas",load_cfg().get("max_replicas",3))))
        con.execute("""insert or ignore into validations(segment_id,start_unit,end_unit,base_required,target_replicas,
                      max_replicas,status,created) values(?,?,?,?,?,?,'pending',?)""",
                    (lease["segment_id"],lease["start_unit"],lease["end_unit"],base,base,mx,now()))
        key=(lease["segment_id"],lease["start_unit"],lease["end_unit"])
        perf_inserted=time.perf_counter()
        status=None
        if load_cfg().get("trusted_sampling_enabled",False) is True:
            # Do not bypass a competing receipt or a replica already assigned.
            single=con.execute("select count(*) from submissions where segment_id=? and start_unit=? and end_unit=?",key).fetchone()[0]==1
            active=con.execute("select 1 from leases where segment_id=? and start_unit=? and end_unit=? and status='leased' limit 1",key).fetchone()
            freshdev=con.execute("select quarantined from devices where id=?",(dev["id"],)).fetchone()
            server_check=con.execute("select 1 from server_verifications where segment_id=? and start_unit=? and end_unit=? limit 1",key).fetchone()
            validation_state=con.execute("select status from validations where segment_id=? and start_unit=? and end_unit=?",key).fetchone()[0]
            if single and not active and not server_check and validation_state=='pending' and safe_candidates==0:
                decision=trusted_sampling.decide(con,sid,dev["id"],lease["engine"],recorded_version,quarantined=bool(freshdev["quarantined"]))
                if decision.action=='accepted_trusted':
                    row=con.execute("select * from submissions where id=?",(sid,)).fetchone()
                    con.execute("""insert into done_ranges(segment_id,start_unit,end_unit,lease_id,device_id,completed_at,result_json,verification_status)
                      values(?,?,?,?,?,?,?,'accepted_trusted')""",(*key,lid,dev["id"],now(),raw))
                    con.execute("""update validations set status='accepted_trusted',canonical_fingerprint=?,verified_at=NULL
                      where segment_id=? and start_unit=? and end_unit=?""",(fp,*key))
                    credit_submission(con,row,verified=False)
                    status='accepted_trusted'
        perf_sampled=time.perf_counter()
        if status is None:status=reconcile(con,*key)
        perf_reconciled=time.perf_counter()
        con.execute("delete from requeue where segment_id=? and start_unit=? and end_unit=?",
                    (lease["segment_id"],lease["start_unit"],lease["end_unit"]))
        # Pending receipts cannot close a campaign. Verified reconciliation
        # already refreshes it, so only trusted acceptance needs this call.
        if status=='accepted_trusted':
            refresh_campaign_completion(con,lease["segment_id"])
        perf.update(insert_ms=(perf_inserted-perf_locked)*1000,
                    sampling_ms=(perf_sampled-perf_inserted)*1000,
                    reconcile_ms=(perf_reconciled-perf_sampled)*1000,
                    finalize_ms=(time.perf_counter()-perf_reconciled)*1000)
        credited=bool(con.execute("select credited from submissions where id=?",(sid,)).fetchone()["credited"])
        return respond(200,{"ok":True,"duplicate":False,"credited":credited,
                                   "validation_status":status,"fingerprint":fp})

    def complete(self,con,dev,b,respond=None):
        respond=respond or self.send_json
        perf_started=time.perf_counter();prepared=self._prepare_completion(con,dev,b)
        perf_validated=time.perf_counter();con.execute('BEGIN IMMEDIATE');perf_locked=time.perf_counter();perf={}
        try:
            code,value=self._apply_completion(con,dev,b,prepared,perf)
            before_commit=time.perf_counter();con.commit();ended=time.perf_counter()
        except BaseException:
            if con.in_transaction:con.rollback()
            raise
        if ended-perf_started>.25:
            print(json.dumps(dict(slow_complete_ms=round((ended-perf_started)*1000,1),
                validate_ms=round((perf_validated-perf_started)*1000,1),
                writer_wait_ms=round((perf_locked-perf_validated)*1000,1),
                commit_ms=round((ended-before_commit)*1000,1),transaction_ms=round((ended-perf_locked)*1000,1),
                engine=prepared[0]['engine'] if prepared[0] else '',purpose=prepared[0]['purpose'] if prepared[0] else '',
                **{key:round(perf.get(key,0),1) for key in ('insert_ms','sampling_ms','reconcile_ms','finalize_ms')}),separators=(',',':')),flush=True)
        return respond(code,value)

    def complete_many(self,con,dev,submissions,*,expected_segment,block_id=None):
        """At most 64 individually checked receipts share one durable commit.

        All CPU replay is outside the writer. A rejection/quarantine commits its
        penalty and prior valid receipts, then stops; later receipts remain in
        durable intake for retry. Unexpected failures roll the entire group back.
        """
        if not 1<=len(submissions)<=64:raise ValueError('Completion group bounds')
        preparing_started=time.perf_counter()
        prepared=[self._prepare_completion(con,dev,b) for b in submissions]
        prepared_at=time.perf_counter()
        con.execute('BEGIN IMMEDIATE');results=[];started=time.perf_counter()
        phases={key:0.0 for key in ('insert_ms','sampling_ms','reconcile_ms','finalize_ms')}
        segment_checked=False
        try:
            for b,item in zip(submissions,prepared):
                current=con.execute('SELECT * FROM devices WHERE id=?',(dev['id'],)).fetchone()
                if current is None or not current['enabled'] or current['quarantined']:
                    results.append((403,{'error':'device_revoked'}));break
                # One writer transaction owns the full group: no other writer
                # can change this segment after its first in-transaction check.
                # Device state still must be refreshed for every receipt.
                if not segment_checked:
                    segment=con.execute('SELECT config_json FROM segments WHERE id=?',(expected_segment[0],)).fetchone()
                    if segment is None or json.loads(segment['config_json'])!=json.loads(expected_segment[1]):
                        results.append((409,{'error':'block_configuration_changed'}));break
                    segment_checked=True
                # Retain the block's original worker version for sampling; only
                # current authorization/state is refreshed inside the writer.
                fresh=dict(current);fresh['meta_json']=dev['meta_json']
                receipt_phases={}
                code,value=self._apply_completion(con,fresh,b,item,receipt_phases)
                for key in phases:phases[key]+=receipt_phases.get(key,0.0)
                if block_id is not None and code==200 and value.get('ok'):
                    unit=item[0]['start_unit'] if item[0] is not None else None
                    authoritative=con.execute('''SELECT 1 FROM submissions WHERE lease_id=?
                        UNION ALL SELECT 1 FROM done_ranges WHERE segment_id=? AND start_unit=? AND end_unit=? LIMIT 1''',
                        (b['lease_id'],expected_segment[0],unit,unit+1)).fetchone() if unit is not None else None
                    if not authoritative:raise ValueError('Block receipt missing scientific record')
                    con.execute('''UPDATE block_receipts SET promoted_at=?
                        WHERE block_id=? AND unit=? AND promoted_at IS NULL''',(now(),block_id,unit))
                results.append((code,value))
                if code!=200 or not value.get('ok'):break
            before_commit=time.perf_counter();con.commit();ended=time.perf_counter()
        except BaseException:
            if con.in_transaction:con.rollback()
            raise
        if ended-preparing_started>.25:
            print(json.dumps(dict(slow_complete_group_ms=round((ended-preparing_started)*1000,1),receipts=len(results),
                prepare_ms=round((prepared_at-preparing_started)*1000,1),
                writer_wait_ms=round((started-prepared_at)*1000,1),
                transaction_ms=round((before_commit-started)*1000,1),
                commit_ms=round((ended-before_commit)*1000,1),
                **{key:round(value,1) for key,value in phases.items()}),separators=(',',':')),flush=True)
        return results


def bind_host_allowed(host):
    host=str(host or "").strip().lower()
    if host in {"127.0.0.1","::1","localhost"}:return True
    return os.environ.get("GRID_ALLOW_NON_LOOPBACK","").lower() in {"1","true","yes","on"}

class PromotionFailure(Exception):
    def __init__(self,block_id,cause_type):
        super().__init__('Durable block promotion failed')
        self.block_id=block_id
        self.cause_type=cause_type


def promote_pending_once(con,handler,*,excluded_blocks=()):
    """Drain one durable batch through the unchanged scientific verifier.

    Replayed receipts, independent validation and contributor credit are
    decided by complete_many, never by the HTTP durable acknowledgement.
    """
    selected=work_blocks.pending_promotion(con,limit=16,excluded_blocks=excluded_blocks)
    if selected is None:return None
    device_id,ack=selected
    started=time.perf_counter()
    try:
        work_blocks.promote_receipts(con,device_id,ack,None,complete_many=handler.complete_many)
    except Exception as exc:
        # A committed scientific rejection is terminal evidence. Retain the
        # receipt and its unpromoted exposure, but do not retry it forever.
        if not con.in_transaction:work_blocks.mark_scientific_rejections(con,ack)
        raise PromotionFailure(ack['block_id'],type(exc).__name__) from exc
    elapsed=time.perf_counter()-started
    if elapsed>.25:
        print(json.dumps(dict(background_promotion_ms=round(elapsed*1000,1),
            receipts=len(ack['results'])),separators=(',',':')),flush=True)
    return ack['block_id']

def promotion_worker(stop):
    """Recover all eligible unpromoted receipts, including after a restart."""
    con=db();handler=object.__new__(Handler);blocked={}
    try:
        # Keep a bounded page cache only for this long-lived promotion connection.
        # The HTTP connections retain SQLite's default cache budget.
        con.execute('PRAGMA main.cache_size=-32768')
        while not stop.is_set():
            tick=time.monotonic()
            blocked={identity:until for identity,until in blocked.items() if until>tick}
            try:
                block_id=promote_pending_once(con,handler,excluded_blocks=tuple(blocked)[:64])
            except Exception as exc:
                # The exception is reported without identifiers or result data.
                # Keep durable rows retryable; avoid spinning on one bad block.
                if con.in_transaction:con.rollback()
                print(json.dumps(dict(background_promotion_error=type(exc).__name__,
                    cause_type=exc.cause_type if isinstance(exc,PromotionFailure) else type(exc).__name__)),flush=True)
                if isinstance(exc,PromotionFailure):
                    if len(blocked)>=64:blocked.pop(next(iter(blocked)))
                    blocked[exc.block_id]=tick+30
                stop.wait(.5)
                continue
            if block_id is None:
                PROMOTION_WAKE.wait(2)
                PROMOTION_WAKE.clear()
            else:
                # Let new durable intake acquire SQLite's single writer.
                stop.wait(.005)
    finally:con.close()

def main():
    from runtime_lock import database_runtime_lock
    runtime=require_database_runtime()
    if runtime is not None:
        print(json.dumps({'sqlite_runtime':runtime['sqlite']}),flush=True)
    with database_runtime_lock(DB):
        init_db();cfg=load_cfg();host=cfg.get("host","127.0.0.1");port=int(cfg.get("port",8765))
        if not bind_host_allowed(host):
            raise SystemExit("Refusing non-loopback bind. Use Tailscale Funnel; set GRID_ALLOW_NON_LOOPBACK only inside an isolated container.")
        print(f"Enigma Volunteer Grid v0.4.0 listening on http://{host}:{port}",flush=True)
        server=LimitedThreadingHTTPServer((host,port),Handler,max_workers=int(cfg.get("max_http_workers",64)))
        stop=threading.Event()
        promoter=threading.Thread(target=promotion_worker,args=(stop,),name='block-promotion',daemon=True)
        promoter.start()
        census=None
        if cfg.get('private_stack_diagnostics',False) is True:
            census=threading.Thread(target=private_stack_census_worker,args=(stop,),
                                    name='private-stack-census',daemon=True)
            census.start()
        try:server.serve_forever()
        finally:
            stop.set();PROMOTION_WAKE.set();server.server_close();promoter.join(timeout=5)
            if census is not None:census.join(timeout=5)

if __name__=="__main__":main()
