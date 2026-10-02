"""Shared Funnel address must not impose one device's limit on all visitors."""
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import coordinator as c
c.load_cfg=lambda:{'rate_limit_per_minute':3,'anonymous_rate_per_minute':30,
                   'global_rate_per_minute':50,'registration_rate_per_minute':5}
def request(path='/api/public/status',token=''):
    return SimpleNamespace(path=path,headers={'X-Device-Token':token},client_address=('127.0.0.1',4321))
for _ in range(10):assert c.allowed_request(request())
for _ in range(3):assert c.allowed_request(request('/api/heartbeat','device-one'))
assert not c.allowed_request(request('/api/heartbeat','device-one'))
assert c.allowed_request(request('/api/heartbeat','device-two'))
for _ in range(5):assert c.allowed_request(request('/api/register-challenge'))
assert not c.allowed_request(request('/api/register-challenge'))
for _ in range(80):c.allowed_request(request())
assert len(c.GLOBAL_RATE)<=50
assert not c.allowed_request(request('/api/heartbeat','new-device'))
print('FUNNEL_RATE_LIMITS_OK')
