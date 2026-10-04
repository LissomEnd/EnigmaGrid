#include <jni.h>
#include <vulkan/vulkan.h>
#include <vector>
#include <string>
#include <stdexcept>
#include <cstring>
#include <memory>
#include <mutex>

namespace {
void checked(VkResult result){if(result!=VK_SUCCESS)throw std::runtime_error("Vulkan operation failed: "+std::to_string(result));}
struct Compute {
    VkInstance instance{};VkDevice device{};VkPhysicalDevice physical{};VkQueue queue{};
    VkBuffer buffers[2]{};VkDeviceMemory memory[2]{};VkShaderModule shader{};
    VkDescriptorSetLayout layout{};VkPipelineLayout pipelineLayout{};VkPipeline pipeline{};
    VkDescriptorPool descriptors{};VkCommandPool commands{};VkFence fence{};
    VkDescriptorSet set{};VkCommandBuffer cmd{};bool initialized=false;
    ~Compute(){
        if(device){vkDeviceWaitIdle(device);if(fence)vkDestroyFence(device,fence,nullptr);if(commands)vkDestroyCommandPool(device,commands,nullptr);if(descriptors)vkDestroyDescriptorPool(device,descriptors,nullptr);if(pipeline)vkDestroyPipeline(device,pipeline,nullptr);if(pipelineLayout)vkDestroyPipelineLayout(device,pipelineLayout,nullptr);if(layout)vkDestroyDescriptorSetLayout(device,layout,nullptr);if(shader)vkDestroyShaderModule(device,shader,nullptr);for(int i=0;i<2;i++){if(buffers[i])vkDestroyBuffer(device,buffers[i],nullptr);if(memory[i])vkFreeMemory(device,memory[i],nullptr);}vkDestroyDevice(device,nullptr);}
        if(instance)vkDestroyInstance(instance,nullptr);
    }
    void buffer(int index,VkDeviceSize bytes){
        VkBufferCreateInfo b{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};b.size=bytes;b.usage=VK_BUFFER_USAGE_STORAGE_BUFFER_BIT;b.sharingMode=VK_SHARING_MODE_EXCLUSIVE;checked(vkCreateBuffer(device,&b,nullptr,&buffers[index]));
        VkMemoryRequirements requirements;vkGetBufferMemoryRequirements(device,buffers[index],&requirements);
        VkPhysicalDeviceMemoryProperties properties;vkGetPhysicalDeviceMemoryProperties(physical,&properties);
        uint32_t type=UINT32_MAX;
        for(uint32_t i=0;i<properties.memoryTypeCount;i++)if((requirements.memoryTypeBits&(1u<<i))&&(properties.memoryTypes[i].propertyFlags&(VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT))==(VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)){type=i;break;}
        if(type==UINT32_MAX)throw std::runtime_error("No coherent host-visible buffer memory");
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
        const VkDeviceSize inputBytes=1273*4,outputBytes=72*26*4;buffer(0,inputBytes);buffer(1,outputBytes);
        VkShaderModuleCreateInfo s{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};s.codeSize=code.size()*4;s.pCode=code.data();checked(vkCreateShaderModule(device,&s,nullptr,&shader));
        VkDescriptorSetLayoutBinding bindings[2]{};for(int i=0;i<2;i++){bindings[i].binding=i;bindings[i].descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;bindings[i].descriptorCount=1;bindings[i].stageFlags=VK_SHADER_STAGE_COMPUTE_BIT;}
        VkDescriptorSetLayoutCreateInfo l{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};l.bindingCount=2;l.pBindings=bindings;checked(vkCreateDescriptorSetLayout(device,&l,nullptr,&layout));
        VkPipelineLayoutCreateInfo pl{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};pl.setLayoutCount=1;pl.pSetLayouts=&layout;checked(vkCreatePipelineLayout(device,&pl,nullptr,&pipelineLayout));
        VkComputePipelineCreateInfo p{VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO};p.layout=pipelineLayout;p.stage.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;p.stage.stage=VK_SHADER_STAGE_COMPUTE_BIT;p.stage.module=shader;p.stage.pName="main";checked(vkCreateComputePipelines(device,VK_NULL_HANDLE,1,&p,nullptr,&pipeline));
        VkDescriptorPoolSize poolSize{VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,2};VkDescriptorPoolCreateInfo pool{VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO};pool.maxSets=1;pool.poolSizeCount=1;pool.pPoolSizes=&poolSize;checked(vkCreateDescriptorPool(device,&pool,nullptr,&descriptors));
        VkDescriptorSetAllocateInfo alloc{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO};alloc.descriptorPool=descriptors;alloc.descriptorSetCount=1;alloc.pSetLayouts=&layout;checked(vkAllocateDescriptorSets(device,&alloc,&set));
        VkDescriptorBufferInfo infos[2]={{buffers[0],0,inputBytes},{buffers[1],0,outputBytes}};VkWriteDescriptorSet writes[2]{};
        for(int i=0;i<2;i++){writes[i].sType=VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;writes[i].dstSet=set;writes[i].dstBinding=i;writes[i].descriptorCount=1;writes[i].descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;writes[i].pBufferInfo=&infos[i];}vkUpdateDescriptorSets(device,2,writes,0,nullptr);
        VkCommandPoolCreateInfo cp{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};cp.queueFamilyIndex=family;checked(vkCreateCommandPool(device,&cp,nullptr,&commands));
        VkCommandBufferAllocateInfo ca{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};ca.commandPool=commands;ca.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY;ca.commandBufferCount=1;checked(vkAllocateCommandBuffers(device,&ca,&cmd));
        VkFenceCreateInfo f{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};checked(vkCreateFence(device,&f,nullptr,&fence));
        initialized=true;
        }
        const VkDeviceSize inputBytes=input.size()*4,outputBytes=input[0]*26*4;
        void* mapped=nullptr;checked(vkMapMemory(device,memory[0],0,inputBytes,0,&mapped));memcpy(mapped,input.data(),inputBytes);vkUnmapMemory(device,memory[0]);
        checked(vkResetCommandPool(device,commands,0));checked(vkResetFences(device,1,&fence));
        VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};begin.flags=VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;checked(vkBeginCommandBuffer(cmd,&begin));
        vkCmdBindPipeline(cmd,VK_PIPELINE_BIND_POINT_COMPUTE,pipeline);vkCmdBindDescriptorSets(cmd,VK_PIPELINE_BIND_POINT_COMPUTE,pipelineLayout,0,1,&set,0,nullptr);vkCmdDispatch(cmd,(input[0]*26+63)/64,1,1);
        VkMemoryBarrier barrier{VK_STRUCTURE_TYPE_MEMORY_BARRIER};barrier.srcAccessMask=VK_ACCESS_SHADER_WRITE_BIT;barrier.dstAccessMask=VK_ACCESS_HOST_READ_BIT;vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,1,&barrier,0,nullptr,0,nullptr);checked(vkEndCommandBuffer(cmd));
        VkSubmitInfo submit{VK_STRUCTURE_TYPE_SUBMIT_INFO};submit.commandBufferCount=1;submit.pCommandBuffers=&cmd;checked(vkQueueSubmit(queue,1,&submit,fence));checked(vkWaitForFences(device,1,&fence,VK_TRUE,5000000000ULL));
        std::vector<uint32_t> output(input[0]*26);checked(vkMapMemory(device,memory[1],0,outputBytes,0,&mapped));memcpy(output.data(),mapped,outputBytes);vkUnmapMemory(device,memory[1]);return output;
    }
};
std::mutex computeMutex;
std::unique_ptr<Compute> cachedCompute;
std::vector<uint32_t> cachedCode;
}

