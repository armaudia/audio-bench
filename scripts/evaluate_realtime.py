#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Measure paced multi-stream capacity for the real-time processing category."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from audio_bench import audio, canonical
from audio_bench.errors import ValidationError

PROFILE_PATH = ROOT / "suites/realtime-throughput-v1/profile.json"


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _p99(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.99 * len(ordered)) - 1)]


def run_realtime_candidate(*, native_build: Path, sdk_prefix: Path, provider_id: str,
                           work: Path, plugin_path: Path | None = None,
                           descriptor_path: Path | None = None,
                           assets: dict[str, Path] | None = None) -> dict:
    """Run repeated paced synthetic streams and report the largest passing tested level."""
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    dataset_path = ROOT / "manifests/synthetic/synthetic-16k-v1/dataset.json"
    dataset = canonical.require_canonical(dataset_path.read_bytes())
    manifest = ROOT / "manifests/synthetic/synthetic-16k-v1/cases-0000.jsonl"
    cases = canonical.parse_jsonl(manifest.read_bytes())
    source = ROOT / "manifests/synthetic/synthetic-16k-v1/audio" / f"{cases[0]['case_id']}.noisy.wav"
    samples = audio.read_wav(source)
    if samples.ndim != 1 or samples.size < 160:
        raise ValidationError("real-time profile requires nonempty mono 16 kHz fixtures")
    if work.exists():
        raise ValidationError("real-time benchmark work directory must be new", path=str(work))
    work.mkdir(parents=True)
    input_dir = work / "inputs"
    input_dir.mkdir()
    input_paths = []
    raw = samples.astype("<f4", copy=False).tobytes()
    for repeat in range(profile["input_repetitions_per_stream"]):
        path = input_dir / f"stream-case-{repeat:02d}.f32"
        path.write_bytes(raw)
        input_paths.append(path)

    driver = native_build / "audio_bench_driver"
    collector = native_build / "audio_bench_collect"
    if not driver.is_file() or not collector.is_file():
        raise ValidationError("native driver/collector are not built")
    metadata_command = [str(driver), "--provider", provider_id]
    if plugin_path is not None:
        if descriptor_path is None:
            raise ValidationError("candidate descriptor is required with a provider plugin")
        plugin_path = plugin_path.resolve(strict=True)
        descriptor_path = descriptor_path.resolve(strict=True)
        metadata_command += ["--plugin", str(plugin_path)]
    config = subprocess.run([*metadata_command, "--effective-config"], check=True,
                            capture_output=True, text=True, timeout=10).stdout
    if not config.endswith("\n") or config.endswith("\n\n") or "\r" in config:
        raise ValidationError("native driver returned malformed effective config")
    config_path = work / "effective-config.json"
    config_path.write_text(config, encoding="utf-8")
    base = [str(collector), "--driver", str(driver), "--provider", provider_id,
            "--paced", "--warmup-ms", str(profile["warmup_ms"])]
    if plugin_path is not None:
        base += ["--plugin", str(plugin_path), "--descriptor-file", str(descriptor_path),
                 "--config-file", str(config_path)]
    for asset_id, path in sorted((assets or {}).items()):
        base += ["--asset", f"{asset_id}={Path(path).resolve(strict=True)}"]

    capacity = 0
    passing_stats = None
    attempted = []
    budget_ns = int(profile["completion_lateness_budget_ms"] * 1_000_000)
    for stream_count in profile["stream_levels"]:
        level_dir = work / f"streams-{stream_count:02d}"
        level_dir.mkdir()
        processes = []
        start = time.monotonic_ns()
        for stream in range(stream_count):
            output = level_dir / f"stream-{stream:02d}"
            command = [*base, "--output-dir", str(output)]
            for item, path in enumerate(input_paths):
                unique = level_dir / f"stream-{stream:02d}-case-{item:02d}.f32"
                unique.write_bytes(path.read_bytes())
                command += ["--input", str(unique)]
            processes.append(subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        outputs = []
        try:
            for process in processes:
                outputs.append(process.communicate(timeout=180))
        except subprocess.TimeoutExpired as exc:
            for process in processes:
                process.kill()
            for process in processes:
                process.communicate()
            raise ValidationError(f"real-time load level {stream_count} exceeded 180 seconds") from exc
        wall_ns = time.monotonic_ns() - start
        if any(process.returncode != 0 for process in processes):
            raise ValidationError(f"real-time load failed at {stream_count} streams: " +
                                  "; ".join(stderr.strip()[-1000:] for _, stderr in outputs if stderr.strip()))
        summaries = []
        per_stream_p99 = []
        for stream in range(stream_count):
            output = level_dir / f"stream-{stream:02d}"
            summary = json.loads((output / "collector-summary.json").read_text(encoding="utf-8"))
            if summary.get("mode") != "paced" or any(row.get("coverage") != "complete" for row in summary.get("cases", [])):
                raise ValidationError(f"incomplete paced output at stream level {stream_count}")
            delays = []
            for path in sorted(output.glob("*.pacing.jsonl")):
                for line in path.read_text(encoding="utf-8").splitlines():
                    delays.append(int(json.loads(line)["completion_lateness_ns"]))
            if not delays:
                raise ValidationError(f"no frame timing evidence at stream level {stream_count}")
            per_stream_p99.append(_p99(delays))
            summaries.append(summary)
        passed = max(per_stream_p99) <= budget_ns
        attempted.append({"streams": stream_count, "passed": passed,
                          "worst_stream_p99_completion_lateness_ns": max(per_stream_p99)})
        if not passed:
            break
        capacity = stream_count
        passing_stats = (summaries, max(per_stream_p99), wall_ns, stream_count)

    if not capacity or passing_stats is None:
        raise ValidationError("candidate did not meet the real-time completion budget at one stream")
    summaries, worst_p99_ns, wall_ns, stream_count = passing_stats
    frames_per_stream = sum((len(samples) + 159) // 160 for _ in input_paths)
    cpu_ns = sum(int(item["direct_child_cpu_ns"]) for item in summaries)
    accepted_samples = sum(int(case["accepted_samples"]) for item in summaries for case in item["cases"])
    rss_bytes = sum(int(item["direct_child_max_rss_bytes"]) for item in summaries)
    audio_seconds = accepted_samples / 16000
    latency_ms = cpu_ns / (frames_per_stream * stream_count) / 1_000_000
    metrics = [
        ("latency_ms", "CPU time per 10 ms frame at capacity", latency_ms, "ms"),
        ("max_tested_streams_at_latency_target", f"Streams meeting {profile['completion_lateness_budget_ms']} ms p99 budget", capacity, "count"),
        ("p99_completion_lateness_ms", "Worst-stream p99 completion lateness", worst_p99_ns / 1_000_000, "ms"),
        ("cpu_occupancy_cores", "CPU use at capacity", cpu_ns / wall_ns, "cores"),
        ("throughput_audio_seconds_per_wall_second", "Aggregate throughput at capacity", audio_seconds / (wall_ns / 1e9), "x real time"),
        ("sum_worker_peak_rss_bytes", "Sum of worker peak memory", rss_bytes, "bytes"),
    ]
    metric_rows = [{"metric_id": metric_id, "label": label, "unit": unit, "median": float(value),
                    "mean": float(value), "finite_count": 1,
                    "display_value": f"{value:.4g} {unit}", "raw_display_value": f"{value:.4g} {unit}",
                    "normalized_display_value": None}
                   for metric_id, label, value, unit in metrics]
    profile_digest = _sha(PROFILE_PATH)
    harness_digest = canonical.digest_of({"profile_digest": profile_digest,
                                          "runner_script_digest": _sha(Path(__file__).resolve())})
    bundle_manifest_digest = canonical.digest_of({"profile_digest": profile_digest,
                                                   "dataset_digest": dataset["dataset_id"],
                                                   "provider_id": provider_id,
                                                   "configuration_id": summaries[0]["sdk_config_digest"],
                                                   "sdk_package_digest": summaries[0]["sdk_package_digest"]})
    return {
        "result_id": f"realtime:{provider_id}:{uuid.uuid4()}",
        "provider_id": provider_id,
        "suite_id": profile["suite_id"], "dataset_id": dataset["dataset_id"],
        "dataset_label": "Synthetic real-time load fixture (not speech-quality scoring)",
        "case_count": len(input_paths), "metrics": metric_rows,
        "harness_digest": harness_digest,
        "evidence": {"configuration_id": summaries[0]["sdk_config_digest"],
                     "sdk_package_digest": summaries[0]["sdk_package_digest"],
                     "harness_digest": harness_digest, "bundle_manifest_digest": bundle_manifest_digest,
                     "dataset_manifest_digest": _sha(dataset_path), "profile_digest": profile_digest,
                     "runner_fingerprint": f"{platform.platform()} / Python {platform.python_version()}",
                     "tested_stream_levels": attempted,
                     "latency_budget_ms": profile["completion_lateness_budget_ms"],
                     "latency_semantics": "worst per-stream p99 completion lateness beyond the 10 ms frame schedule",
                     "memory_semantics": profile["memory_semantics"]},
    }
