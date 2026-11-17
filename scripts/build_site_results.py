#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Convert validated synthetic smoke bundles into cumulative Pages result rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from audio_bench import aggregate, canonical  # noqa: E402
from audio_bench.bundle import validate_bundle  # noqa: E402
from audio_bench.errors import ValidationError  # noqa: E402
from audio_bench.submitter_results import load_submitter_result  # noqa: E402


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        return canonical.parse_jsonl(path.read_bytes(), path=str(path))
    except (OSError, ValidationError) as exc:
        raise ValueError(f"cannot read benchmark observations: {exc}") from exc


def _bundle_manifest_digest(bundle: Path) -> str:
    """Digest the explicit manifest or, for smoke bundles, their root manifest records."""
    manifest_path = bundle / "manifest.json"
    if manifest_path.is_file():
        return canonical.digest_of(json.loads(manifest_path.read_text(encoding="utf-8")))
    records = {}
    for path in sorted((*bundle.glob("*.json"), *bundle.glob("*.jsonl"))):
        records[path.name] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    if not records:
        raise ValueError(f"bundle has no root manifest records: {bundle}")
    return canonical.digest_of({"root_manifest_records": records})


def result_from_bundle(bundle: Path) -> dict[str, Any]:
    """Create a public summary row from an intact, valid bundle; never copy its audio."""
    report = validate_bundle(bundle)
    if not report.valid:
        raise ValueError(f"invalid benchmark bundle {bundle}: {'; '.join(report.errors)}")
    attempts = sorted((bundle / "runs").glob("*/*"))
    if len(attempts) != 1:
        raise ValueError(f"expected exactly one attempt in smoke bundle {bundle}")
    attempt = attempts[0]
    run = json.loads((attempt / "run.json").read_text(encoding="utf-8"))
    summary = json.loads((attempt / "summary.json").read_text(encoding="utf-8"))
    observations = _load_jsonl(attempt / "observations.jsonl")
    provider_id = summary.get("provider_id")
    if summary.get("label") != "synthetic functional integration; not qualified":
        raise ValueError("bundle is not the supported synthetic functional smoke")
    metrics = []
    metric_ids = sorted({row["metric_id"] for row in observations})
    for metric_id in metric_ids:
        rows = [row for row in observations if row["metric_id"] == metric_id]
        stats = aggregate.summarize_metric(rows)
        if stats["finite_count"] == 0 or stats["median"] is None:
            continue
        unit = rows[0]["unit"]
        median = stats["median"]
        metrics.append({
            "metric_id": metric_id,
            "label": metric_id,
            "unit": unit,
            "median": median,
            "mean": stats["mean"],
            "finite_count": stats["finite_count"],
            "display_value": f"{median:.4g} {unit}".strip(),
            "raw_display_value": f"{median:.4g} {unit}".strip(),
            "normalized_display_value": None,
        })
    collector = summary.get("collector", {})
    case_frames = sum((int(case["source_samples"]) + 159) // 160
                      for case in collector.get("cases", []))
    cpu_ns = int(collector.get("direct_child_cpu_ns", "0"))
    if case_frames > 0 and cpu_ns > 0:
        latency = cpu_ns / case_frames / 1_000_000
        metrics.append({
            "metric_id": "latency_ms",
            "label": "CPU time per 10 ms frame",
            "unit": "ms",
            "median": latency,
            "finite_count": case_frames,
            "display_value": f"{latency:.4g} ms",
            "raw_display_value": f"{latency:.4g} ms",
            "normalized_display_value": None,
        })
    dataset = json.loads((bundle / "dataset.json").read_text(encoding="utf-8"))
    request_files = sorted((bundle / "requests").glob("*.json"))
    request = json.loads(request_files[0].read_text(encoding="utf-8"))
    suite_id = request.get("suite_id", "synthetic-smoke-v1")
    return {
        "submission_id": f"reference-{provider_id}",
        "result_id": run["run_id"] + ":" + run["attempt_id"],
        "display_name": "Built-in " + {"speex.ns.v0": "Speex noise suppression",
                                           "dsp.highpass80.v0": "High-pass filter"}.get(provider_id, provider_id),
        "task": "Noise cancellation",
        "runner_mode": "audio-bench",
        "result_status": "Synthetic functional check · not qualification",
        "provider_id": provider_id,
        "suite_id": suite_id,
        "dataset_id": dataset["dataset_id"],
        "model_digest": None,
        "source": {
            "repository": "armaudia/audio-sdk",
            "revision": json.loads((ROOT / "deps/sdk-source.json").read_text(encoding="utf-8"))["revision"],
            "url": "https://github.com/armaudia/audio-sdk",
        },
        "metrics": metrics,
        "evidence": {
            "run_id": run["run_id"],
            "attempt_id": run["attempt_id"],
            "configuration_id": run["configuration_id"],
            "sdk_package_digest": run["sdk_package_digest"],
            "harness_digest": request["harness_digest"],
            "bundle_manifest_digest": _bundle_manifest_digest(bundle),
            "machine_fingerprint": run["machine_fingerprint"],
        },
    }


