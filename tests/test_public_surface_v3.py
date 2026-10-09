import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def request(url,method="GET",body=None):
    data=None if body is None else json.dumps(body).encode()
    req=urllib.request.Request(url,data=data,method=method,headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=5) as r:
            return r.status,dict(r.headers),r.read()
    except urllib.error.HTTPError as e:
        return e.code,dict(e.headers),e.read()

def main():
    tmp=Path(tempfile.mkdtemp(prefix="enigma-public-surface-"))
    s=socket.socket();s.bind(("127.0.0.1",0));port=s.getsockname()[1];s.close()
    cfg=json.loads((ROOT/"config"/"server.example.json").read_text())
    cfg.update({"host":"127.0.0.1","port":port,"registration_open":False,
                "registration_code":"","rate_limit_per_minute":1000})
    cfgp=tmp/"server.json";cfgp.write_text(json.dumps(cfg))
    env=os.environ.copy();env.update({"GRID_CONFIG":str(cfgp),"GRID_DATA_DIR":str(tmp/"state"),
                                      "GRID_DB":str(tmp/"state/grid.sqlite3"),
                                      "GRID_HOST":"127.0.0.1","GRID_PORT":str(port)})
    proc=subprocess.Popen([sys.executable,str(ROOT/"server"/"coordinator.py")],
                          cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    base=f"http://127.0.0.1:{port}"
    try:
        end=time.time()+10
        while True:
            code,_,_=request(base+"/health")
            if code==200:break
            if time.time()>end:raise RuntimeError("coordinator did not start")
            time.sleep(.1)

        code,h,_=request(base+"/")
        assert code==200
        assert h.get("X-Content-Type-Options")=="nosniff"
        assert h.get("X-Frame-Options")=="DENY"
        assert "default-src 'self'" in h.get("Content-Security-Policy","")
        for path in ("/.git/config","/config/server.json","/state/grid.sqlite3",
                     "/server/coordinator.py","/shared_token.txt","/admin","/api/admin","/admin.js","/api/status"):
            code,_,_=request(base+path)
            assert code in (403,404), (path,code)
        code,_,body=request(base+"/api/public/config")
        assert code==200 and "registration_code" not in body.decode()
        code,_,_=request(base+"/api/register","POST",{"display_name":"blocked"})
        assert code in (403,429)
        for body in ([],"invalid",123,None):
            if body is None:continue
            code,_,_=request(base+"/api/register","POST",body)
            assert code==400,(body,code)
        code,_,_=request(base+"/api/me","POST",{"dashboard_token":[]})
        assert code in (400,403)
        assert request(base+"/health")[0]==200
        print("PUBLIC_SURFACE_V3_OK")
    finally:
        proc.terminate()
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:proc.kill()
        import shutil;shutil.rmtree(tmp,ignore_errors=True)

if __name__=="__main__":main()
