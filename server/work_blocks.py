"""Transactional reservations for the negotiated long-block protocol.

Not enabled by the HTTP handler until durable partial intake and both client
recovery paths are connected. Existing lease/verification accounting is unchanged.
"""
import hashlib
import json
import secrets
import time
from search.work_block import FORMAT, MAX_UNITS, TARGET_SECONDS, choose_units, validate_block, validate_partial_results

MAX_RESERVED_BLOCKS_PER_DEVICE = 2
MAX_UNRECEIVED_RESERVED_UNITS_PER_DEVICE = MAX_RESERVED_BLOCKS_PER_DEVICE * MAX_UNITS
MAX_VALIDATION_UNITS = 8192
MAX_VALIDATION_BLOCKS_PER_DEVICE = 2
MAX_VALIDATION_EXPOSURE_UNITS = MAX_VALIDATION_UNITS * MAX_VALIDATION_BLOCKS_PER_DEVICE


def _lease_identity(block_id, unit):
    return 'blockunit_' + hashlib.sha256((block_id + ':' + str(unit)).encode()).hexdigest()


def _validation_lease_identity(block_id,unit):
    return 'blockvalidation_' + hashlib.sha256((block_id + ':' + str(unit)).encode()).hexdigest()


def _receipt_lease_identity(block,unit):
    return (_validation_lease_identity if block['purpose']=='validation' else _lease_identity)(block['id'],unit)


