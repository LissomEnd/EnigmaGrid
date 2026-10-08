import argparse
import base64
import ctypes
import hashlib
import ipaddress
import json
import math
import os
import platform
import socket
import secrets
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
import time
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
from file_state import atomic_write
import windows_telemetry
from receipt_outbox import ReceiptOutbox,OutboxUploader,MAX_RESULTS
from completion_transport import CompletionTransport
from cpu_budget import CpuBudget
from summary_cache import SummaryPublisher

try:
    from updater import UpdateManager
    UPDATE_IMPORT_ERROR=None
except Exception as _update_ex:
    UpdateManager=None
    UPDATE_IMPORT_ERROR=repr(_update_ex)

VERSION="0.4.14"
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

def pending_path(state_path):
    return Path(state_path).with_name(Path(state_path).name+".pending-result")

def result_outbox(state_path,state):
    return ReceiptOutbox(pending_path(state_path),state,load_state,save_state)


def persist_completion(state_path,state,payload):
    result_outbox(state_path,state).append(payload)


def deliver_pending(state_path,state):
    queue=result_outbox(state_path,state);last=None
    for payload in queue.pending():
        ack=post(state['server'],'/api/complete',payload,state['device_token'],timeout=120)
        if not isinstance(ack,dict) or ack.get('ok') is not True:
            raise RuntimeError('Coordinator did not acknowledge saved result; retained locally')
        queue.acknowledge(payload['lease_id']);last=ack
    return last


def control_path(state_path):
    return Path(state_path).with_name("control.json")

def _thermal_limit(value,default,minimum,maximum):
    try:return max(minimum,min(maximum,int(value)))
    except Exception:return default

def read_control(state_path):
    try:
        obj=json.loads(control_path(state_path).read_text(encoding="utf-8"))
    except Exception:obj={}
    return {"paused":bool(obj.get("paused",False)),
            "stop_requested":bool(obj.get("stop_requested",False)),
            "check_update":bool(obj.get("check_update",False)),
            "max_cpu_temp_c":_thermal_limit(obj.get("max_cpu_temp_c"),80,55,95),
            "max_gpu_temp_c":_thermal_limit(obj.get("max_gpu_temp_c"),75,50,90)}

def write_control(state_path,control):
    save_plain_json(control_path(state_path),{
        "paused":bool(control.get("paused",False)),
        "stop_requested":bool(control.get("stop_requested",False)),
        "check_update":bool(control.get("check_update",False)),
        "max_cpu_temp_c":_thermal_limit(control.get("max_cpu_temp_c"),80,55,95),
        "max_gpu_temp_c":_thermal_limit(control.get("max_gpu_temp_c"),75,50,90)})

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

def apply_coordinator_state(reply,runtime):
    runtime['_control_revision']=runtime.get('_control_revision',0)+1
    runtime['wait_reason']=reply.get('wait_reason','')
    if reply.get("settings") is not None:runtime["settings"]=normalize_settings(reply["settings"])
    runtime["enabled"]=bool(reply.get("enabled",True));runtime["trust_score"]=reply.get("trust_score")
    runtime["quarantined"]=bool(reply.get("quarantined",False))
    return reply

def heartbeat_once(state,runtime):
    return apply_coordinator_state(post(state["server"],"/api/heartbeat",{"meta":meta(runtime)},state["device_token"]),runtime)

def request_work(state,runtime):
    if runtime.get('_batch_requests',False):
        return request_batch_work(state,runtime)
    reply=post(state["server"],"/api/lease",{"meta":meta(runtime)},state["device_token"])
    # New coordinators return the same control snapshot with the lease.
    # Older servers still need a heartbeat before executing any returned work.
    if all(key in reply for key in ("settings","enabled","quarantined")):
        control=apply_coordinator_state(reply,runtime)
    else:
        control=heartbeat_once(state,runtime)
    return reply,control

def batch_request_payload(runtime):
    uploader=runtime.get('_uploader')
    held=uploader.queue.held_count() if uploader is not None else 0
    computed=uploader.queue.computed_ids() if uploader is not None else set()
    queued={item['id'] for item in runtime.get('_lease_queue',[]) if item['id'] not in computed}
    free=max(0,32-held-len(queued))
    payload={'meta':meta(runtime),'count':32 if runtime.get('_new_lease_limit') else max(1,free)}
    if runtime.get('_new_lease_limit'):payload['max_new']=free
    return payload


def timed_batch_request(state,payload):
    started=time.monotonic()
    reply=post(state['server'],'/api/leases',payload,state['device_token'])
    return reply,time.monotonic()-started


def start_batch_prefetch(state,runtime):
    """Cover observed allocation latency with queued work, within 32 reservations."""
    job_seconds=max(.001,runtime.get('_mean_job_seconds',1.0))
    threshold=min(24,max(2,math.ceil(runtime.get('_allocation_seconds',1.0)/job_seconds)+2))
    if not runtime.get('_batch_requests') or len(runtime.get('_lease_queue',[]))>threshold or runtime.get('_batch_pending'):
        return
    uploader=runtime.get('_uploader')
    if uploader is None:return
    if uploader.queue.held_count()+len(runtime.get('_lease_queue',[]))>=32:return
    computed=uploader.queue.computed_ids()
    control_revision=runtime.get('_control_revision',0)
    payload=batch_request_payload(runtime)
    pool=runtime.get('_allocation_pool')
    if pool is None:
        pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='lease-prefetch')
        runtime['_allocation_pool']=pool
    future=pool.submit(timed_batch_request,state,payload)
    runtime['_batch_pending']=(future,computed,control_revision)


