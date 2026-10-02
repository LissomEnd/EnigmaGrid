import base64
import ctypes
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

HERE=Path(__file__).resolve().parent
RESOURCE_ROOT=Path(getattr(sys,"_MEIPASS",HERE.parent))
RESOURCE_WORKER=RESOURCE_ROOT/"worker" if getattr(sys,"frozen",False) else HERE
CFG=RESOURCE_WORKER/"update_config.json"
PUB=RESOURCE_WORKER/"update_public_key.json"

def version_tuple(v):
    m=re.match(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?",str(v).strip())
    if not m:return (0,0,0)
    return tuple(int(x or 0) for x in m.groups())

def fetch_bytes(url,timeout=30):
    req=urllib.request.Request(url,headers={"User-Agent":"EnigmaVolunteerGrid-Updater/1"})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return r.read()

def fetch_json(url,timeout=30):
    return json.loads(fetch_bytes(url,timeout).decode("utf-8"))
def verify_manifest(data,sig_b64):
    pub=json.loads(PUB.read_text(encoding="utf-8"))
    if pub.get("algorithm")!="ed25519":raise ValueError("unsupported_signature_algorithm")
    key=Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub["public_key_hex"]))
    sig=base64.b64decode(sig_b64,validate=True)
    key.verify(sig,data)

def valid_https(url,allowed_host=None):
    u=urlparse(url)
    if u.scheme!="https":return False
    if allowed_host and u.hostname!=allowed_host:return False
    return True

def load_json(path,default):
    try:return json.loads(path.read_text(encoding="utf-8"))
    except Exception:return default

def save_json(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,indent=2),encoding="utf-8")
    tmp.replace(path)

def prompt_update(version,mandatory,notes):
    if os.name!="nt":return False
    title="Enigma Volunteer Grid update"
    if mandatory:
        msg=f"Security update {version} is REQUIRED.\n\nYes: download and install at the next safe point.\nNo: finish current work and close safely."
    else:
        msg=f"Update {version} is available.\n\nDownload it in the background and install at the next safe point?"
    if notes:
        msg+="\n\n"+str(notes)[:900]
    MB_YESNO=0x4;MB_ICONINFORMATION=0x40;MB_SETFOREGROUND=0x10000
    return ctypes.windll.user32.MessageBoxW(None,msg,title,MB_YESNO|MB_ICONINFORMATION|MB_SETFOREGROUND)==6

def manifest_is_mandatory(manifest,current):
    if bool(manifest.get("mandatory",False)):return True
    minimum=manifest.get("min_supported_version")
    return bool(minimum and version_tuple(current)<version_tuple(minimum))

