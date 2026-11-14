/* SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
 * SPDX-License-Identifier: Apache-2.0
 */
#include "d256_provider.hpp"

#include <algorithm>
#include <cstdint>
#include <vector>

namespace {

struct Instance {
    uint64_t epoch;
    int64_t first;
    int64_t accepted_end;
    int64_t next_output;
    std::vector<float> input;
};

as_status_v0 AS_CALL create(const as_create_config_v0 *config, void **out, as_error_v0 *) {
    if (config == nullptr || out == nullptr) return AS_INVALID_ARGUMENT;
    *out = new Instance{config->epoch, config->first_input_sample,
                        config->first_input_sample, config->first_input_sample - 256, {}};
    return AS_OK;
}

as_status_v0 AS_CALL process(void *opaque, const as_frame_v0 *frame,
                             const as_output_v0 *output, as_result_v0 *result) {
    auto *instance = static_cast<Instance *>(opaque);
    if (instance == nullptr || frame == nullptr || output == nullptr ||
        output->samples == nullptr || result == nullptr)
        return AS_INVALID_ARGUMENT;

    instance->input.insert(instance->input.end(), frame->input,
                           frame->input + frame->input_valid_count);
    instance->accepted_end = frame->first_input_sample + frame->input_valid_count;
    const int64_t source_first = frame->first_input_sample - 256;
    for (uint32_t i = 0; i < 160; ++i) {
        const int64_t source = source_first + i;
        output->samples[i] = source >= instance->first && source < instance->accepted_end
            ? instance->input[static_cast<size_t>(source - instance->first)]
            : 0.0f;
    }

    as_result_v0_init(result);
    result->status = AS_OK;
    result->consumed_count = 160;
    result->produced_count = 160;
    result->epoch = frame->epoch;
    result->source_first_sample = source_first;
    const int64_t valid_start = std::max(instance->first, source_first);
    const int64_t valid_end = std::min(instance->accepted_end, source_first + 160);
    result->valid_offset = static_cast<uint32_t>(std::clamp<int64_t>(
        valid_start - source_first, 0, 160));
    result->valid_count = static_cast<uint32_t>(
        std::max<int64_t>(0, valid_end - std::max(valid_start, source_first)));
    instance->next_output = source_first + 160;
    return AS_OK;
}

as_status_v0 AS_CALL reset(void *opaque, uint64_t epoch, int64_t first, as_error_v0 *) {
    auto *instance = static_cast<Instance *>(opaque);
    if (instance == nullptr) return AS_INVALID_ARGUMENT;
    instance->epoch = epoch;
    instance->first = first;
    instance->accepted_end = first;
    instance->next_output = first - 256;
    instance->input.clear();
    return AS_OK;
}

as_status_v0 AS_CALL drain(void *opaque, const as_output_v0 *output, as_result_v0 *result) {
    auto *instance = static_cast<Instance *>(opaque);
    if (instance == nullptr || output == nullptr || output->samples == nullptr || result == nullptr)
        return AS_INVALID_ARGUMENT;
    if (instance->accepted_end == instance->first ||
        instance->next_output >= instance->accepted_end)
        return AS_END_OF_STREAM;

    for (uint32_t i = 0; i < 160; ++i) {
        const int64_t source = instance->next_output + i;
        output->samples[i] = source >= instance->first && source < instance->accepted_end
            ? instance->input[static_cast<size_t>(source - instance->first)]
            : 0.0f;
    }
    as_result_v0_init(result);
    result->status = AS_OK;
    result->produced_count = 160;
    result->epoch = instance->epoch;
    result->source_first_sample = instance->next_output;
    const int64_t valid_start = std::max(instance->first, instance->next_output);
    const int64_t valid_end = std::min(instance->accepted_end, instance->next_output + 160);
    result->valid_offset = static_cast<uint32_t>(std::clamp<int64_t>(
        valid_start - instance->next_output, 0, 160));
    result->valid_count = static_cast<uint32_t>(
        std::max<int64_t>(0, valid_end - std::max(valid_start, instance->next_output)));
    instance->next_output += 160;
    return AS_OK;
}

void AS_CALL destroy(void *opaque) {
    delete static_cast<Instance *>(opaque);
}

const as_provider_table_v0 table = {
    sizeof(as_provider_table_v0), AS_ABI_MAJOR, AS_ABI_MINOR,
    create, process, reset, drain, destroy, {0, 0, 0, 0}
};

} // namespace

extern "C" const as_provider_table_v0 *audio_bench_d256_provider() {
    return &table;
}
