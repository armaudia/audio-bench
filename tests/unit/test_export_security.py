import os

import pytest

from audio_bench import canonical
from audio_bench.errors import ValidationError
from audio_bench.errors import BlockedError
from audio_bench.export import (
    _read_beneath,
    _validate_json_bytes,
    ExportPolicy,
    build_offline_candidate,
    export_candidate,
    project_record,
    verify_export,
)


def test_safe_open_rejects_symlink_and_reads_regular_file(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "ok.json").write_bytes(canonical.dumps({"schema_id": "x", "public": True}))
    assert _read_beneath(root, "ok.json", limit=1024)
    outside = tmp_path / "outside"
    outside.write_bytes(b"secret")
    os.symlink(outside, root / "link.json")
    with pytest.raises(ValidationError):
        _read_beneath(root, "link.json", limit=1024)


def test_public_projection_drops_private_keys():
    projected = project_record({"schema_id": "x", "public": 1, "private_path": "/Users/secret"}, allowlist=frozenset({"schema_id", "public"}))
    assert projected == {"schema_id": "x", "public": 1}


def test_export_json_requires_canonical_bytes_and_depth_caps():
    policy = ExportPolicy(max_nesting=2)
    with pytest.raises(ValidationError, match="canonical"):
        _validate_json_bytes(b'{ "a":1}', path="x.json", policy=policy)
    too_deep = canonical.dumps({"a": {"b": {"c": 1}}})
    with pytest.raises(ValidationError, match="nesting"):
        _validate_json_bytes(too_deep, path="deep.json", policy=policy)


def test_offline_candidate_projects_by_record_type_and_rebuilds_public_hashes(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "run.json").write_bytes(canonical.dumps({
        "schema_id": "audio-bench/run/0.1",
        "run_id": "11111111-1111-4111-8111-111111111111",
        "attempt_id": "22222222-2222-4222-8222-222222222222",
        "configuration_id": "synthetic.provider",
        "comparison_cohort_id": "sha256:" + "1" * 64,
        "status": "passed",
        "reason": None,
        "started_at": "2026-01-01T00:00:00Z",
        "ended_at": "2026-01-01T00:00:01Z",
        "collector_version": "local",
        "machine_fingerprint": "/Users/private/host-id",
        "private_key": "DO_NOT_EXPORT",
    }))
    observation = {
        "schema_id": "audio-bench/observation/0.1",
        "configuration_id": "synthetic.provider",
        "comparison_cohort_id": "sha256:" + "1" * 64,
        "case_id": "case-1",
        "metric_id": "si_sdr_db",
        "execution_status": "passed",
        "reason": None,
        "value": 2.5,
        "unit": "dB",
        "direction": "higher",
        "other": "DO_NOT_EXPORT",
        "secret": "/Users/private",
    }
    (source / "observations.jsonl").write_bytes(canonical.jsonl_bytes([observation]))
    (source / "summary.json").write_bytes(canonical.dumps({
        "schema_id": "audio-bench/summary/0.1",
        "label": "synthetic",
        "complete": True,
        "counts": {"machine_fingerprint": "/Users/private"},
        "private": "DO_NOT_EXPORT",
    }))
    private_core_digest = "sha256:" + "f" * 64
    (source / "core.json").write_bytes(canonical.dumps({"schema_id": "audio-bench/core/0.1", "core_digest": private_core_digest}))
    (source / "inventory.json").write_bytes(canonical.dumps({"schema_id": "audio-bench/inventory/0.1"}))

    destination = tmp_path / "public-candidate"
    candidate = build_offline_candidate(source, destination)
    assert candidate["public_core_digest"] != private_core_digest
    assert (destination / "core.json").is_file()
    assert (destination / "inventory.json").is_file()
    run = canonical.require_canonical((destination / "run.json").read_bytes())
    rows = canonical.parse_jsonl((destination / "observations.jsonl").read_bytes())
    assert "machine_fingerprint" not in run
    assert "private_key" not in run
    assert rows[0]["value"] == 2.5 and "secret" not in rows[0]
    assert b"DO_NOT_EXPORT" not in b"".join(path.read_bytes() for path in destination.iterdir() if path.is_file())
    approval_shape = {"file_inventory": candidate["files"]}
    verify_export(destination, approval_shape)


def test_offline_candidate_failure_is_atomic_and_media_requires_rights(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "observations.jsonl").write_bytes(b'{"schema_id":"unknown"}\n')
    destination = tmp_path / "public"
    with pytest.raises(ValidationError):
        build_offline_candidate(source, destination)
    assert not destination.exists()

    source2 = tmp_path / "media-source"
    source2.mkdir()
    (source2 / "media").mkdir()
    import numpy as np
    from audio_bench.audio import write_wav
    write_wav(source2 / "media/synthetic.wav", np.zeros(160, dtype=np.float32))
    with pytest.raises(ValidationError, match="rights not allowed"):
        build_offline_candidate(source2, tmp_path / "media-public")
    assert not (tmp_path / "media-public").exists()
    rights = {
        scope: {"decision": "allowed", "evidence_ref": "synthetic-fixture-rights"}
        for scope in ("redistribution", "public_playback")
    }
    media_candidate = build_offline_candidate(
        source2, tmp_path / "media-public",
        media_rights={"media/synthetic.wav": rights},
    )
    assert (tmp_path / "media-public/media/synthetic.wav").is_file()
    assert any(item["path"] == "media/synthetic.wav" for item in media_candidate["files"])


def test_public_export_gate_is_closed_until_b08_review(tmp_path):
    source = tmp_path / "private"
    source.mkdir()
    destination = tmp_path / "public"
    with pytest.raises(BlockedError, match="public export is disabled"):
        export_candidate(source, destination)
