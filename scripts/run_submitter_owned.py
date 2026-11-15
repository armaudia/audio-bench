#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Run a private candidate locally and emit a result-only public record.

This command never uploads anything. The submitter reviews and copies the resulting JSON to
submissions/results/ when ready. Private source, model files and audio stay on this machine.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from audio_bench import canonical  # noqa: E402
from audio_bench.candidate import build_provider_plugin, load_provider_manifest  # noqa: E402
from audio_bench.errors import ValidationError  # noqa: E402
from audio_bench.smoke import run_sdk_smoke  # noqa: E402
from audio_bench.submission import load_submission, normalize_latency  # noqa: E402
from audio_bench.submitter_results import validate_submitter_result  # noqa: E402
from build_site_results import result_from_bundle  # noqa: E402


def _sha_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _git(source: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(source), *args], check=True,
                          capture_output=True, text=True, timeout=30).stdout.strip()


def _metric_map(row: dict) -> dict[str, dict]:
    return {item["metric_id"]: item for item in row["metrics"]}


def _published_reference(index_path: Path, provider_id: str, suite_id: str, dataset_id: str) -> dict:
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read published reference index: {exc}", path=str(index_path)) from exc
    if index.get("schema_id") != "audio-bench/site-results/0.1" or not isinstance(index.get("results"), list):
        raise ValidationError("published reference index has an unsupported schema")
    matches = [row for row in index["results"]
               if row.get("runner_mode") == "audio-bench" and row.get("provider_id") == provider_id
               and row.get("suite_id") == suite_id and row.get("dataset_id") == dataset_id
               and row.get("result_status", "").startswith("Synthetic functional")]
    if not matches:
        raise ValidationError("no published central synthetic reference matches this provider, suite, and dataset")
    matches.sort(key=lambda row: row.get("result_id", ""))
    metric = _metric_map(matches[-1]).get("latency_ms")
    if not metric or not isinstance(metric.get("median"), (int, float)) or metric["median"] <= 0:
        raise ValidationError("published central reference has no positive latency_ms measurement")
    return matches[-1]


