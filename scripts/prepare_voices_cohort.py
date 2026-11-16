#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Stream VOiCES devkit and materialize a balanced, audio-free-in-Git cohort cache.

The official archive is large, so this reads it as a gzip/tar stream and writes only the
selected clean references and noisy recordings to the external data cache.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import uuid
import wave
from collections import defaultdict
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from audio_bench import canonical  # noqa: E402
from audio_bench.errors import AcquisitionError  # noqa: E402

URL = "https://lab41openaudiocorpus.s3.amazonaws.com/VOiCES_devkit.tar.gz"
DATASET_ID = "voices-balanced-realroom-v1"
SELECTION = json.loads((ROOT / "manifests/voices/voices-balanced-realroom-v1/selection.json").read_text())
MAX_COMPRESSED_BYTES = 32 * 1024**3
MAX_SELECTED_BYTES = 1024 * 1024**3
WAV_NAME = re.compile(r"-mc[0-9]+-(?P<mic_type>[a-z]+)-(?P<mic_location>[a-z]+)-dg(?P<degrees>[0-9]+)\.wav$")


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _normal_member(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise AcquisitionError(f"unsafe VOiCES member path: {value!r}")
    return PurePosixPath(*(part for part in path.parts if part not in ("", "."))).as_posix()


def _matching_member(member: str, relative: str) -> bool:
    member = _normal_member(member)
    relative = _normal_member(relative)
    return member == relative or member.endswith("/" + relative)


def _eligible(row: dict[str, str]) -> bool:
    try:
        if int(row["degrees"]) != SELECTION["degrees"]:
            return False
        if row["room"] not in SELECTION["rooms"] or row["distractor"] not in SELECTION["distractors"]:
            return False
        filename = PurePosixPath(row["filename"]).name
        tags = WAV_NAME.search(filename)
        return bool(tags and tags.group("mic_type") == SELECTION["mic_type"]
                    and tags.group("mic_location") == SELECTION["mic_location"]
                    and int(tags.group("degrees")) == SELECTION["degrees"])
    except (KeyError, TypeError, ValueError):
        return False


def _select(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    by_speaker_source: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
    speaker_gender: dict[str, str] = {}
    for row in rows:
        if _eligible(row):
            source = _normal_member(row["source"])
            by_speaker_source[row["speaker"]][source].append(row)
            speaker_gender[row["speaker"]] = row["gender"]

    def spread(values: list[str], count: int) -> list[str]:
        if len(values) < count:
            raise AcquisitionError(f"VOiCES test index has {len(values)} eligible speakers; {count} are required")
        return [values[round(index * (len(values) - 1) / (count - 1))] for index in range(count)]

    eligible_by_gender = {
        gender: sorted((speaker for speaker in by_speaker_source if speaker_gender.get(speaker) == gender),
                       key=lambda value: int(value))
        for gender in SELECTION["speaker_balance"]
    }
    if sum(len(speakers) for speakers in eligible_by_gender.values()) < SELECTION["speakers"]:
        raise AcquisitionError("VOiCES test index has too few eligible independent speakers")
    speakers = sorted(
        [speaker for gender, count in SELECTION["speaker_balance"].items()
         for speaker in spread(eligible_by_gender[gender], count)],
        key=lambda value: int(value),
    )

    chosen: list[dict[str, str]] = []
    for speaker_index, speaker in enumerate(speakers):
        room = SELECTION["rooms"][speaker_index % len(SELECTION["rooms"])]
        for source in sorted(by_speaker_source[speaker]):
            records = by_speaker_source[speaker][source]
            room_records = [row for row in records if row["room"] == room]
            by_noise = {row["distractor"]: row for row in room_records}
            if all(noise in by_noise for noise in SELECTION["distractors"]):
                chosen.extend(by_noise[noise] for noise in SELECTION["distractors"])
                break
        else:
            raise AcquisitionError(f"speaker {speaker} has no complete four-condition source in {room}")

    identities = {(row["speaker"], row["source"], row["room"], row["distractor"]) for row in chosen}
    if len(identities) != SELECTION["speakers"] * SELECTION["cases_per_speaker"]:
        raise AcquisitionError("VOiCES selection contains duplicate or missing cases")
    return chosen


def _write_member(stream: tarfile.TarFile, member: tarfile.TarInfo, destination: Path) -> dict:
    if not member.isfile() or member.size < 1 or member.size > 100 * 1024 * 1024:
        raise AcquisitionError(f"unexpected selected VOiCES member type/size: {member.name}")
    source = stream.extractfile(member)
    if source is None:
        raise AcquisitionError(f"cannot read selected VOiCES member: {member.name}")
    payload = source.read(member.size + 1)
    if len(payload) != member.size:
        raise AcquisitionError(f"truncated VOiCES member: {member.name}")
    with wave.open(io.BytesIO(payload), "rb") as audio:
        fmt = {"sample_rate_hz": audio.getframerate(), "channels": audio.getnchannels(),
               "sample_count": audio.getnframes(), "sample_width_bytes": audio.getsampwidth()}
    if fmt["sample_rate_hz"] != 16000 or fmt["channels"] != 1 or fmt["sample_width_bytes"] != 2:
        raise AcquisitionError(f"unexpected VOiCES PCM format for {member.name}: {fmt}")
    destination.write_bytes(payload)
    return {"bytes": len(payload), "sha256": _sha(payload), **fmt}


def _head_source() -> tuple[str, int]:
    request = urllib.request.Request(URL, method="HEAD")
    with urllib.request.urlopen(request, timeout=30) as response:
        etag = response.headers.get("ETag", "").strip('"')
        length = int(response.headers.get("Content-Length", "0"))
    if not etag or not length or length > MAX_COMPRESSED_BYTES:
        raise AcquisitionError("VOiCES source lacks a usable ETag/size or exceeds the download cap")
    return etag, length


def _source() -> tuple[io.BufferedReader | object, str, int]:
    etag, length = _head_source()
    get_request = urllib.request.Request(URL)
    response = urllib.request.urlopen(get_request, timeout=60)
    if response.headers.get("ETag", "").strip('"') != etag:
        response.close()
        raise AcquisitionError("VOiCES source changed between HEAD and GET")
    if int(response.headers.get("Content-Length", "0")) != length:
        response.close()
        raise AcquisitionError("VOiCES source size changed between HEAD and GET")
    return response, etag, length


def _verify_cached(destination: Path) -> bool:
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        manifest = canonical.require_canonical(manifest_path.read_bytes(), path=str(manifest_path))
        if manifest.get("dataset_id") != DATASET_ID or manifest.get("selection") != SELECTION:
            return False
        for item in manifest["files"]:
            relative = PurePosixPath(_normal_member(item["path"]))
            path = destination / relative
            if destination.resolve() not in path.resolve().parents:
                return False
            if any(
                parent.is_symlink()
                for parent in (path, *path.parents)
                if parent == path or destination in parent.parents
            ):
                return False
            if not path.is_file() or path.stat().st_size != item["bytes"] or _file_sha(path) != item["sha256"]:
                return False
        return len(manifest["cases"]) == SELECTION["speakers"] * SELECTION["cases_per_speaker"]
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _publish_cache(staging: Path, destination: Path) -> None:
    backup = destination.with_name(f".{destination.name}-previous-{uuid.uuid4().hex}")
    moved_old = False
    if destination.exists():
        if destination.is_symlink():
            raise AcquisitionError("refusing to replace a symlinked VOiCES cache")
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


def prepare(cache_root: Path, *, archive: Path | None = None, offline: bool = False) -> Path:
    destination = cache_root / DATASET_ID
    if _verify_cached(destination):
        if offline:
            return destination
        current_etag, _ = _head_source()
        cached = canonical.require_canonical((destination / "manifest.json").read_bytes())
        if cached.get("source", {}).get("etag_or_archive_sha256") == current_etag:
            return destination
    if offline:
        raise AcquisitionError("offline mode: no verified VOiCES cohort cache is available")
    if destination.is_symlink():
        raise AcquisitionError("refusing to replace a symlinked VOiCES cache")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".voices-cohort-", dir=destination.parent))
    response = None
    source_handle = None
    try:
        if archive:
            source = archive.open("rb")
            source_handle = source
            etag, archive_bytes = _file_sha(archive), archive.stat().st_size
            archive_source = "local archive"
        else:
            source, etag, archive_bytes = _source()
            response = source
            archive_source = URL
        if archive_bytes > MAX_COMPRESSED_BYTES:
            raise AcquisitionError("VOiCES archive exceeds the compressed download cap")

        selected: list[dict[str, str]] | None = None
        desired: dict[str, tuple[str, dict[str, str]]] = {}
        selected_files: list[dict] = []
        case_records: list[dict] = []
        written = 0
        tar = tarfile.open(fileobj=source, mode="r|gz")
        for member in tar:
            member_path = _normal_member(member.name)
            if selected is None and member.isfile() and member_path.endswith("references/test_index.csv"):
                index_file = tar.extractfile(member)
                if index_file is None:
                    raise AcquisitionError("VOiCES archive contains an unreadable test_index.csv")
                index_bytes = index_file.read(64 * 1024 * 1024 + 1)
                if len(index_bytes) > 64 * 1024 * 1024:
                    raise AcquisitionError("VOiCES test index exceeds the 64 MiB safety limit")
                rows = list(csv.DictReader(io.StringIO(index_bytes.decode("utf-8-sig"), newline="")))
                selected = _select(rows)
                for row in selected:
                    speaker = str(int(row["speaker"]))
                    chapter = str(int(row["chapter"]))
                    segment = str(int(row["segment"]))
                    case_id = f"voices-sp{speaker}-ch{chapter}-sg{segment}-{row['room']}-{row['distractor']}"
                    row["_case_id"] = case_id
                    row["_clean_id"] = f"voices-sp{speaker}-ch{chapter}-sg{segment}"
                    desired[_normal_member(row["filename"])] = ("noisy", row)
                    desired.setdefault(_normal_member(row["source"]), ("clean", row))
                    case_records.append({
                        "case_id": case_id,
                        "speaker_id": speaker,
                        "source_path": _normal_member(row["source"]),
                        "noisy_path": _normal_member(row["filename"]),
                        "room": row["room"],
                        "distractor": row["distractor"],
                        "degrees": int(row["degrees"]),
                        "clean_file": f"audio/{row['_clean_id']}.clean.wav",
                        "noisy_file": f"audio/{case_id}.noisy.wav",
                    })
                continue
            if selected is None:
                continue
            matched = next((value for path, value in desired.items() if _matching_member(member_path, path)), None)
            if matched is None:
                continue
            role, row = matched
            case_id = row["_case_id"]
            output_name = f"{row['_clean_id']}.clean.wav" if role == "clean" else f"{case_id}.noisy.wav"
            output_path = staging / "audio" / output_name
            output_path.parent.mkdir(parents=True, exist_ok=True)
            info = _write_member(tar, member, output_path)
            written += info["bytes"]
            if written > MAX_SELECTED_BYTES:
                raise AcquisitionError("selected VOiCES cohort exceeds the extraction cap")
            selected_files.append({"path": f"audio/{output_name}", **info})
        tar.close()
        if selected is None or len(case_records) != SELECTION["speakers"] * SELECTION["cases_per_speaker"]:
            raise AcquisitionError(
                f"VOiCES archive did not contain all selected references and recordings "
                f"({len(case_records)} of {SELECTION['speakers'] * SELECTION['cases_per_speaker']})"
            )
        expected_paths = {
            f"audio/{item['_clean_id']}.clean.wav" for item in selected
        } | {
            f"audio/{item['_case_id']}.noisy.wav" for item in selected
        }
        if {item["path"] for item in selected_files} != expected_paths:
            raise AcquisitionError("VOiCES archive omitted a selected clean reference or noisy recording")
        source.close()
        if response is not None:
            response.close()
        case_records.sort(key=lambda item: item["case_id"])
        selected_files.sort(key=lambda item: item["path"])
        manifest = {
            "schema_id": "audio-bench/voices-cohort/1.0",
            "dataset_id": DATASET_ID,
            "selection": SELECTION,
            "source": {
                "url": archive_source,
                "version": "VOiCES devkit official test partition",
                "etag_or_archive_sha256": etag,
                "compressed_bytes": archive_bytes,
            },
            "license": {
                "name": "Creative Commons Attribution 4.0 International",
                "url": "https://creativecommons.org/licenses/by/4.0/",
                "attribution": "IQT Labs and SRI International, VOiCES corpus; source speech from LibriSpeech/OpenSLR",
                "public_playback": "not_enabled",
            },
            "cases": case_records,
            "files": selected_files,
        }
        (staging / "manifest.json").write_bytes(canonical.dumps(manifest))
        _publish_cache(staging, destination)
        return destination
    except Exception:
        if source_handle is not None:
            source_handle.close()
        if response is not None:
            response.close()
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, help="external cache (defaults to ~/.cache/audio-bench/datasets)")
    parser.add_argument("--archive", type=Path, help="use an already downloaded official devkit tar.gz")
    parser.add_argument("--offline", action="store_true", help="require an existing verified subset cache")
    args = parser.parse_args()
    cache = args.cache or Path(os.environ.get("AUDIO_BENCH_DATA_CACHE", Path.home() / ".cache/audio-bench/datasets"))
    try:
        path = prepare(cache, archive=args.archive, offline=args.offline)
    except (AcquisitionError, OSError, ValueError, KeyError, tarfile.TarError, urllib.error.URLError) as exc:
        raise SystemExit(f"VOiCES cohort preparation failed: {exc}") from exc
    manifest = canonical.require_canonical((path / "manifest.json").read_bytes())
    print(f"verified {len(manifest['cases'])} independent VOiCES speech/noise cases at {path}")
    print(f"cohort manifest digest: {canonical.digest_of(manifest)}")


if __name__ == "__main__":
    main()
