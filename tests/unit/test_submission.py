# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0

import json
from pathlib import Path

import pytest

from audio_bench.errors import ValidationError
from audio_bench.submission import load_submission, normalize_latency, validate_submission

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", ["audio-sdk.json", "audio-pro.json"])
def test_documented_submission_examples_validate(name):
    value = load_submission(ROOT / "examples/submissions" / name)
    assert value["execution"]["enabled"] is False


def test_private_source_cannot_select_benchmark_runner():
    value = json.loads((ROOT / "examples/submissions/audio-pro.json").read_text())
    value["runner_mode"] = "audio-bench"
    with pytest.raises(ValidationError, match="must reference public source"):
        validate_submission(value)


def test_central_runner_rejects_arbitrary_provider():
    value = json.loads((ROOT / "examples/submissions/audio-sdk.json").read_text())
    value["provider_id"] = "attacker.provider"
    with pytest.raises(ValidationError, match="pinned built-in providers"):
        validate_submission(value)


def test_submission_cannot_claim_an_unknown_baseline():
    value = json.loads((ROOT / "examples/submissions/audio-sdk.json").read_text())
    value["baseline_provider_id"] = "unknown.reference"
    with pytest.raises(ValidationError, match="pinned built-in provider"):
        validate_submission(value)


def test_enabled_submission_requires_model_digest():
    value = json.loads((ROOT / "examples/submissions/audio-sdk.json").read_text())
    value["execution"]["enabled"] = True
    with pytest.raises(ValidationError, match="immutable model_digest"):
        validate_submission(value)


def test_submitter_runner_cannot_claim_execution_before_ingestion_exists():
    value = json.loads((ROOT / "examples/submissions/audio-pro.json").read_text())
    value["model_digest"] = "sha256:" + "0" * 64
    value["execution"]["enabled"] = True
    with pytest.raises(ValidationError, match="not enabled yet"):
        validate_submission(value)


def test_latency_normalization_keeps_reference_scale_formula():
    assert normalize_latency(candidate_ns=40, reference_ns=10, local_reference_ns=20) == 20


@pytest.mark.parametrize("values", [(0, 1, 1), (1, 0, 1), (1, 1, float("inf")), (-1, 1, 1), (True, 1, 1)])
def test_latency_normalization_rejects_nonpositive_or_nonfinite(values):
    with pytest.raises(ValueError):
        normalize_latency(*values)
