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

def http_json(url,method="GET",body=None,token=None):
    data=None if body is None else json.dumps(body,separators=(",",":")).encode()
    headers={"Content-Type":"application/json"} if data is not None else {}
    if token:
        headers["X-Device-Token"]=token
    req=urllib.request.Request(url,data=data,headers=headers,method=method)
    with urllib.request.urlopen(req,timeout=5) as r:
        return json.loads(r.read())

def solve_pow(nonce,bits):
    counter=0
    while True:
        h=hashlib.sha256(f"{nonce}:{counter}".encode()).digest()
        if (int.from_bytes(h,"big")>>(256-bits))==0:
            return counter
        counter+=1

def demo_result(segment_id,start,end,rounds):
    best=None
    for unit in range(start,end):
        h=f"{segment_id}:{unit}".encode()
        for _ in range(rounds):
            h=hashlib.sha256(h).digest()
        hx=h.hex()
        if best is None or hx<best["hash"]:
            best={"unit":unit,"hash":hx}
    return {"summary":{"engine":"demo_hash","best":best,"rounds":rounds}}

def register(base,name):
    ch=http_json(base+"/api/register-challenge")
    payload={
        "display_name":name,"device_label":name+" PC",
        "pow_nonce":ch["nonce"],"pow_counter":solve_pow(ch["nonce"],ch["difficulty_bits"]),
        "meta":{"worker_version":"0.3.0","cpu_count":4,"machine":"AMD64",
                "capabilities":["cpu"],"hostname":"MUST-NOT-PERSIST"},
        "settings":{"cpu_percent":50,"gpu_percent":0,"allow_cpu":True,"allow_gpu":False},
    }
    return http_json(base+"/api/register","POST",payload)

def main():
    tmp=Path(tempfile.mkdtemp(prefix="enigma-http-v3-"))
    sock=socket.socket();sock.bind(("127.0.0.1",0));port=sock.getsockname()[1];sock.close()
    cfg=json.loads((ROOT/"config"/"server.example.json").read_text(encoding="utf-8"))
    cfg.update({"host":"127.0.0.1","port":port,"registration_open":True,
                "registration_code":"","registration_pow_bits":10,
                "min_worker_version":"0.3.0","rate_limit_per_minute":1000})
    cfg_path=tmp/"server.json";cfg_path.write_text(json.dumps(cfg),encoding="utf-8")
    env=os.environ.copy()
    env.update({"GRID_CONFIG":str(cfg_path),"GRID_DATA_DIR":str(tmp/"state"),
                "GRID_HOST":"127.0.0.1","GRID_PORT":str(port)})
    proc=subprocess.Popen([sys.executable,str(ROOT/"server"/"coordinator.py")],
                          cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    base=f"http://127.0.0.1:{port}"
    try:
        deadline=time.time()+10
        while True:
            try:
                if http_json(base+"/health").get("ok"):
                    break
            except Exception:
                if time.time()>deadline:
                    raise
                time.sleep(.1)
        db=tmp/"state"/"grid.sqlite3"
        con=sqlite3.connect(db)
        con.execute("insert into campaigns(id,name,version,status,created,notes) values(?,?,?,?,?,?)",
                    ("it","Integration","test","running",time.time(),""))
        config=json.dumps({"hash_rounds":20,"requires":["cpu"],"replicas_required":2,"max_replicas":3})
        con.execute("""insert into segments(id,campaign_id,label,engine,start_unit,end_unit,next_unit,
                     chunk_size,priority,config_json) values(?,?,?,?,?,?,?,?,?,?)""",
                    ("it-seg","it","Integration demo","demo_hash",0,4,0,2,1,config))
        con.commit();con.close()
        a=register(base,"Alice")
        hb=http_json(base+"/api/heartbeat","POST",
                     {"meta":{"worker_version":"0.3.0","cpu_count":4,"capabilities":["cpu"]}},
                     a["device_token"])
        assert hb["ok"] and not hb["update_required"]
        lease_response=http_json(base+"/api/lease","POST",{"meta":{}},a["device_token"])
        la=lease_response.get("lease")
        assert la and la["segment_id"]=="it-seg" and la["purpose"]=="primary",lease_response
        previous_id=la['id']
        http_json(base+'/api/device/settings','POST',{'settings':{'cpu_percent':0,'gpu_percent':0}},a['device_token'])
        assert http_json(base+'/api/lease','POST',{},a['device_token'])['lease'] is None
        http_json(base+'/api/device/settings','POST',{'settings':{'cpu_percent':50,'gpu_percent':0}},a['device_token'])
        replacement=http_json(base+'/api/lease','POST',{},a['device_token'])['lease']
        assert replacement['id']!=previous_id
        assert (replacement['start_unit'],replacement['end_unit'])==(la['start_unit'],la['end_unit'])
        la=replacement
        result=demo_result(la["segment_id"],la["start_unit"],la["end_unit"],20)
        ack1=http_json(base+"/api/complete","POST",
                       {"lease_id":la["id"],"work_token":la["work_token"],
                        "compute_seconds":1,"candidate_count":0,"result":result},
                       a["device_token"])
        assert ack1["validation_status"].startswith("pending") and not ack1["credited"]
        b=register(base,"Bob")
        lb=http_json(base+"/api/lease","POST",{"meta":{}},b["device_token"])["lease"]
        assert lb and lb["purpose"]=="validation"
        assert (lb["start_unit"],lb["end_unit"])==(la["start_unit"],la["end_unit"])
        ack2=http_json(base+"/api/complete","POST",
                       {"lease_id":lb["id"],"work_token":lb["work_token"],
                        "compute_seconds":1,"candidate_count":0,"result":result},
                       b["device_token"])
        assert ack2["validation_status"]=="verified" and ack2["credited"]
        con=sqlite3.connect(db);con.row_factory=sqlite3.Row
        meta=json.loads(con.execute("select meta_json from devices where id=?",(a["device_id"],)).fetchone()["meta_json"])
        assert "hostname" not in meta
        credits=con.execute("select count(*) from contributions").fetchone()[0]
        done=con.execute("select count(*) from done_ranges").fetchone()[0]
        con.close()
        assert credits==2 and done==1
        print("HTTP_INTEGRATION_V3_OK",{"range":[la["start_unit"],la["end_unit"]],"credits":credits})
    finally:
        proc.terminate()
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:proc.kill()
        shutil.rmtree(tmp,ignore_errors=True)

if __name__=="__main__":
    main()
