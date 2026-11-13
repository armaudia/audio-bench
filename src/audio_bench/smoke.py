"""Run the pinned local SDK against the checked-in synthetic suite and seal a bundle."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from . import audio, canonical, ledger
from .errors import ValidationError
from .scoring import case_input_from_arrays, score_case
from .schemas import Validator


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _copy_manifest(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        if entry.name == "smoke-selection.json":
            continue
        target = destination / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target)
        elif entry.is_file():
            shutil.copyfile(entry, target)
        else:
            raise ValidationError(f"unexpected synthetic manifest entry: {entry}")


def _verify_sdk_snapshot(prefix: Path, runtime_data: Path) -> None:
    lock = canonical.strict_loads((runtime_data / "deps/lock.json").read_bytes())
    dependency = next(item for item in lock["dependencies"] if item["id"] == "audio-sdk-installed-package")
    manifest = runtime_data / "deps/sdk-snapshot/audio-sdk-0.1.0.files.sha256"
    if _digest_file(manifest) != dependency["file_manifest_sha256"]:
        raise ValidationError("bundled SDK manifest digest mismatch")
    archive = prefix.parent / "audio-sdk-0.1.0.tar.gz"
    if _digest_file(archive) != dependency["sha256"]:
        raise ValidationError("SDK archive differs from the pinned smoke dependency")
    expected: dict[str, str] = {}
    for line in manifest.read_text(encoding="ascii").splitlines():
        digest, relative = line.split(None, 1)
        relative = relative.strip()
        if not re.fullmatch(r"audio-sdk-0\.1\.0/[A-Za-z0-9._/-]+", relative) or ".." in Path(relative).parts:
            raise ValidationError(f"unsafe path in pinned SDK manifest: {relative!r}")
        expected[relative.removeprefix("audio-sdk-0.1.0/")] = "sha256:" + digest
    observed = {
        path.relative_to(prefix).as_posix(): _digest_file(path)
        for path in prefix.rglob("*") if path.is_file()
    }
    if observed != expected:
        raise ValidationError("SDK prefix files differ from the pinned manifest")


def _reconstruct_output(raw_path: Path, map_path: Path, count: int) -> np.ndarray:
    raw = np.fromfile(raw_path, dtype="<f4")
    result = np.zeros(count, dtype=np.float32)
    covered = np.zeros(count, dtype=np.bool_)
    for line in map_path.read_text(encoding="utf-8").splitlines():
        interval = json.loads(line)
        begin, end = int(interval["source_start"]), int(interval["source_end"])
        output_offset = int(interval["output_offset_samples"]) + int(interval["valid_offset"])
        valid_count = int(interval["valid_count"])
        if begin < 0 or end > count or end - begin != valid_count or output_offset + valid_count > len(raw):
            raise ValidationError("collector source map has an out-of-bounds interval")
        if covered[begin:end].any():
            raise ValidationError("collector source map has duplicate/overlapping valid samples")
        result[begin:end] = raw[output_offset : output_offset + valid_count]
        covered[begin:end] = True
    if not covered.all():
        raise ValidationError(f"collector source map has {int((~covered).sum())} missing samples")
    if not np.isfinite(result).all():
        raise ValidationError("collector output contains non-finite samples")
    return result


def run_sdk_smoke(
    destination: Path,
    *,
    native_build: Path,
    sdk_prefix: Path,
    provider_id: str = "dsp.highpass80.v0",
    repository: Path | None = None,
) -> dict[str, Any]:
    """Execute only an explicitly selected pinned built-in provider on synthetic fixtures.

    The destination is created atomically and must not already exist. This is local functional
    evidence, not an official runner, qualification, or publication.
    """
    source_root = Path(__file__).resolve().parents[2]
    repository = repository or (
        source_root if (source_root / "manifests/synthetic/synthetic-16k-v1").is_dir()
        else Path(__file__).resolve().parent / "runtime_data"
    )
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValidationError("smoke output destination must be a new path", path=str(destination))
    allowed = {"speex.ns.v0", "dsp.highpass80.v0"}
    if provider_id not in allowed:
        raise ValidationError(f"smoke supports only pinned built-in SDK providers: {sorted(allowed)}")
    collector = native_build / "audio_bench_collect"
    driver = native_build / "audio_bench_driver"
    if not collector.is_file() or not driver.is_file():
        raise ValidationError("native driver/collector are not built; configure native/CMakeLists.txt first")

    manifest = repository / "manifests/synthetic/synthetic-16k-v1"
    suite = repository / "suites/synthetic-smoke-v1"
    _verify_sdk_snapshot(sdk_prefix, repository)
    dataset = canonical.require_canonical((manifest / "dataset.json").read_bytes())
    if dataset["rights"]["evaluation"]["decision"] != "allowed":
        raise ValidationError("synthetic fixture does not declare local evaluation allowed")
    cases = canonical.parse_jsonl((manifest / "cases-0000.jsonl").read_bytes())
    case_set = canonical.require_canonical((manifest / "case-set.json").read_bytes())
    intervals = canonical.require_canonical((manifest / "scored-intervals.json").read_bytes())
    cohort = canonical.require_canonical((suite / "cohort.json").read_bytes())
    case_ids = [row["case_id"] for row in case_set["cases"]]
    if case_ids != sorted(case_ids) or {row["case_id"] for row in cases} != set(case_ids):
        raise ValidationError("synthetic case manifest does not match the frozen case set")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".audio-bench-smoke-", dir=destination.parent) as tmp:
        staging = Path(tmp) / "bundle"
        staging.mkdir()
        _copy_manifest(manifest, staging)
        for source_name, bundle_name in (
            ("cohort.json", "cohort.json"),
            ("preprocessing-recipe.json", "recipe-preprocessing.json"),
            ("alignment-recipe.json", "recipe-alignment.json"),
        ):
            shutil.copyfile(suite / source_name, staging / bundle_name)
        (staging / "requests").mkdir()
        attempt_id, run_id, request_id = (str(uuid.uuid4()) for _ in range(3))
        metrics = sorted(item["metric_id"] for item in cohort["metric_set"])
        registry = canonical.strict_loads((repository / "registry/catalog.json").read_bytes())
        request = {
            "schema_id": "audio-bench/request/0.1",
            "request_id": request_id,
            "source_request_key": f"local-synthetic-smoke-{attempt_id}",
            "sequence": "1",
            "sdk_package_digest": next(
                item["sha256"] for item in canonical.strict_loads((repository / "deps/lock.json").read_bytes())["dependencies"]
                if item["id"] == "audio-sdk-installed-package"
            ),
            "harness_revision": "audio-bench-local-smoke-v1",
            "harness_digest": _digest_file(Path(__file__)),
            "registry_snapshot_id": canonical.digest_of(registry),
            "matrix": [{
                "configuration_id": provider_id,
                "cohort_id": cohort["comparison_cohort_id"],
                "expected_case_ids": case_ids,
                "expected_metric_ids": metrics,
                "expected_artifact_paths": sorted([
                    "observations.jsonl", "outputs.jsonl", "summary.json", "collector-summary.json",
                    *[f"rendered/{case_id}.wav" for case_id in case_ids],
                    *[f"source-maps/{case_id}.jsonl" for case_id in case_ids],
                ]),
            }],
            "required_artifact_types": ["observation", "output", "inventory", "summary"],
            "created_at": _utc_now(),
            "resource_profile_id": "local-functional-smoke",
            "requested_target_id": "personal-workstation-not-qualified",
        }
        ledger.store_request(staging, request)

        with tempfile.TemporaryDirectory(prefix="audio-bench-smoke-input-") as input_tmp:
            input_dir = Path(input_tmp)
            input_files = []
            for case_id in case_ids:
                source = staging / "audio" / f"{case_id}.noisy.wav"
                samples = audio.read_wav(source)
                input_path = input_dir / f"{case_id}.f32"
                input_path.write_bytes(samples.astype("<f4", copy=False).tobytes())
                input_files.append(input_path)
            native_output = input_dir / "native-output"
            started = _utc_now()
            command = [
                str(collector), "--driver", str(driver), "--provider", provider_id,
                "--output-dir", str(native_output),
            ]
            for path in input_files:
                command += ["--input", str(path)]
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=300)

            provider_descriptor = repository / "schemas/sdk/providers" / f"{provider_id}.descriptor.json"
            conformance = repository / "docs/task-evidence/artifacts/sdk-conformance"
            conformance_digest = canonical.digest_of({
                "speex": _digest_file(conformance / "speex-report.json"),
                "highpass": _digest_file(conformance / "highpass-report.json"),
            })
            toolchain = repository / "toolchain-lock.json"
            sdk_archive = sdk_prefix.parent / "audio-sdk-0.1.0.tar.gz"
            sdk_digest = _digest_file(sdk_archive)
            if sdk_digest != request["sdk_package_digest"]:
                raise ValidationError("SDK archive changed since the pinned smoke request")
            now = _utc_now()
            run = {
                "schema_id": "audio-bench/run/0.1",
                "request_id": request_id,
                "run_id": run_id,
                "attempt_id": attempt_id,
                "configuration_id": provider_id,
                "comparison_cohort_id": cohort["comparison_cohort_id"],
                "expected_case_metric_set_id": canonical.digest_of([
                    [case_id, metric_id] for case_id in case_ids for metric_id in metrics
                ]),
                "sdk_package_digest": sdk_digest,
                "provider_digest": _digest_file(provider_descriptor),
                "conformance_digest": conformance_digest,
                "source_build_digest": _digest_file(driver),
                "toolchain_lock_digest": _digest_file(toolchain),
                "environment_digest": canonical.digest_of({
                    "system": platform.platform(),
                    "machine": platform.machine(),
                    "python": platform.python_version(),
                }),
                "machine_fingerprint": f"local {platform.system()} {platform.machine()}; not qualified",
                "collector_version": "audio-bench-native-collector/0.1 protocol-v1",
                "started_at": started,
                "ended_at": now,
                "status": "passed",
                "reason": None,
                "core_digest": None,
            }
            attempt = ledger.start_attempt(staging, run)
            rendered = attempt / "rendered"
            maps_dir = attempt / "source-maps"
            rendered.mkdir()
            maps_dir.mkdir()
            case_by_id = {record["case_id"]: record for record in cases}
            interval_by_id = {entry["case_id"]: entry for entry in intervals["entries"]}
            outputs, observations = [], []
            for case_id in case_ids:
                count = int(case_by_id[case_id]["sample_count"])
                raw_path = native_output / f"{case_id}.raw.f32"
                native_map = native_output / f"{case_id}.intervals.jsonl"
                output = _reconstruct_output(raw_path, native_map, count)
                source_map = maps_dir / f"{case_id}.jsonl"
                shutil.copyfile(native_map, source_map)
                wav_path = rendered / f"{case_id}.wav"
                audio.write_wav(wav_path, output)
                clean = audio.read_wav(staging / "audio" / f"{case_id}.clean.wav")
                noisy = audio.read_wav(staging / "audio" / f"{case_id}.noisy.wav")
                case = case_by_id[case_id]
                start_sample = int(interval_by_id[case_id]["start_sample"])
                end_sample = int(interval_by_id[case_id]["end_sample"])
                scored = score_case(
                    case_input_from_arrays(case_id=case_id, clean=clean, noisy=noisy, output=output),
                    interval=(start_sample, end_sample),
                    metric_ids=metrics,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    configuration_id=provider_id,
                    comparison_cohort_id=cohort["comparison_cohort_id"],
                )
                observations.extend(scored)
                outputs.append({
                    "schema_id": "audio-bench/output/0.1",
                    "attempt_id": attempt_id,
                    "case_id": case_id,
                    "configuration_id": provider_id,
                    "mode": "sequential",
                    "workload_id": None,
                    "native_container_sha": audio.encoded_digest(wav_path),
                    "decoded_pcm_sha": audio.pcm_digest(output),
                    "format": {"container": "wav", "subtype": "FLOAT", "sample_rate_hz": 16000, "channels": 1},
                    "sample_count": str(count),
                    "source_map_digest": _digest_file(source_map),
                    "source_input_digest": case["noisy_file_digest"],
                    "sdk_config_digest": None,
                    "preview": None,
                })
            # The collector summary binds measured timing/resources. Its config digest is obtained
            # from the installed SDK and recorded by the native collector (validated below).
            collector_summary = canonical.strict_loads((native_output / "collector-summary.json").read_bytes())
            config_digest = collector_summary.get("sdk_config_digest")
            if not isinstance(config_digest, str) or not canonical.is_digest(config_digest):
                raise ValidationError("native collector summary lacks an SDK effective-config digest")
            for output_record in outputs:
                output_record["sdk_config_digest"] = config_digest
            ledger.sealed_write(attempt / "collector-summary.json", canonical.dumps(collector_summary))
            summary = {
                "schema_id": "audio-bench/summary/0.1",
                "label": "synthetic functional integration; local workstation; not qualified",
                "provider_id": provider_id,
                "sdk_build_id": collector_summary["sdk_build_id"],
                "collector": collector_summary,
                "finite_metric_counts": {
                    metric_id: sum(1 for row in observations if row["metric_id"] == metric_id and row["value"] is not None)
                    for metric_id in metrics
                },
            }
            ledger.seal_attempt(
                attempt,
                request=request,
                matrix_entry=request["matrix"][0],
                observations=observations,
                outputs=outputs,
                summary=summary,
                dataset_id=case_set["dataset_id"],
                comparison_cohort_id=cohort["comparison_cohort_id"],
                scored_interval_set_id=cohort["scored_interval_set_id"],
                metric_set_digest=canonical.digest_of(cohort["metric_set"]),
                registry_snapshot_id=request["registry_snapshot_id"],
                validator=Validator(),
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.rename(staging, destination)
    return {
        "bundle": str(destination),
        "provider_id": provider_id,
        "cases": len(case_ids),
        "metrics_per_case": len(metrics),
        "status": "passed",
        "qualification": "not_assessed",
        "label": "synthetic local functional evidence; not qualification",
    }
