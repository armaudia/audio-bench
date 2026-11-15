# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0

import hashlib
from pathlib import Path

import pytest

from audio_bench import canonical
from audio_bench.errors import AcquisitionError, ValidationError
from audio_bench.external_dataset import fetch_external_dataset, validate_external_manifest


def manifest_for(payload: bytes = b"dataset bytes"):
    return {
        "schema_id": "audio-bench/external-dataset/0.1",
        "dataset_id": "sample-noise-corpus-v1",
        "version": "v1",
        "license": {"spdx_id": "CC-BY-4.0", "source_url": "https://example.org/license", "attribution": "Dataset authors"},
        "allowed_hosts": ["example.org"],
        "files": [{
            "path": "audio/case-1.noisy.wav", "url": "https://example.org/case-1.wav",
            "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(), "bytes": len(payload),
            "case_id": "case-1", "role": "noisy",
        }],
    }


class FakeFetcher:
    def __init__(self, body: bytes):
        self.body = body
        self.calls = 0

    def __call__(self, url: str, *, offset: int, max_bytes: int):
        from audio_bench.acquire import FetchResult
        self.calls += 1
        return FetchResult(url, 200, self.body)


def save_manifest(tmp_path: Path, payload: bytes = b"dataset bytes") -> Path:
    path = tmp_path / "manifest.json"
    path.write_bytes(canonical.dumps(manifest_for(payload)))
    return path


def test_fetch_caches_verified_assets_outside_repository(tmp_path):
    manifest = save_manifest(tmp_path)
    fetcher = FakeFetcher(b"dataset bytes")
    cache = tmp_path / "external-cache"
    result = fetch_external_dataset(manifest, cache, fetcher=fetcher,
                                    resolver=lambda _: ["93.184.216.34"])
    asset = result / "audio/case-1.noisy.wav"
    assert asset.read_bytes() == b"dataset bytes"
    assert asset.is_relative_to(cache)
    fetch_external_dataset(manifest, cache, fetcher=fetcher,
                           resolver=lambda _: ["93.184.216.34"])
    assert fetcher.calls == 1


def test_fetch_rejects_hash_mismatch_and_does_not_publish_asset(tmp_path):
    manifest = save_manifest(tmp_path, b"expected")
    cache = tmp_path / "cache"
    with pytest.raises(AcquisitionError, match="digest mismatch"):
        fetch_external_dataset(manifest, cache, fetcher=FakeFetcher(b"mismatch"),
                               resolver=lambda _: ["93.184.216.34"])
    assert not list(cache.rglob("case-1.noisy.wav"))


def test_manifest_rejects_traversal_paths_and_unlisted_hosts():
    value = manifest_for()
    value["files"][0]["path"] = "audio/../secret.wav"
    with pytest.raises(ValidationError, match="unsafe"):
        validate_external_manifest(value)
    value = manifest_for()
    value["files"][0]["url"] = "https://unexpected.org/audio.wav"
    with pytest.raises(ValidationError, match="not allowlisted"):
        validate_external_manifest(value)
