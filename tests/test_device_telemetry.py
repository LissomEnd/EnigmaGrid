"""Telemetry is bounded, marks unknown sensors absent and never holds receipts."""
import sys
import threading
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
from performance_telemetry import DeviceTelemetry

sender=DeviceTelemetry({},lambda:{},lambda _runtime:None,lambda:{},lambda _body:{},'0.5.0')
sender._add_sample({'cpu_percent':27.5,'gpu_metric_scope':'unknown'},
                   {'completed_jobs':0,'completed_units':0,'compute_seconds':0,
                    'pending_receipts':2,'backend':'CPU','status':'waiting'})
sender._add_sample({'cpu_percent':30,'gpu_metric_scope':'unknown','memory_bytes':123456},
                   {'completed_jobs':2,'completed_units':512,'compute_seconds':1.5,
                    'pending_receipts':2,'backend':'CPU','status':'computing'})
bucket=sender._finish(sender.current)
assert bucket['jobs_done']==2 and bucket['units_done']==512 and bucket['compute_ms']==1500
assert bucket['pending_receipts']==2 and bucket['cpu_percent']==28.75
assert bucket['memory_bytes']==123456
assert 'gpu_percent' not in bucket and 'gpu_temp_c' not in bucket
assert sender.ready.maxlen==12
ack=threading.Event();packets=[]
def accept(packet):
    packets.append(packet);ack.set();return {'ok':True,'accepted':1}
sender.capabilities=lambda:{'device_telemetry':'device_telemetry_v1'}
sender.post=accept
sender.ready.append((bucket,{'backend':'CPU','cpu_scope':'process','gpu_scope':'unknown',
                            'cpu_provider':'Win32 process tree','gpu_provider':''}))
thread=threading.Thread(target=sender._send_loop,daemon=True)
thread.start();sender.wake.set()
assert ack.wait(2),'Telemetry sender did not accept the negotiated capability'
sender.stop_event.set();sender.wake.set();thread.join(2)
assert len(packets)==1 and packets[0]['buckets']==[bucket]
assert 'device_id' not in packets[0] and 'token' not in packets[0]
server_now=1_800_000_000_000
clock=DeviceTelemetry({},lambda:{},lambda _runtime:None,lambda:{},lambda _body:{},'0.5.0')
clock.clock_anchor=(server_now,time.monotonic())
assert abs(clock._epoch_ms()-server_now)<1000, 'Diagnostic clock used local wall time'
retry=DeviceTelemetry({},lambda:{},lambda _runtime:None,
    lambda:{'device_telemetry':'device_telemetry_v1'},lambda _body:{},'0.5.0')
retry.ready.append((bucket,{'backend':'CPU','cpu_scope':'process','gpu_scope':'unknown',
                            'cpu_provider':'Win32 process tree','gpu_provider':''}))
attempts=[];first=threading.Event();second=threading.Event()
def partial_then_complete(packet):
    attempts.append((packet['session_id'],packet['seq'],dict(packet)))
    if len(attempts)==1:first.set();return {'ok':True,'accepted':0}
    second.set();return {'ok':True,'accepted':1}
retry.post=partial_then_complete
thread=threading.Thread(target=retry._send_loop,daemon=True);thread.start();retry.wake.set()
assert first.wait(2),'Missing first telemetry attempt'
retry.wake.set()
assert second.wait(2),'Partial acknowledgement did not retry'
retry.stop_event.set();retry.wake.set();thread.join(2)
assert attempts[0]==attempts[1], 'Retry changed session, sequence or bucket payload'
print('PASS disposable telemetry bucket counters and unsupported sensor omission')
