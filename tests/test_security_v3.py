import hashlib
import ipaddress
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlparse
from cryptography.exceptions import InvalidSignature

ROOT=Path(__file__).resolve().parents[1]
def main():
    TMP=Path(tempfile.mkdtemp(prefix="security-v3-"))
    test_cfg=json.loads((ROOT/"config"/"server.example.json").read_text(encoding="utf-8"))
    test_cfg.update({"registration_code":"TEST-REGISTRATION-CODE","registration_open":False,
                     "min_worker_version":"0.3.0","registration_pow_bits":12})
    test_cfg_path=TMP/"server.json"
    test_cfg_path.write_text(json.dumps(test_cfg),encoding="utf-8")
    os.environ["GRID_DATA_DIR"]=str(TMP)
    os.environ["GRID_DB"]=str(TMP/"grid.sqlite3")
    os.environ["GRID_CONFIG"]=str(test_cfg_path)
    sys.path.insert(0,str(ROOT/"server"))
    sys.path.insert(0,str(ROOT/"worker"))
    import coordinator as c
    c.DATA=TMP;c.DB=TMP/"grid.sqlite3";c.CFG=test_cfg_path
    assert c.DB.resolve().is_relative_to(TMP.resolve())
    import updater
    import updater_apply
    import worker

    c.init_db()
    con=c.db()
    challenge=c.new_registration_challenge(con)
    nonce=challenge["nonce"];bits=challenge["difficulty_bits"];counter=0
    while True:
        h=hashlib.sha256((nonce+":"+str(counter)).encode()).digest()
        if (int.from_bytes(h,"big")>>(256-bits))==0:break
        counter+=1
    assert c.verify_registration_pow(con,{"pow_nonce":nonce,"pow_counter":counter})
    assert not c.verify_registration_pow(con,{"pow_nonce":nonce,"pow_counter":counter})
    meta=c.sanitize_meta({"worker_version":"0.3.0","hostname":"PRIVATE-NAME","python":"3.13",
                          "cpu_count":8,"machine":"AMD64","capabilities":["cpu","cuda"],
                          "gpus":[{"vendor":"NVIDIA","name":"RTX Test","uuid":"SECRET-ID","memory_mb":8192}]})
    assert "hostname" not in meta and "python" not in meta
    assert "uuid" not in meta["gpus"][0]

    assert c.version_tuple("0.3.0") < c.version_tuple("0.3.1")
    os.environ.pop("GRID_ALLOW_NON_LOOPBACK",None)
    assert c.bind_host_allowed("127.0.0.1")
    assert c.bind_host_allowed("::1")
    assert not c.bind_host_allowed("0.0.0.0")
    assert not c.bind_host_allowed("192.168.1.10")
    assert c.worker_update_required({"meta_json":'{"worker_version":"0.2.9"}'})==(True,"0.3.0")
    assert c.worker_update_required({"meta_json":'{"worker_version":"0.3.0"}'})==(False,"0.3.0")

    handler=object.__new__(c.Handler)
    handler.send_json=lambda code,obj:(code,obj)
    code,registered=handler.register(con,{
        "registration_code":"TEST-REGISTRATION-CODE","display_name":"Privacy Test","device_label":"PC",
        "meta":{"worker_version":"0.3.0","hostname":"SHOULD-NOT-PERSIST","python":"SECRET",
                "cpu_count":8,"machine":"AMD64","capabilities":["cpu","cuda"],
                "gpus":[{"vendor":"NVIDIA","name":"RTX Test","uuid":"SHOULD-NOT-PERSIST","memory_mb":8192}]},
        "settings":{"cpu_percent":50,"gpu_percent":0}
    })
    assert code==200
    stored=con.execute("select meta_json from devices where id=?",(registered["device_id"],)).fetchone()
    stored_meta=json.loads(stored["meta_json"])
    assert "hostname" not in stored_meta and "python" not in stored_meta
    assert "uuid" not in stored_meta["gpus"][0]

    manifest=ROOT/"dist"/"update-manifest.json"
    sig=ROOT/"dist"/"update-manifest.sig"
    if manifest.exists() and sig.exists():
        raw=manifest.read_bytes();s=sig.read_text().strip()
        updater.verify_manifest(raw,s)
        try:
            updater.verify_manifest(raw+b"x",s)
        except InvalidSignature:
            pass
        else:
            raise AssertionError("tampered manifest accepted")

    bad=TMP/"bad.zip"
    with zipfile.ZipFile(bad,"w") as z:z.writestr("worker/../../escape.txt","x")
    try:
        updater_apply.safe_extract(bad,TMP/"extract")
        raise AssertionError("path traversal accepted")
    except ValueError:
        pass

    assert updater.manifest_is_mandatory({"mandatory":False,"min_supported_version":"0.3.1"},"0.3.0")
    assert not updater.manifest_is_mandatory({"mandatory":False,"min_supported_version":"0.3.0"},"0.3.0")

    asset=TMP/"asset.zip";asset.write_bytes(b"test-update")
    generated=TMP/"generated-manifest.json"
    subprocess.run([sys.executable,str(ROOT/"scripts"/"create_update_manifest.py"),str(asset),
                    "--version","0.3.1","--repository","Test/Repo","--out",str(generated)],
                   check=True,capture_output=True,text=True)
    generated_obj=json.loads(generated.read_text(encoding="utf-8"))
    assert generated_obj["min_supported_version"]==""
    assert generated_obj["mandatory"] is False

    client_state=TMP/"client.json"
    secret_state={"server":"https://example.invalid","device_token":"DPAPI-SECRET","dashboard_token":"DASH-SECRET"}
    worker.save_state(client_state,secret_state)
    assert worker.load_state(client_state)==secret_state
    raw_state=client_state.read_text(encoding="utf-8")
    if os.name=="nt":
        assert json.loads(raw_state).get("_format")=="dpapi-v1"
        assert "DPAPI-SECRET" not in raw_state and "DASH-SECRET" not in raw_state

    release_cfg=json.loads((ROOT/"worker"/"release_config.json").read_text(encoding="utf-8"))
    release_url=urlparse(str(release_cfg["server_url"]))
    assert release_url.scheme=="https" and release_url.hostname
    assert not release_url.username and not release_url.password and not release_url.query and not release_url.fragment
    try:
        ipaddress.ip_address(release_url.hostname)
        raise AssertionError("public bootstrap must not expose a direct IP address")
    except ValueError:
        pass

    print("SECURITY_V3_OK",{"pow_counter":counter,"sanitized_meta":meta,"release_host":release_url.hostname})
    con.close()
    assert TMP.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()) and TMP.name.startswith("security-v3-")
    shutil.rmtree(TMP)

if __name__ == "__main__":
    main()
