import argparse
import base64
import ctypes
import hashlib
import ipaddress
import json
import os
import platform
import socket
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
from file_state import atomic_write

try:
    from updater import UpdateManager
    UPDATE_IMPORT_ERROR=None
except Exception as _update_ex:
    UpdateManager=None
    UPDATE_IMPORT_ERROR=repr(_update_ex)

VERSION="0.4.3"
SOURCE_ROOT=Path(__file__).resolve().parents[1]
FROZEN=bool(getattr(sys,"frozen",False))
ROOT=Path(getattr(sys,"_MEIPASS",SOURCE_ROOT))
INSTALL_ROOT=Path(sys.executable).resolve().parent if FROZEN else SOURCE_ROOT
_HW=None
_WORKER_MUTEX=None
_GPU_SCORERS=[]

def acquire_worker_mutex():
    global _WORKER_MUTEX
    if os.name!="nt":return True
    ctypes.windll.kernel32.CreateMutexW.restype=ctypes.c_void_p
    ctypes.windll.kernel32.CloseHandle.argtypes=[ctypes.c_void_p]
    h=ctypes.windll.kernel32.CreateMutexW(None,False,"Local\\EnigmaVolunteerGridWorker")
    if not h:raise ctypes.WinError()
    if ctypes.windll.kernel32.GetLastError()==183:
        ctypes.windll.kernel32.CloseHandle(h);return False
    _WORKER_MUTEX=h;return True

def validate_server_url(server):
    p=urlparse(server)
    if not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError("Server URL must contain a host and no credentials, query or fragment")
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

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise ValueError("Coordinator redirects are not allowed")

def _response_json(req,timeout):
    # Never forward device credentials to a redirected host; bound untrusted replies.
    opener=urllib.request.build_opener(_NoRedirect())
    with opener.open(req,timeout=timeout) as response:  # nosec B310 - validated coordinator URL
        body=response.read(4*1024*1024+1)
    if len(body)>4*1024*1024:raise ValueError("Coordinator response too large")
    result=json.loads(body)
    if not isinstance(result,dict):raise ValueError("Invalid coordinator response")
    return result

def get_json(server,path,timeout=30):
    validate_server_url(server)
    req=urllib.request.Request(server.rstrip("/")+path,headers={"User-Agent":"EnigmaVolunteerGrid/"+VERSION})
    return _response_json(req,timeout)