def create_result(*, submission_path: Path, candidate_source: Path, sdk_prefix: Path,
                  native_build: Path, work: Path, reference_index: Path) -> dict:
    submission = load_submission(submission_path)
    if submission["runner_mode"] != "submitter-owned" or submission["source"]["visibility"] != "private":
        raise ValidationError("submitter runner requires runner_mode=submitter-owned and private source metadata")
    if not submission["execution"]["enabled"]:
        raise ValidationError("submission execution is disabled; clear the specific data/model rights gate first")
    candidate_source = candidate_source.resolve(strict=True)
    source_revision = _git(candidate_source, "rev-parse", "HEAD")
    if source_revision != submission["source"]["revision"]:
        raise ValidationError("candidate checkout HEAD does not match the pinned manifest revision")
    manifest, descriptor = load_provider_manifest(candidate_source, submission["provider_id"])
    del manifest
    work = work.resolve()
    if work.exists():
        raise ValidationError("submitter work directory must be new", path=str(work))
    work.mkdir(parents=True)
    plugin = build_provider_plugin(candidate_source, work / "candidate-build", sdk_prefix)

    baseline_bundle = work / "reference-bundle"
    candidate_bundle = work / "candidate-bundle"
    baseline = run_sdk_smoke(baseline_bundle, native_build=native_build, sdk_prefix=sdk_prefix,
                             provider_id=submission["baseline_provider_id"], repository=ROOT)
    candidate = run_sdk_smoke(candidate_bundle, native_build=native_build, sdk_prefix=sdk_prefix,
                              provider_id=submission["provider_id"], repository=ROOT,
                              plugin_path=plugin, descriptor_path=descriptor)
    if baseline["status"] != "passed" or candidate["status"] != "passed":
        raise ValidationError("reference or candidate synthetic smoke did not pass")

    baseline_row = result_from_bundle(baseline_bundle)
    candidate_row = result_from_bundle(candidate_bundle)
    if (baseline_row["suite_id"] != submission["benchmark"]["suite_id"]
            or candidate_row["suite_id"] != baseline_row["suite_id"]
            or baseline_row["dataset_id"] != candidate_row["dataset_id"]):
        raise ValidationError("actual run suite/dataset does not match the submission")
    central = _published_reference(reference_index, submission["baseline_provider_id"],
                                   baseline_row["suite_id"], baseline_row["dataset_id"])
    baseline_metrics = _metric_map(baseline_row)
    candidate_metrics = _metric_map(candidate_row)
    local_baseline_latency = baseline_metrics.get("latency_ms", {}).get("median")
    candidate_latency = candidate_metrics.get("latency_ms", {}).get("median")
    central_latency = _metric_map(central)["latency_ms"]["median"]
    if not all(isinstance(x, (int, float)) and x > 0 for x in
               (local_baseline_latency, candidate_latency, central_latency)):
        raise ValidationError("both local runs and the central reference must have positive latency")
    normalized_latency = normalize_latency(candidate_latency, central_latency, local_baseline_latency)
    metrics = []
    for metric_id, metric in sorted(candidate_metrics.items()):
        item = {key: metric[key] for key in ("metric_id", "label", "unit", "median", "finite_count")}
        if metric_id == "latency_ms":
            item.update(normalized_median=normalized_latency, normalized_unit="ms")
        metrics.append(item)
    dataset_manifest = (ROOT / "manifests/synthetic/synthetic-16k-v1/dataset.json").read_bytes()
    dataset = canonical.require_canonical(dataset_manifest)
    source_identity = _sha_bytes(submission["source"]["repository"].encode("utf-8"))
    harness_revision = _git(ROOT, "rev-parse", "HEAD")
    request = json.loads(next((baseline_bundle / "requests").glob("*.json")).read_text(encoding="utf-8"))
    result = {
        "schema_id": "audio-bench/submitter-result/0.1",
        "submission_id": submission["submission_id"],
        "result_id": f"submitter:{submission['submission_id']}:{uuid.uuid4()}",
        "display_name": submission["display_name"],
        "task": "noise-cancellation",
        "runner_mode": "submitter-owned",
        "result_status": "Submitter-run · not independently verified",
        "provider_id": submission["provider_id"],
        "suite_id": baseline_row["suite_id"],
        "dataset_id": dataset["dataset_id"],
        "model_digest": submission["model_digest"],
        "source": {"visibility": "private", "revision": source_revision,
                   "repository_identity_sha256": source_identity},
        "metrics": metrics,
        "baseline": {"provider_id": submission["baseline_provider_id"],
                     "run_id": baseline_row["result_id"],
                     "metrics": [{"metric_id": item["metric_id"], "median": item["median"],
                                  "unit": item["unit"]} for item in baseline_row["metrics"]]},
        "evidence": {
            "harness_revision": harness_revision,
            "harness_digest": request["harness_digest"],
            "dataset_manifest_digest": _sha_bytes(dataset_manifest),
            "runner_fingerprint": f"{platform.platform()} / Python {platform.python_version()}",
            "reference_raw_latency_ms": local_baseline_latency,
            "candidate_raw_latency_ms": candidate_latency,
            "reference_baseline_latency_ms": central_latency,
            "workflow_attestation_url": None,
        },
    }
    return validate_submitter_result(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--candidate-source", type=Path, required=True)
    parser.add_argument("--sdk-prefix", type=Path, required=True)
    parser.add_argument("--native-build", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--reference-index", type=Path, default=ROOT / "site/data/results.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        record = create_result(submission_path=args.submission, candidate_source=args.candidate_source,
                               sdk_prefix=args.sdk_prefix, native_build=args.native_build,
                               work=args.work, reference_index=args.reference_index)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n",
                               encoding="utf-8")
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError, TypeError, ValidationError) as exc:
        raise SystemExit(f"submitter-owned run failed: {exc}") from exc
    print(f"wrote result-only record to {args.output}; no private source or audio was uploaded")


if __name__ == "__main__":
    main()
