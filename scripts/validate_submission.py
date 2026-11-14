#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Validate submission metadata without checking out or executing target code."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from audio_bench.submission import load_submission  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifests", nargs="+", type=Path)
    args = parser.parse_args()
    try:
        for path in args.manifests:
            if path.name == "_template.json":
                continue
            manifest = load_submission(path)
            print(json.dumps({"valid": True, "submission_id": manifest["submission_id"],
                              "runner_mode": manifest["runner_mode"],
                              "execution_enabled": manifest["execution"]["enabled"]}, sort_keys=True))
    except Exception as exc:
        print(f"submission validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
