# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0

import json
from pathlib import Path

import pytest

from audio_bench.errors import ValidationError
from audio_bench.submission import load_submission, normalize_latency, validate_submission
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def template():
    return json.loads((ROOT / "submissions/_template.json").read_text())


def test_submission_template_validates_without_examples():
    value = load_submission(ROOT / "submissions/_template.json")
    assert value["execution"]["enabled"] is False


def test_private_source_cannot_select_benchmark_runner():
    value = template()
    value["source"]["visibility"] = "private"
    value["runner_mode"] = "audio-bench"
    with pytest.raises(ValidationError, match="must reference public source"):
        validate_submission(value)


def test_public_submission_accepts_a_provider_plugin_identity():
    value = template()
    value["provider_id"] = "attacker.provider"
    assert validate_submission(value)["provider_id"] == "attacker.provider"


def test_submission_cannot_claim_an_unknown_baseline():
    value = template()
    value["baseline_provider_id"] = "unknown.reference"
    with pytest.raises(ValidationError, match="pinned built-in provider"):
        validate_submission(value)


def test_enabled_submission_requires_model_digest():
    value = template()
    value["provider_id"] = "example.noise-suppressor.v0"
    value["execution"]["enabled"] = True
    with pytest.raises(ValidationError, match="immutable model_digest"):
        validate_submission(value)


def test_enabled_voicebank_sdk_reference_registration_is_supported():
    value = template()
    value["execution"]["enabled"] = True
    value["benchmark"] = {
        "dataset_id": "voicebank-demand-test-v1",
        "suite_id": "voicebank-demand-paired-v1",
    }
    assert validate_submission(value)["benchmark"] == value["benchmark"]


def test_enabled_submission_rejects_mismatched_dataset_suite_pair():
    value = template()
    value["execution"]["enabled"] = True
    value["benchmark"] = {"dataset_id": "voicebank-demand-test-v1", "suite_id": "synthetic-smoke-v1"}
    with pytest.raises(ValidationError, match="supported dataset/suite pair"):
        validate_submission(value)


def test_submitter_runner_manifest_can_be_enabled_after_model_digest_is_pinned():
    value = template()
    value["runner_mode"] = "submitter-owned"
    value["source"]["visibility"] = "private"
    value["model_digest"] = "sha256:" + "0" * 64
    value["execution"]["enabled"] = True
    assert validate_submission(value)["execution"]["enabled"] is True


def test_submitter_runner_refuses_disabled_template_before_checkout(tmp_path):
    from run_submitter_owned import create_result

    submission = template()
    submission["runner_mode"] = "submitter-owned"
    submission["source"]["visibility"] = "private"
    submission_path = tmp_path / "disabled-submission.json"
    submission_path.write_text(json.dumps(submission))
    with pytest.raises(ValidationError, match="execution is disabled"):
        create_result(
            submission_path=submission_path,
            candidate_source=tmp_path / "private-source-not-present",
            sdk_prefix=tmp_path / "sdk-not-present",
            native_build=tmp_path / "native-not-present",
            work=tmp_path / "work",
            reference_calibration=tmp_path / "calibration-not-present.json",
        )


def test_runner_calibration_matches_suite_and_dataset():
    from run_submitter_owned import _runner_calibration

    calibration = _runner_calibration(
        ROOT / "qualification/runner-calibration.json", "speex.ns.v0",
        "voicebank-demand-paired-v1",
        "sha256:cfdc29c6655d195b806c58e75266c05e6cb974ac73c1c1291000af9f386e3f74",
    )
    assert calibration == pytest.approx(0.024241217697068954)


def test_uncalibrated_realtime_suite_keeps_submitter_latency_raw():
    from run_submitter_owned import _runner_calibration

    assert _runner_calibration(
        ROOT / "qualification/runner-calibration.json", "speex.ns.v0",
        "realtime-throughput-v1",
        "sha256:b5ff8fc7185216331ed004005189319cd0bc4e2ad538c87176ba6bac91504ce8",
    ) is None


def test_submitter_runner_accepts_exact_tree_when_git_commit_object_differs():
    from run_submitter_owned import _verify_source_checkout

    revision = "a" * 40
    tree = "b" * 40
    _verify_source_checkout({"revision": revision, "tree_sha": tree}, "c" * 40, tree)
    with pytest.raises(ValidationError, match="pinned commit or its declared Git tree"):
        _verify_source_checkout({"revision": revision, "tree_sha": tree}, "c" * 40, "d" * 40)


def test_latency_normalization_keeps_reference_scale_formula():
    assert normalize_latency(candidate_ns=40, reference_ns=10, local_reference_ns=20) == 20


@pytest.mark.parametrize("values", [(0, 1, 1), (1, 0, 1), (1, 1, float("inf")), (-1, 1, 1), (True, 1, 1)])
def test_latency_normalization_rejects_nonpositive_or_nonfinite(values):
    with pytest.raises(ValueError):
        normalize_latency(*values)