def request_batch_work(state,runtime,*,take=True):
    """Bounded reservations with legacy fallback and expiring local snapshots."""
    uploader=runtime.get('_uploader')
    computed=uploader.queue.computed_ids() if uploader is not None else set()
    queued=runtime.get('_lease_queue',[])
    if computed:
        queued=[item for item in queued if item['id'] not in computed]
        runtime['_lease_queue']=queued
    # Server renewals may extend these deadlines. Refetching an old snapshot is
    # safer than assuming that a reservation is still ours after a long pause.
    if queued and any(float(item['expires_at'])<=time.time() for item in queued):
        queued=[];runtime['_lease_queue']=queued
    if queued and take:
        if time.monotonic()-runtime.get('_batch_controls_at',0)>=20:
            control=heartbeat_once(state,runtime)
            runtime['_batch_controls']=control
            runtime['_batch_controls_at']=time.monotonic()
        control=runtime['_batch_controls']
        if not runtime.get('enabled',False) or control.get('update_required'):
            runtime['_lease_queue']=[]
            return {'lease':None,**control},control
        return {'lease':queued.pop(0) if take else None},control
    pending=runtime.pop('_batch_pending',None)
    stale_controls=False
    try:
        if pending:
            future,before_request,control_revision=pending
            computed=set(computed)|set(before_request)
            reply,runtime['_allocation_seconds']=future.result()
            stale_controls=runtime.get('_control_revision',0)!=control_revision
        else:
            reply,runtime['_allocation_seconds']=timed_batch_request(state,batch_request_payload(runtime))
    except urllib.error.HTTPError as error:
        if error.code!=404:raise
        runtime['_batch_requests']=False
        if not take:return {'lease':None},{}
        return request_work(state,runtime)
    # A heartbeat may have revoked the device or changed settings while the
    # prefetched response waited behind computation. Never overwrite that newer
    # control state with the old allocation snapshot.
    control=apply_coordinator_state(reply,runtime) if not stale_controls and all(k in reply for k in ('settings','enabled','quarantined')) else heartbeat_once(state,runtime)
    if not runtime.get('enabled',False) or reply.get('enabled') is False or reply.get('quarantined') or reply.get('update_required') or control.get('update_required'):
        return {'lease':None,'update_required':bool(reply.get('update_required') or control.get('update_required'))},control
    runtime['_new_lease_limit']=reply.get('new_lease_limit') is True
    leases=reply.get('leases')
    if not isinstance(leases,list) or len(leases)>32:raise ValueError('Invalid lease batch')
    ids=set()
    for lease in leases:
        if not isinstance(lease,dict) or not isinstance(lease.get('id'),str) or not lease['id'] or lease['id'] in ids or not isinstance(lease.get('work_token'),str):
            raise ValueError('Invalid or duplicate lease')
        if not isinstance(lease.get('expires_at'),(int,float)) or not math.isfinite(lease['expires_at']):
            raise ValueError('Invalid lease deadline')
        if lease['expires_at']<=time.time():raise ValueError('Coordinator returned expired work')
        ids.add(lease['id'])
    # The coordinator may replay leases whose durable receipts are uploading.
    # Keep the pre-request snapshot even when an acknowledgement arrives while
    # the allocation HTTP request is in flight.
    merged={item['id']:item for item in queued}
    merged.update({item['id']:item for item in leases})
    runtime['_lease_queue']=[item for item in merged.values() if item['id'] not in computed]
    runtime['wait_reason']=reply.get('wait_reason','')
    runtime['_batch_controls']=control;runtime['_batch_controls_at']=time.monotonic()
    return {'lease':runtime['_lease_queue'].pop(0) if take and runtime['_lease_queue'] else None,
            'retry_after_seconds':reply.get('retry_after_seconds',0)},control

def heartbeat_loop(stop,state,runtime):
    while not stop.wait(20):
        publish_health(runtime)
        try:heartbeat_once(state,runtime)
        except Exception:pass


def release_unused_work(state,runtime):
    """Return only work still queued locally, never an executing/durable receipt."""
    if runtime.get('_batch_pending'):
        try:request_batch_work(state,runtime,take=False)
        except Exception as error:runtime['release_error']=type(error).__name__
    queued=runtime.get('_lease_queue',[])
    if not queued:return True
    if time.monotonic()<runtime.get('_release_retry_at',0):return False
    try:
        capabilities=runtime.get('_release_capabilities')
        if capabilities is None:
            try:capabilities=get_json(state['server'],'/api/capabilities',5)
            except urllib.error.HTTPError as error:
                if error.code not in (404,405):raise
                capabilities={}
            runtime['_release_capabilities']=capabilities
        if not isinstance(capabilities,dict) or capabilities.get('release_leases') is not True:return False
        leases=[{'lease_id':item['id'],'work_token':item['work_token']} for item in queued]
        response=post(state['server'],'/api/leases/release',{'leases':leases},state['device_token'],timeout=5)
        if not isinstance(response,dict) or response.get('ok') is not True:raise ValueError('Lease release not acknowledged')
        runtime['_lease_queue']=[];runtime.pop('release_error',None)
        return True
    except Exception as error:
        runtime['release_error']=type(error).__name__
        runtime['_release_retry_at']=time.monotonic()+5
        return False

def runtime_guard(fn):
    """Protect shared metrics and file snapshots, never waits for compute jobs."""
    from functools import wraps
    @wraps(fn)
    def guarded(runtime,*args,**kwargs):
        with runtime.setdefault('_metrics_lock',threading.RLock()):
            return fn(runtime,*args,**kwargs)
    return guarded


@runtime_guard
def record_throughput(runtime, units, compute_seconds):
    now=time.monotonic()
    previous=runtime.get('_mean_job_seconds',compute_seconds)
    runtime['_mean_job_seconds']=.8*previous+.2*compute_seconds
    samples=runtime.setdefault('_throughput_samples',[])
    samples.append((now,units))
    totals=runtime.setdefault('throughput',{})
    totals['completed_units']=totals.get('completed_units',0)+units
    totals['completed_jobs']=totals.get('completed_jobs',0)+1
    totals['compute_seconds']=totals.get('compute_seconds',0)+compute_seconds
    totals['last_compute_seconds']=compute_seconds
    totals['last_units']=units


@runtime_guard
def throughput_snapshot(runtime):
    # A wall-time window includes allocation, durable writes and upload stalls.
    now=time.monotonic()
    samples=runtime.setdefault('_throughput_samples',[])
    samples[:]=[(at,units) for at,units in samples if now-at<5.0]
    result=dict(runtime.get('throughput',{}))
    result.update(units_per_second=sum(units for _,units in samples)/5.0,
                  jobs_per_second=len(samples)/5.0,window_seconds=5.0,sampled_at=time.time())
    return result


@runtime_guard
def publish_health(runtime, status=None):
    if status:runtime["status"]=status
    path=runtime.get("health_path")
    if path:
        try:
            ready_units=runtime.get("ready_units")
            if "_lease_queue" in runtime:
                ready_units=(ready_units or 0)+sum(max(0,int(item["end_unit"])-int(item["start_unit"]))
                    for item in tuple(runtime["_lease_queue"]) if float(item["expires_at"])>time.time())
            save_plain_json(path,{"version":VERSION,"pid":os.getpid(),"started":runtime.get("started",time.time()),
                                  "heartbeat":time.time(),"status":runtime.get("status","starting"),
                                  "resource":runtime.get("resource","cpu"),"progress":runtime.get("progress",0),
                                  "telemetry":runtime.get("telemetry",{}),
                                  "throughput":throughput_snapshot(runtime),
                                  "bounded_backend":runtime.get("bounded_backend","CPU"),
                                  "outbox_count":runtime.get("outbox_count",0),
                                  "expired_results":runtime.get("expired_results"),
                                  "running_jobs":runtime.get("running_jobs",0),
                                  "ready_units":ready_units,
                                  "ready_blocks":runtime.get("ready_blocks"),
                                  "persistence_seconds":runtime.get("persistence_seconds",0),
                                  "wait_reason":runtime.get("wait_reason",""),
                                  "thermal_reason":runtime.get("thermal_reason","")})
        except OSError:
            # A telemetry write must never abort a computation or its heartbeat.
            # The next progress/heartbeat update retries; credentials and control
            # writes deliberately retain their error reporting.
            return False
    return True

