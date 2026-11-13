cmake_minimum_required(VERSION 3.20)
project(audio_bench_native VERSION 0.1.0 LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
find_package(Python3 3.12 COMPONENTS Interpreter REQUIRED)
if(NOT AUDIO_SDK_PREFIX)
  message(FATAL_ERROR "Set AUDIO_SDK_PREFIX to the verified installed SDK prefix")
endif()
execute_process(
  COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_LIST_DIR}/../scripts/verify_sdk_snapshot.py" --prefix "${AUDIO_SDK_PREFIX}"
  RESULT_VARIABLE SDK_VERIFY_RESULT
  OUTPUT_VARIABLE SDK_VERIFY_OUTPUT
  ERROR_VARIABLE SDK_VERIFY_ERROR
)
if(NOT SDK_VERIFY_RESULT EQUAL 0)
  message(FATAL_ERROR "Pinned SDK verification failed: ${SDK_VERIFY_OUTPUT}${SDK_VERIFY_ERROR}")
endif()
message(STATUS "${SDK_VERIFY_OUTPUT}")
find_package(AudioSDK 0.1 CONFIG REQUIRED)
if(NOT TARGET AudioSDK::audio_sdk)
  message(FATAL_ERROR "Installed package lacks exported AudioSDK::audio_sdk target")
endif()
add_executable(audio_bench_driver src/driver.cpp src/wire.cpp)
target_include_directories(audio_bench_driver PRIVATE src)
target_link_libraries(audio_bench_driver PRIVATE AudioSDK::audio_sdk)
add_executable(audio_bench_collect src/collect.cpp src/wire.cpp)
target_include_directories(audio_bench_collect PRIVATE src)
target_link_libraries(audio_bench_collect PRIVATE AudioSDK::audio_sdk)
add_executable(audio_bench_d256_regression tests/d256_regression.cpp tests/d256_provider.cpp)
target_include_directories(audio_bench_d256_regression PRIVATE tests)
target_link_libraries(audio_bench_d256_regression PRIVATE AudioSDK::audio_sdk)
foreach(target audio_bench_driver audio_bench_collect audio_bench_d256_regression)
  target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic -Werror)
endforeach()
enable_testing()
add_test(NAME sdk_snapshot_reverify COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_LIST_DIR}/../scripts/verify_sdk_snapshot.py" --prefix "${AUDIO_SDK_PREFIX}")
add_test(NAME sdk_d256_startup_validity_regression
  COMMAND audio_bench_d256_regression
    "${CMAKE_CURRENT_LIST_DIR}/../tests/fixtures/d256/descriptor.json"
    "${CMAKE_CURRENT_LIST_DIR}/../tests/fixtures/d256/config-schema.json")
