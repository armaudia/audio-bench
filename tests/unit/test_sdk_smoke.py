# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
import os
import json
import subprocess
from pathlib import Path

import pytest

from audio_bench.bundle import validate_bundle
from audio_bench import __main__ as cli
from audio_bench.report import build_report
from audio_bench.smoke import run_sdk_smoke
from audio_bench.errors import ValidationError


ROOT = Path(__file__).resolve().parents[2]
_SDK_LOCK = json.loads((ROOT / "deps/lock.json").read_text())
_SDK_ARCHIVE = next(item["artifact"] for item in _SDK_LOCK["dependencies"]
                    if item["id"] == "audio-sdk-installed-package")
SDK_PREFIX = Path(os.environ.get(
    "AUDIO_SDK_PREFIX", str((ROOT / _SDK_ARCHIVE).resolve().parent / "audio-sdk-0.1.0")
))
NATIVE_BUILD = Path(os.environ.get("AUDIO_BENCH_NATIVE_BUILD", ROOT / "build/ci/native"))


@pytest.mark.parametrize("dependencies", [{}, {"numpy": "0.0.0"}])
def test_frozen_metric_environment_rejects_missing_or_different_versions(tmp_path, dependencies):
    from audio_bench.smoke import _verify_python_environment

    (tmp_path / "toolchain-lock.json").write_text(json.dumps({"python_dependencies": dependencies}))
    with pytest.raises(ValidationError, match="frozen metric environment"):
        _verify_python_environment(tmp_path)


@pytest.mark.sdk
@pytest.mark.skipif(not (NATIVE_BUILD / "audio_bench_asset_test_provider.so").is_file(),
                    reason="native asset provider fixture is not built")
def test_native_collector_passes_pinned_model_assets_to_provider_create(tmp_path):
    import numpy as np

    driver = NATIVE_BUILD / "audio_bench_driver"
    collector = NATIVE_BUILD / "audio_bench_collect"
    plugin = NATIVE_BUILD / "audio_bench_asset_test_provider.so"
    asset = tmp_path / "weights.bin"
    asset.write_bytes(b"audio-bench-asset-test-v1")
    input_file = tmp_path / "input.f32"
    np.zeros(1600, dtype="<f4").tofile(input_file)
    config = tmp_path / "effective-config.json"
    descriptor = tmp_path / "provider.descriptor.json"
    generated = subprocess.run([str(driver), "--provider", "bench.test.asset.v0",
                                "--plugin", str(plugin), "--effective-config"],
                               check=True, capture_output=True).stdout
    descriptor_bytes = subprocess.run([str(driver), "--provider", "bench.test.asset.v0",
                                       "--plugin", str(plugin), "--descriptor"],
                                      check=True, capture_output=True).stdout
    config.write_bytes(generated)
    descriptor.write_bytes(descriptor_bytes[:-1])
    output = tmp_path / "valid-output"
    subprocess.run([str(collector), "--driver", str(driver), "--provider", "bench.test.asset.v0",
                    "--plugin", str(plugin), "--config-file", str(config),
                    "--descriptor-file", str(descriptor), "--asset", f"benchmark-test-asset={asset}",
                    "--output-dir", str(output), "--input", str(input_file)],
                   check=True, capture_output=True, text=True)
    summary = json.loads((output / "collector-summary.json").read_text())
    assert summary["cases"][0]["coverage"] == "complete"

    corrupt = tmp_path / "corrupt.bin"
    corrupt.write_bytes(b"audio-bench-asset-test-X")
    bad_output = tmp_path / "invalid-output"
    failure = subprocess.run([str(collector), "--driver", str(driver), "--provider", "bench.test.asset.v0",
                              "--plugin", str(plugin), "--config-file", str(config),
                              "--descriptor-file", str(descriptor), "--asset", f"benchmark-test-asset={corrupt}",
                              "--output-dir", str(bad_output), "--input", str(input_file)],
                             capture_output=True, text=True)
    assert failure.returncode != 0


