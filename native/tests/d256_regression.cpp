#include "d256_provider.hpp"

#include <audio_sdk/session_v0.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {

constexpr uint32_t kDelay = 256;
constexpr uint32_t kFrame = 160;
constexpr int64_t kOrigin = 12345;
constexpr uint32_t kMaxWaitMs = 5000;

std::string read_file(const char *path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error(std::string("fixture file missing: ") + path);
    return {std::istreambuf_iterator<char>(input), {}};
}

[[noreturn]] void fail(const std::string &message) {
    throw std::runtime_error(message);
}

void check_status(as_status_v0 actual, as_status_v0 expected, const char *operation) {
    if (actual != expected) {
        fail(std::string(operation) + " returned " + as_status_name_v0(actual) +
             ", expected " + as_status_name_v0(expected));
    }
}

struct Session {
    as_registry_v0 *registry = nullptr;
    as_session_v0 *session = nullptr;
    std::string provider_id = "bench.delay256.fixture.v0";
    uint32_t mode = 0;
    uint64_t epoch = 1;
    int64_t origin = kOrigin;
    std::string config;

    ~Session() {
        if (session) as_session_close_v0(&session);
        if (registry) as_registry_close_v0(&registry);
    }

    void create(const std::string &descriptor, uint64_t new_epoch, int64_t first) {
        if (registry == nullptr) {
            as_error_v0 error;
            as_error_v0_init(&error);
            check_status(as_registry_create_v0(&registry, &error), AS_OK, "registry create");
            check_status(as_register_provider_v0(
                             registry, audio_bench_d256_provider(),
                             descriptor.data(), static_cast<uint32_t>(descriptor.size()), &error),
                         AS_OK, "fixture provider registration");
        }
        epoch = new_epoch;
        origin = first;
        as_error_v0 error;
        as_error_v0_init(&error);
        uint32_t required = 0;
        std::vector<char> buffer(AS_MAX_CONTROL_BYTES + 1);
        check_status(as_effective_config_create_v0(
                         registry, provider_id.data(), static_cast<uint32_t>(provider_id.size()),
                         mode, buffer.data(), static_cast<uint32_t>(buffer.size()),
                         &required, &error),
                     AS_OK, "effective config generation");
        if (required < 2 || required > buffer.size() || buffer[required - 1] != '\0')
            fail("effective config size/terminator invalid");
        config.assign(buffer.data(), required - 1);

        as_create_config_v0 create_config;
        as_create_config_v0_init(&create_config);
        create_config.execution_mode = mode;
        create_config.epoch = epoch;
        create_config.first_input_sample = origin;
        create_config.config_json = config.data();
        create_config.config_json_length = static_cast<uint32_t>(config.size());
        if (session != nullptr)
            check_status(as_session_close_v0(&session), AS_OK, "prior session close");
        check_status(as_session_create_v0(
                         registry, provider_id.data(), static_cast<uint32_t>(provider_id.size()),
                         &create_config, &session, &error),
                     AS_OK, "session create");
    }
};

struct Output {
    as_result_v0 result{};
    std::array<float, kFrame> samples{};
};

Output make_output() {
    Output output;
    as_result_v0_init(&output.result);
    return output;
}

as_output_v0 sdk_output(Output &output) {
    as_output_v0 value;
    as_output_v0_init(&value);
    value.samples = output.samples.data();
    value.capacity = kFrame;
    return value;
}

Output next_buffered(Session &session, bool draining) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(kMaxWaitMs);
    for (;;) {
        Output output = make_output();
        as_output_v0 destination = sdk_output(output);
        const as_status_v0 status = draining
            ? as_session_drain_next_v0(session.session, &destination, &output.result)
            : as_session_pull_v0(session.session, &destination, &output.result);
        if (status == AS_OK) {
            check_status(output.result.status, AS_OK, draining ? "drain result" : "pull result");
            return output;
        }
        if (status != AS_NOT_READY) check_status(status, AS_OK, draining ? "drain" : "pull");
        if (std::chrono::steady_clock::now() >= deadline)
            fail(std::string(draining ? "drain" : "pull") + " exceeded absolute test deadline");
        std::this_thread::sleep_for(std::chrono::microseconds(100));
    }
}

