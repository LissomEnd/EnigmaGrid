#ifndef ENIGMAGRID_NO_JNI
#include <jni.h>
#endif
#include <vulkan/vulkan.h>
#include "host_memory.h"
#include <vector>
#include <string>
#include <stdexcept>
#include <fstream>
#include <iostream>
#include <cstring>
#include <mutex>
#include <memory>
#include <array>
#include <algorithm>
#include <random>
#include <climits>
namespace {
void checked(VkResult result){if(result!=VK_SUCCESS)throw std::runtime_error("Vulkan operation failed: "+std::to_string(result));}
struct PortableCompute {
 bool inFlight=false; uint32_t trajectories=0; int parameters[12]{}; int completed=0;
    VkInstance instance{};VkDevice device{};VkPhysicalDevice physical{};VkQueue queue{};
    VkBuffer buffers[3]{};VkDeviceMemory memory[3]{};bool coherent[3]{};VkShaderModule shader{};
    VkDescriptorSetLayout layout{};VkPipelineLayout pipelineLayout{};VkPipeline pipeline{};
    VkDescriptorPool descriptors{};VkCommandPool commands{};VkFence fence{};
    VkDescriptorSet set{};VkCommandBuffer cmd{};bool initialized=false;uint32_t capacity=0;
    uint32_t recordedCount=0,recordedHashSize=0;
    ~PortableCompute(){
        if(inFlight)return;
        if(device){if(fence)vkDestroyFence(device,fence,nullptr);if(commands)vkDestroyCommandPool(device,commands,nullptr);if(descriptors)vkDestroyDescriptorPool(device,descriptors,nullptr);if(pipeline)vkDestroyPipeline(device,pipeline,nullptr);if(pipelineLayout)vkDestroyPipelineLayout(device,pipelineLayout,nullptr);if(layout)vkDestroyDescriptorSetLayout(device,layout,nullptr);if(shader)vkDestroyShaderModule(device,shader,nullptr);for(int i=0;i<3;i++){if(buffers[i])vkDestroyBuffer(device,buffers[i],nullptr);if(memory[i])vkFreeMemory(device,memory[i],nullptr);}vkDestroyDevice(device,nullptr);}
        if(instance)vkDestroyInstance(instance,nullptr);
    }
    void buffer(int index,VkDeviceSize bytes){
        VkPhysicalDeviceProperties limits;vkGetPhysicalDeviceProperties(physical,&limits);
        if(bytes>limits.limits.maxStorageBufferRange)throw std::runtime_error("GPU cohort storage range unavailable");
        VkBufferCreateInfo b{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};b.size=bytes;b.usage=VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT;b.sharingMode=VK_SHARING_MODE_EXCLUSIVE;checked(vkCreateBuffer(device,&b,nullptr,&buffers[index]));
        VkMemoryRequirements requirements;vkGetBufferMemoryRequirements(device,buffers[index],&requirements);
        VkPhysicalDeviceMemoryProperties properties;vkGetPhysicalDeviceMemoryProperties(physical,&properties);
        uint32_t type=enigmagrid::hostMemoryType(properties,requirements.memoryTypeBits);
        if(requirements.size>properties.memoryHeaps[properties.memoryTypes[type].heapIndex].size/2)throw std::runtime_error("GPU cohort memory heap unavailable");
        coherent[index]=(properties.memoryTypes[type].propertyFlags&VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)!=0;
        VkMemoryAllocateInfo a{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};a.allocationSize=requirements.size;a.memoryTypeIndex=type;checked(vkAllocateMemory(device,&a,nullptr,&memory[index]));checked(vkBindBufferMemory(device,buffers[index],memory[index],0));
    }
 void init(const std::vector<uint32_t>& code,uint32_t n){
 trajectories=n;
        VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};app.pApplicationName="EnigmaGrid";app.apiVersion=VK_API_VERSION_1_0;
        VkInstanceCreateInfo instanceInfo{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};instanceInfo.pApplicationInfo=&app;checked(vkCreateInstance(&instanceInfo,nullptr,&instance));
        uint32_t count=0;checked(vkEnumeratePhysicalDevices(instance,&count,nullptr));if(count==0||count>64)throw std::runtime_error("No Vulkan device");
        std::vector<VkPhysicalDevice> devices(count);checked(vkEnumeratePhysicalDevices(instance,&count,devices.data()));uint32_t family=UINT32_MAX;
        for(auto candidate:devices){
            VkPhysicalDeviceProperties props;vkGetPhysicalDeviceProperties(candidate,&props);if(props.limits.maxComputeWorkGroupInvocations<64||props.limits.maxComputeWorkGroupSize[0]<64)continue;
            uint32_t n=0;vkGetPhysicalDeviceQueueFamilyProperties(candidate,&n,nullptr);std::vector<VkQueueFamilyProperties> families(n);vkGetPhysicalDeviceQueueFamilyProperties(candidate,&n,families.data());
            for(uint32_t i=0;i<n;i++)if(families[i].queueCount&&(families[i].queueFlags&VK_QUEUE_COMPUTE_BIT)){physical=candidate;family=i;break;}
            if(physical)break;
        }
        if(!physical)throw std::runtime_error("No compute queue");
        float priority=0.25f;VkDeviceQueueCreateInfo q{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};q.queueFamilyIndex=family;q.queueCount=1;q.pQueuePriorities=&priority;
        VkDeviceCreateInfo d{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};d.queueCreateInfoCount=1;d.pQueueCreateInfos=&q;checked(vkCreateDevice(physical,&d,nullptr,&device));vkGetDeviceQueue(device,family,0,&queue);
        // Fixed bounded capacity supports every accepted row length without reallocations.
        capacity=n;
        const VkDeviceSize inputBytes=457673*4,outputBytes=n*16*5*4,scratchBytes=n*86*4;buffer(0,inputBytes);buffer(1,outputBytes);buffer(2,scratchBytes);
        VkShaderModuleCreateInfo s{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};s.codeSize=code.size()*4;s.pCode=code.data();checked(vkCreateShaderModule(device,&s,nullptr,&shader));
        VkDescriptorSetLayoutBinding bindings[3]{};for(int i=0;i<3;i++){bindings[i].binding=i;bindings[i].descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;bindings[i].descriptorCount=1;bindings[i].stageFlags=VK_SHADER_STAGE_COMPUTE_BIT;}
        VkDescriptorSetLayoutCreateInfo l{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};l.bindingCount=3;l.pBindings=bindings;checked(vkCreateDescriptorSetLayout(device,&l,nullptr,&layout));
        VkPipelineLayoutCreateInfo pl{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};pl.setLayoutCount=1;pl.pSetLayouts=&layout;VkPushConstantRange pc{VK_SHADER_STAGE_COMPUTE_BIT,0,48};pl.pushConstantRangeCount=1;pl.pPushConstantRanges=&pc;checked(vkCreatePipelineLayout(device,&pl,nullptr,&pipelineLayout));
        VkComputePipelineCreateInfo p{VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO};p.layout=pipelineLayout;p.stage.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;p.stage.stage=VK_SHADER_STAGE_COMPUTE_BIT;p.stage.module=shader;p.stage.pName="main";checked(vkCreateComputePipelines(device,VK_NULL_HANDLE,1,&p,nullptr,&pipeline));
        VkDescriptorPoolSize poolSize{VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,3};VkDescriptorPoolCreateInfo pool{VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO};pool.maxSets=1;pool.poolSizeCount=1;pool.pPoolSizes=&poolSize;checked(vkCreateDescriptorPool(device,&pool,nullptr,&descriptors));
        VkDescriptorSetAllocateInfo alloc{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO};alloc.descriptorPool=descriptors;alloc.descriptorSetCount=1;alloc.pSetLayouts=&layout;checked(vkAllocateDescriptorSets(device,&alloc,&set));
        VkDescriptorBufferInfo infos[3]={{buffers[0],0,inputBytes},{buffers[1],0,outputBytes},{buffers[2],0,scratchBytes}};VkWriteDescriptorSet writes[3]{};
        for(int i=0;i<3;i++){writes[i].sType=VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;writes[i].dstSet=set;writes[i].dstBinding=i;writes[i].descriptorCount=1;writes[i].descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;writes[i].pBufferInfo=&infos[i];}vkUpdateDescriptorSets(device,3,writes,0,nullptr);
        VkCommandPoolCreateInfo cp{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};cp.queueFamilyIndex=family;checked(vkCreateCommandPool(device,&cp,nullptr,&commands));
        VkCommandBufferAllocateInfo ca{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};ca.commandPool=commands;ca.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY;ca.commandBufferCount=1;checked(vkAllocateCommandBuffers(device,&ca,&cmd));
        VkFenceCreateInfo f{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};checked(vkCreateFence(device,&f,nullptr,&fence));
VkPhysicalDeviceProperties props;vkGetPhysicalDeviceProperties(physical,&props);if(props.limits.maxPushConstantsSize<48||props.limits.maxComputeWorkGroupCount[0]<(n+31)/32)throw std::runtime_error("Portable dispatch limits unavailable");}
 void dispatch(int* pc){checked(vkResetCommandPool(device,commands,0));VkCommandBufferBeginInfo b{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};checked(vkBeginCommandBuffer(cmd,&b));
 VkMemoryBarrier before{VK_STRUCTURE_TYPE_MEMORY_BARRIER};before.srcAccessMask=VK_ACCESS_HOST_WRITE_BIT|VK_ACCESS_SHADER_WRITE_BIT;before.dstAccessMask=VK_ACCESS_SHADER_READ_BIT|VK_ACCESS_SHADER_WRITE_BIT;vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_HOST_BIT|VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,0,1,&before,0,nullptr,0,nullptr);
 vkCmdBindPipeline(cmd,VK_PIPELINE_BIND_POINT_COMPUTE,pipeline);vkCmdBindDescriptorSets(cmd,VK_PIPELINE_BIND_POINT_COMPUTE,pipelineLayout,0,1,&set,0,nullptr);vkCmdPushConstants(cmd,pipelineLayout,VK_SHADER_STAGE_COMPUTE_BIT,0,48,pc);vkCmdDispatch(cmd,(trajectories+31)/32,1,1);
 VkMemoryBarrier after{VK_STRUCTURE_TYPE_MEMORY_BARRIER};after.srcAccessMask=VK_ACCESS_SHADER_WRITE_BIT;after.dstAccessMask=VK_ACCESS_HOST_READ_BIT;vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,1,&after,0,nullptr,0,nullptr);checked(vkEndCommandBuffer(cmd));checked(vkResetFences(device,1,&fence));VkSubmitInfo sub{VK_STRUCTURE_TYPE_SUBMIT_INFO};sub.commandBufferCount=1;sub.pCommandBuffers=&cmd;inFlight=true;checked(vkQueueSubmit(queue,1,&sub,fence));checked(vkWaitForFences(device,1,&fence,VK_TRUE,5000000000ULL));inFlight=false;}
};}
// Resident API is not activated by any worker. The isolated service must kill its
// process when poisoned() is true: a timed-out queue may still own all buffers.
namespace portable_backend {
std::mutex mutex;
std::unique_ptr<PortableCompute> active;
// One idle context, never an additional active session. Its fence has completed
// before it is cached. A shader change or larger cohort recreates the context.
std::unique_ptr<PortableCompute> idle;
std::vector<uint32_t> contextCode;
std::vector<int> contextReference;
void retire(){idle=std::move(active);}

bool poisoned=false;
int serial=1,lastClosed=0;
void require(bool ok,const char* message){if(!ok)throw std::invalid_argument(message);}
void abandon(){idle.reset();contextCode.clear();contextReference.clear();if(active){if(active->inFlight){poisoned=true;(void)active.release();}else active.reset();}}
PortableCompute& get(int id){require(!poisoned,"PortableGpuTimeout: process restart required");require(active&&id==serial,"Stale portable GPU session");return *active;}
void validate(const std::vector<int>& ref,const std::vector<int>& state,const std::vector<int>& p,const std::vector<uint32_t>& code){
 require(p.size()==12,"Portable parameter length");int n=p[0];require(n>=256&&n<=4096&&n%256==0&&p[1]==0&&p[2]==1,"Portable trajectory scope");require(p[3]>=0&&p[4]<=13&&p[3]<=p[4]&&p[5]>=1&&p[5]<=6,"Portable pair/kind bounds");
 bool kinds[7]{};for(int i=0;i<p[5];i++){require(p[6+i]>=1&&p[6+i]<=6&&!kinds[p[6+i]],"Portable kinds");kinds[p[6+i]]=true;}
 require(ref.size()==457673&&state.size()==size_t(n)*86,"Portable buffer lengths");
 for(int i=0;i<72;i++)require(ref[i]>=0&&ref[i]<26,"Portable ciphertext");
 for(int r=0;r<12;r++){bool seen[26]{};for(int i=0;i<26;i++){int v=ref[73+r*26+i];require(v>=0&&v<26&&!seen[v],"Portable electrical table");seen[v]=true;require(ref[385+r*26+v]==i,"Portable inverse table");}}
 for(size_t i=697;i<ref.size();i++)require(ref[i]>=2357&&ref[i]<=10924,"Portable quadgram bounds");
 for(int i=0;i<n;i++){const int* k=state.data()+i*86;require(k[0]>=0&&k[0]<1344,"Portable shell");for(int j=1;j<9;j++)require(k[j]>=0&&k[j]<26,"Portable ring/position");int pairs=0;for(int j=0;j<26;j++){int v=k[9+j];require(v>=0&&v<26&&k[9+v]==j,"Portable plugboard");pairs+=v!=j;}require(pairs/2>=p[3]&&pairs/2<=p[4],"Portable pair scope");for(int j=35;j<39;j++)require(k[j]>=0&&k[j]<26,"Portable reset position");require(k[39]>=1&&k[39]<=6&&kinds[k[39]],"Portable event kind");require(k[40]>=4&&k[40]<=68&&k[40]%4==0&&k[41]>=1&&k[41]<=4,"Portable event parameters");}
 require(code.size()>=5&&code.size()<=262144&&code[0]==0x07230203&&code[4]==0,"Portable SPIR-V header");for(size_t i=5;i<code.size();){size_t words=code[i]>>16;require(words&&words<=code.size()-i,"Portable SPIR-V instruction");i+=words;}
}
int begin(const std::vector<int>& ref,const std::vector<int>& input,const std::vector<int>& p,const std::vector<uint32_t>& code){std::lock_guard<std::mutex> lock(mutex);require(!poisoned,"PortableGpuTimeout: process restart required");require(!active,"Portable GPU session already active");validate(ref,input,p,code);
 if(serial==1){std::random_device random;serial=1+int(random()%1000000000u);}require(serial<INT_MAX,"Portable session identifiers exhausted");++serial;
 try{
 if(idle&&idle->capacity>=uint32_t(p[0])&&contextCode==code)active=std::move(idle);
 else {idle.reset();contextCode.clear();contextReference.clear();active.reset(new PortableCompute());active->init(code,p[0]);contextCode=code;}
 active->trajectories=p[0];active->completed=0;
 std::copy(p.begin(),p.end(),active->parameters);auto state=input;for(int i=0;i<p[0];i++)std::fill(state.begin()+i*86+42,state.begin()+(i+1)*86,0);if(contextReference!=ref){enigmagrid::uploadHost(active->device,active->memory[0],active->coherent[0],ref.data(),ref.size()*4);contextReference=ref;}enigmagrid::uploadHost(active->device,active->memory[2],active->coherent[2],state.data(),state.size()*4);active->dispatch(active->parameters);return serial;}catch(...){abandon();throw;}}
void step(int id,const std::vector<int>& tape,int iterations){std::lock_guard<std::mutex> lock(mutex);auto& c=get(id);try{require(iterations>=1&&iterations<=16&&c.completed+iterations<=512&&tape.size()==size_t(iterations)*c.trajectories*5,"Portable tape length");for(size_t i=0;i<tape.size();i+=5)require(tape[i]>=0&&tape[i]<100&&tape[i+1]>=0&&tape[i+1]<26&&tape[i+2]>=0&&tape[i+2]<26&&tape[i+3]>=0&&tape[i+3]<(1<<30)&&tape[i+4]>=0&&tape[i+4]<=38000,"Portable tape bounds");enigmagrid::uploadHost(c.device,c.memory[1],c.coherent[1],tape.data(),tape.size()*4);c.parameters[1]=iterations;c.parameters[2]=0;c.dispatch(c.parameters);c.completed+=iterations;}catch(...){abandon();throw;}}
std::vector<int> finish(int id){std::lock_guard<std::mutex> lock(mutex);auto& c=get(id);try{std::vector<int> state(c.trajectories*86);enigmagrid::downloadHost(c.device,c.memory[2],c.coherent[2],state.data(),state.size()*4);retire();lastClosed=id;return state;}catch(...){abandon();throw;}}
void close(int id){std::lock_guard<std::mutex> lock(mutex);if(id==lastClosed&&!active)return;get(id);retire();lastClosed=id;}
bool isPoisoned(){std::lock_guard<std::mutex> lock(mutex);return poisoned;}
}
#ifndef ENIGMAGRID_NO_JNI
namespace {
std::vector<int> integers(JNIEnv* e,jintArray a,size_t maximum){if(!a)throw std::invalid_argument("Missing portable array");jsize n=e->GetArrayLength(a);if(n<0||size_t(n)>maximum)throw std::invalid_argument("Oversized portable array");std::vector<int> v(n);e->GetIntArrayRegion(a,0,n,v.data());if(e->ExceptionCheck())throw std::runtime_error("Portable array copy failed");return v;}
void failure(JNIEnv* e,const std::exception& ex){if(!e->ExceptionCheck())e->ThrowNew(e->FindClass("java/lang/IllegalStateException"),portable_backend::isPoisoned()?"PortableGpuTimeout: process restart required":ex.what());}
}
extern "C" JNIEXPORT jint JNICALL Java_org_enigmagrid_android_VulkanBackend_portableBeginNative(JNIEnv* e,jclass,jintArray r,jintArray s,jintArray p,jbyteArray b){try{if(!b)throw std::invalid_argument("Missing portable shader");jsize n=e->GetArrayLength(b);if(n<20||n>1048576||n%4)throw std::invalid_argument("Portable shader size");std::vector<uint32_t> code(n/4);e->GetByteArrayRegion(b,0,n,reinterpret_cast<jbyte*>(code.data()));if(e->ExceptionCheck())return 0;return portable_backend::begin(integers(e,r,457673),integers(e,s,4096*86),integers(e,p,12),code);}catch(const std::exception& x){failure(e,x);return 0;}}
extern "C" JNIEXPORT void JNICALL Java_org_enigmagrid_android_VulkanBackend_portableStepNative(JNIEnv* e,jclass,jint id,jintArray t,jint n){try{portable_backend::step(id,integers(e,t,4096*16*5),n);}catch(const std::exception& x){failure(e,x);}}
extern "C" JNIEXPORT jintArray JNICALL Java_org_enigmagrid_android_VulkanBackend_portableFinishNative(JNIEnv* e,jclass,jint id){try{auto state=portable_backend::finish(id);auto a=e->NewIntArray(state.size());if(a)e->SetIntArrayRegion(a,0,state.size(),state.data());return a;}catch(const std::exception& x){failure(e,x);return nullptr;}}
extern "C" JNIEXPORT void JNICALL Java_org_enigmagrid_android_VulkanBackend_portableCloseNative(JNIEnv* e,jclass,jint id){try{portable_backend::close(id);}catch(const std::exception& x){failure(e,x);}}
extern "C" JNIEXPORT jboolean JNICALL Java_org_enigmagrid_android_VulkanBackend_portablePoisonedNative(JNIEnv*,jclass){return portable_backend::isPoisoned();}
#endif


