"""Safe public export: explicit allowlist, no link following, bounded reads.

Threat model (B08/TEST_PLAN B-T15): the exported directory is candidate-influenced. Therefore:

* every path is relative, NFC-normalized, ``..``-free, deduplicated after normalization, and
  enumerated with ``O_NOFOLLOW``/``follow_symlinks=False``;
* hard links (``st_nlink != 1``), devices, FIFOs, sockets, executables and archives are refused;
* content is bounded *before* parsing or decoding;
* JSON/JSONL must already be canonical; audio is decoded and length/channel checked;
* HTML/JS/SVG/PNG are not passed through: this exporter has no trusted PNG re-encoder, so PNG is
  reported as an unsupported capability instead of being trusted byte-for-byte;
* the destination is a fresh trusted directory and copied bytes are re-hashed;
* a public record is projected onto an explicit field allowlist, with absolute paths, private
  identifiers and non-canonical text refused.

Approval is a separate step: :func:`export_candidate` writes the exact candidate inventory,
then :func:`approve_export` binds that exact digest to a reviewer and time.
"""

from __future__ import annotations

import hashlib
import jsonschema
import os
import stat
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from . import audio, canonical
from .errors import AcquisitionError, BlockedError, ValidationError
from .ledger import PAYLOAD_NAMES, sha256_bytes
from .schemas import Validator

BUNDLE_MAX_BYTES = 2_000_000_000
MEDIA_MAX_BYTES = 100_000_000
RECORD_MAX_BYTES = 1024 * 1024
MAX_ENTRIES = 100_000
MAX_NESTING = 32
MAX_AUDIO_SECONDS = 30 * 60
MAX_AUDIO_CHANNELS = 2
MAX_JSONL_SHARD_BYTES = 100_000_000

#: Only these control/payload names may leave the private bundle at all.
EXPORTABLE_NAMES = frozenset({*PAYLOAD_NAMES, "core.json", "run.json", "inventory.json", "source-map.json"})

PUBLIC_PROJECTIONS: dict[str, frozenset[str]] = {
    "observation": frozenset({
        "schema_id", "run_id", "attempt_id", "configuration_id", "comparison_cohort_id",
        "case_id", "metric_id", "metric_revision", "execution_status", "reason", "value",
        "unit", "direction", "numerator", "denominator", "valid_interval.start_sample",
        "valid_interval.end_sample", "valid_interval.sample_rate_hz", "output_pcm_digest",
    }),
    "output": frozenset({
        "schema_id", "attempt_id", "case_id", "configuration_id", "mode", "workload_id",
        "native_container_sha", "decoded_pcm_sha", "format.container", "format.subtype",
        "format.sample_rate_hz", "format.channels", "sample_count", "source_map_digest",
        "source_input_digest", "sdk_config_digest", "preview.recipe", "preview.digest",
    }),
    "run": frozenset({
        "schema_id", "run_id", "attempt_id", "configuration_id", "comparison_cohort_id",
        "provider_digest", "status", "reason", "started_at", "ended_at", "collector_version",
    }),
    "summary": frozenset({
        "schema_id", "attempt_status", "complete", "expected_case_metric_count",
        "delivered_case_metric_count", "missing", "extra", "duplicates", "mean", "median",
        "min", "max", "finite_count", "undefined_reasons", "passed", "failed", "blocked",
        "invalid", "not_applicable", "not_run", "label",
    }),
}

PUBLIC_REQUIRED = {
    "observation": ("schema_id", "configuration_id", "comparison_cohort_id", "case_id", "metric_id", "execution_status"),
    "output": ("schema_id", "case_id", "configuration_id", "decoded_pcm_sha", "sample_count", "format", "sdk_config_digest"),
    "run": ("schema_id", "run_id", "attempt_id", "configuration_id", "status"),
    "summary": ("schema_id",),
}