def init_schema(con):
    con.execute("""CREATE TABLE IF NOT EXISTS work_blocks(
        id TEXT PRIMARY KEY, device_id TEXT NOT NULL, request_id TEXT NOT NULL,
        segment_id TEXT NOT NULL, start_unit INTEGER NOT NULL,
        end_unit INTEGER NOT NULL, config_json TEXT NOT NULL,
        created_at REAL NOT NULL, expires_at REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'reserved', worker_version TEXT NOT NULL DEFAULT '',
        UNIQUE(device_id,request_id))""")
    if 'worker_version' not in {row[1] for row in con.execute('PRAGMA table_info(work_blocks)')}:
        con.execute("ALTER TABLE work_blocks ADD COLUMN worker_version TEXT NOT NULL DEFAULT ''")
    if 'purpose' not in {row[1] for row in con.execute('PRAGMA table_info(work_blocks)')}:
        con.execute("ALTER TABLE work_blocks ADD COLUMN purpose TEXT NOT NULL DEFAULT 'primary'")
    con.execute("CREATE INDEX IF NOT EXISTS ix_work_blocks_validation_range ON work_blocks(segment_id,purpose,start_unit,end_unit,status,expires_at)")
    # Production migration should create this additive index with writers
    # stopped before activating claim-split selection. On a fresh database it
    # is tiny; IF NOT EXISTS makes subsequent starts a schema lookup.
    con.execute("""CREATE INDEX IF NOT EXISTS ix_work_blocks_validation_reserved_claim
        ON work_blocks(segment_id,start_unit,end_unit,expires_at)
        WHERE purpose='validation' AND status='reserved'""")
    con.execute("""CREATE TABLE IF NOT EXISTS block_requeue(
        source_block TEXT NOT NULL,start_unit INTEGER NOT NULL,end_unit INTEGER NOT NULL,
        PRIMARY KEY(source_block,start_unit))""")
    con.execute('CREATE INDEX IF NOT EXISTS ix_work_blocks_device ON work_blocks(device_id,status)')
    # Do not create the cross-protocol expiry index here: init_schema runs at
    # every coordinator/operations startup, and CREATE INDEX on the live leases
    # table could block service. An operator applies the additive index during
    # a measured maintenance window after a consistent database backup.
    # A pre-validation-block coordinator still runs _return_missing on every
    # reserved block. Prevent its legacy expiry/release path from turning
    # validation replicas into new primary work during code-only rollback.
    con.executescript("""
      CREATE TRIGGER IF NOT EXISTS tr_validation_block_no_primary_requeue
      BEFORE INSERT ON block_requeue
      WHEN EXISTS(SELECT 1 FROM work_blocks b WHERE b.id=NEW.source_block AND b.purpose='validation')
      BEGIN SELECT RAISE(IGNORE); END;
    """)
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='leases'").fetchone():
        con.executescript("""
          CREATE TRIGGER IF NOT EXISTS tr_validation_block_old_promotion_guard
          BEFORE INSERT ON leases
          WHEN NEW.purpose='block_receipt' AND NEW.id NOT GLOB 'blockvalidation_*' AND EXISTS(
            SELECT 1 FROM work_blocks b WHERE b.purpose='validation'
              AND b.device_id=NEW.device_id AND b.segment_id=NEW.segment_id
              AND b.start_unit<=NEW.start_unit AND b.end_unit>=NEW.end_unit)
          BEGIN SELECT RAISE(ABORT,'validation receipt requires new coordinator'); END;
        """)
    con.execute("""CREATE TABLE IF NOT EXISTS block_receipts(
        block_id TEXT NOT NULL, unit INTEGER NOT NULL, fingerprint TEXT NOT NULL,
        result_json TEXT NOT NULL, compute_seconds REAL NOT NULL, received_at REAL NOT NULL,
        verification_status TEXT NOT NULL DEFAULT 'pending', promoted_at REAL DEFAULT -1,
        PRIMARY KEY(block_id,unit))""")
    if 'received_units' not in {row[1] for row in con.execute('PRAGMA table_info(work_blocks)')}:
        # Transactional schema/data migration: a crash cannot leave a new
        # zero counter on blocks that already contain durable receipts.
        con.execute('SAVEPOINT block_receipt_counter_migration')
        try:
            con.execute("ALTER TABLE work_blocks ADD COLUMN received_units INTEGER NOT NULL DEFAULT 0")
            con.execute("""UPDATE work_blocks SET received_units=(
                SELECT count(*) FROM block_receipts r WHERE r.block_id=work_blocks.id)""")
            if con.execute("SELECT 1 FROM work_blocks WHERE received_units<0 OR received_units>end_unit-start_unit LIMIT 1").fetchone():
                raise ValueError('Invalid migrated block receipt count')
            con.execute('RELEASE block_receipt_counter_migration')
        except BaseException:
            con.execute('ROLLBACK TO block_receipt_counter_migration')
            con.execute('RELEASE block_receipt_counter_migration')
            raise
    # This counter is on the reservation path, so it must not scan historical
    # submissions or receipts on every request. All deltas share the writer
    # transaction of the scientific/intake change which causes them.
    con.execute("""CREATE TABLE IF NOT EXISTS device_work_exposure(
        device_id TEXT PRIMARY KEY,pending_units INTEGER NOT NULL DEFAULT 0,
        unpromoted_units INTEGER NOT NULL DEFAULT 0,
        CHECK(pending_units>=0),CHECK(unpromoted_units>=0))""")
    if 'validation_unpromoted_units' not in {row[1] for row in con.execute('PRAGMA table_info(device_work_exposure)')}:
        # No historical validation-purpose blocks exist before this migration.
        con.execute("ALTER TABLE device_work_exposure ADD COLUMN validation_unpromoted_units INTEGER NOT NULL DEFAULT 0 CHECK(validation_unpromoted_units>=0)")
    con.execute("CREATE TABLE IF NOT EXISTS work_exposure_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    has_submissions=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='submissions'").fetchone() is not None
    if not con.execute("SELECT 1 FROM work_exposure_meta WHERE key='promoted_backfilled_v1'").fetchone():
        # Existing receipts may already have passed through scientific intake.
        # Match their stable synthetic lease ID exactly; a same-range receipt
        # from another block/device is not evidence of this receipt's promotion.
        con.execute('SAVEPOINT block_promotion_migration')
        try:
            if 'promoted_at' not in {row[1] for row in con.execute('PRAGMA table_info(block_receipts)')}:
                # SQLite adds a constant default without rewriting 890k+ old
                # rows. Treat old rows as promoted provisionally, then mark
                # only exact synthetic lease IDs lacking a submission pending.
                con.execute('ALTER TABLE block_receipts ADD COLUMN promoted_at REAL DEFAULT -1')
            if has_submissions:
                con.create_function('_block_lease_identity',2,_lease_identity,deterministic=True)
                con.create_function('_block_validation_lease_identity',2,_validation_lease_identity,deterministic=True)
                con.execute("""UPDATE block_receipts SET promoted_at=NULL
                    WHERE promoted_at=-1 AND NOT EXISTS(
                      SELECT 1 FROM submissions s
                      WHERE s.lease_id=CASE WHEN (
                        SELECT purpose FROM work_blocks WHERE id=block_receipts.block_id)='validation'
                        THEN _block_validation_lease_identity(block_receipts.block_id,block_receipts.unit)
                        ELSE _block_lease_identity(block_receipts.block_id,block_receipts.unit) END)""")
            else:
                con.execute('UPDATE block_receipts SET promoted_at=NULL WHERE promoted_at=-1')
            con.execute("INSERT INTO work_exposure_meta(key,value) VALUES('promoted_backfilled_v1','1')")
            con.execute('RELEASE block_promotion_migration')
        except BaseException:
            con.execute('ROLLBACK TO block_promotion_migration')
            con.execute('RELEASE block_promotion_migration')
            raise
    # A durable receipt is acknowledged before scientific promotion. Build
    # this only after the additive promoted_at migration on older databases.
    con.execute("""CREATE INDEX IF NOT EXISTS ix_block_receipts_promotion
        ON block_receipts(received_at,block_id,unit)
        WHERE promoted_at IS NULL AND verification_status='pending'""")
    # Build offline before the first production restart; block_receipts may be
    # large although the pending partial index is small.
    con.execute("""CREATE INDEX IF NOT EXISTS ix_block_receipts_pending_unit
        ON block_receipts(unit,block_id)
        WHERE promoted_at IS NULL AND verification_status='pending'""")
    if has_submissions:
        con.executescript("""
        CREATE TRIGGER IF NOT EXISTS tr_work_pending_insert AFTER INSERT ON submissions
        WHEN NEW.status='pending' AND (SELECT engine FROM segments WHERE id=NEW.segment_id)='bounded_crib_v1'
        BEGIN
          INSERT OR IGNORE INTO device_work_exposure(device_id) VALUES(NEW.device_id);
          UPDATE device_work_exposure SET pending_units=pending_units+NEW.end_unit-NEW.start_unit
            WHERE device_id=NEW.device_id;
        END;
        CREATE TRIGGER IF NOT EXISTS tr_work_pending_update
        AFTER UPDATE OF status,device_id,segment_id,start_unit,end_unit ON submissions
        BEGIN
          INSERT OR IGNORE INTO device_work_exposure(device_id) VALUES(OLD.device_id);
          INSERT OR IGNORE INTO device_work_exposure(device_id) VALUES(NEW.device_id);
          UPDATE device_work_exposure SET pending_units=pending_units-
            CASE WHEN OLD.status='pending' AND (SELECT engine FROM segments WHERE id=OLD.segment_id)='bounded_crib_v1'
              THEN OLD.end_unit-OLD.start_unit ELSE 0 END WHERE device_id=OLD.device_id;
          UPDATE device_work_exposure SET pending_units=pending_units+
            CASE WHEN NEW.status='pending' AND (SELECT engine FROM segments WHERE id=NEW.segment_id)='bounded_crib_v1'
              THEN NEW.end_unit-NEW.start_unit ELSE 0 END WHERE device_id=NEW.device_id;
        END;
        CREATE TRIGGER IF NOT EXISTS tr_work_pending_delete AFTER DELETE ON submissions
        WHEN OLD.status='pending' AND (SELECT engine FROM segments WHERE id=OLD.segment_id)='bounded_crib_v1'
        BEGIN
          UPDATE device_work_exposure SET pending_units=pending_units-(OLD.end_unit-OLD.start_unit)
            WHERE device_id=OLD.device_id;
        END;
        """)
    con.executescript("""
      CREATE TRIGGER IF NOT EXISTS tr_work_unpromoted_insert AFTER INSERT ON block_receipts
      WHEN NEW.promoted_at IS NULL
      BEGIN
        INSERT OR IGNORE INTO device_work_exposure(device_id)
          SELECT device_id FROM work_blocks WHERE id=NEW.block_id;
        UPDATE device_work_exposure SET unpromoted_units=unpromoted_units+1
          WHERE device_id=(SELECT device_id FROM work_blocks WHERE id=NEW.block_id);
      END;
      CREATE TRIGGER IF NOT EXISTS tr_work_unpromoted_update AFTER UPDATE OF promoted_at ON block_receipts
      BEGIN
        INSERT OR IGNORE INTO device_work_exposure(device_id)
          SELECT device_id FROM work_blocks WHERE id=NEW.block_id;
        UPDATE device_work_exposure SET unpromoted_units=unpromoted_units+
          CASE WHEN OLD.promoted_at IS NULL AND NEW.promoted_at IS NOT NULL THEN -1
               WHEN OLD.promoted_at IS NOT NULL AND NEW.promoted_at IS NULL THEN 1 ELSE 0 END
          WHERE device_id=(SELECT device_id FROM work_blocks WHERE id=NEW.block_id);
      END;
      CREATE TRIGGER IF NOT EXISTS tr_work_unpromoted_delete AFTER DELETE ON block_receipts
      WHEN OLD.promoted_at IS NULL
      BEGIN
        UPDATE device_work_exposure SET unpromoted_units=unpromoted_units-1
          WHERE device_id=(SELECT device_id FROM work_blocks WHERE id=OLD.block_id);
      END;
      CREATE TRIGGER IF NOT EXISTS tr_work_owner_update AFTER UPDATE OF device_id ON work_blocks
      WHEN OLD.device_id!=NEW.device_id
      BEGIN
        INSERT OR IGNORE INTO device_work_exposure(device_id) VALUES(NEW.device_id);
        UPDATE device_work_exposure SET unpromoted_units=unpromoted_units-
          (SELECT count(*) FROM block_receipts WHERE block_id=NEW.id AND promoted_at IS NULL)
          WHERE device_id=OLD.device_id;
        UPDATE device_work_exposure SET unpromoted_units=unpromoted_units+
          (SELECT count(*) FROM block_receipts WHERE block_id=NEW.id AND promoted_at IS NULL)
          WHERE device_id=NEW.device_id;
      END;
    """)
    con.executescript("""
      CREATE TRIGGER IF NOT EXISTS tr_validation_unpromoted_insert AFTER INSERT ON block_receipts
      WHEN NEW.promoted_at IS NULL AND NEW.verification_status='pending'
        AND (SELECT purpose FROM work_blocks WHERE id=NEW.block_id)='validation'
      BEGIN
        INSERT OR IGNORE INTO device_work_exposure(device_id)
          SELECT device_id FROM work_blocks WHERE id=NEW.block_id;
        UPDATE device_work_exposure SET validation_unpromoted_units=validation_unpromoted_units+1
          WHERE device_id=(SELECT device_id FROM work_blocks WHERE id=NEW.block_id);
      END;
      CREATE TRIGGER IF NOT EXISTS tr_validation_unpromoted_update
      AFTER UPDATE OF promoted_at,verification_status ON block_receipts
      WHEN (SELECT purpose FROM work_blocks WHERE id=NEW.block_id)='validation'
      BEGIN
        UPDATE device_work_exposure SET validation_unpromoted_units=validation_unpromoted_units+
          CASE WHEN NEW.promoted_at IS NULL AND NEW.verification_status='pending' THEN 1 ELSE 0 END-
          CASE WHEN OLD.promoted_at IS NULL AND OLD.verification_status='pending' THEN 1 ELSE 0 END
          WHERE device_id=(SELECT device_id FROM work_blocks WHERE id=NEW.block_id);
      END;
      CREATE TRIGGER IF NOT EXISTS tr_validation_unpromoted_delete AFTER DELETE ON block_receipts
      WHEN OLD.promoted_at IS NULL AND OLD.verification_status='pending'
        AND (SELECT purpose FROM work_blocks WHERE id=OLD.block_id)='validation'
      BEGIN
        UPDATE device_work_exposure SET validation_unpromoted_units=validation_unpromoted_units-1
          WHERE device_id=(SELECT device_id FROM work_blocks WHERE id=OLD.block_id);
      END;
      CREATE TRIGGER IF NOT EXISTS tr_validation_owner_update AFTER UPDATE OF device_id ON work_blocks
      WHEN OLD.device_id!=NEW.device_id AND NEW.purpose='validation'
      BEGIN
        INSERT OR IGNORE INTO device_work_exposure(device_id) VALUES(NEW.device_id);
        UPDATE device_work_exposure SET validation_unpromoted_units=validation_unpromoted_units-
          (SELECT count(*) FROM block_receipts WHERE block_id=NEW.id AND promoted_at IS NULL
            AND verification_status='pending') WHERE device_id=OLD.device_id;
        UPDATE device_work_exposure SET validation_unpromoted_units=validation_unpromoted_units+
          (SELECT count(*) FROM block_receipts WHERE block_id=NEW.id AND promoted_at IS NULL
            AND verification_status='pending') WHERE device_id=NEW.device_id;
      END;
    """)
    # A pre-0.5 coordinator can be restarted against this additive schema
    # during rollback. Its INSERT omits both new columns. The sentinel default
    # identifies only those *new* legacy inserts; historical rows never fire an
    # INSERT trigger. Treat every new durable receipt conservatively until an
    # exact scientific submission proves promotion on the next new-code boot.
    con.execute("INSERT OR IGNORE INTO work_exposure_meta(key,value) VALUES('legacy_receipts_dirty','0')")
    if not con.execute("SELECT 1 FROM work_exposure_meta WHERE key='legacy_receipt_trigger_v2'").fetchone():
        con.execute('SAVEPOINT legacy_receipt_trigger_upgrade')
        try:
            con.execute('DROP TRIGGER IF EXISTS tr_work_legacy_receipt_insert')
            con.execute("""CREATE TRIGGER tr_work_legacy_receipt_insert
              AFTER INSERT ON block_receipts WHEN NEW.promoted_at=-1
              BEGIN
                UPDATE work_blocks SET received_units=received_units+1 WHERE id=NEW.block_id;
                UPDATE block_receipts SET promoted_at=NULL
                  WHERE block_id=NEW.block_id AND unit=NEW.unit;
                UPDATE device_work_exposure SET validation_unpromoted_units=(
                  SELECT count(*) FROM block_receipts r JOIN work_blocks b ON b.id=r.block_id
                  WHERE b.device_id=device_work_exposure.device_id AND b.purpose='validation'
                    AND r.promoted_at IS NULL AND r.verification_status='pending')
                  WHERE device_id=(SELECT device_id FROM work_blocks WHERE id=NEW.block_id)
                    AND (SELECT purpose FROM work_blocks WHERE id=NEW.block_id)='validation';
                UPDATE work_exposure_meta SET value='1' WHERE key='legacy_receipts_dirty';
              END""")
            con.execute("INSERT INTO work_exposure_meta(key,value) VALUES('legacy_receipt_trigger_v2','1')")
            con.execute('RELEASE legacy_receipt_trigger_upgrade')
        except BaseException:
            con.execute('ROLLBACK TO legacy_receipt_trigger_upgrade')
            con.execute('RELEASE legacy_receipt_trigger_upgrade')
            raise
    if not con.execute("SELECT 1 FROM work_exposure_meta WHERE key='backfilled_v1'").fetchone():
        con.execute('BEGIN IMMEDIATE')
        try:
            con.execute('DELETE FROM device_work_exposure')
            if has_submissions:
                for device_id,units in con.execute("""SELECT sub.device_id,sum(sub.end_unit-sub.start_unit)
                    FROM submissions sub JOIN segments s ON s.id=sub.segment_id
                    WHERE sub.status='pending' AND s.engine='bounded_crib_v1' GROUP BY sub.device_id"""):
                    con.execute('INSERT INTO device_work_exposure(device_id,pending_units) VALUES(?,?)',(device_id,units))
            for device_id,units in con.execute("""SELECT b.device_id,count(*) FROM block_receipts r
                JOIN work_blocks b ON b.id=r.block_id WHERE r.promoted_at IS NULL GROUP BY b.device_id"""):
                con.execute("""INSERT INTO device_work_exposure(device_id,unpromoted_units) VALUES(?,?)
                    ON CONFLICT(device_id) DO UPDATE SET unpromoted_units=excluded.unpromoted_units""",(device_id,units))
            con.execute("INSERT INTO work_exposure_meta(key,value) VALUES('backfilled_v1','1')")
            con.commit()
        except BaseException:
            if con.in_transaction:con.rollback()
            raise
    if has_submissions and con.execute("SELECT value FROM work_exposure_meta WHERE key='legacy_receipts_dirty'").fetchone()[0]=='1':
        # This scans only after a rollback actually inserted legacy receipts.
        # It is transactional and never assumes a durable receipt was accepted.
        con.create_function('_block_lease_identity',2,_lease_identity,deterministic=True)
        con.create_function('_block_validation_lease_identity',2,_validation_lease_identity,deterministic=True)
        con.execute('BEGIN IMMEDIATE')
        try:
            con.execute("""UPDATE block_receipts SET promoted_at=received_at
                WHERE promoted_at IS NULL AND EXISTS(
                  SELECT 1 FROM submissions s
                  WHERE s.lease_id=CASE WHEN (
                    SELECT purpose FROM work_blocks WHERE id=block_receipts.block_id)='validation'
                    THEN _block_validation_lease_identity(block_receipts.block_id,block_receipts.unit)
                    ELSE _block_lease_identity(block_receipts.block_id,block_receipts.unit) END)""")
            con.execute("UPDATE work_exposure_meta SET value='0' WHERE key='legacy_receipts_dirty'")
            con.commit()
        except BaseException:
            if con.in_transaction:con.rollback()
            raise


