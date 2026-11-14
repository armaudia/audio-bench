#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Browser regression for evidence visibility, filters, CSV and unavailable media."""
import argparse
import csv
import functools
import http.server
import json
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(args.report.resolve()))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright, tempfile.TemporaryDirectory() as temporary:
            browser = playwright.chromium.launch()
            page = browser.new_page(accept_downloads=True)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            base = f"http://127.0.0.1:{server.server_port}/"
            page.goto(base)
            body = page.locator("#rows-body")
            for text in ("execution: passed", "review: pending", "reproduction: not_reproduced", "qualification: not_assessed"):
                expect(body).to_contain_text(text)
            expect(page.locator("#player-status")).to_contain_text("No authorized preview media")
            expect(page.locator("#play")).to_be_disabled()
            index = json.loads((args.report / "data/index.json").read_text())
            task = index["rows"][0]["task"]
            page.locator("#filter-task").select_option(task)
            page.get_by_role("button", name="Apply", exact=True).click()
            expect(page).to_have_url(base + "?task=" + task)
            expect(page.locator("#rows-body tr")).to_have_count(1)
            with page.expect_download() as pending:
                page.get_by_role("button", name="Export visible rows (CSV)", exact=True).click()
            destination = Path(temporary) / "rows.csv"
            pending.value.save_as(destination)
            with destination.open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            assert len(rows) == 7
            assert all(row["qualification"] == "not_assessed" and row["review"] == "pending" for row in rows)
            page.goto(base + "?task=unknown-test-task")
            expect(page.locator("#error")).to_contain_text("Unknown task ID")
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
