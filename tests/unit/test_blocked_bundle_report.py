"""A closed synthetic fixture that demonstrates failure visibility, not SDK integration."""

import shutil
import uuid
from pathlib import Path

from audio_bench import canonical, ledger
from audio_bench.bundle import validate_bundle
from audio_bench.manifests import build_synthetic_dataset
from audio_bench.metrics import METRICS
from audio_bench.report import build_report
from audio_bench.schemas import Validator


def _digest(value):
    return canonical.digest_of({"synthetic_test_only": value})


def test_blocked_attempt_survives_sealing_validation_and_report(tmp_path):
    root = tmp_path / "bundle"
    generated = root / "data-source"
    source = build_synthetic_dataset(generated)
    (root / "audio").mkdir()
    for item in sorted((generated / "audio").glob("*.wav")):
        shutil.copyfile(item, root / "audio" / item.name)
    for name in ("dataset.json", "cases-0000.jsonl", "files-0000.jsonl", "case-set.json", "scored-intervals.json"):
        shutil.copyfile(generated / name, root / name)
    shutil.rmtree(generated)
    suite = Path("suites/synthetic-smoke-v1")
    shutil.copyfile(suite / "cohort.json", root / "cohort.json")
    shutil.copyfile(suite / "preprocessing-recipe.json", root / "recipe-preprocessing.json")
    shutil.copyfile(suite / "alignment-recipe.json", root / "recipe-alignment.json")
    cohort = canonical.require_canonical((root / "cohort.json").read_bytes())
    dataset = canonical.require_canonical((root / "dataset.json").read_bytes())
    case_set = canonical.require_canonical((root / "case-set.json").read_bytes())
    cases = [record["case_id"] for record in case_set["cases"]]

    request_id = str(uuid.UUID("10000000-0000-4000-8000-000000000001"))
    run_id = str(uuid.UUID("10000000-0000-4000-8000-000000000002"))
    attempt_id = str(uuid.UUID("10000000-0000-4000-8000-000000000003"))
    config_id = _digest("effective-config")
    request = {
        "schema_id": "audio-bench/request/0.1",
        "request_id": request_id,
        "source_request_key": "synthetic-test-fixture",
        "sequence": "1",
        # Hash identifies a test string only. This test never asserts SDK package presence.
        "sdk_package_digest": _digest("missing-sdk-test-placeholder"),
        "harness_revision": "synthetic-test",
        "harness_digest": _digest("harness"),
        "registry_snapshot_id": _digest("catalog"),
        "matrix": [{
            "configuration_id": config_id,
            "provider_digest": _digest("synthetic-provider"),
            "cohort_id": cohort["comparison_cohort_id"],
            "expected_case_ids": cases,
            "expected_metric_ids": ["si_sdr_db"],
            "expected_artifact_paths": [
                "effective-config.json", "observations.jsonl", "outputs.jsonl", "summary.json",
            ],
        }],
        "required_artifact_types": ["observation", "output", "inventory", "summary"],
        "created_at": "2026-11-13T00:00:00Z",
        "resource_profile_id": "synthetic-only",
        "requested_target_id": "no-target",
    }
    ledger.store_request(root, request)
    run = {
        "schema_id": "audio-bench/run/0.1",
        "request_id": request_id,
        "run_id": run_id,
        "attempt_id": attempt_id,
        "configuration_id": config_id,
        "comparison_cohort_id": cohort["comparison_cohort_id"],
        "expected_case_metric_set_id": _digest("case-metric-set"),
        "sdk_package_digest": request["sdk_package_digest"],
        "provider_digest": None,
        "conformance_digest": None,
        "source_build_digest": _digest("none"),
        "toolchain_lock_digest": _digest("test-toolchain"),
        "environment_digest": _digest("test-environment"),
        "machine_fingerprint": "synthetic fixture only",
        "collector_version": "not-run",
        "started_at": "2026-11-13T00:00:00Z",
        "ended_at": "2026-11-13T00:00:01Z",
        "status": "blocked",
        "reason": "incompatible_contract",
        "core_digest": None,
    }
    attempt_dir = ledger.start_attempt(root, run)
    ledger.sealed_write(attempt_dir / "effective-config.json", canonical.dumps({
        "synthetic_test_only": "effective-config",
    }))
    observations = [
        {
            "schema_id": "audio-bench/observation/0.1",
            "run_id": run_id,
            "attempt_id": attempt_id,
            "configuration_id": config_id,
            "comparison_cohort_id": cohort["comparison_cohort_id"],
            "case_id": case_id,
            "metric_id": "si_sdr_db",
            "metric_revision": METRICS["si_sdr_db"].revision,
            "execution_status": "blocked",
            "reason": "incompatible_contract",
            "value": None,
            "unit": "dB",
            "direction": "higher",
            "numerator": None,
            "denominator": None,
            "valid_interval": None,
            "output_pcm_digest": None,
        }
        for case_id in cases
    ]
    summary = {"schema_id": "audio-bench/summary/0.1"}
    ledger.seal_attempt(
        attempt_dir,
        request=request,
        matrix_entry=request["matrix"][0],
        observations=observations,
        outputs=[],
        summary=summary,
        dataset_id=dataset["dataset_id"],
        comparison_cohort_id=cohort["comparison_cohort_id"],
        scored_interval_set_id=cohort["scored_interval_set_id"],
        metric_set_digest=_digest("metrics"),
        registry_snapshot_id=request["registry_snapshot_id"],
        validator=Validator(),
    )
    result = validate_bundle(root)
    assert result.valid, result.errors
    assert result.counts == {"cases": 24, "requests": 1, "attempts": 1, "reviews": 0}
    report_result = build_report(root, tmp_path / "report")
    assert report_result["rows"] == 1
    html = (tmp_path / "report" / "index.html").read_text()
    assert "execution: blocked" in html
    assert "qualification: not_assessed" in html
