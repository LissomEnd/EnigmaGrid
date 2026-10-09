"""Bounded, disposable device diagnostics, isolated from campaign accounting.

Nothing in this module allocates work, changes trust, or credits a submission.
The caller authenticates a device token before passing its server-side device ID.
"""

import hashlib
import json
import math
import re
import sqlite3
import threading
import time
from pathlib import Path

FORMAT = "device_telemetry_v1"
MAX_BODY_BYTES = 8192
MAX_BUCKETS = 12
BUCKET_MS = 5000
DETAIL_RETENTION_MS = 7 * 86400 * 1000
MINUTE_RETENTION_MS = 30 * 86400 * 1000
MAX_AGE_MS = 24 * 3600 * 1000
MAX_FUTURE_MS = 2 * 60 * 1000
_SESSION = re.compile(r"[A-Za-z0-9_-]{16,64}\Z")
_SCOPES = {"process", "device", "system", "unknown"}
_COUNTERS = {"jobs_done": 10**9, "units_done": 10**12,
             "receipts_acked": 10**9, "verified_acked": 10**9,
             "trusted_acked": 10**9}
_DURATIONS = {"compute_ms", "persist_ms", "upload_ms", "lease_ms"}
_QUEUES = {"ready_jobs", "pending_receipts"}
_PERCENTAGES = {"cpu_percent", "gpu_percent"}
_TEMPERATURES = {"cpu_temp_c", "gpu_temp_c", "battery_temp_c"}
_BUCKET_KEYS = ({"start_ms", "duration_ms", "samples", "memory_bytes", "wait_reason"}
                | set(_COUNTERS) | _DURATIONS | _QUEUES | _PERCENTAGES | _TEMPERATURES)
_TOP_KEYS = {"format", "session_id", "seq", "worker_version", "backend",
             "cpu_scope", "gpu_scope", "cpu_provider", "gpu_provider", "buckets"}
_SCHEMA_LOCK = threading.Lock()
_READY_PATHS = set()


class TelemetryError(ValueError):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _integer(value, maximum):
    return type(value) is int and 0 <= value <= maximum


def _finite(value, lower, upper):
    return type(value) in (int, float) and math.isfinite(value) and lower <= value <= upper


def _ascii(value, maximum):
    return isinstance(value, str) and len(value) <= maximum and value.isascii() and all(32 <= ord(ch) <= 126 for ch in value)


def validate(payload, *, now_ms=None):
    """Return canonicalized input after strict shape, magnitude and time checks."""
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    if not isinstance(payload, dict) or set(payload) - _TOP_KEYS:
        raise TelemetryError("invalid_telemetry", "Invalid top-level fields")
    if payload.get("format") != FORMAT:
        raise TelemetryError("invalid_telemetry", "Unsupported telemetry format")
    session = payload.get("session_id")
    if not isinstance(session, str) or not _SESSION.fullmatch(session):
        raise TelemetryError("invalid_telemetry", "Invalid session ID")
    if not _integer(payload.get("seq"), (1 << 63) - 1):
        raise TelemetryError("invalid_telemetry", "Invalid sequence")
    for key in ("worker_version", "backend", "cpu_provider", "gpu_provider"):
        if key in payload and not _ascii(payload[key], 64):
            raise TelemetryError("invalid_telemetry", "Invalid device description")
    for key in ("cpu_scope", "gpu_scope"):
        if key in payload and payload[key] not in _SCOPES:
            raise TelemetryError("invalid_telemetry", "Invalid sensor scope")
    buckets = payload.get("buckets")
    if not isinstance(buckets, list) or not 1 <= len(buckets) <= MAX_BUCKETS:
        raise TelemetryError("invalid_telemetry", "Invalid bucket count")
    previous = None
    for bucket in buckets:
        if not isinstance(bucket, dict) or set(bucket) - _BUCKET_KEYS:
            raise TelemetryError("invalid_telemetry", "Invalid bucket fields")
        start = bucket.get("start_ms")
        if not _integer(start, (1 << 63) - 1) or start % BUCKET_MS:
            raise TelemetryError("invalid_telemetry", "Invalid bucket time")
        if start < now_ms - MAX_AGE_MS or start > now_ms + MAX_FUTURE_MS:
            raise TelemetryError("stale_telemetry", "Bucket outside freshness window")
        if previous is not None and start < previous + BUCKET_MS:
            raise TelemetryError("invalid_telemetry", "Buckets overlap or are unsorted")
        previous = start
        if bucket.get("duration_ms") != BUCKET_MS or type(bucket.get("duration_ms")) is not int:
            raise TelemetryError("invalid_telemetry", "Invalid bucket duration")
        if "samples" in bucket and not (type(bucket["samples"]) is int and 1 <= bucket["samples"] <= 5):
            raise TelemetryError("invalid_telemetry", "Invalid sample count")
        for key, maximum in _COUNTERS.items():
            if key in bucket and not _integer(bucket[key], maximum):
                raise TelemetryError("invalid_telemetry", "Invalid counter")
        for key in _DURATIONS:
            if key in bucket and not _integer(bucket[key], 10**9):
                raise TelemetryError("invalid_telemetry", "Invalid duration")
        for key in _QUEUES:
            if key in bucket and not _integer(bucket[key], 10**9):
                raise TelemetryError("invalid_telemetry", "Invalid queue length")
        for key in _PERCENTAGES:
            if key in bucket and not _finite(bucket[key], 0, 100):
                raise TelemetryError("invalid_telemetry", "Invalid utilization")
        for key in _TEMPERATURES:
            if key in bucket and not _finite(bucket[key], -30, 150):
                raise TelemetryError("invalid_telemetry", "Invalid temperature")
        if "memory_bytes" in bucket and not _integer(bucket["memory_bytes"], 1 << 50):
            raise TelemetryError("invalid_telemetry", "Invalid memory reading")
        if "wait_reason" in bucket and not _ascii(bucket["wait_reason"], 48):
            raise TelemetryError("invalid_telemetry", "Invalid wait reason")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=True)
    if len(canonical.encode("utf-8")) > MAX_BODY_BYTES:
        raise TelemetryError("invalid_telemetry", "Telemetry body too large")
    return canonical


