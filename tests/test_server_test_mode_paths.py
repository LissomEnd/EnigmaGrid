"""Test-mode processes must never touch the production config or database."""
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
import coordinator as c


def main():
    previous = c.DATA, c.DB, c.CFG, os.environ.get("GRID_TEST_MODE")
    try:
        os.environ["GRID_TEST_MODE"] = "1"
        production = ROOT / "state"
        c.DATA, c.DB, c.CFG = production, production / "grid.sqlite3", ROOT / "config" / "server.json"
        for access in (c.db, c.load_cfg):
            try:
                access()
            except RuntimeError as exc:
                assert "GRID_TEST_MODE" in str(exc)
            else:
                raise AssertionError("production path was accepted in test mode")
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            c.DATA, c.DB, c.CFG = temporary, temporary / "grid.sqlite3", temporary / "server.json"
            c.CFG.write_text("{}", encoding="utf-8")
            assert c.load_cfg() == {}
            handler=object.__new__(c.Handler)
            handler.path='/api/capabilities'
            handler.send_json=lambda code,payload:(code,payload)
            before=int(time.time()*1000)
            with patch.object(c,'allowed_request',return_value=True):
                status,capabilities=c.Handler.do_GET(handler)
            after=int(time.time()*1000)
            assert status==200 and before<=capabilities['server_time_ms']<=after
            con = c.db()
            try:
                assert con.execute("select 1").fetchone()[0] == 1
            finally:
                con.close()
            c.DB = production / "grid.sqlite3"
            try:
                c.db()
            except RuntimeError:
                pass
            else:
                raise AssertionError("database outside test DATA was accepted")
    finally:
        c.DATA, c.DB, c.CFG = previous[:3]
        if previous[3] is None:
            os.environ.pop("GRID_TEST_MODE", None)
        else:
            os.environ["GRID_TEST_MODE"] = previous[3]


if __name__ == "__main__":
    main()
    print("PASS test-mode production path guard")
