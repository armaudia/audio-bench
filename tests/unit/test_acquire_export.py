# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
import hashlib
import os
import zipfile

import pytest

from audio_bench.acquire import FetchResult, SourcePolicy, acquire, validate_url
from audio_bench.acquire import ExtractionLimits, extract_archive
from audio_bench.errors import AcquisitionError, BlockedError, ValidationError
from audio_bench.export import ExportPolicy, _enumerate


def test_safe_zip_extracts_and_refuses_traversal(tmp_path):
    good = tmp_path / "good.zip"
    with zipfile.ZipFile(good, "w") as bundle:
        bundle.writestr("audio/test.wav", b"fake")
    out = tmp_path / "out"
    assert extract_archive(good, out) == ["audio/test.wav"]

    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as bundle:
        bundle.writestr("../escape.wav", b"bad")
    with pytest.raises(AcquisitionError, match="traversal"):
        extract_archive(bad, tmp_path / "bad-out")
    assert not (tmp_path / "escape.wav").exists()


def test_safe_zip_refuses_duplicate_and_symlink(tmp_path):
    duplicate = tmp_path / "duplicate.zip"
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(duplicate, "w") as bundle:
            bundle.writestr("a.wav", b"one")
            bundle.writestr("a.wav", b"two")
    with pytest.raises(AcquisitionError, match="duplicate"):
        extract_archive(duplicate, tmp_path / "duplicate-out")


def test_export_source_rejects_link_hardlink_and_undeclared(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "evil.js").write_text("alert(1)")
    with pytest.raises(ValidationError):
        _enumerate(source, ExportPolicy())
    (source / "evil.js").unlink()
    target = source / "core.json"
    target.write_text("{}")
    link = source / "alias.json"
    try:
        os.link(target, link)
    except OSError:
        pytest.skip("hard links unavailable")
    with pytest.raises(ValidationError, match="hard link"):
        _enumerate(source, ExportPolicy(exportable_names=frozenset({"core.json", "alias.json"})))


def test_export_blocks_png_without_trusted_reencoder(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "preview.png").write_bytes(b"png")
    with pytest.raises((ValidationError, BlockedError)):
        _enumerate(source, ExportPolicy())


def test_https_acquire_is_bounded_resumable_and_hash_verified(tmp_path):
    content = (b"audio-bench-test-data" * 250_000)[:5_100_000]
    policy = SourcePolicy(frozenset({"assets.example.test"}))
    requests = []

    def fake_fetch(url, *, offset, max_bytes):
        requests.append((url, offset, max_bytes))
        chunk = content[offset : offset + max_bytes]
        return FetchResult(
            url,
            206,
            chunk,
            range_start=offset,
        )

    target = tmp_path / "asset.bin"
    result = acquire(
        "https://assets.example.test/archive.bin",
        target,
        expected_sha256="sha256:" + hashlib.sha256(content).hexdigest(),
        expected_bytes=len(content),
        policy=policy,
        fetcher=fake_fetch,
        resolver=lambda _host: ["93.184.216.34"],
    )
    assert result.read_bytes() == content
    assert len(requests) == 2
    assert all(size <= 4 * 1024 * 1024 for _url, _offset, size in requests)


def test_https_acquire_supports_one_bounded_request_for_known_archive(tmp_path):
    content = b"known-size-dataset-archive" * 500_000
    policy = SourcePolicy(frozenset({"assets.example.test"}))
    requests = []

    def fake_fetch(url, *, offset, max_bytes):
        requests.append((offset, max_bytes))
        return FetchResult(url, 206, content[offset:offset + max_bytes], range_start=offset)

    target = tmp_path / "archive.bin"
    result = acquire(
        "https://assets.example.test/archive.bin",
        target,
        expected_sha256="sha256:" + hashlib.sha256(content).hexdigest(),
        expected_bytes=len(content),
        policy=policy,
        fetcher=fake_fetch,
        max_bytes=len(content),
        chunk_size=len(content),
        resolver=lambda _host: ["93.184.216.34"],
    )
    assert result.read_bytes() == content
    assert requests == [(0, len(content))]


def test_url_policy_rejects_credentials_private_addresses_and_redirect_escape(tmp_path):
    policy = SourcePolicy(frozenset({"assets.example.test"}))
    with pytest.raises(AcquisitionError, match="credentials"):
        validate_url("https://user:secret@assets.example.test/a", policy, resolver=lambda _h: ["93.184.216.34"])
    with pytest.raises(AcquisitionError, match="non-public"):
        validate_url("https://assets.example.test/a", policy, resolver=lambda _h: ["127.0.0.1"])

    def redirect(url, *, offset, max_bytes):
        return FetchResult(url, 302, b"", "https://127.0.0.1/private")

    with pytest.raises(AcquisitionError, match="allowlist"):
        acquire(
            "https://assets.example.test/archive",
            tmp_path / "redirected-asset",
            expected_sha256="sha256:" + "0" * 64,
            expected_bytes=10,
            policy=policy,
            fetcher=redirect,
            resolver=lambda _host: ["93.184.216.34"],
        )
