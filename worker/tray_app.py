import json

import math

import os

import subprocess

import sys

import threading

import time

import tkinter as tk

import webbrowser

from pathlib import Path

from tkinter import messagebox, ttk

from file_state import atomic_write
from summary_cache import read_cached_summary

try:

    import winreg

except ImportError:

    winreg=None

import pystray

from PIL import Image, ImageDraw



APP_NAME="Enigma Volunteer Grid"

APP_VERSION="0.5.0"

BG="#0b1020";CARD="#131c31";CARD2="#18233c";TEXT="#f4f7fb";MUTED="#98a6c2"

ACCENT="#55d6ff";ACCENT2="#7768ff";GREEN="#62d99b";AMBER="#f4b860";RED="#ff6b7a"



def install_root():

    if getattr(sys,"frozen",False):

        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parents[1]



ROOT=install_root()

SOURCE_ROOT=Path(__file__).resolve().parents[1]

LOCAL=Path(os.environ.get("LOCALAPPDATA",Path.home()))/"EnigmaVolunteerGrid"

STATE=Path(os.environ.get("ENIGMA_GRID_STATE",LOCAL/"client.json"))

CONTROL=STATE.with_name("control.json")

HEALTH=STATE.with_name("worker-health.json")

UI_STATE=STATE.with_name("ui.json")

SHOW_REQUEST=STATE.with_name("show-window")

PROJECT_URL="https://github.com/LissomEnd/EnigmaGrid"

RUN_KEY=r"Software\Microsoft\Windows\CurrentVersion\Run"

RUN_NAME="EnigmaVolunteerGrid"



def atomic_json(path,obj):

    atomic_write(path,json.dumps(obj,separators=(",",":")).encode("utf-8"))



def load_json(path,default):

    try:return json.loads(path.read_text(encoding="utf-8"))

    except Exception:return default



def release_config():

    override=os.environ.get("ENIGMA_GRID_SERVER","").strip()

    candidates=[ROOT/"release_config.json",SOURCE_ROOT/"worker"/"release_config.json"]

    cfg={}

    for p in candidates:

        if p.exists():

            cfg=load_json(p,{})

            if cfg:break

    if override:cfg["server_url"]=override

    return cfg



def server_url():

    return str(release_config().get("server_url","")).strip().rstrip("/")



def worker_base_cmd():

    exe=ROOT/"EnigmaGridWorker.exe"

    return [str(exe)] if exe.exists() else [sys.executable,str(SOURCE_ROOT/"worker"/"worker.py")]



def run_worker(args,capture=False,timeout=180):

    flags=getattr(subprocess,"CREATE_NO_WINDOW",0) if os.name=="nt" else 0

    kw={"creationflags":flags,"close_fds":True}

    if capture:kw.update({"stdout":subprocess.PIPE,"stderr":subprocess.PIPE,"text":True})

    return subprocess.run(worker_base_cmd()+list(args),timeout=timeout,**kw)



def start_worker():

    flags=getattr(subprocess,"CREATE_NO_WINDOW",0) if os.name=="nt" else 0

    STATE.parent.mkdir(parents=True,exist_ok=True)

    log=open(STATE.with_name("worker.log"),"a",encoding="utf-8",buffering=1)

    return subprocess.Popen(worker_base_cmd()+["--state",str(STATE)],

        creationflags=flags,close_fds=True,stdout=log,stderr=log)



def control():

    obj=load_json(CONTROL,{})

    try:cpu=max(55,min(95,int(obj.get("max_cpu_temp_c",80))))

    except Exception:cpu=80

    try:gpu=max(50,min(90,int(obj.get("max_gpu_temp_c",75))))

    except Exception:gpu=75

    return {"paused":bool(obj.get("paused",False)),"stop_requested":bool(obj.get("stop_requested",False)),

            "check_update":bool(obj.get("check_update",False)),"max_cpu_temp_c":cpu,"max_gpu_temp_c":gpu}



def save_control(**changes):

    obj=control();obj.update(changes);atomic_json(CONTROL,obj);return obj



def is_alive():

    h=load_json(HEALTH,{})

    try:return h.get("status") not in {"stopped","disabled"} and time.time()-float(h.get("heartbeat",0))<45

    except Exception:return False



def get_autostart():

    if not winreg:return False

    try:

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,RUN_KEY) as k:

            return bool(winreg.QueryValueEx(k,RUN_NAME)[0])

    except OSError:return False



def set_autostart(enabled):

    if not winreg:return

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,RUN_KEY) as k:

        if enabled:

            exe=ROOT/"EnigmaGrid.exe"

            winreg.SetValueEx(k,RUN_NAME,0,winreg.REG_SZ,f'"{exe}" --background')

        else:

            try:winreg.DeleteValue(k,RUN_NAME)

            except FileNotFoundError:pass

            except OSError:pass



def make_icon():

    im=Image.new("RGBA",(64,64),(11,16,32,255));d=ImageDraw.Draw(im)

    d.ellipse((7,7,57,57),outline=(85,214,255,255),width=4)

    d.ellipse((17,17,47,47),outline=(119,104,255,255),width=3)

    for x,y in [(32,10),(50,32),(32,54),(14,32)]:

        d.ellipse((x-3,y-3,x+3,y+3),fill=(244,247,251,255))

    d.text((26,21),"E",fill=(244,247,251,255))

    return im



def fmt(n):

    try:return f"{int(n):,}"

    except Exception:return "0"



