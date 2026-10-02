import hashlib
import json
import os
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from pathlib import Path
from urllib.parse import urlparse

from validator import validate_result

ROOT=Path(__file__).resolve().parents[1]
CFG=Path(os.environ.get("GRID_CONFIG",str(ROOT/"config"/"server.json")))
DATA=Path(os.environ.get("GRID_DATA_DIR",str(ROOT/"state")))
DB=Path(os.environ.get("GRID_DB",str(DATA/"grid.sqlite3")))
WEB=ROOT/"web"/"index.html"
RATE=defaultdict(deque)
RATE_SALT=secrets.token_bytes(32)
LAST_PRUNE=0.0

def load_cfg():
    cfg=json.loads(CFG.read_text(encoding="utf-8"))
    if os.environ.get("GRID_HOST"): cfg["host"]=os.environ["GRID_HOST"]
    if os.environ.get("GRID_PORT"): cfg["port"]=int(os.environ["GRID_PORT"])
    if os.environ.get("GRID_REGISTRATION_CODE") is not None:
        cfg["registration_code"]=os.environ["GRID_REGISTRATION_CODE"]
    if os.environ.get("GRID_REGISTRATION_OPEN") is not None:
        cfg["registration_open"]=os.environ["GRID_REGISTRATION_OPEN"].lower() in {"1","true","yes","on"}
    if os.environ.get("GRID_TRUST_PROXY") is not None:
        cfg["trust_proxy"]=os.environ["GRID_TRUST_PROXY"].lower() in {"1","true","yes","on"}
    return cfg

def db():
    DATA.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(DB,timeout=30,isolation_level=None)
    con.row_factory=sqlite3.Row
    con.execute("pragma journal_mode=WAL")
    con.execute("pragma foreign_keys=ON")
    return con

def now(): return time.time()
def sha(value):
    import hashlib
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def rid(prefix): return prefix+"_"+secrets.token_urlsafe(12)

def ensure_column(con,table,name,decl):
    cols={r["name"] for r in con.execute(f"pragma table_info({table})")}
    if name not in cols: con.execute(f"alter table {table} add column {name} {decl}")

def init_db():
    con=db()
    con.executescript("""
    create table if not exists contributors(
      id text primary key, display_name text not null, public_credit integer not null default 1,
      join_key_hash text not null unique, dashboard_token_hash text not null unique, created real not null);
    create table if not exists devices(
      id text primary key, contributor_id text not null references contributors(id),
      label text not null, token_hash text not null unique, enabled integer not null default 1,
      last_seen real, meta_json text not null default '{}', created real not null);
    create table if not exists campaigns(
      id text primary key, name text not null, version text not null, status text not null,
      created real not null, notes text not null default '');
    """)
    con.executescript("""
    create table if not exists segments(
      id text primary key, campaign_id text not null references campaigns(id),
      label text not null, engine text not null, start_unit integer not null,
      end_unit integer not null, next_unit integer not null, chunk_size integer not null,
      priority integer not null default 100, config_json text not null default '{}');
    create table if not exists leases(
      id text primary key, segment_id text not null references segments(id),
      device_id text not null references devices(id), start_unit integer not null,
      end_unit integer not null, work_token text not null, status text not null,
      leased_at real not null, expires_at real not null, completed_at real);
    create index if not exists ix_leases_device on leases(device_id,status);
    create table if not exists requeue(
      segment_id text not null, start_unit integer not null, end_unit integer not null,
      queued_at real not null, primary key(segment_id,start_unit,end_unit));
    create table if not exists done_ranges(
      segment_id text not null, start_unit integer not null, end_unit integer not null,
      lease_id text not null, device_id text not null, completed_at real not null,
      result_json text not null, primary key(segment_id,start_unit,end_unit));
    """)
    con.executescript("""
    create table if not exists contributions(
      contributor_id text not null, device_id text not null,
      units integer not null default 0, jobs integer not null default 0,
      compute_seconds real not null default 0, candidates integer not null default 0,
      primary key(contributor_id,device_id));
    create table if not exists validations(
      segment_id text not null, start_unit integer not null, end_unit integer not null,
      base_required integer not null, target_replicas integer not null, max_replicas integer not null,
      status text not null default 'pending', canonical_fingerprint text,
      created real not null, verified_at real,
      primary key(segment_id,start_unit,end_unit));
    create table if not exists submissions(
      id text primary key, lease_id text not null unique, segment_id text not null,
      start_unit integer not null, end_unit integer not null, device_id text not null,
      contributor_id text not null, fingerprint text not null, result_json text not null,
      compute_seconds real not null, candidate_count integer not null,
      status text not null default 'pending', credited integer not null default 0,
      submitted_at real not null);
    """)
    con.executescript("""
    create index if not exists ix_sub_range on submissions(segment_id,start_unit,end_unit,status);
    create table if not exists audit_log(
      id integer primary key autoincrement, created real not null, kind text not null,
      device_id text, detail_json text not null default '{}');
    create table if not exists registration_nonces(
      nonce text primary key, expires real not null, used integer not null default 0);
    """)
    ensure_column(con,"devices","settings_json","text not null default '{}'")
    ensure_column(con,"devices","capabilities_json","text not null default '[]'")
    ensure_column(con,"devices","trust_score","real not null default 1.0")
    ensure_column(con,"devices","quarantined","integer not null default 0")
    ensure_column(con,"devices","valid_jobs","integer not null default 0")
    ensure_column(con,"devices","invalid_jobs","integer not null default 0")
    ensure_column(con,"leases","purpose","text not null default 'primary'")
    con.close()

