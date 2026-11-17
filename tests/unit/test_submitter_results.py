# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0

import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from audio_bench.errors import ValidationError
from audio_bench.submitter_results import validate_submitter_result
import build_site_results as publisher


def record():
    return {
        "schema_id": "audio-bench/submitter-result/0.1",
        "submission_id": "audio-pro-tiny16",
        "result_id": "private-run-20261115-001",
        "display_name": "Private pipeline example",
        "task": "noise-cancellation",
        "runner_mode": "submitter-owned",
        "result_status": "Submitter-run · not independently verified",
        "provider_id": "private.pipeline.v1",
        "suite_id": "synthetic-smoke-v1",
        "dataset_id": "sha256:" + "1" * 64,
        "model_digest": "sha256:" + "2" * 64,
        "source": {
            "visibility": "private",
            "revision": "a" * 40,
            "repository_identity_sha256": "sha256:" + "3" * 64,
        },
        "metrics": [
            {"metric_id": "si_sdr_db", "label": "SI-SDR", "unit": "dB", "median": 3.5, "finite_count": 24},
            {"metric_id": "latency_ms", "label": "Latency", "unit": "ms", "median": 20.0, "finite_count": 24,
             "normalized_median": 25.0, "normalized_unit": "ms"},
        ],
        "baseline": {"provider_id": "speex.ns.v0", "run_id": "baseline-001",
                     "metrics": [{"metric_id": "si_sdr_db", "median": 2.0, "unit": "dB"}]},
        "evidence": {
            "harness_revision": "b" * 40,
            "harness_digest": "sha256:" + "4" * 64,
            "dataset_manifest_digest": "sha256:" + "5" * 64,
            "runner_fingerprint": "submitter-owned runner; linux x86_64",
            "reference_raw_latency_ms": 10.0,
            "candidate_raw_latency_ms": 20.0,
            "reference_baseline_latency_ms": 12.5,
        },
    }


def test_submitter_result_validates_and_converts_without_private_url(tmp_path):
    value = validate_submitter_result(record())
    path = tmp_path / "result.json"
    path.write_text(json.dumps(value))
    row = publisher.result_from_submitter_file(path)
    assert value["source"]["repository_identity_sha256"].startswith("sha256:")
    assert row["runner_mode"] == "submitter-owned"
    assert row["source"].get("repository") is None
    assert row["metrics"][1]["normalized_display_value"] == "25 ms"


def test_submitter_result_rejects_quality_metric_normalization():
    value = record()
    value["metrics"][0]["normalized_median"] = 4.0
    value["metrics"][0]["normalized_unit"] = "dB"
    with pytest.raises(ValidationError, match="only latency"):
        validate_submitter_result(value)


def test_submitter_result_rejects_private_repository_url_or_name():
    value = record()
    value["source"]["repository"] = "acme/private-repo"
    with pytest.raises(ValidationError, match="(?i)additional properties"):
        validate_submitter_result(value)


def test_submitter_result_rejects_nan_metrics():
    value = record()
    value["metrics"][0]["median"] = math.nan
    with pytest.raises(ValidationError, match="must be finite"):
        validate_submitter_result(value)


def test_submitter_result_requires_unverified_label():
    value = record()
    value["result_status"] = "Audio-bench verified"
    with pytest.raises(ValidationError, match="result_status"):
        validate_submitter_result(value)


def test_result_merge_rejects_conflicting_result_ids(tmp_path):
    existing = tmp_path / "existing.json"
    additions = tmp_path / "additions.json"
    # Reuse the public conversion path so the collision is checked after validation.
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps(record()))
    row = publisher.result_from_submitter_file(candidate)
    existing.write_text(json.dumps({"schema_id": "audio-bench/site-results/0.1", "updated_at": "x", "results": [row]}))
    changed = dict(row, display_name="Tampered duplicate")
    additions.write_text(json.dumps({"schema_id": "audio-bench/site-results/0.1", "updated_at": "x", "results": [changed]}))
    with pytest.raises(ValueError, match="conflicting records"):
        publisher.merge_index_files(existing, additions)


def test_canonical_submitter_record_refreshes_older_site_projection(tmp_path):
    source = tmp_path / "submitter.json"
    source.write_text(json.dumps(record()))
    current = publisher.result_from_submitter_file(source)
    legacy = json.loads(json.dumps(current))
    legacy["metrics"] = [{k: v for k, v in metric.items() if k not in {"mean", "median_interval_95"}}
                         for metric in legacy["metrics"]]
    existing = tmp_path / "existing.json"
    additions = tmp_path / "additions.json"
    existing.write_text(json.dumps({"schema_id": "audio-bench/site-results/0.1", "updated_at": "x", "results": [legacy]}))
    additions.write_text(json.dumps({"schema_id": "audio-bench/site-results/0.1", "updated_at": "x", "results": []}))
    merged = publisher.merge_index_files(existing, additions, [source])
    refreshed = merged["results"][0]
    assert refreshed["metrics"] == current["metrics"]
