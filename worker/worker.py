import argparse
import base64
import ctypes
import hashlib
import ipaddress
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import urlparse
from pathlib import Path

try:
    from updater import UpdateManager
    UPDATE_IMPORT_ERROR=None
except Exception as _update_ex:
    UpdateManager=None
    UPDATE_IMPORT_ERROR=repr(_update_ex)

VERSION="0.3.0"
ROOT=Path(__file__).resolve().parents[1]
_HW=None

def validate_server_url(server):
    p=urlparse(server)
    if p.scheme=="https": return
    if p.scheme!="http": raise ValueError("Server URL must use https, or http on a private/local network")
    host=(p.hostname or "").lower()
    if host=="localhost": return
    try:
        ip=ipaddress.ip_address(host)
        tailscale=ip in ipaddress.ip_network("100.64.0.0/10")
        if ip.is_private or ip.is_loopback or ip.is_link_local or tailscale:return
    except ValueError:pass
    raise ValueError("Refusing plaintext HTTP to a public server; use HTTPS")

def get_json(server,path,timeout=30):
    validate_server_url(server)
    req=urllib.request.Request(server.rstrip("/")+path,headers={"User-Agent":"EnigmaVolunteerGrid/"+VERSION})
    with urllib.request.urlopen(req,timeout=timeout) as f:return json.loads(f.read())

def post(server,path,obj,token=None,timeout=30):
    validate_server_url(server)
    data=json.dumps(obj,separators=(",",":")).encode()
    headers={"Content-Type":"application/json"}
    if token:headers["X-Device-Token"]=token
    req=urllib.request.Request(server.rstrip("/")+path,data=data,headers=headers)
    with urllib.request.urlopen(req,timeout=timeout) as f:return json.loads(f.read())

def detect_nvidia():
    try:
        cmd=["nvidia-smi","--query-gpu=name,memory.total","--format=csv,noheader,nounits"]
        out=subprocess.check_output(cmd,text=True,timeout=5,stderr=subprocess.DEVNULL)
        gpus=[]
        for line in out.splitlines():
            parts=[x.strip() for x in line.split(",")]
            if len(parts)>=2:gpus.append({"vendor":"NVIDIA","name":parts[0],"memory_mb":int(float(parts[1]))})
        return gpus
    except Exception:return []
def hardware():
    global _HW
    if _HW is not None:return _HW
    gpus=detect_nvidia();caps=["cpu"]
    if gpus:caps+=["gpu","cuda"]
    _HW={"worker_version":VERSION,"platform":platform.platform(),
         "cpu_count":os.cpu_count() or 1,"machine":platform.machine(),
         "gpus":gpus,"capabilities":caps}
    return _HW

def normalize_settings(v):
    v=v if isinstance(v,dict) else {}
    cpu=max(0,min(100,int(v.get("cpu_percent",50))))
    gpu=max(0,min(100,int(v.get("gpu_percent",0))))
    return {"cpu_percent":cpu,"gpu_percent":gpu,
            "allow_cpu":bool(v.get("allow_cpu",cpu>0)),
            "allow_gpu":bool(v.get("allow_gpu",gpu>0))}

def cpu_threads(percent):
    n=os.cpu_count() or 1
    if percent<=0:return 0
    return max(1,min(n,round(n*percent/100)))

def apply_cpu_limit(percent):
    n=cpu_threads(percent)
    if n<=0:return 0
    total=os.cpu_count() or 1
    try:
        if os.name=="nt":
            mask=(1<<n)-1
            ctypes.windll.kernel32.SetProcessAffinityMask(ctypes.windll.kernel32.GetCurrentProcess(),mask)
        elif hasattr(os,"sched_setaffinity"):
            os.sched_setaffinity(0,set(range(n)))
    except Exception:pass
    try:
        import numba
        numba.set_num_threads(min(n,numba.config.NUMBA_NUM_THREADS))
    except Exception:pass
    return n
def meta(runtime=None):
    x=dict(hardware())
    if runtime:
        x["effective_settings"]=runtime.get("settings",{})
        x["cpu_threads_effective"]=runtime.get("cpu_threads",0)
    return x

