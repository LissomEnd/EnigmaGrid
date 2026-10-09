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
from file_state import atomic_write

APP_ID="EnigmaVolunteerGrid"
APP_NAME="Enigma Volunteer Grid"
VERSION="0.5.0"
RUN_KEY=r"Software\Microsoft\Windows\CurrentVersion\Run"
UNINSTALL_BASE=r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
PAYLOAD_NAMES=("EnigmaGrid.exe","EnigmaGridWorker.exe","EnigmaGridUpdater.exe","release_config.json","LICENSES.txt")

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

def read_control(data):
    try:control=json.loads((data/'control.json').read_text(encoding='utf-8'))
    except FileNotFoundError:return {'paused':False,'stop_requested':False,'check_update':False}
    if not isinstance(control,dict):raise ValueError('Invalid existing control settings')
    return control


def restore_control(data,previous):
    control=read_control(data)
    # Retain temperature/settings changes made while the worker was draining.
    for key in ('paused','stop_requested','check_update'):
        control[key]=previous.get(key,False)
    atomic_write(data/'control.json',json.dumps(control).encode('utf-8'))


def write_control(data,stop=True):
    data.mkdir(parents=True,exist_ok=True)
    control=read_control(data)
    control['stop_requested']=bool(stop)
    atomic_write(data/'control.json',json.dumps(control).encode('utf-8'))
    atomic_write(data/'update-exit',b'1')

def wait_worker_stopped(data,timeout=600):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            h=json.loads((data/"worker-health.json").read_text())
            if h.get("status") in {"stopped","disabled"}:return
            if time.time()-float(h.get("heartbeat",0))>50:return
        except (FileNotFoundError,ValueError):return
        time.sleep(.5)
    raise TimeoutError("The worker is still finishing a job. Wait for it to stop, then try again.")

def shortcut(install,app_id,remove=False):
    folder=Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs'
    link=folder/(app_id+'.lnk')
    if remove:
        link.unlink(missing_ok=True);return
    env=os.environ.copy();env['EG_LINK']=str(link);env['EG_APP']=str(install/'EnigmaGrid.exe')
    script="$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut($env:EG_LINK); $s.TargetPath=$env:EG_APP; $s.Save()"
    subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],env=env,
                   creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=True,timeout=30)

def replace_retry(src,dst,timeout=120):
    end=time.time()+timeout
    while time.time()<end:
        try:
            tmp=dst.with_suffix(dst.suffix+".new")
            shutil.copy2(src,tmp);os.replace(tmp,dst);return
        except PermissionError:time.sleep(.5)
    raise TimeoutError("Application is still busy: "+dst.name)

def register_install(install,data,app_id=APP_ID,autostart=True):
    setup=install/"EnigmaGridSetup.exe"
    tray=install/"EnigmaGrid.exe"
    if autostart:reg_set(RUN_KEY,app_id,quote(tray)+' --background')
    else:reg_delete_value(RUN_KEY,app_id)
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
    size_kb=sum(p.stat().st_size for p in install.glob("*") if p.is_file())//1024
    reg_set(u,"EstimatedSize",int(size_kb),winreg.REG_DWORD)
    reg_set(u,"URLInfoAbout","https://github.com/LissomEnd/EnigmaGrid")
    shortcut(install,app_id)

def install(args):
    payload,manifest=verify_payload()
    install=Path(args.install_dir or default_install()).resolve()
    data=Path(args.data_dir or default_data()).resolve()
    previous_control=read_control(data)
    install.mkdir(parents=True,exist_ok=True)
    if any((install/x).exists() for x in PAYLOAD_NAMES):
        write_control(data,True);wait_worker_stopped(data);time.sleep(2)
    for name in PAYLOAD_NAMES:
        replace_retry(payload/name,install/name)
    if not getattr(sys,"frozen",False):raise RuntimeError("installer must run frozen")
    replace_retry(Path(sys.executable),install/"EnigmaGridSetup.exe")
    register_install(install,data,args.app_id,not args.no_autostart)
    (install/'enigmagrid-install.json').write_text(json.dumps({
        'product':'EnigmaVolunteerGrid','directory':str(install)}),encoding='utf-8')
    (data/'update-exit').unlink(missing_ok=True)
    restore_control(data,previous_control)
    if not args.no_launch:
        subprocess.Popen([str(install/"EnigmaGrid.exe")],close_fds=True)
    return install

