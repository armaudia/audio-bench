/* SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
 * SPDX-License-Identifier: Apache-2.0
 */
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace ab {
constexpr uint32_t kMagic = 0x41425530u;
constexpr uint16_t kVersion = 1;
constexpr size_t kHeaderBytes = 24;
constexpr size_t kMaxMessage = 65536;
constexpr size_t kMaxPayload = kMaxMessage - kHeaderBytes;
constexpr uint32_t kFrameSamples = 160;
constexpr uint32_t kPhaseProcess = 0;
constexpr uint32_t kPhaseDrain = 1;
enum class Type : uint16_t { Prepare=1, Ready=2, Input=3, Output=4, EndInput=5, Drained=6, Error=7, Reset=8, Close=9 };
struct Message { Type type; uint32_t stream; uint64_t sequence; std::vector<uint8_t> payload; };
struct Input { uint64_t epoch; int64_t first; uint32_t valid; uint32_t flags; std::array<float,160> samples; };
struct Output { uint64_t epoch; int64_t source_first; uint32_t produced; uint32_t valid_offset; uint32_t valid; uint32_t flags; uint32_t phase; int64_t service_begin; int64_t service_end; std::array<float,160> samples; };
struct End { uint64_t epoch; int64_t sample; };
std::vector<uint8_t> encode_message(const Message &message);
Message read_message(int fd, int timeout_ms=30000);
void write_message(int fd, const Message &message, int timeout_ms=30000);
Message prepare(uint32_t stream, uint64_t sequence, const std::array<uint8_t,32>& digest, const std::string& config);
Message ready(uint32_t stream, uint64_t sequence, const std::array<uint8_t,32>& build, const std::array<uint8_t,32>& descriptor);
Message input_message(uint32_t stream, uint64_t sequence, const Input& input);
Input decode_input(const Message& message);
Message output_message(uint32_t stream, uint64_t sequence, const Output& output);
Output decode_output(const Message& message);
Message end_message(Type type, uint32_t stream, uint64_t sequence, const End& end);
End decode_end(const Message& message);
Message error_message(uint32_t stream, uint64_t sequence, uint64_t epoch, int32_t status, const std::string& text);
std::array<uint8_t,32> digest_from_hex(const std::string& hex);
std::string hex_from_digest(const std::array<uint8_t,32>& bytes);
} // namespace ab
