#ifndef ENIGMAGRID_NO_JNI
#include <jni.h>
#endif
#include "solver_api.h"
#include "host_memory.h"
#include <vulkan/vulkan.h>
#include <vector>
#include <string>
#include <stdexcept>
#include <cstring>
#include <memory>
#include <mutex>

namespace {
void checked(VkResult result){if(result!=VK_SUCCESS)throw std::runtime_error("Vulkan operation failed: "+std::to_string(result));}
struct SolverCompute {
    VkInstance instance{};VkDevice device{};VkPhysicalDevice physical{};VkQueue queue{};
    VkBuffer buffers[3]{};VkDeviceMemory memory[3]{};bool coherent[3]{};VkShaderModule shader{};
    VkDescriptorSetLayout layout{};VkPipelineLayout pipelineLayout{};VkPipeline pipeline{};
    VkDescriptorPool descriptors{};VkCommandPool commands{};VkFence fence{};
    VkDescriptorSet set{};VkCommandBuffer cmd{};bool initialized=false;uint32_t capacity=0;
    uint32_t recordedCount=0,recordedHashSize=0;
    ~SolverCompute(){
        if(device){vkDeviceWaitIdle(device);if(fence)vkDestroyFence(device,fence,nullptr);if(commands)vkDestroyCommandPool(device,commands,nullptr);if(descriptors)vkDestroyDescriptorPool(device,descriptors,nullptr);if(pipeline)vkDestroyPipeline(device,pipeline,nullptr);if(pipelineLayout)vkDestroyPipelineLayout(device,pipelineLayout,nullptr);if(layout)vkDestroyDescriptorSetLayout(device,layout,nullptr);if(shader)vkDestroyShaderModule(device,shader,nullptr);for(int i=0;i<3;i++){if(buffers[i])vkDestroyBuffer(device,buffers[i],nullptr);if(memory[i])vkFreeMemory(device,memory[i],nullptr);}vkDestroyDevice(device,nullptr);}
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
    std::vector<uint32_t> run(const std::vector<uint32_t>& input,const std::vector<uint32_t>& code){
        if(!initialized){
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
        capacity=input[0]>128?512:128;
        const VkDeviceSize inputBytes=(5+capacity*72*26+72*3)*4,outputBytes=capacity*1667*4,scratchBytes=capacity*41384*4;buffer(0,inputBytes);buffer(1,outputBytes);buffer(2,scratchBytes);
        VkShaderModuleCreateInfo s{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};s.codeSize=code.size()*4;s.pCode=code.data();checked(vkCreateShaderModule(device,&s,nullptr,&shader));
        VkDescriptorSetLayoutBinding bindings[3]{};for(int i=0;i<3;i++){bindings[i].binding=i;bindings[i].descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;bindings[i].descriptorCount=1;bindings[i].stageFlags=VK_SHADER_STAGE_COMPUTE_BIT;}
        VkDescriptorSetLayoutCreateInfo l{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};l.bindingCount=3;l.pBindings=bindings;checked(vkCreateDescriptorSetLayout(device,&l,nullptr,&layout));
        VkPipelineLayoutCreateInfo pl{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};pl.setLayoutCount=1;pl.pSetLayouts=&layout;checked(vkCreatePipelineLayout(device,&pl,nullptr,&pipelineLayout));
        VkComputePipelineCreateInfo p{VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO};p.layout=pipelineLayout;p.stage.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;p.stage.stage=VK_SHADER_STAGE_COMPUTE_BIT;p.stage.module=shader;p.stage.pName="main";checked(vkCreateComputePipelines(device,VK_NULL_HANDLE,1,&p,nullptr,&pipeline));
        VkDescriptorPoolSize poolSize{VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,3};VkDescriptorPoolCreateInfo pool{VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO};pool.maxSets=1;pool.poolSizeCount=1;pool.pPoolSizes=&poolSize;checked(vkCreateDescriptorPool(device,&pool,nullptr,&descriptors));
        VkDescriptorSetAllocateInfo alloc{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO};alloc.descriptorPool=descriptors;alloc.descriptorSetCount=1;alloc.pSetLayouts=&layout;checked(vkAllocateDescriptorSets(device,&alloc,&set));
        VkDescriptorBufferInfo infos[3]={{buffers[0],0,inputBytes},{buffers[1],0,outputBytes},{buffers[2],0,scratchBytes}};VkWriteDescriptorSet writes[3]{};
        for(int i=0;i<3;i++){writes[i].sType=VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;writes[i].dstSet=set;writes[i].dstBinding=i;writes[i].descriptorCount=1;writes[i].descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;writes[i].pBufferInfo=&infos[i];}vkUpdateDescriptorSets(device,3,writes,0,nullptr);
        VkCommandPoolCreateInfo cp{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};cp.queueFamilyIndex=family;checked(vkCreateCommandPool(device,&cp,nullptr,&commands));
        VkCommandBufferAllocateInfo ca{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};ca.commandPool=commands;ca.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY;ca.commandBufferCount=1;checked(vkAllocateCommandBuffers(device,&ca,&cmd));
        VkFenceCreateInfo f{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};checked(vkCreateFence(device,&f,nullptr,&fence));
        initialized=true;
        }
        const VkDeviceSize inputBytes=input.size()*4,outputBytes=input[0]*(3+input[4]*26)*4;
        enigmagrid::uploadHost(device,memory[0],coherent[0],input.data(),inputBytes);
        uint32_t hashSize=2;while(hashSize<input[3]*2)hashSize*=2;
        // The buffers and descriptor set are persistent. Re-record only when
        // the bounded dispatch shape changes; the recorded fills still run on
        // EVERY submission, before the solver reads the visited tables.
        if(recordedCount!=input[0]||recordedHashSize!=hashSize){
        checked(vkResetCommandPool(device,commands,0));
        VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};checked(vkBeginCommandBuffer(cmd,&begin));
        // Clear visited-table headers with transfer commands instead of a serial
        // loop in every solver invocation. Key storage is read only for occupied
        // slots, so it does not need clearing. Reinitialize on EVERY dispatch.
        for(uint32_t core=0;core<input[0];core++)
            vkCmdFillBuffer(cmd,buffers[2],VkDeviceSize(core)*41384*4,VkDeviceSize(hashSize)*4,0);
        VkBufferMemoryBarrier cleared{VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER};
        cleared.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT;
        cleared.dstAccessMask=VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT;
        cleared.srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;
        cleared.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;
        cleared.buffer=buffers[2];cleared.offset=0;cleared.size=VK_WHOLE_SIZE;
        vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,0,0,nullptr,1,&cleared,0,nullptr);
        vkCmdBindPipeline(cmd,VK_PIPELINE_BIND_POINT_COMPUTE,pipeline);vkCmdBindDescriptorSets(cmd,VK_PIPELINE_BIND_POINT_COMPUTE,pipelineLayout,0,1,&set,0,nullptr);vkCmdDispatch(cmd,(input[0]+15)/16,1,1);
        VkMemoryBarrier barrier{VK_STRUCTURE_TYPE_MEMORY_BARRIER};barrier.srcAccessMask=VK_ACCESS_SHADER_WRITE_BIT;barrier.dstAccessMask=VK_ACCESS_HOST_READ_BIT;vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,1,&barrier,0,nullptr,0,nullptr);checked(vkEndCommandBuffer(cmd));
        recordedCount=input[0];recordedHashSize=hashSize;
        }
        checked(vkResetFences(device,1,&fence));
        VkSubmitInfo submit{VK_STRUCTURE_TYPE_SUBMIT_INFO};submit.commandBufferCount=1;submit.pCommandBuffers=&cmd;checked(vkQueueSubmit(queue,1,&submit,fence));checked(vkWaitForFences(device,1,&fence,VK_TRUE,5000000000ULL));
        std::vector<uint32_t> output(input[0]*(3+input[4]*26));enigmagrid::downloadHost(device,memory[1],coherent[1],output.data(),outputBytes);return output;
    }
};
std::mutex computeMutex;
std::unique_ptr<SolverCompute> cachedSolverCompute;
std::vector<uint32_t> cachedCode;
}

