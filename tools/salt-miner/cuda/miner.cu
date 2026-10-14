// Standalone Ethereum Keccak/CUDA miner. Seven stdin lines, Rust-compatible JSON.
#include <cuda_runtime.h>
#include <array>
#include <vector>
#include <string>
#include <iostream>
#include <sstream>
#include <iomanip>
#include <stdexcept>
#include <chrono>
#include <algorithm>
#include <cstdint>
#include <limits>

using Byte = unsigned char;
using U64 = unsigned long long;
#define HD __host__ __device__
struct Sponge { U64 a[25]; unsigned cursor; };
HD inline U64 rol(U64 x, unsigned n) { return (x<<n)|(x>>(64-n)); }
HD void permute(U64* a) {
    const U64 rc[24]={0x1ULL,0x8082ULL,0x800000000000808aULL,0x8000000080008000ULL,0x808bULL,0x80000001ULL,0x8000000080008081ULL,0x8000000000008009ULL,0x8aULL,0x88ULL,0x80008009ULL,0x8000000aULL,0x8000808bULL,0x800000000000008bULL,0x8000000000008089ULL,0x8000000000008003ULL,0x8000000000008002ULL,0x8000000000000080ULL,0x800aULL,0x800000008000000aULL,0x8000000080008081ULL,0x8000000000008080ULL,0x80000001ULL,0x8000000080008008ULL};
    const unsigned rotations[24]={1,3,6,10,15,21,28,36,45,55,2,14,27,41,56,8,25,43,62,18,39,61,20,44};
    const unsigned lanes[24]={10,7,11,17,18,3,5,16,8,21,24,4,15,23,19,13,12,2,20,14,22,9,6,1};
    for (unsigned r=0;r<24;++r) {
        U64 c[5];
        #pragma unroll
        for(unsigned x=0;x<5;++x) c[x]=a[x]^a[x+5]^a[x+10]^a[x+15]^a[x+20];
        #pragma unroll
        for(unsigned x=0;x<5;++x) {
            U64 d=c[(x+4)%5]^rol(c[(x+1)%5],1);
            #pragma unroll
            for(unsigned y=0;y<25;y+=5) a[y+x]^=d;
        }
        U64 t=a[1];
        #pragma unroll
        for(unsigned j=0;j<24;++j) { U64 next=a[lanes[j]]; a[lanes[j]]=rol(t,rotations[j]); t=next; }
        #pragma unroll
        for(unsigned y=0;y<25;y+=5) {
            #pragma unroll
            for(unsigned x=0;x<5;++x) c[x]=a[y+x];
            #pragma unroll
            for(unsigned x=0;x<5;++x) a[y+x]=c[x]^((~c[(x+1)%5])&c[(x+2)%5]);
        }
        a[0]^=rc[r];
    }
}
HD void absorb(Sponge& s,const Byte* p,size_t n) {
    for(size_t i=0;i<n;++i) {
        s.a[s.cursor/8]^=U64(p[i])<<((s.cursor%8)*8);
        if(++s.cursor==136) { permute(s.a); s.cursor=0; }
    }
}
HD void finish(Sponge& s,Byte* out) {
    s.a[s.cursor/8]^=1ULL<<((s.cursor%8)*8);
    s.a[16]^=0x8000000000000000ULL;
    permute(s.a);
    #pragma unroll
    for(unsigned i=0;i<32;++i) out[i]=Byte(s.a[i/8]>>((i%8)*8));
}
HD void hash(const Byte* p,size_t n,Byte* out) { Sponge s{}; absorb(s,p,n); finish(s,out); }
HD bool addSalt(const Byte* start,U64 offset,Byte* out) {
    U64 carry=offset;
    for(int i=31;i>=0;--i) { U64 v=U64(start[i])+(carry&255); out[i]=Byte(v); carry=(carry>>8)+(v>>8); }
    return carry==0;
}
struct Job { Sponge initial; Byte start[32],factory[20],proxyHash[32],prefix[40]; unsigned prefixLen; };
__constant__ Job gpuJob;
HD void child(const Byte* coord,const Byte* salt,const char* label,unsigned len,const Byte* proxyHash,Byte* out) {
    Byte data[85],derived[32],proxy[32];
    for(unsigned i=0;i<32;++i) data[i]=salt[i];
    for(unsigned i=0;i<len;++i) data[32+i]=Byte(label[i]);
    hash(data,32+len,derived);
    data[0]=255;
    for(unsigned i=0;i<20;++i) data[1+i]=coord[i];
    for(unsigned i=0;i<32;++i) { data[21+i]=derived[i]; data[53+i]=proxyHash[i]; }
    hash(data,85,proxy);
    data[0]=0xd6; data[1]=0x94;
    for(unsigned i=0;i<20;++i) data[2+i]=proxy[12+i];
    data[22]=1; hash(data,23,proxy);
    for(unsigned i=0;i<20;++i) out[i]=proxy[12+i];
}
HD void candidate(const Job& j,const Byte* suffix,size_t suffixLen,const Byte* salt,Byte* initHash,Byte* coord,Byte* wrapper) {
    Sponge s=j.initial; absorb(s,salt,32); absorb(s,suffix,suffixLen); finish(s,initHash);
    Byte data[85],derived[32];
    for(unsigned i=0;i<32;++i) data[i]=salt[i];
    const char label[]="atomic-deployment";
    for(unsigned i=0;i<17;++i) data[32+i]=Byte(label[i]);
    hash(data,49,derived); data[0]=255;
    for(unsigned i=0;i<20;++i) data[1+i]=j.factory[i];
    for(unsigned i=0;i<32;++i) { data[21+i]=derived[i]; data[53+i]=initHash[i]; }
    hash(data,85,derived);
    for(unsigned i=0;i<20;++i) coord[i]=derived[12+i];
    child(coord,salt,"wrapper",7,j.proxyHash,wrapper);
}
__global__ void mine(const Byte* suffix,size_t suffixLen,U64 base,U64 count,U64* best) {
    U64 i=U64(blockIdx.x)*blockDim.x+threadIdx.x;
    if(i>=count) return;
    Byte salt[32],initHash[32],coord[20],wrapper[20];
    addSalt(gpuJob.start,base+i,salt);
    candidate(gpuJob,suffix,suffixLen,salt,initHash,coord,wrapper);
    for(unsigned n=0;n<gpuJob.prefixLen;++n) {
        unsigned digit=(n%2)?(wrapper[n/2]&15):(wrapper[n/2]>>4);
        if(digit!=gpuJob.prefix[n]) return;
    }
    atomicMin(best,i);
}
void check(cudaError_t e) { if(e!=cudaSuccess) throw std::runtime_error(std::string("CUDA: ")+cudaGetErrorString(e)); }
int nibble(char c) { if(c>='0'&&c<='9')return c-'0'; if(c>='a'&&c<='f')return c-'a'+10; if(c>='A'&&c<='F')return c-'A'+10; throw std::runtime_error("invalid hex input"); }
std::vector<Byte> decode(const std::string& s) {
    if(s.size()%2)throw std::runtime_error("invalid hex input");
    std::vector<Byte> v(s.size()/2);
    for(size_t i=0;i<v.size();++i)v[i]=Byte(16*nibble(s[2*i])+nibble(s[2*i+1]));
    return v;
}
std::string hex(const Byte* p,size_t n) {
    const char* h="0123456789abcdef"; std::string out;
    for(size_t i=0;i<n;++i) { out+=h[p[i]>>4];out+=h[p[i]&15]; } return out;
}
struct DeviceBuffers {
    Byte* suffix=nullptr; U64* best=nullptr;
    ~DeviceBuffers() { if(suffix)cudaFree(suffix); if(best)cudaFree(best); }
};
int run() {
    std::vector<std::string> lines; std::string line;
    while(std::getline(std::cin,line)) { if(!line.empty()&&line.back()=='\r')line.pop_back(); lines.push_back(line); }
    if(lines.size()!=7)throw std::runtime_error("expected seven input lines");
    auto factory=decode(lines[0]),before=decode(lines[1]),after=decode(lines[2]),start=decode(lines[3]);
    if(factory.size()!=20)throw std::runtime_error("CREATE2 deployer must be 20 bytes");
    if(start.size()!=32)throw std::runtime_error("salt must be 32 bytes");
    Job job{}; std::copy(factory.begin(),factory.end(),job.factory);std::copy(start.begin(),start.end(),job.start);
    if(lines[4].size()>40)throw std::runtime_error("prefix must have at most 40 hex digits");
    job.prefixLen=unsigned(lines[4].size());
    for(unsigned i=0;i<job.prefixLen;++i) job.prefix[i]=Byte(nibble(lines[4][i]));
    if(lines[5].empty()||!std::all_of(lines[5].begin(),lines[5].end(),[](char c){return c>='0'&&c<='9';}))throw std::runtime_error("invalid attempt limit");
    U64 limit=std::stoull(lines[5]);
    if(!limit)throw std::runtime_error("attempt limit must be positive");
    if(lines[6]!="wrapper")throw std::runtime_error("only wrapper targets are supported");
    Byte end[32]; if(!addSalt(job.start,limit-1,end))throw std::runtime_error("exhausted bytes32 salt range");
    auto ph=decode("21c35dbe1b344a2488cf3321d6ce542f8e9f305544ff09e4993a62319a497c1f");
    std::copy(ph.begin(),ph.end(),job.proxyHash);
    // Hash the invariant bytecode/ABI prefix once on CPU, retaining sponge cursor.
    absorb(job.initial,before.data(),before.size());
    DeviceBuffers d;
    check(cudaMalloc(reinterpret_cast<void**>(&d.suffix),std::max(size_t(1),after.size())));
    if(!after.empty())check(cudaMemcpy(d.suffix,after.data(),after.size(),cudaMemcpyHostToDevice));
    check(cudaMalloc(reinterpret_cast<void**>(&d.best),sizeof(U64)));
    check(cudaMemcpyToSymbol(gpuJob,&job,sizeof(job)));
    const U64 batch=1ULL<<20;
    U64 searched=0,winning=0; bool found=false;
    auto started=std::chrono::steady_clock::now();
    while(searched<limit) {
        U64 count=std::min(batch,limit-searched),best=std::numeric_limits<U64>::max();
        check(cudaMemcpy(d.best,&best,sizeof(best),cudaMemcpyHostToDevice));
        mine<<<unsigned((count+127)/128),128>>>(d.suffix,after.size(),searched,count,d.best);
        check(cudaGetLastError()); check(cudaDeviceSynchronize());
        check(cudaMemcpy(&best,d.best,sizeof(best),cudaMemcpyDeviceToHost));
        if(best<count) { winning=searched+best; found=true; }
        searched+=count;
        if(found)break;
    }
    double secs=std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count();
    std::cerr<<"GPU searched "<<searched<<" candidates in "<<std::fixed<<std::setprecision(6)<<secs<<" s ("<<std::setprecision(0)<<searched/secs<<" candidates/s); batch="<<batch<<"\n";
    if(!found) {
        Byte next[32];
        if(addSalt(job.start,limit,next)) {
            std::cerr<<"No match in "<<limit<<" candidates. Resume with --start 0x"<<hex(next,32)<<"\n";
        } else {
            std::cerr<<"No match in "<<limit<<" candidates. Exhausted bytes32 salt range; no resume salt\n";
        }
        return 2;
    }
    Byte salt[32],initHash[32],coord[20],wrapper[20],impl[20],beacon[20];
    addSalt(job.start,winning,salt); candidate(job,after.data(),after.size(),salt,initHash,coord,wrapper);
    for(unsigned n=0;n<job.prefixLen;++n)if(((n%2)?(wrapper[n/2]&15):(wrapper[n/2]>>4))!=job.prefix[n])throw std::runtime_error("GPU/CPU winner mismatch");
    child(coord,salt,"implementation",14,job.proxyHash,impl);child(coord,salt,"beacon",6,job.proxyHash,beacon);
    std::cout<<"{\"salt\":\"0x"<<hex(salt,32)<<"\",\"attempts\":"<<winning+1<<",\"initcodeHash\":\"0x"<<hex(initHash,32)<<"\",\"create2Deployer\":\"0x"<<hex(job.factory,20)<<"\",\"addresses\":{\"coordinator\":\"0x"<<hex(coord,20)<<"\",\"implementation\":\"0x"<<hex(impl,20)<<"\",\"beacon\":\"0x"<<hex(beacon,20)<<"\",\"wrapper\":\"0x"<<hex(wrapper,20)<<"\"}}\n";
    return 0;
}
int main(int argc, char** argv) {
    try {
        if(argc==2 && std::string(argv[1])=="--probe") {
            int count=0;
            check(cudaGetDeviceCount(&count));
            if(count==0)throw std::runtime_error("CUDA: no usable device");
            cudaDeviceProp device{};
            check(cudaGetDeviceProperties(&device,0));
            check(cudaSetDevice(0));
            check(cudaFree(nullptr));
            std::cout<<"{\"name\":"<<std::quoted(device.name)<<",\"major\":"<<device.major
                     <<",\"minor\":"<<device.minor<<"}\n";
            return 0;
        }
        if(argc!=1)throw std::runtime_error("only --probe is supported");
        return run();
    } catch(const std::exception& e) {std::cerr<<"Error: "<<e.what()<<"\n";return 1;}
}
