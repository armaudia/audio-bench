#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Verify the external SDK prefix against the reviewed byte snapshot in deps/lock.json."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "deps/lock.json"
MANIFEST = ROOT / "deps/sdk-snapshot/audio-sdk-0.1.0.files.sha256"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", required=True, type=Path)
    args = parser.parse_args()
    lock = json.loads(LOCK.read_text())
    dependency = next(item for item in lock["dependencies"] if item["id"] == "audio-sdk-installed-package")
    manifest_bytes = MANIFEST.read_bytes()
    if sha256(MANIFEST) != dependency["file_manifest_sha256"]:
        raise SystemExit("audio-bench SDK file manifest digest mismatch")
    archive = (ROOT / dependency["artifact"]).resolve()
    if not archive.is_file() or sha256(archive) != dependency["sha256"]:
        raise SystemExit("SDK archive missing or digest differs from the pinned snapshot")

    expected: dict[str, str] = {}
    for line in manifest_bytes.decode("ascii").splitlines():
        if not line.strip():
            continue
        digest, relative = line.split(None, 1)
        relative = relative.strip()
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or len(path.parts) < 2:
            raise SystemExit(f"unsafe path in pinned SDK manifest: {relative!r}")
        if relative in expected:
            raise SystemExit(f"duplicate path in pinned SDK manifest: {relative!r}")
        expected[relative] = "sha256:" + digest
    package_name = "audio-sdk-0.1.0"
    if not expected or any(not name.startswith(package_name + "/") for name in expected):
        raise SystemExit("unexpected package paths in pinned SDK manifest")
    observed = {}
    for path in args.prefix.rglob("*"):
        if path.is_file():
            observed[f"{package_name}/{path.relative_to(args.prefix).as_posix()}"] = sha256(path)
    if observed != expected:
        missing = sorted(expected.keys() - observed.keys())
        extra = sorted(observed.keys() - expected.keys())
        changed = sorted(key for key in expected.keys() & observed.keys() if expected[key] != observed[key])
        raise SystemExit(f"SDK prefix differs from pinned snapshot: missing={missing}, extra={extra}, changed={changed}")
    print(f"verified SDK prefix: {len(observed)} files; archive {dependency['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
