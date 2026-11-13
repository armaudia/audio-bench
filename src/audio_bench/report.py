"""Offline static evidence report.

Input is a validated bundle; output is plain HTML/CSS/ES modules with compact JSON shards. No
framework, no external fetch, no hidden pay gate. Rows are keyed by ``(configuration, cohort)`` and
every row shows its dimensions, complete counts and each status dimension separately (execution,
reproduction, review, qualification). Builds fail rather than exceed the size caps.
"""

from __future__ import annotations

import csv
import gzip
import html
import io
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import aggregate, canonical, ledger
from .bundle import validate_bundle
from .errors import ValidationError

SITE_CAP_BYTES = 500 * 1024 * 1024
INDEX_CAP_BYTES = 1024 * 1024
PREVIEW_PRELOAD_CAP_BYTES = 20 * 1024 * 1024
ASSET_DIR = Path(__file__).resolve().parent / "report_assets"
if not ASSET_DIR.is_dir():  # source checkout fallback; installed wheels use packaged resources
    ASSET_DIR = Path(__file__).resolve().parents[2] / "report" / "assets"

CSV_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
QUALIFICATION_LABELS = ("qualified", "not_qualified", "not_assessed")


@dataclass
class ReportRow:
    configuration_id: str
    comparison_cohort_id: str
    task: str = "unknown"
    hardware: str = "unspecified"
    crop: str = "unspecified"
    attempts: list[dict[str, Any]] = field(default_factory=list)
    badges: dict[str, str] = field(
        default_factory=lambda: {"origin": "unknown", "execution": "not_run"}
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "configuration_id": self.configuration_id,
            "comparison_cohort_id": self.comparison_cohort_id,
            "task": self.task,
            "hardware": self.hardware,
            "crop": self.crop,
            "attempts": self.attempts,
            "badges": self.badges,
        }


def _safe_cell(value: Any) -> str:
    """CSV injection guard: prefix cells that a spreadsheet would treat as a formula."""
    text = "" if value is None else str(value)
    if text.startswith(CSV_DANGEROUS_PREFIXES):
        return "'" + text
    return text


def _read_reviews(bundle: Path) -> list[dict[str, Any]]:
    directory = bundle / "reviews"
    if not directory.is_dir():
        return []
    return [
        canonical.require_canonical(path.read_bytes(), path=str(path))
        for path in sorted(directory.glob("*.json"))
    ]


def collect_rows(bundle: Path) -> list[ReportRow]:
    rows: dict[tuple[str, str], ReportRow] = {}
    reviews = _read_reviews(bundle)
    reviews_by_core: dict[str, dict[str, Any]] = {review["result_core_digest"]: review for review in reviews}
    for attempt_dir in ledger.find_attempts(bundle):
        run = canonical.require_canonical((attempt_dir / "run.json").read_bytes())
        core = canonical.require_canonical((attempt_dir / "core.json").read_bytes())
        observations = canonical.parse_jsonl((attempt_dir / "observations.jsonl").read_bytes())
        key = (run["configuration_id"], run["comparison_cohort_id"])
        row = rows.setdefault(
            key,
            ReportRow(configuration_id=key[0], comparison_cohort_id=key[1]),
        )
        metric_ids = sorted({row_data["metric_id"] for row_data in observations})
        attempt_metrics = {
            metric_id: aggregate.summarize_metric(
                [item for item in observations if item["metric_id"] == metric_id]
            )
            for metric_id in metric_ids
        }
        attempt_status = aggregate.aggregate_status([item["execution_status"] for item in observations])
        review = reviews_by_core.get(core["core_digest"])
        row.attempts.append(
            {
                "run_id": run["run_id"],
                "attempt_id": run["attempt_id"],
                "status": attempt_status,
                "core_digest": core["core_digest"],
                "started_at": run["started_at"],
                "hardware": run["machine_fingerprint"],
                "evidence_complete": all(
                    record["execution_status"] in ("passed", "not_applicable") for record in observations
                ),
                "counts": {
                    status: sum(1 for item in observations if item["execution_status"] == status)
                    for status in ("passed", "failed", "blocked", "invalid", "not_applicable", "not_run")
                },
                "metrics": attempt_metrics,
                "badges": {
                    "execution": attempt_status,
                    "review": "pending" if review is None else review["decision"],
                    "reproduction": "not_reproduced" if review is None else review["reproduction"],
                    "qualification": (
                        "not_assessed"
                        if review is None or review["qualification"] is None
                        else review["qualification"]["decision"]
                    ),
                },
            }
        )
        row.hardware = run["machine_fingerprint"]
        row.badges["execution"] = aggregate.aggregate_status(
            [item["status"] for item in row.attempts]
        )
    cohort_path = bundle / "cohort.json"
    if cohort_path.is_file():
        cohort = canonical.require_canonical(cohort_path.read_bytes())
        for row in rows.values():
            if row.comparison_cohort_id == cohort["comparison_cohort_id"]:
                row.task = cohort["task"]
                runtime = cohort["runtime_condition"]
                row.crop = cohort["scored_interval_set_id"]
                if isinstance(runtime, Mapping):
                    row.hardware = str(runtime.get("hardware_fingerprint", row.hardware))
    return [rows[key].as_dict() for key in sorted(rows)]


