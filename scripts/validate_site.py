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
        if not isinstance(source, dict) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", source.get("repository", "")):
            raise ValueError(f"invalid source repository in {row['result_id']}")
        if not re.fullmatch(r"[0-9a-f]{40}", source.get("revision", "")):
            raise ValueError(f"source revision must be a full commit in {row['result_id']}")
        if set(source) - {"repository", "revision", "url"}:
            raise ValueError(f"unexpected source metadata in {row['result_id']}")
        if source.get("url") is not None and (not isinstance(source["url"], str) or not source["url"].startswith("https://")):
            raise ValueError(f"source URL must use HTTPS in {row['result_id']}")
        if row.get("model_digest") is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", row["model_digest"]):
            raise ValueError(f"invalid model digest in {row['result_id']}")
        evidence = row.get("evidence")
        if not isinstance(evidence, dict):
            raise ValueError(f"missing evidence provenance in {row['result_id']}")
        for field in ("configuration_id", "sdk_package_digest", "harness_digest", "bundle_manifest_digest"):
            if not isinstance(evidence.get(field), str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", evidence[field]):
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
            for field in ("median", "normalized_value"):
                value = metric.get(field)
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                    raise ValueError(f"invalid metric {field} in {row['result_id']}")
            if metric.get("normalized_display_value") is not None and not isinstance(metric["normalized_display_value"], str):
                raise ValueError(f"invalid normalized display value in {row['result_id']}")
        if row["runner_mode"] == "submitter-owned" and not any(token in row["result_status"].lower() for token in ("submitter", "unverified")):
            raise ValueError(f"submitter-owned results must be clearly labeled in {row['result_id']}")
    return len(seen)


if __name__ == "__main__":
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "site/data/results.json"
    index = json.loads(source.read_text(encoding="utf-8"))
    count = validate_index(index)
    print(f"validated Pages result index ({count} results)")
