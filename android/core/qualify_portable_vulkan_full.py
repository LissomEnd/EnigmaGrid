import pathlib,subprocess,json,os,time,ctypes,hashlib
P=pathlib.Path;repo=P(__file__).resolve().parents[2];base=P(r'C:/Users/azerj/Documents/ChatGPT/Enigma');out=base/'monitoring/recovery-20261012/portable-full-gpu';out.mkdir(exist_ok=True);tools=base/'tools';native=tools/'windows-native';jdk=tools/'android/jdk-17.0.20.1+1/bin';zig=next(native.glob('zig*/zig.exe'))
k=ctypes.windll.kernel32;k.GetCurrentProcess.restype=ctypes.c_void_p;k.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t];k.SetPriorityClass.argtypes=[ctypes.c_void_p,ctypes.c_uint32];h=k.GetCurrentProcess();assert k.SetProcessAffinityMask(h,1);assert k.SetPriorityClass(h,0x4000)
env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(native/'cache'));log=[]
def run(cmd,timeout=300):
 t=time.time();r=subprocess.run(list(map(str,cmd)),capture_output=True,text=True,timeout=timeout,env=env);log.append({'command':str(cmd[0]),'seconds':time.time()-t,'exit_code':r.returncode,'stdout':r.stdout,'stderr':r.stderr});(out/'report.json').write_text(json.dumps(log,indent=2));print(r.stdout,r.stderr,flush=True);r.check_returncode()
run([zig,'c++','-target','x86_64-windows-gnu','-std=c++17','-O2','-I',native/'include',repo/'android/core/portable_vulkan_full_host.cpp',out.parent/'vulkan.lib','-o',out/'full.exe'])
classes=out/'classes';classes.mkdir(exist_ok=True);run([jdk/'javac.exe','-d',classes,*list((repo/'android/core/src/main/java').rglob('*.java')),repo/'android/core/PortableVulkanFullFixture.java'])
f=json.loads((repo/'android/app/src/lab/assets/portable_fullunit_v1.json').read_text());states=f['pcg_states'];print(states[0].keys(),flush=True)
(out/'seeds.txt').write_text('\n'.join(str(x['state'])+' '+str(x.get('inc',x.get('increment'))) for x in states))
a=repo/'android/app/src/main/assets';cipher=json.loads((a/'portable_c3_scope_v1.json').read_text())['ciphertext']
for low,high in [(0,3),(4,10),(11,13)]:
 fixture=out/f'full-{low}-{high}.bin';run([jdk/'java.exe','-Xmx96m','-cp',classes,'org.enigmagrid.core.PortableVulkanFullFixture',a/'portable_qint_v1.bin',fixture,cipher,out/'seeds.txt',low,high]);run([out/'full.exe',out.parent/'portable_solver.spv',fixture]);log.append({'fixture':fixture.name,'sha256':hashlib.sha256(fixture.read_bytes()).hexdigest()});(out/'report.json').write_text(json.dumps(log,indent=2))