@runtime_guard
def _thermal_probe(runtime,state_path):
    now=time.monotonic()
    if runtime.get("_telemetry_device") is None:
        runtime["_telemetry_device"]=windows_telemetry.SystemTelemetry()
    if now-runtime.get("_telemetry_at",0)>=1 or "telemetry" not in runtime:
        try:runtime["telemetry"]=runtime["_telemetry_device"].sample()
        except Exception:runtime["telemetry"]={}
        runtime["_telemetry_at"]=now
    ctl=read_control(state_path)
    sample=runtime.get("telemetry",{})
    cpu=sample.get("cpu_temp_c");gpu=sample.get("gpu_temp_c")
    cpu_limit=int(ctl.get("max_cpu_temp_c",80));gpu_limit=int(ctl.get("max_gpu_temp_c",75))
    cpu_hot=runtime.get("_cpu_hot",False)
    gpu_hot=runtime.get("_gpu_hot",False)
    cpu_hot=(isinstance(cpu,(int,float)) and math.isfinite(cpu) and (cpu>cpu_limit-5 if cpu_hot else cpu>=cpu_limit))
    gpu_hot=(isinstance(gpu,(int,float)) and math.isfinite(gpu) and (gpu>gpu_limit-5 if gpu_hot else gpu>=gpu_limit))
    runtime["_cpu_hot"]=cpu_hot;runtime["_gpu_hot"]=gpu_hot
    if cpu_hot:reason=f"CPU cooling · {cpu:.1f}°C / {cpu_limit}°C"
    elif gpu_hot:reason=f"GPU cooling · {gpu:.1f}°C / {gpu_limit}°C"
    else:reason=""
    runtime["thermal_reason"]=reason
    return reason,ctl

def cooperative_gate(runtime,state_path,pool=None):
    while True:
        if runtime.get('_qualification_check'):runtime['_qualification_check']()
        block_stop=runtime.get('_block_stop_event')
        if block_stop is not None and block_stop.is_set():
            raise InterruptedError('Block work stopped')
        reason,ctl=_thermal_probe(runtime,state_path)
        if ctl.get("stop_requested"):
            if pool is not None:pool.set_percent(0)
            raise InterruptedError("Work stopped")
        if ctl.get("paused"):
            if pool is not None:pool.set_percent(0)
            publish_health(runtime,"paused");time.sleep(.1);continue
        if reason:
            if pool is not None:pool.set_percent(0)
            publish_health(runtime,"cooling");time.sleep(.25);continue
        return ctl

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
        ctl=cooperative_gate(runtime,state_path)
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