class HistoryChart(tk.Canvas):

    def __init__(self,parent,series,minimum=0,maximum=100,height=190,dynamic=False,suffix=""):

        super().__init__(parent,bg="#0a1324",highlightbackground="#263653",highlightthickness=1,height=height)

        self.series=series;self.minimum=float(minimum);self.maximum=float(maximum);self.dynamic=dynamic;self.suffix=suffix

        self.rows=[];self.configure(cursor="arrow");self.bind("<Configure>",lambda _e:self.redraw())

    def add(self,sample):

        self.rows.append(dict(sample));self.rows=self.rows[-120:];self.redraw()

    def _bounds(self):

        if not self.dynamic:return self.minimum,self.maximum

        values=[float(row[key]) for row in self.rows for _label,key,_color in self.series

                if isinstance(row.get(key),(int,float)) and math.isfinite(row[key])]

        peak=max(values,default=0.0)

        if peak<=0:return 0.0,1.0

        ceiling=1.0

        while ceiling<peak*1.15:ceiling*=2.0

        return 0.0,ceiling

    def _value(self,value):

        if not isinstance(value,(int,float)):return "n/a"

        v=float(value)

        shown=f"{v:.0f}" if abs(v)>=100 else f"{v:.1f}" if abs(v)>=10 else f"{v:.3f}"

        return shown+self.suffix

    def _segments(self,key,left,right,top,bottom,minimum,maximum):

        """Keep unavailable samples as gaps rather than drawing invented readings."""

        segments=[];points=[];span=max(.000001,maximum-minimum)

        for i,row in enumerate(self.rows):

            value=row.get(key)

            if not isinstance(value,(int,float)) or not math.isfinite(value):

                if points:segments.append(points);points=[]

                continue

            x=left+(right-left)*(i/max(1,len(self.rows)-1))

            clipped=max(minimum,min(maximum,float(value)))

            y=bottom-(bottom-top)*(clipped-minimum)/span

            points.extend((x,y))

        if points:segments.append(points)

        return segments

    def redraw(self):

        self.delete("all");w=max(20,self.winfo_width());h=max(20,self.winfo_height())

        left=46;right=12;top=34;bottom=30;minimum,maximum=self._bounds();span=max(.000001,maximum-minimum)

        for i in range(5):

            y=top+(h-top-bottom)*i/4

            self.create_line(left,y,w-right,y,fill="#263653")

            value=maximum-span*i/4

            self.create_text(5,y,text=self._value(value),anchor="w",fill=MUTED,font=("Segoe UI",7))

        for i in range(5):

            x=left+(w-left-right)*i/4;self.create_line(x,top,x,h-bottom,fill="#1d2b43")

        for label,key,color in self.series:

            for points in self._segments(key,left,w-right,top,h-bottom,minimum,maximum):

                if len(points)>=4:self.create_line(*points,fill=color,width=2,smooth=False)

                self.create_oval(points[-2]-2,points[-1]-2,points[-2]+2,points[-1]+2,fill=color,outline=color)

        self.create_text(left,h-7,text="-2 min",anchor="w",fill=MUTED,font=("Segoe UI",7))

        self.create_text(w-right,h-7,text="now",anchor="e",fill=MUTED,font=("Segoe UI",7))

        x=left

        latest=self.rows[-1] if self.rows else {}

        for label,key,color in self.series:

            self.create_rectangle(x,9,x+9,18,fill=color,outline=color)

            caption=f"{label} {self._value(latest.get(key))}"

            self.create_text(x+13,14,text=caption,anchor="w",fill=TEXT,font=("Segoe UI",8,"bold"))

            x+=max(105,len(caption)*7+28)



