"""Legacy control files and partial fixtures retain safe temperature defaults."""
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
import worker

with tempfile.TemporaryDirectory() as directory:
    state=Path(directory)/'state.json'
    for obj in ({},{'paused':True},{'max_cpu_temp_c':None,'max_gpu_temp_c':'bad'}):
        worker.control_path(state).write_text(json.dumps(obj))
        ctl=worker.read_control(state)
        assert (ctl['max_cpu_temp_c'],ctl['max_gpu_temp_c'])==(80,75)
    runtime={'_telemetry_device':object(),'_telemetry_at':time.monotonic(),
             'telemetry':{'cpu_temp_c':81,'gpu_temp_c':60}}
    with patch.object(worker,'read_control',return_value={'paused':False}):
        assert worker._thermal_probe(runtime,state)[0].startswith('CPU cooling')
        runtime['telemetry']['cpu_temp_c']=76
        assert worker._thermal_probe(runtime,state)[0]
        runtime['telemetry']['cpu_temp_c']=75
        assert not worker._thermal_probe(runtime,state)[0]
print('PASS legacy controls, partial fixtures, safe defaults and hysteresis')
