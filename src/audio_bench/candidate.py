# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Build a contract-conforming provider from a locally checked-out source tree."""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import ValidationError

PLUGIN_MANIFEST = Path("audio-bench-provider.json")
PLUGIN_SCHEMA = Path(__file__).resolve().parent / "schema_data" / "provider-plugin.schema.json"


def load_provider_manifest(source: Path, expected_provider: str) -> tuple[dict[str, Any], Path]:
    source = source.resolve(strict=True)
    path = source / PLUGIN_MANIFEST
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        import jsonschema
        jsonschema.Draft202012Validator(json.loads(PLUGIN_SCHEMA.read_text(encoding="utf-8"))).validate(value)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read provider plugin manifest: {exc}", path=str(path)) from exc
    except ImportError as exc:  # pragma: no cover - project dependency
        raise ValidationError("jsonschema is required to validate provider plugins") from exc
    except Exception as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError(f"invalid provider plugin manifest: {exc}", path=str(path)) from exc
    if value["provider_id"] != expected_provider:
        raise ValidationError("provider plugin id differs from the submission")
    rel = PurePosixPath(value["descriptor_path"])
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise ValidationError("provider descriptor path must stay within the candidate repository")
    descriptor = (source / Path(*rel.parts)).resolve(strict=True)
    try:
        descriptor.relative_to(source)
    except ValueError as exc:
        raise ValidationError("provider descriptor escapes the candidate repository") from exc
    if descriptor.is_symlink() or not descriptor.is_file():
        raise ValidationError("provider descriptor must be a regular file")
    return value, descriptor


def load_provider_assets(source: Path, manifest: dict[str, Any], descriptor: Path) -> dict[str, Path]:
    """Resolve only descriptor-required, digest-pinned asset files from a checkout."""
    source = source.resolve(strict=True)
    descriptor_data = json.loads(descriptor.read_text(encoding="utf-8"))
    required = {item["id"]: item for item in descriptor_data.get("required_assets", [])}
    declared = manifest.get("assets", [])
    if len({item["id"] for item in declared}) != len(declared):
        raise ValidationError("provider plugin manifest contains duplicate asset ids")
    if {item["id"] for item in declared} != set(required):
        raise ValidationError("provider plugin manifest assets must match descriptor required_assets")
    resolved = {}
    for item in declared:
        relative = PurePosixPath(item["path"])
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise ValidationError("provider asset path must stay within the candidate repository")
        unresolved = source / Path(*relative.parts)
        if unresolved.is_symlink():
            raise ValidationError("provider asset must be a regular file, not a symlink")
        path = unresolved.resolve(strict=True)
        try:
            path.relative_to(source)
        except ValueError as exc:
            raise ValidationError("provider asset escapes the candidate repository") from exc
        expected = required[item["id"]]
        digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if (not path.is_file() or digest != item["sha256"]
                or item["sha256"] != expected["sha256"] or path.stat().st_size != expected["byte_count"]):
            raise ValidationError(f"provider asset identity does not match its descriptor: {item['id']}")
        resolved[item["id"]] = path
    return resolved


def build_provider_plugin(source: Path, output: Path, sdk_prefix: Path) -> Path:
    """Build the fixed CMake target; source configuration is candidate code."""
    source, output, sdk_prefix = source.resolve(strict=True), output.resolve(), sdk_prefix.resolve(strict=True)
    if output.exists() or output.is_symlink():
        raise ValidationError("candidate build output must be a new directory", path=str(output))
    output.mkdir(parents=True)
    env = dict(os.environ)
    env["AUDIO_SDK_PREFIX"] = str(sdk_prefix)
    subprocess.run([
        "cmake", "-S", str(source), "-B", str(output),
        "-DCMAKE_BUILD_TYPE=Release", f"-DAUDIO_SDK_PREFIX={sdk_prefix}",
        f"-DPython3_EXECUTABLE={sys.executable}",
    ], check=True, env=env, timeout=300, capture_output=True, text=True)
    subprocess.run(["cmake", "--build", str(output), "--target", "audio_bench_provider", "--parallel", "2"],
                   check=True, env=env, timeout=600, capture_output=True, text=True)
    candidates = [path for path in output.rglob("*audio_bench_provider.*")
                  if path.suffix in {".so", ".dylib"} and path.is_file() and not path.is_symlink()]
    if len(candidates) != 1:
        raise ValidationError(f"expected one audio_bench_provider shared library, found {len(candidates)}")
    return candidates[0].resolve(strict=True)

