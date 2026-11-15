#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Fetch SHA-pinned dataset files to a local external cache, never to the repo."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from audio_bench.external_dataset import fetch_external_dataset  # noqa: E402
from audio_bench.errors import BenchError  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--cache", type=Path, help="external cache directory; defaults outside the repository")
    args = parser.parse_args()
    cache = args.cache or Path(os.environ.get("AUDIO_BENCH_DATA_CACHE", Path.home() / ".cache/audio-bench/datasets"))
    try:
        path = fetch_external_dataset(args.manifest, cache)
    except (BenchError, OSError, ValueError) as exc:
        raise SystemExit(f"dataset fetch failed: {exc}") from exc
    print(f"verified dataset assets cached at {path}")


if __name__ == "__main__":
    main()