def descriptor(row):
    return dict(format=FORMAT, block_id=row['id'], engine='bounded_crib_v1',
                start_unit=row['start_unit'], end_unit=row['end_unit'],
                config=json.loads(row['config_json']))


def reserved_exposure_units(con, device_id):
    """Authoritative unreceived units still reserved to this device."""
    return con.execute("""SELECT coalesce(sum(end_unit-start_unit-received_units),0)
        FROM work_blocks WHERE device_id=? AND status='reserved' AND purpose='primary'""", (device_id,)).fetchone()[0]


def _expire_legacy_primary(con, timestamp, limit=32):
    """Return a bounded page of expired pre-block primary leases.

    Old and new clients share the segment cursor but not their requeue tables.
    A long-block-only fleet must not rely on a legacy /api/leases request to
    release old claims. This runs inside reserve's writer transaction.
    """
    if not con.in_transaction:raise ValueError('Writer transaction required')
    index=con.execute("""SELECT 1 FROM sqlite_master WHERE type='index'
        AND name='ix_leases_primary_segment_expiry'""").fetchone()
    if not index:return 0  # Existing legacy requeue is still claimable.
    # Seek each bounded segment directly. An older portable campaign can have a
    # large expired prefix; scanning it would delay bounded recovery despite a
    # LIMIT on returned rows.
    rows=[]
    for segment in con.execute("SELECT id FROM segments WHERE engine='bounded_crib_v1' ORDER BY id"):
        if len(rows)>=limit:break
        rows.extend(con.execute("""SELECT id,segment_id,start_unit,end_unit FROM leases
            INDEXED BY ix_leases_primary_segment_expiry
            WHERE segment_id=? AND status='leased' AND purpose='primary' AND expires_at<?
            ORDER BY expires_at,id LIMIT ?""",
            (segment['id'],timestamp,limit-len(rows))).fetchall())
    for row in rows:
        con.execute("UPDATE leases SET status='expired' WHERE id=? AND status='leased'",(row['id'],))
        done=con.execute("""SELECT 1 FROM done_ranges
            WHERE segment_id=? AND start_unit=? AND end_unit=?""",
            (row['segment_id'],row['start_unit'],row['end_unit'])).fetchone()
        if not done:
            con.execute("""INSERT OR IGNORE INTO requeue(segment_id,start_unit,end_unit,queued_at)
                VALUES(?,?,?,?)""",(row['segment_id'],row['start_unit'],row['end_unit'],timestamp))
    return len(rows)


