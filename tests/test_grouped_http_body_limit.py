"""Grouped uploads get a bounded larger HTTP body; other routes stay at 256 KiB."""
import io
import json
import sys
import tempfile
from email.message import Message
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
import coordinator as c


def parse(path, encoded):
    handler = object.__new__(c.Handler)
    handler.path = path
    handler.rfile = io.BytesIO(encoded)
    handler.headers = Message()
    handler.headers["Content-Length"] = str(len(encoded))
    handler.headers["Content-Type"] = "application/json"
    return handler.body()


def rejected(path, encoded):
    try:
        parse(path, encoded)
    except ValueError as exc:
        assert str(exc) == "body_too_large", str(exc)
    else:
        raise AssertionError("oversized HTTP body accepted")


def main():
    original_cfg = c.CFG
    with tempfile.TemporaryDirectory() as folder:
        c.CFG = Path(folder) / "server.json"
        try:
            c.CFG.write_text(json.dumps({"max_body_bytes": 256 * 1024}), encoding="utf-8")
            body = json.dumps({"groups": [], "padding": "x" * (512 * 1024)}).encode()
            assert 256 * 1024 < len(body) < c.work_result_groups.MAX_BODY_BYTES
            assert parse("/api/work-blocks/result-groups", body)["groups"] == []
            rejected("/api/work-blocks/results", body)
            rejected("/api/complete", body)
            rejected("/api/work-blocks/result-groups", body + b" " * (c.work_result_groups.MAX_BODY_BYTES - len(body) + 1))

            # A private operator setting can only lower the grouped ceiling.
            c.CFG.write_text(json.dumps({"max_body_bytes": 256 * 1024,
                                         "max_result_group_body_bytes": 512 * 1024}), encoding="utf-8")
            rejected("/api/work-blocks/result-groups", body)
            c.CFG.write_text(json.dumps({"max_body_bytes": 256 * 1024,
                                         "max_result_group_body_bytes": 1024 * 1024}), encoding="utf-8")
            rejected("/api/work-blocks/result-groups", body + b" " * (c.work_result_groups.MAX_BODY_BYTES - len(body) + 1))
        finally:
            c.CFG = original_cfg
    print("PASS grouped HTTP cap 768 KiB; ordinary cap 256 KiB; operator cap cannot exceed protocol")


if __name__ == "__main__":
    main()
