"""Local-only bounded Vulkan qualification, invalidated by hardware/code changes."""
import hashlib,json,math,platform,subprocess
from pathlib import Path

FORMAT = 'bounded-vulkan-qualification-v2'

def sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def hardware_fingerprint():
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\Cryptography') as key:
        machine=winreg.QueryValueEx(key,'MachineGuid')[0]
    command='Get-CimInstance Win32_VideoController | Sort-Object PNPDeviceID | Select-Object PNPDeviceID,DriverVersion | ConvertTo-Json -Compress'
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],capture_output=True,text=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=True)
    devices=json.loads(result.stdout)
    if not devices:raise ValueError('GPU inventory unavailable')
    return hashlib.sha256(json.dumps([machine,platform.platform(),platform.processor(),devices],sort_keys=True).encode()).hexdigest()

def _load_checked(record,library,shader,fingerprint,*,adapter,factory=None,require_speed=True):
    data=json.loads(Path(record).read_text(encoding='utf-8'))
    if data.get('format')!=FORMAT or data.get('hardware')!=fingerprint:return None
    if data.get('library_sha256')!=sha256(library) or data.get('shader_sha256')!=sha256(shader) or data.get('adapter_sha256')!=sha256(adapter):return None
    if data.get('parity_passed') is not True or type(data.get('core_checks')) is not int or data['core_checks']<657:return None
    workers=data.get('cpu_workers');gpu=data.get('gpu_cores')
    if type(workers) is not int or not 1<=workers<=32 or type(gpu) is not int or not 1<=gpu<=128:return None
    scope=data.get('scope')
    if scope!=[128,24,'clean',10,5000,64,256]:return None
    trials=data.get('warm_trials')
    if not isinstance(trials,list) or len(trials)!=3:return None
    for index,trial in enumerate(trials):
        if not isinstance(trial,dict) or trial.get('receipt_equal') is not True:return None
        if type(trial.get('domain_start')) is not int or trial['domain_start']!=(index+3)*128:return None
        cpu,hybrid=trial.get('cpu_seconds'),trial.get('hybrid_seconds')
        if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in (cpu,hybrid)):return None
        if require_speed and hybrid>cpu*.95:return None
    if factory is None:
        from search.vulkan_bounded import NativeSolver
        factory=NativeSolver
    return dict(qualified=True,cpu_workers=workers,gpu_cores=gpu,scope=tuple(scope),dispatch=factory(library,shader))


def load_qualification(record,library,shader,fingerprint,*,adapter,factory=None):
    return _load_checked(record,library,shader,fingerprint,adapter=adapter,factory=factory)


def load_parity(record,library,shader,fingerprint,*,adapter,factory=None):
    """Load exact native parity despite a failed intra-job speed comparison.

    This is only a prerequisite for a separate aggregate-throughput proof.
    It must never activate GPU production work by itself.
    """
    return _load_checked(record,library,shader,fingerprint,adapter=adapter,
                         factory=factory,require_speed=False)


