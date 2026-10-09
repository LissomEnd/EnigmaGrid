"""Bounded telemetry transport; direct entrypoint uses temporary databases only."""
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
import coordinator as c
import device_telemetry as dt


def denied(call, code):
    try:
        call()
    except dt.TelemetryError as exc:
        assert exc.code == code, (exc.code, code)
    else:
        raise AssertionError("Invalid telemetry was accepted")


def main():
    old = c.DATA, c.DB, c.CFG, os.environ.get("GRID_TELEMETRY_DB")
    with tempfile.TemporaryDirectory(prefix="enigma-telemetry-") as folder:
        root = Path(folder)
        c.DATA, c.DB, c.CFG = root, root / "grid.sqlite3", root / "server.json"
        private_db = root / "device-telemetry.sqlite3"
        os.environ["GRID_TELEMETRY_DB"] = str(private_db)
        assert (c.DATA.resolve(), c.DB.resolve(), c.CFG.resolve(), private_db.resolve()) == (
            root.resolve(), (root / "grid.sqlite3").resolve(),
            (root / "server.json").resolve(), (root / "device-telemetry.sqlite3").resolve())
        assert all(path.is_relative_to(root.resolve()) for path in (
            c.DATA.resolve(), c.DB.resolve(), c.CFG.resolve(), private_db.resolve()))
        cfg = json.loads((ROOT / "config" / "server.example.json").read_text(encoding="utf-8"))
        cfg["long_work_blocks_enabled"] = True
        c.CFG.write_text(json.dumps(cfg), encoding="utf-8")
        c.init_db()
        con = c.db()
        try:
            con.execute("INSERT INTO contributors(id,display_name,join_key_hash,dashboard_token_hash,created) VALUES('o','test','j',?,?)",
                        (c.sha("dashboard"), time.time()))
            con.execute("INSERT INTO devices(id,contributor_id,label,token_hash,created,last_seen) VALUES('d','o','test',?,?,?)",
                        (c.sha("test-token"), time.time(), 123.0))
        finally:
            con.close()

        now_ms = int(time.time() * 1000)
        start = now_ms // 5000 * 5000 - 30000
        packet = {"format": dt.FORMAT, "session_id": "a" * 32, "seq": 1,
                  "worker_version": "0.5.0", "backend": "CPU + Vulkan",
                  "cpu_scope": "process", "gpu_scope": "device",
                  "cpu_provider": "procstat", "gpu_provider": "gpu_busy", "buckets": [
                      {"start_ms": start, "duration_ms": 5000, "samples": 5,
                       "jobs_done": 10, "units_done": 10, "compute_ms": 4800,
                       "cpu_percent": 75.0, "gpu_percent": 25.0, "ready_jobs": 25},
                      {"start_ms": start + 5000, "duration_ms": 5000,
                       "jobs_done": 11, "units_done": 11, "compute_ms": 4900}]}
        first = dt.ingest(private_db, "d", packet, now_ms=now_ms)
        assert first["accepted"] == 2 and first["duplicate"] is False
        assert dt.ingest(private_db, "d", json.loads(json.dumps(packet, sort_keys=True)), now_ms=now_ms)["duplicate"] is True
        telemetry = sqlite3.connect(private_db)
        try:
            assert telemetry.execute("SELECT count(*) FROM packets").fetchone()[0] == 1
            assert telemetry.execute("SELECT count(*) FROM buckets").fetchone()[0] == 2
            rollups = [json.loads(row[0]) for row in telemetry.execute("SELECT payload_json FROM minute_rollups")]
            assert sum(row["totals"]["jobs_done"]["sum"] for row in rollups) == 21
            assert sum(row["totals"]["units_done"]["sum"] for row in rollups) == 21
            assert sum(row["totals"]["jobs_done"]["present_buckets"] for row in rollups) == 2
            assert sum(row["gauges"]["cpu_percent"]["samples"] for row in rollups if "cpu_percent" in row["gauges"]) == 5
        finally:
            telemetry.close()
        assert dt.recent_by_device(private_db, since_ms=start, device_ids=["d"])["d"][0]["jobs_done"] == 10
        assert dt.latest_by_device(private_db, since_ms=start, device_ids=["d"])["d"]["gpu_provider"] == "gpu_busy"
        conflicting = {**packet, "buckets": [{**packet["buckets"][0], "jobs_done": 999}]}
        denied(lambda: dt.ingest(private_db, "d", conflicting, now_ms=now_ms), "conflicting_telemetry")
        repeated = {**packet, "seq": 2}
        denied(lambda: dt.ingest(private_db, "d", repeated, now_ms=now_ms), "conflicting_telemetry")
        denied(lambda: dt.validate({**packet, "buckets": [{**packet["buckets"][0], "cpu_percent": float("nan")}]}, now_ms=now_ms), "invalid_telemetry")
        denied(lambda: dt.validate({**packet, "buckets": [{**packet["buckets"][0], "start_ms": start - 86400000 - 5000}]}, now_ms=now_ms), "stale_telemetry")
        denied(lambda: dt.validate({**packet, "buckets": [{**packet["buckets"][0], "gpu_percent": 101}]}, now_ms=now_ms), "invalid_telemetry")

        server = c.ThreadingHTTPServer(("127.0.0.1", 0), c.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:" + str(server.server_port)

        def request(path, body=None, token="test-token"):
            data = None if body is None else json.dumps(body).encode("utf-8")
            req = urllib.request.Request(base + path, data=data, headers={
                "Content-Type": "application/json", "X-Device-Token": token})
            try:
                with urllib.request.urlopen(req, timeout=5) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as exc:
                return exc.code, json.load(exc)

        try:
            capability = request("/api/capabilities")[1]
            assert capability["device_telemetry"] == dt.FORMAT
            assert capability["telemetry_interval_seconds"] == 30
            assert capability["telemetry_max_body_bytes"] == 8192
            http_packet = {**packet, "seq": 3,
                           "buckets": [{"start_ms": start + 10000, "duration_ms": 5000, "jobs_done": 5}]}
            assert request("/api/device/telemetry/v1", http_packet, token="bad")[0] == 403
            code, body = request("/api/device/telemetry/v1", http_packet)
            assert code == 200 and body["accepted"] == 1 and not body["duplicate"], (code, body)
            assert request("/api/device/telemetry/v1", http_packet)[1]["duplicate"] is True
            assert request("/api/device/telemetry/v1", {**http_packet, "backend": "changed"})[0] == 409
            assert request("/api/device/telemetry/v1", {**http_packet, "seq": 4, "buckets": [
                {"start_ms": start - 86400000 - 5000, "duration_ms": 5000}]})[0] == 409
            assert request("/api/device/telemetry/v1", {**http_packet, "seq": 5,
                "backend": "x" * 9000})[0] == 400
            con = c.db()
            try:
                assert con.execute("SELECT last_seen FROM devices WHERE id='d'").fetchone()[0] == 123.0
            finally:
                con.close()
            con = c.db()
            try:
                con.execute("INSERT INTO campaigns(id,name,version,status,created) VALUES('campaign','test','1','running',?)", (time.time(),))
                con.execute("""INSERT INTO segments(id,campaign_id,label,engine,start_unit,end_unit,next_unit,
                    chunk_size,priority,config_json) VALUES('segment','campaign','test','bounded_crib_v1',0,10,10,1,10,'{}')""")
                con.execute("""INSERT INTO work_blocks(id,device_id,request_id,segment_id,start_unit,end_unit,
                    config_json,created_at,expires_at,status) VALUES('block','d','request','segment',0,10,'{}',?,?,'reserved')""",
                    (time.time(), time.time() + 3600))
                con.execute("""INSERT INTO block_receipts(block_id,unit,fingerprint,result_json,compute_seconds,received_at)
                    VALUES('block',0,'fingerprint','{}',1,?)""", (time.time(),))
                con.execute("INSERT INTO sampling_decisions VALUES('oldsub','d','bounded_crib_v1','0.5.0','verify','probation',0)")
                con.execute("INSERT INTO sampling_evidence VALUES('oldsub','d','bounded_crib_v1','0.5.0','match')")
                con.execute("INSERT INTO sampling_state VALUES('d','bounded_crib_v1','0.5.0',0,1)")
                con.execute("""INSERT INTO contributors(id,display_name,join_key_hash,dashboard_token_hash,created)
                    VALUES('other','other','other_join','other_dashboard',?)""", (time.time(),))
                con.execute("""INSERT INTO devices(id,contributor_id,label,token_hash,created)
                    VALUES('other_device','other','other','other_token',?)""", (time.time(),))
                con.execute("""INSERT INTO contributions(contributor_id,device_id,units,jobs,compute_seconds,candidates)
                    VALUES('other','other_device',7,7,1.0,0)""")
            finally:
                con.close()
            code, deleted = request("/api/me/delete", {"dashboard_token": "dashboard", "confirm": "DELETE"}, token="")
            assert code == 200 and deleted["deleted"], (code, deleted)
            assert dt.latest_by_device(private_db, since_ms=start, device_ids=["d"]) == {}
            con = c.db()
            try:
                assert con.execute("SELECT id FROM contributors").fetchall()[0][0] == 'other'
                assert con.execute("SELECT units,jobs FROM contributions WHERE contributor_id='other'").fetchone()[:] == (7, 7)
                block = con.execute("SELECT device_id,status FROM work_blocks WHERE id='block'").fetchone()
                assert block["device_id"].startswith("deleted_") and block["status"] == "released"
                assert con.execute("SELECT start_unit,end_unit FROM block_requeue WHERE source_block='block'").fetchone()[:] == (1, 10)
                assert con.execute("SELECT count(*) FROM block_receipts WHERE block_id='block'").fetchone()[0] == 1
                assert con.execute("SELECT device_id FROM sampling_evidence WHERE submission_id='oldsub'").fetchone()[0] == block["device_id"]
                assert con.execute("SELECT device_id FROM sampling_decisions WHERE submission_id='oldsub'").fetchone()[0] == block["device_id"]
                assert con.execute("SELECT device_id FROM sampling_state").fetchone()[0] == block["device_id"]
            finally:
                con.close()
            telemetry = sqlite3.connect(private_db)
            try:
                for table in ("packets", "buckets", "minute_rollups"):
                    assert telemetry.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
            finally:
                telemetry.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
    c.DATA, c.DB, c.CFG = old[:3]
    if old[3] is None:
        os.environ.pop("GRID_TELEMETRY_DB", None)
    else:
        os.environ["GRID_TELEMETRY_DB"] = old[3]
    print("PASS device telemetry v1 isolated auth, validation, idempotency, rollup and HTTP bounds")


if __name__ == "__main__":
    main()
