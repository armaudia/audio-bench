# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Fail-closed rights checks for corpus evaluation and public Actions caching."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

CORPORA = {
    "voices": ("manifests/voices/voices-balanced-realroom-v1/status.json", "voices-balanced-realroom-v1"),
    "voicebank-demand": ("manifests/voicebank.status.json", "voicebank-demand-test-v1"),
    "dns5": ("manifests/dns5.status.json", "dns5-speakerphone-dev-v1"),
}


def check_corpus_rights(
    dataset: str,
    operation: str,
    *,
    root: Path,
    cache_root: Path | None = None,
) -> dict:
    if dataset not in CORPORA or operation not in {"evaluation", "public-cache"}:
        raise ValueError("unknown corpus or rights operation")
    status_path, dataset_id = CORPORA[dataset]
    status = json.loads((root / status_path).read_text(encoding="utf-8"))
    if status.get("status") not in {"allowed", "enabled_for_evaluation"} or status.get("evaluation") != "allowed" and status.get("rights", {}).get("evaluation") != "allowed":
        raise ValueError(f"{dataset} evaluation is not approved by its corpus status record")

    if operation == "public-cache":
        rights = status.get("rights", {})
        redistribution = rights.get("redistribution", status.get("audio_redistribution"))
        cache_permission = status.get("public_actions_cache", rights.get("public_actions_cache"))
        if redistribution != "allowed" or cache_permission != "allowed":
            raise ValueError(f"{dataset} is not cleared for redistribution through a public Actions cache")
        if not status.get("public_cache_evidence_ref") or not status.get("cache_attribution"):
            raise ValueError(f"{dataset} public-cache approval must include evidence and attribution")
        licenses = status.get("cache_license_sources")
        if not isinstance(licenses, list) or not licenses or any(
            not all(isinstance(item.get(key), str) and item[key].strip() for key in ("title", "license", "url"))
            for item in licenses if isinstance(item, dict)
        ) or any(not isinstance(item, dict) for item in licenses):
            raise ValueError(f"{dataset} public-cache approval must list every source license")

    notice = {
        "dataset_id": dataset_id,
        "operation": operation,
        "source": status.get("source") or status.get("provenance_review", {}).get("primary_record"),
        "licenses": status.get("cache_license_sources") or [
            {"title": status.get("dataset_label", dataset),
             "license": status.get("provenance_review", {}).get("license", "see source terms"),
             "url": status.get("provenance_review", {}).get("primary_record", status.get("source", ""))}
        ],
        "attribution": status.get("cache_attribution") or status.get("provenance_review", {}).get("attribution"),
        "public_cache_evidence_ref": status.get("public_cache_evidence_ref"),
        "status_ref": status_path,
    }
    if cache_root is not None:
        destination = cache_root / dataset_id
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "RIGHTS_NOTICE.json").write_text(
            json.dumps(notice, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    return notice


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=sorted(CORPORA), required=True)
    parser.add_argument("--operation", choices=("evaluation", "public-cache"), required=True)
    parser.add_argument("--cache-root", type=Path, help="write a rights notice beside acquired cache data")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        notice = check_corpus_rights(args.dataset, args.operation, root=args.root, cache_root=args.cache_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"corpus rights check failed: {exc}") from exc
    print(f"{notice['dataset_id']}: {args.operation} approved by its status record")


if __name__ == "__main__":
    main()
