#include "../app/src/main/cpp/host_memory.h"
#include <cassert>
#include <vector>
#include <iostream>
static unsigned char storage[64];
static std::vector<int> calls;
static bool failMap=false,failSync=false;
VKAPI_ATTR VkResult VKAPI_CALL vkMapMemory(VkDevice,VkDeviceMemory,VkDeviceSize offset,VkDeviceSize size,VkMemoryMapFlags,void** data){calls.push_back(1);assert(offset==0&&size==VK_WHOLE_SIZE);*data=storage;return failMap?VK_ERROR_MEMORY_MAP_FAILED:VK_SUCCESS;}
VKAPI_ATTR void VKAPI_CALL vkUnmapMemory(VkDevice,VkDeviceMemory){calls.push_back(4);}
VKAPI_ATTR VkResult VKAPI_CALL vkFlushMappedMemoryRanges(VkDevice,uint32_t count,const VkMappedMemoryRange* range){calls.push_back(2);assert(count==1&&range->offset==0&&range->size==VK_WHOLE_SIZE);assert(storage[0]==42);return failSync?VK_ERROR_DEVICE_LOST:VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkInvalidateMappedMemoryRanges(VkDevice,uint32_t count,const VkMappedMemoryRange* range){calls.push_back(3);assert(count==1&&range->offset==0&&range->size==VK_WHOLE_SIZE);storage[0]=73;return failSync?VK_ERROR_DEVICE_LOST:VK_SUCCESS;}
int main(){
 VkPhysicalDeviceMemoryProperties p{};p.memoryTypeCount=3;
 p.memoryTypes[0].propertyFlags=VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT;
 p.memoryTypes[1].propertyFlags=VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
 p.memoryTypes[2].propertyFlags=VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT;
 assert(enigmagrid::hostMemoryType(p,7)==1);assert(enigmagrid::hostMemoryType(p,5)==0);
 bool rejected=false;try{enigmagrid::hostMemoryType(p,4);}catch(const std::runtime_error&){rejected=true;}assert(rejected);
 unsigned char input=42,output=0;
 for(bool coherent:{false,true}){
  calls.clear();enigmagrid::uploadHost(VK_NULL_HANDLE,VK_NULL_HANDLE,coherent,&input,1);assert(calls==(coherent?std::vector<int>{1,4}:std::vector<int>{1,2,4}));
  calls.clear();enigmagrid::downloadHost(VK_NULL_HANDLE,VK_NULL_HANDLE,coherent,&output,1);assert(calls==(coherent?std::vector<int>{1,4}:std::vector<int>{1,3,4}));assert(output==(coherent?42:73));
 }
 failSync=true;
 for(bool upload:{false,true}){
  calls.clear();output=0;rejected=false;
  try{if(upload)enigmagrid::uploadHost(VK_NULL_HANDLE,VK_NULL_HANDLE,false,&input,1);else enigmagrid::downloadHost(VK_NULL_HANDLE,VK_NULL_HANDLE,false,&output,1);}catch(const std::runtime_error&){rejected=true;}
  assert(rejected&&calls==(upload?std::vector<int>{1,2,4}:std::vector<int>{1,3,4}));assert(output==0);
 }
 failMap=true;calls.clear();rejected=false;
 try{enigmagrid::uploadHost(VK_NULL_HANDLE,VK_NULL_HANDLE,false,&input,1);}catch(const std::runtime_error&){rejected=true;}assert(rejected&&calls==std::vector<int>{1});
 std::cout<<"PASS host-visible selection, coherent preference, whole allocation, upload/flush and invalidate/read ordering, failure cleanup\n";
}
