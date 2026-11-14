# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_site_results as publisher
import validate_site


def make_bundle(path: Path, run_id: str, provider: str = "speex.ns.v0") -> Path:
    attempt = path / "runs" / run_id / ("a" * 36)
    attempt.mkdir(parents=True)
    (attempt / "run.json").write_text(json.dumps({
        "run_id": run_id, "attempt_id": "a" * 36, "configuration_id": "sha256:" + "1" * 64,
        "machine_fingerprint": "test-runner", "sdk_package_digest": "sha256:" + "2" * 64,
    }))
    (attempt / "summary.json").write_text(json.dumps({
        "provider_id": provider,
        "label": "synthetic functional integration; not qualified",
    }))
    observations = [
        {"metric_id": "stoi", "execution_status": "passed", "value": 0.5, "reason": None, "unit": "index"},
        {"metric_id": "stoi", "execution_status": "passed", "value": 0.7, "reason": None, "unit": "index"},
    ]
    (attempt / "observations.jsonl").write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in observations))
    (path / "dataset.json").write_text(json.dumps({"dataset_id": "synthetic-16k-v1"}))
    (path / "manifest.json").write_text(json.dumps({"bundle": "test"}))
    (path / "requests").mkdir()
    (path / "requests" / "request.json").write_text(json.dumps({"suite_id": "synthetic-smoke-v1", "harness_digest": "sha256:" + "3" * 64}))
    return path


def test_result_builder_aggregates_and_keeps_provenance(monkeypatch, tmp_path):
    bundle = make_bundle(tmp_path / "bundle", "b" * 36)
    monkeypatch.setattr(publisher, "validate_bundle", lambda path: type("Report", (), {"valid": True, "errors": []})())
    result = publisher.result_from_bundle(bundle)
    assert result["metrics"][0]["median"] == 0.6
    assert result["runner_mode"] == "audio-bench"
    assert result["evidence"]["bundle_manifest_digest"].startswith("sha256:")
    assert "audio" not in result and "audio_path" not in result
    assert validate_site.validate_index({"schema_id": "audio-bench/site-results/0.1", "updated_at": None, "results": [result]}) == 1


def test_index_cumulates_and_deduplicates_runs(monkeypatch, tmp_path):
    first = make_bundle(tmp_path / "first", "b" * 36)
    second = make_bundle(tmp_path / "second", "c" * 36)
    monkeypatch.setattr(publisher, "validate_bundle", lambda path: type("Report", (), {"valid": True, "errors": []})())
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"schema_id": "audio-bench/site-results/0.1", "updated_at": None,
                               "results": [publisher.result_from_bundle(first)]}))
    index = publisher.build_index([first, second], old)
    assert len(index["results"]) == 2
    assert len(publisher.build_index([first], old)["results"]) == 1


def test_invalid_bundle_is_not_published(monkeypatch, tmp_path):
    bundle = make_bundle(tmp_path / "bundle", "d" * 36)
    monkeypatch.setattr(publisher, "validate_bundle", lambda path: type("Report", (), {"valid": False, "errors": ["digest mismatch"]})())
    try:
        publisher.result_from_bundle(bundle)
    except ValueError as exc:
        assert "digest mismatch" in str(exc)
    else:
        raise AssertionError("invalid bundle was published")


def test_submitter_owned_results_must_disclose_unverified_status(monkeypatch, tmp_path):
    bundle = make_bundle(tmp_path / "bundle", "e" * 36)
    monkeypatch.setattr(publisher, "validate_bundle", lambda path: type("Report", (), {"valid": True, "errors": []})())
    row = publisher.result_from_bundle(bundle)
    row["runner_mode"] = "submitter-owned"
    row["source"] = {"visibility": "private", "revision": "a" * 40,
                     "repository_identity_sha256": "sha256:" + "1" * 64}
    row["evidence"] = {"harness_digest": "sha256:" + "2" * 64,
                       "dataset_manifest_digest": "sha256:" + "3" * 64,
                       "reference_raw_latency_ms": 10.0,
                       "candidate_raw_latency_ms": 20.0,
                       "reference_baseline_latency_ms": 12.0}
    try:
        validate_site.validate_index({"schema_id": "audio-bench/site-results/0.1", "updated_at": None, "results": [row]})
    except ValueError as exc:
        assert "clearly labeled" in str(exc)
    else:
        raise AssertionError("submitter-run result lacked an unverified label")