def _dpapi(data,protect=True):
    if os.name!="nt":return data
    class BLOB(ctypes.Structure):
        _fields_=[("cbData",ctypes.c_ulong),("pbData",ctypes.POINTER(ctypes.c_ubyte))]
    raw=(ctypes.c_ubyte*len(data)).from_buffer_copy(data)
    src=BLOB(len(data),ctypes.cast(raw,ctypes.POINTER(ctypes.c_ubyte)));dst=BLOB()
    fn=ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    args=(ctypes.byref(src),None,None,None,None,0x1,ctypes.byref(dst)) if protect else (ctypes.byref(src),None,None,None,None,0x1,ctypes.byref(dst))
    if not fn(*args):raise ctypes.WinError()
    try:return ctypes.string_at(dst.pbData,dst.cbData)
    finally:ctypes.windll.kernel32.LocalFree(dst.pbData)

def load_state(path):
    if not path.exists():return None
    obj=json.loads(path.read_text(encoding="utf-8"))
    if isinstance(obj,dict) and obj.get("_format")=="dpapi-v1":
        raw=base64.b64decode(obj["blob"],validate=True)
        return json.loads(_dpapi(raw,False).decode("utf-8"))
    if os.name=="nt" and isinstance(obj,dict):
        save_state(path,obj)
    return obj

def save_state(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+".tmp")
    raw=json.dumps(obj,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    if os.name=="nt":
        wrapped={"_format":"dpapi-v1","blob":base64.b64encode(_dpapi(raw,True)).decode("ascii")}
        tmp.write_text(json.dumps(wrapped,separators=(",",":")),encoding="utf-8")
    else:
        tmp.write_text(json.dumps(obj,indent=2),encoding="utf-8")
        try:os.chmod(tmp,0o600)
        except Exception:pass
    tmp.replace(path)

def save_plain_json(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,separators=(",",":")),encoding="utf-8");tmp.replace(path)

def solve_registration_pow(server):
    c=get_json(server,"/api/register-challenge",30)
    nonce=str(c["nonce"]);bits=int(c["difficulty_bits"])
    counter=0
    while True:
        digest=hashlib.sha256((nonce+":"+str(counter)).encode("utf-8")).digest()
        if (int.from_bytes(digest,"big")>>(256-bits))==0:
            return nonce,counter
        counter+=1

def register(args,state_path):
    st=normalize_settings({"cpu_percent":args.cpu_percent,"gpu_percent":args.gpu_percent,
                           "allow_cpu":args.cpu_percent>0,"allow_gpu":args.gpu_percent>0})
    payload={"registration_code":args.registration_code,"display_name":args.name or "Anonymous volunteer",
             "device_label":args.device_label or "Volunteer PC","public_credit":not args.private_credit,
             "meta":hardware(),"settings":st}
    if not args.registration_code:
        nonce,counter=solve_registration_pow(args.server)
        payload["pow_nonce"]=nonce;payload["pow_counter"]=counter
    if args.contributor_key:payload["contributor_key"]=args.contributor_key
    r=post(args.server,"/api/register",payload)
    state={"server":args.server.rstrip("/"),"device_id":r["device_id"],"device_token":r["device_token"],
           "contributor_id":r["contributor_id"],"settings":r.get("settings",st)}
    if r.get("contributor_key"):state["contributor_key"]=r["contributor_key"]
    if r.get("dashboard_token"):state["dashboard_token"]=r["dashboard_token"]
    save_state(state_path,state);return state

def heartbeat_once(state,runtime):
    r=post(state["server"],"/api/heartbeat",{"meta":meta(runtime)},state["device_token"])
    if r.get("settings") is not None:runtime["settings"]=normalize_settings(r["settings"])
    runtime["enabled"]=bool(r.get("enabled",True));runtime["trust_score"]=r.get("trust_score")
    runtime["quarantined"]=bool(r.get("quarantined",False))
    return r
