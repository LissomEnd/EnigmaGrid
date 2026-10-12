#define ENIGMAGRID_NO_JNI
#include "../app/src/main/cpp/vulkan_portable.cpp"
#include <chrono>
#include <algorithm>
std::vector<int> readInts(std::ifstream& f,size_t n){std::vector<int> v(n);if(!f.read((char*)v.data(),n*4))throw std::runtime_error("Short full fixture");return v;}
int main(int argc,char**argv){try{
 if(argc!=3)return 2;std::ifstream sf(argv[1],std::ios::binary|std::ios::ate);size_t bytes=sf.tellg();sf.seekg(0);auto raw=readInts(sf,bytes/4);std::vector<uint32_t> code(raw.begin(),raw.end());
 std::ifstream f(argv[2],std::ios::binary);auto ref=readInts(f,457673);auto shape=readInts(f,3);int n=shape[0];auto initial=readInts(f,n*86);std::vector<int> params={n,0,1,shape[1],shape[2],6,1,2,3,4,5,6};
 auto start=std::chrono::steady_clock::now();int id=portable_backend::begin(ref,initial,params,code);VkPhysicalDeviceProperties props;vkGetPhysicalDeviceProperties(portable_backend::active->physical,&props);std::cout<<"device="<<props.deviceName<<" driver="<<props.driverVersion<<std::endl;
 double dispatch=0;std::vector<int> actual(n*86),expected,firstTape,firstExpected;
 for(int chunk=0;chunk<32;chunk++){auto tape=readInts(f,n*16*5);if(chunk==0)firstTape=tape;expected=readInts(f,n*86);if(chunk==0)firstExpected=expected;auto t=std::chrono::steady_clock::now();portable_backend::step(id,tape,16);dispatch+=std::chrono::duration<double>(std::chrono::steady_clock::now()-t).count();
 auto& c=*portable_backend::active;enigmagrid::downloadHost(c.device,c.memory[2],c.coherent[2],actual.data(),actual.size()*4);for(size_t j=0;j<actual.size();j++)if(actual[j]!=expected[j]){std::cerr<<"Mismatch chunk="<<chunk<<" index="<<j<<" actual="<<actual[j]<<" expected="<<expected[j]<<std::endl;return 1;}
 }
 VkDevice originalDevice=portable_backend::active->device;actual=portable_backend::finish(id);if(actual!=expected)throw std::runtime_error("Finish mismatch");portable_backend::close(id);
 // Cancel safely between chunks, then reopen same cohort. No receipt is produced.
 id=portable_backend::begin(ref,initial,params,code);
 if(portable_backend::active->device!=originalDevice)throw std::runtime_error("Context was not reused");
 portable_backend::step(id,firstTape,16);actual=portable_backend::finish(id);if(actual!=firstExpected)throw std::runtime_error("Cached context state not reset");portable_backend::close(id);
 auto smallParams=params;smallParams[0]=256;std::vector<int> smallState(initial.begin(),initial.begin()+256*86),smallTape;
 for(int i=0;i<16;i++)smallTape.insert(smallTape.end(),firstTape.begin()+i*n*5,firstTape.begin()+i*n*5+256*5);
 id=portable_backend::begin(ref,smallState,smallParams,code);if(portable_backend::active->device!=originalDevice)throw std::runtime_error("Smaller context was not reused");portable_backend::step(id,smallTape,16);actual=portable_backend::finish(id);if(actual!=std::vector<int>(firstExpected.begin(),firstExpected.begin()+256*86))throw std::runtime_error("Smaller cached context mismatch");portable_backend::close(id);
 id=portable_backend::begin(ref,initial,params,code);portable_backend::step(id,firstTape,16);portable_backend::close(id);portable_backend::close(id);
 id=portable_backend::begin(ref,initial,params,code);try{portable_backend::step(id,std::vector<int>{},1);throw std::runtime_error("Malformed tape accepted");}catch(const std::invalid_argument&){}if(portable_backend::active)throw std::runtime_error("Failure left active session");
 id=portable_backend::begin(ref,initial,params,code);portable_backend::close(id);if(portable_backend::isPoisoned())throw std::runtime_error("Unexpected poison");
 std::cout<<"PASS full resident parity "<<n<<"x512 mixed kinds all32 checkpoints; cachedcontext-reset/shrink/cancel/reopen/malformed recovery. dispatch_seconds="<<dispatch<<" wall_seconds="<<std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()<<std::endl;return 0;
 }catch(std::exception&e){std::cerr<<e.what()<<std::endl;return 2;}}
