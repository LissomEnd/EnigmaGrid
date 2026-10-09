"""Run only against copied candidate coordinators in isolated temporary DBs."""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

STAGE = Path(__file__).resolve().parents[1] / "server"
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "server"))
sys.path.insert(0, str(REPO / "solver/runtime/src"))

def exercise(filename, module_name):
    with tempfile.TemporaryDirectory(prefix="enigma-public-credit-") as temporary:
        folder = Path(temporary)
        state = folder / "state"
        state.mkdir()
        config = json.loads((REPO / "config/server.example.json").read_text(encoding="utf-8"))
        config.update(registration_code="TEST-PRIVATE-REGISTRATION", registration_open=False)
        config_path = folder / "server.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        os.environ.update(GRID_TEST_MODE="1", GRID_DATA_DIR=str(state), GRID_DB=str(state / "test.sqlite3"), GRID_CONFIG=str(config_path))
        spec = importlib.util.spec_from_file_location(module_name, STAGE / filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.DATA = state
        module.DB = state / "test.sqlite3"
        module.CFG = config_path
        module.init_db()
        con = module.db()
        handler = object.__new__(module.Handler)
        handler.send_json = lambda code, payload: (code, payload)
        base = {"registration_code":"TEST-PRIVATE-REGISTRATION", "display_name":"Privacy Fixture", "device_label":"Fixture", "meta":{"worker_version":"0.5.0", "capabilities":["cpu"]}, "settings":{}}
        def enroll(extra):
            code, reply = handler.register(con, {**base, **extra})
            assert code == 200, (module_name, code, reply)
            public = con.execute("SELECT public_credit FROM contributors WHERE id=?", (reply["contributor_id"],)).fetchone()[0]
            return reply, public
        omitted, public = enroll({})
        assert public == 0, (module_name, "omission must be private")
        shown, public = enroll({"public_credit": True})
        assert public == 1, (module_name, "explicit public")
        hidden, public = enroll({"public_credit": False})
        assert public == 0, (module_name, "explicit private")
        before = con.execute("SELECT count(*) FROM contributors").fetchone()[0]
        joined, public = enroll({"contributor_key": shown["contributor_key"], "public_credit": False})
        assert joined["contributor_id"] == shown["contributor_id"] and public == 1
        joined_private, public = enroll({"contributor_key": hidden["contributor_key"], "public_credit": True})
        assert joined_private["contributor_id"] == hidden["contributor_id"] and public == 0
        assert con.execute("SELECT count(*) FROM contributors").fetchone()[0] == before
        assert omitted["contributor_id"] != hidden["contributor_id"]
        con.close()
    print("PASS", module_name, "omitted/private, explicit true/false, join unchanged")

exercise("coordinator.py", "privacy_reference_coordinator")
