#include "d256_provider.hpp"
#include <algorithm>
#include <array>
#include <vector>

namespace {
struct Instance {uint64_t epoch;int64_t first;int64_t accepted_end;int64_t next_output;std::vector<float> input;uint32_t drains=0;};
as_status_v0 AS_CALL create(const as_create_config_v0*c,void**out,as_error_v0*){if(!c||!out)return AS_INVALID_ARGUMENT;auto*i=new Instance{c->epoch,c->first_input_sample,c->first_input_sample,c->first_input_sample-256,{}};*out=i;return AS_OK;}
as_status_v0 AS_CALL process(void*opaque,const as_frame_v0*f,const as_output_v0*o,as_result_v0*r){auto*i=static_cast<Instance*>(opaque);if(!i||!f||!o||!o->samples||!r)return AS_INVALID_ARGUMENT;i->input.insert(i->input.end(),f->input,f->input+f->input_valid_count);i->accepted_end=f->first_input_sample+f->input_valid_count;int64_t start=f->first_input_sample-256;for(uint32_t k=0;k<160;k++){int64_t source=start+k;o->samples[k]=(source>=i->first&&source<i->accepted_end)?i->input[size_t(source-i->first)]:0.0f;}as_result_v0_init(r);r->status=AS_OK;r->consumed_count=160;r->produced_count=160;r->epoch=f->epoch;r->source_first_sample=start;int64_t valid_start=std::max<int64_t>(0,start),valid_end=std::min<int64_t>(i->accepted_end,start+160);if(valid_end>valid_start){r->valid_offset=uint32_t(valid_start-start);r->valid_count=uint32_t(valid_end-valid_start);}i->next_output=start+160;return AS_OK;}
as_status_v0 AS_CALL reset(void*opaque,uint64_t epoch,int64_t first,as_error_v0*){auto*i=static_cast<Instance*>(opaque);if(!i)return AS_INVALID_ARGUMENT;i->epoch=epoch;i->first=first;i->accepted_end=first;i->next_output=first-256;i->input.clear();i->drains=0;return AS_OK;}
as_status_v0 AS_CALL drain(void*opaque,const as_output_v0*o,as_result_v0*r){auto*i=static_cast<Instance*>(opaque);if(!i||!o||!o->samples||!r)return AS_INVALID_ARGUMENT;if(i->next_output>=i->accepted_end||i->drains++)return AS_END_OF_STREAM;uint32_t count=uint32_t(std::min<int64_t>(160,i->accepted_end-i->next_output));for(uint32_t k=0;k<160;k++){int64_t source=i->next_output+k;o->samples[k]=(k<count&&source>=i->first)?i->input[size_t(source-i->first)]:0.0f;}as_result_v0_init(r);r->status=AS_OK;r->produced_count=count;r->valid_count=count;r->epoch=i->epoch;r->source_first_sample=i->next_output;i->next_output+=count;return AS_OK;}
void AS_CALL destroy(void*p){delete static_cast<Instance*>(p);}
const as_provider_table_v0 table={sizeof(as_provider_table_v0),AS_ABI_MAJOR,AS_ABI_MINOR,create,process,reset,drain,destroy,{0,0,0,0}};
}
extern "C" const as_provider_table_v0 *audio_bench_d256_provider(){return &table;}
