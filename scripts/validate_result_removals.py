#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Validate exact-result removal requests without changing the published report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from build_site_results import load_result_removals  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, default=[ROOT / "submissions/removals"])
    args = parser.parse_args()
    try:
        result_ids = load_result_removals(args.paths)
    except (OSError, ValueError, TypeError) as exc:
        raise SystemExit(f"invalid result removal request: {exc}") from exc
    print(f"validated {len(result_ids)} result removal request(s)")


if __name__ == "__main__":
    main()