def validation_claims(con, segment_id, start_unit, end_unit, *, timestamp, contributor_id=None):
    """Count live validation replicas, including durable receipts awaiting promotion.

    A received unit ceases to be an unreceived reservation. Once promoted,
    its scientific submission replaces the claim in the normal replica count.
    A rejected durable receipt holds neither a claim nor a submission.
    """
    owner=' AND d.contributor_id=?' if contributor_id is not None else ''
    reserved_args=[segment_id,start_unit,end_unit,timestamp,start_unit]
    pending_args=[start_unit,segment_id,start_unit,end_unit]
    if contributor_id is not None:
        reserved_args.append(contributor_id)
        pending_args.append(contributor_id)
    # A received unit ceases to be an unreceived reservation.  These sets are
    # disjoint even if the block remains in status='reserved' until promotion.
    reserved_sql="""SELECT count(*) FROM work_blocks b INDEXED BY ix_work_blocks_validation_reserved_claim
        JOIN devices d ON d.id=b.device_id
        WHERE b.segment_id=? AND b.purpose='validation' AND b.status='reserved'
          AND b.start_unit<=? AND b.end_unit>=? AND b.expires_at>?
          AND NOT EXISTS(SELECT 1 FROM block_receipts r WHERE r.block_id=b.id AND r.unit=?)"""+owner
    pending_sql="""SELECT count(*) FROM block_receipts r INDEXED BY ix_block_receipts_pending_unit
        CROSS JOIN work_blocks b ON b.id=r.block_id JOIN devices d ON d.id=b.device_id
        WHERE r.unit=? AND r.promoted_at IS NULL AND r.verification_status='pending'
          AND b.segment_id=? AND b.purpose='validation'
          AND b.start_unit<=? AND b.end_unit>=?"""+owner
    return con.execute('SELECT ('+reserved_sql+')+('+pending_sql+')',
                       tuple(reserved_args+pending_args)).fetchone()[0]


def validation_reserved_units(con,device_id):
    return con.execute("""SELECT coalesce(sum(end_unit-start_unit-received_units),0)
        FROM work_blocks WHERE device_id=? AND status='reserved' AND purpose='validation'""",
        (device_id,)).fetchone()[0]


