"""Policy reads are cached, but file edits and environment overrides remain live."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
import coordinator as c


def write_config(path, **values):
    path.write_text(json.dumps(values), encoding="utf-8")
    # Force distinct metadata even on a filesystem with coarse write stamps.
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


def main():
    previous = c.CFG
    old_host = os.environ.get("GRID_HOST")
    with tempfile.TemporaryDirectory() as folder:
        first = Path(folder) / "first.json"
        second = Path(folder) / "second.json"
        try:
            write_config(first, host="127.0.0.1", compute_rate_limit_per_minute=3600)
            c.CFG = first
            assert c.load_cfg()["compute_rate_limit_per_minute"] == 3600
            value = c.load_cfg()
            value["compute_rate_limit_per_minute"] = 0
            assert c.load_cfg()["compute_rate_limit_per_minute"] == 3600
            write_config(first, host="127.0.0.1", compute_rate_limit_per_minute=7200)
            assert c.load_cfg()["compute_rate_limit_per_minute"] == 7200
            write_config(second, host="127.0.0.1", compute_rate_limit_per_minute=1800)
            c.CFG = second
            assert c.load_cfg()["compute_rate_limit_per_minute"] == 1800
            os.environ["GRID_HOST"] = "localhost"
            assert c.load_cfg()["host"] == "localhost"
        finally:
            c.CFG = previous
            if old_host is None:
                os.environ.pop("GRID_HOST", None)
            else:
                os.environ["GRID_HOST"] = old_host
    print("PASS server policy cache reloads edited/changed config and preserves live overrides")


if __name__ == "__main__":
    main()
