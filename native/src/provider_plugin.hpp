/* SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
 * SPDX-License-Identifier: Apache-2.0
 */
#pragma once

#include <audio_sdk/provider_v0.h>
#include <dlfcn.h>

#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>

namespace ab {

// Candidate code is loaded only by benchmark jobs with no publishing credentials.
class ProviderPlugin {
 public:
  explicit ProviderPlugin(const std::string& path) {
    handle_ = dlopen(path.c_str(), RTLD_NOW | RTLD_LOCAL);
    if (!handle_) {
      const char* error = dlerror();
      throw std::runtime_error(std::string("cannot load provider: ") + (error ? error : "unknown loader error"));
    }
    void* table_symbol = dlsym(handle_, "audio_bench_provider_table_v0");
    void* descriptor_symbol = dlsym(handle_, "audio_bench_provider_descriptor_v0");
    static_assert(sizeof(table_) == sizeof(table_symbol));
    static_assert(sizeof(descriptor_) == sizeof(descriptor_symbol));
    std::memcpy(&table_, &table_symbol, sizeof(table_));
    std::memcpy(&descriptor_, &descriptor_symbol, sizeof(descriptor_));
    if (!table_ || !descriptor_) {
      dlclose(handle_);
      handle_ = nullptr;
      throw std::runtime_error("candidate plugin lacks the audio-bench provider exports");
    }
  }
  ProviderPlugin(const ProviderPlugin&) = delete;
  ProviderPlugin& operator=(const ProviderPlugin&) = delete;
  ~ProviderPlugin() { if (handle_) dlclose(handle_); }

  void register_with(as_registry_v0* registry) const {
    uint32_t length = 0;
    const auto* table = table_();
    const char* descriptor = descriptor_(&length);
    if (!table || !descriptor || !length || length > AS_MAX_CONTROL_BYTES)
      throw std::runtime_error("candidate plugin returned invalid metadata");
    as_error_v0 error;
    as_error_v0_init(&error);
    const auto status = as_register_provider_v0(registry, table, descriptor, length, &error);
    if (status != AS_OK)
      throw std::runtime_error(std::string("candidate provider registration failed: ") + error.message);
  }

 private:
  using TableFn = const as_provider_table_v0* (AS_CALL*)();
  using DescriptorFn = const char* (AS_CALL*)(uint32_t*);
  void* handle_ = nullptr;
  TableFn table_ = nullptr;
  DescriptorFn descriptor_ = nullptr;
};

}  // namespace ab