_DIGEST = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
_ID = {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[a-z0-9][a-z0-9._-]*$"}
_NULLABLE_DIGEST = {"oneOf": [_DIGEST, {"type": "null"}]}
_NULLABLE_TEXT = {"oneOf": [{"type": "string", "maxLength": 2000}, {"type": "null"}]}

PUBLIC_RECORD_SCHEMAS = {
    "observation": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object", "additionalProperties": False,
        "required": list(PUBLIC_REQUIRED["observation"]),
        "properties": {
            "schema_id": {"const": "audio-bench/public-observation/0.1"},
            "run_id": {"type": "string", "format": "uuid"},
            "attempt_id": {"type": "string", "format": "uuid"},
            "configuration_id": dict(_DIGEST),
            "comparison_cohort_id": dict(_DIGEST),
            "case_id": dict(_ID), "metric_id": dict(_ID), "metric_revision": dict(_ID),
            "execution_status": {"enum": ["passed", "failed", "blocked", "invalid", "not_applicable", "not_run"]},
            "reason": _NULLABLE_TEXT,
            "value": {"oneOf": [{"type": "number"}, {"type": "null"}]},
            "unit": {"enum": ["dB", "ratio", "count", "index", "none"]},
            "direction": {"enum": ["higher", "lower", "diagnostic"]},
            "numerator": {"oneOf": [{"type": "string", "pattern": "^(0|[1-9][0-9]*)$"}, {"type": "null"}]},
            "denominator": {"oneOf": [{"type": "string", "pattern": "^(0|[1-9][0-9]*)$"}, {"type": "null"}]},
            "valid_interval": {"oneOf": [{
                "type": "object", "additionalProperties": False,
                "required": ["start_sample", "end_sample", "sample_rate_hz"],
                "properties": {
                    "start_sample": {"type": "string", "pattern": "^(0|-?[1-9][0-9]*)$"},
                    "end_sample": {"type": "string", "pattern": "^(0|-?[1-9][0-9]*)$"},
                    "sample_rate_hz": {"const": 16000},
                },
            }, {"type": "null"}]},
            "output_pcm_digest": _NULLABLE_DIGEST,
        },
    },
    "output": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object", "additionalProperties": False,
        "required": list(PUBLIC_REQUIRED["output"]),
        "properties": {
            "schema_id": {"const": "audio-bench/public-output/0.1"},
            "attempt_id": {"type": "string", "format": "uuid"},
            "case_id": dict(_ID), "configuration_id": dict(_DIGEST),
            "mode": {"enum": ["sequential", "paced"]},
            "workload_id": {"oneOf": [dict(_ID), {"type": "null"}]},
            "native_container_sha": dict(_DIGEST), "decoded_pcm_sha": dict(_DIGEST),
            "format": {
                "type": "object", "additionalProperties": False,
                "required": ["container", "subtype", "sample_rate_hz", "channels"],
                "properties": {
                    "container": {"const": "wav"}, "subtype": {"enum": ["FLOAT", "PCM_16"]},
                    "sample_rate_hz": {"const": 16000}, "channels": {"const": 1},
                },
            },
            "sample_count": {"type": "string", "pattern": "^(0|[1-9][0-9]*)$"},
            "source_map_digest": _NULLABLE_DIGEST,
            "source_input_digest": dict(_DIGEST), "sdk_config_digest": dict(_DIGEST),
            "preview": {"oneOf": [{
                "type": "object", "additionalProperties": False, "required": ["recipe", "digest"],
                "properties": {"recipe": {"type": "string", "maxLength": 2000}, "digest": dict(_DIGEST)},
            }, {"type": "null"}]},
        },
    },
    "run": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object", "additionalProperties": False,
        "required": list(PUBLIC_REQUIRED["run"]),
        "properties": {
            "schema_id": {"const": "audio-bench/public-run/0.1"},
            "run_id": {"type": "string", "format": "uuid"},
            "attempt_id": {"type": "string", "format": "uuid"},
            "configuration_id": dict(_DIGEST), "comparison_cohort_id": dict(_DIGEST),
            "provider_digest": _NULLABLE_DIGEST,
            "status": {"enum": ["passed", "failed", "blocked", "invalid", "not_applicable", "not_run"]},
            "reason": _NULLABLE_TEXT,
            "started_at": {"type": "string", "format": "date-time"},
            "ended_at": {"type": "string", "format": "date-time"},
            "collector_version": {"type": "string", "maxLength": 2000},
        },
    },
    "summary": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object", "additionalProperties": False,
        "required": list(PUBLIC_REQUIRED["summary"]),
        "properties": {
            "schema_id": {"const": "audio-bench/public-summary/0.1"},
            "attempt_status": {"enum": ["passed", "failed", "blocked", "invalid", "not_applicable", "not_run"]},
            "complete": {"type": "boolean"},
            "expected_case_metric_count": {"type": "string", "pattern": "^(0|[1-9][0-9]*)$"},
            "delivered_case_metric_count": {"type": "string", "pattern": "^(0|[1-9][0-9]*)$"},
            "missing": {"type": "array", "items": {"type": "string", "maxLength": 512}},
            "extra": {"type": "array", "items": {"type": "string", "maxLength": 512}},
            "duplicates": {"type": "array", "items": {"type": "string", "maxLength": 512}},
            "mean": {"type": "number"}, "median": {"type": "number"},
            "min": {"type": "number"}, "max": {"type": "number"},
            "finite_count": {"type": "integer", "minimum": 0},
            "undefined_reasons": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0}},
            **{status: {"type": "integer", "minimum": 0}
               for status in ("passed", "failed", "blocked", "invalid", "not_applicable", "not_run")},
            "label": {"type": "string", "maxLength": 2000},
        },
    },
}
PUBLIC_INVENTORY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_id", "files", "actual_artifact_set_id"],
    "properties": {
        "schema_id": {"const": "audio-bench/public-inventory/0.1"},
        "files": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["path", "media_type", "bytes", "sha256"],
                "properties": {
                    "path": {"type": "string", "minLength": 1, "maxLength": 1024,
                             "pattern": "^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$"},
                    "media_type": {"enum": ["application/json", "application/jsonl", "audio/wav"]},
                    "bytes": {"type": "string", "pattern": "^(0|[1-9][0-9]*)$"},
                    "sha256": dict(_DIGEST),
                },
            },
        },
        "actual_artifact_set_id": dict(_DIGEST),
    },
}
PUBLIC_CORE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_id", "identity_algorithm", "inventory_digest", "payload_digest", "core_digest"],
    "properties": {
        "schema_id": {"const": "audio-bench/public-core/0.1"},
        "identity_algorithm": {"const": canonical.JCS_IDENTITY_ALGORITHM},
        "inventory_digest": {"type": "string"},
        "payload_digest": {"type": "string"},
        "core_digest": {"type": "string"},
    },
}


