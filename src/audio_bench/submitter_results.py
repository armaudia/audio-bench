# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Validate public, submitter-owned result metadata without acquiring private source."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .errors import ValidationError

SCHEMA_PATH = Path(__file__).resolve().parent / "schema_data" / "submitter-result.schema.json"


def validate_submitter_result(value: Any) -> dict[str, Any]:
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - project dependency
        raise ValidationError("jsonschema is required to validate results") from exc
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(value),
                    key=lambda item: list(map(str, item.absolute_path)))
    if errors:
        error = errors[0]
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        raise ValidationError(f"submitter result schema error at {location}: {error.message}")

    evidence = value["evidence"]
    category_by_task = {"noise-cancellation": "speech-enhancement", "filtering": "real-time-processing"}
    if value.get("category_id", category_by_task[value["task"]]) != category_by_task[value["task"]]:
        raise ValidationError("category_id does not match the result task")
    if value["suite_id"] == "voicebank-demand-paired-v1":
        if value.get("case_count") != 824 or not str(value.get("dataset_label", "")).startswith("VoiceBank+DEMAND"):
            raise ValidationError("VoiceBank submitter results must identify the complete 824-pair cohort")
    reference_local = evidence["reference_raw_latency_ms"]
    candidate_local = evidence["candidate_raw_latency_ms"]
    reference_central = evidence["reference_baseline_latency_ms"]
    if any(not math.isfinite(x) or x <= 0 for x in (reference_local, candidate_local, reference_central)):
        raise ValidationError("latency measurements must be finite positive numbers")
    expected_latency = candidate_local * reference_central / reference_local
    if not math.isfinite(expected_latency):
        raise ValidationError("normalized latency estimate is not finite")
    seen_metrics: set[str] = set()
    for metric in value["metrics"]:
        if metric["metric_id"] in seen_metrics:
            raise ValidationError(f"duplicate metric_id: {metric['metric_id']}")
        seen_metrics.add(metric["metric_id"])
        if not math.isfinite(metric["median"]):
            raise ValidationError(f"metric {metric['metric_id']} median must be finite")
        if "mean" in metric and not math.isfinite(metric["mean"]):
            raise ValidationError(f"metric {metric['metric_id']} mean must be finite")
        interval = metric.get("median_interval_95")
        if interval is not None and (not all(math.isfinite(value) for value in interval) or interval[0] > interval[1]):
            raise ValidationError(f"metric {metric['metric_id']} has an invalid 95% interval")
        normalized = metric.get("normalized_median")
        if normalized is not None:
            if metric["unit"] != "ms" or metric.get("normalized_unit") != "ms":
                raise ValidationError("only latency in milliseconds may be hardware-normalized")
            if not math.isfinite(normalized) or not math.isclose(normalized, expected_latency, rel_tol=1e-6, abs_tol=1e-6):
                raise ValidationError("normalized latency does not match the declared reference measurements")
        elif metric.get("normalized_unit") is not None:
            raise ValidationError("normalized_unit requires normalized_median")
    baseline_ids: set[str] = set()
    for metric in value["baseline"]["metrics"]:
        if metric["metric_id"] in baseline_ids:
            raise ValidationError(f"duplicate baseline metric_id: {metric['metric_id']}")
        baseline_ids.add(metric["metric_id"])
        if not math.isfinite(metric["median"]):
            raise ValidationError(f"baseline metric {metric['metric_id']} median must be finite")
    if value["baseline"]["provider_id"] != value["baseline"]["provider_id"].strip():
        raise ValidationError("baseline provider_id must not contain surrounding whitespace")
    return value


def load_submitter_result(path: Path) -> dict[str, Any]:
    def reject_constant(token: str) -> None:
        raise ValueError(f"invalid JSON numeric constant {token}")

    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValidationError(f"cannot read submitter result: {exc}", path=str(path)) from exc
    return validate_submitter_result(value)
