#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Run packaged public C providers and produce a result-only Pages index."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import PurePosixPath
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from audio_bench import canonical  # noqa: E402
from audio_bench.errors import ValidationError  # noqa: E402
from audio_bench.smoke import run_sdk_smoke  # noqa: E402
from audio_bench.submission import validate_submission  # noqa: E402
from evaluate_voicebank import DATASET_ID as VOICEBANK_DATASET_ID, run_voicebank_candidate  # noqa: E402
from evaluate_realtime import run_realtime_candidate  # noqa: E402
from build_site_results import result_from_bundle  # noqa: E402
import validate_site  # noqa: E402


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(package_root: Path, *, sdk_prefix: Path, native_build: Path,
             work: Path, dataset_cache: Path | None = None) -> dict:
    rows = []
    for package_dir in sorted(item for item in package_root.iterdir() if item.is_dir()):
        package = json.loads((package_dir / "package.json").read_text(encoding="utf-8"))
        submission = json.loads((package_dir / "submission.json").read_text(encoding="utf-8"))
        submission = validate_submission(submission)
        if package.get("schema_id") != "audio-bench/candidate-package/0.1":
            raise ValidationError(f"unsupported candidate package in {package_dir.name}")
        plugin = package_dir / package["plugin_file"] if isinstance(package.get("plugin_file"), str) else None
        descriptor = package_dir / "provider.descriptor.json"
        builtin = package.get("builtin_provider") is True
        if not builtin and (plugin is None or _sha(plugin) != package["plugin_sha256"]):
            raise ValidationError(f"candidate package digest mismatch: {package_dir.name}")
        if builtin and (package.get("plugin_file") is not None or
                        submission["provider_id"] not in {"speex.ns.v0", "dsp.highpass80.v0"}):
            raise ValidationError(f"invalid built-in provider package: {package_dir.name}")
        if _sha(descriptor) != package["descriptor_sha256"]:
            raise ValidationError(f"candidate package digest mismatch: {package_dir.name}")
        asset_paths = {}
        for asset in package.get("assets", []):
            relative = PurePosixPath(asset["file"])
            if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
                raise ValidationError("candidate package asset path is unsafe")
            unresolved = package_dir.joinpath(*relative.parts)
            asset_path = unresolved.resolve(strict=True)
            if (unresolved.is_symlink() or not asset_path.is_file()
                    or not asset_path.is_relative_to(package_dir.resolve())
                    or _sha(asset_path) != asset["sha256"] or asset["id"] in asset_paths):
                raise ValidationError(f"candidate asset package digest mismatch: {package_dir.name}")
            asset_paths[asset["id"]] = asset_path
        if (package["submission_id"] != submission["submission_id"]
                or package["source_revision"] != submission["source"]["revision"]
                or package["provider_id"] != submission["provider_id"]):
            raise ValidationError(f"candidate package metadata mismatch: {package_dir.name}")
        canonical.require_canonical(descriptor.read_bytes(), path=str(descriptor))
        if submission["category_id"] == "real-time-processing":
            measured = run_realtime_candidate(
                native_build=native_build, sdk_prefix=sdk_prefix,
                provider_id=submission["provider_id"], plugin_path=plugin,
                descriptor_path=None if builtin else descriptor, assets=asset_paths,
                work=work / f"{submission['submission_id']}-realtime")
            row = {
                "submission_id": submission["submission_id"], "result_id": measured["result_id"],
                "display_name": submission["display_name"], "task": "Filtering",
                "category_id": submission["category_id"], "runner_mode": "audio-bench",
                "result_status": "Measured · real-time load; synthetic input",
                "provider_id": submission["provider_id"], "suite_id": measured["suite_id"],
                "dataset_id": measured["dataset_id"], "dataset_label": measured["dataset_label"],
                "case_count": measured["case_count"], "model_digest": submission["model_digest"],
                "metrics": measured["metrics"],
                "evidence": {**measured["evidence"],
                    "candidate_package_digest": canonical.digest_of(package),
                    "provider_plugin_digest": package.get("plugin_sha256"),
                    "provider_descriptor_digest": package["descriptor_sha256"]},
            }
        elif submission["benchmark"]["dataset_id"] == VOICEBANK_DATASET_ID:
            if dataset_cache is None:
                raise ValidationError("VoiceBank evaluation requires --dataset-cache")
            measured = run_voicebank_candidate(
                native_build=native_build, sdk_prefix=sdk_prefix, cache_root=dataset_cache,
                provider_id=submission["provider_id"],
                plugin_path=plugin,
                descriptor_path=None if builtin else descriptor,
                assets=asset_paths,
                work=work / f"{submission['submission_id']}-voicebank")
            row = {
                "submission_id": submission["submission_id"], "result_id": measured["result_id"],
                "display_name": submission["display_name"], "task": "Noise cancellation",
                "category_id": submission["category_id"],
                "runner_mode": "audio-bench", "result_status": "Measured · full paired corpus",
                "provider_id": submission["provider_id"], "suite_id": measured["suite_id"],
                "dataset_id": measured["dataset_id"], "dataset_label": measured["dataset_label"],
                "case_count": measured["case_count"], "model_digest": submission["model_digest"],
                "protocol_url": "https://github.com/armaudia/audio-bench/blob/main/suites/voicebank-demand-paired-v1/protocol.json",
                "dataset_source_url": "https://datashare.ed.ac.uk/handle/10283/2791",
                "source": {"visibility": "public", "repository": submission["source"]["repository"],
                           "revision": submission["source"]["revision"],
                           "url": f"https://github.com/{submission['source']['repository']}"},
                "metrics": measured["metrics"],
                "evidence": {
                    "configuration_id": measured["configuration_id"],
                    "sdk_package_digest": measured["sdk_package_digest"],
                    "harness_digest": measured["harness_digest"],
                    "bundle_manifest_digest": canonical.digest_of({
                        key: measured[key] for key in ("dataset_manifest_digest", "case_manifest_digest",
                                                       "protocol_digest", "configuration_id", "sdk_package_digest")}),
                    "dataset_manifest_digest": measured["dataset_manifest_digest"],
                    "case_manifest_digest": measured["case_manifest_digest"],
                    "protocol_digest": measured["protocol_digest"],
                    "candidate_package_digest": canonical.digest_of(package),
                    "provider_plugin_digest": package.get("plugin_sha256"),
                    "provider_descriptor_digest": package["descriptor_sha256"],
                    "case_count": measured["case_count"], "speaker_count": measured["speaker_count"],
                    "runner_fingerprint": "GitHub Actions ubuntu-24.04",
                },
            }
        else:
            bundle = work / f"{submission['submission_id']}-bundle"
            run_sdk_smoke(bundle, native_build=native_build, sdk_prefix=sdk_prefix,
                          repository=ROOT, provider_id=submission["provider_id"],
                          plugin_path=plugin,
                          descriptor_path=None if builtin else descriptor)
            row = result_from_bundle(bundle, submission["category_id"])
        source = submission["source"]
        row.update({
            "submission_id": submission["submission_id"],
            "display_name": submission["display_name"],
            "runner_mode": "audio-bench",
            "result_status": row.get("result_status", "Audio-bench-run · synthetic functional; not qualified"),
            "provider_id": submission["provider_id"],
            "model_digest": submission["model_digest"],
            "source": {"visibility": "public", "repository": source["repository"],
                       "revision": source["revision"], "url": f"https://github.com/{source['repository']}"},
        })
        rows.append(row)
    index = {"schema_id": "audio-bench/site-results/0.1",
             "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
             "results": rows}
    validate_site.validate_index(index)
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages", required=True, type=Path)
    parser.add_argument("--sdk-prefix", required=True, type=Path)
    parser.add_argument("--native-build", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--dataset-cache", type=Path, help="external verified corpus cache root")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        index = evaluate(args.packages, sdk_prefix=args.sdk_prefix,
                         native_build=args.native_build, work=args.work,
                         dataset_cache=args.dataset_cache)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(index, indent=2, sort_keys=True, allow_nan=False) + "\n",
                               encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError, ValidationError) as exc:
        raise SystemExit(f"candidate evaluation failed: {exc}") from exc
    print(f"evaluated {len(index['results'])} public candidate(s); artifact contains result metadata only")


if __name__ == "__main__":
    main()