def qualify(library,shader,adapter,workers,*,checkpoint=lambda:None):
    """Bounded device-local qualification. Caller owns pause/thermal/stop policy."""
    import time
    from search.vulkan_bounded import NativeSolver,HybridSolverMap,pack,unpack
    from search.bounded_crib import crib_rows
    from search.crib_pilot import core_at
    from search.c3_models import solve_board
    from search.crib_work import run
    from search.process_map import OrderedProcessMap
    if type(workers) is not int or not 1<=workers<=32:raise ValueError('Invalid CPU worker count')
    checkpoint()
    native=NativeSolver(library,shader)
    report=dict(format=FORMAT,hardware=hardware_fingerprint(),
        library_sha256=sha256(library),shader_sha256=sha256(shader),adapter_sha256=sha256(adapter),
        cpu_workers=workers,gpu_cores=64,scope=[128,24,'clean',10,5000,64,256],
        parity_passed=False,core_checks=0,warm_trials=[])
    for count in (1,8,64):
        for length in (1,5,24):
            checkpoint()
            rows=[crib_rows(core_at(i),0,length) for i in range(count)]
            edges=[(i,0,rows[0][i][0]) for i in range(length)]
            for nodes in (1,32,5000):
                checkpoint()
                packed=pack(rows,edges,10,nodes,64)
                actual=unpack(native(packed),packed)
                expected=[]
                for row in rows:
                    checkpoint();expected.append(solve_board(row,edges,max_pairs=10,node_limit=nodes,solution_limit=64))
                if actual!=expected:raise ValueError('Vulkan core parity failed')
                report['core_checks']+=count
    with OrderedProcessMap(workers,chunk_size=8,check=checkpoint) as cpu:
        shares=(16,32,64,96,128)
        hybrids={share:HybridSolverMap(native,cpu,share,checkpoint=checkpoint) for share in shares}
        comparisons={share:[] for share in shares}
        try:
            for trial in range(4):
                checkpoint()
                start=max(0,trial-1)*128
                job=dict(engine='bounded_crib_v1',ciphertext='A'*72,crib='B'*24,offset=0,
                    core_indices=list(range(start,start+128)),model='clean',pairs=10,
                    budgets=dict(node_limit=5000,board_limit=64,completion_limit=256,candidate_limit=64))
                lease=dict(engine='bounded_crib_v1',start_unit=0,end_unit=1,config=dict(job=job,requires=['cpu','bounded_crib_v1']))
                reference=run(lease,checkpoint=lambda *args:checkpoint())
                paths=[(0,cpu)]+list(hybrids.items())
                # Rotate order to avoid always giving one backend the warmest slot.
                rotation=trial%len(paths);paths=paths[rotation:]+paths[:rotation]
                timings={}
                for share,backend in paths:
                    checkpoint();began=time.perf_counter()
                    actual=run(lease,checkpoint=lambda *args:checkpoint(),solve_map=backend)
                    timings[share]=time.perf_counter()-began
                    if actual!=reference or any(h.failed for h in hybrids.values()):
                        raise ValueError('Vulkan full receipt parity or backend failed')
                if trial:
                    for share in shares:
                        comparisons[share].append(dict(receipt_equal=True,cpu_seconds=timings[0],hybrid_seconds=timings[share]))
            qualified=[share for share in shares if all(row['hybrid_seconds']<=row['cpu_seconds']*.95 for row in comparisons[share])]
            selected=min(qualified or shares,key=lambda share:sum(row['hybrid_seconds'] for row in comparisons[share]))
            report['gpu_cores']=selected
            report['partition_trials']={str(share):rows for share,rows in comparisons.items()}
            # Selection timings cannot also prove the selected partition wins.
            # Validate on disjoint mechanical domains without selecting again.
            report['warm_trials']=[]
            for trial in range(3):
                checkpoint()
                start=(trial+3)*128
                job=dict(job,core_indices=list(range(start,start+128)))
                lease=dict(lease,config=dict(job=job,requires=['cpu','bounded_crib_v1']))
                reference=run(lease,checkpoint=lambda *args:checkpoint())
                paths=[('cpu_seconds',cpu),('hybrid_seconds',hybrids[selected])]
                if trial%2:paths.reverse()
                row={'receipt_equal':True,'domain_start':start}
                for name,backend in paths:
                    checkpoint();began=time.perf_counter()
                    actual=run(lease,checkpoint=lambda *args:checkpoint(),solve_map=backend)
                    row[name]=time.perf_counter()-began
                    if actual!=reference or hybrids[selected].failed:
                        raise ValueError('Vulkan holdout receipt parity or backend failed')
                report['warm_trials'].append(row)
        finally:
            for hybrid in hybrids.values():hybrid.close()
    checkpoint();report['parity_passed']=True
    return report


def save_qualification(path,report):
    from file_state import atomic_write
    atomic_write(path,json.dumps(report,allow_nan=False,sort_keys=True).encode('utf-8'))