def constrained_process_limit(requested, available_bytes=None, total_bytes=None, existing_workers=0):
    """Conservative child-process ceiling; the CPU slider remains an upper bound."""
    if available_bytes is None or total_bytes is None:
        try:
            if os.name != 'nt':
                import psutil
                memory=psutil.virtual_memory()
                available_bytes,total_bytes=memory.available,memory.total
            else:
                class MemoryStatus(ctypes.Structure):
                    _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(name,ctypes.c_ulonglong) for name in ('total','available','page_total','page_available','virtual_total','virtual_available','extended')]
                memory=MemoryStatus();memory.length=ctypes.sizeof(memory)
                if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
                    return 0
                available_bytes,total_bytes=memory.available,memory.total
        except Exception:
            return 0
    reserve=max(2*1024**3,int(total_bytes*.25))
    budget=max(0,int(available_bytes)-reserve+max(0,int(existing_workers))*512*1024**2)
    # Frozen children import the solver/native runtime independently. Reserve
    # 512 MiB per child. Available memory, rather than an arbitrary eight-core
    # ceiling, determines how much of the requested CPU quota can be fed.
    return min(32,max(0,int(requested)),budget//(512*1024**2))


def release_constrained_pool(runtime):
    hybrid=runtime.pop('_constrained_hybrid',None)
    if hybrid is not None:hybrid.close()
    pool=runtime.pop('_constrained_pool',None)
    if pool is not None:pool.close()


def prepare_shared_constrained(runtime):
    """Create one process/GPU owner before any concurrent block job starts."""
    from search.process_map import ConcurrentProcessMaps
    from search.vulkan_bounded import SharedGpuSolver
    settings=runtime.get('settings',{})
    percent=max(0,min(100,int(settings.get('cpu_percent',0))))
    if not percent or not settings.get('allow_cpu',True):return False
    requested=min(32,max(1,math.ceil((os.cpu_count() or 1)*percent/100)))
    count=constrained_process_limit(requested)
    if not count:return False
    release_constrained_pool(runtime)
    runtime['_shared_constrained_pool']=ConcurrentProcessMaps(count)
    runtime.setdefault('_cpu_budget',CpuBudget())
    qualification=runtime.get('_bounded_gpu_qualification',{})
    if qualification.get('qualified') is True and qualification.get('cpu_workers')==count and callable(qualification.get('dispatch')):
        def percent():
            current=runtime.get('settings',{})
            return max(0,min(100,int(current.get('gpu_percent',0)))) if current.get('allow_gpu',False) else 0
        runtime['_shared_gpu_solver']=SharedGpuSolver(qualification['dispatch'],percent)
    return True


def release_shared_constrained(runtime):
    # The block pipeline joins its compute tasks before releasing these owners.
    gpu=runtime.pop('_shared_gpu_solver',None)
    if gpu is not None:gpu.close()
    pool=runtime.pop('_shared_constrained_pool',None)
    if pool is not None:pool.close()
    runtime.pop('_block_stop_event',None)


def bounded_cpu_reason(runtime, reason):
    runtime['bounded_gpu_reason']=reason
    runtime['bounded_backend']='CPU ('+reason+')'


def load_bounded_gpu(state_path,runtime):
    record=Path(state_path).with_name('bounded-gpu-qualification.json')
    if not record.exists():
        bounded_cpu_reason(runtime,'Vulkan qualification not available');return
    native=ROOT/'worker/native'
    library=native/'enigmagrid_solver.dll';shader=native/'bounded_solver.spv'
    adapter=ROOT/'solver/runtime/src/search/vulkan_bounded.py'
    try:
        if not all(path.is_file() for path in (library,shader,adapter)):
            bounded_cpu_reason(runtime,'Vulkan package unavailable');return
        from bounded_gpu_qualification import load_qualification,hardware_fingerprint
        sys.path.insert(0,str(ROOT/'solver/runtime/src'))
        qualification=load_qualification(record,library,shader,hardware_fingerprint(),adapter=adapter)
        if qualification is not None:
            runtime['_bounded_gpu_qualification']=qualification
            runtime.pop('bounded_gpu_reason',None)
        else:bounded_cpu_reason(runtime,'Vulkan qualification expired or insufficient')
    except Exception as error:
        bounded_cpu_reason(runtime,'Vulkan qualification unavailable: '+type(error).__name__)


def run_constrained_parallel(lease,runtime,state_path):
    from search.crib_work import run
    from search.process_map import OrderedProcessMap
    import math
    settings=runtime.get('settings',{})
    percent=max(0,min(100,int(settings.get('cpu_percent',0))))
    if not settings.get('allow_cpu',True) or not percent:
        raise InterruptedError('CPU disabled during constrained work')
    requested=min(32,max(1,math.ceil((os.cpu_count() or 1)*percent/100)))
    shared=runtime.get('_shared_constrained_pool')
    pool=shared or runtime.get('_constrained_pool')
    count=shared.workers if shared is not None else constrained_process_limit(requested,existing_workers=pool.workers if pool else 0)
    if not count:
        release_constrained_pool(runtime)
        runtime['resource']='CPU';runtime['cpu_threads']=1
        runtime['bounded_backend']='CPU (insufficient free memory for parallel solver)'
        serial=dict(runtime,_parallel_constrained=False)
        return run_constrained(lease,serial,state_path)
    pool=shared or runtime.get('_constrained_pool')
    if pool is not None and pool.workers!=count:
        release_constrained_pool(runtime);pool=None
    if pool is None:
        pool=OrderedProcessMap(count,chunk_size=8)
        runtime['_constrained_pool']=pool
    next_health=[0.0]
    def control():
        if runtime.get('_qualification_check'):runtime['_qualification_check']()
        block_stop=runtime.get('_block_stop_event')
        if block_stop is not None and block_stop.is_set():raise InterruptedError('Block work stopped')
        if runtime.get('enabled',True) is False:raise InterruptedError('Device disabled')
        current=runtime.get('settings',{})
        pct=max(0,min(100,int(current.get('cpu_percent',0))))
        if not current.get('allow_cpu',True) or not pct:
            pool.set_percent(0);raise InterruptedError('CPU disabled')
        ctl=cooperative_gate(runtime,state_path,pool) if state_path else {}
        # Preferences may change while the parent is waiting in pause.
        current=runtime.get('settings',{})
        pct=max(0,min(100,int(current.get('cpu_percent',0))))
        if not current.get('allow_cpu',True) or not pct:
            pool.set_percent(0);raise InterruptedError('CPU disabled during pause')
        with runtime.setdefault('_metrics_lock',threading.RLock()):
            observed=runtime.get('telemetry',{}).get('cpu_percent')
            delay=0
            if isinstance(observed,(int,float)) and math.isfinite(observed):
                budget=runtime.setdefault('_cpu_budget',CpuBudget())
                delay=budget.delay(time.monotonic(),pct,runtime.get('_telemetry_at'),observed)
                # One shared gate controls every child; no child applies another duty cycle.
                pool.set_percent(0 if delay>0 else 100)
                runtime['cpu_quota_provider']='measured_process_tree'
                runtime['cpu_average_10s']=budget.measured_percent()
            else:
                # Unsupported telemetry must remain explicit, not masquerade as zero CPU.
                runtime['cpu_quota_provider']='estimated_worker_duty'
                pool.set_percent(min(100,max(1,int((os.cpu_count() or 1)*pct/count))))
        if delay>0:time.sleep(min(.02,delay))
    def progress(done,total):
        control();runtime['progress']=done/max(1,total)
        now=time.monotonic()
        if done>=total or now>=next_health[0]:
            publish_health(runtime,'computing');next_health[0]=now+.5
    if shared is None:pool.check=control
    runtime['resource']='CPU';runtime['cpu_threads']=count
    control()
    solve_map=pool.view(control) if shared is not None else pool
    job_hybrid=None
    qualification=runtime.get('_bounded_gpu_qualification',{})
    runtime['bounded_backend']='CPU ('+runtime.get('bounded_gpu_reason','Vulkan qualification not available')+')'
    if qualification.get('qualified') is True:
        runtime['bounded_backend']='CPU (Vulkan qualification uses a different CPU pool size)'
    if qualification.get('qualified') is True and qualification.get('cpu_workers')==count:
        from search.crib_work import validate_envelope
        from search.vulkan_bounded import HybridSolverMap
        job=validate_envelope(lease)
        scope=(len(job['core_indices']),len(job['crib']),job['model'],job['pairs'],
               job['budgets']['node_limit'],job['budgets']['board_limit'],job['budgets']['completion_limit'])
        dispatch=qualification.get('dispatch')
        runtime['bounded_backend']='CPU (job outside qualified Vulkan scope)'
        shared_gpu=runtime.get('_shared_gpu_solver')
        if callable(dispatch) and scope==qualification.get('scope') and (shared is None or (shared_gpu is not None and shared_gpu.budget.dispatch is dispatch)):
            hybrid=None if shared is not None else runtime.get('_constrained_hybrid')
            if hybrid is not None and (hybrid.cpu is not pool or runtime.get('_hybrid_dispatch') is not dispatch or hybrid.gpu_cores!=qualification.get('gpu_cores',64)):
                hybrid.close();hybrid=None
            def gpu_percent():
                current=runtime.get('settings',{})
                return max(0,min(100,int(current.get('gpu_percent',0)))) if current.get('allow_gpu',False) else 0
            def failed(error):bounded_cpu_reason(runtime,'Vulkan failed: '+type(error).__name__)
            if hybrid is None:
                hybrid=HybridSolverMap(dispatch,solve_map,qualification.get('gpu_cores',64),
                    gpu_enabled=lambda:gpu_percent()>0,on_failure=failed,gpu_percent=gpu_percent,
                    gpu_service=runtime.get('_shared_gpu_solver') if shared is not None else None)
                if shared is not None:job_hybrid=hybrid
                else:runtime['_constrained_hybrid']=hybrid;runtime['_hybrid_dispatch']=dispatch
            hybrid.checkpoint=control
            runtime['bounded_backend']='CPU (GPU disabled in settings)' if gpu_percent()<=0 else ('CPU ('+runtime.get('bounded_gpu_reason','Vulkan backend failed')+')')
            solve_map=hybrid
            if gpu_percent()>0 and not hybrid.failed:
                runtime['bounded_backend']='CPU + Vulkan bounded solver'
                runtime['resource']='CPU + GPU'
    try:
        result=run(lease,checkpoint=progress,solve_map=solve_map)
        return result,len(result['receipt']['candidates'])
    finally:
        if job_hybrid is not None:job_hybrid.close()

def run_constrained(lease,runtime=None,state_path=None):
    from search.crib_work import run
    runtime=runtime if runtime is not None else {}
    if runtime.get('_parallel_constrained'):
        return run_constrained_parallel(lease,runtime,state_path)
    runtime['resource']='CPU'
    last=time.monotonic()
    next_health=last
    def checkpoint(done,total):
        nonlocal last,next_health
        settings=runtime.get('settings',{'allow_cpu':True,'cpu_percent':50})
        if not settings.get('allow_cpu',True) or settings.get('cpu_percent',0)<=0:
            raise InterruptedError('CPU disabled during constrained work')
        if state_path:
            ctl=cooperative_gate(runtime,state_path)
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
        if state_path and (done>=total or last>=next_health):
            publish_health(runtime,'computing');next_health=last+0.5
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
    runtime={"settings":normalize_settings(state.get("settings",{})),"enabled":True,
             "_parallel_constrained":True,"_batch_requests":True,"_async_upload":True}
    try:
        return _work(args,state,runtime)
    finally:
        suspend_long_blocks(runtime)
        summary_publisher=runtime.pop('_summary_publisher',None)
        if summary_publisher is not None:summary_publisher.close()
        release_unused_work(state,runtime)
        allocation_pool=runtime.pop('_allocation_pool',None)
        if allocation_pool is not None:allocation_pool.shutdown(wait=True)
        uploader=runtime.pop('_uploader',None)
        if uploader is not None:uploader.close()
        release_constrained_pool(runtime)


def suspend_long_blocks(runtime):
    pipeline=runtime.pop('_block_pipeline',None)
    if pipeline is None:return
    # Finish in-flight HTTP operations before marking the resulting descriptors.
    pipeline.close()
    release_shared_constrained(runtime)
    runtime['running_jobs']=0
    runtime.pop('_block_concurrency_considered',None)
    runtime['_qualified_block_lanes']=1
    pipeline.queue.retire()
    try:
        while pipeline.queue.pending():
            if not pipeline.transport.upload():break
        pipeline.transport.release_ready()
    except Exception as error:
        # Retirement and all unsent receipts remain durable for next startup.
        runtime['block_release_error']=type(error).__name__


def maybe_qualify_block_concurrency(state_path,state,runtime,pipeline):
    from concurrency_qualification import qualify,select_lanes
    if pipeline.running or runtime.get('_block_concurrency_considered') or time.monotonic()<runtime.get('_block_qualification_retry_at',0):return False
    envelopes=pipeline.queue.qualification_sample()
    if not envelopes:return False
    settings=dict(runtime['settings'])
    sources=['worker/worker.py','worker/concurrency_qualification.py','worker/cpu_budget.py',
             'solver/runtime/src/search/process_map.py','solver/runtime/src/search/vulkan_bounded.py',
             'solver/runtime/src/search/crib_work.py','solver/runtime/src/search/bounded_crib.py',
             'solver/runtime/src/search/c3_models.py','solver/runtime/src/search/work_block.py']
    assets=runtime.get('_concurrency_asset_hashes')
    if assets is None:
        # Frozen modules live in the executable archive, not as worker/*.py.
        # Hash that complete archive without loading it all into RAM.
        paths=[Path(sys.executable)] if FROZEN else [ROOT/name for name in sources]
        assets=[]
        for path in paths:
            digest=hashlib.sha256()
            with path.open('rb') as source:
                for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
            assets.append(digest.hexdigest())
        runtime['_concurrency_asset_hashes']=assets
    gpu_record=Path(state_path).with_name('bounded-gpu-qualification.json')
    expected_workers=constrained_process_limit(min(32,max(1,math.ceil((os.cpu_count() or 1)*int(settings['cpu_percent'])/100))))
    if not expected_workers:return False
    identity=dict(assets=assets,settings=settings,config=envelopes[0]['config'],
                  hardware=[platform.platform(),platform.processor(),os.cpu_count()],
                  workers=expected_workers,
                  gpu=hashlib.sha256(gpu_record.read_bytes()).hexdigest() if gpu_record.is_file() else None)
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    path=Path(state_path).with_name('block-concurrency-qualification.json')
    try:record=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):record={}
    if record.get('identity')==key:
        try:
            report=record['report'];lanes=select_lanes(report['trials'])
            if report.get('format')!='local-concurrency-v1' or report.get('jobs_per_trial')!=12 or report.get('parity_checks')!=120 or report.get('lanes')!=lanes:
                raise ValueError('Incomplete cached qualification')
        except (ValueError,KeyError,TypeError):pass
        else:
            runtime['_qualified_block_lanes']=lanes
            runtime['_qualified_block_config']=envelopes[0]['config']
            runtime['_block_concurrency_considered']=True
            return lanes!=pipeline.lanes
    if not prepare_shared_constrained(runtime):return False
    if runtime['_shared_constrained_pool'].workers!=expected_workers:
        release_shared_constrained(runtime);return False
    deadline=time.monotonic()+120;cancel=threading.Event()
    prior_stop=runtime.get('_block_stop_event')
    runtime['_block_stop_event']=cancel
    def check():
        if time.monotonic()>=deadline or cancel.is_set():raise InterruptedError('Concurrency qualification stopped')
        if runtime.get('settings')!=settings or not runtime.get('enabled',True):raise InterruptedError('Qualification settings changed')
        reason,control=_thermal_probe(runtime,state_path)
        if reason or control.get('paused') or control.get('stop_requested'):raise InterruptedError(reason or 'Qualification paused/stopped')
    runtime['_qualification_check']=check
    heartbeat_stop=threading.Event()
    heartbeat=threading.Thread(target=heartbeat_loop,args=(heartbeat_stop,state,runtime),daemon=True)
    heartbeat.start()
    try:
        from search.crib_work import run
        pool=runtime['_shared_constrained_pool']
        def reference(envelope):
            # Reuse the same controlled CPU executor without the GPU adapter.
            def cpu_only(fn,tasks):
                def gate():
                    check()
                    pct=int(settings['cpu_percent'])
                    pool.set_percent(min(100,max(1,int((os.cpu_count() or 1)*pct/pool.workers))))
                return pool.view(gate)(fn,tasks)
            return run(envelope,checkpoint=lambda *_:check(),solve_map=cpu_only)
        publish_health(runtime,'qualifying_concurrency')
        report=qualify(envelopes,reference,lambda envelope:run_constrained_parallel(envelope,runtime,state_path)[0],
                       checkpoint=check,cancel_running=cancel.set)
        check()
        save_plain_json(path,dict(identity=key,report=report))
        runtime['_qualified_block_lanes']=report['lanes']
        runtime['_qualified_block_config']=envelopes[0]['config']
        runtime['_block_concurrency_considered']=True
        return report['lanes']!=pipeline.lanes
    except InterruptedError:
        runtime['_block_qualification_retry_at']=time.monotonic()+60
        if time.monotonic()>=deadline:
            runtime['_block_concurrency_considered']=True
            runtime['concurrency_reason']='Qualification exceeded time limit; using one job'
        raise
    except (ValueError,OSError) as error:
        runtime['_qualified_block_lanes']=1
        runtime['_block_concurrency_considered']=True
        runtime['concurrency_reason']='Qualification unavailable: '+type(error).__name__
        return False
    finally:
        cancel.set();heartbeat_stop.set();heartbeat.join(timeout=2)
        runtime.pop('_qualification_check',None)
        release_shared_constrained(runtime)
        if prior_stop is not None:runtime['_block_stop_event']=prior_stop