def _record_type(record: Mapping[str, Any]) -> str:
    schema_id = record.get("schema_id")
    parts = schema_id.rsplit("/", 2) if isinstance(schema_id, str) else []
    if len(parts) != 3:
        raise ValidationError("public record has an invalid schema_id")
    record_type = parts[1]
    if record_type.startswith("public-"):
        record_type = record_type.removeprefix("public-")
    return record_type

#: Private markers that must never appear in public text (B08 step 6).
FORBIDDEN_TEXT_PATTERNS = (
    "/Users/",
    "/home/",
    "/private/",
    "file://",
    "ssh-rsa",
    "BEGIN PRIVATE KEY",
    "AKIA",  # AWS access key prefix
)

FORBIDDEN_SUFFIXES = frozenset(
    {".html", ".htm", ".js", ".mjs", ".svg", ".exe", ".dll", ".so", ".dylib", ".sh", ".bat", ".ps1",
     ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".jar", ".bin", ".dmg", ".pkg", ".png"}
)


@dataclass(frozen=True)
class ExportPolicy:
    max_bundle_bytes: int = BUNDLE_MAX_BYTES
    max_media_bytes: int = MEDIA_MAX_BYTES
    max_record_bytes: int = RECORD_MAX_BYTES
    max_entries: int = MAX_ENTRIES
    max_nesting: int = MAX_NESTING
    max_audio_seconds: int = MAX_AUDIO_SECONDS
    max_audio_channels: int = MAX_AUDIO_CHANNELS
    exportable_names: frozenset[str] = field(default_factory=lambda: EXPORTABLE_NAMES)


def _nfc_stable(name: str) -> bool:
    return unicodedata.normalize("NFC", name) == name