def _connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _SCHEMA_LOCK:
        if str(path.resolve()) not in _READY_PATHS:
            con = sqlite3.connect(path, timeout=0.25, isolation_level=None)
            try:
                con.execute("PRAGMA journal_mode=WAL")
                con.execute("PRAGMA busy_timeout=250")
                con.executescript("""
                    CREATE TABLE IF NOT EXISTS packets (
                      device_id TEXT NOT NULL, session_id TEXT NOT NULL, seq INTEGER NOT NULL,
                      payload_hash TEXT NOT NULL, received_ms INTEGER NOT NULL,
                      metadata_json TEXT NOT NULL,
                      PRIMARY KEY(device_id,session_id,seq));
                    CREATE INDEX IF NOT EXISTS ix_packets_received ON packets(received_ms);
                    CREATE TABLE IF NOT EXISTS buckets (
                      device_id TEXT NOT NULL, session_id TEXT NOT NULL,
                      start_ms INTEGER NOT NULL, seq INTEGER NOT NULL,
                      received_ms INTEGER NOT NULL, payload_json TEXT NOT NULL,
                      PRIMARY KEY(device_id,session_id,start_ms));
                    CREATE INDEX IF NOT EXISTS ix_buckets_received ON buckets(received_ms);
                    CREATE INDEX IF NOT EXISTS ix_buckets_device_time ON buckets(device_id,start_ms);
                    CREATE TABLE IF NOT EXISTS minute_rollups (
                      device_id TEXT NOT NULL, minute_ms INTEGER NOT NULL,
                      payload_json TEXT NOT NULL,
                      PRIMARY KEY(device_id,minute_ms));
                    CREATE INDEX IF NOT EXISTS ix_rollups_minute ON minute_rollups(minute_ms);
                """)
            finally:
                con.close()
            _READY_PATHS.add(str(path.resolve()))
    con = sqlite3.connect(path, timeout=0.25, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=250")
    return con


def _rollup(con, device_id, bucket):
    minute = bucket["start_ms"] // 60000 * 60000
    old = con.execute("SELECT payload_json FROM minute_rollups WHERE device_id=? AND minute_ms=?",
                      (device_id, minute)).fetchone()
    report = json.loads(old[0]) if old else {"bucket_count": 0, "totals": {}, "gauges": {},
                                            "latest": {}, "wait_reasons": {}}
    report["bucket_count"] += 1
    for key in set(_COUNTERS) | _DURATIONS:
        if key in bucket:
            item = report["totals"].setdefault(key, {"sum": 0, "present_buckets": 0})
            item["sum"] += bucket[key]
            item["present_buckets"] += 1
    samples = bucket.get("samples", 1)
    for key in _PERCENTAGES | _TEMPERATURES | {"memory_bytes"}:
        if key in bucket:
            item = report["gauges"].setdefault(key, {"weighted_sum": 0, "samples": 0})
            item["weighted_sum"] += bucket[key] * samples
            item["samples"] += samples
    for key in _QUEUES:
        if key in bucket:
            report["latest"][key] = bucket[key]
    if "wait_reason" in bucket:
        reasons = report["wait_reasons"]
        reasons[bucket["wait_reason"]] = reasons.get(bucket["wait_reason"], 0) + 1
    con.execute("""INSERT INTO minute_rollups(device_id,minute_ms,payload_json) VALUES(?,?,?)
        ON CONFLICT(device_id,minute_ms) DO UPDATE SET payload_json=excluded.payload_json""",
        (device_id, minute, json.dumps(report, sort_keys=True, separators=(",", ":"))))


def _prune(con, path, now_ms):
    # A small deletion allowance per accepted packet scales with the arrival
    # rate, so retention can keep up even with hundreds of devices. It stays
    # entirely inside the separate disposable telemetry database.
    for table, cutoff in (("buckets", now_ms - DETAIL_RETENTION_MS),
                          ("packets", now_ms - DETAIL_RETENTION_MS),
                          ("minute_rollups", now_ms - MINUTE_RETENTION_MS)):
        column = "minute_ms" if table == "minute_rollups" else "received_ms"
        con.execute(f"DELETE FROM {table} WHERE rowid IN "
                    f"(SELECT rowid FROM {table} WHERE {column}<? LIMIT 100)", (cutoff,))


def ingest(path, device_id, payload, *, now_ms=None):
    """Commit one packet and its minute rollups idempotently in the private DB."""
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    canonical = validate(payload, now_ms=now_ms)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    con = _connect(path)
    try:
        con.execute("BEGIN IMMEDIATE")
        key = (device_id, payload["session_id"], payload["seq"])
        old = con.execute("SELECT payload_hash FROM packets WHERE device_id=? AND session_id=? AND seq=?", key).fetchone()
        if old is not None:
            if old["payload_hash"] != digest:
                raise TelemetryError("conflicting_telemetry", "Sequence replay has different content")
            con.commit()
            return {"ok": True, "accepted": len(payload["buckets"]), "duplicate": True,
                    "server_time_ms": now_ms}
        latest = con.execute("SELECT max(seq) FROM packets WHERE device_id=? AND session_id=?", key[:2]).fetchone()[0]
        if latest is not None and payload["seq"] <= latest:
            raise TelemetryError("out_of_order_telemetry", "Sequence is not increasing")
        metadata={name:payload[name] for name in ("worker_version","backend","cpu_scope","gpu_scope",
                                                  "cpu_provider","gpu_provider") if name in payload}
        con.execute("INSERT INTO packets VALUES(?,?,?,?,?,?)",
                    (*key, digest, now_ms, json.dumps(metadata,sort_keys=True,separators=(",", ":"))))
        for bucket in payload["buckets"]:
            encoded = json.dumps(bucket, sort_keys=True, separators=(",", ":"), allow_nan=False)
            try:
                con.execute("INSERT INTO buckets VALUES(?,?,?,?,?,?)",
                            (device_id, payload["session_id"], bucket["start_ms"], payload["seq"], now_ms, encoded))
            except sqlite3.IntegrityError as exc:
                raise TelemetryError("conflicting_telemetry", "Bucket already recorded in this session") from exc
            _rollup(con, device_id, bucket)
        _prune(con, path, now_ms)
        con.commit()
        return {"ok": True, "accepted": len(payload["buckets"]), "duplicate": False,
                "server_time_ms": now_ms}
    except BaseException:
        if con.in_transaction:
            con.rollback()
        raise
    finally:
        con.close()


def recent_by_device(path, *, since_ms, device_ids, limit_per_device=360):
    """Bounded local-admin read. Missing files mean no telemetry, not zero."""
    if not Path(path).is_file():
        return {}
    ids = list(dict.fromkeys(device_ids))[:64]
    out = {}
    con = _connect(path)
    try:
        for device_id in ids:
            rows = con.execute("""SELECT b.payload_json,p.metadata_json FROM buckets b
                JOIN packets p ON p.device_id=b.device_id AND p.session_id=b.session_id AND p.seq=b.seq
                WHERE b.device_id=? AND b.start_ms>=? ORDER BY b.start_ms DESC LIMIT ?""",
                (device_id, since_ms, min(max(1, limit_per_device), 720))).fetchall()
            out[device_id] = [{**json.loads(row["payload_json"]),**json.loads(row["metadata_json"])}
                              for row in reversed(rows)]
        return out
    finally:
        con.close()


def latest_by_device(path, *, since_ms, device_ids):
    """One indexed lookup per recently active device for the private admin UI."""
    if not Path(path).is_file():
        return {}
    out = {}
    con = _connect(path)
    try:
        for device_id in list(dict.fromkeys(device_ids))[:100]:
            row = con.execute("""SELECT b.payload_json,p.metadata_json FROM buckets b
                JOIN packets p ON p.device_id=b.device_id AND p.session_id=b.session_id AND p.seq=b.seq
                WHERE b.device_id=? AND b.start_ms>=? ORDER BY b.start_ms DESC LIMIT 1""",
                (device_id, since_ms)).fetchone()
            if row is not None:
                out[device_id] = {**json.loads(row["payload_json"]),**json.loads(row["metadata_json"])}
        return out
    finally:
        con.close()


def delete_devices(path, device_ids):
    """Erase private diagnostics before a user-initiated account deletion."""
    if not Path(path).is_file():
        return
    ids = list(dict.fromkeys(device_ids))
    if not ids:
        return
    con = _connect(path)
    try:
        con.execute("BEGIN IMMEDIATE")
        for device_id in ids:
            for table in ("buckets", "packets", "minute_rollups"):
                con.execute(f"DELETE FROM {table} WHERE device_id=?", (device_id,))
        con.commit()
    except BaseException:
        if con.in_transaction:
            con.rollback()
        raise
    finally:
        con.close()
