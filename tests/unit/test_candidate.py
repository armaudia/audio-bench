# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from audio_bench import canonical
from audio_bench.candidate import load_provider_assets, load_provider_manifest
from audio_bench.errors import ValidationError
from audio_bench.candidate import build_provider_plugin
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


def test_candidate_assets_are_digest_pinned_and_confined_to_source(tmp_path):
    import hashlib

    source = tmp_path / "candidate"
    source.mkdir()
    asset = source / "weights.f32"
    asset.write_bytes(b"pinned model bytes")
    digest = "sha256:" + hashlib.sha256(asset.read_bytes()).hexdigest()
    descriptor = source / "provider.descriptor.json"
    descriptor.write_bytes(canonical.dumps({
        "provider_id": "test.provider.v0",
        "required_assets": [{"id": "weights", "sha256": digest, "byte_count": asset.stat().st_size}],
    }))
    (source / "audio-bench-provider.json").write_text(json.dumps({
        "schema_id": "audio-bench/provider-plugin/0.1",
        "provider_id": "test.provider.v0",
        "descriptor_path": "provider.descriptor.json",
        "assets": [{"id": "weights", "path": "weights.f32", "sha256": digest}],
    }))
    manifest, checked_descriptor = load_provider_manifest(source, "test.provider.v0")
    assert load_provider_assets(source, manifest, checked_descriptor) == {"weights": asset}
    (source / "weights.f32").write_bytes(b"tampered")
    with pytest.raises(ValidationError, match="identity"):
        load_provider_assets(source, manifest, checked_descriptor)


def test_candidate_manifest_asset_path_cannot_escape_checkout(tmp_path):
    source = tmp_path / "candidate"
    source.mkdir()
    descriptor = source / "provider.descriptor.json"
    descriptor.write_bytes(canonical.dumps({"provider_id": "test.provider.v0", "required_assets": []}))
    (source / "provider.descriptor.json").write_bytes(canonical.dumps({
        "provider_id": "test.provider.v0",
        "required_assets": [{"id": "weights", "sha256": "sha256:" + "0" * 64, "byte_count": 1}],
    }))
    manifest = {"assets": [{"id": "weights", "path": "../weights.f32", "sha256": "sha256:" + "0" * 64}]}
    with pytest.raises(ValidationError, match="must stay within"):
        load_provider_assets(source, manifest, source / "provider.descriptor.json")


def test_candidate_build_uses_the_running_python_interpreter(tmp_path, monkeypatch):
    source = tmp_path / "candidate"
    source.mkdir()
    sdk_prefix = tmp_path / "sdk"
    sdk_prefix.mkdir()
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if "--build" in command:
            output = Path(command[command.index("--build") + 1])
            (output / "libaudio_bench_provider.so").write_bytes(b"test plugin")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("audio_bench.candidate.subprocess.run", fake_run)
    plugin = build_provider_plugin(source, tmp_path / "build", sdk_prefix)
    assert plugin.name == "libaudio_bench_provider.so"
    assert f"-DPython3_EXECUTABLE={sys.executable}" in commands[0]


def test_disabled_public_example_packages_to_an_empty_marker(tmp_path):
    output = tmp_path / "packages"
    count = packager.package([ROOT / "examples/submissions/audio-sdk.json"],
                             sdk_prefix=tmp_path / "sdk", output=output)
    assert count == 0
    assert json.loads((output / "no-enabled-public-submissions.json").read_text()) == {}


def test_enabled_pinned_sdk_provider_packages_as_builtin_without_candidate_checkout(monkeypatch, tmp_path):
    revision = "84a102112ce83fb519303a832be15ad88e452d74"

    def fake_run(command, **kwargs):
        if command[-2:] == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(command, 0, stdout=revision + "\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(packager.subprocess, "run", fake_run)
    output = tmp_path / "packages"
    assert packager.package([ROOT / "submissions/audio-sdk-speex-voicebank.json"],
                            sdk_prefix=tmp_path / "sdk", output=output) == 1
    package_dir = output / "audio-sdk-speex-voicebank"
    package = json.loads((package_dir / "package.json").read_text())
    assert package["builtin_provider"] is True
    assert package["plugin_file"] is None
    assert package["assets"] == []
    assert (package_dir / "provider.descriptor.json").is_file()


def test_evaluator_checks_package_hashes_and_provenance(tmp_path, monkeypatch):
    package_dir = tmp_path / "packages" / "test-submission"
    package_dir.mkdir(parents=True)
    plugin = package_dir / "libaudio_bench_provider.so"
    plugin.write_bytes(b"candidate binary fixture")
    descriptor = package_dir / "provider.descriptor.json"
    descriptor.write_bytes(canonical.dumps({"provider_id": "test.provider.v0"}))
    revision = "a" * 40
    submission = {
        "schema_id": "audio-bench/submission/0.1",
        "submission_id": "test-submission",
        "display_name": "Test provider",
        "task": "noise-cancellation",
        "runner_mode": "audio-bench",
        "source": {"repository": "example/provider", "visibility": "public", "revision": revision},
        "provider_id": "test.provider.v0",
        "model_digest": "sha256:" + "1" * 64,
        "baseline_provider_id": "speex.ns.v0",
        "benchmark": {"dataset_id": "synthetic-16k-v1", "suite_id": "synthetic-smoke-v1"},
        "execution": {"enabled": True, "reason": "test"},
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
    monkeypatch.setattr(evaluator, "result_from_bundle", lambda _bundle, _category_id=None: {
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
