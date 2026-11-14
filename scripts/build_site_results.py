#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Convert validated synthetic smoke bundles into cumulative Pages result rows."""

from __future__ import annotations

import argparse
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


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        return canonical.parse_jsonl(path.read_bytes(), path=str(path))
    except (OSError, ValidationError) as exc:
        raise ValueError(f"cannot read benchmark observations: {exc}") from exc


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
    if provider_id not in {"speex.ns.v0", "dsp.highpass80.v0"}:
        raise ValueError(f"unsupported provider in smoke bundle: {provider_id!r}")
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
            "finite_count": stats["finite_count"],
            "display_value": f"{median:.4g} {unit}".strip(),
            "raw_display_value": f"{median:.4g} {unit}".strip(),
            "normalized_display_value": None,
        })
    dataset = json.loads((bundle / "dataset.json").read_text(encoding="utf-8"))
    request_files = sorted((bundle / "requests").glob("*.json"))
    request = json.loads(request_files[0].read_text(encoding="utf-8"))
    suite_id = request.get("suite_id", "synthetic-smoke-v1")
    return {
        "submission_id": f"reference-{provider_id}",
        "result_id": run["run_id"] + ":" + run["attempt_id"],
        "display_name": "Built-in " + ("Speex noise suppression" if provider_id == "speex.ns.v0" else "High-pass filter"),
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
            "bundle_manifest_digest": canonical.digest_of(json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))),
            "machine_fingerprint": run["machine_fingerprint"],
        },
    }


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


def merge_index_files(existing: Path, additions: Path) -> dict[str, Any]:
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
    parser.add_argument("--output", type=Path, default=ROOT / "site/data/results.json")
    parser.add_argument("bundles", type=Path, nargs="*")
    args = parser.parse_args()
    try:
        if args.from_index:
            if args.bundles or not args.existing:
                parser.error("--from-index requires --existing and does not accept bundle arguments")
            index = merge_index_files(args.existing, args.from_index)
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
