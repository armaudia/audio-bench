# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Command-line entry points for offline validation and synthetic fixture generation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bundle import validate_bundle
from .errors import BenchError, InvocationError, ValidationError
from .manifests import build_synthetic_dataset
from .report import build_report
from .registry import load_catalog
from .schemas import Validator, schema_index
from .smoke import run_sdk_smoke


def _locked_sdk_prefix() -> Path | None:
    repo = Path(__file__).resolve().parents[2]
    lock_path = repo / "deps/lock.json"
    # A source checkout can derive the adjacent Candidate prefix. A wheel carries
    # the lock as data, but cannot assume the workspace-relative SDK build exists.
    if not lock_path.is_file():
        return None
    lock = json.loads(lock_path.read_text())
    artifact = next(item["artifact"] for item in lock["dependencies"]
                    if item["id"] == "audio-sdk-installed-package")
    return (repo / artifact).resolve().parent / "audio-sdk-0.1.0"


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="python -m audio_bench")
    sub = root.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="validate an offline evidence bundle; never executes candidates")
    validate.add_argument("bundle", type=Path)

    synthetic = sub.add_parser("synthetic", help="generate labelled synthetic correctness fixtures")
    synthetic_sub = synthetic.add_subparsers(dest="synthetic_command", required=True)
    build = synthetic_sub.add_parser("build", help="write a deterministic dataset/case/interval manifest")
    build.add_argument("--output", required=True, type=Path)
    build.add_argument("--speakers", type=int, default=6)
    build.add_argument("--pairs-per-speaker", type=int, default=4)
    build.add_argument("--duration-seconds", type=float, default=1.0)

    report = sub.add_parser("report", help="build an offline static report from a validated bundle")
    report_sub = report.add_subparsers(dest="report_command", required=True)
    report_build = report_sub.add_parser("build")
    report_build.add_argument("--bundle", required=True, type=Path)
    report_build.add_argument("--output", required=True, type=Path)

    schemas_cmd = sub.add_parser("schemas", help="inspect pinned, local-only schema identities")
    schemas_cmd.add_argument("--index", action="store_true", required=True)

    catalog_cmd = sub.add_parser("catalog", help="validate closed catalog metadata without executing candidates")
    catalog_cmd.add_argument("catalog", type=Path)

    smoke = sub.add_parser("smoke", help="run the pinned SDK on synthetic fixtures and seal local evidence")
    smoke.add_argument("--output", required=True, type=Path)
    smoke.add_argument("--native-build", type=Path, default=Path("build/ci/native"))
    smoke.add_argument(
        "--sdk-prefix",
        type=Path,
        default=_locked_sdk_prefix(),
    )
    smoke.add_argument("--provider", choices=("speex.ns.v0", "dsp.highpass80.v0"), default="dsp.highpass80.v0")

    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            report = validate_bundle(args.bundle)
            print(json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True, indent=2))
            return 0 if report.valid else 1
        if args.command == "synthetic":
            result = build_synthetic_dataset(
                args.output,
                validator=Validator(),
                speakers=args.speakers,
                pairs_per_speaker=args.pairs_per_speaker,
                duration_s=args.duration_seconds,
            )
            print(
                json.dumps(
                    {
                        "dataset_id": result["dataset"]["dataset_id"],
                        "case_set_id": result["case_set"]["case_set_id"],
                        "scored_interval_set_id": result["intervals"]["scored_interval_set_id"],
                        "case_count": len(result["cases"]),
                        "label": "synthetic correctness fixtures; not corpus evaluation",
                        "output": str(args.output),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
            )
            return 0
        if args.command == "report":
            result = build_report(args.bundle, args.output)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
            return 0
        if args.command == "schemas":
            print(json.dumps(schema_index(), ensure_ascii=False, sort_keys=True, indent=2))
            return 0
        if args.command == "catalog":
            catalog = load_catalog(args.catalog)
            print(json.dumps({"valid": True, "entries": len(catalog["entries"]), "executed_candidate_code": False}, indent=2))
            return 0
        if args.command == "smoke":
            if args.sdk_prefix is None:
                raise InvocationError(
                    "an installed audio-bench wheel requires --sdk-prefix; its SDK package is external"
                )
            result = run_sdk_smoke(
                args.output,
                native_build=args.native_build,
                sdk_prefix=args.sdk_prefix,
                provider_id=args.provider,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
            return 0
    except (BenchError, OSError, ValueError) as exc:
        print(f"audio-bench: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
