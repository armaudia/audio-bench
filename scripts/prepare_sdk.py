#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Build the exact source-pinned SDK and record this host's verified package snapshot.

This deliberately refreshes the local dependency lock and wheel resources. It never
changes the source pin, and it does not label the package as workload-qualified.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("build/sdk"))
    args = parser.parse_args()
    source, output = args.sdk_source.resolve(), args.output.resolve()
    pin = json.loads((ROOT / "deps/sdk-source.json").read_text())
    observed = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if observed != pin["revision"]:
        raise SystemExit("SDK checkout does not match deps/sdk-source.json")
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=source, text=True)
    if dirty:
        raise SystemExit("SDK checkout has modified tracked files; commit and review its source pin first")
    subprocess.run([sys.executable, str(source / "scripts/ci.py"), "--output", str(output)], check=True)
    candidate = output / "candidate"
    prefix = candidate / "audio-sdk-0.1.0"
    schemas = prefix / "share/audio-sdk/schemas"
    for relative in ("descriptor.schema.json", "effective-config.schema.json",
                     "providers/speex.ns.v0.descriptor.json", "providers/dsp.highpass80.v0.descriptor.json"):
        if (ROOT / "schemas/sdk" / relative).read_bytes() != (schemas / relative).read_bytes():
            raise SystemExit(f"SDK schema/descriptor changed; migrate reviewed schemas before adoption: {relative}")
    file_manifest = candidate / "audio-sdk-0.1.0.files.sha256"
    shutil.copyfile(file_manifest, ROOT / "deps/sdk-snapshot" / file_manifest.name)
    lock = json.loads((ROOT / "deps/lock.json").read_text())
    sdk = next(item for item in lock["dependencies"] if item["id"] == "audio-sdk-installed-package")
    sdk.clear()
    sdk.update({
        "id": "audio-sdk-installed-package", "role": "runtime", "version": "0.1.0",
        "source_revision": observed, "artifact": os.path.relpath(candidate / "audio-sdk-0.1.0.tar.gz", ROOT),
        "sha256": sha(candidate / "audio-sdk-0.1.0.tar.gz"),
        "file_manifest": "deps/sdk-snapshot/audio-sdk-0.1.0.files.sha256",
        "file_manifest_sha256": sha(file_manifest),
        "build_id": json.loads((prefix / "share/audio-sdk/build-info.json").read_text())["build_id"],
        "platform": f"{platform.system()} {platform.machine()}",
        "qualification": "not_assessed; source-pinned functional package only",
        "headers": {name: sha(prefix / "include/audio_sdk" / name) for name in ("provider_v0.h", "session_v0.h")},
    })
    (ROOT / "deps/lock.json").write_text(json.dumps(lock, indent=2) + "\n")
    reports = ROOT / "docs/task-evidence/artifacts/sdk-conformance"
    for name in ("speex-report.json", "highpass-report.json"):
        shutil.copyfile(candidate / "verification" / name, reports / name)
    toolchain = {"schema_version": 1, "platform": platform.platform(),
                 "python": {"version": platform.python_version()},
                 "sdk_build": json.loads((prefix / "share/audio-sdk/build-info.json").read_text()),
                 "qualification": "not_assessed"}
    versions = {}
    for line in (ROOT / "locks/requirements-ci.txt").read_text().splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^ ]+)", line)
        if match:
            name, expected = match.groups()
            actual = importlib.metadata.version(name)
            if actual != expected:
                raise SystemExit(f"Install the pinned CI requirements first: {name}={actual}, expected {expected}")
            versions[name] = actual
    toolchain["python_dependencies"] = versions
    (ROOT / "toolchain-lock.json").write_text(json.dumps(toolchain, indent=2) + "\n")
    from audio_bench import canonical
    cohort_path = ROOT / "suites/synthetic-smoke-v1/cohort.json"
    cohort = canonical.strict_loads(cohort_path.read_bytes())
    for metric in cohort["metric_set"]:
        metric["lock_digest"] = sha(ROOT / "locks/requirements-ci.txt")
        metric["code_digest"] = sha(ROOT / "src/audio_bench/metrics.py")
    cohort["comparison_cohort_id"] = canonical.content_id(cohort, "comparison_cohort_id")
    cohort_path.write_bytes(canonical.dumps(cohort))
    runtime = ROOT / "src/audio_bench/runtime_data"
    for relative in ("deps", "docs/task-evidence/artifacts/sdk-conformance", "native", "registry", "locks", "suites"):
        shutil.copytree(ROOT / relative, runtime / relative, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("build*", "__pycache__", "tests", "source-inventory.json"))
    for relative in ("toolchain-lock.json", "pyproject.toml"):
        shutil.copyfile(ROOT / relative, runtime / relative)
    subprocess.run([sys.executable, str(ROOT / "scripts/verify_sdk_snapshot.py"),
                    "--prefix", str(prefix)], check=True)
    print(f"Prepared installed SDK: {prefix}")


if __name__ == "__main__":
    main()