def audit(con,kind,device_id=None,**detail):
    con.execute("insert into audit_log(created,kind,device_id,detail_json) values(?,?,?,?)",
                (now(),kind,device_id,json.dumps(detail,separators=(",",":"))))

def new_registration_challenge(con):
    t=now();con.execute("delete from registration_nonces where expires<?",(t-60,))
    nonce=secrets.token_urlsafe(18);expires=t+300
    con.execute("insert into registration_nonces(nonce,expires,used) values(?,?,0)",(nonce,expires))
    bits=max(12,min(24,int(load_cfg().get("registration_pow_bits",18))))
    return {"nonce":nonce,"difficulty_bits":bits,"expires_at":expires}

def verify_registration_pow(con,b):
    nonce=str(b.get("pow_nonce",""));counter=str(b.get("pow_counter",""))
    row=con.execute("select expires,used from registration_nonces where nonce=?",(nonce,)).fetchone()
    if not row or row["used"] or row["expires"]<now():return False
    bits=max(12,min(24,int(load_cfg().get("registration_pow_bits",18))))
    digest=hashlib.sha256((nonce+":"+counter).encode("utf-8")).digest()
    if (int.from_bytes(digest,"big")>>(256-bits))!=0:return False
    cur=con.execute("update registration_nonces set used=1 where nonce=? and used=0",(nonce,))
    return cur.rowcount==1
def normalize_settings(v):
    v=v if isinstance(v,dict) else {}
    cpu=max(0,min(100,int(v.get("cpu_percent",50))))
    gpu=max(0,min(100,int(v.get("gpu_percent",0))))
    return {"cpu_percent":cpu,"gpu_percent":gpu,
            "allow_cpu":bool(v.get("allow_cpu",cpu>0)),
            "allow_gpu":bool(v.get("allow_gpu",gpu>0))}

def sanitize_meta(meta):
    meta=meta if isinstance(meta,dict) else {}
    gpus=[]
    for g in (meta.get("gpus") or [])[:4]:
        if not isinstance(g,dict): continue
        gpus.append({"vendor":str(g.get("vendor",""))[:32],
                     "name":str(g.get("name",""))[:96],
                     "memory_mb":max(0,int(g.get("memory_mb",0) or 0))})
    out={"worker_version":str(meta.get("worker_version",""))[:32],
         "platform":str(meta.get("platform",""))[:128],
         "machine":str(meta.get("machine",""))[:32],
         "cpu_count":max(1,min(1024,int(meta.get("cpu_count",1) or 1))),
         "gpus":gpus,
         "capabilities":[x for x in (meta.get("capabilities") or []) if x in {"cpu","cuda","rocm","gpu"}]}
    if isinstance(meta.get("effective_settings"),dict):
        out["effective_settings"]=normalize_settings(meta["effective_settings"])
    if "cpu_threads_effective" in meta:
        out["cpu_threads_effective"]=max(0,min(1024,int(meta.get("cpu_threads_effective",0) or 0)))
    return out

def capabilities_from_meta(meta):
    meta=sanitize_meta(meta)
    caps={"cpu"}
    for x in meta.get("capabilities",[]) or []:
        if x in {"cpu","cuda","rocm","gpu"}: caps.add(x)
    if meta.get("gpus"):
        caps.add("gpu")
        if any(str(g.get("vendor","")).lower()=="nvidia" for g in meta["gpus"] if isinstance(g,dict)):
            caps.add("cuda")
    return sorted(caps)

def device_from_token(con,token):
    if not token:return None
    return con.execute("""select d.*,c.display_name,c.public_credit from devices d
                          join contributors c on c.id=d.contributor_id
                          where d.token_hash=?""",(sha(token),)).fetchone()

def parse_json(v,default):
    try:return json.loads(v) if v else default
    except Exception:return default

def version_tuple(value):
    parts=[]
    for raw in str(value or "").strip().split("."):
        digits=""
        for ch in raw:
            if ch.isdigit():digits+=ch
            else:break
        parts.append(int(digits or 0))
    while len(parts)<3:parts.append(0)
    return tuple(parts[:4])

def worker_update_required(dev):
    minimum=str(load_cfg().get("min_worker_version","") or "").strip()
    if not minimum:return False,""
    meta=parse_json(dev["meta_json"],{})
    current=str(meta.get("worker_version","") or "").strip()
    if not current:return True,minimum
    return version_tuple(current)<version_tuple(minimum),minimum

def update_device_runtime(con,dev,body):
    meta=sanitize_meta(body.get("meta",{}) if isinstance(body,dict) else {})
    caps=capabilities_from_meta(meta)
    con.execute("""update devices set last_seen=?,meta_json=?,capabilities_json=? where id=?""",
                (now(),json.dumps(meta,separators=(",",":")),
                 json.dumps(caps,separators=(",",":")),dev["id"]))