def reserve_validation(con,device_id,request_id,candidates,*,observed_rate,timestamp,eligible,recheck_run):
    """Claim a bounded contiguous prefix of the existing validation queue.

    `candidates` is an advisory ordered prefix. A set-level query rechecks the
    entire prefix under one SQLite writer transaction, including contributor
    and replica independence, without an SQL call per unit.
    No primary range cursor or requeue is changed here.
    """
    if not isinstance(request_id,str) or not 1<=len(request_id)<=128 or not request_id.isascii() or not all(c.isalnum() or c in '-_' for c in request_id):
        raise ValueError('Invalid block request identity')
    if con.in_transaction:raise ValueError('Reservation requires its own transaction')
    if not candidates or len(candidates)>MAX_VALIDATION_UNITS:raise ValueError('Invalid validation prefix')
    con.execute('BEGIN IMMEDIATE')
    try:
        dev=con.execute('SELECT * FROM devices WHERE id=?',(device_id,)).fetchone()
        if dev is None or not dev['enabled'] or dev['quarantined']:raise ValueError('Device cannot reserve work')
        expire(con,timestamp)
        old=con.execute('SELECT * FROM work_blocks WHERE device_id=? AND request_id=?',(device_id,request_id)).fetchone()
        if old is not None:
            con.commit()
            return dict(block=descriptor(old),replay=True,status=old['status'],
                        valid_for_seconds=max(0,old['expires_at']-timestamp) if old['status']=='reserved' else 0)
        count=con.execute("SELECT count(*) FROM work_blocks WHERE device_id=? AND status='reserved' AND purpose='validation'",(device_id,)).fetchone()[0]
        if count>=MAX_VALIDATION_BLOCKS_PER_DEVICE:
            con.commit();return dict(block=None,wait_reason='validation_blocks_reserved')
        exposure=validation_reserved_units(con,device_id)
        backlog=con.execute('SELECT validation_unpromoted_units FROM device_work_exposure WHERE device_id=?',(device_id,)).fetchone()
        unpromoted=backlog[0] if backlog else 0
        available=MAX_VALIDATION_EXPOSURE_UNITS-exposure-unpromoted
        if available<=0:
            con.commit();return dict(block=None,wait_reason='validation_exposure_budget')
        first=candidates[0]
        if first['engine']!='bounded_crib_v1' or first['v_end']!=first['v_start']+1:
            con.commit();return dict(block=None,wait_reason='legacy_validation_work')
        if not eligible(dev,first):
            con.commit();return dict(block=None,wait_reason='validation_selection_changed')
        checked=[];config=first['config_json'];segment_id=first['id'];next_unit=first['v_start']
        requested=min(choose_units(observed_rate,len(candidates)),available,MAX_VALIDATION_UNITS)
        for candidate in candidates[:requested]:
            if candidate['id']!=segment_id or candidate['v_start']!=next_unit or candidate['v_end']!=next_unit+1 or candidate['config_json']!=config:
                break
            checked.append(candidate)
            next_unit+=1
        if not checked:
            con.commit();return dict(block=None,wait_reason='validation_selection_changed')
        # A concurrent assignment may invalidate the advisory tail. The
        # predicate is monotone for a prefix, so find the maximal safe prefix
        # in logarithmically many bounded set-level checks under this writer.
        if not recheck_run(con,dev,first,next_unit):
            low=0;high=len(checked)
            while high-low>1:
                mid=(low+high)//2
                if recheck_run(con,dev,first,first['v_start']+mid):low=mid
                else:high=mid
            checked=checked[:low]
            next_unit=first['v_start']+low
        if not checked:
            con.commit();return dict(block=None,wait_reason='validation_selection_changed')
        start=first['v_start'];end=next_unit
        block=dict(format=FORMAT,block_id='blk_'+secrets.token_hex(16),engine='bounded_crib_v1',
                   start_unit=start,end_unit=end,config=json.loads(config))
        validate_block(block)
        meta=json.loads(dev['meta_json'] or '{}') if 'meta_json' in dev.keys() else {}
        con.execute("""INSERT INTO work_blocks(id,device_id,request_id,segment_id,start_unit,end_unit,
            config_json,created_at,expires_at,worker_version,purpose)
            VALUES(?,?,?,?,?,?,?,?,?,?,'validation')""",
            (block['block_id'],device_id,request_id,segment_id,start,end,config,
             timestamp,timestamp+4*TARGET_SECONDS,str(meta.get('worker_version',''))))
        con.commit()
        return dict(block=block,replay=False,status='reserved',target_seconds=TARGET_SECONDS,
                    estimated_seconds=len(checked)/observed_rate,
                    domain_tail=len(checked)<requested,exposure_limited=len(checked)<requested,
                    valid_for_seconds=4*TARGET_SECONDS,validation_exposure_units=exposure+len(checked),
                    validation_unpromoted_units=unpromoted)
    except BaseException:
        if con.in_transaction:con.rollback()
        raise