def _check_relative_path(relative: str, policy: ExportPolicy) -> None:
    if not relative or relative.startswith("/") or relative.startswith("\\"):
        raise ValidationError(f"absolute or empty export path: {relative!r}")
    if "\\" in relative:
        raise ValidationError(f"backslash in export path: {relative!r}")
    parts = relative.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValidationError(f"non-clean export path: {relative!r}")
    if len(parts) > policy.max_nesting:
        raise ValidationError(f"export path deeper than {policy.max_nesting}: {relative!r}")
    if not _nfc_stable(relative):
        raise ValidationError(f"export path is not NFC-normalized: {relative!r}")
    name = parts[-1]
    suffix = Path(name).suffix.lower()
    if suffix in FORBIDDEN_SUFFIXES:
        raise ValidationError(f"media type {suffix!r} may not be exported: {relative!r}")
    if suffix == ".png":
        raise BlockedError(
            "unsupported_capability",
            "PNG passthrough requires a trusted decode/re-encode step, which is not installed",
        )


def _enumerate(source: Path, policy: ExportPolicy) -> list[tuple[str, os.stat_result]]:
    """Enumerate regular files without following links; refuse anything unsafe."""
    try:
        root_info = source.lstat()
    except OSError as exc:
        raise ValidationError(f"cannot inspect export root: {exc}", path=str(source)) from None
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise ValidationError("export root must be a real directory, not a link", path=str(source))
    entries: list[tuple[str, os.stat_result]] = []
    stack = [(source, "")]
    total = 0
    while stack:
        directory, prefix = stack.pop()
        with os.scandir(directory) as iterator:
            for entry in iterator:
                relative = f"{prefix}{entry.name}"
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    raise ValidationError(f"symlink in export source: {relative!r}")
                if stat.S_ISDIR(info.st_mode):
                    if not _nfc_stable(entry.name):
                        raise ValidationError(f"export directory name is not NFC-normalized: {relative!r}")
                    stack.append((Path(entry.path), f"{relative}/"))
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise ValidationError(f"non-regular file in export source: {relative!r}")
                _check_relative_path(relative, policy)
                if info.st_nlink != 1:
                    raise ValidationError(f"hard link in export source: {relative!r}")
                if info.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
                    raise ValidationError(f"executable file in export source: {relative!r}")
                if info.st_size > policy.max_media_bytes:
                    raise ValidationError(f"file exceeds the media byte cap: {relative!r}")
                public_media = relative.startswith("media/") and relative.lower().endswith(".wav")
                if relative not in policy.exportable_names and not public_media:
                    raise ValidationError(f"file is not on the export allowlist: {relative!r}")
                total += info.st_size
                if total > policy.max_bundle_bytes:
                    raise ValidationError("bundle exceeds the 2 GB export cap")
                entries.append((relative, info))
                if len(entries) > policy.max_entries:
                    raise ValidationError("bundle exceeds the entry-count cap")
    normalized_names = [
        unicodedata.normalize("NFKC", relative).casefold()
        for relative, _info in entries
    ]
    if len(set(normalized_names)) != len(normalized_names):
        raise ValidationError("export paths collide after Unicode normalization/case folding")
    return sorted(entries, key=lambda item: item[0])


def _read_bounded(path: Path, *, limit: int, what: str) -> bytes:
    with open(path, "rb") as handle:
        payload = handle.read(limit + 1)
    if len(payload) > limit:
        raise ValidationError(f"{what} exceeds the {limit}-byte read cap", path=str(path))
    return payload


