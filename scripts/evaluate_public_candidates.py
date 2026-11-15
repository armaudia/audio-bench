#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Run packaged public C providers and produce a result-only Pages index."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from audio_bench import canonical  # noqa: E402
from audio_bench.errors import ValidationError  # noqa: E402
from audio_bench.smoke import run_sdk_smoke  # noqa: E402
from build_site_results import result_from_bundle  # noqa: E402
import validate_site  # noqa: E402


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(package_root: Path, *, sdk_prefix: Path, native_build: Path,
             work: Path) -> dict:
    rows = []
    for package_dir in sorted(item for item in package_root.iterdir() if item.is_dir()):
        package = json.loads((package_dir / "package.json").read_text(encoding="utf-8"))
        submission = json.loads((package_dir / "submission.json").read_text(encoding="utf-8"))
        if package.get("schema_id") != "audio-bench/candidate-package/0.1":
            raise ValidationError(f"unsupported candidate package in {package_dir.name}")
        plugin = package_dir / package["plugin_file"]
        descriptor = package_dir / "provider.descriptor.json"
        if _sha(plugin) != package["plugin_sha256"] or _sha(descriptor) != package["descriptor_sha256"]:
            raise ValidationError(f"candidate package digest mismatch: {package_dir.name}")
        if (package["submission_id"] != submission["submission_id"]
                or package["source_revision"] != submission["source"]["revision"]
                or package["provider_id"] != submission["provider_id"]):
            raise ValidationError(f"candidate package metadata mismatch: {package_dir.name}")
        canonical.require_canonical(descriptor.read_bytes(), path=str(descriptor))
        bundle = work / f"{submission['submission_id']}-bundle"
        run_sdk_smoke(bundle, native_build=native_build, sdk_prefix=sdk_prefix,
                      repository=ROOT, provider_id=submission["provider_id"],
                      plugin_path=plugin, descriptor_path=descriptor)
        row = result_from_bundle(bundle)
        source = submission["source"]
        row.update({
            "submission_id": submission["submission_id"],
            "display_name": submission["display_name"],
            "runner_mode": "audio-bench",
            "result_status": "Audio-bench-run · synthetic functional; not qualified",
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
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        index = evaluate(args.packages, sdk_prefix=args.sdk_prefix,
                         native_build=args.native_build, work=args.work)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(index, indent=2, sort_keys=True, allow_nan=False) + "\n",
                               encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError, ValidationError) as exc:
        raise SystemExit(f"candidate evaluation failed: {exc}") from exc
    print(f"evaluated {len(index['results'])} public candidate(s); artifact contains result metadata only")


if __name__ == "__main__":
    main()
