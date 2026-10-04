#pragma once
#include <vulkan/vulkan.h>
#include <stdexcept>
#include <string>
#include <cstring>

namespace enigmagrid {
inline void memoryChecked(VkResult result){if(result!=VK_SUCCESS)throw std::runtime_error("Vulkan memory operation failed: "+std::to_string(result));}
inline uint32_t hostMemoryType(const VkPhysicalDeviceMemoryProperties& properties,uint32_t allowed){
    uint32_t fallback=UINT32_MAX;
    for(uint32_t i=0;i<properties.memoryTypeCount;i++){
        if(!(allowed&(1u<<i))||!(properties.memoryTypes[i].propertyFlags&VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT))continue;
        if(properties.memoryTypes[i].propertyFlags&VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)return i;
        if(fallback==UINT32_MAX)fallback=i;
    }
    if(fallback==UINT32_MAX)throw std::runtime_error("No host-visible buffer memory");
    return fallback;
}
class HostMapping {
    VkDevice device;VkDeviceMemory memory;void* pointer=nullptr;
public:
    HostMapping(VkDevice d,VkDeviceMemory m):device(d),memory(m){memoryChecked(vkMapMemory(device,memory,0,VK_WHOLE_SIZE,0,&pointer));}
    ~HostMapping(){vkUnmapMemory(device,memory);}
    HostMapping(const HostMapping&)=delete;
    HostMapping& operator=(const HostMapping&)=delete;
    void* data(){return pointer;}
    void synchronize(bool flush){
        // Entire dedicated allocation is mapped, so its end satisfies atom-size
        // alignment even when allocationSize itself is not an atom multiple.
        VkMappedMemoryRange range{VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE};range.memory=memory;range.offset=0;range.size=VK_WHOLE_SIZE;
        memoryChecked(flush?vkFlushMappedMemoryRanges(device,1,&range):vkInvalidateMappedMemoryRanges(device,1,&range));
    }
};
inline void uploadHost(VkDevice device,VkDeviceMemory memory,bool coherent,const void* source,size_t bytes){
    HostMapping mapped(device,memory);std::memcpy(mapped.data(),source,bytes);if(!coherent)mapped.synchronize(true);
}
// Caller must have waited for the submission fence after its shader->host barrier.
inline void downloadHost(VkDevice device,VkDeviceMemory memory,bool coherent,void* destination,size_t bytes){
    HostMapping mapped(device,memory);if(!coherent)mapped.synchronize(false);std::memcpy(destination,mapped.data(),bytes);
}
}
