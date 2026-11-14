# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Fetch exact dataset assets into an external cache; repository trees stay audio-free."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from . import canonical
from .acquire import Fetcher, HTTPSFetcher, SourcePolicy, acquire
from .errors import AcquisitionError, ValidationError

SCHEMA_PATH = Path(__file__).resolve().parent / "schema_data" / "external-dataset.schema.json"
MAX_TOTAL_BYTES = 100 * 1024 * 1024 * 1024


def validate_external_manifest(value: Any) -> dict[str, Any]:
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover
        raise ValidationError("jsonschema is required to validate dataset manifests") from exc
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(value),
                    key=lambda item: list(map(str, item.absolute_path)))
    if errors:
        error = errors[0]
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        raise ValidationError(f"external dataset schema error at {location}: {error.message}")
    hosts = {host.lower() for host in value["allowed_hosts"]}
    total = 0
    paths: set[str] = set()
    for item in value["files"]:
        relative = PurePosixPath(item["path"])
        if relative.as_posix() != item["path"] or relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise ValidationError(f"unsafe external dataset path: {item['path']!r}")
        if item["path"] in paths:
            raise ValidationError(f"duplicate external dataset path: {item['path']}")
        paths.add(item["path"])
        if (urlsplit(item["url"]).hostname or "").lower() not in hosts:
            raise ValidationError(f"dataset URL host is not allowlisted: {item['url']}")
        total += item["bytes"]
    if total > MAX_TOTAL_BYTES:
        raise ValidationError("external dataset exceeds 100 GiB download cap")
    return value


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def fetch_external_dataset(
    manifest_path: Path,
    cache_root: Path,
    *,
    fetcher: Fetcher | None = None,
    resolver=None,
) -> Path:
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = canonical.require_canonical(manifest_bytes, path=str(manifest_path))
    except (OSError, ValidationError) as exc:
        raise AcquisitionError(f"cannot load canonical external dataset manifest: {exc}") from exc
    validate_external_manifest(manifest)
    manifest_digest = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
    destination = cache_root / manifest["dataset_id"] / manifest["version"] / manifest_digest.removeprefix("sha256:")
    destination.mkdir(parents=True, exist_ok=True)
    downloader = fetcher or HTTPSFetcher()
    policy = SourcePolicy(allowed_hosts=frozenset(host.lower() for host in manifest["allowed_hosts"]))
    for item in manifest["files"]:
        path = destination / PurePosixPath(item["path"])
        resolved_destination = destination.resolve()
        resolved_parent = path.parent.resolve()
        if resolved_parent != resolved_destination and resolved_destination not in resolved_parent.parents:
            raise AcquisitionError(f"dataset cache path escapes destination: {path}")
        parent = path.parent
        while parent != destination.parent and parent != parent.parent:
            if parent.is_symlink():
                raise AcquisitionError(f"dataset cache directory is a symlink: {parent}")
            if parent == destination:
                break
            parent = parent.parent
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise AcquisitionError(f"dataset cache path is a symlink: {path}")
        if path.is_file() and path.stat().st_size == item["bytes"] and _digest(path) == item["sha256"]:
            continue
        path.unlink(missing_ok=True)
        acquire(item["url"], path, expected_sha256=item["sha256"], expected_bytes=item["bytes"],
                policy=policy, fetcher=downloader, max_bytes=item["bytes"], resolver=resolver)
    return destination
