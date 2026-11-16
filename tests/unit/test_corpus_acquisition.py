# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0

import base64
import hashlib
import io
import json
import sys
import wave
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_dns5_dev as dns5  # noqa: E402
from audio_bench.errors import AcquisitionError  # noqa: E402


def _wav48() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(48000)
        audio.writeframes(b"\x01\x00" * 32)
    return output.getvalue()


def _dns5_archive(path: Path) -> bytes:
    track = "V5_dev_testset/Track2_Speakerphone"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index in range(600):
            archive.writestr(f"{track}/noisy/clip-{index:03}.wav", _wav48())
        archive.writestr(f"{track}/enrol/reference.wav", _wav48())
        archive.writestr(
            f"{track}/transcripts/v5_devset_transcripts_track2.tsv",
            "clip\ttext\n",
        )
    return path.read_bytes()


def test_dns5_preparation_keeps_only_test_track_and_verifies_cache(tmp_path, monkeypatch):
    archive = tmp_path / "dns5-fixture.zip"
    payload = _dns5_archive(archive)
    expected_md5 = base64.b64encode(hashlib.md5(payload).digest()).decode("ascii")
    monkeypatch.setattr(dns5, "EXPECTED_ETAG", "fixture-etag")
    monkeypatch.setattr(dns5, "EXPECTED_ARCHIVE_BYTES", len(payload))
    monkeypatch.setattr(dns5, "EXPECTED_CONTENT_MD5", expected_md5)
    monkeypatch.setattr(dns5, "MAX_ARCHIVE_BYTES", len(payload))
    status = tmp_path / "dns5-status.json"
    status.write_text(json.dumps({"status": "enabled_for_evaluation", "evaluation": "allowed"}))
    monkeypatch.setattr(dns5, "STATUS", status)

    cache = tmp_path / "cache"
    prepared = dns5.fetch(cache, archive_file=archive)
    manifest = json.loads((prepared / "manifest.json").read_text())
    wav_paths = [item["path"] for item in manifest["files"] if item["path"].endswith(".wav")]

    assert len(wav_paths) == 600
    assert all("/enrol/" not in path for path in wav_paths)
    assert any(path.endswith("v5_devset_transcripts_track2.tsv") for path in (item["path"] for item in manifest["files"]))
    assert dns5._verified_cache(prepared)
    assert dns5.fetch(cache, offline=True) == prepared

    (prepared / wav_paths[0]).write_bytes(b"tampered")
    assert not dns5._verified_cache(prepared)
    with pytest.raises(AcquisitionError, match="offline mode"):
        dns5.fetch(cache, offline=True)


def test_dns5_rights_gate_fails_closed_before_archive_use(tmp_path, monkeypatch):
    status = tmp_path / "dns5-status.json"
    status.write_text(json.dumps({"status": "blocked", "evaluation": "unknown"}))
    monkeypatch.setattr(dns5, "STATUS", status)
    with pytest.raises(AcquisitionError, match="disabled"):
        dns5.fetch(tmp_path / "cache", archive_file=tmp_path / "missing.zip")


def test_dns5_member_path_rejects_traversal():
    with pytest.raises(AcquisitionError, match="unsafe"):
        dns5._safe_path("V5_dev_testset/../../outside.wav")
