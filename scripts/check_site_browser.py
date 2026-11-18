#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Browser acceptance for the static public results page (GitHub Actions)."""

from __future__ import annotations

import http.server
import argparse
import json
import shutil
import tempfile
import threading
from functools import partial
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--results", type=Path, help="exercise the results table using this validated index")
args = parser.parse_args()
with tempfile.TemporaryDirectory(prefix="audio-bench-site-") as temporary:
    site = Path(temporary) / "site"
    shutil.copytree(ROOT / "site", site)
    expected = 0
    if args.results:
        index = json.loads(args.results.read_text(encoding="utf-8"))
        expected = len(index["results"])
        shutil.copyfile(args.results, site / "data/results.json")
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(f"http://127.0.0.1:{server.server_port}/", wait_until="networkidle")
            assert page.get_by_role("heading", name="Compare audio pipelines with clear evidence.").is_visible()
            assert page.get_by_role("link", name="How to submit").is_visible()
            assert page.locator("#result-count").inner_text() == str(expected)
            if expected:
                assert page.locator(".results-table tbody tr").count() == expected
                assert page.get_by_text("Provenance").first.is_visible()
                page.get_by_role("searchbox", name="Search pipelines").fill("speex")
                assert page.locator(".results-table tbody tr").count() < expected
                page.get_by_role("button", name="Clear filters").click()
                assert page.locator(".results-table tbody tr").count() == expected
            else:
                assert page.get_by_text("No benchmark results are published yet. Submit the first pipeline to start the comparison.").is_visible()
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert page.locator("#search").is_visible()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
print("Pages UI browser acceptance passed")