def result_from_submitter_file(path: Path) -> dict[str, Any]:
    """Convert an explicitly unverified submitter record to the Pages presentation shape."""
    record = load_submitter_result(path)
    metrics = []
    for metric in record["metrics"]:
        normalized = metric.get("normalized_median")
        metrics.append({
            "metric_id": metric["metric_id"],
            "label": metric["label"],
            "unit": metric["unit"],
            "median": metric["median"],
            "mean": metric.get("mean"),
            "median_interval_95": metric.get("median_interval_95"),
            "finite_count": metric["finite_count"],
            "display_value": f"{metric['median']:.4g} {metric['unit']}".strip(),
            "raw_display_value": f"{metric['median']:.4g} {metric['unit']}".strip(),
            "normalized_display_value": f"{normalized:.4g} ms" if normalized is not None else None,
        })
    row = {
        "submission_id": record["submission_id"],
        "result_id": record["result_id"],
        "display_name": record["display_name"],
        "task": "Noise cancellation",
        "runner_mode": "submitter-owned",
        "result_status": record["result_status"],
        "provider_id": record["provider_id"],
        "suite_id": record["suite_id"],
        "dataset_id": record["dataset_id"],
        "dataset_label": record.get("dataset_label", record["dataset_id"]),
        "case_count": record.get("case_count"),
        "model_digest": record["model_digest"],
        "source": {
            "visibility": "private",
            "revision": record["source"]["revision"],
            "repository_identity_sha256": record["source"]["repository_identity_sha256"],
        },
        "metrics": metrics,
        "baseline": record["baseline"],
        "evidence": record["evidence"],
    }
    if str(record.get("dataset_label", "")).startswith("VoiceBank+DEMAND"):
        row["protocol_url"] = "https://github.com/armaudia/audio-bench/blob/main/suites/voicebank-demand-paired-v1/protocol.json"
        row["dataset_source_url"] = "https://datashare.ed.ac.uk/handle/10283/2791"
    return row


def build_index(bundles: list[Path], existing: Path | None = None) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    if existing and existing.exists():
        current = json.loads(existing.read_text(encoding="utf-8"))
        if set(current) != {"schema_id", "updated_at", "results"} or current["schema_id"] != "audio-bench/site-results/0.1":
            raise ValueError("existing site results index has an unsupported format")
        for row in current["results"]:
            if not isinstance(row, dict) or not isinstance(row.get("result_id"), str):
                raise ValueError("existing site result has no result_id")
            rows[row["result_id"]] = row
    for bundle in bundles:
        row = result_from_bundle(bundle)
        rows[row["result_id"]] = row
    return _index(rows)


def merge_index_files(existing: Path, additions: Path, submitter_paths: list[Path] | None = None) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    for path in (existing, additions):
        if not path.exists():
            continue
        current = json.loads(path.read_text(encoding="utf-8"))
        if set(current) != {"schema_id", "updated_at", "results"} or current["schema_id"] != "audio-bench/site-results/0.1":
            raise ValueError(f"result index has an unsupported format: {path}")
        if not isinstance(current["results"], list):
            raise ValueError(f"result index results must be a list: {path}")
        for row in current["results"]:
            if not isinstance(row, dict) or not isinstance(row.get("result_id"), str):
                raise ValueError(f"result row lacks a result_id: {path}")
            previous = rows.get(row["result_id"])
            if previous is not None and previous != row:
                raise ValueError(f"conflicting records use result_id {row['result_id']!r}")
            rows[row["result_id"]] = row
    for item in submitter_paths or []:
        files = sorted(item.glob("*.json")) if item.is_dir() else [item]
        for path in files:
            if path.name.startswith("_"):
                continue
            row = result_from_submitter_file(path)
            previous = rows.get(row["result_id"])
            if previous is not None and previous.get("submission_id") != row["submission_id"]:
                raise ValueError(f"conflicting records use result_id {row['result_id']!r}")
            # The validated submitter record is canonical; re-convert it when the display schema evolves.
            rows[row["result_id"]] = row
    return _index(rows)


def _index(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows.values(), key=lambda row: (row["submission_id"], row["result_id"]))
    return {
        "schema_id": "audio-bench/site-results/0.1",
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "results": ordered,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--existing", type=Path, help="merge with a prior cumulative Pages index")
    parser.add_argument("--from-index", type=Path, help="merge rows from a generated result index")
    parser.add_argument("--submitter-results", type=Path, nargs="*", default=[], help="validated submitter result files or directories")
    parser.add_argument("--output", type=Path, default=ROOT / "site/data/results.json")
    parser.add_argument("bundles", type=Path, nargs="*")
    args = parser.parse_args()
    try:
        if args.from_index:
            if args.bundles or not args.existing:
                parser.error("--from-index requires --existing and does not accept bundle arguments")
            index = merge_index_files(args.existing, args.from_index, args.submitter_results)
        else:
            if not args.bundles:
                parser.error("provide one or more bundles, or use --from-index")
            index = build_index(args.bundles, args.existing)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(index, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f"cannot build Pages result index: {exc}") from exc
    print(f"wrote {len(index['results'])} cumulative result rows to {args.output}")


if __name__ == "__main__":
    main()
