import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import pystray
from PIL import Image, ImageDraw

APP_NAME="Enigma Volunteer Grid"
APP_VERSION="0.3.0"

def install_root():
    if getattr(sys,"frozen",False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]

ROOT=install_root()
LOCAL=Path(os.environ.get("LOCALAPPDATA",Path.home()))/"EnigmaVolunteerGrid"
STATE=Path(os.environ.get("ENIGMA_GRID_STATE",LOCAL/"client.json"))
CONTROL=STATE.with_name("control.json")
HEALTH=STATE.with_name("worker-health.json")
UI_STATE=STATE.with_name("ui.json")

def atomic_json(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,separators=(",",":")),encoding="utf-8")
    tmp.replace(path)

def load_json(path,default):
    try:return json.loads(path.read_text(encoding="utf-8"))
    except Exception:return default

def worker_base_cmd():
    exe=ROOT/"EnigmaGridWorker.exe"
    if exe.exists():
        return [str(exe)]
    script=ROOT/"worker"/"worker.py"
    return [sys.executable,str(script)]

def run_worker(args,capture=False,timeout=120):
    flags=getattr(subprocess,"CREATE_NO_WINDOW",0) if os.name=="nt" else 0
    kw={"creationflags":flags,"close_fds":True}
    if capture:
        kw.update({"stdout":subprocess.PIPE,"stderr":subprocess.PIPE,"text":True})
    return subprocess.run(worker_base_cmd()+list(args),timeout=timeout,**kw)

def start_worker():
    flags=getattr(subprocess,"CREATE_NO_WINDOW",0) if os.name=="nt" else 0
    STATE.parent.mkdir(parents=True,exist_ok=True)
    log=open(STATE.with_name("worker.log"),"a",encoding="utf-8",buffering=1)
    return subprocess.Popen(worker_base_cmd()+["--state",str(STATE)],
                            creationflags=flags,close_fds=True,
                            stdout=log,stderr=log)

def control():
    return load_json(CONTROL,{"paused":False,"stop_requested":False,"check_update":False})

def save_control(**changes):
    obj=control();obj.update(changes);atomic_json(CONTROL,obj);return obj

def is_alive():
    h=load_json(HEALTH,{})
    try:return time.time()-float(h.get("heartbeat",0))<20
    except Exception:return False

def make_icon():
    im=Image.new("RGBA",(64,64),(12,18,32,255))
    d=ImageDraw.Draw(im)
    d.rounded_rectangle((8,8,56,56),radius=10,outline=(80,211,255,255),width=4)
    d.text((21,15),"E",fill=(235,240,250,255))
    return im

