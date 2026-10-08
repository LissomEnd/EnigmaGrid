"""Windows hardware telemetry used by the local operations monitor.

AMD ADL is used when available. Unsupported sensors remain None; no value is
fabricated and failure to read telemetry never stops the coordinator.
"""
import ctypes
import os
import threading
import time

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


class SystemTelemetry(HardwareTelemetry):
    """Host utilization plus hardware sensors for the Windows worker UI."""
    def __init__(self):
        super().__init__();self.previous_cpu=None;self.process_cpu=ProcessTreeCpu()
    def sample(self):
        values=super().sample()
        if os.name!='nt':return values
        try:
            idle,kernel,user=ctypes.c_ulonglong(),ctypes.c_ulonglong(),ctypes.c_ulonglong()
            if ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle),ctypes.byref(kernel),ctypes.byref(user)):
                current=(idle.value,kernel.value+user.value)
                if self.previous_cpu:
                    di=current[0]-self.previous_cpu[0];dt=current[1]-self.previous_cpu[1]
                    if dt>0:values['system_cpu_percent']=round(max(0,min(100,100*(1-di/dt))),2)
                self.previous_cpu=current
        except Exception:pass
        try:
            class Memory(ctypes.Structure):
                _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(name,ctypes.c_ulonglong) for name in
                    ('total','available','page_total','page_available','virtual_total','virtual_available','extended')]
            memory=Memory();memory.length=ctypes.sizeof(memory)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
                values['memory_percent']=float(memory.load)
                values['available_gb']=round(memory.available/1024**3,2)
        except Exception:pass
        try:values['cpu_percent']=self.process_cpu.sample()
        except Exception:values['cpu_percent']=None
        values['gpu_metric_scope']='system'
        values['time']=time.time()
        return values


class ProcessTreeCpu:
    """Read-only aggregate CPU time for this worker and its descendants."""
    def __init__(self):self.previous={};self.at=None
    def sample(self):
        if os.name!='nt':return None
        from ctypes import wintypes as w
        class Entry(ctypes.Structure):
            _fields_=[('size',w.DWORD),('usage',w.DWORD),('pid',w.DWORD),('heap',ctypes.c_size_t),('module',w.DWORD),('threads',w.DWORD),('parent',w.DWORD),('priority',w.LONG),('flags',w.DWORD),('exe',w.WCHAR*260)]
        k=ctypes.WinDLL('kernel32',use_last_error=True)
        k.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD];k.CreateToolhelp32Snapshot.restype=w.HANDLE
        k.Process32FirstW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)];k.Process32NextW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)]
        k.CloseHandle.argtypes=[w.HANDLE]
        k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
        k.GetProcessTimes.argtypes=[w.HANDLE]+[ctypes.POINTER(ctypes.c_ulonglong)]*4
        snapshot=k.CreateToolhelp32Snapshot(2,0)
        if snapshot==ctypes.c_void_p(-1).value:return None
        parents={};entry=Entry();entry.size=ctypes.sizeof(entry)
        try:
            more=k.Process32FirstW(snapshot,ctypes.byref(entry))
            while more:
                parents[entry.pid]=entry.parent;more=k.Process32NextW(snapshot,ctypes.byref(entry))
        finally:k.CloseHandle(snapshot)
        descendants={os.getpid()}
        while True:
            found={pid for pid,parent in parents.items() if parent in descendants}
            if found<=descendants:break
            descendants.update(found)
        current={}
        for pid in descendants:
            handle=k.OpenProcess(0x1000,False,pid)
            if not handle:continue
            try:
                created,exited,kernel,user=(ctypes.c_ulonglong() for _ in range(4))
                if k.GetProcessTimes(handle,*[ctypes.byref(x) for x in (created,exited,kernel,user)]):current[(pid,created.value)]=(kernel.value+user.value)/1e7
            finally:k.CloseHandle(handle)
        now=time.monotonic();value=None
        if self.at is not None and now>self.at:
            seconds=sum(max(0,total-self.previous[key]) for key,total in current.items() if key in self.previous)
            value=max(0,min(100,100*seconds/(now-self.at)/max(1,os.cpu_count() or 1)))
        self.previous=current;self.at=now;return value