namespace {
std::vector<uint32_t> solvePacked(const std::vector<uint32_t>& input,const std::vector<uint32_t>& code) {
    std::lock_guard<std::mutex> lock(computeMutex);
    try {
        if(input.size()<34||input.size()>(5+512*72*26+72*3)||code.size()<5||code.size()>262144)
            throw std::runtime_error("Invalid solver buffer");
        uint32_t count=input[0],edges=input[1];
        if(count<1||count>512||edges<1||edges>72||input[2]>13||input[3]<1||input[3]>5000||input[4]<1||input[4]>64||input.size()!=5+count*edges*26+edges*3||code[0]!=0x07230203)throw std::runtime_error("Invalid solver layout");
        for(uint32_t r=0;r<count*edges;r++){
            uint32_t base=5+r*26;
            for(uint32_t x=0;x<26;x++)if(input[base+x]>25||input[base+input[base+x]]!=x)throw std::runtime_error("Invalid involution");
        }
        uint32_t base=5+count*edges*26;
        for(uint32_t e=0;e<edges;e++)if(input[base+e*3]>=edges||input[base+e*3+1]>25||input[base+e*3+2]>25)throw std::runtime_error("Invalid solver edge");
        if(!cachedSolverCompute||cachedCode!=code||input[0]>cachedSolverCompute->capacity){cachedSolverCompute.reset(new SolverCompute());cachedCode=code;}
        auto dense=cachedSolverCompute->run(input,code);
        // Do not send unused answer slots through Binder. Keep the GPU layout
        // fixed, but encode only headers and actual ordered boards for JNI/IPC.
        std::vector<uint32_t> output{UINT32_MAX,count};
        uint32_t stride=3+input[4]*26;
        for(uint32_t core=0;core<count;core++){
            uint32_t base=core*stride,answers=dense[base+2];
            if(answers>input[4])throw std::runtime_error("Invalid solver answer count");
            output.insert(output.end(),dense.begin()+base,dense.begin()+base+3+answers*26);
        }
        return output;
    } catch(...) {cachedSolverCompute.reset();cachedCode.clear();throw;}
}
}

