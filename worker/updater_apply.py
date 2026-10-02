import argparse
import base64
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

def wait_parent(pid,timeout=120):
    if os.name=="nt":
        SYNCHRONIZE=0x00100000
        h=ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE,False,int(pid))
        if h:
            ctypes.windll.kernel32.WaitForSingleObject(h,int(timeout*1000))
            ctypes.windll.kernel32.CloseHandle(h)
        return
    end=time.time()+timeout
    while time.time()<end:
        try:os.kill(pid,0);time.sleep(.5)
        except OSError:return

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
    if h.hexdigest().lower()!=str(m.get("sha256","")).lower():raise ValueError("asset_hash_mismatch")
    if size!=int(m.get("size",0)):raise ValueError("asset_size_mismatch")
    return m

def safe_extract(asset,dest):
    total=0;max_total=1024*1024*1024
    with zipfile.ZipFile(asset) as z:
        for info in z.infolist():
            name=info.filename.replace("\\","/")
            parts=[p for p in name.split("/") if p]
            if not parts:continue
            if parts[0] not in {"worker","solver"}:raise ValueError("unexpected_archive_root")
            if any(p in {".",".."} or ":" in p or p.endswith((" ",".")) for p in parts):
                raise ValueError("unsafe_archive_path")
            if name.startswith("/"):raise ValueError("unsafe_archive_path")
            mode=(info.external_attr>>16)&0o170000
            if mode==0o120000:raise ValueError("archive_symlink_rejected")
            total+=max(0,int(info.file_size))
            if total>max_total:raise ValueError("archive_uncompressed_too_large")
        z.extractall(dest)

def preflight(stage):
    files=[stage/"worker"/x for x in ("worker.py","updater.py","updater_apply.py")]
    if not all(x.exists() for x in files):raise ValueError("update_missing_required_worker_files")
    r=subprocess.run([sys.executable,"-m","py_compile",*[str(x) for x in files]],
                     stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,timeout=60)
    if r.returncode!=0:raise ValueError("update_preflight_failed:"+r.stderr[-500:])
def spawn_worker(root,state,server):
    cmd=[sys.executable,str(root/"worker"/"worker.py"),"--state",str(state),"--server",server]
    flags=0
    if os.name=="nt":flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
    return subprocess.Popen(cmd,creationflags=flags,close_fds=True)

def read_health(path):
    try:return json.loads(path.read_text(encoding="utf-8"))
    except Exception:return {}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--parent-pid",type=int,required=True)
    ap.add_argument("--install-root",required=True)
    ap.add_argument("--state",required=True)
    ap.add_argument("--server",required=True)
    ap.add_argument("--asset",required=True)
    ap.add_argument("--manifest",required=True)
    ap.add_argument("--signature",required=True)
    a=ap.parse_args()
    root=Path(a.install_root).resolve();state=Path(a.state).resolve()
    manifest=verify(a.manifest,a.signature,root/"worker"/"update_public_key.json",a.asset)
    target=str(manifest["version"])
    import re
    if not re.fullmatch(r"\d+\.\d+\.\d+",target):raise ValueError("invalid_update_version")
    stage=root/(".update-stage-"+target)
    backup=root/".update-backup"
    if stage.exists():shutil.rmtree(stage,ignore_errors=True)
    stage.mkdir(parents=True)
    safe_extract(a.asset,stage);preflight(stage)
    wait_parent(a.parent_pid)
    if backup.exists():shutil.rmtree(backup,ignore_errors=True)
    backup.mkdir()
    health=root/".worker-health.json"
    try:health.unlink()
    except Exception:pass
    moved=[]
    try:
        for name in ("worker","solver"):
            src=root/name;dst=backup/name
            if src.exists():
                src.replace(dst);moved.append(name)
            (stage/name).replace(src)
        proc=spawn_worker(root,state,a.server)
        ok=False;deadline=time.time()+30
        while time.time()<deadline:
            h=read_health(health)
            if h.get("version")==target:
                ok=True;break
            if proc.poll() is not None:break
            time.sleep(.5)
        if not ok:
            try:proc.terminate()
            except Exception:pass
            for name in ("worker","solver"):
                cur=root/name
                if cur.exists():shutil.rmtree(cur,ignore_errors=True)
                old=backup/name
                if old.exists():old.replace(cur)
            spawn_worker(root,state,a.server)
            raise SystemExit(4)
        shutil.rmtree(stage,ignore_errors=True)
    except Exception:
        for name in ("worker","solver"):
            cur=root/name;old=backup/name
            if cur.exists() and old.exists():shutil.rmtree(cur,ignore_errors=True)
            if old.exists() and not cur.exists():old.replace(cur)
        raise

if __name__=="__main__":main()
