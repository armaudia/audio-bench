#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Browser acceptance for the static public results page."""

from __future__ import annotations

import argparse
import http.server
import json
import shutil
import tempfile
import threading
from functools import partial
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--results", type=Path, help="exercise the results table using this validated index")
args = parser.parse_args()
with tempfile.TemporaryDirectory(prefix="audio-bench-site-") as temporary:
    site = Path(temporary) / "site"
    shutil.copytree(ROOT / "site", site)
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900}, accept_downloads=True)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            base = f"http://127.0.0.1:{server.server_port}/"
            page.goto(base)
            expect(page.get_by_role("heading", name="Audio benchmark results")).to_be_visible()
            expect(page.get_by_role("link", name="Submit a pipeline", exact=True)).to_be_visible()
            expect(page.get_by_role("heading", name="No published results yet")).to_be_visible()
            expect(page.locator("#result-count")).to_have_text("0")
            if args.results:
                index = json.loads(args.results.read_text(encoding="utf-8"))
                expected = len(index["results"])
                shutil.copyfile(args.results, site / "data/results.json")
                page.reload()
                rows = page.locator(".results-table tbody tr")
                expect(rows).to_have_count(expected)
                page.get_by_role("searchbox", name="Search").fill("no-match-for-browser-test")
                expect(page.get_by_role("heading", name="No matching results")).to_be_visible()
                page.locator("#results").get_by_role("button", name="Clear filters").click()
                expect(rows).to_have_count(expected)
                expect(page.get_by_role("searchbox", name="Search")).to_be_focused()

                speech_count = sum(row["category_id"] == "speech-enhancement" for row in index["results"])
                category = page.get_by_role("button", name="Speech enhancement")
                category.click()
                expect(category).to_have_attribute("aria-pressed", "true")
                expect(rows).to_have_count(speech_count)
                page.get_by_role("button", name="All results").click()

                suite = index["results"][0]["suite_id"]
                page.get_by_label("Benchmark suite").select_option(suite)
                suite_count = sum(row["suite_id"] == suite for row in index["results"])
                expect(rows).to_have_count(suite_count)
                expand_metrics = page.get_by_role("button", name="Show all", exact=False)
                if expand_metrics.is_visible():
                    key_columns = page.get_by_role("columnheader").count()
                    expand_metrics.click()
                    assert page.get_by_role("columnheader").count() > key_columns
                    page.get_by_role("button", name="Show key metrics", exact=True).click()
                    expect(page.get_by_role("columnheader")).to_have_count(key_columns)
                first_details = rows.first.get_by_text("Run details", exact=True)
                first_details.click()
                expect(rows.first.get_by_text("All measurements")).to_be_visible()

                sort = page.get_by_role("button", name="Pipeline", exact=True)
                sort.click()
                expect(sort).to_be_focused()
                expect(page.get_by_role("columnheader", name="Pipeline")).to_have_attribute("aria-sort", "descending")
                page.get_by_label("Run by").select_option("submitter-owned")
                owner_count = sum(row["suite_id"] == suite and row["runner_mode"] == "submitter-owned"
                                  for row in index["results"])
                expect(rows).to_have_count(owner_count)
                page.locator("#clear-filters").click()
                with page.expect_download() as download:
                    page.get_by_role("link", name="Download JSON").click()
                assert json.loads(Path(download.value.path()).read_text()) == index

            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            expect(page.get_by_role("searchbox", name="Search")).to_be_visible()
            if args.results:
                pipeline = page.locator(".results-table .pipeline > strong").first
                pipeline.scroll_into_view_if_needed()
                expect(pipeline).to_be_in_viewport()
            page.route("**/data/results.json?*", lambda route: route.fulfill(status=503))
            page.reload()
            expect(page.get_by_role("status")).to_contain_text("Could not load results (HTTP 503).")
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
print("Pages UI browser acceptance passed")