class App:

    def __init__(self):

        if os.name=="nt":

            try:__import__("ctypes").windll.shcore.SetProcessDpiAwareness(1)

            except Exception:pass

        self.root=tk.Tk()

        self.root.title(APP_NAME)

        self.root.geometry("740x820");self.root.minsize(640,600)

        self.root.configure(bg=BG);self.root.protocol("WM_DELETE_WINDOW",self.on_close)

        self.root.option_add("*Font",("Segoe UI",10))

        self.icon=None;self.worker_proc=None;self.refresh_busy=False;self.hw={}

        self.limits_dirty=False;self.settings_loaded=False;self.stopping=False;self.starting_until=0

        self.cfg=release_config();self.setup_mode=not STATE.exists()

        self.cpu_var=tk.IntVar(value=50);self.gpu_var=tk.IntVar(value=0)

        policy=control();self.max_cpu_temp_var=tk.IntVar(value=policy["max_cpu_temp_c"]);self.max_gpu_temp_var=tk.IntVar(value=policy["max_gpu_temp_c"])

        self.thermal_dirty=False;self.last_telemetry_time=None

        self.name_var=tk.StringVar();self.public_var=tk.BooleanVar(value=False)

        self.consent_var=tk.BooleanVar(value=False);self.autostart_var=tk.BooleanVar(value=get_autostart())

        self.status_var=tk.StringVar(value="Preparing...")

        self.status_detail=tk.StringVar(value="Checking local worker")

        self.update_detail=tk.StringVar(value=f"Installed version {APP_VERSION}. Updates are optional unless marked required.")

        self.update_requested_at=0

        self.build()

        threading.Thread(target=self.load_hardware,daemon=True).start()

        self.root.after(500,self.refresh_async)

        self.root.after(1000,self.poll_local)



    def label(self,parent,text,size=10,color=TEXT,bold=False,**kw):

        return tk.Label(parent,text=text,bg=parent.cget("bg"),fg=color,

                        font=("Segoe UI",size,"bold" if bold else "normal"),**kw)



    def card(self,parent):

        f=tk.Frame(parent,bg=CARD,highlightbackground="#263653",highlightthickness=1)

        f.pack(fill="x",pady=(0,12));return f



    def button(self,parent,text,cmd,primary=False,width=0):

        bg=ACCENT2 if primary else CARD2

        b=tk.Button(parent,text=text,command=cmd,bg=bg,fg=TEXT,activebackground="#6558df",

                    activeforeground=TEXT,relief="flat",bd=0,padx=16,pady=9,cursor="hand2")

        if width:b.config(width=width)

        return b



    def build(self):

        outer=tk.Frame(self.root,bg=BG);outer.pack(fill="both",expand=True,padx=24,pady=20)

        head=tk.Frame(outer,bg=BG);head.pack(fill="x",pady=(0,16))

        self.label(head,"ENIGMA",11,ACCENT,True).pack(anchor="w")

        self.label(head,APP_NAME,24,TEXT,True).pack(anchor="w")

        camp=self.cfg.get("campaign_name","P1030680 Naval Enigma M4")

        self.label(head,camp,10,MUTED).pack(anchor="w",pady=(2,0))

        self.status_pill=tk.Label(head,textvariable=self.status_var,bg=CARD2,fg=AMBER,

                                  font=("Segoe UI",10,"bold"),padx=12,pady=5)

        self.status_pill.pack(anchor="w",pady=(12,3))

        tk.Label(head,textvariable=self.status_detail,bg=BG,fg=MUTED,wraplength=650,

                 justify="left",font=("Segoe UI",9)).pack(anchor="w")

        area=tk.Frame(outer,bg=BG);area.pack(fill="both",expand=True)

        canvas=tk.Canvas(area,bg=BG,highlightthickness=0)

        scroll=tk.Scrollbar(area,orient="vertical",command=canvas.yview)

        canvas.configure(yscrollcommand=scroll.set)

        scroll.pack(side="right",fill="y");canvas.pack(side="left",fill="both",expand=True)

        self.body=tk.Frame(canvas,bg=BG)

        window=canvas.create_window((0,0),window=self.body,anchor="nw")

        self.body.bind("<Configure>",lambda e:canvas.configure(scrollregion=canvas.bbox("all")))

        canvas.bind("<Configure>",lambda e:canvas.itemconfigure(window,width=e.width))

        self.root.bind("<MouseWheel>",lambda e:canvas.yview_scroll(-int(e.delta/120),"units"))

        self.render_body()



    def render_body(self):

        for w in self.body.winfo_children():w.destroy()

        if self.setup_mode:self.render_onboarding()

        else:self.render_dashboard()



    def render_onboarding(self):

        c=self.card(self.body);inner=tk.Frame(c,bg=CARD);inner.pack(fill="x",padx=20,pady=18)

        self.label(inner,"Join the search",17,TEXT,True).pack(anchor="w")

        self.label(inner,"Contribute spare compute to an independently validated Enigma search.",10,MUTED,

                   wraplength=580,justify="left").pack(anchor="w",pady=(4,16))

        self.label(inner,"Contributor nickname (2–80 characters; no real name needed)",9,MUTED,True).pack(anchor="w")

        e=tk.Entry(inner,textvariable=self.name_var,bg="#0d1527",fg=TEXT,insertbackground=TEXT,

                   relief="flat",font=("Segoe UI",11))

        e.pack(fill="x",ipady=9,pady=(5,12));e.focus_set()

        tk.Checkbutton(inner,text="Show my name on the public leaderboard",variable=self.public_var,

                       bg=CARD,fg=TEXT,selectcolor=CARD2,activebackground=CARD,activeforeground=TEXT).pack(anchor="w")

        self.resource_controls(inner)

        self.button(inner,"Read privacy & project information",lambda:webbrowser.open(PROJECT_URL+"/blob/main/PRIVACY.md")).pack(anchor="w",pady=(12,0))

        tk.Checkbutton(inner,text="I understand this uses CPU/GPU time and electricity.",

                       variable=self.consent_var,bg=CARD,fg=TEXT,selectcolor=CARD2,

                       activebackground=CARD,activeforeground=TEXT).pack(anchor="w",pady=(14,4))



        endpoint=server_url()

        secure="Secure HTTPS endpoint configured" if endpoint.startswith("https://") else "Secure endpoint unavailable"

        self.endpoint_label=self.label(inner,secure,9,GREEN if endpoint.startswith("https://") else RED)

        self.endpoint_label.pack(anchor="w",pady=(4,14))

        self.join_btn=self.button(inner,"Start contributing",self.register,True)

        self.join_btn.pack(fill="x")

        self.label(inner,"You can pause or stop at any time. Updates are signature-verified and applied only between jobs.",

                   9,MUTED,wraplength=580,justify="left").pack(anchor="w",pady=(12,0))



    def resource_controls(self,parent):

        box=tk.Frame(parent,bg=CARD);box.pack(fill="x",pady=(16,0))

        row=tk.Frame(box,bg=CARD);row.pack(fill="x")

        self.cpu_text=self.label(row,"CPU 50%",10,TEXT,True);self.cpu_text.pack(side="left")

        self.hw_text=self.label(row,"Detecting hardware...",9,MUTED);self.hw_text.pack(side="right")

        self.cpu_scale=tk.Scale(box,from_=0,to=100,resolution=5,orient="horizontal",variable=self.cpu_var,

             command=self.limits_changed,bg=CARD,fg=TEXT,troughcolor="#263653",

             activebackground=ACCENT,highlightthickness=0,showvalue=False)

        self.cpu_scale.pack(fill="x")

        self.gpu_text=self.label(box,"GPU 0%",10,TEXT,True);self.gpu_text.pack(anchor="w",pady=(8,0))

        self.gpu_scale=tk.Scale(box,from_=0,to=100,resolution=5,orient="horizontal",variable=self.gpu_var,

             command=self.limits_changed,bg=CARD,fg=TEXT,troughcolor="#263653",

             activebackground=ACCENT2,highlightthickness=0,showvalue=False)

        self.gpu_scale.pack(fill="x")

        self.label(box,"CPU sets a thread budget; GPU sets a work/rest budget. Actual load varies.\nChanges apply to the next job. 0% disables that resource. First start may take a minute.",

                   9,MUTED,wraplength=560,justify="left").pack(anchor="w",pady=(8,0))



    def limits_changed(self,_=None):

        self.limits_dirty=True;self.update_scale_labels()



    def update_thermal_labels(self):

        if hasattr(self,"max_cpu_temp_text"):self.max_cpu_temp_text.config(text=f"CPU maximum {int(self.max_cpu_temp_var.get())}°C")

        if hasattr(self,"max_gpu_temp_text"):self.max_gpu_temp_text.config(text=f"GPU maximum {int(self.max_gpu_temp_var.get())}°C")



    def thermal_changed(self,_=None):

        self.thermal_dirty=True;self.update_thermal_labels()



    def save_thermal_limits(self):

        cpu=max(55,min(95,int(self.max_cpu_temp_var.get())));gpu=max(50,min(90,int(self.max_gpu_temp_var.get())))

        save_control(max_cpu_temp_c=cpu,max_gpu_temp_c=gpu)

        ui=load_json(UI_STATE,{});ui.update({"max_cpu_temp_c":cpu,"max_gpu_temp_c":gpu});atomic_json(UI_STATE,ui)

        self.thermal_dirty=False

        self.set_status("Thermal limits saved",GREEN,f"CPU {cpu}°C · GPU {gpu}°C")



    def render_dashboard(self):

        navigation=tk.Frame(self.body,bg=BG);navigation.pack(fill="x",pady=(0,12))

        pages={name:tk.Frame(self.body,bg=BG) for name in ('Compute','Monitor','Results','Settings')}

        buttons={}

        def select(name):

            self.active_page=name

            for title,page in pages.items():

                page.pack_forget()

                buttons[title].config(bg=ACCENT2 if title==name else CARD2)

            pages[name].pack(fill="both",expand=True)

        for name in pages:

            buttons[name]=self.button(navigation,name,lambda name=name:select(name))

            buttons[name].pack(side="left",fill="x",expand=True,padx=2)

        select(getattr(self,'active_page','Compute'))

        stats=tk.Frame(pages['Results'],bg=BG);stats.pack(fill="x")

        self.stat_labels={}

        for key,title in [("progress","Campaign progress"),("units","Your verified units"),

                          ("pending","Awaiting checks"),("trust","Device trust")]:

            c=tk.Frame(stats,bg=CARD,highlightbackground="#263653",highlightthickness=1)

            c.pack(side="left",fill="both",expand=True,padx=(0 if not self.stat_labels else 8,0))

            self.label(c,title,8,MUTED,True).pack(anchor="w",padx=12,pady=(11,2))

            v=self.label(c,"--",16,TEXT,True);v.pack(anchor="w",padx=12,pady=(0,11))

            self.stat_labels[key]=v

        board=self.card(pages["Results"]);board_inner=tk.Frame(board,bg=CARD);board_inner.pack(fill="both",expand=True,padx=18,pady=14)

        self.label(board_inner,"Global scoreboard",14,TEXT,True).pack(anchor="w")

        self.label(board_inner,"Top 20 public contributors · credited work reported by the coordinator",9,MUTED,wraplength=580,justify="left").pack(anchor="w",pady=(5,8))

        self.scoreboard_status=self.label(board_inner,"Loading global standings...",9,MUTED,wraplength=580,justify="left")

        self.scoreboard_status.pack(anchor="w",pady=(0,10))

        self.scoreboard=ttk.Treeview(board_inner,columns=("rank","name","units","jobs"),show="headings",height=7)

        for key,title,width in (("rank","#",40),("name","Contributor",230),("units","Credited units",130),("jobs","Credited jobs",130)):

            self.scoreboard.heading(key,text=title);self.scoreboard.column(key,width=width,minwidth=35,anchor="w" if key=="name" else "e",stretch=key=="name")

        self.scoreboard.pack(fill="both",expand=True)

        updates=self.card(pages["Settings"]);u=tk.Frame(updates,bg=CARD);u.pack(fill="x",padx=18,pady=14)

        self.label(u,"App updates",14,TEXT,True).pack(anchor="w")

        tk.Label(u,textvariable=self.update_detail,bg=CARD,fg=MUTED,wraplength=560,

                 justify="left",font=("Segoe UI",10)).pack(anchor="w",pady=(8,10))

        self.update_btn=self.button(u,"Check for updates",self.check_update)

        self.update_btn.pack(anchor="w")

        diagnostics=self.card(pages["Settings"]);d=tk.Frame(diagnostics,bg=CARD);d.pack(fill="x",padx=18,pady=14)
        self.label(d,"Device check",14,TEXT,True).pack(anchor="w")
        self.device_check_status=self.label(d,"Check CPU and qualified GPU availability without changing your settings.",9,MUTED,wraplength=560,justify="left")
        self.device_check_status.pack(anchor="w",pady=(5,8))
        self.device_check_btn=self.button(d,"Run device check",self.run_device_check)
        self.device_check_btn.pack(anchor="w")



        controls=self.card(pages["Compute"]);inner=tk.Frame(controls,bg=CARD);inner.pack(fill="x",padx=18,pady=16)

        top=tk.Frame(inner,bg=CARD);top.pack(fill="x")

        self.label(top,"Resource controls",14,TEXT,True).pack(side="left")

        tk.Checkbutton(top,text="Start with Windows",variable=self.autostart_var,command=self.toggle_autostart,

                       bg=CARD,fg=TEXT,selectcolor=CARD2,activebackground=CARD,activeforeground=TEXT).pack(side="right")

        self.resource_controls(inner)

        actions=tk.Frame(inner,bg=CARD);actions.pack(fill="x",pady=(14,0))

        self.save_btn=self.button(actions,"Apply resource limits",self.save_limits,True);self.save_btn.pack(side="left")

        self.pause_btn=self.button(actions,"Pause",self.toggle_pause);self.pause_btn.pack(side="left",padx=8)

        self.button(actions,"Stop safely",self.stop_safe).pack(side="left",padx=8)

        self.label(inner,"Pause keeps the app open. Stop safely finishes your current job before closing.",

                   9,MUTED,wraplength=560,justify="left").pack(anchor="w",pady=(10,0))



        monitoring=self.card(pages["Monitor"]);m=tk.Frame(monitoring,bg=CARD);m.pack(fill="x",padx=18,pady=14)

        self.label(m,"Advanced monitoring",14,TEXT,True).pack(anchor="w")

        self.monitor_line=self.label(m,"Waiting for worker telemetry...",9,MUTED,wraplength=610,justify="left")

        self.monitor_line.pack(anchor="w",pady=(5,10))

        self.label(m,"Resource utilization · rolling 2 minutes",9,MUTED,True).pack(anchor="w")

        self.resource_chart=HistoryChart(m,[("CPU","cpu_percent",ACCENT),("GPU","gpu_percent",AMBER),("RAM","memory_percent",ACCENT2)],0,100,suffix="%")

        self.resource_chart.pack(fill="x",pady=(4,10))

        self.label(m,"CPU / GPU temperature · rolling 2 minutes",9,MUTED,True).pack(anchor="w")

        self.temperature_status=self.label(m,"Checking temperature sensors...",8,MUTED,wraplength=610,justify="left")

        self.temperature_status.pack(anchor="w",pady=(3,0))

        self.temperature_chart=HistoryChart(m,[("CPU","cpu_temp_c",GREEN),("GPU","gpu_temp_c",AMBER)],20,100,suffix="°C")

        self.temperature_chart.pack(fill="x",pady=(4,10))

        self.label(m,"Processing throughput · rolling 2 minutes",9,MUTED,True).pack(anchor="w")

        self.units_chart=HistoryChart(m,[("Units/s","units_per_second",ACCENT)],height=130,dynamic=True)

        self.units_chart.pack(fill="x",pady=(4,8))

        self.jobs_chart=HistoryChart(m,[("Jobs/s","jobs_per_second",GREEN)],height=130,dynamic=True)

        self.jobs_chart.pack(fill="x",pady=(4,12))

        thermal=tk.Frame(pages["Settings"],bg=CARD);thermal.pack(fill="x")

        left=tk.Frame(thermal,bg=CARD);left.pack(side="left",fill="x",expand=True,padx=(0,8))

        right=tk.Frame(thermal,bg=CARD);right.pack(side="left",fill="x",expand=True,padx=(8,0))

        self.max_cpu_temp_text=self.label(left,"CPU maximum",9,TEXT,True);self.max_cpu_temp_text.pack(anchor="w")

        self.max_cpu_temp_scale=tk.Scale(left,from_=55,to=95,resolution=1,orient="horizontal",variable=self.max_cpu_temp_var,

             command=self.thermal_changed,bg=CARD,fg=TEXT,troughcolor="#263653",activebackground=GREEN,highlightthickness=0,showvalue=False)

        self.max_cpu_temp_scale.pack(fill="x")

        self.max_gpu_temp_text=self.label(right,"GPU maximum",9,TEXT,True);self.max_gpu_temp_text.pack(anchor="w")

        self.max_gpu_temp_scale=tk.Scale(right,from_=50,to=90,resolution=1,orient="horizontal",variable=self.max_gpu_temp_var,

             command=self.thermal_changed,bg=CARD,fg=TEXT,troughcolor="#263653",activebackground=AMBER,highlightthickness=0,showvalue=False)

        self.max_gpu_temp_scale.pack(fill="x")

        self.update_thermal_labels()

        self.thermal_save_btn=self.button(pages["Settings"],"Apply thermal limits",self.save_thermal_limits,True);self.thermal_save_btn.pack(anchor="w",pady=(10,0))

        self.label(pages["Settings"],"When a temperature sensor is available, EnigmaGrid pauses at your ceiling and resumes after about 5°C of cooling. Firmware/driver protections remain active even if sensors are unavailable to the app.",

                   8,MUTED,wraplength=610,justify="left").pack(anchor="w",pady=(8,0))



        info=self.card(pages["Results"]);i=tk.Frame(info,bg=CARD);i.pack(fill="x",padx=18,pady=14)

        self.label(i,"Project",12,TEXT,True).pack(anchor="w")

        self.personal_line=self.label(i,"Loading contribution statistics...",10,MUTED,wraplength=590,justify="left")

        self.personal_line.pack(anchor="w",pady=(5,9))

        self.hardware_line=self.label(i,"",9,MUTED,wraplength=590,justify="left")

        self.hardware_line.pack(anchor="w")

        links=tk.Frame(i,bg=CARD);links.pack(fill="x",pady=(12,0))

        self.button(links,"Open dashboard",self.open_dashboard).pack(side="left")

        self.button(links,"Open logs",self.open_logs).pack(side="left",padx=8)

        self.button(links,"Stop safely",self.stop_safe).pack(side="right")

        account=tk.Frame(pages["Settings"],bg=BG);account.pack(fill="x",pady=(8,0))

        self.button(account,"Copy private dashboard token",self.copy_dashboard_token).pack(side="left")

        self.button(account,"Privacy & help",lambda:webbrowser.open(PROJECT_URL)).pack(side="right")

        self.label(self.body,f"Version {APP_VERSION}  |  Signed updates  |  Independent result validation",

                   8,MUTED).pack(anchor="center",pady=(4,0))



    def update_scale_labels(self):

        if hasattr(self,"cpu_text"):self.cpu_text.config(text=f"CPU {int(self.cpu_var.get())}%")

        if hasattr(self,"gpu_text"):self.gpu_text.config(text=f"GPU {int(self.gpu_var.get())}%")



    def load_hardware(self):

        try:

            r=run_worker(["--self-test"],capture=True,timeout=120)

            self.hw=json.loads((r.stdout or "").strip().splitlines()[-1]) if r.returncode==0 else {}

        except Exception:self.hw={}

        self.root.after(0,self.apply_hardware)

    def run_device_check(self):
        self.device_check_btn.config(state='disabled')
        self.device_check_status.config(text='Checking local CPU and GPU support...')
        def check():
            try:
                result=run_worker(['--self-test'],capture=True,timeout=120)
                report=json.loads((result.stdout or '').strip().splitlines()[-1]) if result.returncode==0 else {}
                if report.get('ok') is not True:raise RuntimeError('Local check did not complete')
                gpus=report.get('gpus') or []
                detail=f"CPU: {report.get('cpu_count','n/a')} logical cores · Qualified OpenCL GPUs: {len(gpus)}"
            except Exception as error:
                detail=f'Device check unavailable: {type(error).__name__}'
            def finish():
                if not self.root.winfo_exists():return
                self.device_check_status.config(text=detail)
                self.device_check_btn.config(state='normal')
            self.root.after(0,finish)
        threading.Thread(target=check,name='device-check',daemon=True).start()



    def apply_hardware(self):

        cpus=int(self.hw.get("cpu_count",0) or 0);gpus=self.hw.get("gpus",[]) or []

        gpu_name=gpus[0].get("name","GPU") if gpus else "No verified OpenCL GPU"

        if hasattr(self,"hw_text"):self.hw_text.config(text=f"{cpus} CPU threads | {gpu_name}")

        if hasattr(self,"hardware_line"):

            self.hardware_line.config(text=f"Hardware: {cpus} CPU threads | {gpu_name}")

        if not gpus:

            self.gpu_var.set(0)

            if hasattr(self,"gpu_scale"):self.gpu_scale.config(state="disabled")

        elif hasattr(self,"gpu_scale"):self.gpu_scale.config(state="normal")

        self.update_scale_labels()

        if self.setup_mode and self.status_var.get()=="Preparing...":

            self.set_status("Ready to join",GREEN,"Choose a nickname and the resources you want to contribute.")



    def register(self):

        endpoint=server_url();name=self.name_var.get().strip()

        if not endpoint.startswith("https://"):

            return messagebox.showerror(APP_NAME,"The secure project endpoint is not available yet.")

        if not 2<=len(name)<=80:return messagebox.showerror(APP_NAME,"Enter a nickname between 2 and 80 characters.")

        if self.cpu_var.get()==0 and self.gpu_var.get()==0:

            return messagebox.showerror(APP_NAME,"Choose a CPU or GPU contribution above 0% to start.")

        if not self.consent_var.get():

            return messagebox.showerror(APP_NAME,"Confirm that you understand the resource usage before joining.")

        self.join_btn.config(state="disabled");self.set_status("Registering",AMBER,"Solving registration challenge")

        cpu=int(self.cpu_var.get());gpu=int(self.gpu_var.get())

        args=["--server",endpoint,"--name",name,"--state",str(STATE),"--register-only",

              "--cpu-percent",str(cpu),"--gpu-percent",str(gpu)]

        if not self.public_var.get():args.append("--private-credit")



        def job():

            try:

                r=run_worker(args,capture=True,timeout=240)

                if r.returncode:raise RuntimeError((r.stderr or r.stdout or "Registration failed")[-600:])

                atomic_json(UI_STATE,{"name":name,"cpu":cpu,"gpu":gpu})

                self.root.after(0,self.registration_ok)

            except Exception as e:self.root.after(0,lambda msg=str(e):self.registration_failed(msg))

        threading.Thread(target=job,daemon=True).start()



    def registration_failed(self,msg):

        self.join_btn.config(state="normal")

        self.set_status("Connection error",RED,"Could not register with the project")

        messagebox.showerror(APP_NAME,msg)



    def registration_ok(self):

        self.setup_mode=False;save_control(paused=False,stop_requested=False)

        self.ensure_worker();self.render_body();self.apply_hardware()

        self.set_status("Starting",AMBER,"Account created. Preparing the worker and checking for available work.")



    def save_limits(self):

        cpu=int(self.cpu_var.get());gpu=int(self.gpu_var.get())

        self.save_btn.config(state="disabled")

        def job():

            try:

                r=run_worker(["--state",str(STATE),"--set-preferences","--cpu-percent",str(cpu),

                              "--gpu-percent",str(gpu)],capture=True)

                if r.returncode:raise RuntimeError((r.stderr or r.stdout or "Save failed")[-500:])

                ui=load_json(UI_STATE,{});ui.update({"cpu":cpu,"gpu":gpu});atomic_json(UI_STATE,ui)

                self.root.after(0,self.limits_saved)

            except Exception as e:self.root.after(0,lambda msg=str(e):messagebox.showerror(APP_NAME,msg))

            finally:self.root.after(0,lambda:self.save_btn.config(state="normal"))

        threading.Thread(target=job,daemon=True).start()



    def limits_saved(self):

        self.limits_dirty=False

        self.set_status("Saved",GREEN,"Resource budgets saved; they apply to the next job.")



    def toggle_pause(self):

        c=control();paused=not bool(c.get("paused",False))

        if c.get("stop_requested"):paused=False

        save_control(paused=paused,stop_requested=False)

        if not paused:self.ensure_worker()

        self.set_status("Paused" if paused else "Contributing",AMBER if paused else GREEN,

                        "No new jobs will start" if paused else "Worker resumed")

        if hasattr(self,"pause_btn"):self.pause_btn.config(text="Resume" if paused else "Pause")



    def check_update(self):

        if control().get("stop_requested") or not STATE.exists():

            self.update_detail.set("Start contributing or resume the worker to check for updates.")

            return

        self.ensure_worker()

        self.update_requested_at=time.time()

        atomic_write(STATE.with_name("check-update-request"),b"check")

        self.update_detail.set("Checking for updates… Contacting GitHub and verifying the release signature.")

        if hasattr(self,"update_btn"):self.update_btn.config(state="disabled",text="Checking…")



    def toggle_autostart(self):

        try:set_autostart(bool(self.autostart_var.get()))

        except Exception as e:

            self.autostart_var.set(get_autostart());messagebox.showerror(APP_NAME,str(e))



    def stop_safe(self):

        self.stopping=True

        save_control(stop_requested=True,paused=False)

        self.set_status("Stopping safely",AMBER,"Finishing the current job before exit")



    def poll_local(self):

        if SHOW_REQUEST.exists():

            SHOW_REQUEST.unlink(missing_ok=True);self.show()

        if STATE.with_name("update-exit").exists():

            STATE.with_name("update-exit").unlink(missing_ok=True);self.quit_all();return

        if self.stopping and not is_alive():

            self.quit_all();return

        if not self.setup_mode:

            self.apply_worker_status()

            self.refresh_update_status()

        self.root.after(1000,self.poll_local)



    def refresh_update_status(self):

        status=load_json(STATE.with_name("update_status.json"),{})

        recent=float(status.get("checked_at",0))>=self.update_requested_at

        if recent and status.get("message"):

            self.update_detail.set(status["message"])

        pending=(not recent and self.update_requested_at>0) or (recent and status.get("status") in {"checking","downloading","ready"})

        if not recent and self.update_requested_at and time.time()-self.update_requested_at>100:

            self.update_detail.set("The worker has not answered yet. Check that it is running, then retry.")

            pending=False

        if hasattr(self,"update_btn"):

            self.update_btn.config(state="disabled" if pending else "normal",text={"downloading":"Downloading...","ready":"Ready to install"}.get(status.get("status"),"Checking...") if pending else "Check for updates")



    def ensure_worker(self):

        if not STATE.exists() or control().get("stop_requested"):return

        if self.worker_proc and self.worker_proc.poll() is None:return

        if not is_alive() and time.monotonic()>self.starting_until:

            try:

                self.worker_proc=start_worker();self.starting_until=time.monotonic()+60

            except Exception as e:self.set_status("Worker error",RED,str(e))



    def set_status(self,title,color,detail=""):

        self.status_var.set(title);self.status_detail.set(detail)

        if hasattr(self,"status_pill"):self.status_pill.config(fg=color)



    def refresh_async(self):

        if self.root.winfo_exists():

            if not self.setup_mode:self.ensure_worker()

            if not self.refresh_busy:

                self.refresh_busy=True;threading.Thread(target=self.fetch_summary,daemon=True).start()

            self.root.after(10000,self.refresh_async)



    def fetch_summary(self):

        try:

            data=read_cached_summary(STATE,APP_VERSION)
            if data is None:
                r=run_worker(["--state",str(STATE),"--client-summary-json"],capture=True,timeout=60)
                data=json.loads((r.stdout or "").strip().splitlines()[-1]) if r.returncode==0 else {}

            self.root.after(0,lambda:self.apply_summary(data))

        except Exception:

            self.root.after(0,lambda:self.apply_summary({}))

        finally:self.refresh_busy=False



    def apply_summary(self,data):

        if self.setup_mode:return

        ui=load_json(UI_STATE,{})

        settings=data.get("settings") or ui

        if settings and (not self.settings_loaded or not self.limits_dirty):

            self.cpu_var.set(int(settings.get("cpu_percent",settings.get("cpu",50))))

            self.gpu_var.set(int(settings.get("gpu_percent",settings.get("gpu",0))))

            self.settings_loaded=True

            self.root.after_idle(lambda:setattr(self,"limits_dirty",False))

        self.apply_worker_status()



        g=data.get("global") or {};p=data.get("personal") or {};st=p.get("stats") or {}

        if hasattr(self,"scoreboard"):

            leaders=g.get("leaderboard")

            if isinstance(leaders,list):

                self.scoreboard.delete(*self.scoreboard.get_children())

                for rank,entry in enumerate(leaders[:20],1):

                    self.scoreboard.insert("","end",values=(rank,str(entry.get("display_name") or "Anonymous"),fmt(entry.get("units",0)),fmt(entry.get("jobs",0))))

                self.scoreboard_status.config(text=f"{len(leaders[:20])} public contributors shown · {g.get('online_devices','n/a')} devices online. Private profiles are omitted." if leaders else "No public credited contributions yet.")

            else:

                self.scoreboard_status.config(text="Latest available standings; refresh pending." if self.scoreboard.get_children() else "Global standings temporarily unavailable; retrying automatically.")

        if hasattr(self,"stat_labels"):

            self.stat_labels["progress"].config(text=f"{float(g.get('progress_pct',0)):.3f}%" if g else "--")

            self.stat_labels["units"].config(text=fmt(st.get("units",0)) if p else "--")

            self.stat_labels["pending"].config(text=fmt(p.get("pending_units",0)) if p else "--")

            devs=p.get("devices") or [];dev=next((d for d in devs if d["id"]==data.get("device_id")),{})

            self.stat_labels["trust"].config(text=f"{float(dev.get('trust_score',1)):.2f}" if dev else "--")

        if hasattr(self,"personal_line"):

            jobs=fmt(st.get("jobs",0));units=fmt(st.get("units",0))

            self.personal_line.config(text=f"{units} verified units | {jobs} verified jobs. Credit arrives after another contributor checks your work." if p else "Statistics temporarily unavailable. Your saved account is safe; retrying automatically.")

        self.apply_hardware()



    def apply_worker_status(self):

        c=control();alive=is_alive();h=load_json(HEALTH,{})

        if not self.thermal_dirty:

            self.max_cpu_temp_var.set(int(c.get("max_cpu_temp_c",80)));self.max_gpu_temp_var.set(int(c.get("max_gpu_temp_c",75)));self.update_thermal_labels()

        telemetry=h.get("telemetry") if isinstance(h.get("telemetry"),dict) else {}

        if not alive:telemetry={}

        if hasattr(self,"temperature_status"):

            cpu_temp=telemetry.get("cpu_temp_c");gpu_temp=telemetry.get("gpu_temp_c")

            if not alive:detail="Temperature readings unavailable while worker is stopped."

            elif not isinstance(cpu_temp,(int,float)) and not isinstance(gpu_temp,(int,float)):

                detail="Temperature sensors unavailable on this PC. App temperature ceilings need sensor readings; firmware/driver protection remains active."

            else:

                shown=lambda value:f"{float(value):.1f}°C" if isinstance(value,(int,float)) else "n/a"

                detail=f"CPU {shown(cpu_temp)} · GPU {shown(gpu_temp)}"

            self.temperature_status.config(text=detail)

        if hasattr(self,"monitor_line"):

            def show(value,suffix=""):

                return f"{float(value):.1f}{suffix}" if isinstance(value,(int,float)) else "n/a"

            gpu_scope=telemetry.get('gpu_metric_scope','unknown')
            backend=(h.get('bounded_backend','not reported') if h.get('active_engine') in (None,'bounded_crib_v1')
                     else h.get('resource','not reported')) if alive else 'worker stopped'
            self.monitor_line.config(text=f"CPU {show(telemetry.get('cpu_percent'),'%')} (worker) · GPU {show(telemetry.get('gpu_percent'),'%')} ({gpu_scope}) · RAM {show(telemetry.get('memory_percent'),'%')} · CPU {show(telemetry.get('cpu_temp_c'),'°C')} · GPU {show(telemetry.get('gpu_temp_c'),'°C')} · {telemetry.get('sensor_provider','temperature sensor unavailable')}\nBackend: {backend} · Ready units: {h.get('ready_units') if alive and h.get('ready_units') is not None else 'n/a'} · Pending uploads: {h.get('outbox_count','n/a') if alive else 'n/a'} | Running: {h.get('running_jobs','n/a') if alive else 'n/a'} | Expired, saved: {h.get('expired_results') if alive and h.get('expired_results') is not None else 'n/a'}")

            throughput=h.get("throughput") if isinstance(h.get("throughput"),dict) else {}

            if not alive or time.time()-float(throughput.get("sampled_at",0))>5:

                throughput={}

            stamp=telemetry.get("time",int(time.time()))

            if stamp!=self.last_telemetry_time:

                self.last_telemetry_time=stamp

                self.resource_chart.add(telemetry);self.temperature_chart.add(telemetry)

                self.units_chart.add({"units_per_second":throughput.get("units_per_second")})

                self.jobs_chart.add({"jobs_per_second":throughput.get("jobs_per_second")})

        if c.get("stop_requested"):

            self.set_status("Stopping safely" if alive else "Stopped",AMBER,"Finishing the current job" if alive else "Choose Start to contribute again.")

            if hasattr(self,"pause_btn"):self.pause_btn.config(text="Start" if not alive else "Resume")

            return

        if c.get("paused"):

            self.set_status("Paused",AMBER,"No new jobs will start")

            if hasattr(self,"pause_btn"):self.pause_btn.config(text="Resume")

        elif alive:

            status=h.get("status","starting")

            titles={"computing":"Contributing","waiting":"Waiting for work","starting":"Preparing worker", "connection_error":"Reconnecting","paused":"Paused","cooling":"Cooling", "qualifying_gpu":"Checking GPU performance"}

            detail=(str(h.get("resource","CPU"))+" | "+f"{min(100,max(0,float(h.get('progress',0))*100)):.0f}% of current search" if status=="computing" else str(h.get("thermal_reason") or "Waiting for temperatures to fall below the configured limit.") if status=="cooling" else "Your worker is ready; jobs are assigned automatically." if status=="waiting" else "Checking the coordinator; retrying automatically.")

            if status=='waiting':

                detail={'verification_pending':'Waiting for independent verification; safety limit reached.',

                        'primary_held_for_verification':'Coordinator is prioritizing independent verification.',

                        'no_compatible_work':'No compatible work is available for this device.'}.get(h.get('wait_reason'),detail)

            self.set_status(titles.get(status,"Preparing worker"),GREEN if status=="computing" else AMBER,detail)

            if hasattr(self,"pause_btn"):self.pause_btn.config(text="Pause")

        else:self.set_status("Connecting",AMBER,"Waiting for worker heartbeat")



    def copy_dashboard_token(self):

        def job():

            try:

                r=run_worker(["--state",str(STATE),"--dashboard-token"],capture=True,timeout=30)

                if r.returncode:raise RuntimeError("Could not read your private dashboard token.")

                token=r.stdout.strip()

                def copy():

                    self.root.clipboard_clear();self.root.clipboard_append(token)

                    self.set_status("Copied",ACCENT,"Private token copied. Paste it only into the project dashboard; do not share it.")

                self.root.after(0,copy)

            except Exception as e:self.root.after(0,lambda msg=str(e):messagebox.showerror(APP_NAME,msg))

        threading.Thread(target=job,daemon=True).start()



    def open_dashboard(self):

        url=server_url()

        if url:webbrowser.open(url)



    def open_logs(self):

        LOCAL.mkdir(parents=True,exist_ok=True)

        if os.name=="nt":os.startfile(str(LOCAL))

        else:webbrowser.open(LOCAL.as_uri())



    def on_close(self):

        if self.setup_mode:self.quit_all()

        else:

            self.root.withdraw()

            if self.icon:

                try:self.icon.notify("Still running in the system tray. Use Pause or Stop safely to stop computing.",APP_NAME)

                except Exception:pass



    def show(self,*_):

        self.root.after(0,lambda:(self.root.deiconify(),self.root.lift(),self.root.focus_force()))



    def quit_all(self):

        try:

            if self.icon:self.icon.stop()

        finally:

            try:self.root.destroy()

            except Exception:pass



    def tray_thread(self):

        menu=pystray.Menu(

            pystray.MenuItem("Open controls",self.show,default=True),

            pystray.MenuItem("Pause / Resume",lambda *_:self.root.after(0,self.toggle_pause)),

            pystray.MenuItem("Open dashboard",lambda *_:self.root.after(0,self.open_dashboard)),

            pystray.MenuItem("Check for update",lambda *_:self.root.after(0,self.check_update)),

            pystray.MenuItem("Stop safely and exit",lambda *_:self.root.after(0,self.stop_safe)))

        self.icon=pystray.Icon("EnigmaVolunteerGrid",make_icon(),APP_NAME,menu);self.icon.run()



    def run(self):

        ui=load_json(UI_STATE,{})

        self.cpu_var.set(int(ui.get("cpu",50)));self.gpu_var.set(int(ui.get("gpu",0)))

        policy=control();self.max_cpu_temp_var.set(int(policy.get("max_cpu_temp_c",ui.get("max_cpu_temp_c",80))));self.max_gpu_temp_var.set(int(policy.get("max_gpu_temp_c",ui.get("max_gpu_temp_c",75))))

        self.name_var.set(str(ui.get("name","")))

        threading.Thread(target=self.tray_thread,daemon=True).start()

        if not self.setup_mode and "--background" in sys.argv:self.root.withdraw()

        self.root.mainloop()



def self_test():

    cfg=release_config();assert isinstance(cfg,dict)

    assert worker_base_cmd()

    p=Path(os.environ.get("TEMP","."))/("enigma-tray-selftest-"+str(os.getpid())+".json")

    atomic_json(p,{"paused":True});assert load_json(p,{})["paused"] is True;p.unlink()

    print(json.dumps({"ok":True,"version":APP_VERSION,"server_configured":bool(server_url())}))



if __name__=="__main__":

    if "--self-test" in sys.argv:self_test()

    else:

        handle=None

        if os.name=="nt":

            import ctypes

            kernel=ctypes.windll.kernel32;kernel.CreateMutexW.restype=ctypes.c_void_p

            handle=kernel.CreateMutexW(None,False,"Local\\EnigmaVolunteerGridTray")

            if kernel.GetLastError()==183:

                STATE.parent.mkdir(parents=True,exist_ok=True);SHOW_REQUEST.write_text("1");sys.exit(0)

        App().run()