def heartbeat_loop(stop,state,runtime):
    while not stop.wait(20):
        try:heartbeat_once(state,runtime)
        except Exception:pass

def run_demo(lease):
    cfg=lease.get("config",{});rounds=int(cfg.get("hash_rounds",2000));best=None
    for unit in range(int(lease["start_unit"]),int(lease["end_unit"])):
        h=f"{lease['segment_id']}:{unit}".encode()
        for _ in range(rounds):h=hashlib.sha256(h).digest()
        hx=h.hex()
        if best is None or hx<best["hash"]:best={"unit":unit,"hash":hx}
    return {"summary":{"engine":"demo_hash","best":best,"rounds":rounds}},0

def run_event_stochastic(lease):
    runtime=ROOT/"solver"/"runtime";sys.path.insert(0,str(runtime/"src"))
    from search.event_stochastic import run_event_stochastic
    msg=json.loads((runtime/"data"/"messages"/"p1030680.json").read_text(encoding="utf-8"))
    target=msg["ciphertext"];cfg=lease["config"]
    count=int(cfg.get("count_per_unit",32768));iters=int(cfg.get("iterations",800))
    topk=int(cfg.get("topk",6));base=int(cfg.get("base_attempt",310000000))
    mn=int(cfg.get("min_pairs",0));mx=int(cfg.get("max_pairs",13));kinds=tuple(cfg.get("event_kinds",[1,2,3,4,5]))
    out=[]
    for unit in range(int(lease["start_unit"]),int(lease["end_unit"])):
        hits=run_event_stochastic(target,base+unit*count,count=count,iterations=iters,topk=topk,
                                  min_pairs=mn,max_pairs=mx,event_kinds=kinds,
                                  assumptions=("volunteer_grid",lease["segment_label"]))
        for h in hits:h["unit"]=unit
        out.extend(hits)
    out.sort(key=lambda x:x.get("score",-1e99),reverse=True);out=out[:max(topk,12)]
    return {"summary":{"engine":"event_stochastic_v1","units":lease["end_unit"]-lease["start_unit"]},
            "candidates":out},len(out)
def execute(lease):
    if lease["engine"]=="demo_hash":return run_demo(lease)
    if lease["engine"]=="event_stochastic_v1":return run_event_stochastic(lease)
    raise RuntimeError("Unsupported engine: "+repr(lease["engine"]))

def gpu_cooldown(percent,compute_seconds):
    if percent<=0:return 60
    if percent>=100:return 0
    return max(0.0,compute_seconds*(100.0-percent)/percent)

def disable(state):
    try:return post(state["server"],"/api/device/disable",{"meta":hardware()},state["device_token"])
    except Exception as e:return {"ok":False,"error":repr(e)}

def set_preferences(state,cpu,gpu):
    st=normalize_settings({"cpu_percent":cpu,"gpu_percent":gpu,"allow_cpu":cpu>0,"allow_gpu":gpu>0})
    r=post(state["server"],"/api/device/settings",{"settings":st,"meta":hardware()},state["device_token"])
    state["settings"]=r.get("settings",st);return r

