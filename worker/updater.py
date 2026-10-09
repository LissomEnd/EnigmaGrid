import base64
import ctypes
import hashlib
import ipaddress
import json
import multiprocessing
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

def safe_fetch_url(url):
    u=urlparse(url)
    if u.scheme=="https" and u.hostname:return True
    if u.scheme!="http" or not u.hostname:return False
    host=u.hostname.lower()
    if host=="localhost":return True
    try:
        ip=ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:return False

def fetch_bytes(url,timeout=30):
    if not safe_fetch_url(url):raise ValueError("unsafe_update_url")
    req=urllib.request.Request(url,headers={"User-Agent":"EnigmaVolunteerGrid-Updater/1"})
    with urllib.request.urlopen(req,timeout=timeout) as r:  # nosec B310
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

def _message_box_update(version,mandatory,notes):
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

def _prompt_child(send,version,mandatory,notes):
    try:
        send.send(("ok",_message_box_update(version,mandatory,notes)))
    except BaseException as error:
        try:send.send(("error",type(error).__name__))
        except (OSError,EOFError):pass
    finally:
        send.close()

def _await_owned_prompt(child,receive,stop_event):
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                raise InterruptedError("Update prompt cancelled")
            if receive.poll(.1):
                try:status,value=receive.recv()
                except EOFError:raise RuntimeError("Update prompt closed without a result")
                if status!="ok":raise RuntimeError("Update prompt failed: "+str(value))
                return bool(value)
            if not child.is_alive():
                raise RuntimeError("Update prompt exited without a result")
    finally:
        # This handle is the exact process created above, never a searched
        # application PID or another user's window.
        child.join(.5)
        if child.is_alive():
            child.terminate();child.join(3)
        if child.is_alive():
            child.kill();child.join(3)
        receive.close()

