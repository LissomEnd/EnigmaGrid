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
   assert [b.cget('text') for b in buttons]==['Compute','Monitor','Results','Scoreboard','Settings']
   for b in buttons:
    b.invoke();root.update_idletasks();assert app.active_page==b.cget('text')
   assert app.throughput_chart.winfo_exists() and app.temperature_chart.winfo_exists()
   assert sum(b.winfo_reqwidth() for b in buttons)<640
   health={'telemetry':{'time':1,'cpu_percent':30},'bounded_backend':'CPU + Vulkan bounded solver','outbox_count':3,'throughput':{'sampled_at':1,'units_per_second':9,'jobs_per_second':9}}
   with patch.object(ui,'is_alive',return_value=True),patch.object(ui,'load_json',return_value=health):
    app.apply_worker_status()
   assert 'CPU + Vulkan bounded solver' in app.monitor_line.cget('text')
   assert 'Pending uploads: 3' in app.monitor_line.cget('text')
   assert app.throughput_chart.rows[-1]['jobs_per_second'] is None,'Stale throughput shown as zero'
   with patch.object(ui,'is_alive',return_value=False),patch.object(ui,'load_json',return_value=health):
    app.apply_worker_status()
   assert 'worker stopped' in app.monitor_line.cget('text')
   assert app.resource_chart.rows[-1].get('cpu_percent') is None,'Stopped worker displayed stale CPU'

 print('PASS five-page navigation and dedicated Windows monitor layout')
finally:root.destroy()
