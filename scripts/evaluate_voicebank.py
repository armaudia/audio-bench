#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Run and score the pinned VoiceBank+DEMAND paired test cohort.

Audio is read only from the external verified corpus cache and temporary runner storage. The
returned/public record contains aggregates and provenance hashes, never waveform data.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "src"))

from audio_bench import audio, canonical, metrics  # noqa: E402
from audio_bench.errors import ValidationError  # noqa: E402

DATASET_ID = "voicebank-demand-test-v1"
SUITE_ID = "voicebank-demand-paired-v1"
METRIC_IDS = ("si_sdr_db", "si_sdr_improvement_db", "stoi", "estoi")
PROTOCOL = json.loads((ROOT / "suites/voicebank-demand-paired-v1/protocol.json").read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _load_resampled(path: Path) -> np.ndarray:
    samples, rate = sf.read(path, dtype="float32", always_2d=True)
    if rate != 48000 or samples.shape[1] != 1 or not np.isfinite(samples).all():
        raise ValidationError(f"unexpected VoiceBank audio format: {path.name}")
    result = resample_poly(samples[:, 0].astype(np.float64), 1, 3,
                           window=("kaiser", 5.0), padtype="constant")
    result = np.asarray(result, dtype=np.float32)
    if not np.isfinite(result).all() or not len(result):
        raise ValidationError(f"invalid resampled audio: {path.name}")
    return result


def _reconstruct(raw_path: Path, map_path: Path, count: int) -> np.ndarray:
    raw = np.fromfile(raw_path, dtype="<f4")
    output = np.zeros(count, dtype=np.float32)
    cursor = 0
    for line in map_path.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        start, end = int(item["source_start"]), int(item["source_end"])
        offset = int(item["output_offset_samples"]) + int(item["valid_offset"])
        valid = int(item["valid_count"])
        if start != cursor or end - start != valid or offset + valid > len(raw):
            raise ValidationError("collector output map has a gap, overlap, or out-of-range sample")
        output[start:end] = raw[offset:offset + valid]
        cursor = end
    if cursor != count or not np.isfinite(output).all():
        raise ValidationError("candidate output does not cover the full VoiceBank utterance")
    return output


def _bootstrap(values: list[float], speakers: list[str], seed: int) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    groups = [np.asarray([v for v, s in zip(values, speakers, strict=True) if s == speaker], dtype=np.float64)
              for speaker in sorted(set(speakers))]
    samples = np.empty(int(PROTOCOL["bootstrap_draws"]), dtype=np.float64)
    for draw in range(len(samples)):
        resampled = np.concatenate([group[rng.integers(0, len(group), len(group))] for group in groups])
        samples[draw] = np.median(resampled)
    return float(np.quantile(samples, 0.025)), float(np.quantile(samples, 0.975))


def run_voicebank_candidate(*, native_build: Path, sdk_prefix: Path, cache_root: Path,
                            provider_id: str, plugin_path: Path | None = None,
                            descriptor_path: Path | None = None, assets: dict[str, Path] | None = None,
                            work: Path) -> dict[str, Any]:
    """Execute one provider across the full pinned cohort and return result-only data."""
    if (plugin_path is None) != (descriptor_path is None):
        raise ValidationError("candidate plugins require both a library and descriptor")
    if work.exists():
        raise ValidationError("VoiceBank work directory must be new")
    dataset = ROOT / "manifests/voicebank-demand/voicebank-demand-test-v1"
    provenance_path = dataset / "provenance.json"
    case_manifest = dataset / "cases-0000.jsonl"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    rights = json.loads((ROOT / "manifests/voicebank.status.json").read_text(encoding="utf-8"))
    if rights.get("status") != "allowed" or rights.get("rights", {}).get("evaluation") != "allowed":
        raise ValidationError("VoiceBank evaluation is disabled by the repository rights gate")
    cases = canonical.parse_jsonl(case_manifest.read_bytes())
    corpus_root = cache_root / DATASET_ID
    clean_root = corpus_root / "clean_testset_wav/clean_testset_wav"
    noisy_root = corpus_root / "noisy_testset_wav/noisy_testset_wav"
    if len(cases) != 824:
        raise ValidationError("VoiceBank+DEMAND case inventory must have exactly 824 cases")
    if provenance.get("case_manifest_sha256") != sha256_file(case_manifest):
        raise ValidationError("VoiceBank case manifest does not match its pinned digest")
    if not clean_root.is_dir() or not noisy_root.is_dir():
        raise ValidationError(f"verified VoiceBank cache is missing at {corpus_root}")
    notice_path = corpus_root / "RIGHTS_NOTICE.json"
    if not notice_path.is_file() or json.loads(notice_path.read_text(encoding="utf-8")).get("dataset_id") != DATASET_ID:
        raise ValidationError("VoiceBank cache lacks a matching attribution/rights notice")

    driver = native_build / "audio_bench_driver"
    collector = native_build / "audio_bench_collect"
    if not driver.is_file() or not collector.is_file():
        raise ValidationError("native collector/driver binaries are missing")
    metadata_command = [str(driver), "--provider", provider_id]
    if plugin_path:
        metadata_command += ["--plugin", str(plugin_path)]
    config_bytes = subprocess.run([*metadata_command, "--effective-config"], check=True,
                                   capture_output=True, timeout=15).stdout
    if not config_bytes.endswith(b"\n") or config_bytes.endswith(b"\n\n"):
        raise ValidationError("provider returned malformed effective config")
    config_digest = "sha256:" + hashlib.sha256(config_bytes[:-1]).hexdigest()
    assets = assets or {}
    required_assets = []
    if descriptor_path is not None:
        descriptor = canonical.require_canonical(descriptor_path.read_bytes(), path=str(descriptor_path))
        if descriptor.get("provider_id") != provider_id:
            raise ValidationError("provider descriptor identity differs from provider id")
        required_assets = descriptor.get("required_assets", [])
    if {item.get("id") for item in required_assets} != set(assets):
        raise ValidationError("candidate asset paths must exactly match descriptor required_assets")
    for item in required_assets:
        path = Path(assets[item["id"]]).resolve(strict=True)
        if (path.is_symlink() or not path.is_file() or path.stat().st_size != item["byte_count"]
                or sha256_file(path) != item["sha256"]):
            raise ValidationError(f"candidate asset does not match its pinned identity: {item['id']}")
        assets[item["id"]] = path
    work.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="audio-bench-voicebank-") as temp:
        temp_root = Path(temp)
        inputs = temp_root / "inputs"
        inputs.mkdir()
        aligned: dict[str, tuple[np.ndarray, np.ndarray, dict[str, Any]]] = {}
        for case in cases:
            case_id = case["case_id"]
            clean_path = clean_root / Path(case["clean"]["archive_member"]).name
            noisy_path = noisy_root / Path(case["noisy"]["archive_member"]).name
            for role, path, spec in (("clean", clean_path, case["clean"]),
                                     ("noisy", noisy_path, case["noisy"])):
                if not path.is_file() or path.stat().st_size != spec["bytes"] or sha256_file(path) != spec["sha256"]:
                    raise ValidationError(f"cached corpus file failed its pinned hash: {case_id} {role}")
            clean, noisy = _load_resampled(clean_path), _load_resampled(noisy_path)
            if clean.shape != noisy.shape:
                raise ValidationError(f"resampled clean/noisy alignment mismatch: {case_id}")
            source = inputs / f"{case_id}.f32"
            source.write_bytes(np.ascontiguousarray(noisy, dtype="<f4").tobytes())
            aligned[case_id] = (clean, noisy, case)

        output = temp_root / "outputs"
        command = [str(collector), "--driver", str(driver), "--provider", provider_id,
                   "--timeout-seconds", "3600", "--output-dir", str(output)]
        if plugin_path:
            config_file = temp_root / "effective-config.json"
            descriptor_copy = temp_root / "provider.descriptor.json"
            config_file.write_bytes(config_bytes)
            descriptor_copy.write_bytes(descriptor_path.read_bytes())
            command += ["--plugin", str(plugin_path), "--config-file", str(config_file),
                        "--descriptor-file", str(descriptor_copy)]
        for asset_id, path in sorted(assets.items()):
            command += ["--asset", f"{asset_id}={Path(path).resolve(strict=True)}"]
        command += [arg for case in cases for arg in ("--input", str(inputs / f"{case['case_id']}.f32"))]
        run = subprocess.run(command, check=True, capture_output=True, text=True, timeout=3600)
        collector_summary = json.loads((output / "collector-summary.json").read_text(encoding="utf-8"))
        if len(collector_summary.get("cases", [])) != len(cases) or any(
                item.get("coverage") != "complete" for item in collector_summary["cases"]):
            raise ValidationError("collector did not provide complete output for all 824 cases")
        values: dict[str, list[float]] = {metric_id: [] for metric_id in METRIC_IDS}
        speakers: list[str] = []
        for case in cases:
            case_id = case["case_id"]
            clean, noisy, metadata = aligned[case_id]
            base = output / f"{case_id}.f32"
            estimated = _reconstruct(base.with_suffix(".raw.f32"), base.with_suffix(".intervals.jsonl"), len(noisy))
            for metric_id in METRIC_IDS:
                value, reason = metrics.metric_value(metric_id, reference=clean, estimate=estimated,
                                                     raw=noisy if metric_id == "si_sdr_improvement_db" else None)
                if value is None or reason:
                    raise ValidationError(f"metric {metric_id} is undefined for {case_id}: {reason}")
                values[metric_id].append(float(value))
            speakers.append(metadata["speaker_id"])

        metric_rows = []
        for metric_id in METRIC_IDS:
            data = values[metric_id]
            low, high = _bootstrap(data, speakers, PROTOCOL["seed"] + len(metric_rows))
            median = float(np.median(data))
            metric_rows.append({
                "metric_id": metric_id,
                "label": {"si_sdr_improvement_db": "SI-SDR improvement (primary)",
                          "si_sdr_db": "SI-SDR", "stoi": "STOI", "estoi": "ESTOI"}[metric_id],
                "unit": "dB" if metric_id.endswith("_db") else "index",
                "median": median,
                "mean": float(np.mean(data)),
                "median_interval_95": [low, high],
                "finite_count": len(data),
                "display_value": f"{median:.4g} {'dB' if metric_id.endswith('_db') else 'index'}",
                "raw_display_value": f"{median:.4g} {'dB' if metric_id.endswith('_db') else 'index'}",
                "normalized_display_value": None,
            })
        frame_count = sum((len(aligned[case["case_id"]][1]) + 159) // 160 for case in cases)
        cpu_ns = int(collector_summary["direct_child_cpu_ns"])
        latency_ms = cpu_ns / frame_count / 1_000_000
        metric_rows.append({"metric_id": "latency_ms", "label": "CPU time per 10 ms frame",
                            "unit": "ms", "median": latency_ms, "mean": latency_ms,
                            "finite_count": frame_count, "display_value": f"{latency_ms:.4g} ms",
                            "raw_display_value": f"{latency_ms:.4g} ms",
                            "normalized_display_value": None})
        accepted_samples = sum(int(item["accepted_samples"]) for item in collector_summary["cases"])
        wall_ns = int(collector_summary["wall_ns"])
        audio_seconds = accepted_samples / 16000
        for metric_id, label, value, unit in (
            ("cpu_occupancy_cores", "CPU use", cpu_ns / wall_ns, "cores"),
            ("cpu_seconds_per_audio_second", "CPU seconds per audio second", cpu_ns / 1e9 / audio_seconds, "s/s"),
            ("throughput_audio_seconds_per_wall_second", "Audio seconds processed per wall second", audio_seconds / (wall_ns / 1e9), "x real time"),
            ("peak_worker_rss_bytes", "Worker peak memory", int(collector_summary["direct_child_max_rss_bytes"]), "bytes"),
        ):
            metric_rows.append({"metric_id": metric_id, "label": label, "unit": unit,
                                "median": value, "mean": value, "finite_count": 1,
                                "display_value": f"{value:.4g} {unit}",
                                "raw_display_value": f"{value:.4g} {unit}",
                                "normalized_display_value": None})
        sdk_archive = sdk_prefix.parent / "audio-sdk-0.1.0.tar.gz"
        if not sdk_archive.is_file():
            raise ValidationError("pinned SDK package archive is missing")
        result_id = f"voicebank:{provider_id}:{uuid.uuid4()}"
        dataset_digest = canonical.digest_of(provenance)
        protocol_digest = canonical.digest_of(PROTOCOL)
        harness_digest = canonical.digest_of({
            "protocol_digest": protocol_digest,
            "runner_script_sha256": sha256_file(Path(__file__).resolve()),
            "metric_implementation_sha256": sha256_file(ROOT / "src/audio_bench/metrics.py"),
            "collector_sha256": sha256_file(collector),
            "driver_sha256": sha256_file(driver),
        })
        return {
            "schema_id": "audio-bench/voicebank-result/0.1",
            "result_id": result_id,
            "dataset_id": dataset_digest,
            "dataset_label": "VoiceBank+DEMAND official test split (824 paired utterances)",
            "suite_id": SUITE_ID,
            "provider_id": provider_id,
            "configuration_id": config_digest,
            "sdk_package_digest": sha256_file(sdk_archive),
            "dataset_manifest_digest": dataset_digest,
            "case_manifest_digest": sha256_file(case_manifest),
            "protocol_digest": protocol_digest,
            "harness_digest": harness_digest,
            "case_count": len(cases),
            "speaker_count": len(set(speakers)),
            "metrics": metric_rows,
            "execution": {"status": "complete", "collector": collector_summary,
                          "stdout": run.stdout.strip()},
        }

