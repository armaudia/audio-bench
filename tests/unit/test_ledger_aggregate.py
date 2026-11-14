# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
import pytest

from audio_bench import aggregate, canonical, ledger
from audio_bench.errors import ImmutableViolation, ValidationError


def test_immutable_write_is_idempotent_but_never_overwrites(tmp_path):
    path = tmp_path / "runs" / "one.json"
    ledger.sealed_write(path, b"first")
    ledger.sealed_write(path, b"first")
    assert path.read_bytes() == b"first"
    with pytest.raises(ImmutableViolation):
        ledger.sealed_write(path, b"second")


def test_status_precedence_and_not_applicable():
    assert aggregate.aggregate_status(["passed", "failed", "blocked"]) == "failed"
    assert aggregate.aggregate_status(["passed", "not_applicable"]) == "passed"
    assert aggregate.aggregate_status(["not_applicable"]) == "not_applicable"


def test_matrix_missing_and_duplicate_rows_are_not_hidden():
    expected = [("case-1", "si_sdr"), ("case-2", "si_sdr")]
    rows = [
        {"case_id": "case-1", "metric_id": "si_sdr", "execution_status": "passed"},
        {"case_id": "case-1", "metric_id": "si_sdr", "execution_status": "passed"},
    ]
    result = aggregate.check_matrix(expected, rows)
    assert result["missing"] == [("case-2", "si_sdr")]
    assert result["duplicates"] == [("case-1", "si_sdr")]
    assert not result["complete"]


def test_finite_pair_intersection_shows_excluded_rows():
    candidate = [
        {"case_id": "a", "metric_id": "si_sdr", "execution_status": "passed", "value": 2.0},
        {"case_id": "b", "metric_id": "si_sdr", "execution_status": "failed", "value": None},
    ]
    baseline = [
        {"case_id": "a", "metric_id": "si_sdr", "execution_status": "passed", "value": 1.0},
        {"case_id": "b", "metric_id": "si_sdr", "execution_status": "passed", "value": 0.0},
    ]
    result = aggregate.paired_summary(candidate, baseline, speakers={"a": "s1", "b": "s1"}, metric_id="si_sdr", draws=10)
    assert result["delta"] == 1.0
    assert result["complete"] is False
    assert result["excluded"]["candidate_failed"] == 1
    assert result["label"] == "partial diagnostic comparison"


def test_seal_and_recompute_synthetic_bundle_without_hash_cycles(tmp_path):
    digest = lambda value: canonical.digest_of({"synthetic_fixture": value})
    config_id = digest("effective-config")
    request = {
        "schema_id": "audio-bench/request/0.1",
        "request_id": "00000000-0000-4000-8000-000000000001",
        "source_request_key": "unit-test-1",
        "sequence": "1",
        # Synthetic-only schema fixture, not an installed SDK package or SDK claim.
        "sdk_package_digest": digest("synthetic-sdk-package-placeholder-for-schema-test"),
        "harness_revision": "synthetic-test",
        "harness_digest": digest("harness"),
        "registry_snapshot_id": digest("registry"),
        "matrix": [{
            "configuration_id": config_id,
            "provider_digest": digest("provider"),
            "cohort_id": digest("cohort"),
            "expected_case_ids": ["case-1"],
            "expected_metric_ids": ["clipping_count"],
            "expected_artifact_paths": [
                "effective-config.json", "observations.jsonl", "outputs.jsonl", "summary.json",
            ],
        }],
        "required_artifact_types": ["observation", "output", "inventory", "summary"],
        "created_at": "2026-11-13T00:00:00Z",
        "resource_profile_id": "synthetic-test",
        "requested_target_id": "synthetic-only",
    }
    request_path = ledger.store_request(tmp_path, request)
    assert ledger.store_request(tmp_path, request) == request_path
    stale = {**request, "request_id": "00000000-0000-4000-8000-000000000004"}
    with pytest.raises(ValidationError, match="not greater than prior sequence"):
        ledger.store_request(tmp_path, stale)
    run = {
        "schema_id": "audio-bench/run/0.1",
        "request_id": request["request_id"],
        "run_id": "00000000-0000-4000-8000-000000000002",
        "attempt_id": "00000000-0000-4000-8000-000000000003",
        "configuration_id": config_id,
        "comparison_cohort_id": request["matrix"][0]["cohort_id"],
        "expected_case_metric_set_id": digest("expected"),
        "sdk_package_digest": request["sdk_package_digest"],
        "provider_digest": None,
        "conformance_digest": None,
        "source_build_digest": digest("source"),
        "toolchain_lock_digest": digest("toolchain"),
        "environment_digest": digest("environment"),
        "machine_fingerprint": "synthetic-test-only",
        "collector_version": "synthetic-no-collector",
        "started_at": "2026-11-13T00:00:00Z",
        "ended_at": "2026-11-13T00:00:01Z",
        "status": "passed",
        "reason": None,
        "core_digest": None,
    }
    attempt = ledger.start_attempt(tmp_path, run)
    ledger.sealed_write(attempt / "effective-config.json", canonical.dumps({
        "synthetic_fixture": "effective-config",
    }))
    observation = {
        "schema_id": "audio-bench/observation/0.1",
        "run_id": "00000000-0000-4000-8000-000000000002",
        "attempt_id": "00000000-0000-4000-8000-000000000003",
        "configuration_id": config_id,
        "comparison_cohort_id": request["matrix"][0]["cohort_id"],
        "case_id": "case-1",
        "metric_id": "clipping_count",
        "metric_revision": "abs-gt-1.v1",
        "execution_status": "passed",
        "reason": None,
        "value": 0,
        "unit": "count",
        "direction": "lower",
        "numerator": "0",
        "denominator": "160",
        "valid_interval": {"start_sample": "0", "end_sample": "160", "sample_rate_hz": 16000},
        "output_pcm_digest": digest("pcm"),
    }
    output = {
        "schema_id": "audio-bench/output/0.1",
        "attempt_id": "00000000-0000-4000-8000-000000000003",
        "case_id": "case-1",
        "configuration_id": config_id,
        "mode": "sequential",
        "workload_id": None,
        "native_container_sha": digest("wav"),
        "decoded_pcm_sha": digest("pcm"),
        "format": {"container": "wav", "subtype": "FLOAT", "sample_rate_hz": 16000, "channels": 1},
        "sample_count": "160",
        "source_map_digest": None,
        "source_input_digest": digest("input"),
        "sdk_config_digest": config_id,
        "preview": None,
    }
    summary = {"schema_id": "audio-bench/summary/0.1"}
    core = ledger.seal_attempt(
        attempt,
        request=request,
        matrix_entry=request["matrix"][0],
        observations=[observation],
        outputs=[output],
        summary=summary,
        dataset_id=digest("dataset"),
        comparison_cohort_id=request["matrix"][0]["cohort_id"],
        scored_interval_set_id=digest("intervals"),
        metric_set_digest=digest("metrics"),
        registry_snapshot_id=request["registry_snapshot_id"],
    )
    verified = ledger.verify_attempt(attempt, request=request)
    assert verified["core"]["core_digest"] == core["core_digest"]
    assert verified["run"]["core_digest"] is None
    assert request_path.is_file()
    # A correction never overwrites this attempt: a different digest at an old path is rejected.
    with pytest.raises(ImmutableViolation):
        ledger.sealed_write(attempt / "core.json", b"changed")