def test_installed_cli_requires_explicit_external_sdk_prefix(tmp_path, monkeypatch):
    fake_module = tmp_path / "venv/lib/python3.12/site-packages/audio_bench/__main__.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.write_text("")
    monkeypatch.setattr(cli, "__file__", str(fake_module))
    assert cli._locked_sdk_prefix() is None
    parsed = cli.parser().parse_args([
        "smoke", "--output", str(tmp_path / "bundle"),
    ])
    assert parsed.sdk_prefix is None


@pytest.mark.skipif(
    not (SDK_PREFIX / "bin/audio_sdk_conformance").is_file()
    or not (NATIVE_BUILD / "audio_bench_collect").is_file(),
    reason="verified installed SDK/native build is not available",
)
@pytest.mark.parametrize("field", ["sdk_package_digest", "sdk_build_id"])
def test_smoke_rejects_native_binaries_from_a_different_sdk(tmp_path, monkeypatch, field):
    import audio_bench.smoke as smoke

    original_run = smoke.subprocess.run

    def mismatch_identity(command, *args, **kwargs):
        result = original_run(command, *args, **kwargs)
        if "--output-dir" in command:
            summary_path = Path(command[command.index("--output-dir") + 1]) / "collector-summary.json"
            summary = json.loads(summary_path.read_text())
            summary[field] = "wrong-sdk-identity"
            summary_path.write_text(json.dumps(summary))
        return result

    monkeypatch.setattr(smoke.subprocess, "run", mismatch_identity)
    bundle = tmp_path / "rejected"
    with pytest.raises(ValidationError, match="native collector identity mismatch"):
        run_sdk_smoke(bundle, native_build=NATIVE_BUILD, sdk_prefix=SDK_PREFIX, repository=ROOT)
    assert (bundle / "failure-evidence.json").is_file()


@pytest.mark.sdk
@pytest.mark.skipif(
    not (SDK_PREFIX / "bin/audio_sdk_conformance").is_file()
    or not (NATIVE_BUILD / "audio_bench_collect").is_file(),
    reason="verified installed SDK/native build is not available",
)
def test_installed_sdk_smoke_seals_valid_bundle_and_report(tmp_path):
    bundle = tmp_path / "bundle"
    result = run_sdk_smoke(
        bundle,
        native_build=NATIVE_BUILD,
        sdk_prefix=SDK_PREFIX,
        repository=ROOT,
    )
    assert result["cases"] == 24
    assert result["metrics_per_case"] == 7
    checked = validate_bundle(bundle)
    assert checked.valid, checked.errors
    report = build_report(bundle, tmp_path / "report")
    assert report["rows"] == 1
    assert report["media_bytes"] == 0
    assert "not_assessed" in (tmp_path / "report/index.html").read_text()


@pytest.mark.sdk
@pytest.mark.skipif(
    not (SDK_PREFIX / "bin/audio_sdk_conformance").is_file()
    or not (NATIVE_BUILD / "audio_bench_collect").is_file(),
    reason="verified installed SDK/native build is not available",
)
def test_paced_collection_uses_absolute_schedule_and_matches_sequential(tmp_path):
    driver = NATIVE_BUILD / "audio_bench_driver"
    collector = NATIVE_BUILD / "audio_bench_collect"
    source = tmp_path / "input.f32"
    source.write_bytes(b"".join(
        __import__("struct").pack("<f", ((i % 31) - 15) / 32)
        for i in range(3 * 160)
    ))
    outputs = {}
    for mode, extra in (("sequential", []), ("paced", ["--paced", "--warmup-ms", "0"])):
        destination = tmp_path / mode
        subprocess.run(
            [str(collector), *extra, "--driver", str(driver), "--provider", "dsp.highpass80.v0",
             "--output-dir", str(destination), "--input", str(source)],
            check=True, capture_output=True, text=True, timeout=15,
        )
        outputs[mode] = destination
    assert (outputs["sequential"] / "input.raw.f32").read_bytes() == \
        (outputs["paced"] / "input.raw.f32").read_bytes()
    summary = json.loads((outputs["paced"] / "collector-summary.json").read_text())
    assert summary["mode"] == "paced"
    assert summary["cases"][0]["accepted_samples"] == "480"
    frames = [
        json.loads(line)
        for line in (outputs["paced"] / "input.pacing.jsonl").read_text().splitlines()
    ]
    assert len(frames) == 3
    assert [int(item["scheduled_submit_ns"]) for item in frames] == [
        int(frames[0]["scheduled_submit_ns"]) + i * 10_000_000 for i in range(3)
    ]
    assert all(int(item["submitted_ns"]) >= int(item["scheduled_submit_ns"])
               for item in frames)
    assert all(int(item["completed_ns"]) >= int(item["submitted_ns"]) for item in frames)
    assert all(1 <= int(item["in_flight_at_send"]) <= 3 for item in frames)
    assert all(int(item["send_backpressure_ns"]) >= 0 for item in frames)


