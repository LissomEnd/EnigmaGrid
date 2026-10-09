import sys
import ctypes
import threading
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
from windows_telemetry import gpu_engine_percent,NvidiaNvmlTelemetry,_NvmlUtilization

def counter(pid,engine,kind='3D'):
    return f'pid_{pid}_luid_0x0_0x1234_phys_0_eng_{engine}_engtype_{kind}'

# Instances are processes, while the graph reports the busiest physical engine.
assert gpu_engine_percent([(counter(1,0),12.5),(counter(2,0),20.0),
                           (counter(1,1,'Compute'),18.0)])==32.5
assert gpu_engine_percent([(counter(1,0),0.0)])==0.0
assert gpu_engine_percent([('unavailable',99.0)]) is None

class FakeNvml:
    def nvmlDeviceGetUtilizationRates(self,_handle,out):
        ctypes.cast(out,ctypes.POINTER(_NvmlUtilization)).contents.gpu=37
        return 0
    def nvmlDeviceGetTemperature(self,_handle,_sensor,out):
        ctypes.cast(out,ctypes.POINTER(ctypes.c_uint)).contents.value=61
        return 0
    def nvmlShutdown(self):return 0

sensor=NvidiaNvmlTelemetry.__new__(NvidiaNvmlTelemetry)
sensor.dll=FakeNvml();sensor.handles=[ctypes.c_void_p(1)];sensor._lock=threading.Lock()
assert sensor.sample()=={'gpu_percent':37.0,'gpu_temp_c':61.0,
                         'sensor_provider':'NVIDIA NVML','gpu_util_provider':'NVIDIA NVML'}
sensor.close()
print('PASS PDH engine aggregation and NVML temperature/utilization sampling')