def _read_beneath(root: Path, relative: str, *, limit: int) -> bytes:
    """Open each path component relative to a trusted directory fd, never following links."""
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise BlockedError(
            "unsupported_capability",
            "safe descriptor-relative no-follow export is unavailable on this platform",
        )
    parts = relative.split("/")
    directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    opened_fds = [directory_fd]
    try:
        for component in parts[:-1]:
            child = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
            opened_fds.append(child)
            directory_fd = child
        file_fd = os.open(
            parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        opened_fds.append(file_fd)
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValidationError(f"export source changed to a non-regular/hard-linked file: {relative!r}")
        if info.st_size > limit:
            raise ValidationError(f"{relative} exceeds the {limit}-byte read cap")
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(file_fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > limit:
            raise ValidationError(f"{relative} exceeds the {limit}-byte read cap")
        return payload
    except OSError as exc:
        raise ValidationError(f"safe no-follow read failed for {relative!r}: {exc}") from None
    finally:
        for fd in reversed(opened_fds):
            os.close(fd)


def _validate_json_bytes(payload: bytes, *, path: str, policy: ExportPolicy) -> Any:
    value = canonical.strict_loads(payload, path=path, max_bytes=policy.max_record_bytes)
    if canonical.dumps(value, path=path) != payload:
        raise ValidationError("exported JSON must already be canonical", path=path)
    _validate_nesting(value, policy=policy, path=path)
    return value


def _validate_nesting(value: Any, *, policy: ExportPolicy, path: str, depth: int = 0) -> None:
    if depth > policy.max_nesting:
        raise ValidationError(f"JSON nesting deeper than {policy.max_nesting}", path=path)
    if isinstance(value, Mapping):
        for item in value.values():
            _validate_nesting(item, policy=policy, path=path, depth=depth + 1)
    elif isinstance(value, list):
        for item in value:
            _validate_nesting(item, policy=policy, path=path, depth=depth + 1)


def _validate_jsonl(payload: bytes, *, path: str, policy: ExportPolicy) -> list[Any]:
    if len(payload) > MAX_JSONL_SHARD_BYTES:
        raise ValidationError("JSONL shard exceeds 100 MB", path=path)
    rows = canonical.parse_jsonl(payload, path=path)
    for index, line in enumerate(payload.split(b"\n")):
        if not line:
            continue
        record = canonical.strict_loads(line, path=f"{path}:{index + 1}")
        if canonical.dumps(record) != line:
            raise ValidationError(f"JSONL row {index + 1} is not canonical", path=path)
        _validate_nesting(record, policy=policy, path=path)
    return rows


def _validate_wav(path: Path, payload: bytes, policy: ExportPolicy) -> None:
    if len(payload) > policy.max_media_bytes:
        raise ValidationError("WAV exceeds the media cap", path=str(path))
    import io

    import soundfile as sf

    try:
        info = sf.info(io.BytesIO(payload))
    except Exception as exc:  # malformed container
        raise ValidationError(f"malformed WAV: {exc}", path=str(path)) from None
    if info.channels != 1 or info.channels > policy.max_audio_channels:
        raise ValidationError("exported WAV must be mono", path=str(path))
    if info.frames > policy.max_audio_seconds * info.samplerate:
        raise ValidationError("WAV exceeds the 30-minute cap", path=str(path))
    if info.samplerate != audio.SAMPLE_RATE:
        raise ValidationError("exported WAV must be 16 kHz", path=str(path))
    decoded_bytes = info.frames * info.channels * np.dtype(np.float32).itemsize
    if decoded_bytes > policy.max_media_bytes:
        raise ValidationError("decoded WAV exceeds the bounded decode allocation", path=str(path))
    try:
        decoded, rate = sf.read(io.BytesIO(payload), dtype="float32", always_2d=True)
    except Exception as exc:
        raise ValidationError(f"malformed WAV decode: {exc}", path=str(path)) from None
    if (rate != audio.SAMPLE_RATE or decoded.shape != (info.frames, info.channels)
            or not np.isfinite(decoded).all()):
        raise ValidationError("WAV decode failed finite-sample validation", path=str(path))


def _scan_public_text(value: Any, *, path: str) -> None:
    if isinstance(value, str):
        if any(pattern in value for pattern in FORBIDDEN_TEXT_PATTERNS):
            raise ValidationError(f"forbidden private marker in public text: {value[:80]!r}", path=path)
        if any(ord(char) < 0x20 and char not in "\t\n\r" for char in value):
            raise ValidationError("control character in public text", path=path)
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _scan_public_text(key, path=path)
            _scan_public_text(item, path=path)
    elif isinstance(value, list):
        for item in value:
            _scan_public_text(item, path=path)


def project_record(
    record: Mapping[str, Any],
    *,
    record_type: str | None = None,
    allowlist: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Project exact record-type field paths; an identically named field elsewhere is not allowed."""
    kind = record_type or (_record_type(record) if allowlist is None else "")
    if allowlist is not None:  # narrow compatibility for callers with their own reviewed projection
        paths = allowlist
    else:
        paths = PUBLIC_PROJECTIONS.get(kind)
        if paths is None:
            raise ValidationError(f"no public projection is defined for record type {kind!r}")
    result: dict[str, Any] = {}
    for path in paths:
        parts = path.split(".")
        value: Any = record
        for part in parts:
            if not isinstance(value, Mapping) or part not in value:
                value = None
                break
            value = value[part]
        if value is None:
            continue
        target = result
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value
    if allowlist is None and kind in PUBLIC_RECORD_SCHEMAS:
        result["schema_id"] = f"audio-bench/public-{kind}/0.1"
    return result


def build_offline_candidate(
    source: Path,
    destination: Path,
    *,
    media_rights: Mapping[str, Mapping[str, Any]] | None = None,
    policy: ExportPolicy | None = None,
) -> dict[str, Any]:
    """Build sanitized local bytes for review; this function does not approve or publish them."""
    policy = policy or ExportPolicy()
    media_rights = media_rights or {}
    if destination.exists() or destination.is_symlink():
        raise ValidationError("offline candidate destination must be new", path=str(destination))
    entries = _enumerate(source, policy)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".offline-export-", dir=destination.parent) as tmp:
        staging = Path(tmp) / "candidate"
        staging.mkdir()
        files: list[dict[str, str]] = []

        def write(relative: str, payload: bytes, media_type: str) -> None:
            _check_relative_path(relative, policy)
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            copied = _read_beneath(staging, relative, limit=policy.max_media_bytes)
            if copied != payload:
                raise ValidationError("offline export copy verification failed", path=relative)
            files.append({
                "path": relative,
                "media_type": media_type,
                "bytes": str(len(copied)),
                "sha256": sha256_bytes(copied),
            })

        for relative, _info in entries:
            payload = _read_beneath(source, relative, limit=policy.max_media_bytes)
            if relative.endswith(".wav"):
                rights = media_rights.get(relative)
                if not isinstance(rights, Mapping) or any(
                    not isinstance(rights.get(scope), Mapping)
                    or rights[scope].get("decision") != "allowed"
                    or not rights[scope].get("evidence_ref")
                    for scope in ("redistribution", "public_playback")
                ):
                    raise ValidationError(f"media rights not allowed/documented for {relative}")
                _validate_wav(source / relative, payload, policy)
                write(relative, payload, "audio/wav")
                continue
            if relative in ("core.json", "inventory.json"):
                continue  # replaced below; private inventory/core hashes must not survive projection
            if relative.endswith(".jsonl"):
                rows = _validate_jsonl(payload, path=relative, policy=policy)
                projected_rows = []
                for row in rows:
                    kind = _record_type(row)
                    projected = project_record(row, record_type=kind)
                    jsonschema.Draft202012Validator(PUBLIC_RECORD_SCHEMAS[kind]).validate(projected)
                    _scan_public_text(projected, path=relative)
                    projected_rows.append(projected)
                write(relative, canonical.jsonl_bytes(projected_rows), "application/jsonl")
                continue
            if relative.endswith(".json"):
                record = _validate_json_bytes(payload, path=relative, policy=policy)
                kind = _record_type(record)
                if kind not in PUBLIC_RECORD_SCHEMAS:
                    raise ValidationError(f"no explicit public projection for {relative} ({kind})")
                projected = project_record(record, record_type=kind)
                jsonschema.Draft202012Validator(PUBLIC_RECORD_SCHEMAS[kind]).validate(projected)
                _scan_public_text(projected, path=relative)
                write(relative, canonical.dumps(projected), "application/json")
                continue
            raise ValidationError(f"unsupported export type: {relative!r}")

        files.sort(key=lambda item: item["path"])
        payload_files = list(files)
        inventory = {
            "schema_id": "audio-bench/public-inventory/0.1",
            "files": payload_files,
            "actual_artifact_set_id": canonical.digest_of([item["path"] for item in payload_files]),
        }
        jsonschema.Draft202012Validator(PUBLIC_INVENTORY_SCHEMA).validate(inventory)
        inventory_bytes = canonical.dumps(inventory)
        write("inventory.json", inventory_bytes, "application/json")
        core: dict[str, Any] = {
            "schema_id": "audio-bench/public-core/0.1",
            "identity_algorithm": canonical.JCS_IDENTITY_ALGORITHM,
            "inventory_digest": sha256_bytes(inventory_bytes),
            "payload_digest": canonical.digest_of([[item["path"], item["sha256"]] for item in payload_files]),
            "core_digest": "sha256:" + "0" * 64,
        }
        core["core_digest"] = canonical.content_id(core, "core_digest")
        jsonschema.Draft202012Validator(PUBLIC_CORE_SCHEMA).validate(core)
        core_bytes = canonical.dumps(core)
        write("core.json", core_bytes, "application/json")
        files.sort(key=lambda item: item["path"])
        total = sum(int(item["bytes"]) for item in files)
        if total > policy.max_bundle_bytes:
            raise ValidationError(f"offline export exceeds {policy.max_bundle_bytes}-byte bundle cap")
        candidate = {
            "schema_id": "audio-bench/export-candidate/0.1",
            "files": files,
            "total_bytes": str(total),
            "candidate_digest": canonical.digest_of([[item["path"], item["sha256"]] for item in files]),
            "public_core_digest": core["core_digest"],
            "redaction_policy_version": "explicit-record-projection-0.2",
        }
        os.rename(staging, destination)
    return candidate


def export_candidate(
    source: Path,
    destination: Path,
    *,
    policy: ExportPolicy | None = None,
    validator: Validator | None = None,
) -> dict[str, Any]:
    """Publishing gate. Offline sanitization is separately available via build_offline_candidate."""
    raise BlockedError(
        "unsupported_capability",
        "public export is disabled: B08 isolation, reviewed public projection schema, and independent adversarial review are incomplete",
    )



def approve_export(
    candidate: Mapping[str, Any],
    *,
    export_id: str,
    public_core_digest: str,
    public_descriptor_digest: str,
    public_config_digest: str,
    approved_scopes: Sequence[str],
    approval_actor: str,
    approved_at: str,
    validator: Validator | None = None,
) -> dict[str, Any]:
    """Bind one exact candidate inventory to a named reviewer; the digest is the approval unit."""
    validator = validator or Validator()
    record = {
        "schema_id": "audio-bench/export/0.1",
        "export_id": export_id,
        "public_core_digest": public_core_digest,
        "file_inventory": candidate["files"],
        "public_descriptor_digest": public_descriptor_digest,
        "public_config_digest": public_config_digest,
        "approved_scopes": list(approved_scopes),
        "approval_actor": approval_actor,
        "approved_at": approved_at,
        "redaction_policy_version": candidate["redaction_policy_version"],
    }
    if candidate.get("public_core_digest") != public_core_digest:
        raise ValidationError("approval public_core_digest differs from sanitized public core")
    validator.validate("export", record)
    recomputed = canonical.digest_of([[entry["path"], entry["sha256"]] for entry in candidate["files"]])
    if recomputed != candidate["candidate_digest"]:
        raise ValidationError("candidate digest does not match the file inventory")
    return record


def verify_export(directory: Path, record: Mapping[str, Any]) -> None:
    """Confirm the directory still contains exactly the approved bytes."""
    root_info = directory.lstat()
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise ValidationError("approved export root must be a real directory")
    declared = {entry["path"]: entry for entry in record["file_inventory"]}
    present: set[str] = set()
    for path in directory.rglob("*"):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValidationError("link found in approved export", path=str(path))
        if stat.S_ISREG(info.st_mode):
            present.add(str(path.relative_to(directory)))
    if set(declared) != present:
        raise ValidationError("export directory does not match the approved inventory")
    for relative, entry in declared.items():
        payload = _read_beneath(directory, relative, limit=MEDIA_MAX_BYTES)
        if entry["sha256"] != sha256_bytes(payload):
            raise ValidationError(f"approved export byte mismatch: {relative}")
