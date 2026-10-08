import sys,tempfile,json,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
from bounded_gpu_qualification import load_qualification,sha256
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);files=[root/name for name in ('native.dll','shader.spv','adapter.py')]
    for f in files:f.write_bytes(f.name.encode())
    lib,shader,adapter=files;record=root/'qualification.json';loads=[]
    data=dict(format='bounded-vulkan-qualification-v2',hardware='local-hash',library_sha256=sha256(lib),shader_sha256=sha256(shader),adapter_sha256=sha256(adapter),parity_passed=True,core_checks=657,cpu_workers=2,gpu_cores=64,scope=[128,24,'clean',10,5000,64,256],warm_trials=[dict(receipt_equal=True,cpu_seconds=.1,hybrid_seconds=.08,domain_start=(i+3)*128) for i in range(3)])
    def factory(*args):loads.append(args);return lambda data:[]
    def load(value,hardware='local-hash'):
        record.write_text(json.dumps(value));return load_qualification(record,lib,shader,hardware,adapter=adapter,factory=factory)
    assert load(data)['qualified'] and len(loads)==1
    assert load(data,'other-machine') is None
    for field,value in [('parity_passed',False),('core_checks',656),('cpu_workers',True),('gpu_cores',129),('adapter_sha256','changed'),('shader_sha256','changed'),('library_sha256','changed')]:
        bad=copy.deepcopy(data);bad[field]=value;assert load(bad) is None
    for field,value in [('domain_start',0),('domain_start',True),('receipt_equal',False),('hybrid_seconds',.099),('cpu_seconds',float('nan')),('hybrid_seconds',True)]:
        bad=copy.deepcopy(data);bad['warm_trials'][1][field]=value;assert load(bad) is None
    assert len(loads)==1,'Invalid qualification loaded native code'
print('PASS qualification binds hardware and all code assets; insufficient parity, unstable gain and invalid metrics do not load DLL')
