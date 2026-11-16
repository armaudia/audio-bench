/* SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
 * SPDX-License-Identifier: Apache-2.0
 */
#include <audio_sdk/provider_v0.h>

#include <cstdlib>
#include <cstring>

namespace {
constexpr char kAssetId[] = "benchmark-test-asset";
constexpr char kAssetBytes[] = "audio-bench-asset-test-v1";
constexpr char kDescriptor[] =
    "{\"buffering_delay_samples\":0,\"callback_safe\":false,"
    "\"configuration_schema_digest\":\"sha256:1111111111111111111111111111111111111111111111111111111111111111\","
    "\"contract_version\":\"0.1\",\"edge_exclusions\":{\"end_samples\":0,\"start_samples\":0},"
    "\"execution_modes\":[2],\"implementation_id\":\"audio-bench.test.asset\","
    "\"implementation_version\":\"0.1.0\",\"max_drain_calls\":1,\"native_hop_samples\":160,"
    "\"platform\":{\"architectures\":[\"arm64\",\"x86_64\"],\"cpu_requirements\":\"test fixture\"},"
    "\"provider_id\":\"bench.test.asset.v0\",\"required_assets\":[{\"byte_count\":25,"
    "\"id\":\"benchmark-test-asset\",\"sha256\":\"sha256:e16d1c518a867ae1f5286755082c41176b66d2e28289f1195ed5d8998e3fba02\","
    "\"storage\":\"external\"}],\"schema_id\":\"audio-sdk/descriptor/0.1\","
    "\"source_digest\":\"sha256:2222222222222222222222222222222222222222222222222222222222222222\","
    "\"source_revision\":null,\"supported_formats\":[{\"channels\":1,\"frame_samples\":160,"
    "\"sample_format\":\"f32\",\"sample_rate_hz\":16000}],"
    "\"upstream\":{\"license\":\"Apache-2.0\",\"name\":\"audio-bench test fixture\","
    "\"notice_path\":\"native/tests/provider_asset_plugin.cpp\"}}";

as_status_v0 AS_CALL create(const as_create_config_v0* config, void** out, as_error_v0*) {
  if (!config || !out || config->asset_count != 1 || !config->assets) return AS_INVALID_ARGUMENT;
  const as_asset_v0& asset = config->assets[0];
  if (asset.asset_id_length != sizeof(kAssetId) - 1 ||
      std::memcmp(asset.asset_id, kAssetId, sizeof(kAssetId) - 1) != 0 ||
      asset.byte_count != sizeof(kAssetBytes) - 1 ||
      std::memcmp(asset.data, kAssetBytes, sizeof(kAssetBytes) - 1) != 0) return AS_INVALID_ARGUMENT;
  *out = std::malloc(1);
  return *out ? AS_OK : AS_RESOURCE_EXHAUSTED;
}
as_status_v0 AS_CALL process(void*, const as_frame_v0* frame, const as_output_v0* output,
                             as_result_v0* result) {
  as_result_v0_init(result);
  std::memcpy(output->samples, frame->input, sizeof(float) * frame->input_valid_count);
  result->status = AS_OK;
  result->consumed_count = frame->input_count;
  result->produced_count = frame->input_valid_count;
  result->valid_count = frame->input_valid_count;
  result->epoch = frame->epoch;
  result->source_first_sample = frame->first_input_sample;
  return AS_OK;
}
as_status_v0 AS_CALL reset(void*, uint64_t, int64_t, as_error_v0*) { return AS_OK; }
as_status_v0 AS_CALL drain(void*, const as_output_v0*, as_result_v0*) { return AS_END_OF_STREAM; }
void AS_CALL destroy(void* instance) { std::free(instance); }
const as_provider_table_v0 kTable = {
    sizeof(as_provider_table_v0), AS_ABI_MAJOR, AS_ABI_MINOR,
    create, process, reset, drain, destroy, {0, 0, 0, 0}};
}

extern "C" const as_provider_table_v0* audio_bench_provider_table_v0() { return &kTable; }
extern "C" const char* audio_bench_provider_descriptor_v0(uint32_t* length) {
  *length = static_cast<uint32_t>(sizeof(kDescriptor) - 1);
  return kDescriptor;
}
