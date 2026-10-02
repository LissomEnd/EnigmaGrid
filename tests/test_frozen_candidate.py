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
EXE=ROOT/"dist"/"windows-candidate"/"EnigmaGridWorker.exe"
TRAY=ROOT/"dist"/"windows-candidate"/"EnigmaGrid.exe"

def get(url):
    with urllib.request.urlopen(url,timeout=5) as r:return json.loads(r.read())

def run(args,timeout=180):
    p=subprocess.run([str(EXE),*args],timeout=timeout)
    if p.returncode!=0:raise RuntimeError(f"worker exit {p.returncode}")

def main():
    assert EXE.exists() and TRAY.exists()
    tr=subprocess.run([str(TRAY),"--self-test"],capture_output=True,text=True,timeout=60)
    assert tr.returncode==0,tr.stderr
    assert json.loads((EXE.parent/'release_config.json').read_text())["server_url"].startswith('https://')
    tmp=Path(tempfile.mkdtemp(prefix="enigma-frozen-"))
    s=socket.socket();s.bind(("127.0.0.1",0));port=s.getsockname()[1];s.close()
    cfg=json.loads((ROOT/"config"/"server.example.json").read_text(encoding="utf-8"))
    cfg.update({"host":"127.0.0.1","port":port,"registration_open":True,
                "registration_code":"","registration_pow_bits":9,
                "min_worker_version":"0.3.0","rate_limit_per_minute":1000})
    cfgp=tmp/"server.json";cfgp.write_text(json.dumps(cfg),encoding="utf-8")
    env=os.environ.copy();env.update({"GRID_CONFIG":str(cfgp),"GRID_DATA_DIR":str(tmp/"db"),
                                      "GRID_HOST":"127.0.0.1","GRID_PORT":str(port)})
    server=subprocess.Popen([sys.executable,str(ROOT/"server"/"coordinator.py")],
                            cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
    base=f"http://127.0.0.1:{port}"

    try:
        deadline=time.time()+10
        while True:
            try:
                if get(base+"/health")["ok"]:break
            except Exception:
                if time.time()>deadline:raise
                time.sleep(.1)
        db=tmp/"db"/"grid.sqlite3";con=sqlite3.connect(db)
        con.execute("insert into campaigns(id,name,version,status,created,notes) values(?,?,?,?,?,?)",
                    ("frozen","Frozen test","t","running",time.time(),""))
        scfg={"requires":["cpu"],"replicas_required":2,"max_replicas":3,
              "base_attempt":9900000000,"count_per_unit":32,"iterations":5,"topk":2,
              "min_pairs":0,"max_pairs":3,"event_kinds":[1,2,3,4,5]}
        con.execute("""insert into segments(id,campaign_id,label,engine,start_unit,end_unit,next_unit,
                     chunk_size,priority,config_json) values(?,?,?,?,?,?,?,?,?,?)""",
                    ("frozen-event","frozen","Tiny frozen event","portable_event_v1",0,1,0,1,1,
                     json.dumps(scfg,separators=(",",":"))))
        con.commit();con.close()
        a=tmp/"a.json";b=tmp/"b.json"

        run(["--server",base,"--name","Frozen A","--state",str(a),"--register-only",
             "--cpu-percent","25","--gpu-percent","30"],120)
        run(["--state",str(a),"--once"],240)
        run(["--server",base,"--name","Frozen B","--state",str(b),"--register-only",
             "--cpu-percent","25"],120)
        run(["--state",str(b),"--once"],240)
        con=sqlite3.connect(db)
        done=con.execute("select count(*) from done_ranges where segment_id='frozen-event'").fetchone()[0]
        subs=con.execute("select count(*) from submissions where segment_id='frozen-event'").fetchone()[0]
        credits=con.execute("select count(*) from contributions").fetchone()[0]
        con.close()
        assert (done,subs,credits)==(1,2,2),(done,subs,credits)
        # DPAPI state must not expose device tokens.
        raw=a.read_text(encoding="utf-8")
        assert json.loads(raw).get("_format")=="dpapi-v1" and "device_token" not in raw
        print("FROZEN_CANDIDATE_OK",{"done":done,"submissions":subs,"credits":credits})
    finally:
        server.terminate()
        try:server.wait(timeout=5)
        except subprocess.TimeoutExpired:server.kill()
        shutil.rmtree(tmp,ignore_errors=True)

if __name__=="__main__":main()