def long_block_tick(state_path,state,runtime):
    """Run one local unit, with allocation and upload on separate executors."""
    sys.path.insert(0,str(ROOT/'solver/runtime/src'))
    from search.work_block import FORMAT
    from block_queue import BlockQueue
    from block_transport import BlockTransport
    from block_pipeline import BlockPipeline
    if runtime.get('_lease_queue') or runtime.get('_batch_pending'):return False
    pipeline=runtime.get('_block_pipeline')
    if pipeline is None:
        capabilities=runtime.get('_block_capabilities')
        if capabilities is None or time.monotonic()>=runtime.get('_block_capabilities_at',0):
            # A running legacy client must discover a server rollout without a
            # restart. Probe only between lease queues, never per local unit.
            runtime['_block_capabilities_at']=time.monotonic()+60
            try:capabilities=get_json(state['server'],'/api/capabilities',5)
            except (OSError,TimeoutError):return False
            if not isinstance(capabilities,dict):return False
            runtime['_block_capabilities']=capabilities
        if capabilities.get('long_work_blocks')!=FORMAT:return False
        from search.work_result_groups import FORMAT as GROUP_FORMAT
        grouped=capabilities.get('work_result_groups')==GROUP_FORMAT
        queue=BlockQueue(Path(state_path).with_name('work-block-queue.dat'),
                         dict(server=state['server'],device_id=state['device_id']),load_state,save_state,grouped=grouped)
        transport=BlockTransport(queue,lambda path,payload:post(state['server'],path,payload,state['device_token'],timeout=30),grouped=grouped)
        def compute(envelope):
            qualified_config=runtime.get('_qualified_block_config')
            if qualified_config is not None and qualified_config!=envelope['config']:
                runtime.pop('_block_concurrency_considered',None)
                if runtime.get('_shared_constrained_pool') is not None:
                    raise InterruptedError('Workload changed; requalify concurrency')
            publish_health(runtime,'computing')
            began=time.monotonic()
            result,_=execute(envelope,runtime,state_path)
            record_throughput(runtime,envelope['end_unit']-envelope['start_unit'],max(.000001,time.monotonic()-began))
            return result
        transport.refresh_status()
        lanes=runtime.get('_qualified_block_lanes',1)
        if lanes not in (1,2,4):lanes=1
        runtime['cpu_threads']=apply_cpu_limit(100)
        if lanes>1 and not prepare_shared_constrained(runtime):lanes=1
        try:pipeline=BlockPipeline(queue,transport,compute,lanes=lanes)
        except BaseException:
            release_shared_constrained(runtime)
            raise
        runtime['_block_stop_event']=pipeline.stop_event
        runtime['_block_settings']=tuple(runtime['settings'].get(k) for k in ('allow_cpu','cpu_percent','allow_gpu','gpu_percent'))
        runtime['_block_pipeline']=pipeline
    # Network control runs independently; apply settings on the compute thread
    # before deciding whether another local unit may start.
    def refresh_control():
        return post(state['server'],'/api/heartbeat',{'meta':meta(runtime)},state['device_token'],timeout=30)
    response=pipeline.poll_control(refresh_control)
    if response is not None:apply_coordinator_state(response,runtime)
    if not runtime.get('enabled',False):
        suspend_long_blocks(runtime)
        control=read_control(state_path);control['stop_requested']=True;write_control(state_path,control)
        publish_health(runtime,'disabled')
        return True
    settings_key=tuple(runtime['settings'].get(k) for k in ('allow_cpu','cpu_percent','allow_gpu','gpu_percent'))
    if settings_key!=runtime.get('_block_settings',settings_key):
        # Join the old quota's jobs before sizing the next pool. Completed
        # receipts stay durable; untouched reservations are returned normally.
        suspend_long_blocks(runtime)
        runtime.pop('_block_concurrency_considered',None)
        runtime['_qualified_block_lanes']=1
        return True
    pipeline.poll_status()
    st=runtime['settings'];control=read_control(state_path)
    allowed=runtime.get('enabled',False) and st.get('allow_cpu',False) and st.get('cpu_percent',0)>0
    allowed=allowed and not control.get('paused') and not control.get('stop_requested')
    if allowed and maybe_qualify_block_concurrency(state_path,state,runtime,pipeline):
        # Preserve the received blocks and outbox while replacing only executors.
        pipeline.close();runtime.pop('_block_pipeline',None)
        release_shared_constrained(runtime)
        return True
    worked=pipeline.tick(allow_compute=allowed)
    runtime['running_jobs']=sum(not task.done() for task in pipeline.running)
    runtime.update(pipeline.queue.monitor_snapshot())
    runtime['wait_reason']='' if worked or pipeline.computing else (pipeline.wait_reason or '')
    if not worked and not runtime['ready_units'] and not runtime['outbox_count'] and pipeline.wait_reason in ('block_calibration_required','legacy_priority_work','legacy_validation_work'):return False
    if not worked:
        if pipeline.computing:
            publish_health(runtime,'computing');time.sleep(.01);return True
        if pipeline.terminal_error:runtime['wait_reason']='Receipt rejected: '+pipeline.terminal_error
        publish_health(runtime,'coordinator_rejected' if pipeline.terminal_error else ('uploading' if runtime['outbox_count']>=pipeline.queue.max_pending else 'waiting'))
        time.sleep(.05)
    return True


