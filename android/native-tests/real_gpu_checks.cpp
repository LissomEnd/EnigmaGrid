#include "../app/src/main/cpp/vulkan_rows.cpp"
#include <fstream>
#include <iostream>
#include <chrono>
int main(int argc,char** argv){
 try{
  if(argc!=3)throw std::runtime_error("usage: executable shader.spv fixtures.txt");
  std::ifstream shader(argv[1],std::ios::binary|std::ios::ate);auto bytes=shader.tellg();if(bytes<20||bytes>1024*1024||bytes%4)throw std::runtime_error("invalid shader");shader.seekg(0);std::vector<uint32_t> code(bytes/4);shader.read(reinterpret_cast<char*>(code.data()),bytes);if(!shader||code[0]!=0x07230203)throw std::runtime_error("shader read failed");
  std::ifstream fixtures(argv[2]);int count=0;if(!(fixtures>>count)||count!=18)throw std::runtime_error("expected18 fixtures");
  std::vector<std::vector<uint32_t>> inputs,expected;
  for(int test=0;test<count;test++){int ni=0,no=0;if(!(fixtures>>ni>>no)||ni<634||ni>10993||no<26||no>29952)throw std::runtime_error("fixturebounds");std::vector<uint32_t> a(ni),b(no);for(auto& v:a)fixtures>>v;for(auto& v:b)fixtures>>v;if(!fixtures)throw std::runtime_error("fixture read failed");if(a[0]<1||a[0]>1152||ni!=625+a[0]*9||no!=a[0]*26)throw std::runtime_error("fixture layout");
   for(size_t i=1;i<625;i++)if(a[i]>25)throw std::runtime_error("fixture contact");
   for(size_t i=625;i<a.size();i++)if(a[i]>=((i-625)%9<5?12u:26u))throw std::runtime_error("fixture rotor");
   inputs.push_back(a);expected.push_back(b);}
  Compute compute;size_t contacts=0;auto start=std::chrono::steady_clock::now();
  for(int pass=0;pass<3;pass++)for(int test=0;test<count;test++){
   auto actual=compute.run(inputs[test],code);if(actual!=expected[test])throw std::runtime_error("parity mismatch pass="+std::to_string(pass)+" fixture="+std::to_string(test));contacts+=actual.size();
  }
  auto ms=std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-start).count();
  std::cout<<"PASS real Vulkan production Compute::run: 54 dispatches, "<<contacts<<" Java-reference contacts, coherent input="<<compute.coherent[0]<<" output="<<compute.coherent[1]<<", ms="<<ms<<std::endl;
  return 0;
 }catch(const std::exception& e){std::cerr<<"FAIL "<<e.what()<<std::endl;return 1;}
}
