"""Build the Windows UI without launching a worker or contacting the coordinator."""
import sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
import tray_app as ui
import tkinter as tk
root=tk.Tk();root.withdraw()
try:
 with tempfile.TemporaryDirectory() as tmp:
  state=Path(tmp)/'state';state.write_text('{}')
  with patch.object(ui.tk,'Tk',return_value=root),patch.object(ui,'STATE',state),patch.object(ui,'release_config',return_value={}),patch.object(ui,'get_autostart',return_value=False),patch.object(ui.threading.Thread,'start'),patch.object(ui,'control',return_value={'max_cpu_temp_c':80,'max_gpu_temp_c':75}):
   app=ui.App();root.update_idletasks()
   navigation=app.body.winfo_children()[0]
   buttons=navigation.winfo_children()
   assert [b.cget('text') for b in buttons]==['Compute','Monitor','Results','Settings']
   for b in buttons:
    b.invoke();root.update_idletasks();assert app.active_page==b.cget('text')
   assert app.units_chart.winfo_exists() and app.jobs_chart.winfo_exists() and app.temperature_chart.winfo_exists()
   assert sum(b.winfo_reqwidth() for b in buttons)<640
   health={'telemetry':{'time':1,'cpu_percent':30},'bounded_backend':'CPU + Vulkan bounded solver','outbox_count':3,'throughput':{'sampled_at':1,'units_per_second':9,'jobs_per_second':9}}
   with patch.object(ui,'is_alive',return_value=True),patch.object(ui,'load_json',return_value=health):
    app.apply_worker_status()
   assert 'CPU + Vulkan bounded solver' in app.monitor_line.cget('text')
   assert 'Pending uploads: 3' in app.monitor_line.cget('text')
   assert 'Temperature sensors unavailable' in app.temperature_status.cget('text')
   assert app.jobs_chart.rows[-1]['jobs_per_second'] is None,'Stale throughput shown as zero'
   health['telemetry']={'time':2,'cpu_temp_c':68.5}
   with patch.object(ui,'is_alive',return_value=True),patch.object(ui,'load_json',return_value=health):
    app.apply_worker_status()
   assert 'CPU 68.5°C · GPU n/a'==app.temperature_status.cget('text')
   with patch.object(ui,'is_alive',return_value=False),patch.object(ui,'load_json',return_value=health):
    app.apply_worker_status()
   assert 'worker stopped' in app.monitor_line.cget('text')
   assert app.resource_chart.rows[-1].get('cpu_percent') is None,'Stopped worker displayed stale CPU'
   app.units_chart.rows=[{'units_per_second':10000},{'units_per_second':20000}]
   app.jobs_chart.rows=[{'jobs_per_second':2},{'jobs_per_second':4}]
   assert app.units_chart._bounds()==(0,32768) and app.jobs_chart._bounds()==(0,8),'Independent throughput scales required'
   app.resource_chart.rows=[{'gpu_percent':20},{'gpu_percent':None},{'gpu_percent':30}]
   assert len(app.resource_chart._segments('gpu_percent',0,100,0,100,0,100))==2,'Missing GPU telemetry joined as a false reading'
   app.apply_summary({'global':{'leaderboard':[{'display_name':'Volunteer','units':4,'jobs':2}],'online_devices':2}})
   assert app.scoreboard.item(app.scoreboard.get_children()[0],'values')[1]=='Volunteer'
   app.apply_summary({})
   assert len(app.scoreboard.get_children())==1 and 'Latest available' in app.scoreboard_status.cget('text'),'Transient fetch failure erased last standings'

 print('PASS four-page navigation and dedicated Windows monitor layout')
finally:root.destroy()