def trust_penalty(con,device_id,severe=False,reason="invalid"):
    delta=0.35 if severe else 0.15
    con.execute("""update devices set invalid_jobs=invalid_jobs+1,
                  trust_score=max(0.0,trust_score-?) where id=?""",(delta,device_id))
    row=con.execute("select trust_score,invalid_jobs from devices where id=?",(device_id,)).fetchone()
    if row and (row["trust_score"]<0.5 or row["invalid_jobs"]>=3):
        con.execute("update devices set quarantined=1,enabled=0 where id=?",(device_id,))
        audit(con,"device_quarantined",device_id,reason=reason,trust=row["trust_score"])
    else:audit(con,"trust_penalty",device_id,reason=reason,delta=delta)

def trust_reward(con,device_id):
    con.execute("""update devices set valid_jobs=valid_jobs+1,
                  trust_score=min(1.0,trust_score+0.01) where id=?""",(device_id,))

def expire_leases(con):
    t=now()
    rows=con.execute("""select id,segment_id,start_unit,end_unit,purpose from leases
                        where status='leased' and expires_at<?""",(t,)).fetchall()
    for r in rows:
        con.execute("update leases set status='expired' where id=?",(r["id"],))
        if r["purpose"]=="primary":
            done=con.execute("""select 1 from done_ranges where segment_id=? and start_unit=? and end_unit=?""",
                             (r["segment_id"],r["start_unit"],r["end_unit"])).fetchone()
            if not done:
                con.execute("""insert or ignore into requeue(segment_id,start_unit,end_unit,queued_at)
                               values(?,?,?,?)""",(r["segment_id"],r["start_unit"],r["end_unit"],t))
def segment_config(row):
    return parse_json(row["config_json"],{})

def device_eligible(dev,seg):
    if not dev["enabled"] or dev["quarantined"]:return False,None,0
    settings=normalize_settings(parse_json(dev["settings_json"],{}))
    caps=set(parse_json(dev["capabilities_json"],["cpu"]))
    cfg=segment_config(seg); req=set(cfg.get("requires",["cpu"]))
    if not req.issubset(caps):return False,None,0
    if "cuda" in req or "gpu" in req or "rocm" in req:
        if not settings["allow_gpu"] or settings["gpu_percent"]<=0:return False,None,0
        return True,"gpu",settings["gpu_percent"]
    if not settings["allow_cpu"] or settings["cpu_percent"]<=0:return False,None,0
    return True,"cpu",settings["cpu_percent"]

def make_lease(con,dev,seg,start,end,purpose,ttl):
    lid=rid("lease"); work=secrets.token_urlsafe(18); t=now()
    con.execute("""insert into leases(id,segment_id,device_id,start_unit,end_unit,work_token,status,
                  leased_at,expires_at,purpose) values(?,?,?,?,?,?,'leased',?,?,?)""",
                (lid,seg["id"],dev["id"],start,end,work,t,t+ttl,purpose))
    row=con.execute("""select l.*,s.engine,s.label,s.config_json from leases l
                       join segments s on s.id=l.segment_id where l.id=?""",(lid,)).fetchone()
    ok,resource,pct=device_eligible(dev,seg)
    return lease_obj(row,resource,pct)

def lease_obj(r,resource,pct):
    return {"id":r["id"],"segment_id":r["segment_id"],"segment_label":r["label"],
            "engine":r["engine"],"start_unit":r["start_unit"],"end_unit":r["end_unit"],
            "work_token":r["work_token"],"expires_at":r["expires_at"],"purpose":r["purpose"],
            "resource_class":resource,"resource_percent":pct,
            "config":parse_json(r["config_json"],{})}
def validation_candidate(con,dev):
    rows=con.execute("""select s.*,v.start_unit v_start,v.end_unit v_end,
                        v.target_replicas v_target,v.max_replicas v_max,v.created v_created
                        from validations v join segments s on s.id=v.segment_id
                        join campaigns c on c.id=s.campaign_id
                        where v.status='pending' and c.status='running'
                        order by s.priority,v.created limit 200""").fetchall()
    for r in rows:
        ok,resource,pct=device_eligible(dev,r)
        if not ok:continue
        prior=con.execute("""select count(*) n from submissions where segment_id=? and start_unit=? and end_unit=?""",
                          (r["id"],r["v_start"],r["v_end"])).fetchone()["n"]
        active=con.execute("""select count(*) n from leases where segment_id=? and start_unit=? and end_unit=?
                              and status='leased' and purpose='validation'""",
                           (r["id"],r["v_start"],r["v_end"])).fetchone()["n"]
        if prior+active>=r["v_target"]:continue
        same=con.execute("""select 1 from submissions where segment_id=? and start_unit=? and end_unit=?
                            and contributor_id=? limit 1""",
                         (r["id"],r["v_start"],r["v_end"],dev["contributor_id"])).fetchone()
        if same:continue
        active_same=con.execute("""select 1 from leases l join devices d on d.id=l.device_id
                                   where l.segment_id=? and l.start_unit=? and l.end_unit=? and l.status='leased'
                                   and d.contributor_id=? limit 1""",
                                (r["id"],r["v_start"],r["v_end"],dev["contributor_id"])).fetchone()
        if active_same:continue
        return r,resource,pct
    return None,None,None