class UpdateManager:
    def __init__(self,current_version,state_path,server_url):
        self.current_version=current_version
        self.state_path=Path(state_path)
        self.server_url=server_url
        self.local_state_path=self.state_path.with_name("update_state.json")
        self.local_state=load_json(self.local_state_path,{})
        self.cfg=load_json(CFG,{})
        self.stop_event=threading.Event()
        self.wake=threading.Event()
        self.lock=threading.Lock()
        self.thread=None
        self.apply_requested=False
        self.stop_requested=False
        self.pending=None
        self.last_error=None

    def start(self):
        if self.thread and self.thread.is_alive():return
        self.thread=threading.Thread(target=self._loop,name="update-checker",daemon=True)
        self.thread.start()
    def shutdown(self):
        self.stop_event.set();self.wake.set()

    def force_check(self):
        self.wake.set()

    def _loop(self):
        first=True
        while not self.stop_event.is_set():
            if not first:
                interval=max(900,int(self.cfg.get("check_interval_seconds",21600)))
                self.wake.wait(interval);self.wake.clear()
                if self.stop_event.is_set():break
            first=False
            try:self.check_once()
            except Exception as e:self.last_error=repr(e)

    def resolve_repo(self):
        repo=str(self.cfg.get("github_repo","")).strip()
        if not repo:
            url=self.server_url.rstrip("/")+"/api/public/config"
            public=fetch_json(url,15)
            repo=str(public.get("github_repo","")).strip()
        if not repo:return ""
        if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$",repo):
            raise ValueError("invalid_github_repo")
        return repo

    def _release(self):
        repo=self.resolve_repo()
        if not repo:return None
        url=f"https://api.github.com/repos/{repo}/releases/latest"
        rel=fetch_json(url,30)
        if rel.get("draft") or rel.get("prerelease"):return None
        return rel

    def check_once(self):
        rel=self._release()
        if not rel:return None
        assets={a.get("name"):a for a in rel.get("assets",[]) if isinstance(a,dict)}
        mn=self.cfg.get("manifest_name","update-manifest.json")
        sn=self.cfg.get("signature_name","update-manifest.sig")
        if mn not in assets or sn not in assets:raise ValueError("signed_update_metadata_missing")
        murl=assets[mn].get("browser_download_url","")
        surl=assets[sn].get("browser_download_url","")
        if not valid_https(murl,"github.com") or not valid_https(surl,"github.com"):
            raise ValueError("invalid_manifest_asset_url")
        mdata=fetch_bytes(murl,30);sig=fetch_bytes(surl,30).decode("ascii").strip()
        verify_manifest(mdata,sig)
        manifest=json.loads(mdata.decode("utf-8"))
        if int(manifest.get("schema",0))!=1:raise ValueError("unsupported_update_schema")
        version=str(manifest.get("version",""))
        if not re.fullmatch(r"\d+\.\d+\.\d+",version):raise ValueError("invalid_update_version")
        if version_tuple(version)<=version_tuple(self.current_version):return None
        repo=self.resolve_repo()
        if manifest.get("repository") not in (None,repo):raise ValueError("manifest_repository_mismatch")
        mandatory=manifest_is_mandatory(manifest,self.current_version)
        if self.local_state.get("dismissed_version")==version and not mandatory:return None
        accepted=prompt_update(version,mandatory,manifest.get("notes",""))
        if not accepted:
            if mandatory:
                with self.lock:self.stop_requested=True
            else:
                self.local_state["dismissed_version"]=version
                save_json(self.local_state_path,self.local_state)
            return {"version":version,"accepted":False,"mandatory":mandatory}
        staged=self._download_asset(rel,manifest,mdata,sig)
        with self.lock:
            self.pending=staged
            self.apply_requested=True
        return staged

    def _download_asset(self,rel,manifest,mdata,sig):
        assets={a.get("name"):a for a in rel.get("assets",[]) if isinstance(a,dict)}
        name=str(manifest.get("asset_name",self.cfg.get("asset_name","")))
        if not name or Path(name).name!=name:raise ValueError("invalid_update_asset_name")
        asset=assets.get(name)
        if not asset:raise ValueError("update_asset_missing")
        url=asset.get("browser_download_url","")
        if not valid_https(url,"github.com"):raise ValueError("invalid_update_asset_url")
        expected=str(manifest.get("sha256","")).lower()
        if not re.fullmatch(r"[0-9a-f]{64}",expected):raise ValueError("invalid_update_sha256")
        max_size=600*1024*1024
        declared=int(manifest.get("size",0) or 0)
        if declared<=0 or declared>max_size:raise ValueError("invalid_update_size")
        target_dir=self.state_path.parent/"updates"/str(manifest["version"])
        target_dir.mkdir(parents=True,exist_ok=True)
        tmp=target_dir/(name+".part");final=target_dir/name
        req=urllib.request.Request(url,headers={"User-Agent":"EnigmaVolunteerGrid-Updater/1"})
        h=hashlib.sha256();size=0
        with urllib.request.urlopen(req,timeout=60) as r,open(tmp,"wb") as f:
            while True:
                block=r.read(1024*1024)
                if not block:break
                size+=len(block)
                if size>max_size:raise ValueError("update_too_large")
                h.update(block);f.write(block)
        if size!=declared or h.hexdigest().lower()!=expected:
            try:tmp.unlink()
            except Exception:pass
            raise ValueError("update_hash_or_size_mismatch")
        tmp.replace(final)
        mp=target_dir/"update-manifest.json";sp=target_dir/"update-manifest.sig"
        mp.write_bytes(mdata);sp.write_text(sig,encoding="ascii")
        self.local_state["downloaded_version"]=manifest["version"]
        save_json(self.local_state_path,self.local_state)
        return {"version":manifest["version"],"mandatory":manifest_is_mandatory(manifest,self.current_version),
                "asset":str(final),"manifest":str(mp),"signature":str(sp)}
    def launch_apply(self,install_root):
        with self.lock:
            p=dict(self.pending or {})
            if not self.apply_requested or not p:return False
        script=HERE/"updater_apply.py"
        cmd=[sys.executable,str(script),"--parent-pid",str(os.getpid()),
             "--install-root",str(install_root),"--state",str(self.state_path),
             "--server",self.server_url,"--asset",p["asset"],
             "--manifest",p["manifest"],"--signature",p["signature"]]
        flags=0
        if os.name=="nt":
            flags=getattr(subprocess,"CREATE_NO_WINDOW",0)|getattr(subprocess,"DETACHED_PROCESS",0)
        subprocess.Popen(cmd,close_fds=True,creationflags=flags)
        return True