def post(server,path,obj,token=None,timeout=30):
    validate_server_url(server)
    data=json.dumps(obj,separators=(",",":")).encode()
    headers={"Content-Type":"application/json"}
    if token:headers["X-Device-Token"]=token
    req=urllib.request.Request(server.rstrip("/")+path,data=data,headers=headers)
    return _response_json(req,timeout)

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
    gpus=[];caps=["cpu","bounded_crib_v1"]
    sys.path.insert(0,str(ROOT/"solver"/"runtime"/"src"))
    try:
        from search.portable_search import opencl_devices, qualify_device
        import numba
        previous=numba.get_num_threads();numba.set_num_threads(min(2,previous))
        try:
            text=json.loads((ROOT/"solver/runtime/data/messages/p1030680.json").read_text())["ciphertext"]
            for device in opencl_devices():
                try:
                    scorer=qualify_device(device,text)
                    _GPU_SCORERS.append(scorer)
                    gpus.append({"vendor":device.vendor.strip(),"name":device.name.strip(),
                                 "memory_mb":device.global_mem_size//(1024*1024),"backend":"opencl"})
                except Exception:continue
        finally:numba.set_num_threads(previous)
    except Exception:pass
    if gpus:caps += ["gpu","opencl"]
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
            kernel=ctypes.windll.kernel32
            kernel.GetCurrentProcess.restype=ctypes.c_void_p
            kernel.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
            mask=(1<<min(n,ctypes.sizeof(ctypes.c_size_t)*8))-1
            kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(),mask)
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
    raw=json.dumps(obj,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    if os.name=="nt":
        wrapped={"_format":"dpapi-v1","blob":base64.b64encode(_dpapi(raw,True)).decode("ascii")}
        raw=json.dumps(wrapped,separators=(",",":" )).encode("utf-8")
    atomic_write(path,raw)

def save_plain_json(path,obj):
    atomic_write(path,json.dumps(obj,separators=(",",":")).encode("utf-8"))

def control_path(state_path):
    return Path(state_path).with_name("control.json")

def read_control(state_path):
    try:
        obj=json.loads(control_path(state_path).read_text(encoding="utf-8"))
        return {"paused":bool(obj.get("paused",False)),
                "stop_requested":bool(obj.get("stop_requested",False)),
                "check_update":bool(obj.get("check_update",False))}
    except Exception:return {"paused":False,"stop_requested":False,"check_update":False}

def write_control(state_path,control):
    save_plain_json(control_path(state_path),{
        "paused":bool(control.get("paused",False)),
        "stop_requested":bool(control.get("stop_requested",False)),
        "check_update":bool(control.get("check_update",False))})

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
        publish_health(runtime)
        try:heartbeat_once(state,runtime)
        except Exception:pass

def publish_health(runtime, status=None):
    if status:runtime["status"]=status
    path=runtime.get("health_path")
    if path:
        try:
            save_plain_json(path,{"version":VERSION,"pid":os.getpid(),"started":runtime.get("started",time.time()),
                                  "heartbeat":time.time(),"status":runtime.get("status","starting"),
                                  "resource":runtime.get("resource","cpu"),"progress":runtime.get("progress",0)})
        except OSError:
            # A telemetry write must never abort a computation or its heartbeat.
            # The next progress/heartbeat update retries; credentials and control
            # writes deliberately retain their error reporting.
            return False
    return True

def client_summary(state_path):
    state=load_state(Path(state_path))
    hw=_HW or {}
    base={"registered":bool(state),"hardware":{"cpu_count":hw.get("cpu_count",os.cpu_count() or 1),
          "capabilities":hw.get("capabilities",[]),"gpus":hw.get("gpus",[]),
          "source":"local_probe" if _HW is not None else "not_probed",
          "detection_complete":_HW is not None},
          "worker_version":VERSION}
    if not state:return base
    base["server"]=state.get("server","")
    base["settings"]=normalize_settings(state.get("settings",{}))
    base["device_id"]=state.get("device_id","")
    try:base["global"]=get_json(state["server"],"/api/public/status",10)
    except Exception as e:base["global_error"]=type(e).__name__
    token=state.get("dashboard_token","")
    if token:
        try:
            base["personal"]=post(state["server"],"/api/me",{"dashboard_token":token},timeout=10)
            for d in base["personal"].get("devices",[]):
                if d["id"]==state.get("device_id"):
                    base["settings"]=d["settings"]
                    meta=d.get("meta",{})
                    if _HW is None and meta.get("cpu_count"):
                        base["hardware"]={"cpu_count":meta["cpu_count"],
                            "capabilities":meta.get("capabilities",[]),"gpus":meta.get("gpus",[]),
                            "source":"last_server_report","detection_complete":False}
        except Exception as e:base["personal_error"]=type(e).__name__
    return base

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
def run_portable(lease,runtime=None,state_path=None):
    from concurrent.futures import ThreadPoolExecutor
    from search.portable_search import search,score_cpu
    from search.cpu_numba import encode
    import numpy as np
    cfg=lease["config"]
    text=json.loads((ROOT/"solver/runtime/data/messages/p1030680.json").read_text())["ciphertext"]
    inp=encode(text);runtime=runtime or {}
    settings=runtime.get("settings",{"cpu_percent":50,"gpu_percent":0})
    gpu=bool(_GPU_SCORERS and settings.get("allow_gpu",True) and settings.get("gpu_percent",0)>0)
    cpu=bool(settings.get("allow_cpu",True) and settings.get("cpu_percent",0)>0)
    backend="opencl" if gpu else "cpu"
    runtime["resource"]="CPU + GPU" if gpu and cpu else ("GPU" if gpu else "CPU")
    threads=cpu_threads(settings.get("cpu_percent",50)) or 1
    def cpu_score(keys):
        import numba
        numba.set_num_threads(min(threads,numba.config.NUMBA_NUM_THREADS))
        return score_cpu(inp,keys)
    from scoring_pool import OrderedScorers
    gpu_pool=OrderedScorers(_GPU_SCORERS) if gpu else None
    def gpu_score(keys):return np.concatenate(gpu_pool.score(keys))
    pool=ThreadPoolExecutor(max_workers=1) if gpu and cpu else None
    def scorer(keys):
        if gpu and cpu and len(keys)>1:
            middle=len(keys)//2
            future=pool.submit(cpu_score,keys[:middle])
            right=gpu_score(keys[middle:])
            return np.concatenate((future.result(),right))
        return gpu_score(keys) if gpu else cpu_score(keys)
    def checkpoint(offset,iteration):
        if not state_path:return
        ctl=read_control(state_path)
        while ctl["paused"] and not ctl["stop_requested"]:
            publish_health(runtime,"paused");time.sleep(.25);ctl=read_control(state_path)
        count=max(1,int(cfg.get("count_per_unit",4096)))
        iterations=max(1,int(cfg.get("iterations",512)))
        unit_progress=(offset+min(256,count-offset)*iteration/iterations)/count
        runtime["progress"]=(unit-int(lease["start_unit"])+unit_progress)/max(1,int(lease["end_unit"])-int(lease["start_unit"]))
        # Health writes are throttled; the separate heartbeat also covers compilation.
        if time.monotonic()-runtime.get("last_local_health",0)>2:
            publish_health(runtime,"stopping" if ctl["stop_requested"] else "computing")
            runtime["last_local_health"]=time.monotonic()
    out=[]
    try:
        for unit in range(int(lease["start_unit"]),int(lease["end_unit"])):
            count=int(cfg.get("count_per_unit",4096));topk=int(cfg.get("topk",8))
            hits=search(text,int(cfg.get("base_attempt",71000000000))+unit*count,
                        count=count,iterations=int(cfg.get("iterations",512)),topk=topk,
                        min_pairs=int(cfg.get("min_pairs",0)),max_pairs=int(cfg.get("max_pairs",13)),
                        event_kinds=tuple(cfg.get("event_kinds",[1,2,3,4,5,6])),backend=backend,
                        percent=int(settings.get("gpu_percent",100)) if gpu else 100,
                        checkpoint=checkpoint,scorer=scorer)
            for hit in hits:hit["unit"]=unit
            out.extend(hits)
        runtime["progress"]=1.0
    finally:
        if pool:pool.shutdown(wait=True)
        if gpu_pool:gpu_pool.close()
    out.sort(key=lambda x:(-x["score"],x["attempt"]));out=out[:max(topk,12)]
    return {"summary":{"engine":"portable_event_v1","units":lease["end_unit"]-lease["start_unit"]},"candidates":out},len(out)

def run_constrained(lease,runtime=None,state_path=None):
    from search.crib_work import run
    runtime=runtime if runtime is not None else {}
    runtime['resource']='CPU'
    last=time.monotonic()
    def checkpoint(done,total):
        nonlocal last
        settings=runtime.get('settings',{'allow_cpu':True,'cpu_percent':50})
        if not settings.get('allow_cpu',True) or settings.get('cpu_percent',0)<=0:
            raise InterruptedError('CPU disabled during constrained work')
        if state_path:
            ctl=read_control(state_path)
            while ctl['paused'] and not ctl['stop_requested']:
                publish_health(runtime,'paused');time.sleep(.25);ctl=read_control(state_path)
            if ctl['stop_requested']:
                raise InterruptedError('Constrained work stopped; no completion submitted')
        now=time.monotonic()
        # One CPU thread. Bound duty as well as parallelism for this engine.
        pct=max(1,min(100,int(settings.get('cpu_percent',50))))
        delay=(now-last)*(100-pct)/pct
        until=time.monotonic()+delay
        while time.monotonic()<until:
            if state_path and read_control(state_path)['stop_requested']:
                raise InterruptedError('Constrained work stopped during cooldown')
            time.sleep(min(.1,max(0,until-time.monotonic())))
        last=time.monotonic()
        runtime['progress']=done/max(1,total)
        if state_path:publish_health(runtime,'computing')
    result=run(lease,checkpoint=checkpoint)
    return result,len(result['receipt']['candidates'])

def execute(lease,runtime=None,state_path=None):
    if lease["engine"]=="demo_hash":return run_demo(lease)
    if lease["engine"]=="event_stochastic_v1":return run_event_stochastic(lease)
    if lease["engine"]=="portable_event_v1":return run_portable(lease,runtime,state_path)
    if lease["engine"]=="bounded_crib_v1":return run_constrained(lease,runtime,state_path)
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
    if not acquire_worker_mutex():
        print("Worker already running for this Windows user.",flush=True);return 0
    runtime={"settings":normalize_settings(state.get("settings",{})),"enabled":True}
    state_path=Path(args.state);health_path=state_path.with_name("worker-health.json")
    updater=UpdateManager(VERSION,state_path,state["server"]) if UpdateManager else None
    if updater:updater.start()
    started=time.time()
    runtime.update(health_path=health_path,started=started)
    publish_health(runtime,"starting")
    while True:
        try:
            publish_health(runtime)
            control=read_control(state_path)
            if control["stop_requested"]:
                print("Safe stop requested; worker is idle and will close.",flush=True)
                publish_health(runtime,"stopped")
                if updater:updater.shutdown()
                return 0
            if control["check_update"]:
                control["check_update"]=False;write_control(state_path,control)
                if updater:updater.force_check()
            if control["paused"]:
                publish_health(runtime,"paused")
                time.sleep(args.idle_seconds);continue
            if updater and updater.stop_requested:
                print("Mandatory update declined: stopping safely.",flush=True)
                c=read_control(state_path);c["stop_requested"]=True;write_control(state_path,c)
                return 0
            if updater and updater.apply_requested:
                updater.shutdown()
                if updater.launch_apply(INSTALL_ROOT):
                    print("Applying verified update at safe point.",flush=True)
                    return 0
            hb=heartbeat_once(state,runtime)
            if hb.get("update_required") and updater:updater.force_check()
            if not runtime["enabled"]:
                publish_health(runtime,"disabled")
                c=read_control(state_path);c["stop_requested"]=True;write_control(state_path,c)
                print("Worker disabled or quarantined by coordinator.");return 0
            st=runtime["settings"];runtime["cpu_threads"]=apply_cpu_limit(st["cpu_percent"])
            got=post(state["server"],"/api/lease",{"meta":meta(runtime)},state["device_token"])
            if got.get("update_required") and updater:updater.force_check()
            lease=got.get("lease")
            if not lease:
                publish_health(runtime,"waiting")
                if args.once:return 0
                time.sleep(args.idle_seconds);continue
            resource=lease.get("resource_class","cpu");pct=int(lease.get("resource_percent",100))
            if resource=="cpu" and (not st["allow_cpu"] or st["cpu_percent"]<=0):
                time.sleep(args.idle_seconds);continue
            if resource=="gpu" and (not st["allow_gpu"] or st["gpu_percent"]<=0):
                time.sleep(args.idle_seconds);continue
            print(f"Lease {lease['id']} {lease['purpose']} {resource}@{pct}% {lease['segment_label']} {lease['start_unit']}:{lease['end_unit']}",flush=True)
            stop=threading.Event();th=threading.Thread(target=heartbeat_loop,args=(stop,state,runtime),daemon=True);th.start()
            publish_health(runtime,"computing")
            t=time.time()
            try:result,candidates=execute(lease,runtime,state_path)
            finally:stop.set();th.join(timeout=2)
            secs=time.time()-t
            ack=post(state["server"],"/api/complete",
                     {"lease_id":lease["id"],"work_token":lease["work_token"],"compute_seconds":secs,
                      "candidate_count":candidates,"result":result,"meta":meta(runtime)},
                     state["device_token"],timeout=120)
            print(json.dumps({"completed":lease["id"],"seconds":round(secs,3),"ack":ack}),flush=True)
            if updater and updater.stop_requested:
                print("Mandatory update declined: current work finished; closing.",flush=True)
                c=read_control(state_path);c["stop_requested"]=True;write_control(state_path,c)
                return 0
            if updater and updater.apply_requested:
                updater.shutdown()
                if updater.launch_apply(INSTALL_ROOT):
                    print("Verified update ready; restarting at safe point.",flush=True)
                    return 0
            if resource=="gpu" and lease.get("engine")!="portable_event_v1":
                cool=gpu_cooldown(pct,secs)
                if cool>0:time.sleep(cool)
            if args.once:return 0
        except KeyboardInterrupt:return 130
        except Exception as e:
            publish_health(runtime,"connection_error")
            print(json.dumps({"worker_error":repr(e)}),flush=True)
            if args.once:return 2
            time.sleep(10)

def main():
    ap=argparse.ArgumentParser(description="Volunteer Enigma Grid worker v0.3")
    ap.add_argument("--server",default=os.environ.get("ENIGMA_GRID_SERVER",""));ap.add_argument("--registration-code",default="")
    ap.add_argument("--name",default="");ap.add_argument("--device-label",default="");ap.add_argument("--contributor-key",default="")
    ap.add_argument("--private-credit",action="store_true");ap.add_argument("--state",default=str(Path.home()/".enigma-volunteer"/"client.json"))
    ap.add_argument("--show-secrets",action="store_true")
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--client-summary-json",action="store_true")
    ap.add_argument("--dashboard-token",action="store_true",help="Print the private dashboard token locally")
    ap.add_argument("--once",action="store_true");ap.add_argument("--disable",action="store_true")
    ap.add_argument("--register-only",action="store_true")
    ap.add_argument("--set-preferences",action="store_true");ap.add_argument("--cpu-percent",type=int,default=50)
    ap.add_argument("--gpu-percent",type=int,default=0);ap.add_argument("--idle-seconds",type=int,default=5)
    args=ap.parse_args()
    if args.self_test:
        h=hardware();assert "cpu_count" in h
        import numpy, numba
        print(json.dumps({"ok":True,"version":VERSION,"numpy":numpy.__version__,"numba":numba.__version__,
                          "cpu_count":h.get("cpu_count",1),"capabilities":h.get("capabilities",[]),
                          "gpus":h.get("gpus",[])}))
        return
    if args.client_summary_json:
        print(json.dumps(client_summary(args.state),ensure_ascii=False))
        return
    state_path=Path(args.state);state=load_state(state_path)
    if args.dashboard_token:
        if not state or not state.get("dashboard_token"):raise SystemExit("No dashboard token available")
        print(state["dashboard_token"]);return
    if state is None:
        if not args.server:raise SystemExit("First run requires --server (or ENIGMA_GRID_SERVER)")
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