def next_primary(con,dev):
    choices=[]
    rq=con.execute("""select r.segment_id,r.start_unit,r.end_unit,s.* from requeue r
                      join segments s on s.id=r.segment_id join campaigns c on c.id=s.campaign_id
                      where c.status='running' order by s.priority,r.queued_at limit 500""").fetchall()
    for r in rq:
        ok,res,pct=device_eligible(dev,r)
        if ok: choices.append((r["priority"],0,r,r["start_unit"],r["end_unit"],res,pct,True))
    segs=con.execute("""select s.* from segments s join campaigns c on c.id=s.campaign_id
                        where c.status='running' and s.next_unit<s.end_unit
                        order by s.priority,s.id limit 500""").fetchall()
    for s in segs:
        ok,res,pct=device_eligible(dev,s)
        if ok:
            start=s["next_unit"];end=min(s["end_unit"],start+s["chunk_size"])
            choices.append((s["priority"],1,s,start,end,res,pct,False))
    if not choices:return None,None,None,None,None,False
    _,_,seg,start,end,res,pct,wasrq=min(choices,key=lambda x:(x[0],x[1]))
    return seg,start,end,res,pct,wasrq

def credit_submission(con,row):
    if row["credited"]:return
    units=row["end_unit"]-row["start_unit"]
    con.execute("""insert into contributions(contributor_id,device_id,units,jobs,compute_seconds,candidates)
                   values(?,?,?,1,?,?) on conflict(contributor_id,device_id) do update set
                   units=units+excluded.units,jobs=jobs+1,
                   compute_seconds=compute_seconds+excluded.compute_seconds,
                   candidates=candidates+excluded.candidates""",
                (row["contributor_id"],row["device_id"],units,row["compute_seconds"],row["candidate_count"]))
    con.execute("update submissions set credited=1,status='verified' where id=?",(row["id"],))
    trust_reward(con,row["device_id"])
def reconcile(con,segid,start,end):
    v=con.execute("""select * from validations where segment_id=? and start_unit=? and end_unit=?""",
                  (segid,start,end)).fetchone()
    if not v or v["status"]!="pending":return v["status"] if v else "missing"
    rows=con.execute("""select * from submissions where segment_id=? and start_unit=? and end_unit=?
                        and status in ('pending','verified') order by submitted_at""",
                     (segid,start,end)).fetchall()
    counts=defaultdict(list)
    for r in rows:counts[r["fingerprint"]].append(r)
    best_fp=None;best=[]
    for fp,items in counts.items():
        if len(items)>len(best):best_fp,best=fp,items
    if len(best)>=v["base_required"]:
        canonical=best[0]
        con.execute("""insert or ignore into done_ranges(segment_id,start_unit,end_unit,lease_id,device_id,completed_at,result_json)
                       values(?,?,?,?,?,?,?)""",(segid,start,end,canonical["lease_id"],canonical["device_id"],now(),canonical["result_json"]))
        con.execute("""update validations set status='verified',canonical_fingerprint=?,verified_at=?
                       where segment_id=? and start_unit=? and end_unit=?""",(best_fp,now(),segid,start,end))
        for r in rows:
            if r["fingerprint"]==best_fp:credit_submission(con,r)
            elif r["status"]!="rejected":
                con.execute("update submissions set status='rejected' where id=?",(r["id"],))
                trust_penalty(con,r["device_id"],False,"consensus_mismatch")
        return "verified"
    total=len(rows)
    if len(counts)>1 and v["target_replicas"]<v["max_replicas"]:
        con.execute("""update validations set target_replicas=max_replicas
                       where segment_id=? and start_unit=? and end_unit=?""",(segid,start,end))
        return "pending_tiebreak"
    if total>=v["max_replicas"]:
        con.execute("""update validations set status='manual_review' where segment_id=? and start_unit=? and end_unit=?""",
                    (segid,start,end))
        audit(con,"validation_manual_review",None,segment_id=segid,start=start,end=end,
              fingerprints={k:len(x) for k,x in counts.items()})
        return "manual_review"
    return "pending"
def refresh_campaign_completion(con):
    for c in con.execute("select id from campaigns where status='running'"):
        cid=c["id"]
        total=con.execute("select coalesce(sum(end_unit-start_unit),0) n from segments where campaign_id=?",(cid,)).fetchone()["n"]
        done=con.execute("""select coalesce(sum(dr.end_unit-dr.start_unit),0) n from done_ranges dr
                            join segments s on s.id=dr.segment_id where s.campaign_id=?""",(cid,)).fetchone()["n"]
        pending=con.execute("select count(*) n from segments where campaign_id=? and next_unit<end_unit",(cid,)).fetchone()["n"]
        active=con.execute("""select count(*) n from leases l join segments s on s.id=l.segment_id
                              where s.campaign_id=? and l.status='leased'""",(cid,)).fetchone()["n"]
        val=con.execute("""select count(*) n from validations v join segments s on s.id=v.segment_id
                           where s.campaign_id=? and v.status in ('pending','manual_review')""",(cid,)).fetchone()["n"]
        rq=con.execute("""select count(*) n from requeue r join segments s on s.id=r.segment_id
                          where s.campaign_id=?""",(cid,)).fetchone()["n"]
        if total and done>=total and not pending and not active and not val and not rq:
            con.execute("update campaigns set status='complete' where id=?",(cid,))