std::pair<as_status_v0, Output> next_drain(Session &session) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(kMaxWaitMs);
    for (;;) {
        Output output = make_output();
        as_output_v0 destination = sdk_output(output);
        const as_status_v0 status =
            as_session_drain_next_v0(session.session, &destination, &output.result);
        if (status == AS_OK || status == AS_END_OF_STREAM)
            return {status, std::move(output)};
        if (status != AS_NOT_READY) check_status(status, AS_OK, "drain");
        if (std::chrono::steady_clock::now() >= deadline)
            fail("drain exceeded absolute test deadline");
        std::this_thread::sleep_for(std::chrono::microseconds(100));
    }
}

void assert_frame(const Output &output, int64_t source_first, uint32_t produced,
                  int64_t content_start, int64_t content_end, bool final_phase,
                  uint64_t epoch, const std::vector<float> &input, const std::string &case_label,
                  uint32_t frame_number) {
    const auto &r = output.result;
    const std::string label = case_label + " frame " + std::to_string(frame_number);
    if (r.epoch != epoch)
        fail(label + ": result epoch=" + std::to_string(r.epoch) +
             ", expected " + std::to_string(epoch));
    if (r.source_first_sample != source_first)
        fail(label + ": source_first_sample=" + std::to_string(r.source_first_sample) +
             ", expected " + std::to_string(source_first));
    if (r.produced_count != produced)
        fail(label + ": produced_count=" + std::to_string(r.produced_count) +
             ", expected " + std::to_string(produced));

    const int64_t source_end = source_first + produced;
    const int64_t valid_begin = std::max(source_first, content_start);
    const int64_t valid_end = std::max(valid_begin, std::min(source_end, content_end));
    const uint32_t expected_offset = static_cast<uint32_t>(
        std::clamp<int64_t>(valid_begin - source_first, 0, produced));
    const uint32_t expected_count = static_cast<uint32_t>(valid_end - valid_begin);
    if (r.valid_offset != expected_offset || r.valid_count != expected_count)
        fail(label + ": validity=(" + std::to_string(r.valid_offset) + "," +
             std::to_string(r.valid_count) + "), expected=(" +
             std::to_string(expected_offset) + "," + std::to_string(expected_count) + ")");

    uint32_t expected_flags = source_first < content_start ? AS_RESULT_STARTUP_PADDING : 0u;
    if (final_phase && source_end > content_end) expected_flags |= AS_RESULT_FINAL_PADDING;
    if (r.flags != expected_flags)
        fail(label + ": flags=" + std::to_string(r.flags) +
             ", expected " + std::to_string(expected_flags));

    for (uint32_t i = 0; i < produced; ++i) {
        const int64_t source = source_first + i;
        const float expected = source >= content_start && source < content_end
            ? input.at(static_cast<size_t>(source - content_start))
            : 0.0f;
        if (output.samples[i] != expected)
            fail(label + ": output sample differs at produced offset " + std::to_string(i));
    }
}

