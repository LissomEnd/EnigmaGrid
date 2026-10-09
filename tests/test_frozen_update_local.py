import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PY=Path(sys.executable)
CAND=Path(os.environ.get("ENIGMA_TEST_CANDIDATE", ROOT/"dist"/"windows-candidate"))
ASSET=Path(os.environ.get("ENIGMA_TEST_ASSET", ROOT/"dist"/"enigma-volunteer-windows-candidate.zip"))
VERSION=os.environ.get("ENIGMA_TEST_TARGET_VERSION", "0.4.2")

def get(url):
    with urllib.request.urlopen(url,timeout=5) as r:return json.loads(r.read())

def wait_health(path,version,timeout=20):
    end=time.time()+timeout
    while time.time()<end:
        try:
            if json.loads(path.read_text())["version"]==version:return True
        except Exception:pass
        time.sleep(.3)
    return False

def stop_runtime(state):
    state.parent.mkdir(parents=True,exist_ok=True)
    (state.with_name("control.json")).write_text(
        json.dumps({"paused":False,"stop_requested":True,"check_update":False}))
    (state.with_name("update-exit")).write_text("1")
    time.sleep(4)

def force_stop_tmp(tmp):
    if os.name!="nt":return
    pfx=str(tmp).replace("'","''")
    script=("$pfx='"+pfx+"'; Get-CimInstance Win32_Process | "
            "Where-Object {$_.ExecutablePath -like \"$pfx*\" -and "
            "$_.Name -in @('EnigmaGrid.exe','EnigmaGridWorker.exe','runner.exe')} | "
            "ForEach-Object {Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}")
    subprocess.run(["powershell","-NoProfile","-Command",script],
                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def manifest(asset,version,out,key_blob):
    subprocess.run([str(PY),str(ROOT/"scripts"/"create_update_manifest.py"),str(asset),
                    "--version",version,"--repository","Test/Local","--out",str(out)],
                   check=True,stdout=subprocess.DEVNULL)
    sig=out.with_suffix(".sig")
    subprocess.run([str(PY),str(ROOT/"scripts"/"sign_update_manifest_dpapi.py"),str(out),
                    "--key-blob",str(key_blob),"--out",str(sig)],
                   check=True,stdout=subprocess.DEVNULL)
    return sig

def run_updater(runner,install,state,base,asset,man,sig,timeout):
    return subprocess.run([str(runner),"--parent-pid","999999",
        "--install-root",str(install),"--state",str(state),"--server",base,
        "--asset",str(asset),"--manifest",str(man),"--signature",str(sig),
        "--health-timeout",str(timeout)],timeout=180).returncode

def main():
    kb=os.environ.get("ENIGMA_TEST_SIGNING_KEY_BLOB","").strip()
    if not kb:
        print("FROZEN_UPDATE_LOCAL_SKIPPED no ENIGMA_TEST_SIGNING_KEY_BLOB");return
    key_blob=Path(kb)
    required=["EnigmaGrid.exe","EnigmaGridWorker.exe","EnigmaGridUpdater.exe","release_config.json"]
    assert ASSET.exists() and key_blob.exists()
    assert all((CAND/x).exists() for x in required)

    tmp=Path(tempfile.mkdtemp(prefix="enigma-update-e2e-"))
    s=socket.socket();s.bind(("127.0.0.1",0));port=s.getsockname()[1];s.close()
    cfg=json.loads((ROOT/"config"/"server.example.json").read_text(encoding="utf-8"))
    cfg.update({"host":"127.0.0.1","port":port,"registration_open":True,
                "registration_code":"","registration_pow_bits":8,
                "min_worker_version":VERSION,"rate_limit_per_minute":1000})
    cfgp=tmp/"server.json";cfgp.write_text(json.dumps(cfg))
    env=os.environ.copy();env.update({"GRID_CONFIG":str(cfgp),"GRID_DATA_DIR":str(tmp/"db"),
                                      "GRID_DB":str(tmp/"db/grid.sqlite3"),
                                      "GRID_HOST":"127.0.0.1","GRID_PORT":str(port)})

    server=subprocess.Popen([str(PY),str(ROOT/"server"/"coordinator.py")],
                            cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.time()+10;base=f"http://127.0.0.1:{port}"
        while True:
            try:
                if get(base+"/health")["ok"]:break
            except Exception:
                if time.time()>deadline:raise
                time.sleep(.1)

        install=tmp/"install";install.mkdir()
        for name in required:shutil.copy2(CAND/name,install/name)
        state=tmp/"user"/"client.json";state.parent.mkdir()
        subprocess.run([str(install/"EnigmaGridWorker.exe"),"--server",base,
                        "--name","Update Test","--state",str(state),"--register-only",
                        "--cpu-percent","10"],check=True,timeout=120)
        runner=tmp/"runner.exe";shutil.copy2(CAND/"EnigmaGridUpdater.exe",runner)

        man1=tmp/"success.json";sig1=manifest(ASSET,VERSION,man1,key_blob)
        rc=run_updater(runner,install,state,base,ASSET,man1,sig1,12)
        assert rc==0,rc
        assert wait_health(state.with_name("worker-health.json"),VERSION,10)

        expected={x:hashlib.sha256((CAND/x).read_bytes()).hexdigest() for x in required}
        actual={x:hashlib.sha256((install/x).read_bytes()).hexdigest() for x in required}
        assert actual==expected
        stop_runtime(state)

        # A manifest version the staged worker cannot report forces post-swap rollback.
        (state.with_name("control.json")).unlink(missing_ok=True)
        man2=tmp/"rollback.json";sig2=manifest(ASSET,"9.9.9",man2,key_blob)
        rc=run_updater(runner,install,state,base,ASSET,man2,sig2,5)
        assert rc==4,rc
        assert wait_health(state.with_name("worker-health.json"),VERSION,10)
        actual2={x:hashlib.sha256((install/x).read_bytes()).hexdigest() for x in required}
        assert actual2==expected
        stop_runtime(state)
        print("FROZEN_UPDATE_E2E_OK",{"success_rc":0,"rollback_rc":4})
    finally:
        server.terminate()
        try:server.wait(timeout=5)
        except subprocess.TimeoutExpired:server.kill()
        force_stop_tmp(tmp);time.sleep(.5)
        shutil.rmtree(tmp,ignore_errors=True)

if __name__=="__main__":main()