def work(args,state):
    runtime={"settings":normalize_settings(state.get("settings",{})),"enabled":True}
    state_path=Path(args.state)
    updater=UpdateManager(VERSION,state_path,state["server"]) if UpdateManager else None
    if updater:updater.start()
    save_plain_json(ROOT/".worker-health.json",{"version":VERSION,"started":time.time()})
    while True:
        try:
            if updater and updater.stop_requested:
                print("Mandatory update declined: stopping safely.",flush=True)
                return 0
            if updater and updater.apply_requested:
                updater.shutdown()
                if updater.launch_apply(ROOT):
                    print("Applying verified update at safe point.",flush=True)
                    return 0
            hb=heartbeat_once(state,runtime)
            if hb.get("update_required") and updater:updater.force_check()
            if not runtime["enabled"]:
                print("Worker disabled or quarantined by coordinator.");return 0
            st=runtime["settings"];runtime["cpu_threads"]=apply_cpu_limit(st["cpu_percent"])
            got=post(state["server"],"/api/lease",{"meta":meta(runtime)},state["device_token"])
            if got.get("update_required") and updater:updater.force_check()
            lease=got.get("lease")
            if not lease:
                if args.once:return 0
                time.sleep(args.idle_seconds);continue
            resource=lease.get("resource_class","cpu");pct=int(lease.get("resource_percent",100))
            if resource=="cpu" and (not st["allow_cpu"] or st["cpu_percent"]<=0):
                time.sleep(args.idle_seconds);continue
            if resource=="gpu" and (not st["allow_gpu"] or st["gpu_percent"]<=0):
                time.sleep(args.idle_seconds);continue
            print(f"Lease {lease['id']} {lease['purpose']} {resource}@{pct}% {lease['segment_label']} {lease['start_unit']}:{lease['end_unit']}",flush=True)
            stop=threading.Event();th=threading.Thread(target=heartbeat_loop,args=(stop,state,runtime),daemon=True);th.start()
            t=time.time()
            try:result,candidates=execute(lease)
            finally:stop.set();th.join(timeout=2)
            secs=time.time()-t
            ack=post(state["server"],"/api/complete",
                     {"lease_id":lease["id"],"work_token":lease["work_token"],"compute_seconds":secs,
                      "candidate_count":candidates,"result":result,"meta":meta(runtime)},
                     state["device_token"],timeout=120)
            print(json.dumps({"completed":lease["id"],"seconds":round(secs,3),"ack":ack}),flush=True)
            if updater and updater.stop_requested:
                print("Mandatory update declined: current work finished; closing.",flush=True)
                return 0
            if updater and updater.apply_requested:
                updater.shutdown()
                if updater.launch_apply(ROOT):
                    print("Verified update ready; restarting at safe point.",flush=True)
                    return 0
            if resource=="gpu":
                cool=gpu_cooldown(pct,secs)
                if cool>0:time.sleep(cool)
            if args.once:return 0
        except KeyboardInterrupt:return 130
        except Exception as e:
            print(json.dumps({"worker_error":repr(e)}),flush=True)
            if args.once:return 2
            time.sleep(10)

def main():
    ap=argparse.ArgumentParser(description="Volunteer Enigma Grid worker v0.3")
    ap.add_argument("--server",default=os.environ.get("ENIGMA_GRID_SERVER",""));ap.add_argument("--registration-code",default="")
    ap.add_argument("--name",default="");ap.add_argument("--device-label",default="");ap.add_argument("--contributor-key",default="")
    ap.add_argument("--private-credit",action="store_true");ap.add_argument("--state",default=str(Path.home()/".enigma-volunteer"/"client.json"))
    ap.add_argument("--show-secrets",action="store_true")
    ap.add_argument("--once",action="store_true");ap.add_argument("--disable",action="store_true")
    ap.add_argument("--register-only",action="store_true")
    ap.add_argument("--set-preferences",action="store_true");ap.add_argument("--cpu-percent",type=int,default=50)
    ap.add_argument("--gpu-percent",type=int,default=0);ap.add_argument("--idle-seconds",type=int,default=5)
    args=ap.parse_args();state_path=Path(args.state);state=load_state(state_path)
    if state is None:
        if not args.server:raise SystemExit("First run requires --server (or ENIGMA_GRID_SERVER)")
        if not args.registration_code:raise SystemExit("First run requires --registration-code")
        state=register(args,state_path);print("Registered device",state["device_id"],flush=True)
        if args.show_secrets:
            if state.get("dashboard_token"):print("Dashboard token:",state["dashboard_token"],flush=True)
            if state.get("contributor_key"):print("Contributor key:",state["contributor_key"],flush=True)
        else:
            print("Private credentials stored locally with user-only file permissions.",flush=True)
    if args.register_only:return
    if args.disable:print(json.dumps(disable(state)));return
    if args.set_preferences:
        print(json.dumps(set_preferences(state,args.cpu_percent,args.gpu_percent)));save_state(state_path,state);return
    raise SystemExit(work(args,state))

if __name__=="__main__":main()
