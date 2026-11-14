/* SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
 * SPDX-License-Identifier: Apache-2.0
 */
#include "wire.hpp"
#include <audio_sdk/provider_v0.h>
#include <audio_sdk/session_v0.h>
#include <array>
#include <algorithm>
#include <chrono>
#include <cerrno>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <mutex>
#include <string>
#include <thread>
#include <condition_variable>
#include <exception>
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
std::array<uint8_t,32> pinned_package_digest(){
#ifndef AUDIO_BENCH_SDK_PACKAGE_SHA256
#error "SDK package digest must be pinned at configure time"
#endif
 return ab::digest_from_hex(AUDIO_BENCH_SDK_PACKAGE_SHA256);
}
std::string config_for(const std::string&id){as_registry_v0*r=nullptr;as_error_v0 e;as_error_v0_init(&e);if(as_registry_create_v0(&r,&e)!=AS_OK)throw std::runtime_error("SDK registry create failed");uint32_t n=0;std::vector<char>b(AS_MAX_CONTROL_BYTES+1);auto s=as_effective_config_create_v0(r,id.data(),uint32_t(id.size()),AS_MODE_PROCESSING_THREAD,b.data(),uint32_t(b.size()),&n,&e);if(s!=AS_OK||n==0||n>b.size()||b[n-1]!='\0'){as_registry_close_v0(&r);throw std::runtime_error("SDK effective config generation failed");}std::string value(b.data(),n-1);as_registry_close_v0(&r);return value;}
std::array<uint8_t,32> descriptor_digest_for(const std::string&id){as_registry_v0*r=nullptr;as_error_v0 e;as_error_v0_init(&e);if(as_registry_create_v0(&r,&e)!=AS_OK)throw std::runtime_error("SDK registry create failed");char out[65]{};auto s=as_provider_digest_v0(r,id.data(),uint32_t(id.size()),out,sizeof(out));as_registry_close_v0(&r);if(s!=AS_OK)throw std::runtime_error("SDK provider digest query failed");return ab::digest_from_hex(out);}
struct Child {
 pid_t pid=-1;int to_child=-1;int from_child=-1;uint64_t tx=0,rx=0;uint64_t epoch=1;int64_t deadline_ns=0;
 int timeout_ms()const{int64_t left=deadline_ns-now_ns();if(left<=0)throw std::runtime_error("collector whole-run absolute deadline exceeded");return int(std::min<int64_t>(30000,(left+999999)/1000000));}
 void close_input(){if(to_child>=0){close(to_child);to_child=-1;}}
 Child(const fs::path&driver,const std::string&provider):deadline_ns(now_ns()+300000000000LL){int in[2],out[2];if(pipe(in)||pipe(out))throw std::runtime_error("pipe creation failed");pid=fork();if(pid<0)throw std::runtime_error("fork failed");if(pid==0){setpgid(0,0);dup2(in[0],STDIN_FILENO);dup2(out[1],STDOUT_FILENO);close(in[0]);close(in[1]);close(out[0]);close(out[1]);execl(driver.c_str(),driver.c_str(),"--provider",provider.c_str(),static_cast<char*>(nullptr));_exit(127);}setpgid(pid,pid);close(in[0]);close(out[1]);to_child=in[1];from_child=out[0];nonblocking(to_child);nonblocking(from_child);}
 ~Child(){if(pid>0){kill(-pid,SIGKILL);kill(pid,SIGKILL);int status=0;const int64_t cleanup_deadline=now_ns()+2000000000LL;while(now_ns()<cleanup_deadline){pid_t result=waitpid(pid,&status,WNOHANG);if(result==pid|| (result<0&&errno==ECHILD)){pid=-1;break;}if(result<0&&errno!=EINTR)break;timespec pause{0,10000000};nanosleep(&pause,nullptr);}if(pid>0)std::cerr<<"collector: child cleanup was not verified before 2-second deadline\n";}if(to_child>=0)close(to_child);if(from_child>=0)close(from_child);}
 void send(ab::Message m){m.stream=0;m.sequence=tx++;ab::write_message(to_child,m,timeout_ms());}
 ab::Message receive(){auto m=ab::read_message(from_child,timeout_ms());if(m.stream!=0||m.sequence!=rx++)throw std::runtime_error("driver duplicate/out-of-order sequence or stream");if(m.type==ab::Type::Error){throw std::runtime_error("driver error status="+std::to_string(int32_t(m.payload[8]|uint32_t(m.payload[9])<<8|uint32_t(m.payload[10])<<16|uint32_t(m.payload[11])<<24)));}return m;}
  void ready(const std::array<uint8_t,32>&expected_build,const std::array<uint8_t,32>&expected_descriptor){auto m=receive();if(m.type!=ab::Type::Ready||m.payload.size()!=64)throw std::runtime_error("expected READY");if(!std::equal(expected_build.begin(),expected_build.end(),m.payload.begin()))throw std::runtime_error("READY SDK package digest mismatch");if(!std::equal(expected_descriptor.begin(),expected_descriptor.end(),m.payload.begin()+32))throw std::runtime_error("READY provider descriptor digest mismatch");}
 int finish(rusage&usage){if(to_child>=0){close(to_child);to_child=-1;}int status=0;struct rusage local{};const int64_t deadline=std::min<int64_t>(deadline_ns,now_ns()+30000000000LL);pid_t result=0;while(now_ns()<deadline){result=wait4(pid,&status,WNOHANG,&local);if(result==pid)break;if(result<0&&errno!=EINTR)throw std::runtime_error("wait4 failed");timespec pause{0,10000000};nanosleep(&pause,nullptr);}if(result!=pid){kill(-pid,SIGKILL);kill(pid,SIGKILL);const int64_t cleanup_deadline=now_ns()+2000000000LL;while(now_ns()<cleanup_deadline){result=wait4(pid,&status,WNOHANG,&local);if(result==pid)break;if(result<0&&errno!=EINTR)break;timespec pause{0,10000000};nanosleep(&pause,nullptr);}if(result!=pid)throw std::runtime_error("child cleanup could not be verified before deadline");pid=-1;throw std::runtime_error("driver shutdown exceeded absolute deadline and was killed");}pid=-1;usage=local;if(from_child>=0){close(from_child);from_child=-1;}if(!WIFEXITED(status)||WEXITSTATUS(status)!=0)throw std::runtime_error("driver exited unsuccessfully");return status;}
};
std::vector<float> read_f32(const fs::path&path){std::ifstream f(path,std::ios::binary);if(!f)throw std::runtime_error("cannot open input: "+path.string());f.seekg(0,std::ios::end);auto bytes=f.tellg();if(bytes<0||bytes%4)throw std::runtime_error("input must be little-endian float32 bytes");f.seekg(0);std::vector<float>v(size_t(bytes)/4);if(!v.empty())f.read(reinterpret_cast<char*>(v.data()),bytes);if(!f||!std::all_of(v.begin(),v.end(),[](float x){return std::isfinite(x);}))throw std::runtime_error("input contains non-finite or unreadable samples");return v;}
void write_f32(std::ofstream&out,const std::array<float,160>&samples,uint32_t count){out.write(reinterpret_cast<const char*>(samples.data()),std::streamsize(count*sizeof(float)));if(!out)throw std::runtime_error("output write failed");}
std::string q(const std::string&s){std::string o="\"";for(unsigned char c:s){if(c=='\"'||c=='\\'){o.push_back('\\');o.push_back(char(c));}else if(c<0x20){static const char*h="0123456789abcdef";o+="\\u00";o.push_back(h[c>>4]);o.push_back(h[c&15]);}else o.push_back(char(c));}return o+'\"';}
struct CaseResult {std::string id;uint64_t samples=0,accepted=0,produced=0;bool complete=true;uint64_t output_messages=0;};
uint64_t usage_cpu_ns(const rusage&u){return uint64_t(u.ru_utime.tv_sec+u.ru_stime.tv_sec)*1000000000ULL+uint64_t(u.ru_utime.tv_usec+u.ru_stime.tv_usec)*1000ULL;}
void accept_output(const ab::Message&m,uint64_t epoch,uint32_t expected_phase,CaseResult&result,std::ofstream&audio,std::ofstream&maps){if(m.type!=ab::Type::Output)throw std::runtime_error("expected OUTPUT or DRAINED");auto o=ab::decode_output(m);int64_t receive_ns=now_ns();if(o.epoch!=epoch||o.phase!=expected_phase)throw std::runtime_error("OUTPUT epoch/phase mismatch");uint64_t output_offset=result.produced;if(o.produced)write_f32(audio,o.samples,o.produced);result.produced+=o.produced;result.output_messages++;if(o.valid){int64_t begin=o.source_first+o.valid_offset;int64_t end=begin+o.valid;maps<<"{\"phase\":"<<q(expected_phase==ab::kPhaseProcess?"process":"drain")<<",\"source_start\":\""<<begin<<"\",\"source_end\":\""<<end<<"\",\"output_offset_samples\":\""<<output_offset<<"\",\"source_first_sample\":\""<<o.source_first<<"\",\"produced_count\":"<<o.produced<<",\"valid_offset\":"<<o.valid_offset<<",\"valid_count\":"<<o.valid<<",\"flags\":"<<o.flags<<",\"collector_receive_monotonic_ns\":\""<<receive_ns<<"\",\"candidate_service_begin_ns\":\""<<o.service_begin<<"\",\"candidate_service_end_ns\":\""<<o.service_end<<"\"}\n";}}
struct PaceRecord {int64_t target=0,send_begin=0,submitted=0,completed=0;uint32_t in_flight=0;};
ab::Message input_message(const std::vector<float>&samples,size_t frame,uint64_t epoch,uint64_t sequence,int64_t origin=0){
 const size_t offset=frame*160;const size_t count=std::min<size_t>(160,samples.size()-offset);ab::Input in{};in.epoch=epoch;in.first=origin+int64_t(offset);in.valid=uint32_t(count);in.flags=count<160?1u:0u;std::copy_n(samples.begin()+offset,count,in.samples.begin());return ab::input_message(0,sequence,in);
}
void run_warmup(Child&child,const std::vector<float>&samples,uint64_t epoch,
                uint32_t warmup_ms){
 if(warmup_ms==0)return;
 if(samples.empty())throw std::runtime_error("paced warmup requires nonempty input");
 const uint64_t frames=uint64_t(warmup_ms/10u);
 const int64_t start=now_ns();
 std::array<float,160> frame_samples{};
 for(uint64_t frame=0;frame<frames;++frame){
  const int64_t target=start+int64_t(frame+1u)*10000000LL;
  for(;;){
   const int64_t left=target-now_ns();
   if(left<=0)break;
   timespec wait{time_t(left/1000000000LL),long(left%1000000000LL)};
   while(nanosleep(&wait,&wait)!=0&&errno==EINTR){}
  }
  for(size_t i=0;i<frame_samples.size();++i)
   frame_samples[i]=samples[(size_t(frame*160u)+i)%samples.size()];
  ab::Input input{};input.epoch=epoch;input.first=int64_t(frame*160u);
  input.valid=160;input.samples=frame_samples;
  child.send(ab::input_message(0,0,input));
  auto response=child.receive();
  if(response.type!=ab::Type::Output)throw std::runtime_error("warmup expected OUTPUT");
  auto output=ab::decode_output(response);
  if(output.epoch!=epoch||output.phase!=ab::kPhaseProcess||
     output.produced>160||output.valid>output.produced||
     uint32_t(output.valid_offset)+uint32_t(output.valid)>output.produced)
   throw std::runtime_error("warmup output metadata mismatch");
 }
}
bool wait_until_or_abort(int64_t deadline,std::mutex&mutex,std::condition_variable&ready,bool&aborted){
 for(;;){const int64_t left=deadline-now_ns();if(left<=0)return true;std::unique_lock lock(mutex);if(ready.wait_for(lock,std::chrono::nanoseconds(left),[&]{return aborted;}))return false;}
}
void run_case(Child&child,const fs::path&input,const fs::path&output_dir,uint64_t epoch,CaseResult&result,bool paced,int64_t origin=0){
 auto samples=read_f32(input);result.id=input.stem().string();result.samples=samples.size();child.epoch=epoch;
 fs::path raw=output_dir/(result.id+".raw.f32"),maps_path=output_dir/(result.id+".intervals.jsonl"),pace_path=output_dir/(result.id+".pacing.jsonl");
 std::ofstream audio(raw,std::ios::binary|std::ios::out|std::ios::trunc),maps(maps_path,std::ios::out|std::ios::trunc),pacing(pace_path,std::ios::out|std::ios::trunc);
 if(!audio||!maps||!pacing)throw std::runtime_error("cannot create case output artifacts");
 const size_t frame_count=(samples.size()+159u)/160u;const int64_t capture_t0=now_ns();uint64_t seq=1;
 if(!paced){for(size_t frame=0;frame<frame_count;++frame){child.send(input_message(samples,frame,epoch,seq++,origin));auto message=child.receive();accept_output(message,epoch,ab::kPhaseProcess,result,audio,maps);result.accepted+=std::min<size_t>(160,samples.size()-frame*160);}}
 else {
  constexpr uint32_t kMaxInFlight=3;std::vector<PaceRecord>records(frame_count);std::mutex mutex;std::condition_variable ready;uint32_t in_flight=0;bool aborted=false;std::exception_ptr send_error;uint64_t sequence=seq;
  std::thread sender([&]{try{for(size_t frame=0;frame<frame_count;++frame){auto&record=records[frame];record.target=capture_t0+int64_t(frame+1)*10000000LL;if(!wait_until_or_abort(record.target,mutex,ready,aborted))break;{std::unique_lock lock(mutex);ready.wait(lock,[&]{return aborted||in_flight<kMaxInFlight;});if(aborted)break;++in_flight;record.in_flight=in_flight;}record.send_begin=now_ns();child.send(input_message(samples,frame,epoch,sequence++,origin));record.submitted=now_ns();}}catch(...){send_error=std::current_exception();{std::lock_guard lock(mutex);aborted=true;}child.close_input();ready.notify_all();}});
  std::exception_ptr receive_error;try{for(size_t frame=0;frame<frame_count;++frame){auto message=child.receive();records[frame].completed=now_ns();accept_output(message,epoch,ab::kPhaseProcess,result,audio,maps);result.accepted+=std::min<size_t>(160,samples.size()-frame*160);{std::lock_guard lock(mutex);if(in_flight==0)throw std::runtime_error("paced response arrived without an in-flight frame");--in_flight;}ready.notify_all();}}catch(...){receive_error=std::current_exception();{std::lock_guard lock(mutex);aborted=true;}ready.notify_all();}
  sender.join();if(send_error)std::rethrow_exception(send_error);if(receive_error)std::rethrow_exception(receive_error);seq=sequence;
  for(size_t frame=0;frame<records.size();++frame){const auto&r=records[frame];pacing<<"{\"frame\":"<<frame<<",\"scheduled_submit_ns\":\""<<r.target<<"\",\"send_begin_ns\":\""<<r.send_begin<<"\",\"submitted_ns\":\""<<r.submitted<<"\",\"completed_ns\":\""<<r.completed<<"\",\"in_flight_at_send\":"<<r.in_flight<<",\"submission_lateness_ns\":\""<<std::max<int64_t>(0,r.submitted-r.target)<<"\",\"completion_lateness_ns\":\""<<std::max<int64_t>(0,r.completed-r.target)<<"\",\"send_backpressure_ns\":\""<<std::max<int64_t>(0,r.submitted-r.send_begin)<<"\"}\n";}
 }
 child.send(ab::end_message(ab::Type::EndInput,0,seq++,{epoch,origin+int64_t(samples.size())}));for(uint32_t calls=0;calls<1025;calls++){auto m=child.receive();if(m.type==ab::Type::Drained){auto ack=ab::decode_end(m);if(ack.epoch!=epoch||ack.sample!=origin+int64_t(samples.size()))throw std::runtime_error("DRAINED acknowledgement mismatch");break;}accept_output(m,epoch,ab::kPhaseDrain,result,audio,maps);if(calls==1024)throw std::runtime_error("drain completion exceeded bound");}
 audio.flush();maps.flush();pacing.flush();if(!audio||!maps||!pacing)throw std::runtime_error("failed flushing retained output");
 // Verify exact source coverage; gaps/overlaps remain a failed row, never a fitted crop.
 std::ifstream verify(maps_path);std::string line;std::vector<std::pair<int64_t,int64_t>>intervals;while(std::getline(verify,line)){auto p=line.find("\"source_start\":\"");if(p==std::string::npos)continue;p+=16;auto e=line.find('\"',p);int64_t start=std::stoll(line.substr(p,e-p));p=line.find("\"source_end\":\"",e);p+=14;e=line.find('\"',p);int64_t end=std::stoll(line.substr(p,e-p));intervals.emplace_back(start,end);}std::sort(intervals.begin(),intervals.end());int64_t cursor=origin;for(auto [a,b]:intervals){if(a!=cursor||b<=a){result.complete=false;break;}cursor=b;}if(cursor!=origin+int64_t(samples.size()))result.complete=false;
}
}
int main(int argc,char**argv){try{signal(SIGPIPE,SIG_IGN);fs::path driver;fs::path output;std::string provider;std::vector<fs::path>inputs;bool print_config=false,paced=false;uint32_t warmup_ms=10000;for(int i=1;i<argc;i++){std::string a=argv[i];if(a=="--effective-config")print_config=true;else if(a=="--paced")paced=true;else if(a=="--warmup-ms"&&i+1<argc){char*end=nullptr;unsigned long value=strtoul(argv[++i],&end,10);if(end==argv[i]||*end!='\0'||value>600000||value%10!=0)throw std::runtime_error("warmup must be a multiple of 10 ms in [0,600000]");warmup_ms=uint32_t(value);}else if(a=="--driver"&&i+1<argc)driver=argv[++i];else if(a=="--provider"&&i+1<argc)provider=argv[++i];else if(a=="--output-dir"&&i+1<argc)output=argv[++i];else if(a=="--input"&&i+1<argc)inputs.emplace_back(argv[++i]);else throw std::runtime_error("usage: audio_bench_collect [--paced] [--warmup-ms N] --driver PATH --provider ID --output-dir NEW --input F32 [--input F32 ...]");}if(provider.empty())throw std::runtime_error("missing provider");if(print_config){std::cout<<config_for(provider)<<'\n';return 0;}if(driver.empty()||output.empty()||inputs.empty())throw std::runtime_error("missing required argument");if(!paced&&warmup_ms!=10000)throw std::runtime_error("--warmup-ms is only valid with --paced");if(!fs::is_regular_file(driver))throw std::runtime_error("driver executable not found");if(fs::exists(output))throw std::runtime_error("output directory must be new");fs::create_directories(output);auto config=config_for(provider);auto config_digest=sdk_hash(config.data(),config.size());auto expected_build=pinned_package_digest();auto expected_descriptor=descriptor_digest_for(provider);rusage self_before{};if(getrusage(RUSAGE_SELF,&self_before)!=0)throw std::runtime_error("getrusage self failed");int64_t wall_start=now_ns();Child child(driver,provider);child.send(ab::prepare(0,0,config_digest,config));child.ready(expected_build,expected_descriptor);std::vector<CaseResult>results;for(size_t i=0;i<inputs.size();i++){uint64_t warmup_frames=0;if(paced&&warmup_ms>0){auto warm_samples=read_f32(inputs[i]);run_warmup(child,warm_samples,uint64_t(i+1),warmup_ms);warmup_frames=warmup_ms/10u;}CaseResult r;run_case(child,inputs[i],output,uint64_t(i+1),r,paced,int64_t(warmup_frames)*160);results.push_back(r);if(i+1<inputs.size()){child.send(ab::end_message(ab::Type::Reset,0,child.tx,{uint64_t(i+2),0}));child.ready(expected_build,expected_descriptor);}}
 ab::Message close{ab::Type::Close,0,child.tx,{}};child.send(close);rusage usage{};child.finish(usage);int64_t wall_end=now_ns();rusage self_after{};if(getrusage(RUSAGE_SELF,&self_after)!=0)throw std::runtime_error("getrusage self failed");uint64_t worker_cpu_ns=usage_cpu_ns(usage),collector_cpu_ns=usage_cpu_ns(self_after)-usage_cpu_ns(self_before);
#if defined(__APPLE__)
 uint64_t max_rss=uint64_t(usage.ru_maxrss);
 uint64_t collector_rss=uint64_t(self_after.ru_maxrss);
#else
 uint64_t max_rss=uint64_t(usage.ru_maxrss)*1024ULL;
 uint64_t collector_rss=uint64_t(self_after.ru_maxrss)*1024ULL;
#endif
 std::ofstream summary(output/"collector-summary.json");summary<<"{\"schema_id\":\"audio-bench/local-collector-summary/0.1\",\"sdk_build_id\":"<<q(as_build_id_v0())<<",\"sdk_package_digest\":"<<q("sha256:"+ab::hex_from_digest(pinned_package_digest()))<<",\"sdk_config_digest\":"<<q("sha256:"+ab::hex_from_digest(config_digest))<<",\"provider_id\":"<<q(provider)<<",\"mode\":"<<q(paced?"paced":"sequential")<<",\"frame_period_ns\":\"10000000\",\"warmup_ms\":"<<(paced?warmup_ms:0)<<",\"protocol_version\":1,\"clock\":\"collector CLOCK_MONOTONIC\",\"wall_ns\":\""<<(wall_end-wall_start)<<"\",\"collector_cpu_ns\":\""<<collector_cpu_ns<<"\",\"direct_child_cpu_ns\":\""<<worker_cpu_ns<<"\",\"direct_child_max_rss_bytes\":\""<<max_rss<<"\",\"collector_max_rss_bytes\":\""<<collector_rss<<"\",\"rss_semantics\":\"per-process high-water marks; not process-tree peak\",\"cases\":[";for(size_t i=0;i<results.size();i++){const auto&r=results[i];if(i)summary<<',';summary<<"{\"case_id\":"<<q(r.id)<<",\"source_samples\":\""<<r.samples<<"\",\"accepted_samples\":\""<<r.accepted<<"\",\"produced_samples\":\""<<r.produced<<"\",\"output_messages\":"<<r.output_messages<<",\"coverage\":"<<(r.complete?"\"complete\"":"\"incomplete\"")<<"}";}summary<<"]}\n";summary.close();bool complete=std::all_of(results.begin(),results.end(),[](const auto&r){return r.complete;});std::cout<<"cases="<<results.size()<<" wall_ns="<<(wall_end-wall_start)<<" direct_child_cpu_ns="<<worker_cpu_ns<<" collector_cpu_ns="<<collector_cpu_ns<<" coverage="<<(complete?"complete":"incomplete")<<" output="<<output<<"\n";return complete?0:1;}catch(const std::exception&e){std::cerr<<"collector: "<<e.what()<<"\n";return 1;}}