def build_report(
    bundle: Path,
    output: Path,
    *,
    site_cap_bytes: int = SITE_CAP_BYTES,
    index_cap_bytes: int = INDEX_CAP_BYTES,
) -> dict[str, Any]:
    report = validate_bundle(bundle)
    if not report.valid:
        raise ValidationError("refusing to build a report from an invalid bundle: " + "; ".join(report.errors[:5]))
    rows = collect_rows(bundle)
    if not rows:
        raise ValidationError("bundle contains no sealed attempts to report")
    if output.exists() and any(output.iterdir()):
        raise ValidationError(f"report output must be a fresh/empty directory: {output}")
    output.mkdir(parents=True)
    (output / "assets").mkdir()
    (output / "data").mkdir()

    for name in ("app.css", "app.js", "player.js"):
        source = ASSET_DIR / name
        if not source.is_file():
            raise ValidationError(f"report asset is missing: {source}")
        shutil.copyfile(source, output / "assets" / name)
    shutil.copyfile(ASSET_DIR / "index.html", output / "index.html")

    index_payload = {
        "schema_id": "audio-bench/report-index/0.1",
        "rows": rows,
        "caps": {"preview_preload_bytes": str(PREVIEW_PRELOAD_CAP_BYTES)},
    }
    index_bytes = canonical.dumps(index_payload)
    compressed = gzip.compress(index_bytes, 9)
    if len(compressed) > index_cap_bytes:
        raise ValidationError(
            f"compressed report index is {len(compressed)} bytes, above the {index_cap_bytes}-byte cap"
        )
    (output / "data" / "index.json").write_bytes(index_bytes)

    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer)
    writer.writerow(
        [
            "configuration_id",
            "comparison_cohort_id",
            "task",
            "metric_id",
            "finite_count",
            "mean",
            "median",
            "min",
            "max",
            "execution_status",
            "review",
            "reproduction",
            "qualification",
        ]
    )
    for row in rows:
        for attempt in row["attempts"]:
            for metric_id, stats in sorted(attempt["metrics"].items()):
                writer.writerow(
                    [
                        _safe_cell(row["configuration_id"]),
                        _safe_cell(row["comparison_cohort_id"]),
                        _safe_cell(row["task"]),
                        _safe_cell(metric_id),
                        _safe_cell(stats.get("finite_count", "")),
                        _safe_cell(stats.get("mean", "")),
                        _safe_cell(stats.get("median", "")),
                        _safe_cell(stats.get("min", "")),
                        _safe_cell(stats.get("max", "")),
                        _safe_cell(attempt["status"]),
                        _safe_cell(attempt["badges"]["review"]),
                        _safe_cell(attempt["badges"]["reproduction"]),
                        _safe_cell(attempt["badges"]["qualification"]),
                    ]
                )
    (output / "data" / "rows.csv").write_text(csv_buffer.getvalue(), encoding="utf-8")

    # No audio is copied until an approved public export/gallery manifest and media rights review
    # exist. Never treat an arbitrary bundle/audio directory as public-playback permission.
    media_bytes = 0

    html_payload = _render_html(rows)
    (output / "index.html").write_text(html_payload, encoding="utf-8")

    total = sum(path.stat().st_size for path in output.rglob("*") if path.is_file())
    if total > site_cap_bytes:
        raise ValidationError(f"report site is {total} bytes, above the {site_cap_bytes}-byte cap")
    return {
        "rows": len(rows),
        "site_bytes": total,
        "index_bytes": len(index_bytes),
        "index_gzip_bytes": len(compressed),
        "media_bytes": media_bytes,
        "output": str(output),
    }


def _render_html(rows: Iterable[Mapping[str, Any]]) -> str:
    template = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
    table_rows = []
    for row in rows:
        metrics = "; ".join(
            f"{html.escape(attempt['attempt_id'])} / {html.escape(metric_id)}: "
            f"mean {html.escape(str(stats.get('mean')))} (n={stats.get('finite_count')})"
            for attempt in row["attempts"]
            for metric_id, stats in sorted(attempt["metrics"].items())
        )
        badges = " ".join(
            f'<span class="badge badge-{html.escape(value)}">{html.escape(kind)}: {html.escape(value)}</span>'
            for kind, value in sorted(row["badges"].items())
        )
        attempts = " ".join(
            f'<p>Attempt {html.escape(item["attempt_id"])}: '
            + " ".join(
                f'<span class="badge badge-{html.escape(value)}">{html.escape(kind)}: {html.escape(value)}</span>'
                for kind, value in sorted(item["badges"].items())
            )
            + "</p>"
            for item in row["attempts"]
        )
        table_rows.append(
            "<tr>"
            f'<td><code>{html.escape(row["configuration_id"])}</code></td>'
            f'<td><code>{html.escape(row["comparison_cohort_id"])}</code></td>'
            f'<td>{html.escape(row["task"])}</td>'
            f'<td>{html.escape(row["hardware"])}</td>'
            f'<td>{metrics}</td>'
            f'<td>{badges}{attempts}</td>'
            "</tr>"
        )
    return template.replace("<!--ROWS-->", "\n".join(table_rows))
