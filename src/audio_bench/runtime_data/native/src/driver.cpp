/* SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
 * SPDX-License-Identifier: Apache-2.0
 */
#include "wire.hpp"
#include <audio_sdk/provider_v0.h>
#include <audio_sdk/session_v0.h>
#include <array>
#include <cerrno>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
#include <time.h>
#include <unistd.h>
#include <vector>

namespace {
int64_t monotonic_ns(){timespec t{};if(clock_gettime(CLOCK_MONOTONIC,&t)!=0)throw std::runtime_error("clock_gettime failed");return int64_t(t.tv_sec)*1000000000LL+t.tv_nsec;}
std::array<uint8_t,32> sdk_hash(const void*data,uint64_t size){char out[65]{};if(as_sha256_hex_v0(data,size,out,sizeof(out))!=AS_OK)throw std::runtime_error("SDK SHA-256 helper failed");return ab::digest_from_hex(out);}
std::array<uint8_t,32> build_digest(){
#ifndef AUDIO_BENCH_SDK_PACKAGE_SHA256
#error "SDK package digest must be pinned at configure time"
#endif
 return ab::digest_from_hex(AUDIO_BENCH_SDK_PACKAGE_SHA256);
}
std::array<uint8_t,32> descriptor_digest(as_registry_v0*r,const std::string&id){char out[65]{};if(as_provider_digest_v0(r,id.data(),uint32_t(id.size()),out,sizeof(out))!=AS_OK)throw std::runtime_error("provider digest query failed");return ab::digest_from_hex(out);}
std::string effective_config(as_registry_v0*r,const std::string&id,uint32_t mode){uint32_t n=0;as_error_v0 e;as_error_v0_init(&e);std::vector<char>b(AS_MAX_CONTROL_BYTES+1);auto s=as_effective_config_create_v0(r,id.data(),uint32_t(id.size()),mode,b.data(),uint32_t(b.size()),&n,&e);if(s!=AS_OK||n==0||n>b.size()||b[n-1]!='\0')throw std::runtime_error("effective config generation failed");return std::string(b.data(),n-1);}
struct Driver {
 std::string provider; as_registry_v0*registry=nullptr;as_session_v0*session=nullptr;uint64_t rx=0,tx=0,epoch=0;int64_t next_sample=0,accepted_end=0;bool drained=false;std::string config;
 ~Driver(){if(session)as_session_close_v0(&session);if(registry)as_registry_close_v0(&registry);}
 void send(ab::Message m){m.sequence=tx++;ab::write_message(STDOUT_FILENO,m);}
 ab::Message receive(){auto m=ab::read_message(STDIN_FILENO);if(m.stream!=0||m.sequence!=rx++)throw std::runtime_error("duplicate/out-of-order IPC sequence or stream");return m;}
 void send_ready(){send(ab::ready(0,0,build_digest(),descriptor_digest(registry,provider)));}
 void create(const std::string&json,uint64_t new_epoch,int64_t first){config=json;epoch=new_epoch;next_sample=first;accepted_end=first;as_error_v0 error;as_error_v0_init(&error);as_create_config_v0 c;as_create_config_v0_init(&c);c.sample_rate_hz=16000;c.channels=1;c.frame_samples=160;c.execution_mode=AS_MODE_PROCESSING_THREAD;c.epoch=epoch;c.first_input_sample=first;c.config_json=config.data();c.config_json_length=uint32_t(config.size());auto s=as_session_create_v0(registry,provider.data(),uint32_t(provider.size()),&c,&session,&error);if(s!=AS_OK)throw std::runtime_error(std::string("session create: ")+error.message);}
 void output(const as_result_v0&r,const std::array<float,160>&samples,uint32_t phase,int64_t start,int64_t finish){ab::Output o{};o.epoch=r.epoch;o.source_first=r.source_first_sample;o.produced=r.produced_count;o.valid_offset=r.valid_offset;o.valid=r.valid_count;o.flags=r.flags;o.phase=phase;o.service_begin=start;o.service_end=finish;o.samples=samples;send(ab::output_message(0,0,o));}
 void process(const ab::Input&i){if(drained||i.epoch!=epoch||i.first!=next_sample)throw std::runtime_error("INPUT epoch/source position mismatch");as_frame_v0 f;as_frame_v0_init(&f);f.input=i.samples.data();f.input_count=160;f.input_valid_count=i.valid;f.flags=(i.flags&1)?AS_FRAME_FINAL_INPUT:0;f.epoch=i.epoch;f.first_input_sample=i.first;std::array<float,160>samples{};as_output_v0 o;as_output_v0_init(&o);o.samples=samples.data();o.capacity=160;as_result_v0 result;as_result_v0_init(&result);int64_t start=monotonic_ns();auto status=as_session_process_v0(session,&f,&o,&result);int64_t finish=monotonic_ns();if(status!=AS_OK||result.status!=AS_OK)throw std::runtime_error(std::string("SDK process failed: ")+as_status_name_v0(status));if(result.consumed_count!=160||result.produced_count>160||result.valid_offset>result.produced_count||result.valid_count>result.produced_count-result.valid_offset)throw std::runtime_error("SDK returned invalid process counts");output(result,samples,ab::kPhaseProcess,start,finish);next_sample+=i.valid;accepted_end=next_sample;}
 void drain(const ab::End&end){if(drained||end.epoch!=epoch||end.sample!=accepted_end)throw std::runtime_error("END_INPUT does not match accepted source end");auto s=as_session_begin_drain_v0(session);if(s!=AS_OK)throw std::runtime_error("SDK begin drain failed");for(uint32_t n=0;n<1024;n++){std::array<float,160>samples{};as_output_v0 out;as_output_v0_init(&out);out.samples=samples.data();out.capacity=160;as_result_v0 r;as_result_v0_init(&r);int64_t start=monotonic_ns();s=as_session_drain_next_v0(session,&out,&r);int64_t finish=monotonic_ns();if(s==AS_END_OF_STREAM){send(ab::end_message(ab::Type::Drained,0,0,{epoch,accepted_end}));drained=true;return;}if(s!=AS_OK||r.status!=AS_OK)throw std::runtime_error(std::string("SDK drain failed: ")+as_status_name_v0(s));if(r.produced_count>160||r.valid_offset>r.produced_count||r.valid_count>r.produced_count-r.valid_offset)throw std::runtime_error("SDK returned invalid drain counts");if(r.produced_count)output(r,samples,ab::kPhaseDrain,start,finish);}throw std::runtime_error("SDK exceeded bounded drain loop");}
  int run(){auto first=receive();if(first.type!=ab::Type::Prepare)throw std::runtime_error("expected PREPARE");if(first.payload.size()<36)throw std::runtime_error("short PREPARE");std::array<uint8_t,32>digest{};std::copy_n(first.payload.begin(),32,digest.begin());uint32_t n=uint32_t(first.payload[32])|(uint32_t(first.payload[33])<<8)|(uint32_t(first.payload[34])<<16)|(uint32_t(first.payload[35])<<24);config.assign(reinterpret_cast<const char*>(first.payload.data()+36),n);if(sdk_hash(config.data(),config.size())!=digest)throw std::runtime_error("PREPARE digest mismatch");as_error_v0 error;as_error_v0_init(&error);if(as_registry_create_v0(&registry,&error)!=AS_OK)throw std::runtime_error("SDK registry create failed");std::string expected=effective_config(registry,provider,AS_MODE_PROCESSING_THREAD);if(expected!=config)throw std::runtime_error("PREPARE effective config differs from SDK-generated config");create(config,1,0);send_ready();for(;;){auto m=receive();if(m.type==ab::Type::Input){process(ab::decode_input(m));continue;}if(m.type==ab::Type::EndInput){drain(ab::decode_end(m));continue;}if(m.type==ab::Type::Reset){if(!drained)throw std::runtime_error("RESET before DRAINED");auto reset=ab::decode_end(m);if(reset.epoch<=epoch)throw std::runtime_error("RESET epoch must increase");auto s=as_session_close_v0(&session);if(s!=AS_OK)throw std::runtime_error("SDK session close before RESET failed");create(config,reset.epoch,reset.sample);drained=false;send_ready();continue;}if(m.type==ab::Type::Close){if(!drained)throw std::runtime_error("CLOSE before DRAINED");return 0;}throw std::runtime_error("unexpected message type from collector");}}
};
}
int main(int argc,char**argv){if(argc!=3||std::string(argv[1])!="--provider"){std::cerr<<"usage: audio_bench_driver --provider <id>\n";return 2;}try{Driver d;d.provider=argv[2];return d.run();}catch(const std::exception&e){std::cerr<<"driver: "<<e.what()<<"\n";return 1;}}
