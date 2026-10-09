"""Shared Funnel address must not impose one device's limit on all visitors."""
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import coordinator as c
c.load_cfg=lambda:{'rate_limit_per_minute':3,'compute_rate_limit_per_minute':6,
                   'anonymous_rate_per_minute':30,'global_rate_per_minute':50,
                   'registration_rate_per_minute':5}
def request(path='/api/public/status',token=''):
    return SimpleNamespace(path=path,headers={'X-Device-Token':token},client_address=('127.0.0.1',4321))
for _ in range(10):assert c.allowed_request(request())
for _ in range(3):assert c.allowed_request(request('/api/me','device-one'))
assert not c.allowed_request(request('/api/me','device-one'))
for _ in range(6):assert c.allowed_request(request('/api/heartbeat','compute-device'))
assert not c.allowed_request(request('/api/heartbeat','compute-device'))
assert c.allowed_request(request('/api/heartbeat','device-two'))
for _ in range(5):assert c.allowed_request(request('/api/register-challenge'))
assert not c.allowed_request(request('/api/register-challenge'))
for _ in range(80):c.allowed_request(request())
for i in range(50-len(c.GLOBAL_RATE)):
    assert c.allowed_request(request('/api/me',f'fill-device-{i}'))
assert len(c.GLOBAL_RATE)==50
assert not c.allowed_request(request('/api/heartbeat','new-device'))
print('FUNNEL_RATE_LIMITS_OK')

c.GLOBAL_RATE.clear();c.RATE.clear();c.REGISTER_RATE.clear()
r=request('/api/completions','batch-device')
assert c.allowed_request(r) and c.allowed_request(r,5)
assert not c.allowed_request(r)
assert len(c.RATE[c.rate_key(r)])==6
print('BATCH_RECEIPT_COST_OK')

c.GLOBAL_RATE.clear();c.RATE.clear();c.REGISTER_RATE.clear()
token='same-device'
compute=request('/api/work-blocks/result-groups',token)
normal=request('/api/me',token)
telemetry=request('/api/device/telemetry/v1',token)
assert len({c.rate_key(compute),c.rate_key(normal),c.rate_key(telemetry)})==3
for _ in range(6):assert c.allowed_request(compute)
assert not c.allowed_request(compute)
for _ in range(3):assert c.allowed_request(normal)
assert not c.allowed_request(normal)
assert c.allowed_request(telemetry)
assert len(c.GLOBAL_RATE)==10
c.GLOBAL_RATE.clear();c.RATE.clear();c.REGISTER_RATE.clear()
original_cfg=c.load_cfg
c.load_cfg=lambda:{**original_cfg(),'global_rate_per_minute':10}
for i in range(10):assert c.allowed_request(request('/api/me',f'device-{i}'))
assert not c.allowed_request(request('/api/heartbeat','new-device'))
c.load_cfg=original_cfg
print('RATE_NAMESPACE_SEPARATION_OK')