extern "C" JNIEXPORT jintArray JNICALL
Java_org_enigmagrid_android_VulkanBackend_rowsNative(JNIEnv* env,jclass,jintArray packed,jbyteArray spirv){
    std::lock_guard<std::mutex> lock(computeMutex);
    try{
        if(!packed||!spirv)throw std::runtime_error("Missing GPU input");
        jsize n=env->GetArrayLength(packed),bytes=env->GetArrayLength(spirv);if(n<634||n>1273||bytes<20||bytes>1024*1024||bytes%4)throw std::runtime_error("Invalid GPU buffer size");
        std::vector<uint32_t> input(n),code(bytes/4);env->GetIntArrayRegion(packed,0,n,reinterpret_cast<jint*>(input.data()));env->GetByteArrayRegion(spirv,0,bytes,reinterpret_cast<jbyte*>(code.data()));
        if(input[0]<1||input[0]>72||n!=625+input[0]*9||code[0]!=0x07230203)throw std::runtime_error("Invalid GPU layout");
        for(size_t i=1;i<625;i++)if(input[i]>25)throw std::runtime_error("Invalid contact");
        for(size_t i=625;i<input.size();i++)if(input[i]>=((i-625)%9<5?12u:26u))throw std::runtime_error("Invalid rotor descriptor");
        if(!cachedCompute||cachedCode!=code){cachedCompute.reset(new Compute());cachedCode=code;}
        auto output=cachedCompute->run(input,code);jintArray result=env->NewIntArray(output.size());if(result)env->SetIntArrayRegion(result,0,output.size(),reinterpret_cast<jint*>(output.data()));return result;
    }catch(const std::exception& error){cachedCompute.reset();cachedCode.clear();env->ThrowNew(env->FindClass("java/lang/IllegalStateException"),error.what());return nullptr;}
}

