# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from audio_bench import canonical
from audio_bench.candidate import load_provider_manifest
from audio_bench.errors import ValidationError
import evaluate_public_candidates as evaluator
import package_public_candidates as packager


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_provider_manifest_rejects_descriptor_path_escape(tmp_path):
    (tmp_path / "audio-bench-provider.json").write_text(json.dumps({
        "schema_id": "audio-bench/provider-plugin/0.1",
        "provider_id": "test.provider.v0",
        "descriptor_path": "../descriptor.json",
    }))
    with pytest.raises(ValidationError, match="must stay within"):
        load_provider_manifest(tmp_path, "test.provider.v0")


def test_disabled_public_example_packages_to_an_empty_marker(tmp_path):
    output = tmp_path / "packages"
    count = packager.package([ROOT / "examples/submissions/audio-sdk.json"],
                             sdk_prefix=tmp_path / "sdk", output=output)
    assert count == 0
    assert json.loads((output / "no-enabled-public-submissions.json").read_text()) == {}


def test_evaluator_checks_package_hashes_and_provenance(tmp_path, monkeypatch):
    package_dir = tmp_path / "packages" / "test-submission"
    package_dir.mkdir(parents=True)
    plugin = package_dir / "libaudio_bench_provider.so"
    plugin.write_bytes(b"candidate binary fixture")
    descriptor = package_dir / "provider.descriptor.json"
    descriptor.write_bytes(canonical.dumps({"provider_id": "test.provider.v0"}))
    revision = "a" * 40
    submission = {
        "submission_id": "test-submission",
        "display_name": "Test provider",
        "provider_id": "test.provider.v0",
        "model_digest": "sha256:" + "1" * 64,
        "source": {"repository": "example/provider", "revision": revision},
    }
    (package_dir / "submission.json").write_text(json.dumps(submission))
    package = {
        "schema_id": "audio-bench/candidate-package/0.1",
        "submission_id": "test-submission",
        "source_revision": revision,
        "provider_id": "test.provider.v0",
        "plugin_file": plugin.name,
        "plugin_sha256": sha(plugin),
        "descriptor_sha256": sha(descriptor),
    }
    (package_dir / "package.json").write_text(json.dumps(package))
    calls = []
    monkeypatch.setattr(evaluator, "run_sdk_smoke", lambda *args, **kwargs: calls.append(kwargs))
    monkeypatch.setattr(evaluator, "result_from_bundle", lambda _bundle: {
        "submission_id": "reference-test.provider.v0",
        "result_id": "run:attempt",
        "display_name": "Built-in test.provider.v0",
        "task": "Noise cancellation",
        "runner_mode": "audio-bench",
        "result_status": "Synthetic functional check · not qualification",
        "provider_id": "test.provider.v0",
        "suite_id": "synthetic-smoke-v1",
        "dataset_id": "sha256:" + "2" * 64,
        "model_digest": None,
        "source": {},
        "metrics": [],
        "evidence": {},
    })
    monkeypatch.setattr(evaluator.validate_site, "validate_index", lambda index: len(index["results"]))

    index = evaluator.evaluate(tmp_path / "packages", sdk_prefix=tmp_path / "sdk",
                               native_build=tmp_path / "native", work=tmp_path / "work")
    row = index["results"][0]
    assert calls[0]["plugin_path"] == plugin
    assert row["runner_mode"] == "audio-bench"
    assert row["source"]["repository"] == "example/provider"
    assert row["source"]["revision"] == revision
    assert row["submission_id"] == "test-submission"

    package["plugin_sha256"] = "sha256:" + "0" * 64
    (package_dir / "package.json").write_text(json.dumps(package))
    with pytest.raises(ValidationError, match="digest mismatch"):
        evaluator.evaluate(tmp_path / "packages", sdk_prefix=tmp_path / "sdk",
                           native_build=tmp_path / "native", work=tmp_path / "work-2")
