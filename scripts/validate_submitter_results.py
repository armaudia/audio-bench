#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Validate JSON-only submitter results; never checkout private source or run code."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from audio_bench.errors import ValidationError  # noqa: E402
from audio_bench.submitter_results import load_submitter_result  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, default=[ROOT / "submissions/results"])
    args = parser.parse_args()
    files = []
    for path in args.paths:
        files.extend(sorted(path.glob("*.json")) if path.is_dir() else [path])
    files = [path for path in files if not path.name.startswith("_")]
    try:
        for path in files:
            load_submitter_result(path)
    except (ValidationError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"validated {len(files)} submitter-owned result record(s); executed_candidate_code=false")


if __name__ == "__main__":
    main()