void run_case(Session &session, uint32_t length, uint64_t epoch,
              const std::string &descriptor) {
    const int64_t origin = kOrigin + static_cast<int64_t>(epoch * 1000);
    session.create(descriptor, epoch, origin);
    std::vector<float> input(length);
    for (uint32_t i = 0; i < length; ++i)
        input[i] = static_cast<float>((i % 97) + 1) / 128.0f;

    const std::string label = "mode " + std::to_string(session.mode) +
                              " length " + std::to_string(length) +
                              " origin " + std::to_string(origin);
    uint32_t frame_number = 0;
    for (uint32_t offset = 0; offset < length; offset += kFrame) {
        const uint32_t valid = std::min(kFrame, length - offset);
        std::array<float, kFrame> samples{};
        std::copy_n(input.begin() + offset, valid, samples.begin());
        as_frame_v0 frame;
        as_frame_v0_init(&frame);
        frame.input = samples.data();
        frame.input_count = kFrame;
        frame.input_valid_count = valid;
        frame.flags = valid < kFrame ? AS_FRAME_FINAL_INPUT : 0u;
        frame.epoch = epoch;
        frame.first_input_sample = origin + offset;

        Output output = make_output();
        if (session.mode == AS_MODE_PROCESSING_THREAD) {
            as_output_v0 destination = sdk_output(output);
            const as_status_v0 status =
                as_session_process_v0(session.session, &frame, &destination, &output.result);
            if (status != AS_OK) {
                fail(label + ": process returned " + as_status_name_v0(status) +
                     " at input offset " + std::to_string(offset) +
                     ", valid=" + std::to_string(valid) +
                     ", result epoch=" + std::to_string(output.result.epoch));
            }
            check_status(output.result.status, AS_OK, "process result");
        } else {
            as_result_v0 accepted;
            as_result_v0_init(&accepted);
            check_status(as_session_submit_v0(session.session, &frame, &accepted), AS_OK, "submit");
            check_status(accepted.status, AS_OK, "submit result");
            if (accepted.consumed_count != kFrame || accepted.produced_count != 0 ||
                accepted.valid_count != 0)
                fail(label + ": submit acceptance counts are invalid");
            output = next_buffered(session, false);
        }

        const int64_t source_first = origin + static_cast<int64_t>(offset) - kDelay;
        assert_frame(output, source_first, kFrame, origin, origin + length,
                     valid < kFrame, epoch, input, label, frame_number++);
    }

    check_status(as_session_begin_drain_v0(session.session), AS_OK, "begin drain");
    int64_t next_source = length == 0
        ? origin - static_cast<int64_t>(kDelay)
        : origin + static_cast<int64_t>((((length - 1) / kFrame) * kFrame)) -
              static_cast<int64_t>(kDelay) + kFrame;
    bool drained = false;
    for (uint32_t n = 0; n < 16; ++n) {
        Output output = make_output();
        as_status_v0 status;
        if (session.mode == AS_MODE_BUFFERED_WORKER) {
            auto next = next_drain(session);
            status = next.first;
            output = std::move(next.second);
        } else {
            as_output_v0 destination = sdk_output(output);
            status = as_session_drain_next_v0(session.session, &destination, &output.result);
        }
        if (status == AS_END_OF_STREAM) {
            check_status(output.result.status, AS_END_OF_STREAM, "EOS result");
            if (output.result.produced_count || output.result.valid_count)
                fail(label + ": EOS returned audio counts");
            drained = true;
            break;
        }
        check_status(status, AS_OK, "drain");
        check_status(output.result.status, AS_OK, "drain result");
        if (output.result.produced_count == 0)
            fail(label + ": successful drain produced no samples");
        assert_frame(output, next_source, output.result.produced_count, origin, origin + length,
                     true, epoch, input, label, frame_number++);
        next_source += output.result.produced_count;
    }
    if (!drained) fail(label + ": drain did not reach EOS within 16 calls");

    // Independently check that the observed valid source intervals cover the entire case once.
    // assert_frame checked each interval; derive expected tail through provider cursor.
    if (length && next_source < origin + length)
        fail(label + ": drain stopped before the accepted source end");
}

} // namespace

int main(int argc, char **argv) {
    try {
        if (argc != 3) fail("usage: d256_regression descriptor.json config-schema.json");
        const std::string descriptor = read_file(argv[1]);
        const std::string config_schema = read_file(argv[2]);
        char schema_digest[65]{};
        if (as_sha256_hex_v0(config_schema.data(), config_schema.size(),
                            schema_digest, sizeof(schema_digest)) != AS_OK)
            fail("could not hash loaded provider config schema");
        const std::string expected_schema_digest =
            std::string("\"configuration_schema_digest\":\"sha256:") + schema_digest + "\"";
        if (descriptor.find(expected_schema_digest) == std::string::npos)
            fail("loaded config schema digest does not match the fixture descriptor");

        for (uint32_t mode : {AS_MODE_PROCESSING_THREAD, AS_MODE_BUFFERED_WORKER}) {
            Session session;
            session.mode = mode;
            uint64_t epoch = 1;
            run_case(session, 0, epoch++, descriptor);
            for (uint32_t remainder = 1; remainder < kFrame; ++remainder) {
                run_case(session, remainder, epoch++, descriptor);
                run_case(session, kFrame + remainder, epoch++, descriptor);
            }
            for (uint32_t exact : {kFrame, 2 * kFrame, 3 * kFrame}) {
                run_case(session, exact, epoch++, descriptor);
            }
        }
        std::cout << "D=256 source maps, validity, flags and drains passed for both SDK modes "
                     "and every final remainder 1..159\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "D=256 regression failed: " << error.what() << '\n';
        return 1;
    }
}
