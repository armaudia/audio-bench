#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Verify the build and unit checks, with benchmark execution reserved for main pushes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import venv
import xml.etree.ElementTree as ET
from pathlib import Path


def run(*args: str, cwd: Path | None = None, env: dict | None = None) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument(
        "--skip-benchmarks", action="store_true",
        help="run build/conformance/unit checks without executing the synthetic evaluation suite",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / "build/ci"
    output.mkdir(parents=True, exist_ok=True)
    lock = json.loads((root / "deps/lock.json").read_text())
    sdk = next(item for item in lock["dependencies"] if item["id"] == "audio-sdk-installed-package")
    candidate = (root / sdk["artifact"]).resolve().parent
    prefix = candidate / "audio-sdk-0.1.0"
    native = output / "native"
    run("cmake", "-S", str(root / "native"), "-B", str(native),
        "-DCMAKE_BUILD_TYPE=Release", f"-DPython3_EXECUTABLE={sys.executable}",
        f"-DAUDIO_SDK_PREFIX={prefix}")
    run("cmake", "--build", str(native), "--parallel", "2")
    run("ctest", "--test-dir", str(native), "--output-on-failure", "--timeout", "60",
        "--output-junit", str(output / "native-tests.xml"))
    env = dict(os.environ, AUDIO_BENCH_NATIVE_BUILD=str(native), AUDIO_SDK_PREFIX=str(prefix))
    test_command = [sys.executable, "-m", "pytest", "tests/unit", "-q"]
    if args.skip_benchmarks:
        test_command.extend(["-m", "not sdk"])
    test_command.extend(["--junitxml", str(output / "unit-tests.xml")])
    run(*test_command, cwd=root, env=env)
    suites = ET.parse(output / "unit-tests.xml").getroot()
    if any(int(suite.get("skipped", "0")) for suite in suites.iter("testsuite")):
        raise RuntimeError("release checks must not skip SDK integration tests")
    if not args.skip_benchmarks:
        bundles = []
        for name, provider in (("highpass", "dsp.highpass80.v0"), ("speex", "speex.ns.v0")):
            bundle = output / name
            bundles.append(str(bundle))
            run(sys.executable, "-m", "audio_bench", "smoke", "--output", str(bundle),
                "--native-build", str(native), "--sdk-prefix", str(prefix), "--provider", provider, cwd=root)
            run(sys.executable, "-m", "audio_bench", "validate", str(bundle), cwd=root)
            run(sys.executable, "-m", "audio_bench", "report", "build", "--bundle", str(bundle),
                "--output", str(output / (name + "-report")), cwd=root)
        run(sys.executable, "scripts/build_site_results.py", "--output", str(output / "results.json"),
            *bundles, cwd=root)
        run(sys.executable, "scripts/validate_site.py", str(output / "results.json"), cwd=root)
    wheels = output / "wheels"
    run(sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--wheel-dir", str(wheels), str(root))
    wheel = next(wheels.glob("audio_bench-*.whl"))
    environment = output / "python"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / "bin/python"
    options = ["--no-index", "--find-links", str(args.wheelhouse.resolve())] if args.wheelhouse else []
    run(str(python), "-m", "pip", "install", *options, "--constraint", str(root / "locks/requirements-ci.txt"),
        "--report", str(output / "wheel-install-results.json"), str(wheel))
    clean_env = dict(os.environ)
    clean_env.pop("PYTHONPATH", None)
    if not args.skip_benchmarks:
        run(str(python), "-m", "audio_bench", "smoke", "--output", str(output / "installed-smoke"),
            "--native-build", str(native), "--sdk-prefix", str(prefix), cwd=environment, env=clean_env)
        run(str(python), "-m", "audio_bench", "validate", str(output / "installed-smoke"), cwd=environment, env=clean_env)
        run(str(python), "-m", "audio_bench", "report", "build", "--bundle", str(output / "installed-smoke"),
            "--output", str(output / "installed-report"), cwd=environment, env=clean_env)
    package = output / "package"
    (package / "bin").mkdir(parents=True)
    for name in ("audio_bench_driver", "audio_bench_collect"):
        shutil.copy2(native / name, package / "bin" / name)
    shutil.copy2(wheel, package / wheel.name)
    shutil.copy2(root / "locks/requirements-ci.txt", package / "requirements-ci.txt")
    shutil.copytree(prefix, package / "sdk/audio-sdk-0.1.0")
    for name in ("audio-sdk-0.1.0.tar.gz", "audio-sdk-0.1.0.files.sha256"):
        shutil.copy2(candidate / name, package / "sdk" / name)
    (package / "README.txt").write_text(
        "Install the wheel with Python 3.12 and: pip install --constraint requirements-ci.txt audio_bench-*.whl\n"
        "From this extracted directory, run:\n"
        "python -m audio_bench smoke --output /path/to/new-bundle --native-build bin --sdk-prefix sdk/audio-sdk-0.1.0\n"
        "Synthetic functional evaluation only; no workload qualification or public audio gallery.\n")
    dist = output / "dist"
    dist.mkdir()
    target = f"{platform.system().lower()}-{platform.machine().lower()}"
    archive = Path(shutil.make_archive(str(dist / f"audio-bench-0.1.0-{target}"), "zip", package))
    (dist / (archive.name + ".sha256")).write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n")


if __name__ == "__main__":
    main()