def prune_private_data(con):
    global LAST_PRUNE
    t=now()
    if t-LAST_PRUNE<3600:return
    LAST_PRUNE=t
    con.execute("delete from registration_nonces where expires<?",(t,))
    con.execute("delete from audit_log where created<?",(t-30*86400,))
    con.execute("""update devices set meta_json='{}' where enabled=0
                   and last_seen is not null and last_seen<?""",(t-90*86400,))

def progress_payload(con):
    prune_private_data(con);expire_leases(con);refresh_campaign_completion(con)
    total=con.execute("""select coalesce(sum(s.end_unit-s.start_unit),0) n from segments s
                         join campaigns c on c.id=s.campaign_id where c.status='running'""").fetchone()["n"]
    done=con.execute("""select coalesce(sum(dr.end_unit-dr.start_unit),0) n from done_ranges dr
                        join segments s on s.id=dr.segment_id join campaigns c on c.id=s.campaign_id
                        where c.status='running'""").fetchone()["n"]
    pending=con.execute("""select count(*) n from validations v join segments s on s.id=v.segment_id
                           join campaigns c on c.id=s.campaign_id where c.status='running'
                           and v.status='pending'""").fetchone()["n"]
    online_cut=now()-load_cfg().get("online_seconds",60)
    devs=con.execute("""select capabilities_json,settings_json from devices
                        where enabled=1 and quarantined=0 and last_seen>?""",(online_cut,)).fetchall()
    cpu=gpu=0
    for d in devs:
        st=normalize_settings(parse_json(d["settings_json"],{}));caps=set(parse_json(d["capabilities_json"],[]))
        if st["allow_cpu"] and st["cpu_percent"]>0 and "cpu" in caps:cpu+=1
        if st["allow_gpu"] and st["gpu_percent"]>0 and ("cuda" in caps or "gpu" in caps):gpu+=1
    leaders=[dict(r) for r in con.execute("""select c.display_name,sum(x.units) units,sum(x.jobs) jobs,
              round(sum(x.compute_seconds),1) compute_seconds from contributions x join contributors c on c.id=x.contributor_id
              where c.public_credit=1 group by c.id order by units desc,compute_seconds desc limit 20""")]
    camps=[dict(r) for r in con.execute("select id,name,version,status,created,notes from campaigns order by created desc")]
    return {"total_units":total,"completed_units":done,"progress_pct":round(done*100/total,6) if total else 0,
            "online_devices":len(devs),"online_cpu_devices":cpu,"online_gpu_devices":gpu,
            "pending_validations":pending,"leaderboard":leaders,"campaigns":camps,"time":now()}

def personal_payload(con,token):
    c=con.execute("select * from contributors where dashboard_token_hash=?",(sha(token or ""),)).fetchone()
    if not c:return None
    devs=[]
    for r in con.execute("""select id,label,enabled,last_seen,meta_json,settings_json,capabilities_json,
                            trust_score,quarantined,valid_jobs,invalid_jobs,created from devices
                            where contributor_id=? order by created""",(c["id"],)):
        x=dict(r);x["meta"]=parse_json(x.pop("meta_json"),{});x["settings"]=normalize_settings(parse_json(x.pop("settings_json"),{}))
        x["capabilities"]=parse_json(x.pop("capabilities_json"),[]);devs.append(x)
    stats=dict(con.execute("""select coalesce(sum(units),0) units,coalesce(sum(jobs),0) jobs,
                              coalesce(sum(compute_seconds),0) compute_seconds,
                              coalesce(sum(candidates),0) candidates from contributions where contributor_id=?""",
                           (c["id"],)).fetchone())
    pending=con.execute("""select coalesce(sum(end_unit-start_unit),0) n from submissions
                           where contributor_id=? and status='pending'""",(c["id"],)).fetchone()["n"]
    return {"contributor_id":c["id"],"display_name":c["display_name"],"public_credit":bool(c["public_credit"]),
            "devices":devs,"stats":stats,"pending_units":pending}

def rate_key(handler):
    token=handler.headers.get("X-Device-Token","").strip()
    raw=("token:"+token) if token else ("anon:"+str(handler.client_address[0]))
    return sha(RATE_SALT.hex()+raw)

def allowed_request(handler):
    cfg=load_cfg();limit=int(cfg.get("rate_limit_per_minute",180));key=rate_key(handler);q=RATE[key];t=now()
    while q and q[0]<t-60:q.popleft()
    if len(q)>=limit:return False
    q.append(t);return True

class LimitedThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads=True
    request_queue_size=64
    allow_reuse_address=True
    def __init__(self,address,handler,max_workers=64):
        self._slots=threading.BoundedSemaphore(max_workers)
        super().__init__(address,handler)
    def process_request(self,request,client_address):
        if not self._slots.acquire(blocking=False):
            try:request.close()
            except Exception:pass
            return
        try:super().process_request(request,client_address)
        except Exception:
            self._slots.release();raise
    def process_request_thread(self,request,client_address):
        try:super().process_request_thread(request,client_address)
        finally:self._slots.release()

