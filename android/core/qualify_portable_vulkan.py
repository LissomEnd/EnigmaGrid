"""Isolated experimental Vulkan parity harness; does not enroll or access live state."""
import argparse,pathlib,subprocess,json,os,time,hashlib,ctypes
# Compiler and reference children inherit low priority and two-core affinity.
if os.name == "nt":
 k=ctypes.windll.kernel32;k.GetCurrentProcess.restype=ctypes.c_void_p
 k.SetPriorityClass.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
 k.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)]
 k.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
 h=k.GetCurrentProcess();pm=ctypes.c_size_t();sm=ctypes.c_size_t()
 if not k.SetPriorityClass(h,0x4000) or not k.GetProcessAffinityMask(h,ctypes.byref(pm),ctypes.byref(sm)):raise OSError("Unable to bound qualification process")
 bits=[1<<i for i in range(64) if pm.value&(1<<i)]
 if not k.SetProcessAffinityMask(h,sum(bits[:2])):raise OSError("Unable to bound qualification affinity")
P=pathlib.Path
repo=P(__file__).resolve().parents[2]
a=argparse.ArgumentParser();a.add_argument('--tools',type=P,required=True);a.add_argument('--output',type=P,required=True);opts=a.parse_args();out=opts.output;out.mkdir(parents=True,exist_ok=True)
native=opts.tools/'windows-native';jdk=opts.tools/'android/jdk-17.0.20.1+1/bin';zig=next(native.glob('zig*/zig.exe'))
source=(repo/'android/app/src/main/cpp/vulkan_solver.cpp').read_text();start=source.index('        VkApplicationInfo app');end=source.index('        initialized=true;')
init=source[start:end].replace('capacity=input[0]>128?512:128;','capacity=256;').replace('const VkDeviceSize inputBytes=(5+capacity*72*26+72*3)*4,outputBytes=capacity*1667*4,scratchBytes=capacity*41384*4;','const VkDeviceSize inputBytes=457673*4,outputBytes=256*32*5*4,scratchBytes=256*86*4;')
init=init.replace('pl.pSetLayouts=&layout;','pl.pSetLayouts=&layout;VkPushConstantRange pc{VK_SHADER_STAGE_COMPUTE_BIT,0,48};pl.pushConstantRangeCount=1;pl.pPushConstantRanges=&pc;')
head=source[source.index('namespace {'):source.index('    std::vector<uint32_t> run(')]
cpp='#define ENIGMAGRID_NO_JNI\n#include <vulkan/vulkan.h>\n#include "host_memory.h"\n#include <vector>\n#include <string>\n#include <stdexcept>\n#include <fstream>\n#include <iostream>\n#include <cstring>\n'+head+' void init(const std::vector<uint32_t>& code){\n'+init+'''VkPhysicalDeviceProperties props;vkGetPhysicalDeviceProperties(physical,&props);std::cout<<"device="<<props.deviceName<<" driver="<<props.driverVersion<<" vendor="<<props.vendorID<<"\\n";}
 void dispatch(int* pc){checked(vkResetCommandPool(device,commands,0));VkCommandBufferBeginInfo b{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};checked(vkBeginCommandBuffer(cmd,&b));
 VkMemoryBarrier before{VK_STRUCTURE_TYPE_MEMORY_BARRIER};before.srcAccessMask=VK_ACCESS_HOST_WRITE_BIT|VK_ACCESS_SHADER_WRITE_BIT;before.dstAccessMask=VK_ACCESS_SHADER_READ_BIT|VK_ACCESS_SHADER_WRITE_BIT;vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_HOST_BIT|VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,0,1,&before,0,nullptr,0,nullptr);
 vkCmdBindPipeline(cmd,VK_PIPELINE_BIND_POINT_COMPUTE,pipeline);vkCmdBindDescriptorSets(cmd,VK_PIPELINE_BIND_POINT_COMPUTE,pipelineLayout,0,1,&set,0,nullptr);vkCmdPushConstants(cmd,pipelineLayout,VK_SHADER_STAGE_COMPUTE_BIT,0,48,pc);vkCmdDispatch(cmd,8,1,1);
 VkMemoryBarrier after{VK_STRUCTURE_TYPE_MEMORY_BARRIER};after.srcAccessMask=VK_ACCESS_SHADER_WRITE_BIT;after.dstAccessMask=VK_ACCESS_HOST_READ_BIT;vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,1,&after,0,nullptr,0,nullptr);checked(vkEndCommandBuffer(cmd));checked(vkResetFences(device,1,&fence));VkSubmitInfo sub{VK_STRUCTURE_TYPE_SUBMIT_INFO};sub.commandBufferCount=1;sub.pCommandBuffers=&cmd;checked(vkQueueSubmit(queue,1,&sub,fence));checked(vkWaitForFences(device,1,&fence,VK_TRUE,5000000000ULL));}
};}
std::vector<uint32_t> read(std::ifstream& f,size_t n){std::vector<uint32_t> v(n);if(!f.read((char*)v.data(),n*4))throw std::runtime_error("short fixture");return v;}
int main(int argc,char**argv){try{if(argc!=3)return 2;std::ifstream s(argv[1],std::ios::binary|std::ios::ate);size_t n=s.tellg();s.seekg(0);auto code=read(s,n/4);SolverCompute c;c.init(code);std::ifstream f(argv[2],std::ios::binary);auto ref=read(f,457673);enigmagrid::uploadHost(c.device,c.memory[0],c.coherent[0],ref.data(),ref.size()*4);int cases=read(f,1)[0];for(int test=0;test<cases;test++){auto p=read(f,4);auto state=read(f,256*86);enigmagrid::uploadHost(c.device,c.memory[2],c.coherent[2],state.data(),state.size()*4);for(int chunk=0;chunk<p[3];chunk++){int count=read(f,1)[0];if(count){auto tape=read(f,count*256*5);enigmagrid::uploadHost(c.device,c.memory[1],c.coherent[1],tape.data(),tape.size()*4);}auto expected=read(f,256*86);int pc[12]={256,count,chunk==0,(int)p[0],(int)p[1],1,(int)p[2],0,0,0,0,0};c.dispatch(pc);enigmagrid::downloadHost(c.device,c.memory[2],c.coherent[2],state.data(),state.size()*4);for(size_t j=0;j<state.size();j++)if(state[j]!=expected[j]){std::cerr<<"MISMATCH case "<<test<<" chunk "<<chunk<<" index "<<j<<" got "<<state[j]<<" expected "<<expected[j]<<"\\n";return 1;}}std::cout<<"PASS case "<<test<<std::endl;}return 0;}catch(std::exception&e){std::cerr<<e.what();return 2;}}
'''
(out/'portable_host.cpp').write_text(cpp)
definition=(native/'vulkan-1.def').read_text()+'\nvkCmdPushConstants\n';(out/'vulkan.def').write_text(definition)
env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(native/'cache'))
subprocess.run([str(zig),'dlltool','-m','i386:x86-64','-d',str(out/'vulkan.def'),'-l',str(out/'vulkan.lib')],check=True,env=env)
subprocess.run([str(zig),'c++','-target','x86_64-windows-gnu','-std=c++17','-O2','-I',str(native/'include'),'-I',str(repo/'android/app/src/main/cpp'),str(out/'portable_host.cpp'),str(out/'vulkan.lib'),'-o',str(out/'portable_host.exe')],check=True,env=env)
classes=out/'classes';classes.mkdir(exist_ok=True)
subprocess.run([str(jdk/'javac.exe'),'-d',str(classes),*map(str,(repo/'android/core/src/main/java').rglob('*.java')),str(repo/'android/core/PortableVulkanFixture.java')],check=True)
assets=repo/'android/app/src/main/assets';scope=json.loads((assets/'portable_c3_scope_v1.json').read_text())
subprocess.run([str(jdk/'java.exe'),'-Xmx128m','-cp',str(classes),'org.enigmagrid.core.PortableVulkanFixture',str(assets/'portable_qint_v1.bin'),str(out/'fixture.bin'),scope['ciphertext']],check=True)
started=time.time()
r=subprocess.run([str(out/'portable_host.exe'),str(out/'portable_solver.spv'),str(out/'fixture.bin')],capture_output=True,text=True,timeout=180)
(out/'vulkan-parity-result.json').write_text(json.dumps({'exit_code':r.returncode,'stdout':r.stdout,'stderr':r.stderr,'duration_seconds':time.time()-started,'scope':'18 profiles, 256 trajectories, checkpoints 0/1/8/32 of512 iterations; full resident state, NOT full unit or production qualification','shader_sha256':hashlib.sha256((out/'portable_solver.spv').read_bytes()).hexdigest(),'fixture_sha256':hashlib.sha256((out/'fixture.bin').read_bytes()).hexdigest()},indent=2));print(r.stdout,r.stderr);r.check_returncode()

