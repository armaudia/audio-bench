#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Fetch and hash-cache the DNS5 speakerphone development cohort outside Git."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
import wave
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from audio_bench import canonical  # noqa: E402
from audio_bench.errors import AcquisitionError  # noqa: E402

URL = "https://dnschallengepublic.blob.core.windows.net/dns5archive/V5_dev_testset.zip"
DATASET_ID = "dns5-speakerphone-dev-v1"
STATUS = ROOT / "manifests/dns5.status.json"
EXPECTED_ETAG = "0x8DAD8BE02A959DB"
EXPECTED_ARCHIVE_BYTES = 3236752796
EXPECTED_CONTENT_MD5 = "dqoc3aJKECCYaU+rzFfODQ=="
MAX_ARCHIVE_BYTES = EXPECTED_ARCHIVE_BYTES
MAX_EXTRACTED_BYTES = 5 * 1024**3
MAX_MEMBERS = 20_000


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _safe_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise AcquisitionError(f"unsafe DNS5 archive member: {value!r}")
    return PurePosixPath(*(part for part in path.parts if part not in ("", ".")))


def _verified_cache(destination: Path) -> bool:
    path = destination / "manifest.json"
    if not path.is_file():
        return False
    try:
        manifest = canonical.require_canonical(path.read_bytes(), path=str(path))
        source = manifest.get("source", {})
        if (manifest.get("dataset_id") != DATASET_ID
                or source.get("archive_etag") != EXPECTED_ETAG
                or source.get("archive_bytes") != EXPECTED_ARCHIVE_BYTES
                or source.get("archive_content_md5_base64") != EXPECTED_CONTENT_MD5
                or manifest.get("counts", {}).get("audio_files") != 600):
            return False
        observed_paths = set()
        for item in manifest["files"]:
            relative = _safe_path(item["path"])
            if relative.as_posix() in observed_paths:
                return False
            observed_paths.add(relative.as_posix())
            file_path = destination / relative
            if destination.resolve() not in file_path.resolve().parents:
                return False
            if any(
                parent.is_symlink()
                for parent in (file_path, *file_path.parents)
                if parent == file_path or destination in parent.parents
            ):
                return False
            if not file_path.is_file() or file_path.stat().st_size != item["bytes"] or _sha(file_path) != item["sha256"]:
                return False
        return (manifest["counts"]["audio_files"] == 600
                and "V5_dev_testset/Track2_Speakerphone/transcripts/v5_devset_transcripts_track2.tsv" in observed_paths)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _publish_cache(staging: Path, destination: Path) -> None:
    backup = destination.with_name(f".{destination.name}-previous-{uuid.uuid4().hex}")
    moved_old = False
    if destination.exists():
        if destination.is_symlink():
            raise AcquisitionError("refusing to replace a symlinked DNS5 cache")
        os.replace(destination, backup)
        moved_old = True
    try:
        os.replace(staging, destination)
    except Exception:
        if moved_old:
            os.replace(backup, destination)
        raise
    if moved_old:
        shutil.rmtree(backup)


def _download(archive_path: Path) -> tuple[str, int, str]:
    head = urllib.request.Request(URL, method="HEAD")
    with urllib.request.urlopen(head, timeout=30) as response:
        etag = response.headers.get("ETag", "").strip('"')
        length = int(response.headers.get("Content-Length", "0"))
        content_md5 = response.headers.get("Content-MD5", "")
    if (etag != EXPECTED_ETAG or length != EXPECTED_ARCHIVE_BYTES
            or content_md5 != EXPECTED_CONTENT_MD5):
        raise AcquisitionError("DNS5 source identity differs from the reviewed ETag, size, or Content-MD5 pin")
    request = urllib.request.Request(URL)
    digest = hashlib.sha256()
    md5_digest = hashlib.md5()
    received = 0
    with urllib.request.urlopen(request, timeout=60) as response, archive_path.open("wb") as target:
        if (response.headers.get("ETag", "").strip('"') != etag
                or int(response.headers.get("Content-Length", "0")) != length
                or response.headers.get("Content-MD5", "") != content_md5):
            raise AcquisitionError("DNS5 archive changed between HEAD and GET")
        while chunk := response.read(1024 * 1024):
            received += len(chunk)
            if received > length or received > MAX_ARCHIVE_BYTES:
                raise AcquisitionError("DNS5 source exceeded its declared download size")
            digest.update(chunk)
            md5_digest.update(chunk)
            target.write(chunk)
    if received != length:
        raise AcquisitionError("DNS5 archive download was truncated")
    if base64.b64encode(md5_digest.digest()).decode("ascii") != EXPECTED_CONTENT_MD5:
        raise AcquisitionError("DNS5 archive failed the pinned Content-MD5 check")
    return "sha256:" + digest.hexdigest(), length, etag


