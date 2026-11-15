#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Fetch/build merged public submissions into plugin-only artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from audio_bench.candidate import build_provider_plugin, load_provider_manifest  # noqa: E402
from audio_bench.errors import ValidationError  # noqa: E402
from audio_bench.submission import load_submission  # noqa: E402


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def package(submission_paths: list[Path], sdk_prefix: Path, output: Path) -> int:
    if output.exists():
        raise ValidationError("candidate package output must be new")
    output.mkdir(parents=True)
    count = 0
    for manifest_path in submission_paths:
        submission = load_submission(manifest_path)
        if submission["runner_mode"] != "audio-bench" or not submission["execution"]["enabled"]:
            continue
        source = submission["source"]
        if source["visibility"] != "public":
            raise ValidationError("public runner refuses non-public source")
        with tempfile.TemporaryDirectory(prefix="audio-bench-candidate-source-") as td:
            checkout = Path(td) / "source"
            url = f"https://github.com/{source['repository']}.git"
            env = dict(os.environ)
            for key in list(env):
                if "TOKEN" in key.upper() or "PASSWORD" in key.upper() or "SECRET" in key.upper():
                    env.pop(key, None)
            subprocess.run(["git", "init", str(checkout)], check=True, env=env, capture_output=True, text=True)
            subprocess.run(["git", "-C", str(checkout), "remote", "add", "origin", url],
                           check=True, env=env, capture_output=True, text=True)
            subprocess.run(["git", "-C", str(checkout), "fetch", "--depth=1", "origin", source["revision"]],
                           check=True, env=env, capture_output=True, text=True, timeout=300)
            subprocess.run(["git", "-C", str(checkout), "checkout", "--detach", "FETCH_HEAD"],
                           check=True, env=env, capture_output=True, text=True)
            revision = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                                      check=True, capture_output=True, text=True).stdout.strip()
            if revision != source["revision"]:
                raise ValidationError("public source checkout does not match its pinned commit")
            provider_manifest, descriptor = load_provider_manifest(checkout, submission["provider_id"])
            build = Path(td) / "build"
            plugin = build_provider_plugin(checkout, build, sdk_prefix)
            destination = output / submission["submission_id"]
            destination.mkdir()
            shutil.copyfile(plugin, destination / plugin.name)
            shutil.copyfile(descriptor, destination / "provider.descriptor.json")
            (destination / "submission.json").write_text(
                json.dumps(submission, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            (destination / "package.json").write_text(json.dumps({
                "schema_id": "audio-bench/candidate-package/0.1",
                "submission_id": submission["submission_id"],
                "source_revision": revision,
                "provider_id": provider_manifest["provider_id"],
                "plugin_file": plugin.name,
                "plugin_sha256": _sha(destination / plugin.name),
                "descriptor_sha256": _sha(destination / "provider.descriptor.json"),
            }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            count += 1
    if count == 0:
        (output / "no-enabled-public-submissions.json").write_text("{}\n", encoding="utf-8")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-prefix", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("submissions", nargs="*", type=Path)
    args = parser.parse_args()
    try:
        count = package(args.submissions, args.sdk_prefix, args.output)
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError, TypeError, ValidationError) as exc:
        raise SystemExit(f"public candidate packaging failed: {exc}") from exc
    print(f"packaged {count} public candidate plugin(s); no publishing credential was used")


if __name__ == "__main__":
    main()