def prompt_update(version,mandatory,notes,stop_event=None):
    """Ask in an owned child so a safe stop can close only this dialog."""
    if os.name!="nt":return False
    if stop_event is not None and stop_event.is_set():
        raise InterruptedError("Update prompt cancelled")
    context=multiprocessing.get_context("spawn")
    receive,send=context.Pipe(duplex=False)
    child=context.Process(target=_prompt_child,args=(send,version,mandatory,notes),
                          daemon=True,name="enigmagrid-update-prompt")
    try:
        child.start()
    except BaseException:
        receive.close();send.close()
        raise
    send.close()
    return _await_owned_prompt(child,receive,stop_event)

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
        self.status_path=self.state_path.with_name("update_status.json")
        self.request_path=self.state_path.with_name("check-update-request")
        self.manual_check=False

    def start(self):
        if self.thread and self.thread.is_alive():return
        self.thread=threading.Thread(target=self._loop,name="update-checker")
        self.thread.start()
    def shutdown(self):
        self.stop_event.set();self.wake.set()
        if self.thread is not None and self.thread.ident is not None:
            # One in-flight asset read has a 60-second socket timeout. The
            # prompt is cancellable independently and should finish promptly.
            self.thread.join(timeout=65)
            if self.thread.is_alive():
                raise RuntimeError('Update checker did not terminate')

    def _check_stop(self):
        if self.stop_event.is_set():raise InterruptedError('Update checker stopping')

    def report(self,status,message):
        save_json(self.status_path,{"status":status,"message":message,"checked_at":time.time(),"current_version":self.current_version})

    def force_check(self):
        self.wake.set()

    def _loop(self):
        next_check=0
        while not self.stop_event.is_set():
            requested=self.request_path.exists()
            if requested:
                self.request_path.unlink(missing_ok=True)
                self.manual_check=True
            if requested or self.wake.is_set() or time.monotonic()>=next_check:
                self.wake.clear()
                try:
                    if self.manual_check:
                        self.local_state.pop("dismissed_version",None)
                    self.manual_check=False
                    self.check_once()
                    self.last_error=None
                except Exception as e:
                    if self.stop_event.is_set():return
                    self.last_error=repr(e)
                    self.report("error","Could not check or verify the update. Check your connection and retry. Your current installation is unchanged.")
                next_check=time.monotonic()+max(900,int(self.cfg.get("check_interval_seconds",21600)))
            self.stop_event.wait(1)

    def resolve_repo(self):
        self._check_stop()
        repo=str(self.cfg.get("github_repo","")).strip()
        if not repo:
            url=self.server_url.rstrip("/")+"/api/public/config"
            public=fetch_json(url,15)
            self._check_stop()
            repo=str(public.get("github_repo","")).strip()
        if not repo:return ""
        if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$",repo):
            raise ValueError("invalid_github_repo")
        return repo

    def _release(self):
        repo=self.resolve_repo()
        self._check_stop()
        if not repo:return None
        base=f"https://api.github.com/repos/{repo}/releases"
        required={self.cfg.get("manifest_name","update-manifest.json"),
                  self.cfg.get("signature_name","update-manifest.sig"),
                  self.cfg.get("asset_name","enigma-volunteer-windows.zip")}
        if len(required)!=3 or any(not isinstance(name,str) or not name or Path(name).name!=name for name in required):
            raise ValueError("invalid_update_asset_config")

        def windows_release(rel):
            if not isinstance(rel,dict) or rel.get("draft") is not False or rel.get("prerelease") is not False:
                return False
            if not re.fullmatch(r"v?\d+\.\d+\.\d+",str(rel.get("tag_name",""))):return False
            assets=rel.get("assets")
            if not isinstance(assets,list):return False
            found=set()
            for asset in assets:
                if not isinstance(asset,dict):continue
                name=asset.get("name")
                if isinstance(name,str) and name in required:
                    url=asset.get("browser_download_url")
                    try:asset_url_ok=isinstance(url,str) and valid_https(url,"github.com")
                    except ValueError:asset_url_ok=False
                    if name in found or not asset_url_ok:
                        return False
                    found.add(name)
            return found==required

        self._check_stop()
        latest=fetch_json(base+"/latest",30)
        self._check_stop()
        if windows_release(latest) and version_tuple(latest["tag_name"])>version_tuple(self.current_version):
            return latest
        # GitHub's latest release may be an Android-only package. Inspect one
        # bounded page and choose the highest stable Windows version, not the
        # first release by creation date. The signed manifest remains authoritative.
        listed=fetch_json(base+"?per_page=100&page=1",30)
        self._check_stop()
        if isinstance(listed,list):
            matches=[rel for rel in listed[:100] if windows_release(rel)]
            if matches:return max(matches,key=lambda rel:version_tuple(rel["tag_name"]))
        return latest if windows_release(latest) else None

    def check_once(self):
        self._check_stop()
        if self.apply_requested:
            self.report("ready","A verified update is ready. Installation will start after the current job finishes.")
            return self.pending
        self.report("checking","Checking GitHub for a signed update...")
        rel=self._release()
        self._check_stop()
        if not rel:
            self.report("error","Update source unavailable. Please retry later.")
            return None
        assets={a.get("name"):a for a in rel.get("assets",[]) if isinstance(a,dict)}
        mn=self.cfg.get("manifest_name","update-manifest.json")
        sn=self.cfg.get("signature_name","update-manifest.sig")
        if mn not in assets or sn not in assets:raise ValueError("signed_update_metadata_missing")
        murl=assets[mn].get("browser_download_url","")
        surl=assets[sn].get("browser_download_url","")
        if not valid_https(murl,"github.com") or not valid_https(surl,"github.com"):
            raise ValueError("invalid_manifest_asset_url")
        mdata=fetch_bytes(murl,30)
        self._check_stop()
        sig=fetch_bytes(surl,30).decode("ascii").strip()
        self._check_stop()
        verify_manifest(mdata,sig)
        manifest=json.loads(mdata.decode("utf-8"))
        if int(manifest.get("schema",0))!=1:raise ValueError("unsupported_update_schema")
        version=str(manifest.get("version",""))
        if not re.fullmatch(r"\d+\.\d+\.\d+",version):raise ValueError("invalid_update_version")
        if version_tuple(version)<=version_tuple(self.current_version):
            self.report("current",f"You are up to date — version {self.current_version}.")
            return None
        repo=self.resolve_repo()
        if manifest.get("repository") not in (None,repo):raise ValueError("manifest_repository_mismatch")
        mandatory=manifest_is_mandatory(manifest,self.current_version)
        if self.local_state.get("dismissed_version")==version and not mandatory:
            self.report("available",f"Version {version} is available. Choose Check for updates to review it again.")
            return None
        self.report("available",f"Version {version} is available. Choose Yes or No in the update window.")
        self._check_stop()
        accepted=prompt_update(version,mandatory,manifest.get("notes",""),self.stop_event)
        self._check_stop()
        if not accepted:
            if mandatory:
                with self.lock:self.stop_requested=True
            else:
                self.local_state["dismissed_version"]=version
                save_json(self.local_state_path,self.local_state)
            self.report("deferred", "Required update declined; stopping safely." if mandatory else f"Version {version} postponed. You can check again whenever you are ready.")
            return {"version":version,"accepted":False,"mandatory":mandatory}
        self.report("downloading",f"Downloading version {version} and verifying its signature. You can continue contributing.")
        staged=self._download_asset(rel,manifest,mdata,sig)
        self._check_stop()
        with self.lock:
            self.pending=staged
            self.apply_requested=True
        self.report("ready",f"Version {version} is verified and ready. Installation will start after the current job finishes.")
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
        with urllib.request.urlopen(req,timeout=60) as r,open(tmp,"wb") as f:  # nosec B310
            while True:
                self._check_stop()
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
        frozen=bool(getattr(sys,"frozen",False))
        if frozen:
            helper=Path(install_root)/"EnigmaGridUpdater.exe"
            if not helper.exists():raise FileNotFoundError("EnigmaGridUpdater.exe")
            apply_dir=self.state_path.parent/"update-runner"
            apply_dir.mkdir(parents=True,exist_ok=True)
            runner=apply_dir/"EnigmaGridUpdater.exe"
            import shutil
            shutil.copy2(helper,runner)
            cmd=[str(runner)]
        else:
            script=HERE/"updater_apply.py"
            cmd=[sys.executable,str(script)]
        cmd += ["--parent-pid",str(os.getpid()),"--install-root",str(install_root),
                "--state",str(self.state_path),"--server",self.server_url,
                "--asset",p["asset"],"--manifest",p["manifest"],"--signature",p["signature"]]
        flags=0
        if os.name=="nt":
            flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
        subprocess.Popen(cmd,close_fds=True,creationflags=flags)
        return True