class App:
    def __init__(self):
        self.root=tk.Tk();self.root.title(APP_NAME);self.root.geometry("440x430")
        self.root.protocol("WM_DELETE_WINDOW",self.hide)
        self.worker_proc=None
        self.icon=None
        self.status_var=tk.StringVar(value="Starting…")
        self.cpu_var=tk.IntVar(value=50);self.gpu_var=tk.IntVar(value=0)
        self.server_var=tk.StringVar();self.name_var=tk.StringVar()
        self.code_var=tk.StringVar();self.setup_mode=not STATE.exists()
        self.build_ui()

    def build_ui(self):
        f=ttk.Frame(self.root,padding=18);f.pack(fill="both",expand=True)
        ttk.Label(f,text=APP_NAME,font=("Segoe UI",18,"bold")).pack(anchor="w")
        ttk.Label(f,textvariable=self.status_var).pack(anchor="w",pady=(2,14))
        if self.setup_mode:
            ttk.Label(f,text="Server HTTPS URL").pack(anchor="w")
            ttk.Entry(f,textvariable=self.server_var).pack(fill="x",pady=(2,8))
            ttk.Label(f,text="Contributor name").pack(anchor="w")
            ttk.Entry(f,textvariable=self.name_var).pack(fill="x",pady=(2,8))
            ttk.Label(f,text="Registration code (leave blank for public registration)").pack(anchor="w")
            ttk.Entry(f,textvariable=self.code_var,show="•").pack(fill="x",pady=(2,8))
        ttk.Label(f,text="CPU contribution").pack(anchor="w")
        ttk.Scale(f,from_=0,to=100,variable=self.cpu_var,orient="horizontal").pack(fill="x")
        self.cpu_label=ttk.Label(f);self.cpu_label.pack(anchor="e")
        ttk.Label(f,text="GPU contribution").pack(anchor="w",pady=(8,0))
        ttk.Scale(f,from_=0,to=100,variable=self.gpu_var,orient="horizontal").pack(fill="x")
        self.gpu_label=ttk.Label(f);self.gpu_label.pack(anchor="e")
        self.cpu_var.trace_add("write",lambda *_:self.update_labels())
        self.gpu_var.trace_add("write",lambda *_:self.update_labels())

        buttons=ttk.Frame(f);buttons.pack(fill="x",pady=(18,0))
        if self.setup_mode:
            ttk.Button(buttons,text="Join project",command=self.register).pack(side="left")
        else:
            ttk.Button(buttons,text="Save limits",command=self.save_limits).pack(side="left")
        ttk.Button(buttons,text="Pause / Resume",command=self.toggle_pause).pack(side="left",padx=8)
        ttk.Button(buttons,text="Check update",command=self.check_update).pack(side="left")
        ttk.Button(f,text="Stop safely and exit",command=self.stop_safe).pack(anchor="w",pady=(16,0))
        ttk.Label(f,text="Closing this window keeps the worker running in the tray.",
                  foreground="#666").pack(anchor="w",pady=(18,0))
        self.update_labels()

    def update_labels(self):
        self.cpu_label.config(text=f"{int(self.cpu_var.get())}%")
        self.gpu_label.config(text=f"{int(self.gpu_var.get())}%")

    def register(self):
        server=self.server_var.get().strip();name=self.name_var.get().strip()
        if not server or not name:
            return messagebox.showerror(APP_NAME,"Server and contributor name are required.")
        args=["--server",server,"--name",name,"--state",str(STATE),"--register-only",
              "--cpu-percent",str(int(self.cpu_var.get())),"--gpu-percent",str(int(self.gpu_var.get()))]
        code=self.code_var.get().strip()
        if code:args+=["--registration-code",code]

        self.status_var.set("Registering…")
        def job():
            try:
                r=run_worker(args,capture=True,timeout=180)
                if r.returncode:raise RuntimeError((r.stderr or r.stdout or "Registration failed")[-800:])
                atomic_json(UI_STATE,{"server":server,"name":name,
                    "cpu":int(self.cpu_var.get()),"gpu":int(self.gpu_var.get())})
                self.root.after(0,self.registration_ok)
            except Exception as e:self.root.after(0,lambda:messagebox.showerror(APP_NAME,str(e)))
        threading.Thread(target=job,daemon=True).start()

    def registration_ok(self):
        self.setup_mode=False;self.status_var.set("Registered")
        self.ensure_worker();messagebox.showinfo(APP_NAME,"Registration complete. Contribution has started.")
        self.hide()

    def save_limits(self):
        cpu=int(self.cpu_var.get());gpu=int(self.gpu_var.get())
        def job():
            r=run_worker(["--state",str(STATE),"--set-preferences",
                          "--cpu-percent",str(cpu),"--gpu-percent",str(gpu)],capture=True)
            if r.returncode:
                self.root.after(0,lambda:messagebox.showerror(APP_NAME,(r.stderr or r.stdout)[-800:]))
            else:
                ui=load_json(UI_STATE,{});ui.update({"cpu":cpu,"gpu":gpu});atomic_json(UI_STATE,ui)
        threading.Thread(target=job,daemon=True).start()

    def toggle_pause(self):
        c=control();save_control(paused=not c.get("paused",False),stop_requested=False)
        self.refresh_status()

    def check_update(self):
        save_control(check_update=True)
        self.status_var.set("Update check requested")

    def stop_safe(self):
        save_control(stop_requested=True,paused=False)
        self.status_var.set("Safe stop requested…")
        self.root.after(1200,self.quit_all)

    def ensure_worker(self):
        if not STATE.exists():return
        if not is_alive():
            try:self.worker_proc=start_worker()
            except Exception as e:self.status_var.set("Worker launch failed: "+str(e))

    def refresh_status(self):
        if not self.setup_mode:self.ensure_worker()
        c=control()
        if self.setup_mode:s="Setup required"
        elif c.get("stop_requested"):s="Stopping safely…"
        elif c.get("paused"):s="Paused"
        elif is_alive():s="Contributing"
        else:s="Starting worker…"
        self.status_var.set(s)
        self.root.after(3000,self.refresh_status)

    def show(self,*_):
        self.root.after(0,lambda:(self.root.deiconify(),self.root.lift(),self.root.focus_force()))

    def hide(self):
        self.root.withdraw()

    def tray_pause(self,*_):self.root.after(0,self.toggle_pause)
    def tray_update(self,*_):self.root.after(0,self.check_update)
    def tray_stop(self,*_):self.root.after(0,self.stop_safe)

    def quit_all(self):
        try:
            if self.icon:self.icon.stop()
        finally:self.root.destroy()

    def tray_thread(self):
        menu=pystray.Menu(
            pystray.MenuItem("Open controls",self.show,default=True),
            pystray.MenuItem("Pause / Resume",self.tray_pause),
            pystray.MenuItem("Check for update",self.tray_update),
            pystray.MenuItem("Stop safely and exit",self.tray_stop))
        self.icon=pystray.Icon("EnigmaVolunteerGrid",make_icon(),APP_NAME,menu)
        self.icon.run()

    def run(self):
        ui=load_json(UI_STATE,{})
        if ui:
            self.cpu_var.set(int(ui.get("cpu",50)));self.gpu_var.set(int(ui.get("gpu",0)))
            self.server_var.set(str(ui.get("server","")));self.name_var.set(str(ui.get("name","")))
        threading.Thread(target=self.tray_thread,daemon=True).start()
        if not self.setup_mode:self.root.withdraw()
        self.refresh_status();self.root.mainloop()

def self_test():
    assert worker_base_cmd()
    p=Path(os.environ.get("TEMP","."))/"enigma-tray-control-test.json"
    atomic_json(p,{"paused":True});assert load_json(p,{})["paused"] is True;p.unlink()
    print("TRAY_SELF_TEST_OK",APP_VERSION)

if __name__=="__main__":
    if "--self-test" in sys.argv:self_test()
    else:App().run()