def stale_cleanup_helpers():
    temp=Path(tempfile.gettempdir())
    for pattern in ("EnigmaGridCleanup-*.exe","EnigmaGridCleanup-*.cmd"):
        for p in temp.glob(pattern):
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
    if data.exists():write_control(data,True)
    wait_worker_stopped(data);time.sleep(3)
    reg_delete_value(RUN_KEY,args.app_id)
    reg_delete_tree(UNINSTALL_BASE+"\\"+args.app_id)
    shortcut(install,args.app_id,remove=True)
    runner=prepare_cleanup_helper(install)
    for name in PAYLOAD_NAMES:
        try:(install/name).unlink()
        except FileNotFoundError:pass
        except PermissionError:pass
    if args.purge_data:shutil.rmtree(data,ignore_errors=True)
    launch_cleanup_helper(runner,install)
    return True

def styled_window(title,height=430):
    w=tk.Tk();w.title(title);w.geometry(f"580x{height}");w.resizable(False,False)
    w.configure(bg="#0b1020")
    try:w.iconbitmap(str(frozen_root()/"payload"/"EnigmaGrid.exe"))
    except Exception:pass
    return w

def heading(parent,title,subtitle):
    tk.Label(parent,text="ENIGMA",bg="#0b1020",fg="#55d6ff",
             font=("Segoe UI",10,"bold")).pack(anchor="w")
    tk.Label(parent,text=title,bg="#0b1020",fg="#f4f7fb",
             font=("Segoe UI",23,"bold")).pack(anchor="w",pady=(4,4))
    tk.Label(parent,text=subtitle,bg="#0b1020",fg="#98a6c2",
             font=("Segoe UI",10),wraplength=510,justify="left").pack(anchor="w")

def install_ui(args):
    w=styled_window("Install "+APP_NAME,460);result={"code":1}
    f=tk.Frame(w,bg="#0b1020");f.pack(fill="both",expand=True,padx=28,pady=24)
    heading(f,APP_NAME,"Volunteer computing for the P1030680 Naval Enigma M4 search.")
    card=tk.Frame(f,bg="#131c31",highlightbackground="#263653",highlightthickness=1)
    card.pack(fill="x",pady=20);inner=tk.Frame(card,bg="#131c31");inner.pack(fill="x",padx=18,pady=16)
    for text in ("Installs only for your Windows account - no administrator rights.",
                 "You control CPU/GPU usage and can pause or stop at any time.",
                 "Updates are signature-verified and applied only between jobs."):
        tk.Label(inner,text="- "+text,bg="#131c31",fg="#d5deee",
                 font=("Segoe UI",10),anchor="w").pack(fill="x",pady=3)
    auto=tk.BooleanVar(value=True);launch=tk.BooleanVar(value=True)
    for text,var in (("Start with Windows",auto),("Open Enigma Volunteer Grid after installation",launch)):
        tk.Checkbutton(f,text=text,variable=var,bg="#0b1020",fg="#f4f7fb",
                       selectcolor="#18233c",activebackground="#0b1020",
                       activeforeground="#f4f7fb").pack(anchor="w",pady=3)
    status=tk.StringVar(value="Ready to install");tk.Label(f,textvariable=status,bg="#0b1020",
        fg="#98a6c2",font=("Segoe UI",9)).pack(anchor="w",pady=(12,8))
    row=tk.Frame(f,bg="#0b1020");row.pack(fill="x")
    cancel=tk.Button(row,text="Cancel",command=w.destroy,bg="#18233c",fg="#f4f7fb",
                     relief="flat",padx=18,pady=9)
    cancel.pack(side="right")
    install_btn=tk.Button(row,text="Install",bg="#6857e8",fg="white",relief="flat",
                          padx=22,pady=9)
    install_btn.pack(side="right",padx=(0,8))
    def begin():
        args.no_autostart=not auto.get();args.no_launch=not launch.get()
        install_btn.config(state="disabled");cancel.config(state="disabled");status.set("Installing verified components...")
        def job():
            try:
                target=install(args);result["code"]=0
                w.after(0,lambda:(status.set("Installation complete"),
                    messagebox.showinfo(APP_NAME,"Installation complete.\n\nInstalled in:\n"+str(target),parent=w),
                    w.destroy()))
            except Exception as e:
                w.after(0,lambda msg=str(e):messagebox.showerror(APP_NAME,msg,parent=w))
                w.after(0,lambda:(install_btn.config(state="normal"),cancel.config(state="normal"),status.set("Installation failed")))
        __import__("threading").Thread(target=job,daemon=True).start()
    install_btn.config(command=begin);w.mainloop();return result["code"]