@pytest.mark.sdk
@pytest.mark.skipif(
    not (SDK_PREFIX / "bin/audio_sdk_conformance").is_file()
    or not (NATIVE_BUILD / "audio_bench_collect").is_file(),
    reason="verified installed SDK/native build is not available",
)
def test_paced_warmup_keeps_state_and_measured_source_coverage(tmp_path):
    driver = NATIVE_BUILD / "audio_bench_driver"
    collector = NATIVE_BUILD / "audio_bench_collect"
    source = tmp_path / "warmup.f32"
    source.write_bytes(b"".join(
        __import__("struct").pack("<f", ((i % 17) - 8) / 16)
        for i in range(3 * 160)
    ))
    output = tmp_path / "warmup-output"
    subprocess.run(
        [str(collector), "--paced", "--warmup-ms", "20", "--driver", str(driver),
         "--provider", "dsp.highpass80.v0", "--output-dir", str(output),
         "--input", str(source)],
        check=True, capture_output=True, text=True, timeout=15,
    )
    summary = json.loads((output / "collector-summary.json").read_text())
    assert summary["warmup_ms"] == 20
    assert summary["cases"][0]["accepted_samples"] == "480"
    assert summary["cases"][0]["coverage"] == "complete"
    intervals = [
        json.loads(line)
        for line in (output / "warmup.intervals.jsonl").read_text().splitlines()
    ]
    valid = [item for item in intervals if item["valid_count"]]
    assert min(int(item["source_start"]) for item in valid) == 320
    assert max(int(item["source_end"]) for item in valid) == 800


@pytest.mark.sdk
def test_realtime_evaluator_runs_the_paced_collector(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import evaluate_realtime

    profile = json.loads(evaluate_realtime.PROFILE_PATH.read_text())
    # This exercises the full process and timing path without gating CI on host load.
    profile.update(stream_levels=[1], input_repetitions_per_stream=1, completion_lateness_budget_ms=1000)
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile))
    monkeypatch.setattr(evaluate_realtime, "PROFILE_PATH", profile_path)
    work = tmp_path / "realtime"
    result = evaluate_realtime.run_realtime_candidate(
        native_build=NATIVE_BUILD, sdk_prefix=SDK_PREFIX,
        provider_id="dsp.highpass80.v0", work=work,
    )
    assert (work / "streams-01/stream-00/collector-summary.json").is_file()
    assert result["case_count"] == 1
    assert result["evidence"]["tested_stream_levels"][0]["passed"]


