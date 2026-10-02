import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import secrets
import tkinter as tk
import winreg
from pathlib import Path
from tkinter import messagebox

APP_ID="EnigmaVolunteerGrid"
APP_NAME="Enigma Volunteer Grid"
VERSION="0.3.0"
RUN_KEY=r"Software\Microsoft\Windows\CurrentVersion\Run"
UNINSTALL_BASE=r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
PAYLOAD_NAMES=("EnigmaGrid.exe","EnigmaGridWorker.exe","EnigmaGridUpdater.exe")

def frozen_root():
    return Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parent))

def default_install():
    return Path(os.environ["LOCALAPPDATA"])/"Programs"/APP_ID

def default_data():
    return Path(os.environ["LOCALAPPDATA"])/APP_ID

def quote(path):
    return '"'+str(path)+'"'

def payload_manifest():
    p=frozen_root()/"installer_payload.json"
    return json.loads(p.read_text(encoding="utf-8"))

def verify_payload():
    root=frozen_root()/"payload";m=payload_manifest()
    for name in PAYLOAD_NAMES:
        p=root/name;meta=m["files"][name]
        if p.stat().st_size!=int(meta["size"]):raise ValueError("payload_size:"+name)
        if hashlib.sha256(p.read_bytes()).hexdigest()!=meta["sha256"]:
            raise ValueError("payload_hash:"+name)
    return root,m

def reg_set(key_path,name,value,kind=winreg.REG_SZ):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,key_path) as k:
        winreg.SetValueEx(k,name,0,kind,value)

def reg_delete_tree(path):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,path,0,winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:child=winreg.EnumKey(k,0);reg_delete_tree(path+"\\"+child)
                except OSError:break
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER,path)
    except FileNotFoundError:pass

def reg_delete_value(path,name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,path,0,winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k,name)
    except (FileNotFoundError,OSError):pass

def write_control(data,stop=True):
    data.mkdir(parents=True,exist_ok=True)
    (data/"control.json").write_text(json.dumps({
        "paused":False,"stop_requested":bool(stop),"check_update":False}),encoding="utf-8")
    (data/"update-exit").write_text("1",encoding="ascii")

def replace_retry(src,dst,timeout=120):
    end=time.time()+timeout
    while time.time()<end:
        try:
            tmp=dst.with_suffix(dst.suffix+".new")
            shutil.copy2(src,tmp);os.replace(tmp,dst);return
        except PermissionError:time.sleep(.5)
    raise TimeoutError("Application is still busy: "+dst.name)

def register_install(install,data,app_id=APP_ID):
    setup=install/"EnigmaGridSetup.exe"
    tray=install/"EnigmaGrid.exe"
    reg_set(RUN_KEY,app_id,quote(tray))
    u=UNINSTALL_BASE+"\\"+app_id
    reg_set(u,"DisplayName",APP_NAME)
    reg_set(u,"DisplayVersion",VERSION)
    reg_set(u,"Publisher","Enigma Volunteer Grid")
    reg_set(u,"InstallLocation",str(install))
    reg_set(u,"DisplayIcon",str(tray))
    extra="" if app_id==APP_ID else f' --app-id "{app_id}" --install-dir "{install}" --data-dir "{data}"'
    reg_set(u,"UninstallString",quote(setup)+" --uninstall"+extra)
    reg_set(u,"QuietUninstallString",quote(setup)+" --uninstall --quiet"+extra)
    reg_set(u,"NoModify",1,winreg.REG_DWORD);reg_set(u,"NoRepair",1,winreg.REG_DWORD)

def install(args):
    payload,manifest=verify_payload()
    install=Path(args.install_dir or default_install()).resolve()
    data=Path(args.data_dir or default_data()).resolve()
    install.mkdir(parents=True,exist_ok=True)
    if any((install/x).exists() for x in PAYLOAD_NAMES):
        write_control(data,True);time.sleep(4)
    for name in PAYLOAD_NAMES:
        replace_retry(payload/name,install/name)
    if not getattr(sys,"frozen",False):raise RuntimeError("installer must run frozen")
    replace_retry(Path(sys.executable),install/"EnigmaGridSetup.exe")
    register_install(install,data,args.app_id)
    if not args.no_launch:
        subprocess.Popen([str(install/"EnigmaGrid.exe")],close_fds=True)
    return install

def stale_cleanup_helpers():
    temp=Path(tempfile.gettempdir())
    for p in temp.glob("EnigmaGridCleanup-*.exe"):
        try:p.unlink()
        except Exception:pass

def prepare_cleanup_helper(install):
    source=install/"EnigmaGridUpdater.exe"
    if not source.exists():raise FileNotFoundError(source)
    runner=Path(tempfile.gettempdir())/("EnigmaGridCleanup-"+secrets.token_hex(8)+".exe")
    shutil.copy2(source,runner)
    return runner

def launch_cleanup_helper(runner,install):
    flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
    subprocess.Popen([str(runner),"--cleanup-install",str(install),
                      "--wait-pid",str(os.getpid())],
                     creationflags=flags,close_fds=True)

def uninstall(args):
    install=Path(args.install_dir or default_install()).resolve()
    data=Path(args.data_dir or default_data()).resolve()
    reg_delete_value(RUN_KEY,args.app_id)
    reg_delete_tree(UNINSTALL_BASE+"\\"+args.app_id)
    if data.exists():write_control(data,True)
    time.sleep(5)
    runner=prepare_cleanup_helper(install)
    for name in PAYLOAD_NAMES:
        try:(install/name).unlink()
        except FileNotFoundError:pass
        except PermissionError:pass
    if args.purge_data:shutil.rmtree(data,ignore_errors=True)
    launch_cleanup_helper(runner,install)
    return True

def confirm(text,quiet):
    if quiet:return True
    root=tk.Tk();root.withdraw()
    try:return messagebox.askyesno(APP_NAME,text)
    finally:root.destroy()

def info(text,quiet):
    if quiet:return
    root=tk.Tk();root.withdraw()
    try:messagebox.showinfo(APP_NAME,text)
    finally:root.destroy()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--uninstall",action="store_true")
    ap.add_argument("--quiet",action="store_true")
    ap.add_argument("--purge-data",action="store_true")
    ap.add_argument("--no-launch",action="store_true")
    ap.add_argument("--install-dir",default="")
    ap.add_argument("--data-dir",default="")
    ap.add_argument("--app-id",default=APP_ID)
    args=ap.parse_args()
    stale_cleanup_helpers()
    try:
        if args.uninstall:
            if not confirm("Remove Enigma Volunteer Grid from this PC?",args.quiet):return 1
            uninstall(args);info("Enigma Volunteer Grid was removed.",args.quiet);return 0
        if not confirm("Install Enigma Volunteer Grid for this Windows user?",args.quiet):return 1
        target=install(args)
        info("Installation complete.\n\nInstalled in:\n"+str(target),args.quiet);return 0
    except Exception as e:
        if args.quiet:
            print("ERROR",repr(e),file=sys.stderr)
        else:
            root=tk.Tk();root.withdraw();messagebox.showerror(APP_NAME,str(e));root.destroy()
        return 2

if __name__=="__main__":raise SystemExit(main())
