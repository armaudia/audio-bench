#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Fail closed on malformed public Pages data before deployment."""

import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def validate_index(index):
    if set(index) != {"schema_id", "updated_at", "results"}:
        raise ValueError("site results index has unexpected or missing top-level fields")
    if index["schema_id"] != "audio-bench/site-results/0.1" or not isinstance(index["results"], list):
        raise ValueError("site results index has unsupported schema or results type")
    seen = set()
    for row in index["results"]:
        if not isinstance(row, dict) or not isinstance(row.get("result_id"), str):
            raise ValueError("each result needs a result_id")
        if row["result_id"] in seen:
            raise ValueError(f"duplicate result id: {row['result_id']}")
        seen.add(row["result_id"])
        for field in ("submission_id", "display_name", "provider_id", "task", "suite_id", "dataset_id", "result_status"):
            if not isinstance(row.get(field), str) or not row[field]:
                raise ValueError(f"each result needs a nonempty {field}: {row['result_id']}")
        if row.get("runner_mode") not in {"audio-bench", "submitter-owned"}:
            raise ValueError(f"unsupported runner mode in {row['submission_id']}")
        source = row.get("source")
        if not isinstance(source, dict):
            raise ValueError(f"missing source provenance in {row['result_id']}")
        if source.get("visibility") == "private":
            if set(source) != {"visibility", "revision", "repository_identity_sha256"}:
                raise ValueError(f"private source metadata may contain only identity hash and revision in {row['result_id']}")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", source.get("repository_identity_sha256", "")):
                raise ValueError(f"invalid private source identity hash in {row['result_id']}")
        else:
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", source.get("repository", "")):
                raise ValueError(f"invalid source repository in {row['result_id']}")
            if set(source) - {"visibility", "repository", "revision", "url"}:
                raise ValueError(f"unexpected source metadata in {row['result_id']}")
            if source.get("url") is not None and (not isinstance(source["url"], str) or not source["url"].startswith("https://")):
                raise ValueError(f"source URL must use HTTPS in {row['result_id']}")
        if not re.fullmatch(r"[0-9a-f]{40}", source.get("revision", "")):
            raise ValueError(f"source revision must be a full commit in {row['result_id']}")
        if row.get("model_digest") is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", row["model_digest"]):
            raise ValueError(f"invalid model digest in {row['result_id']}")
        if row.get("case_count") is not None and (isinstance(row["case_count"], bool) or
                not isinstance(row["case_count"], int) or row["case_count"] < 1):
            raise ValueError(f"invalid case count in {row['result_id']}")
        for field in ("protocol_url", "dataset_source_url"):
            url = row.get(field)
            if url is not None and (not isinstance(url, str) or not url.startswith("https://")):
                raise ValueError(f"invalid {field} in {row['result_id']}")
        evidence = row.get("evidence")
        if not isinstance(evidence, dict):
            raise ValueError(f"missing evidence provenance in {row['result_id']}")
        fields = ("configuration_id", "sdk_package_digest", "harness_digest", "bundle_manifest_digest") if row["runner_mode"] == "audio-bench" else ("harness_digest", "dataset_manifest_digest")
        for field in fields:
            if not isinstance(evidence.get(field), str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", evidence[field]):
                raise ValueError(f"invalid evidence {field} in {row['result_id']}")
        for field, value in evidence.items():
            if field.endswith("_digest") and value is not None and (not isinstance(value, str) or
                    not re.fullmatch(r"sha256:[0-9a-f]{64}", value)):
                raise ValueError(f"invalid evidence {field} in {row['result_id']}")
        if row["runner_mode"] == "submitter-owned":
            for field in ("reference_raw_latency_ms", "candidate_raw_latency_ms", "reference_baseline_latency_ms"):
                value = evidence.get(field)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                    raise ValueError(f"invalid evidence {field} in {row['result_id']}")
        metrics = row.get("metrics")
        if not isinstance(metrics, list):
            raise ValueError(f"metrics must be a list in {row['result_id']}")
        for metric in metrics:
            if not isinstance(metric, dict):
                raise ValueError(f"metric entries must be objects in {row['result_id']}")
            for field in ("metric_id", "label", "unit", "display_value", "raw_display_value"):
                if not isinstance(metric.get(field), str):
                    raise ValueError(f"invalid metric {field} in {row['result_id']}")
            for field in ("median", "normalized_value", "normalized_median"):
                value = metric.get(field)
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                    raise ValueError(f"invalid metric {field} in {row['result_id']}")
            mean = metric.get("mean")
            if mean is not None and (isinstance(mean, bool) or not isinstance(mean, (int, float)) or not math.isfinite(mean)):
                raise ValueError(f"invalid metric mean in {row['result_id']}")
            interval = metric.get("median_interval_95")
            if interval is not None and (not isinstance(interval, list) or len(interval) != 2 or
                    any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                        for value in interval) or interval[0] > interval[1]):
                raise ValueError(f"invalid metric interval in {row['result_id']}")
            if metric.get("normalized_display_value") is not None and not isinstance(metric["normalized_display_value"], str):
                raise ValueError(f"invalid normalized display value in {row['result_id']}")
        if row["runner_mode"] == "submitter-owned" and not any(token in row["result_status"].lower() for token in ("submitter", "unverified")):
            raise ValueError(f"submitter-owned results must be clearly labeled in {row['result_id']}")
        if row["runner_mode"] == "submitter-owned":
            reference_local = evidence["reference_raw_latency_ms"]
            candidate_local = evidence["candidate_raw_latency_ms"]
            reference_central = evidence["reference_baseline_latency_ms"]
            expected = candidate_local * reference_central / reference_local
            for metric in metrics:
                normalized = metric.get("normalized_median")
                if normalized is not None:
                    if metric.get("unit") != "ms" or not math.isclose(normalized, expected, rel_tol=1e-6, abs_tol=1e-6):
                        raise ValueError(f"invalid normalized latency in {row['result_id']}")
    return len(seen)


if __name__ == "__main__":
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "site/data/results.json"
    index = json.loads(source.read_text(encoding="utf-8"))
    count = validate_index(index)
    print(f"validated Pages result index ({count} results)")
