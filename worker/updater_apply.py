import argparse
import base64
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

FROZEN_FILES={"EnigmaGrid.exe","EnigmaGridWorker.exe","EnigmaGridUpdater.exe","release_config.json","SHA256SUMS.txt"}

def wait_parent(pid,timeout=120):
    if os.name=="nt":
        h=ctypes.windll.kernel32.OpenProcess(0x00100000,False,int(pid))
        if h:
            ctypes.windll.kernel32.WaitForSingleObject(h,int(timeout*1000))
            ctypes.windll.kernel32.CloseHandle(h)
        return

    end=time.time()+timeout
    while time.time()<end:
        try:os.kill(pid,0);time.sleep(.5)
        except OSError:return

def public_key_path(root):
    if getattr(sys,"frozen",False):
        base=Path(getattr(sys,"_MEIPASS",Path(sys.executable).parent))
        return base/"worker"/"update_public_key.json"
    return root/"worker"/"update_public_key.json"

def verify(manifest_path,sig_path,pub_path,asset_path):
    data=Path(manifest_path).read_bytes()
    sig=base64.b64decode(Path(sig_path).read_text(encoding="ascii").strip(),validate=True)
    pub=json.loads(Path(pub_path).read_text(encoding="utf-8"))
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub["public_key_hex"])).verify(sig,data)
    m=json.loads(data.decode("utf-8"))
    h=hashlib.sha256();size=0
    with open(asset_path,"rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b:break
            h.update(b);size+=len(b)

    if h.hexdigest().lower()!=str(m.get("sha256","")).lower():
        raise ValueError("asset_hash_mismatch")
    if size!=int(m.get("size",0)):raise ValueError("asset_size_mismatch")
    return m

def safe_extract(asset,dest):
    total=0;max_total=1024*1024*1024
    with zipfile.ZipFile(asset) as z:
        infos=z.infolist()
        names=[i.filename.replace("\\","/") for i in infos if i.filename.strip("/")]
        frozen=any("/" not in n.strip("/") and Path(n).name=="EnigmaGridWorker.exe" for n in names)
        for info in infos:
            name=info.filename.replace("\\","/")
            parts=[p for p in name.split("/") if p]
            if not parts:continue
            if any(p in {".",".."} or ":" in p or p.endswith((" ",".")) for p in parts):
                raise ValueError("unsafe_archive_path")
            if name.startswith("/"):raise ValueError("unsafe_archive_path")
            mode=(info.external_attr>>16)&0o170000
            if mode==0o120000:raise ValueError("archive_symlink_rejected")
            if frozen:
                if len(parts)!=1 or parts[0] not in FROZEN_FILES:
                    raise ValueError("unexpected_frozen_archive_entry")

            elif parts[0] not in {"worker","solver"}:
                raise ValueError("unexpected_archive_root")
            total+=max(0,int(info.file_size))
            if total>max_total:raise ValueError("archive_uncompressed_too_large")
        z.extractall(dest)
    if frozen:
        required={"EnigmaGrid.exe","EnigmaGridWorker.exe","EnigmaGridUpdater.exe","release_config.json"}
        if not required.issubset({p.name for p in dest.iterdir() if p.is_file()}):
            raise ValueError("frozen_update_missing_required_files")
        cfg=json.loads((dest/"release_config.json").read_text(encoding="utf-8"))
        if not str(cfg.get("server_url","")).startswith("https://"):
            raise ValueError("invalid_release_server_url")
        return "frozen"
    return "source"

def preflight(stage,kind):
    if kind=="frozen":
        files=[stage/x for x in ("EnigmaGrid.exe","EnigmaGridWorker.exe","EnigmaGridUpdater.exe")]
        for p in files:
            if not p.exists() or p.stat().st_size<100000 or p.read_bytes()[:2]!=b"MZ":
                raise ValueError("invalid_frozen_executable:"+p.name)
        r=subprocess.run([str(stage/"EnigmaGridWorker.exe"),"--self-test"],
                         stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=120)
        if r.returncode!=0:raise ValueError("frozen_worker_self_test_failed")
        return
    files=[stage/"worker"/x for x in ("worker.py","updater.py","updater_apply.py")]

    if not all(x.exists() for x in files):raise ValueError("update_missing_required_worker_files")
    r=subprocess.run([sys.executable,"-m","py_compile",*[str(x) for x in files]],
                     stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,timeout=60)
    if r.returncode!=0:raise ValueError("update_preflight_failed:"+r.stderr[-500:])

def spawn_worker(root,state,server,kind):
    if kind=="frozen":
        cmd=[str(root/"EnigmaGridWorker.exe"),"--state",str(state),"--server",server]
    else:
        cmd=[sys.executable,str(root/"worker"/"worker.py"),"--state",str(state),"--server",server]
    flags=getattr(subprocess,"CREATE_NO_WINDOW",0) if os.name=="nt" else 0
    return subprocess.Popen(cmd,creationflags=flags,close_fds=True,
                            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def spawn_tray(root,kind):
    if kind!="frozen":return None
    flags=getattr(subprocess,"CREATE_NO_WINDOW",0) if os.name=="nt" else 0
    return subprocess.Popen([str(root/"EnigmaGrid.exe")],creationflags=flags,close_fds=True,
                            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def read_health(path):
    try:return json.loads(path.read_text(encoding="utf-8"))
    except Exception:return {}

def replace_with_retry(src,dst,timeout=15):
    end=time.time()+timeout;last=None

    while time.time()<end:
        try:
            if dst.exists():
                if dst.is_dir():shutil.rmtree(dst)
                else:dst.unlink()
            src.replace(dst);return
        except Exception as e:
            last=e;time.sleep(.4)
    raise last or RuntimeError("replace_timeout")

def stop_tray_for_update(state):
    marker=state.with_name("update-exit")
    marker.write_text("1",encoding="ascii")
    time.sleep(4)

def rollback_frozen(root,backup,names):
    for name in names:
        cur=root/name;old=backup/name
        try:
            if cur.exists():cur.unlink()
        except Exception:pass
        if old.exists():replace_with_retry(old,cur,10)

def schedule_self_delete():
    if os.name!="nt" or not getattr(sys,"frozen",False):return
    import tempfile,secrets
    env=os.environ.copy();env["EG_SELF_DELETE"]=str(Path(sys.executable).resolve())
    batch=Path(tempfile.gettempdir())/("EnigmaGridCleanup-"+secrets.token_hex(8)+".cmd")
    batch.write_text("@echo off\r\n"
        "for /L %%i in (1,1,30) do (\r\n"
        "  del /f /q \"%EG_SELF_DELETE%\" 2>nul\r\n"
        "  if not exist \"%EG_SELF_DELETE%\" goto done\r\n"
        "  ping 127.0.0.1 -n 2 >nul\r\n"
        ")\r\n"
        ":done\r\n"
        "del /f /q \"%~f0\"\r\n",encoding="ascii")
    flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
    subprocess.Popen(["cmd.exe","/d","/v:off","/c",str(batch)],
                     env=env,creationflags=flags,close_fds=True)

def cleanup_install(path,wait_pid=0,timeout=45):
    target=Path(path).resolve()
    if wait_pid:wait_parent(wait_pid,timeout=120)
    end=time.time()+timeout;last=None
    while time.time()<end:
        try:
            if target.exists():shutil.rmtree(target)
            schedule_self_delete();return 0
        except Exception as e:
            last=e;time.sleep(.5)
    if last:raise last
    return 0

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--cleanup-install",default="")
    ap.add_argument("--wait-pid",type=int,default=0)
    ap.add_argument("--parent-pid",type=int)
    ap.add_argument("--install-root",default="")
    ap.add_argument("--state",default="")
    ap.add_argument("--server",default="")
    ap.add_argument("--asset",default="")
    ap.add_argument("--manifest",default="")
    ap.add_argument("--signature",default="")
    ap.add_argument("--health-timeout",type=int,default=45)
    a=ap.parse_args()
    if a.cleanup_install:return cleanup_install(a.cleanup_install,a.wait_pid)
    required=[a.parent_pid,a.install_root,a.state,a.server,a.asset,a.manifest,a.signature]
    if any(x in (None,"") for x in required):ap.error("missing update arguments")
    root=Path(a.install_root).resolve();state=Path(a.state).resolve()

    manifest=verify(a.manifest,a.signature,public_key_path(root),a.asset)
    target=str(manifest["version"])
    if not re.fullmatch(r"\d+\.\d+\.\d+",target):raise ValueError("invalid_update_version")
    stage=state.parent/("update-stage-"+target)
    backup=state.parent/"update-backup"
    if stage.exists():shutil.rmtree(stage,ignore_errors=True)
    stage.mkdir(parents=True)
    kind=safe_extract(a.asset,stage);preflight(stage,kind)
    wait_parent(a.parent_pid)
    if backup.exists():shutil.rmtree(backup,ignore_errors=True)
    backup.mkdir()
    health=state.with_name("worker-health.json")
    try:health.unlink()
    except Exception:pass

    if kind=="frozen":stop_tray_for_update(state)
    try:
        if kind=="frozen":
            names=["EnigmaGrid.exe","EnigmaGridWorker.exe","EnigmaGridUpdater.exe","release_config.json"]
            for name in names:
                cur=root/name
                if cur.exists():replace_with_retry(cur,backup/name,15)
                replace_with_retry(stage/name,cur,15)
        else:
            names=["worker","solver"]
            for name in names:
                cur=root/name
                if cur.exists():replace_with_retry(cur,backup/name,15)
                replace_with_retry(stage/name,cur,15)

        proc=spawn_worker(root,state,a.server,kind)
        ok=False;deadline=time.time()+max(3,int(a.health_timeout))
        while time.time()<deadline:
            h=read_health(health)
            if h.get("version")==target:
                ok=True;break
            if proc.poll() is not None:break
            time.sleep(.5)
        if not ok:
            try:proc.terminate()
            except Exception:pass
            if kind=="frozen":rollback_frozen(root,backup,names)
            else:
                for name in names:
                    cur=root/name;old=backup/name
                    if cur.exists():shutil.rmtree(cur,ignore_errors=True)
                    if old.exists():replace_with_retry(old,cur,10)
            spawn_worker(root,state,a.server,kind)
            spawn_tray(root,kind)
            raise SystemExit(4)
        spawn_tray(root,kind)
        shutil.rmtree(stage,ignore_errors=True)
        shutil.rmtree(backup,ignore_errors=True)
    except Exception:
        if kind=="frozen":
            try:rollback_frozen(root,backup,["EnigmaGrid.exe","EnigmaGridWorker.exe","EnigmaGridUpdater.exe","release_config.json"])
            except Exception:pass
        raise

if __name__=="__main__":main()