class Handler(BaseHTTPRequestHandler):
    server_version="EnigmaVolunteerGrid"
    sys_version=""
    def setup(self):
        super().setup()
        self.request.settimeout(15)
    def version_string(self): return "EnigmaVolunteerGrid"
    def log_message(self,fmt,*args): print(fmt%args,flush=True)
    def security_headers(self):
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("X-Frame-Options","DENY")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Permissions-Policy","camera=(), microphone=(), geolocation=(), usb=(), payment=()")
        self.send_header("Cross-Origin-Opener-Policy","same-origin")
        self.send_header("Cross-Origin-Resource-Policy","same-origin")
        self.send_header("Content-Security-Policy","default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
    def send_json(self,code,obj):
        data=json.dumps(obj,separators=(",",":")).encode()
        self.send_response(code);self.send_header("Content-Type","application/json");self.send_header("Cache-Control","no-store")
        self.security_headers();self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data)
    def body(self):
        n=int(self.headers.get("Content-Length","0"));mx=int(load_cfg().get("max_body_bytes",262144))
        if n<0 or n>mx:raise ValueError("body_too_large")
        return json.loads(self.rfile.read(n) or b"{}")
    def token(self):return self.headers.get("X-Device-Token","").strip()
    def do_GET(self):
        if not allowed_request(self):return self.send_json(429,{"error":"rate_limited"})
        u=urlparse(self.path)
        if u.path=="/":
            data=WEB.read_bytes();self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Cache-Control","no-store");self.security_headers()
            self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data);return
        if u.path in {"/style.css","/app.js"}:
            p=ROOT/"web"/u.path.lstrip("/");data=p.read_bytes()
            ctype="text/css; charset=utf-8" if u.path.endswith(".css") else "text/javascript; charset=utf-8"
            self.send_response(200);self.send_header("Content-Type",ctype);self.send_header("Cache-Control","no-store")
            self.security_headers();self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data);return
        if u.path=="/health":return self.send_json(200,{"ok":True,"version":"0.3","time":now()})
        if u.path=="/api/register-challenge":
            con=db()
            try:return self.send_json(200,new_registration_challenge(con))
            finally:con.close()
        if u.path=="/api/public/config":
            cfg=load_cfg()
            return self.send_json(200,{"github_repo":str(cfg.get("github_repo","")),
                                       "min_worker_version":str(cfg.get("min_worker_version","")),
                                       "update_check_seconds":max(900,int(cfg.get("update_check_seconds",21600)))})
        if u.path=="/api/public/status":
            con=db()
            try:return self.send_json(200,progress_payload(con))
            finally:con.close()
        return self.send_json(404,{"error":"not_found"})
    def do_POST(self):
        if not allowed_request(self):return self.send_json(429,{"error":"rate_limited"})
        try:b=self.body()
        except Exception as e:return self.send_json(400,{"error":str(e)})
        u=urlparse(self.path);con=db()
        try:
            if u.path=="/api/register":return self.register(con,b)
            if u.path=="/api/me":
                p=personal_payload(con,b.get("dashboard_token",""))
                return self.send_json(200,p) if p else self.send_json(403,{"error":"invalid_dashboard_token"})
            if u.path=="/api/me/settings":return self.me_settings(con,b)
            if u.path=="/api/me/delete":return self.delete_account(con,b)
            dev=device_from_token(con,self.token())
            if not dev:return self.send_json(403,{"error":"invalid_device_token"})
            update_device_runtime(con,dev,b)
            dev=con.execute("""select d.*,c.display_name,c.public_credit from devices d join contributors c
                               on c.id=d.contributor_id where d.id=?""",(dev["id"],)).fetchone()
            if u.path=="/api/heartbeat":
                ttl=int(load_cfg().get("lease_seconds",900))
                con.execute("update leases set expires_at=? where device_id=? and status='leased'",(now()+ttl,dev["id"]))
                required,minimum=worker_update_required(dev)
                return self.send_json(200,{"ok":True,"enabled":bool(dev["enabled"] and not dev["quarantined"]),
                                           "settings":normalize_settings(parse_json(dev["settings_json"],{})),
                                           "trust_score":dev["trust_score"],"quarantined":bool(dev["quarantined"]),
                                           "update_required":required,"min_worker_version":minimum})
            if u.path=="/api/lease":return self.lease(con,dev)
            if u.path=="/api/complete":return self.complete(con,dev,b)
            if u.path=="/api/device/settings":
                st=normalize_settings(b.get("settings",{}));con.execute("update devices set settings_json=? where id=?",
                    (json.dumps(st,separators=(",",":")),dev["id"]));return self.send_json(200,{"ok":True,"settings":st})
            if u.path=="/api/device/disable":
                con.execute("update devices set enabled=0 where id=?",(dev["id"],));return self.send_json(200,{"ok":True,"enabled":False})
            return self.send_json(404,{"error":"not_found"})
        finally:con.close()
    def register(self,con,b):
        cfg=load_cfg()
        supplied=str(b.get("registration_code",""))
        secret=str(cfg.get("registration_code",""))
        secret_ok=bool(secret and secrets.compare_digest(supplied,secret))
        if not secret_ok:
            if not cfg.get("registration_open",False):
                return self.send_json(403,{"error":"registration_closed"})
            if not verify_registration_pow(con,b):
                return self.send_json(403,{"error":"registration_proof_invalid"})
        name=(b.get("display_name") or "Anonymous volunteer").strip()[:80]
        label=(b.get("device_label") or "PC").strip()[:80];join=b.get("contributor_key");new_key=dash=None
        if join:
            contributor=con.execute("select * from contributors where join_key_hash=?",(sha(join),)).fetchone()
            if not contributor:return self.send_json(403,{"error":"invalid_contributor_key"})
        else:
            cid=rid("ctr");new_key=secrets.token_urlsafe(24);dash=secrets.token_urlsafe(24)
            con.execute("""insert into contributors(id,display_name,public_credit,join_key_hash,dashboard_token_hash,created)
                           values(?,?,?,?,?,?)""",(cid,name,1 if b.get("public_credit",True) else 0,sha(new_key),sha(dash),now()))
            contributor=con.execute("select * from contributors where id=?",(cid,)).fetchone()
        token=secrets.token_urlsafe(32);did=rid("dev");meta=sanitize_meta(b.get("meta",{}));st=normalize_settings(b.get("settings",{}))
        caps=capabilities_from_meta(meta)
        con.execute("""insert into devices(id,contributor_id,label,token_hash,enabled,last_seen,meta_json,created,
                     settings_json,capabilities_json) values(?,?,?,?,1,?,?,?,?,?)""",
                    (did,contributor["id"],label,sha(token),now(),json.dumps(meta,separators=(",",":")),now(),
                     json.dumps(st,separators=(",",":")),json.dumps(caps,separators=(",",":"))))
        audit(con,"device_registered",did,capabilities=caps,settings=st)
        return self.send_json(200,{"ok":True,"contributor_id":contributor["id"],"device_id":did,"device_token":token,
                                   "contributor_key":new_key,"dashboard_token":dash,"settings":st})
    def me_settings(self,con,b):
        c=con.execute("select * from contributors where dashboard_token_hash=?",(sha(b.get("dashboard_token","")),)).fetchone()
        if not c:return self.send_json(403,{"error":"invalid_dashboard_token"})
        dev=con.execute("select * from devices where id=? and contributor_id=?",(b.get("device_id"),c["id"])).fetchone()
        if not dev:return self.send_json(404,{"error":"device_not_found"})
        st=normalize_settings(b.get("settings",{}));con.execute("update devices set settings_json=? where id=?",
             (json.dumps(st,separators=(",",":")),dev["id"]))
        audit(con,"settings_changed",dev["id"],settings=st)
        return self.send_json(200,{"ok":True,"settings":st})

    def delete_account(self,con,b):
        if b.get("confirm")!="DELETE":return self.send_json(400,{"error":"confirmation_required"})
        c=con.execute("select * from contributors where dashboard_token_hash=?",(sha(b.get("dashboard_token","")),)).fetchone()
        if not c:return self.send_json(403,{"error":"invalid_dashboard_token"})
        con.execute("begin immediate")
        try:
            ids=[r["id"] for r in con.execute("select id from devices where contributor_id=?",(c["id"],))]
            for did in ids:
                for l in con.execute("""select segment_id,start_unit,end_unit,purpose from leases
                                        where device_id=? and status='leased'""",(did,)).fetchall():
                    if l["purpose"]=="primary":
                        con.execute("""insert or ignore into requeue(segment_id,start_unit,end_unit,queued_at)
                                       values(?,?,?,?)""",(l["segment_id"],l["start_unit"],l["end_unit"],now()))
                con.execute("update done_ranges set device_id='deleted' where device_id=?",(did,))
                con.execute("delete from audit_log where device_id=?",(did,))
                con.execute("delete from leases where device_id=?",(did,))
            con.execute("delete from submissions where contributor_id=?",(c["id"],))
            con.execute("delete from contributions where contributor_id=?",(c["id"],))
            con.execute("delete from devices where contributor_id=?",(c["id"],))
            con.execute("delete from contributors where id=?",(c["id"],))
            con.execute("commit")
            return self.send_json(200,{"ok":True,"deleted":True})
        except Exception:
            con.execute("rollback");raise
    def lease(self,con,dev):
        if not dev["enabled"] or dev["quarantined"]:return self.send_json(200,{"enabled":False,"lease":None})
        required,minimum=worker_update_required(dev)
        if required:
            return self.send_json(200,{"enabled":True,"lease":None,"update_required":True,
                                       "min_worker_version":minimum})
        ttl=int(load_cfg().get("lease_seconds",900));con.execute("begin immediate")
        try:
            expire_leases(con)
            old=con.execute("""select l.*,s.engine,s.label,s.config_json from leases l join segments s on s.id=l.segment_id
                               where l.device_id=? and l.status='leased' order by l.leased_at desc limit 1""",(dev["id"],)).fetchone()
            if old:
                seg=con.execute("select * from segments where id=?",(old["segment_id"],)).fetchone()
                ok,res,pct=device_eligible(dev,seg)
                con.execute("commit");return self.send_json(200,{"enabled":True,"lease":lease_obj(old,res,pct)})
            vr,res,pct=validation_candidate(con,dev)
            if vr:
                obj=make_lease(con,dev,vr,vr["v_start"],vr["v_end"],"validation",ttl)
                con.execute("commit");return self.send_json(200,{"enabled":True,"lease":obj})
            seg,start,end,res,pct,wasrq=next_primary(con,dev)
            if not seg:
                con.execute("commit");return self.send_json(200,{"enabled":True,"lease":None})
            if wasrq:con.execute("delete from requeue where segment_id=? and start_unit=? and end_unit=?",(seg["id"],start,end))
            else:con.execute("update segments set next_unit=? where id=?",(end,seg["id"]))
            obj=make_lease(con,dev,seg,start,end,"primary",ttl);con.execute("commit")
            return self.send_json(200,{"enabled":True,"lease":obj})
        except Exception:
            con.execute("rollback");raise
    def complete(self,con,dev,b):
        lid=b.get("lease_id");work=b.get("work_token");con.execute("begin immediate")
        try:
            lease=con.execute("""select l.*,s.engine,s.config_json,s.label from leases l join segments s
                                 on s.id=l.segment_id where l.id=? and l.device_id=?""",(lid,dev["id"])).fetchone()
            if not lease or lease["work_token"]!=work:
                con.execute("rollback");return self.send_json(403,{"error":"invalid_lease"})
            if lease["status"]!="leased":
                con.execute("commit");return self.send_json(200,{"ok":True,"duplicate":True,"credited":False})
            done=con.execute("""select 1 from done_ranges where segment_id=? and start_unit=? and end_unit=?""",
                             (lease["segment_id"],lease["start_unit"],lease["end_unit"])).fetchone()
            if done:
                con.execute("update leases set status='superseded',completed_at=? where id=?",(now(),lid))
                con.execute("commit");return self.send_json(200,{"ok":True,"duplicate":True,"credited":False})
            cfg=segment_config(lease)
            lease_obj_for_validation={"segment_id":lease["segment_id"],"start_unit":lease["start_unit"],
                                      "end_unit":lease["end_unit"],"config":cfg}
            try:clean,fp=validate_result(lease["engine"],b.get("result",{}),lease_obj_for_validation)
            except Exception as e:
                con.execute("update leases set status='rejected',completed_at=? where id=?",(now(),lid))
                trust_penalty(con,dev["id"],True,"server_validation:"+str(e))
                if lease["purpose"]=="primary":
                    con.execute("""insert or ignore into requeue(segment_id,start_unit,end_unit,queued_at) values(?,?,?,?)""",
                                (lease["segment_id"],lease["start_unit"],lease["end_unit"],now()))
                con.execute("commit");return self.send_json(422,{"error":"result_validation_failed","detail":str(e),"credited":False})
            raw=json.dumps(clean,separators=(",",":"),sort_keys=True);sid=rid("sub")
            wall=max(0.0,now()-float(lease["leased_at"]))
            client_secs=max(0.0,float(b.get("compute_seconds",0) or 0))
            safe_secs=min(client_secs,wall+5.0)
            safe_candidates=len(clean.get("candidates",[])) if isinstance(clean.get("candidates"),list) else 0
            con.execute("""insert into submissions(id,lease_id,segment_id,start_unit,end_unit,device_id,contributor_id,
                          fingerprint,result_json,compute_seconds,candidate_count,status,credited,submitted_at)
                          values(?,?,?,?,?,?,?,?,?,?,?,'pending',0,?)""",
                        (sid,lid,lease["segment_id"],lease["start_unit"],lease["end_unit"],dev["id"],dev["contributor_id"],
                         fp,raw,safe_secs,safe_candidates,now()))
            con.execute("update leases set status='submitted',completed_at=? where id=?",(now(),lid))
            base=max(2,int(cfg.get("replicas_required",load_cfg().get("replicas_required",2))))
            mx=max(base,int(cfg.get("max_replicas",load_cfg().get("max_replicas",3))))
            con.execute("""insert or ignore into validations(segment_id,start_unit,end_unit,base_required,target_replicas,
                          max_replicas,status,created) values(?,?,?,?,?,?,'pending',?)""",
                        (lease["segment_id"],lease["start_unit"],lease["end_unit"],base,base,mx,now()))
            status=reconcile(con,lease["segment_id"],lease["start_unit"],lease["end_unit"])
            con.execute("delete from requeue where segment_id=? and start_unit=? and end_unit=?",
                        (lease["segment_id"],lease["start_unit"],lease["end_unit"]))
            refresh_campaign_completion(con);con.execute("commit")
            credited=bool(con.execute("select credited from submissions where id=?",(sid,)).fetchone()["credited"])
            return self.send_json(200,{"ok":True,"duplicate":False,"credited":credited,
                                       "validation_status":status,"fingerprint":fp})
        except Exception:
            con.execute("rollback");raise

def bind_host_allowed(host):
    host=str(host or "").strip().lower()
    if host in {"127.0.0.1","::1","localhost"}:return True
    return os.environ.get("GRID_ALLOW_NON_LOOPBACK","").lower() in {"1","true","yes","on"}

def main():
    init_db();cfg=load_cfg();host=cfg.get("host","127.0.0.1");port=int(cfg.get("port",8765))
    if not bind_host_allowed(host):
        raise SystemExit("Refusing non-loopback bind. Use Tailscale Funnel; set GRID_ALLOW_NON_LOOPBACK only inside an isolated container.")
    print(f"Enigma Volunteer Grid v0.3 listening on http://{host}:{port}",flush=True)
    LimitedThreadingHTTPServer((host,port),Handler,max_workers=int(cfg.get("max_http_workers",64))).serve_forever()

if __name__=="__main__":main()