def _work(args,state,runtime):
    if not acquire_worker_mutex():
        print("Worker already running for this Windows user.",flush=True);return 0
    state_path=Path(args.state);health_path=state_path.with_name("worker-health.json")
    load_bounded_gpu(state_path,runtime)
    updater=UpdateManager(VERSION,state_path,state["server"]) if UpdateManager else None
    if updater:updater.start()
    started=time.time()
    runtime.update(health_path=health_path,started=started)
    publish_health(runtime,"starting")
    if not args.once and state_path.is_file():
        publisher=SummaryPublisher(state_path,VERSION,client_summary)
        runtime['_summary_publisher']=publisher;publisher.start()
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
                suspend_long_blocks(runtime)
                release_unused_work(state,runtime)
                release_constrained_pool(runtime)
                publish_health(runtime,"paused")
                time.sleep(args.idle_seconds);continue
            thermal_reason,_thermal_ctl=_thermal_probe(runtime,state_path)
            if thermal_reason:
                suspend_long_blocks(runtime)
                release_constrained_pool(runtime);publish_health(runtime,"cooling")
                try:heartbeat_once(state,runtime)
                except Exception:pass
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
            uploader=runtime.get('_uploader')
            if uploader is not None:
                if uploader.terminal:
                    publish_health(runtime,'coordinator_rejected');time.sleep(1);continue
                waiting=uploader.queue.pending()
                runtime['outbox_count']=len(waiting)
                # Only storage backpressure stops computation. Pending uploads
                # do not require draining the whole outbox before new allocation.
                if not uploader.queue.has_capacity():
                    runtime['wait_reason']='result_storage_full'
                    publish_health(runtime,'uploading');uploader.notify();time.sleep(.1);continue
                if runtime.get('wait_reason')=='result_storage_full':runtime['wait_reason']=''
            recovered=None if uploader is not None else deliver_pending(state_path,state)
            if recovered is not None:
                print(json.dumps({"recovered_completion":True,"ack":recovered}),flush=True)
                if args.once:return 0
            if not args.once and runtime.get('_async_upload') and uploader is None:
                transport=CompletionTransport(lambda path:get_json(state['server'],path,30),
                    lambda path,payload:post(state['server'],path,payload,state['device_token'],timeout=30))
                uploader=OutboxUploader(result_outbox(state_path,state),None,send_batch=transport.send)
                runtime['_uploader']=uploader
            if not args.once:
                check_bounded_gpu_qualification(state_path,state,runtime)
            if not args.once and long_block_tick(state_path,state,runtime):continue
            got,hb=request_work(state,runtime)
            if hb.get("update_required") and updater:updater.force_check()
            if not runtime["enabled"]:
                publish_health(runtime,"disabled")
                c=read_control(state_path);c["stop_requested"]=True;write_control(state_path,c)
                print("Worker disabled or quarantined by coordinator.");return 0
            st=runtime["settings"]
            # Constrained child processes enforce aggregate CPU duty themselves.
            # Do not make them inherit a smaller rounded affinity mask, which
            # could strand their persistent pool on a subset after slider changes.
            constrained=(got.get("lease") or {}).get("engine")=="bounded_crib_v1"
            runtime["cpu_threads"]=apply_cpu_limit(100 if constrained else st["cpu_percent"])
            if got.get("update_required") and updater:updater.force_check()
            lease=got.get("lease")
            if lease and lease.get('engine')!='bounded_crib_v1':release_constrained_pool(runtime)
            if not lease:
                # A temporary empty response must not tear down the warm solver
                # and Vulkan context. Pause/stop, memory pressure and engine
                # changes still release or reconfigure it in their own paths.
                publish_health(runtime,"waiting")
                if args.once:return 0
                retry=got.get('retry_after_seconds',0)
                if not isinstance(retry,(int,float)) or not math.isfinite(retry):retry=0
                deadline=time.monotonic()+max(args.idle_seconds,min(60,max(0,retry)))
                while time.monotonic()<deadline:
                    ctl=read_control(state_path)
                    if ctl.get('paused') or ctl.get('stop_requested'):break
                    time.sleep(min(.1,max(0,deadline-time.monotonic())))
                continue
            resource=lease.get("resource_class","cpu");pct=int(lease.get("resource_percent",100))
            if resource=="cpu" and (not st["allow_cpu"] or st["cpu_percent"]<=0):
                time.sleep(args.idle_seconds);continue
            if resource=="gpu" and (not st["allow_gpu"] or st["gpu_percent"]<=0):
                time.sleep(args.idle_seconds);continue
            print(f"Lease {lease['id']} {lease['purpose']} {resource}@{pct}% {lease['segment_label']} {lease['start_unit']}:{lease['end_unit']}",flush=True)
            if uploader is not None and not uploader.queue.reserve(lease['id']):
                publish_health(runtime,'uploading');uploader.notify();time.sleep(.1);continue
            stop=threading.Event();th=threading.Thread(target=heartbeat_loop,args=(stop,state,runtime),daemon=True);th.start()
            runtime["running_jobs"]=1
            publish_health(runtime,"computing")
            t=time.time()
            try:
                if not args.once:start_batch_prefetch(state,runtime)
                result,candidates=execute(lease,runtime,state_path)
                runtime["running_jobs"]=0
                secs=max(0.000001,time.time()-t)
                units=max(1,int(lease.get("end_unit",1))-int(lease.get("start_unit",0)))
                payload={"lease_id":lease["id"],"work_token":lease["work_token"],"compute_seconds":secs,
                         "candidate_count":candidates,"result":result,"meta":meta(runtime)}
                if uploader is not None:uploader.queue.append(payload)
                else:persist_completion(state_path,state,payload)
                record_throughput(runtime,units,secs)
                publish_health(runtime,"uploading")
                if uploader is not None:uploader.notify();ack={'saved_locally':True}
                else:ack=deliver_pending(state_path,state)
            finally:
                runtime["running_jobs"]=0
                stop.set();th.join(timeout=2)
                if uploader is not None:uploader.queue.release_reservation(lease['id'])
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
        except InterruptedError:
            suspend_long_blocks(runtime)
            release_constrained_pool(runtime)
            publish_health(runtime,'waiting')
            if args.once:return 2
            time.sleep(.1)
        except Exception as e:
            suspend_long_blocks(runtime)
            release_constrained_pool(runtime)
            publish_health(runtime,"connection_error")
            print(json.dumps({"worker_error":repr(e)}),flush=True)
            if args.once:return 2
            time.sleep(10)