@pytest.mark.sdk
@pytest.mark.skipif(
    not (NATIVE_BUILD / "audio_bench_collect").is_file(),
    reason="verified native collector build is not available",
)
def test_collector_handles_child_exit_without_sigpipe_termination(tmp_path):
    collector = NATIVE_BUILD / "audio_bench_collect"
    child = tmp_path / "early-exit-driver"
    child.write_text("#!/bin/sh\nexit 0\n")
    child.chmod(0o755)
    source = tmp_path / "input.f32"
    source.write_bytes(b"\x00\x00\x00\x00")
    result = subprocess.run(
        [str(collector), "--driver", str(child), "--provider", "dsp.highpass80.v0",
         "--output-dir", str(tmp_path / "failed"), "--input", str(source)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode > 0
    assert "collector:" in result.stderr


@pytest.mark.sdk
@pytest.mark.skipif(
    not (SDK_PREFIX / "bin/audio_sdk_conformance").is_file()
    or not (NATIVE_BUILD / "audio_bench_collect").is_file(),
    reason="verified installed SDK/native build is not available",
)
def test_collector_timeout_preserves_frozen_request_and_attempt(tmp_path, monkeypatch):
    import audio_bench.smoke as smoke

    original_run = smoke.subprocess.run
    calls = 0

    def fail_collector(command, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:  # effective-config query before request freeze
            return original_run(command, *args, **kwargs)
        raise subprocess.TimeoutExpired(command, timeout=300)

    monkeypatch.setattr(smoke.subprocess, "run", fail_collector)
    bundle = tmp_path / "failed-bundle"
    with pytest.raises(subprocess.TimeoutExpired):
        run_sdk_smoke(bundle, native_build=NATIVE_BUILD, sdk_prefix=SDK_PREFIX, repository=ROOT)
    requests = list((bundle / "requests").glob("*.json"))
    attempts = list((bundle / "runs").glob("*/*/attempt-start.json"))
    assert len(requests) == 1
    assert len(attempts) == 1
    failure = json.loads((bundle / "failure-evidence.json").read_text())
    assert failure["reason_code"] == "backend_failure"


@pytest.mark.sdk
@pytest.mark.skipif(
    not (SDK_PREFIX / "bin/audio_sdk_conformance").is_file()
    or not (NATIVE_BUILD / "audio_bench_collect").is_file(),
    reason="verified installed SDK/native build is not available",
)
def test_next_recording_after_final_partial_frame_starts_clean_session(tmp_path):
    collector = NATIVE_BUILD / "audio_bench_collect"
    driver = NATIVE_BUILD / "audio_bench_driver"
    short = tmp_path / "short.f32"
    following = tmp_path / "following.f32"
    short.write_bytes(b"\x00\x00\x00\x3e" * 161)
    following.write_bytes(b"\x00\x00\x00\x3e" * 320)
    output = tmp_path / "reset-after-final"
    subprocess.run(
        [str(collector), "--driver", str(driver), "--provider", "dsp.highpass80.v0",
         "--output-dir", str(output), "--input", str(short), "--input", str(following)],
        check=True, capture_output=True, text=True, timeout=15,
    )
    summary = json.loads((output / "collector-summary.json").read_text())
    assert [case["accepted_samples"] for case in summary["cases"]] == ["161", "320"]
    assert all(case["coverage"] == "complete" for case in summary["cases"])


@pytest.mark.skipif(
    not any((NATIVE_BUILD / ("audio_bench_test_provider" + suffix)).is_file()
            for suffix in (".so", ".dylib")),
    reason="test provider plugin is not built",
)
def test_external_provider_plugin_runs_in_driver_child(tmp_path):
    driver = NATIVE_BUILD / "audio_bench_driver"
    collector = NATIVE_BUILD / "audio_bench_collect"
    plugin = next(p for p in (NATIVE_BUILD / "audio_bench_test_provider.so",
                              NATIVE_BUILD / "audio_bench_test_provider.dylib") if p.is_file())
    provider = "bench.test.pass.v0"
    config = subprocess.run([str(driver), "--provider", provider, "--plugin", str(plugin),
                             "--effective-config"], check=True, capture_output=True, text=True).stdout
    descriptor = subprocess.run([str(driver), "--provider", provider, "--plugin", str(plugin),
                                 "--descriptor"], check=True, capture_output=True, text=True).stdout
    config_path, descriptor_path = tmp_path / "config.json", tmp_path / "descriptor.json"
    config_path.write_text(config)
    descriptor_path.write_text(descriptor[:-1])
    source = tmp_path / "input.f32"
    samples = [((i % 31) - 15) / 32 for i in range(480)]
    source.write_bytes(b"".join(__import__("struct").pack("<f", x) for x in samples))
    output = tmp_path / "plugin-output"
    subprocess.run(
        [str(collector), "--driver", str(driver), "--provider", provider,
         "--plugin", str(plugin), "--config-file", str(config_path),
         "--descriptor-file", str(descriptor_path), "--output-dir", str(output),
         "--input", str(source)],
        check=True, capture_output=True, text=True, timeout=15,
    )
    assert (output / "input.raw.f32").read_bytes() == source.read_bytes()
    summary = json.loads((output / "collector-summary.json").read_text())
    assert summary["provider_id"] == provider
    assert summary["cases"][0]["coverage"] == "complete"