def reserve(con, device_id, request_id, *, observed_rate, timestamp, eligible):
    """Reserve a current/next block in one writer transaction.

    observed_rate and eligible are trusted server inputs, not request fields.
    Transport retries MUST reuse request_id. A completed request is replayed too,
    so a lost response can never silently consume a second interval.
    Verification receipts remain a separate operation and never imply credit.
    """
    if not isinstance(request_id,str) or not 1<=len(request_id)<=128 or not request_id.isascii() or not all(c.isalnum() or c in '-_' for c in request_id):
        raise ValueError('Invalid block request identity')
    if con.in_transaction:raise ValueError('Reservation requires its own transaction')
    con.execute('BEGIN IMMEDIATE')
    try:
        dev=con.execute('SELECT * FROM devices WHERE id=?',(device_id,)).fetchone()
        if dev is None or not dev['enabled'] or dev['quarantined']:
            raise ValueError('Device cannot reserve work')
        expire(con,timestamp)
        _expire_legacy_primary(con,timestamp)
        old=con.execute('SELECT * FROM work_blocks WHERE device_id=? AND request_id=?',(device_id,request_id)).fetchone()
        if old is not None:
            exposure=reserved_exposure_units(con,device_id)
            con.commit()
            return dict(block=descriptor(old), replay=True, status=old['status'],
                        valid_for_seconds=max(0,old['expires_at']-timestamp) if old['status']=='reserved' else 0,
                        reserved_exposure_units=exposure)
        count=con.execute("SELECT count(*) FROM work_blocks WHERE device_id=? AND status='reserved' AND purpose='primary'",(device_id,)).fetchone()[0]
        if count>=MAX_RESERVED_BLOCKS_PER_DEVICE:
            con.commit();return dict(block=None,wait_reason='current_and_next_reserved')
        exposure=reserved_exposure_units(con,device_id)
        backlog=con.execute("""SELECT pending_units,unpromoted_units FROM device_work_exposure
            WHERE device_id=?""",(device_id,)).fetchone()
        pending_units=backlog['pending_units'] if backlog else 0
        unpromoted_units=backlog['unpromoted_units'] if backlog else 0
        remaining_exposure=MAX_UNRECEIVED_RESERVED_UNITS_PER_DEVICE-exposure-pending_units-unpromoted_units
        if remaining_exposure<=0:
            con.commit();return dict(block=None,wait_reason='verification_backlog_budget',
                reserved_exposure_units=exposure,pending_verification_units=pending_units,
                unpromoted_receipt_units=unpromoted_units)
        bounded_segments=con.execute("""SELECT s.* FROM segments s JOIN campaigns c ON c.id=s.campaign_id
            WHERE c.status='running' AND s.engine='bounded_crib_v1'
            ORDER BY s.priority,(s.next_unit-s.start_unit)*1.0/max(1,s.end_unit-s.start_unit),s.id""").fetchall()
        segments=[s for s in bounded_segments if s['next_unit']<s['end_unit']]
        returned=con.execute("""SELECT r.*,b.segment_id,b.config_json FROM block_requeue r
            JOIN work_blocks b ON b.id=r.source_block JOIN segments s ON s.id=b.segment_id
            JOIN campaigns c ON c.id=s.campaign_id WHERE c.status='running'
            ORDER BY s.priority,r.source_block,r.start_unit""").fetchall()
        choices=[(con.execute('SELECT * FROM segments WHERE id=?',(r['segment_id'],)).fetchone(),r,'block') for r in returned]
        for segment in bounded_segments:
            # The legacy queue is keyed by segment. Its earliest range remains
            # eligible even after the segment cursor has reached end_unit.
            legacy=con.execute("""SELECT start_unit,end_unit,queued_at FROM requeue
                WHERE segment_id=? ORDER BY start_unit,end_unit LIMIT 1""",(segment['id'],)).fetchone()
            if legacy is not None:choices.append((segment,legacy,'legacy'))
        choices.extend((segment,None,'cursor') for segment in segments)
        choices.sort(key=lambda choice:choice[0]['priority'])
        # Long blocks must preserve the campaign priorities used by legacy
        # allocation, including engines which do not yet support this protocol.
        other_segments=con.execute('''SELECT s.* FROM segments s JOIN campaigns c ON c.id=s.campaign_id
            WHERE c.status='running' AND s.engine!='bounded_crib_v1'
              AND (s.next_unit<s.end_unit OR EXISTS(SELECT 1 FROM requeue r WHERE r.segment_id=s.id))
            ORDER BY s.priority''').fetchall()
        other_priority=next((s['priority'] for s in other_segments if eligible(dev,s)),None)
        for segment,requeued,source in choices:
            config=json.loads(requeued['config_json'] if source=='block' else segment['config_json'])
            if 'program' not in config or not eligible(dev,segment):continue
            if other_priority is not None and other_priority<segment['priority']:
                con.commit();return dict(block=None,wait_reason='legacy_priority_work')
            start=requeued['start_unit'] if requeued else segment['next_unit']
            end=requeued['end_unit'] if requeued else segment['end_unit']
            proposed=choose_units(observed_rate,end-start)
            units=min(proposed,remaining_exposure)
            block=dict(format=FORMAT,block_id='blk_'+secrets.token_hex(16),engine='bounded_crib_v1',
                       start_unit=start,end_unit=start+units,config=config)
            validate_block(block)
            # Store only the compact range, never a million per-unit rows.
            con.execute("""INSERT INTO work_blocks(id,device_id,request_id,segment_id,start_unit,end_unit,
                config_json,created_at,expires_at,worker_version) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (block['block_id'],device_id,request_id,segment['id'],start,start+units,
                 json.dumps(config,separators=(',',':')),timestamp,timestamp+4*TARGET_SECONDS,
                 str(json.loads(dev['meta_json'] or '{}').get('worker_version','')) if 'meta_json' in dev.keys() else ''))
            if source=='block':
                con.execute('DELETE FROM block_requeue WHERE source_block=? AND start_unit=?',(requeued['source_block'],start))
                if start+units<end:
                    con.execute('INSERT INTO block_requeue VALUES(?,?,?)',(requeued['source_block'],start+units,end))
            elif source=='legacy':
                con.execute('DELETE FROM requeue WHERE segment_id=? AND start_unit=? AND end_unit=?',
                            (segment['id'],start,end))
                if start+units<end:
                    con.execute('INSERT INTO requeue VALUES(?,?,?,?)',
                                (segment['id'],start+units,end,requeued['queued_at']))
            else:con.execute('UPDATE segments SET next_unit=? WHERE id=?',(start+units,segment['id']))
            con.commit()
            return dict(block=block,replay=False,status='reserved',target_seconds=TARGET_SECONDS,
                        estimated_seconds=units/observed_rate,domain_tail=end-start<observed_rate*TARGET_SECONDS,
                        exposure_limited=units<proposed,
                        valid_for_seconds=4*TARGET_SECONDS,
                        reserved_exposure_units=exposure+units,
                        pending_verification_units=pending_units,
                        unpromoted_receipt_units=unpromoted_units)
        # Long-block clients must fall back to legacy allocation when only
        # compatible non-block engines still have work.
        con.commit();return dict(block=None,wait_reason='legacy_priority_work' if other_priority is not None else 'no_compatible_work')
    except BaseException:
        if con.in_transaction:con.rollback()
        raise


def receive_partial(con,device_id,payload,*,timestamp):
    """Persist replay-checked partial results; acknowledgement does not verify work.

    Candidate replay occurs before acquiring the writer. Ownership and revocation
    are checked again inside it. Retry of an identical receipt is idempotent.
    """
    if con.in_transaction:raise ValueError('Intake requires its own transaction')
    if not isinstance(payload,dict):raise ValueError('Invalid partial results')
    row=con.execute('SELECT * FROM work_blocks WHERE id=? AND device_id=?',
                    (payload.get('block_id'),device_id)).fetchone()
    if row is None:raise ValueError('Unknown owned block')
    block=descriptor(row)
    validate_partial_results(block,payload)
    return _receive_validated(con,device_id,block,payload['receipts'],timestamp=timestamp)


def receive_groups(con,device_id,payload,*,timestamp):
    """One durable intake for the bounded, fully validated grouped packet."""
    from search.work_result_groups import validate_groups
    if con.in_transaction:raise ValueError('Intake requires its own transaction')
    row=con.execute('SELECT * FROM work_blocks WHERE id=? AND device_id=?',
                    (payload.get('block_id'),device_id)).fetchone()
    if row is None:raise ValueError('Unknown owned block')
    block=descriptor(row);validate_groups(block,payload)
    return _receive_validated(con,device_id,block,[entry for group in payload['groups'] for entry in group],timestamp=timestamp)


def pending_promotion(con, *, limit=16, excluded_blocks=()):
    """Select a bounded, eligible batch for durable scientific handoff.

    The receipt rows themselves are the recovery queue. The owner may have
    been revoked after receipt intake; never promote on its behalf then.
    """
    if not 1 <= limit <= 64 or len(excluded_blocks) > 64:
        raise ValueError('Invalid promotion bounds')
    excluded=tuple(excluded_blocks)
    clause=(' AND r.block_id NOT IN ('+','.join('?' for _ in excluded)+')') if excluded else ''
    rows=con.execute('''SELECT r.block_id,r.unit,b.device_id FROM block_receipts r
        JOIN work_blocks b ON b.id=r.block_id
        JOIN devices d ON d.id=b.device_id
        WHERE r.promoted_at IS NULL AND r.verification_status='pending'
          AND d.enabled=1 AND d.quarantined=0'''+clause+'''
        ORDER BY r.received_at,r.block_id,r.unit LIMIT ?''',(*excluded,limit)).fetchall()
    if not rows:return None
    block_id=rows[0]['block_id'];device_id=rows[0]['device_id']
    # Keep one scientific configuration and owner per complete_many call.
    units=[row['unit'] for row in rows if row['block_id']==block_id]
    return device_id,dict(block_id=block_id,
                          results=[dict(unit=unit,status='received') for unit in units])


def mark_scientific_rejections(con,acknowledgement):
    """Retain invalid durable evidence while preventing a poison retry loop.

    Only a committed rejected internal lease proves the verifier has already
    applied its penalty. Other failures stay pending and retryable.
    """
    if con.in_transaction:raise ValueError('Rejection marking requires its own transaction')
    con.execute('BEGIN IMMEDIATE')
    try:
        changed=0
        block=con.execute('SELECT * FROM work_blocks WHERE id=?',(acknowledgement['block_id'],)).fetchone()
        if block is None:raise ValueError('Missing block for rejection marking')
        for item in acknowledgement['results']:
            if item['status']!='received':continue
            lease_id=_receipt_lease_identity(block,item['unit'])
            row=con.execute('SELECT status FROM leases WHERE id=?',(lease_id,)).fetchone()
            if row is not None and row['status']=='rejected':
                changed+=con.execute('''UPDATE block_receipts SET verification_status='rejected'
                    WHERE block_id=? AND unit=? AND promoted_at IS NULL
                      AND verification_status='pending' ''',
                    (acknowledgement['block_id'],item['unit'])).rowcount
        con.commit();return changed
    except BaseException:
        if con.in_transaction:con.rollback()
        raise


def promotion_metrics(con, *, timestamp):
    """Bounded private dashboard counters; never count the receipt table."""
    total=con.execute('''SELECT coalesce(sum(unpromoted_units),0)
        FROM device_work_exposure''').fetchone()[0]
    oldest=con.execute('''SELECT received_at FROM block_receipts
        WHERE promoted_at IS NULL AND verification_status='pending'
        ORDER BY received_at,block_id,unit LIMIT 1''').fetchone()
    devices=[dict(device_id=row[0],unpromoted_units=row[1]) for row in con.execute('''
        SELECT device_id,unpromoted_units FROM device_work_exposure
        WHERE unpromoted_units>0 ORDER BY unpromoted_units DESC LIMIT 20''')]
    return dict(durable_unpromoted_units=total,
                oldest_pending_age_seconds=max(0.0,timestamp-oldest[0]) if oldest else None,
                top_devices=devices)


def _receive_validated(con,device_id,block,receipts,*,timestamp):
    # Private boundary: callers validate every receipt and the packet first.
    prepared=[]
    for entry in receipts:
        encoded=json.dumps(entry['result'],sort_keys=True,separators=(',',':'),allow_nan=False)
        prepared.append((entry,encoded,hashlib.sha256(encoded.encode()).hexdigest()))
    con.execute('BEGIN IMMEDIATE')
    try:
        dev=con.execute('SELECT * FROM devices WHERE id=?',(device_id,)).fetchone()
        current=con.execute('SELECT * FROM work_blocks WHERE id=? AND device_id=?',
                            (block['block_id'],device_id)).fetchone()
        if dev is None or not dev['enabled'] or dev['quarantined'] or current is None:
            raise ValueError('Device or block revoked')
        if descriptor(current)!=block:raise ValueError('Block changed during validation')
        results=[];new_count=0
        for entry,encoded,fingerprint in prepared:
            old=con.execute('SELECT fingerprint FROM block_receipts WHERE block_id=? AND unit=?',
                            (block['block_id'],entry['unit'])).fetchone()
            if old is not None:
                status='received' if old['fingerprint']==fingerprint else 'conflict'
            elif current['status']!='reserved' or timestamp>current['expires_at']:
                status='expired'
            else:
                con.execute("""INSERT INTO block_receipts(block_id,unit,fingerprint,result_json,
                    compute_seconds,received_at,promoted_at) VALUES(?,?,?,?,?,?,NULL)""",
                    (block['block_id'],entry['unit'],fingerprint,encoded,entry['compute_seconds'],timestamp))
                new_count+=1
                status='received'
            results.append(dict(unit=entry['unit'],status=status))
        if new_count:
            con.execute('UPDATE work_blocks SET received_units=received_units+? WHERE id=?',
                        (new_count,block['block_id']))
        count=current['received_units']+new_count
        if count==block['end_unit']-block['start_unit']:
            con.execute("UPDATE work_blocks SET status='submitted' WHERE id=? AND status='reserved'",(block['block_id'],))
        con.commit()
        return dict(block_id=block['block_id'],results=results)
    except BaseException:
        if con.in_transaction:con.rollback()
        raise


def _return_missing(con,row,status):
    if not con.in_transaction:raise ValueError('Writer transaction required')
    if row['status']!='reserved':return
    if row['purpose']=='validation':
        con.execute('UPDATE work_blocks SET status=? WHERE id=?',(status,row['id']))
        return
    cursor=row['start_unit']
    for receipt in con.execute('SELECT unit FROM block_receipts WHERE block_id=? ORDER BY unit',(row['id'],)):
        unit=receipt['unit']
        if cursor<unit:con.execute('INSERT INTO block_requeue VALUES(?,?,?)',(row['id'],cursor,unit))
        cursor=unit+1
    if cursor<row['end_unit']:con.execute('INSERT INTO block_requeue VALUES(?,?,?)',(row['id'],cursor,row['end_unit']))
    con.execute('UPDATE work_blocks SET status=? WHERE id=?',(status,row['id']))


def expire(con,timestamp):
    if not con.in_transaction:raise ValueError('Writer transaction required')
    for row in con.execute("SELECT * FROM work_blocks WHERE status='reserved' AND expires_at<?",(timestamp,)).fetchall():
        _return_missing(con,row,'expired')


def release(con,device_id,block_id):
    if con.in_transaction:raise ValueError('Release requires its own transaction')
    con.execute('BEGIN IMMEDIATE')
    try:
        row=con.execute('SELECT * FROM work_blocks WHERE id=? AND device_id=?',(block_id,device_id)).fetchone()
        if row is None:raise ValueError('Unknown owned block')
        _return_missing(con,row,'released')
        con.commit();return dict(block_id=block_id,released=True)
    except BaseException:
        if con.in_transaction:con.rollback()
        raise


def promote_receipts(con, device_id, acknowledgement, complete, complete_many=None):
    """Feed durable receipts through the existing independent-verification path.

    Stable internal lease identities make retries safe across a crash after
    submission commit but before HTTP acknowledgement. No per-unit network call.
    Receipt persistence is deliberately not a verification or credit decision.
    """
    received=[item for item in acknowledgement['results'] if item['status']=='received']
    if not received:return acknowledgement
    prepared=[]
    # The stable internal leases can share a durable commit. Validation/replay
    # still occurs afterwards, outside this writer transaction, per receipt.
    con.execute('BEGIN IMMEDIATE')
    try:
        block = con.execute('SELECT * FROM work_blocks WHERE id=? AND device_id=?',
                            (acknowledgement['block_id'], device_id)).fetchone()
        dev = con.execute('SELECT * FROM devices WHERE id=?', (device_id,)).fetchone()
        if block is None or dev is None or not dev['enabled'] or dev['quarantined']:
            raise ValueError('Device or block revoked')
        segment = con.execute('SELECT * FROM segments WHERE id=?', (block['segment_id'],)).fetchone()
        if segment is None or json.loads(segment['config_json']) != json.loads(block['config_json']):
            raise ValueError('Block configuration changed')
        for item in received:
            receipt = con.execute('SELECT * FROM block_receipts WHERE block_id=? AND unit=?',
                                  (block['id'], item['unit'])).fetchone()
            if receipt is None:
                raise ValueError('Missing durable block receipt')
            lease_id = _receipt_lease_identity(block,item['unit'])
            con.execute("""INSERT OR IGNORE INTO leases(id,segment_id,device_id,start_unit,end_unit,
                work_token,status,leased_at,expires_at,purpose)
                VALUES(?,?,?,?,?,?,'leased',?,?,?)""",
                (lease_id,block['segment_id'],device_id,item['unit'],item['unit']+1,
                 secrets.token_hex(32),block['created_at'],block['expires_at'],'block_receipt'))
            lease = con.execute('SELECT * FROM leases WHERE id=?',(lease_id,)).fetchone()
            if (lease['device_id'],lease['segment_id'],lease['start_unit'],lease['end_unit']) != (
                    device_id,block['segment_id'],item['unit'],item['unit']+1):
                raise ValueError('Internal block lease conflict')
            submission = dict(lease_id=lease_id,work_token=lease['work_token'],
                              compute_seconds=receipt['compute_seconds'],result=json.loads(receipt['result_json']))
            prepared.append((item,submission))
        con.commit()
    except BaseException:
        if con.in_transaction:con.rollback()
        raise
    if complete_many is not None:
        if len(prepared)>64:raise ValueError('Promotion batch bounds')
        original_device=dict(dev)
        metadata=json.loads(original_device['meta_json'] or '{}');metadata['worker_version']=block['worker_version']
        original_device['meta_json']=json.dumps(metadata)
        responses=complete_many(con,original_device,[submission for _,submission in prepared],
            expected_segment=(block['segment_id'],block['config_json']),block_id=block['id'])
        if len(responses)!=len(prepared):raise ValueError('Block promotion stopped after rejection or revocation')
        promoted=[(item,submission,code,value) for (item,submission),(code,value) in zip(prepared,responses)]
    else:
        promoted=[]
        for item,submission in prepared:
            # Preserve legacy rechecks when using the one-receipt callback.
            dev=con.execute('SELECT * FROM devices WHERE id=?',(device_id,)).fetchone()
            segment=con.execute('SELECT config_json FROM segments WHERE id=?',(block['segment_id'],)).fetchone()
            if dev is None or not dev['enabled'] or dev['quarantined']:raise ValueError('Device or block revoked')
            if segment is None or json.loads(segment['config_json'])!=json.loads(block['config_json']):raise ValueError('Block configuration changed')
            original_device=dict(dev);metadata=json.loads(original_device['meta_json'] or '{}')
            metadata['worker_version']=block['worker_version'];original_device['meta_json']=json.dumps(metadata)
            code,value=complete(con,original_device,submission)
            submitted=con.execute('SELECT 1 FROM submissions WHERE lease_id=?',(submission['lease_id'],)).fetchone()
            done=con.execute('SELECT 1 FROM done_ranges WHERE segment_id=? AND start_unit=? AND end_unit=?',(block['segment_id'],item['unit'],item['unit']+1)).fetchone()
            if code!=200 or not value.get('ok') or not (submitted or done):raise ValueError('Block receipt could not enter verification')
            promoted.append((item,submission,code,value))
    if complete_many is not None:
        # complete_many verifies an authoritative submission/done range and
        # marks promoted_at in the *same committed transaction*. Do not trust
        # its response or marker alone: confirm both for every unit in one SQL
        # statement, including a retry after a lost commit acknowledgement.
        pairs=[(item['unit'],submission['lease_id']) for item,submission,_,_ in promoted]
        units=[unit for unit,_ in pairs]
        if (len(set(units))!=len(units) or
                any(code!=200 or not value.get('ok') for _,_,code,value in promoted)):
            raise ValueError('Block receipt could not enter verification')
        expected=','.join('(?,?)' for _ in pairs)
        binds=[value for pair in pairs for value in pair]
        authoritative=con.execute('WITH expected(unit,lease_id) AS (VALUES '+expected+
            ''') SELECT count(*) FROM expected e
                JOIN block_receipts r ON r.block_id=? AND r.unit=e.unit
                LEFT JOIN submissions s ON s.lease_id=e.lease_id
                LEFT JOIN done_ranges d ON d.segment_id=?
                  AND d.start_unit=e.unit AND d.end_unit=e.unit+1
                WHERE r.promoted_at IS NOT NULL AND (s.id IS NOT NULL OR d.segment_id IS NOT NULL)''',
            (*binds,block['id'],block['segment_id'])).fetchone()[0]
        if authoritative!=len(pairs):
            raise ValueError('Block receipt missing atomic scientific promotion')
    else:
        for item,submission,code,value in promoted:
            lease_id=submission['lease_id']
            # A legacy duplicate acknowledgement alone is not evidence of
            # intake: an expired lease may also return it.
            submitted=con.execute('SELECT 1 FROM submissions WHERE lease_id=?',(lease_id,)).fetchone()
            done=con.execute('SELECT 1 FROM done_ranges WHERE segment_id=? AND start_unit=? AND end_unit=?',
                             (block['segment_id'],item['unit'],item['unit']+1)).fetchone()
            if code!=200 or not value.get('ok') or not (submitted or done):
                raise ValueError('Block receipt could not enter verification')
    # Transition the durable intake counter only after each receipt has an
    # authoritative submission or done range. A crash before this transaction
    # leaves a conservative unpromoted count; replay can finish it safely.
    if complete_many is None:
        con.execute('BEGIN IMMEDIATE')
        try:
            con.executemany("""UPDATE block_receipts SET promoted_at=?
                WHERE block_id=? AND unit=? AND promoted_at IS NULL""",
                [(time.time(),block['id'],item['unit']) for item,_,_,_ in promoted])
            con.commit()
        except BaseException:
            if con.in_transaction:con.rollback()
            raise
    return acknowledgement


def status(con,device_id,identities,*,timestamp):
    if not isinstance(identities,list) or len(identities)>10 or any(not isinstance(x,str) for x in identities) or len(set(identities))!=len(identities):
        raise ValueError('Invalid block status request')
    con.execute('BEGIN IMMEDIATE')
    try:
        dev=con.execute('SELECT enabled,quarantined FROM devices WHERE id=?',(device_id,)).fetchone()
        if dev is None or not dev['enabled'] or dev['quarantined']:raise ValueError('Device revoked')
        rows=[]
        for identity in identities:
            row=con.execute('SELECT * FROM work_blocks WHERE id=? AND device_id=?',(identity,device_id)).fetchone()
            if row is None:raise ValueError('Unknown owned block')
            if row['status']=='reserved' and row['expires_at']<timestamp:
                _return_missing(con,row,'expired')
                row=con.execute('SELECT * FROM work_blocks WHERE id=?',(identity,)).fetchone()
            rows.append(dict(block_id=identity,status=row['status'],valid_for_seconds=max(0,row['expires_at']-timestamp)))
        con.commit();return dict(blocks=rows)
    except BaseException:
        if con.in_transaction:con.rollback()
        raise