// Capability discovery is not qualification and must not enable GPU work.
extern "C" JNIEXPORT jstring JNICALL
Java_org_enigmagrid_android_VulkanBackend_probeNative(JNIEnv* env,jclass) {
    VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};
    app.pApplicationName="EnigmaGrid";app.apiVersion=VK_API_VERSION_1_0;
    VkInstanceCreateInfo create{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};create.pApplicationInfo=&app;
    VkInstance instance=VK_NULL_HANDLE;
    if(vkCreateInstance(&create,nullptr,&instance)!=VK_SUCCESS)return env->NewStringUTF("Vulkan initialization unavailable");
    std::string description="No suitable Vulkan compute queue";
    uint32_t count=0;
    if(vkEnumeratePhysicalDevices(instance,&count,nullptr)==VK_SUCCESS&&count>0&&count<=64) {
        std::vector<VkPhysicalDevice> devices(count);
        if(vkEnumeratePhysicalDevices(instance,&count,devices.data())==VK_SUCCESS) {
            for(VkPhysicalDevice device:devices) {
                VkPhysicalDeviceProperties properties{};vkGetPhysicalDeviceProperties(device,&properties);
                uint32_t familyCount=0;vkGetPhysicalDeviceQueueFamilyProperties(device,&familyCount,nullptr);
                std::vector<VkQueueFamilyProperties> families(familyCount);vkGetPhysicalDeviceQueueFamilyProperties(device,&familyCount,families.data());
                for(const auto& family:families)if(family.queueCount&&(family.queueFlags&VK_QUEUE_COMPUTE_BIT)&&properties.limits.maxComputeWorkGroupInvocations>=64&&properties.limits.maxComputeWorkGroupSize[0]>=64) {
                    description=std::string(properties.deviceName)+" · Vulkan "+std::to_string(VK_VERSION_MAJOR(properties.apiVersion))+"."+std::to_string(VK_VERSION_MINOR(properties.apiVersion))+" · compute available, not qualified";
                    break;
                }
                if(description!="No suitable Vulkan compute queue")break;
            }
        }
    }
    vkDestroyInstance(instance,nullptr);
    return env->NewStringUTF(description.c_str());
}
