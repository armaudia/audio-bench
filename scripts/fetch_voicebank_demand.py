#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Fetch and verify the official VoiceBank+DEMAND paired test cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from audio_bench.acquire import (  # noqa: E402
    ExtractionLimits,
    HTTPSFetcher,
    SourcePolicy,
    acquire,
    extract_archive,
)
from audio_bench.errors import AcquisitionError  # noqa: E402

DATASET = ROOT / "manifests/voicebank-demand/voicebank-demand-test-v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _load_cases() -> list[dict]:
    manifest = DATASET / "cases-0000.jsonl"
    provenance = json.loads((DATASET / "provenance.json").read_text(encoding="utf-8"))
    if provenance.get("schema_id") != "audio-bench/paired-corpus-provenance/0.1":
        raise AcquisitionError("unsupported paired corpus provenance schema")
    if _sha256(manifest) != provenance.get("case_manifest_sha256"):
        raise AcquisitionError("paired corpus case manifest digest mismatch")
    cases = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line]
    if len(cases) != 824 or len({case["case_id"] for case in cases}) != len(cases):
        raise AcquisitionError("VoiceBank+DEMAND cohort case inventory is not the pinned 824 unique cases")
    for case in cases:
        if not re.fullmatch(r"p[0-9]{3}_[0-9]{3}", case.get("case_id", "")) or case.get("speaker_id") != case["case_id"].split("_")[0]:
            raise AcquisitionError("invalid VoiceBank+DEMAND case identity")
        if case.get("channels") != 1 or case.get("sample_rate_hz") != 48000 or case.get("sample_count", 0) < 1:
            raise AcquisitionError(f"invalid paired audio format for {case['case_id']}")
        for role, prefix in (("clean", "clean_testset_wav"), ("noisy", "noisy_testset_wav")):
            item = case.get(role, {})
            member = PurePosixPath(item.get("archive_member", ""))
            if member.is_absolute() or ".." in member.parts or member.parts[0] != prefix or not member.name.endswith(".wav"):
                raise AcquisitionError(f"invalid {role} archive member for {case['case_id']}")
            if item.get("bytes", 0) < 1 or not re.fullmatch(r"sha256:[0-9a-f]{64}", item.get("sha256", "")):
                raise AcquisitionError(f"invalid {role} digest record for {case['case_id']}")
    return cases


def fetch_and_verify(cache_root: Path, *, archive_dir: Path | None = None, offline: bool = False) -> Path:
    provenance = json.loads((DATASET / "provenance.json").read_text(encoding="utf-8"))
    cases = _load_cases()
    dataset_root = cache_root / "voicebank-demand-test-v1"
    archives_dir = dataset_root / "archives"
    archives_dir.mkdir(parents=True, exist_ok=True)
    extraction_dirs: dict[str, Path] = {}
    policy = SourcePolicy(allowed_hosts=frozenset({"datashare.ed.ac.uk"}))

    for asset in provenance["archives"]:
        archive = archives_dir / asset["filename"]
        local = archive_dir / asset["filename"] if archive_dir else None
        if local and local.is_file():
            if local.stat().st_size != asset["bytes"] or _sha256(local) != asset["sha256"]:
                raise AcquisitionError(f"local archive does not match the pinned asset: {local}")
            if local.resolve() != archive.resolve():
                shutil.copyfile(local, archive)
        elif archive.is_file() and archive.stat().st_size == asset["bytes"] and _sha256(archive) == asset["sha256"]:
            pass
        elif offline:
            raise AcquisitionError(f"offline mode: pinned archive is not cached: {asset['filename']}")
        else:
            archive.unlink(missing_ok=True)
            acquire(
                asset["url"], archive,
                expected_sha256=asset["sha256"], expected_bytes=asset["bytes"],
                policy=policy, fetcher=HTTPSFetcher(), max_bytes=asset["bytes"],
            )

        extraction = dataset_root / asset["id"]
        expected_members = {
            item["archive_member"]
            for case in cases
            for role in ("clean", "noisy")
            if ((role == "clean") == asset["id"].startswith("clean"))
            for item in (case[role],)
        }
        if not extraction.is_dir():
            extracted = extract_archive(
                archive, extraction,
                limits=ExtractionLimits(max_bytes=1024 * 1024 * 1024, max_files=1000,
                                        max_depth=4, allowed_suffixes=(".wav",)),
            )
            if set(extracted) != expected_members:
                shutil.rmtree(extraction, ignore_errors=True)
                raise AcquisitionError(f"archive member inventory differs from the pinned cohort: {asset['filename']}")
        else:
            observed = {
                path.relative_to(extraction).as_posix()
                for path in extraction.rglob("*") if path.is_file()
            }
            if observed != expected_members:
                raise AcquisitionError(f"cached extraction inventory differs from pinned cohort: {asset['filename']}")
        extraction_dirs[asset["id"]] = extraction

    for case in cases:
        for role in ("clean", "noisy"):
            item = case[role]
            archive_id = "clean_testset_wav" if role == "clean" else "noisy_testset_wav"
            relative = PurePosixPath(item["archive_member"])
            if relative.is_absolute() or ".." in relative.parts:
                raise AcquisitionError(f"unsafe archive member in corpus manifest: {relative}")
            path = extraction_dirs[archive_id] / Path(*relative.parts)
            if not path.is_file() or path.stat().st_size != item["bytes"] or _sha256(path) != item["sha256"]:
                raise AcquisitionError(f"corpus member failed its byte/hash check: {case['case_id']} {role}")
    return dataset_root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, help="external data cache (defaults to ~/.cache/audio-bench/datasets)")
    parser.add_argument("--archive-dir", type=Path, help="use already downloaded archives after checking their hashes")
    parser.add_argument("--offline", action="store_true", help="refuse network if an archive is absent from the cache")
    args = parser.parse_args()
    cache = args.cache or Path(os.environ.get("AUDIO_BENCH_DATA_CACHE", Path.home() / ".cache/audio-bench/datasets"))
    try:
        path = fetch_and_verify(cache, archive_dir=args.archive_dir, offline=args.offline)
    except (AcquisitionError, OSError, ValueError, KeyError) as exc:
        raise SystemExit(f"VoiceBank+DEMAND acquisition failed: {exc}") from exc
    print(f"verified 824 clean/noisy pairs in external cache: {path}")


if __name__ == "__main__":
    main()