def _current_etag() -> str:
    request = urllib.request.Request(URL, method="HEAD")
    with urllib.request.urlopen(request, timeout=30) as response:
        etag = response.headers.get("ETag", "").strip('"')
        size = int(response.headers.get("Content-Length", "0"))
        md5 = response.headers.get("Content-MD5", "")
    if (etag != EXPECTED_ETAG or size != EXPECTED_ARCHIVE_BYTES or md5 != EXPECTED_CONTENT_MD5):
        raise AcquisitionError("DNS5 source no longer matches the reviewed archive identity")
    return etag


def _verify_local_archive(archive_path: Path) -> tuple[str, int, str]:
    size = archive_path.stat().st_size
    if size != EXPECTED_ARCHIVE_BYTES:
        raise AcquisitionError("local DNS5 archive size differs from the pinned source size")
    sha256 = hashlib.sha256()
    md5 = hashlib.md5()
    with archive_path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            sha256.update(chunk)
            md5.update(chunk)
    if base64.b64encode(md5.digest()).decode("ascii") != EXPECTED_CONTENT_MD5:
        raise AcquisitionError("local DNS5 archive differs from the pinned Content-MD5")
    return "sha256:" + sha256.hexdigest(), size, EXPECTED_ETAG


def fetch(cache_root: Path, *, offline: bool = False, archive_file: Path | None = None) -> Path:
    status = json.loads(STATUS.read_text(encoding="utf-8"))
    if status.get("status") != "enabled_for_evaluation" or status.get("evaluation") != "allowed":
        raise AcquisitionError("DNS5 acquisition is disabled by manifests/dns5.status.json")
    destination = cache_root / DATASET_ID
    if archive_file is not None and offline:
        raise AcquisitionError("--archive and --offline cannot be combined")
    if _verified_cache(destination) and archive_file is None:
        if offline:
            return destination
        manifest = canonical.require_canonical((destination / "manifest.json").read_bytes())
        if manifest.get("source", {}).get("archive_etag") == _current_etag():
            return destination
    if offline:
        raise AcquisitionError("offline mode: no verified DNS5 development cohort cache is available")
    if destination.is_symlink():
        raise AcquisitionError("refusing to replace a symlinked DNS5 cache")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".dns5-dev-", dir=destination.parent))
    with tempfile.TemporaryDirectory(prefix=".dns5-archive-", dir=destination.parent) as temporary:
        archive_path = archive_file.resolve(strict=True) if archive_file else Path(temporary) / "V5_dev_testset.zip"
        try:
            if archive_file is not None:
                archive_sha, archive_bytes, archive_etag = _verify_local_archive(archive_path)
            else:
                archive_sha, archive_bytes, archive_etag = _download(archive_path)
            files: list[dict] = []
            audio_count = 0
            total = 0
            with zipfile.ZipFile(archive_path) as archive:
                members = archive.infolist()
                if len(members) > MAX_MEMBERS:
                    raise AcquisitionError("DNS5 archive contains too many members")
                names: set[str] = set()
                for member in members:
                    relative = _safe_path(member.filename)
                    if member.is_dir():
                        continue
                    if relative.as_posix() in names:
                        raise AcquisitionError(f"duplicate DNS5 archive member: {member.filename}")
                    names.add(relative.as_posix())
                    mode = member.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        raise AcquisitionError(f"DNS5 archive contains a symlink: {member.filename}")
                    track_parts = [part.lower() for part in relative.parts]
                    if track_parts[:2] != ["v5_dev_testset", "track2_speakerphone"]:
                        continue
                    if relative.suffix.lower() == ".wav" and (len(track_parts) < 3 or track_parts[2] != "noisy"):
                        continue
                    suffix = relative.suffix.lower()
                    if suffix not in {".wav", ".txt", ".tsv", ".csv", ".json"} or "enrol" in "/".join(track_parts):
                        continue
                    if member.file_size < 1 or member.file_size > 100 * 1024 * 1024:
                        raise AcquisitionError(f"unexpected DNS5 test member size: {member.filename}")
                    total += member.file_size
                    if total > MAX_EXTRACTED_BYTES:
                        raise AcquisitionError("selected DNS5 development data exceeds 5 GiB")
                    output = staging / relative
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, output.open("xb") as target:
                        shutil.copyfileobj(source, target, 1024 * 1024)
                    if output.stat().st_size != member.file_size:
                        raise AcquisitionError(f"truncated DNS5 test member: {member.filename}")
                    if suffix == ".wav":
                        with wave.open(str(output), "rb") as audio:
                            if audio.getframerate() != 48000 or audio.getnchannels() != 1 or audio.getsampwidth() != 2:
                                raise AcquisitionError(f"unexpected DNS5 audio format: {member.filename}")
                        audio_count += 1
                    files.append({"path": relative.as_posix(), "bytes": member.file_size, "sha256": _sha(output)})
            transcript_path = "V5_dev_testset/Track2_Speakerphone/transcripts/v5_devset_transcripts_track2.tsv"
            transcript_files = [item["path"] for item in files if item["path"] == transcript_path]
            if audio_count != 600 or len(transcript_files) != 1:
                raise AcquisitionError(f"DNS5 archive did not contain the pinned 600-clip speakerphone dev cohort ({audio_count} WAVs)")
            files.sort(key=lambda item: item["path"])
            manifest = {
                "schema_id": "audio-bench/dns-cohort/1.0",
                "dataset_id": DATASET_ID,
                "source": {
                    "url": URL,
                    "release": "DNS Challenge 5 / ICASSP 2023 development test set",
                    "track": "speakerphone",
                    "archive_etag": archive_etag,
                    "archive_bytes": archive_bytes,
                    "archive_sha256": archive_sha,
                    "archive_content_md5_base64": EXPECTED_CONTENT_MD5,
                },
                "metric_track": "non_intrusive_quality_and_word_accuracy",
                "paired_clean_reference": False,
                "files": files,
                "counts": {"audio_files": audio_count, "total_files": len(files), "bytes": total},
                "license": {
                    "source_terms": "original component terms; maintainer-approved evaluation and aggregate reporting",
                    "status_ref": "manifests/dns5.status.json",
                    "public_playback": "not_enabled",
                },
            }
            (staging / "manifest.json").write_bytes(canonical.dumps(manifest))
            _publish_cache(staging, destination)
            return destination
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, help="external cache (defaults to ~/.cache/audio-bench/datasets)")
    parser.add_argument("--offline", action="store_true", help="require a verified local cache")
    parser.add_argument("--archive", type=Path, help="use a local copy of the exact pinned source archive")
    args = parser.parse_args()
    cache = args.cache or Path(os.environ.get("AUDIO_BENCH_DATA_CACHE", Path.home() / ".cache/audio-bench/datasets"))
    try:
        path = fetch(cache, offline=args.offline, archive_file=args.archive)
    except (AcquisitionError, OSError, ValueError, KeyError, zipfile.BadZipFile, urllib.error.URLError) as exc:
        raise SystemExit(f"DNS5 cohort acquisition failed: {exc}") from exc
    manifest = canonical.require_canonical((path / "manifest.json").read_bytes())
    print(f"verified {manifest['counts']['audio_files']} DNS5 speakerphone clips in {path}")
    print(f"cohort manifest digest: {canonical.digest_of(manifest)}")


if __name__ == "__main__":
    main()
