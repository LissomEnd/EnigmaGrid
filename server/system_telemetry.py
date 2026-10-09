"""Windows hardware telemetry used by the local operations monitor.

AMD ADL is used when available. Unsupported sensors remain None; no value is
fabricated and failure to read telemetry never stops the coordinator.
"""
import ctypes
import os
import threading

class _Sensor(ctypes.Structure):
    _fields_=[("supported",ctypes.c_int),("value",ctypes.c_int)]

class _PMLogOutput(ctypes.Structure):
    _fields_=[("size",ctypes.c_int),("sensors",_Sensor*256)]

class AmdAdlTelemetry:
    # ADLPMLogSensor values used by current AMD Windows drivers.
    GFX_ACTIVITY=19
    TEMP_EDGE=8
    TEMP_HOTSPOT=27
    TEMP_GFX=28
    TEMP_CPU=32

    def __init__(self):
        self.dll=None;self.context=ctypes.c_void_p();self.adapters=[]
        self._buffers=[];self._lock=threading.Lock();self._allocator=None
        if os.name!="nt":return
        for name in ("atiadlxx.dll","amdadlx64.dll"):
            try:self.dll=ctypes.WinDLL(name);break
            except OSError:pass
        if self.dll is None:return
        allocator_type=ctypes.WINFUNCTYPE(ctypes.c_void_p,ctypes.c_int)
        def allocate(size):
            buffer=ctypes.create_string_buffer(max(1,int(size)))
            self._buffers.append(buffer)
            return ctypes.cast(buffer,ctypes.c_void_p).value
        self._allocator=allocator_type(allocate)
        try:
            create=self.dll.ADL2_Main_Control_Create
            create.argtypes=[allocator_type,ctypes.c_int,ctypes.POINTER(ctypes.c_void_p)]
            create.restype=ctypes.c_int
            if create(self._allocator,1,ctypes.byref(self.context))!=0:
                self.dll=None;return
            number=ctypes.c_int()
            get_count=self.dll.ADL2_Adapter_NumberOfAdapters_Get
            get_count.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_int)]
            get_count.restype=ctypes.c_int
            if get_count(self.context,ctypes.byref(number))!=0:return
            active=self.dll.ADL2_Adapter_Active_Get
            active.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.POINTER(ctypes.c_int)]
            active.restype=ctypes.c_int
            self.adapters=[]
            for index in range(max(0,number.value)):
                is_active=ctypes.c_int()
                if active(self.context,index,ctypes.byref(is_active))==0 and is_active.value:
                    self.adapters.append(index)
            if not self.adapters:self.adapters=list(range(max(0,number.value)))
            query=self.dll.ADL2_New_QueryPMLogData_Get
            query.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.POINTER(_PMLogOutput)]
            query.restype=ctypes.c_int
        except Exception:
            self.close()

    @staticmethod
    def _valid(sensor,minimum,maximum):
        return bool(sensor.supported) and minimum<=sensor.value<=maximum

    def sample(self):
        if self.dll is None or not self.context:return {}
        gpu=[],[];cpu=[]
        gpu_activity,gpu_temps=gpu
        with self._lock:
            try:
                query=self.dll.ADL2_New_QueryPMLogData_Get
                for index in self.adapters:
                    output=_PMLogOutput();output.size=ctypes.sizeof(_PMLogOutput)
                    if query(self.context,index,ctypes.byref(output))!=0:continue
                    activity=output.sensors[self.GFX_ACTIVITY]
                    if self._valid(activity,0,100):gpu_activity.append(float(activity.value))
                    cpu_temp=output.sensors[self.TEMP_CPU]
                    if self._valid(cpu_temp,-20,150):cpu.append(float(cpu_temp.value))
                    for sensor_id in (self.TEMP_GFX,self.TEMP_HOTSPOT,self.TEMP_EDGE):
                        sensor=output.sensors[sensor_id]
                        if self._valid(sensor,-20,150):gpu_temps.append(float(sensor.value))
            except Exception:return {}
        return {
            "gpu_percent":max(gpu_activity) if gpu_activity else None,
            "cpu_temp_c":max(cpu) if cpu else None,
            "gpu_temp_c":max(gpu_temps) if gpu_temps else None,
            "sensor_provider":"AMD ADL" if (gpu_activity or cpu or gpu_temps) else None,
        }

    def close(self):
        if self.dll is not None and self.context:
            try:
                destroy=self.dll.ADL2_Main_Control_Destroy
                destroy.argtypes=[ctypes.c_void_p];destroy.restype=ctypes.c_int
                destroy(self.context)
            except Exception:pass
        self.context=ctypes.c_void_p();self.dll=None

    def __del__(self):
        self.close()

class HardwareTelemetry:
    def __init__(self):
        self.amd=AmdAdlTelemetry()
    def sample(self):
        values=self.amd.sample()
        return {k:v for k,v in values.items() if v is not None}
