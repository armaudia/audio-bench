# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Validation and conservative normalization for public benchmark submissions."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import ValidationError

SCHEMA_PATH = Path(__file__).resolve().parent / "schema_data" / "submission.schema.json"
PUBLIC_PROVIDERS = {"speex.ns.v0", "dsp.highpass80.v0"}


def validate_submission(value: Any) -> dict[str, Any]:
    """Validate metadata only. This function never resolves or executes source references."""
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - project dependency
        raise ValidationError("jsonschema is required to validate submissions") from exc

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(value),
                    key=lambda item: list(map(str, item.absolute_path)))
    if errors:
        error = errors[0]
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        raise ValidationError(f"submission schema error at {location}: {error.message}")

    source = value["source"]
    if source["visibility"] == "public" and not re.fullmatch(r"[0-9a-f]{40}", source["revision"]):
        raise ValidationError("source.revision must be a full lowercase 40-character commit")
    if value["runner_mode"] == "audio-bench" and source["visibility"] != "public":
        raise ValidationError("audio-bench runner submissions must reference public source")
    if value["baseline_provider_id"] not in PUBLIC_PROVIDERS:
        raise ValidationError("baseline_provider_id must identify a pinned built-in provider")
    if value["execution"]["enabled"] and value["model_digest"] is None and value["provider_id"] not in PUBLIC_PROVIDERS:
        raise ValidationError("enabled model execution requires an immutable model_digest")
    if value["execution"]["enabled"]:
        dataset_id, suite_id = value["benchmark"]["dataset_id"], value["benchmark"]["suite_id"]
        supported = {"synthetic-16k-v1": "synthetic-smoke-v1",
                     "voicebank-demand-test-v1": "voicebank-demand-paired-v1"}
        if supported.get(dataset_id) != suite_id:
            raise ValidationError("enabled execution requires a supported dataset/suite pair")
    return value


def load_submission(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read submission manifest: {exc}", path=str(path)) from exc
    return validate_submission(value)


def normalize_latency(candidate_ns: float, reference_ns: float, local_reference_ns: float) -> float:
    """Estimate reference-runner latency from a same-runner reference measurement.

    The caller must retain raw values and label this as an estimate. This ratio is not suitable
    for quality metrics, and assumes the candidate scales like the reference implementation.
    """
    values = (candidate_ns, reference_ns, local_reference_ns)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0 for value in values):
        raise ValueError("latency measurements must be finite positive numbers")
    import math
    if any(not math.isfinite(value) for value in values):
        raise ValueError("latency measurements must be finite positive numbers")
    estimate = candidate_ns * reference_ns / local_reference_ns
    if not math.isfinite(estimate):
        raise ValueError("normalized latency estimate is not finite")
    return estimate