extern "C" ENIGMAGRID_EXPORT int enigmagrid_solve(
    const uint32_t* input,size_t inputCount,const uint32_t* code,size_t codeCount,
    uint32_t* output,size_t capacity,size_t* written,char* error,size_t errorCapacity) {
    if(written)*written=0;
    if(error&&errorCapacity)error[0]=0;
    try {
        if(!input||!code||!output||!written||inputCount<34||inputCount>(5+512*72*26+72*3)||codeCount<5||codeCount>262144)
            throw std::runtime_error("Invalid solver buffers");
        // Require bounded worst-case output before dispatch, avoiding repeated
        // GPU work merely to discover a caller's buffer was too small.
        if(input[0]<1||input[0]>512||input[4]<1||input[4]>64||capacity<2+input[0]*(3+input[4]*26))
            throw std::runtime_error("Solver output buffer too small");
        auto result=solvePacked(std::vector<uint32_t>(input,input+inputCount),std::vector<uint32_t>(code,code+codeCount));
        std::memcpy(output,result.data(),result.size()*sizeof(uint32_t));*written=result.size();return 0;
    } catch(const std::exception& failure) {
        if(error&&errorCapacity){std::strncpy(error,failure.what(),errorCapacity-1);error[errorCapacity-1]=0;}
        return -1;
    } catch(...) {return -1;}
}

#ifndef ENIGMAGRID_NO_JNI
extern "C" JNIEXPORT jintArray JNICALL
Java_org_enigmagrid_android_VulkanBackend_solveNative(JNIEnv* env,jclass,jintArray packed,jbyteArray spirv){
    try {
        if(!packed||!spirv)throw std::runtime_error("Missing solver input");
        jsize n=env->GetArrayLength(packed),bytes=env->GetArrayLength(spirv);
        if(n<34||n>(5+512*72*26+72*3)||bytes<20||bytes>1024*1024||bytes%4)throw std::runtime_error("Invalid solver buffer");
        std::vector<uint32_t> input(n),code(bytes/4);
        env->GetIntArrayRegion(packed,0,n,reinterpret_cast<jint*>(input.data()));
        env->GetByteArrayRegion(spirv,0,bytes,reinterpret_cast<jbyte*>(code.data()));
        if(env->ExceptionCheck())return nullptr;
        auto output=solvePacked(input,code);
        jintArray result=env->NewIntArray(output.size());
        if(result)env->SetIntArrayRegion(result,0,output.size(),reinterpret_cast<jint*>(output.data()));return result;
    }catch(const std::exception& error){env->ThrowNew(env->FindClass("java/lang/IllegalStateException"),error.what());return nullptr;}
}
#endif
