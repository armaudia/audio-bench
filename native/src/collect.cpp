#include "wire.hpp"
#include <audio_sdk/provider_v0.h>
#include <audio_sdk/session_v0.h>
#include <array>
#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <string>
#include <sys/resource.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <fcntl.h>
#include <signal.h>
#include <unistd.h>
#include <vector>

namespace fs = std::filesystem;
namespace {
int64_t now_ns(){timespec t{};if(clock_gettime(CLOCK_MONOTONIC,&t)!=0)throw std::runtime_error("monotonic clock failed");return int64_t(t.tv_sec)*1000000000LL+t.tv_nsec;}
void nonblocking(int fd){int flags=fcntl(fd,F_GETFL,0);if(flags<0||fcntl(fd,F_SETFL,flags|O_NONBLOCK)<0)throw std::runtime_error("failed to set nonblocking pipe");}
std::array<uint8_t,32> sdk_hash(const void*data,uint64_t size){char out[65]{};if(as_sha256_hex_v0(data,size,out,sizeof(out))!=AS_OK)throw std::runtime_error("SDK hash helper failed");return ab::digest_from_hex(out);}
std::string config_for(const std::string&id){as_registry_v0*r=nullptr;as_error_v0 e;as_error_v0_init(&e);if(as_registry_create_v0(&r,&e)!=AS_OK)throw std::runtime_error("SDK registry create failed");uint32_t n=0;std::vector<char>b(AS_MAX_CONTROL_BYTES+1);auto s=as_effective_config_create_v0(r,id.data(),uint32_t(id.size()),AS_MODE_PROCESSING_THREAD,b.data(),uint32_t(b.size()),&n,&e);if(s!=AS_OK||n==0||n>b.size()||b[n-1]!='\0'){as_registry_close_v0(&r);throw std::runtime_error("SDK effective config generation failed");}std::string value(b.data(),n-1);as_registry_close_v0(&r);return value;}
struct Child {
 pid_t pid=-1;int to_child=-1;int from_child=-1;uint64_t tx=0,rx=0;uint64_t epoch=1;
 Child(const fs::path&driver,const std::string&provider){int in[2],out[2];if(pipe(in)||pipe(out))throw std::runtime_error("pipe creation failed");pid=fork();if(pid<0)throw std::runtime_error("fork failed");if(pid==0){setpgid(0,0);dup2(in[0],STDIN_FILENO);dup2(out[1],STDOUT_FILENO);close(in[0]);close(in[1]);close(out[0]);close(out[1]);execl(driver.c_str(),driver.c_str(),"--provider",provider.c_str(),static_cast<char*>(nullptr));_exit(127);}setpgid(pid,pid);close(in[0]);close(out[1]);to_child=in[1];from_child=out[0];nonblocking(to_child);nonblocking(from_child);}
 ~Child(){if(pid>0){kill(-pid,SIGKILL);int status=0;waitpid(pid,&status,0);}if(to_child>=0)close(to_child);if(from_child>=0)close(from_child);}
 void send(ab::Message m){m.stream=0;m.sequence=tx++;ab::write_message(to_child,m,30000);}
 ab::Message receive(){auto m=ab::read_message(from_child,30000);if(m.stream!=0||m.sequence!=rx++)throw std::runtime_error("driver duplicate/out-of-order sequence or stream");if(m.type==ab::Type::Error){throw std::runtime_error("driver error status="+std::to_string(int32_t(m.payload[8]|uint32_t(m.payload[9])<<8|uint32_t(m.payload[10])<<16|uint32_t(m.payload[11])<<24)));}return m;}
 void ready(){auto m=receive();if(m.type!=ab::Type::Ready||m.payload.size()!=64)throw std::runtime_error("expected READY");}
 int finish(rusage&usage){if(to_child>=0){close(to_child);to_child=-1;}int status=0;struct rusage local{};pid_t result;do{result=wait4(pid,&status,0,&local);}while(result<0&&errno==EINTR);if(result<0)throw std::runtime_error("wait4 failed");pid=-1;usage=local;if(from_child>=0){close(from_child);from_child=-1;}if(!WIFEXITED(status)||WEXITSTATUS(status)!=0)throw std::runtime_error("driver exited unsuccessfully");return status;}
};
std::vector<float> read_f32(const fs::path&path){std::ifstream f(path,std::ios::binary);if(!f)throw std::runtime_error("cannot open input: "+path.string());f.seekg(0,std::ios::end);auto bytes=f.tellg();if(bytes<0||bytes%4)throw std::runtime_error("input must be little-endian float32 bytes");f.seekg(0);std::vector<float>v(size_t(bytes)/4);if(!v.empty())f.read(reinterpret_cast<char*>(v.data()),bytes);if(!f||!std::all_of(v.begin(),v.end(),[](float x){return std::isfinite(x);}))throw std::runtime_error("input contains non-finite or unreadable samples");return v;}
void write_f32(std::ofstream&out,const std::array<float,160>&samples,uint32_t count){out.write(reinterpret_cast<const char*>(samples.data()),std::streamsize(count*sizeof(float)));if(!out)throw std::runtime_error("output write failed");}
std::string q(const std::string&s){std::string o="\"";for(unsigned char c:s){if(c=='\"'||c=='\\'){o.push_back('\\');o.push_back(char(c));}else if(c<0x20){static const char*h="0123456789abcdef";o+="\\u00";o.push_back(h[c>>4]);o.push_back(h[c&15]);}else o.push_back(char(c));}return o+'\"';}
struct CaseResult {std::string id;uint64_t samples=0,accepted=0,produced=0;bool complete=true;uint64_t output_messages=0;};
uint64_t usage_cpu_ns(const rusage&u){return uint64_t(u.ru_utime.tv_sec+u.ru_stime.tv_sec)*1000000000ULL+uint64_t(u.ru_utime.tv_usec+u.ru_stime.tv_usec)*1000ULL;}
void accept_output(const ab::Message&m,uint64_t epoch,uint32_t expected_phase,CaseResult&result,std::ofstream&audio,std::ofstream&maps){if(m.type!=ab::Type::Output)throw std::runtime_error("expected OUTPUT or DRAINED");auto o=ab::decode_output(m);int64_t receive_ns=now_ns();if(o.epoch!=epoch||o.phase!=expected_phase)throw std::runtime_error("OUTPUT epoch/phase mismatch");uint64_t output_offset=result.produced;if(o.produced)write_f32(audio,o.samples,o.produced);result.produced+=o.produced;result.output_messages++;if(o.valid){int64_t begin=o.source_first+o.valid_offset;int64_t end=begin+o.valid;maps<<"{\"phase\":"<<q(expected_phase==ab::kPhaseProcess?"process":"drain")<<",\"source_start\":\""<<begin<<"\",\"source_end\":\""<<end<<"\",\"output_offset_samples\":\""<<output_offset<<"\",\"source_first_sample\":\""<<o.source_first<<"\",\"produced_count\":"<<o.produced<<",\"valid_offset\":"<<o.valid_offset<<",\"valid_count\":"<<o.valid<<",\"flags\":"<<o.flags<<",\"collector_receive_monotonic_ns\":\""<<receive_ns<<"\",\"candidate_service_begin_ns\":\""<<o.service_begin<<"\",\"candidate_service_end_ns\":\""<<o.service_end<<"\"}\n";}}
void run_case(Child&child,const fs::path&input,const fs::path&output_dir,uint64_t epoch,CaseResult&result){auto samples=read_f32(input);result.id=input.stem().string();result.samples=samples.size();result.accepted=samples.size();child.epoch=epoch;fs::path raw=output_dir/(result.id+".raw.f32"),maps_path=output_dir/(result.id+".intervals.jsonl");std::ofstream audio(raw,std::ios::binary|std::ios::out|std::ios::trunc),maps(maps_path,std::ios::out|std::ios::trunc);if(!audio||!maps)throw std::runtime_error("cannot create case output artifacts");uint64_t seq=1;for(size_t offset=0;offset<samples.size();offset+=160){ab::Input in{};in.epoch=epoch;in.first=int64_t(offset);size_t count=std::min<size_t>(160,samples.size()-offset);in.valid=uint32_t(count);in.flags=count<160?1u:0u;std::copy_n(samples.begin()+offset,count,in.samples.begin());child.send(ab::input_message(0,seq++,in));auto m=child.receive();accept_output(m,epoch,ab::kPhaseProcess,result,audio,maps);}
 child.send(ab::end_message(ab::Type::EndInput,0,seq++,{epoch,int64_t(samples.size())}));for(uint32_t calls=0;calls<1025;calls++){auto m=child.receive();if(m.type==ab::Type::Drained){auto ack=ab::decode_end(m);if(ack.epoch!=epoch||ack.sample!=int64_t(samples.size()))throw std::runtime_error("DRAINED acknowledgement mismatch");break;}accept_output(m,epoch,ab::kPhaseDrain,result,audio,maps);if(calls==1024)throw std::runtime_error("drain completion exceeded bound");}
 audio.flush();maps.flush();if(!audio||!maps)throw std::runtime_error("failed flushing retained output");
 // Verify exact source coverage; gaps/overlaps remain a failed row, never a fitted crop.
 std::ifstream verify(maps_path);std::string line;std::vector<std::pair<int64_t,int64_t>>intervals;while(std::getline(verify,line)){auto p=line.find("\"source_start\":\"");if(p==std::string::npos)continue;p+=16;auto e=line.find('\"',p);int64_t start=std::stoll(line.substr(p,e-p));p=line.find("\"source_end\":\"",e);p+=14;e=line.find('\"',p);int64_t end=std::stoll(line.substr(p,e-p));intervals.emplace_back(start,end);}std::sort(intervals.begin(),intervals.end());int64_t cursor=0;for(auto [a,b]:intervals){if(a!=cursor||b<=a){result.complete=false;break;}cursor=b;}if(cursor!=int64_t(samples.size()))result.complete=false;
}
}
int main(int argc,char**argv){try{fs::path driver;fs::path output;std::string provider;std::vector<fs::path>inputs;for(int i=1;i<argc;i++){std::string a=argv[i];if(a=="--driver"&&i+1<argc)driver=argv[++i];else if(a=="--provider"&&i+1<argc)provider=argv[++i];else if(a=="--output-dir"&&i+1<argc)output=argv[++i];else if(a=="--input"&&i+1<argc)inputs.emplace_back(argv[++i]);else throw std::runtime_error("usage: audio_bench_collect --driver PATH --provider ID --output-dir NEW --input F32 [--input F32 ...]");}if(driver.empty()||provider.empty()||output.empty()||inputs.empty())throw std::runtime_error("missing required argument");if(!fs::is_regular_file(driver))throw std::runtime_error("driver executable not found");if(fs::exists(output))throw std::runtime_error("output directory must be new");fs::create_directories(output);auto config=config_for(provider);auto config_digest=sdk_hash(config.data(),config.size());rusage self_before{};if(getrusage(RUSAGE_SELF,&self_before)!=0)throw std::runtime_error("getrusage self failed");int64_t wall_start=now_ns();Child child(driver,provider);child.send(ab::prepare(0,0,config_digest,config));child.ready();std::vector<CaseResult>results;for(size_t i=0;i<inputs.size();i++){CaseResult r;run_case(child,inputs[i],output,uint64_t(i+1),r);results.push_back(r);if(i+1<inputs.size()){child.send(ab::end_message(ab::Type::Reset,0,child.tx,{uint64_t(i+2),0}));child.ready();}}
 ab::Message close{ab::Type::Close,0,child.tx,{}};child.send(close);rusage usage{};child.finish(usage);int64_t wall_end=now_ns();rusage self_after{};if(getrusage(RUSAGE_SELF,&self_after)!=0)throw std::runtime_error("getrusage self failed");uint64_t worker_cpu_ns=usage_cpu_ns(usage),collector_cpu_ns=usage_cpu_ns(self_after)-usage_cpu_ns(self_before),cpu_ns=worker_cpu_ns+collector_cpu_ns;
#if defined(__APPLE__)
 uint64_t max_rss=uint64_t(usage.ru_maxrss);
 uint64_t collector_rss=uint64_t(self_after.ru_maxrss);
#else
 uint64_t max_rss=uint64_t(usage.ru_maxrss)*1024ULL;
 uint64_t collector_rss=uint64_t(self_after.ru_maxrss)*1024ULL;
#endif
 max_rss=std::max(max_rss,collector_rss);
 std::ofstream summary(output/"collector-summary.json");summary<<"{\"schema_id\":\"audio-bench/local-collector-summary/0.1\",\"sdk_build_id\":"<<q(as_build_id_v0())<<",\"sdk_config_digest\":"<<q("sha256:"+ab::hex_from_digest(config_digest))<<",\"provider_id\":"<<q(provider)<<",\"protocol_version\":1,\"clock\":\"collector CLOCK_MONOTONIC\",\"wall_ns\":\""<<(wall_end-wall_start)<<"\",\"collector_cpu_ns\":\""<<collector_cpu_ns<<"\",\"worker_process_tree_cpu_ns\":\""<<worker_cpu_ns<<"\",\"process_tree_cpu_ns\":\""<<cpu_ns<<"\",\"max_rss_bytes\":\""<<max_rss<<"\",\"cases\":[";for(size_t i=0;i<results.size();i++){const auto&r=results[i];if(i)summary<<',';summary<<"{\"case_id\":"<<q(r.id)<<",\"accepted_samples\":\""<<r.accepted<<"\",\"produced_samples\":\""<<r.produced<<"\",\"output_messages\":"<<r.output_messages<<",\"coverage\":"<<(r.complete?"\"complete\"":"\"incomplete\"")<<"}";}summary<<"]}\n";summary.close();bool complete=std::all_of(results.begin(),results.end(),[](const auto&r){return r.complete;});std::cout<<"cases="<<results.size()<<" wall_ns="<<(wall_end-wall_start)<<" process_tree_cpu_ns="<<cpu_ns<<" max_rss_bytes="<<max_rss<<" coverage="<<(complete?"complete":"incomplete")<<" output="<<output<<"\n";return complete?0:1;}catch(const std::exception&e){std::cerr<<"collector: "<<e.what()<<"\n";return 1;}}