def uninstall_ui(args):
    w=styled_window("Remove "+APP_NAME,340);result={"code":1}
    f=tk.Frame(w,bg="#0b1020");f.pack(fill="both",expand=True,padx=28,pady=24)
    heading(f,"Remove Enigma Volunteer Grid","Contribution will stop safely before installed files are removed.")
    purge=tk.BooleanVar(value=False)
    tk.Checkbutton(f,text="Also delete my local contributor identity and settings",variable=purge,
                   bg="#0b1020",fg="#f4f7fb",selectcolor="#18233c",
                   activebackground="#0b1020",activeforeground="#f4f7fb").pack(anchor="w",pady=(24,8))
    tk.Label(f,text="Leave this unchecked if you may reinstall and want to keep the same contributor identity.",
             bg="#0b1020",fg="#98a6c2",wraplength=510,justify="left").pack(anchor="w")
    status=tk.StringVar(value="");tk.Label(f,textvariable=status,bg="#0b1020",fg="#98a6c2").pack(anchor="w",pady=(15,8))
    row=tk.Frame(f,bg="#0b1020");row.pack(fill="x")
    tk.Button(row,text="Cancel",command=w.destroy,bg="#18233c",fg="#f4f7fb",
              relief="flat",padx=18,pady=9).pack(side="right")
    remove=tk.Button(row,text="Remove",bg="#b6455f",fg="white",relief="flat",padx=22,pady=9)
    remove.pack(side="right",padx=(0,8))
    def begin():
        args.purge_data=purge.get();remove.config(state="disabled");status.set("Stopping safely and removing files...")
        def job():
            try:
                uninstall(args);result["code"]=0
                w.after(0,lambda:(messagebox.showinfo(APP_NAME,"Enigma Volunteer Grid was removed.",parent=w),w.destroy()))
            except Exception as e:
                w.after(0,lambda msg=str(e):messagebox.showerror(APP_NAME,msg,parent=w))
                w.after(0,lambda:remove.config(state="normal"))
        __import__("threading").Thread(target=job,daemon=True).start()
    remove.config(command=begin);w.mainloop();return result["code"]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--uninstall",action="store_true")
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--quiet",action="store_true")
    ap.add_argument("--purge-data",action="store_true")
    ap.add_argument("--no-launch",action="store_true")
    ap.add_argument("--no-autostart",action="store_true")
    ap.add_argument("--install-dir",default="")
    ap.add_argument("--data-dir",default="")
    ap.add_argument("--app-id",default=APP_ID)
    args=ap.parse_args()
    stale_cleanup_helpers()
    if args.self_test:
        verify_payload();return 0
    try:
        if args.quiet:
            if args.uninstall:uninstall(args)
            else:install(args)
            return 0
        return uninstall_ui(args) if args.uninstall else install_ui(args)
    except Exception as e:
        if args.quiet:print("ERROR",repr(e),file=sys.stderr)
        else:
            root=tk.Tk();root.withdraw();messagebox.showerror(APP_NAME,str(e));root.destroy()
        return 2

if __name__=="__main__":raise SystemExit(main())