def constrained_self_test():
    """Offline packaged-worker probe; no enrollment or production state access."""
    sys.path.insert(0,str(ROOT/'solver/runtime/src'))
    from search.crib_work import run
    job=dict(engine='bounded_crib_v1',ciphertext='A'*72,crib='B'*24,offset=0,
             core_indices=list(range(32)),model='clean',pairs=10,
             budgets=dict(node_limit=10,board_limit=1,completion_limit=1,candidate_limit=1))
    lease=dict(engine='bounded_crib_v1',start_unit=0,end_unit=1,
               config=dict(job=job,requires=['cpu','bounded_crib_v1']))
    runtime={'settings':{'cpu_percent':min(100,max(1,200//(os.cpu_count() or 1))),
                         'allow_cpu':True},'_parallel_constrained':True}
    try:
        expected=run(lease)
        for _ in range(2):
            result,_=run_constrained(lease,runtime,None)
            if result!=expected:raise RuntimeError('Constrained receipt mismatch')
        release_constrained_pool(runtime)
        from search.process_map import ConcurrentProcessMaps
        from concurrency_qualification import qualify
        runtime['_shared_constrained_pool']=ConcurrentProcessMaps(2)
        report=qualify([lease]*12,lambda _:expected,lambda envelope:run_constrained(envelope,runtime,None)[0])
        print(json.dumps({'ok':True,'test':'constrained_process_reuse_and_shared_qualification',
                          'version':VERSION,'parity_checks':report['parity_checks']}))
    finally:
        release_shared_constrained(runtime)
        uploader=runtime.pop('_uploader',None)
        if uploader is not None:uploader.close()
        pool=runtime.pop('_constrained_pool',None)
        if pool is not None:pool.close()

def check_bounded_gpu_qualification(state_path,state,runtime):
    """Retry deferred prerequisites at idle boundaries, never a failed comparison."""
    now=time.monotonic()
    if runtime.get('_gpu_qualification_considered') or now<runtime.get('_gpu_qualification_retry_at',0):return
    runtime['_gpu_qualification_retry_at']=now+60
    if maybe_qualify_bounded_gpu(state_path,state,runtime):
        runtime['_gpu_qualification_considered']=True


def maybe_qualify_bounded_gpu(state_path,state,runtime):
    """Return true once qualification is settled; false for transient prerequisites."""
    native=ROOT/'worker/native';adapter=ROOT/'solver/runtime/src/search/vulkan_bounded.py'
    assets=[native/'enigmagrid_solver.dll',native/'bounded_solver.spv',adapter]
    if not all(path.is_file() for path in assets):
        bounded_cpu_reason(runtime,'Vulkan package unavailable');return True
    try:
        heartbeat_once(state,runtime)
        settings=runtime.get('settings',{})
        if not runtime.get('enabled',True) or not settings.get('allow_cpu') or not settings.get('allow_gpu') or settings.get('cpu_percent')!=100 or settings.get('gpu_percent')!=100:
            bounded_cpu_reason(runtime,'Vulkan tuning needs CPU and GPU enabled at 100%');return False
        workers=constrained_process_limit(min(32,os.cpu_count() or 1))
        if not workers:
            bounded_cpu_reason(runtime,'Vulkan tuning deferred: insufficient free memory');return False
        if runtime.get('_bounded_gpu_qualification',{}).get('cpu_workers')==workers:return True
        from bounded_gpu_qualification import hardware_fingerprint,sha256,FORMAT
        identity={'protocol':FORMAT,'hardware':hardware_fingerprint(),'assets':[sha256(path) for path in assets],'workers':workers}
        attempt=Path(state_path).with_name('bounded-gpu-attempt.json')
        try:previous=json.loads(attempt.read_text(encoding='utf-8'))
        except (OSError,ValueError):previous={}
        if previous.get('identity')==identity:
            bounded_cpu_reason(runtime,'Vulkan comparison did not qualify');return True
        publish_health(runtime,'qualifying_gpu')
        stop=threading.Event()
        heartbeat=threading.Thread(target=heartbeat_loop,args=(stop,state,runtime),daemon=True)
        heartbeat.start()
        try:result=qualify_bounded_gpu_client(state_path,workers,owned_runtime=runtime)
        finally:stop.set();heartbeat.join(timeout=2)
        save_plain_json(attempt,{'identity':identity,'result':result})
        load_bounded_gpu(state_path,runtime)
        if not result['qualified']:bounded_cpu_reason(runtime,'Vulkan comparison did not qualify')
        return True
    except InterruptedError:
        bounded_cpu_reason(runtime,'Vulkan qualification interrupted')
        return False
    except Exception as error:
        bounded_cpu_reason(runtime,'Vulkan qualification unavailable: '+type(error).__name__)
        return True


def qualify_bounded_gpu_client(state_path,workers,*,owned_runtime=None):
    """Offline qualification under the normal worker mutex; never edits identity."""
    import tempfile
    from bounded_gpu_qualification import qualify,save_qualification,load_qualification,hardware_fingerprint
    state_path=Path(state_path)
    if owned_runtime is None and not acquire_worker_mutex():raise RuntimeError('Stop the worker safely before GPU qualification')
    runtime=owned_runtime if owned_runtime is not None else {}
    deadline=time.monotonic()+120
    last_probe=[float('-inf')];local_settings=[{}]
    def checkpoint():
        now=time.monotonic()
        if now>deadline:raise InterruptedError('GPU qualification time limit')
        # Poll disk/sensors at one-second intervals, not once per solver node.
        # Coordinator controls already refreshed by heartbeat remain authoritative.
        if now-last_probe[0]>=1:
            last_probe[0]=now
            reason,control=_thermal_probe(runtime,state_path)
            if reason or control.get('paused') or control.get('stop_requested'):
                raise InterruptedError(reason or 'GPU qualification paused/stopped')
            if owned_runtime is None:
                local_settings[0]=normalize_settings((load_state(state_path) or {}).get('settings',{}))
            else:publish_health(runtime,'qualifying_gpu')
        if owned_runtime is not None:
            uploader=runtime.get('_uploader')
            if not runtime.get('enabled',True) or (uploader is not None and uploader.terminal):
                raise InterruptedError('Coordinator rejected contribution')
        settings=runtime.get('settings',{}) if owned_runtime is not None else local_settings[0]
        if not settings.get('allow_cpu') or not settings.get('allow_gpu') or settings.get('cpu_percent')!=100 or settings.get('gpu_percent')!=100:
            raise InterruptedError('Full-duty qualification requires existing CPU/GPU settings at 100 percent')
    checkpoint()
    native=ROOT/'worker/native';library=native/'enigmagrid_solver.dll';shader=native/'bounded_solver.spv'
    adapter=ROOT/'solver/runtime/src/search/vulkan_bounded.py'
    sys.path.insert(0,str(ROOT/'solver/runtime/src'))
    report=qualify(library,shader,adapter,workers,checkpoint=checkpoint)
    checkpoint()
    save_qualification(state_path.with_name('bounded-gpu-comparison.json'),report)
    # A failed comparison must not overwrite an earlier valid qualification.
    with tempfile.TemporaryDirectory(prefix='gpu-qualification-') as temporary:
        candidate=Path(temporary)/'candidate.json'
        save_qualification(candidate,report)
        accepted=load_qualification(candidate,library,shader,hardware_fingerprint(),adapter=adapter,factory=lambda *args:None)
    if accepted is None:return {'qualified':False,'reason':'No repeatable throughput advantage'}
    checkpoint()
    save_qualification(state_path.with_name('bounded-gpu-qualification.json'),report)
    return {'qualified':True,'cpu_workers':workers,'gpu_cores':report['gpu_cores']}


def main():
    ap=argparse.ArgumentParser(description="Volunteer Enigma Grid worker v0.3")
    ap.add_argument("--server",default=os.environ.get("ENIGMA_GRID_SERVER",""));ap.add_argument("--registration-code",default="")
    ap.add_argument("--name",default="");ap.add_argument("--device-label",default="");ap.add_argument("--contributor-key",default="")
    ap.add_argument("--private-credit",action="store_true");ap.add_argument("--state",default=str(Path.home()/".enigma-volunteer"/"client.json"))
    ap.add_argument("--show-secrets",action="store_true")
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--self-test-constrained",action="store_true")
    ap.add_argument("--qualify-bounded-gpu",action="store_true")
    ap.add_argument("--qualification-workers",type=int,choices=range(1,9),default=2)
    ap.add_argument("--client-summary-json",action="store_true")
    ap.add_argument("--dashboard-token",action="store_true",help="Print the private dashboard token locally")
    ap.add_argument("--once",action="store_true");ap.add_argument("--disable",action="store_true")
    ap.add_argument("--register-only",action="store_true")
    ap.add_argument("--set-preferences",action="store_true");ap.add_argument("--cpu-percent",type=int,default=50)
    ap.add_argument("--gpu-percent",type=int,default=0);ap.add_argument("--idle-seconds",type=int,default=5)
    args=ap.parse_args()
    if args.qualify_bounded_gpu:
        print(json.dumps(qualify_bounded_gpu_client(args.state,args.qualification_workers)));return
    if args.self_test_constrained:
        constrained_self_test();return
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

if __name__=="__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
