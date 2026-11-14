# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
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
import jsonschema
import os
import tempfile
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import aggregate, canonical, ledger
from .bundle import validate_bundle
from .errors import ValidationError
from .export import PUBLIC_INVENTORY_SCHEMA, PUBLIC_RECORD_SCHEMAS, _read_beneath, verify_export

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
    if output.is_symlink():
        raise ValidationError("report output may not be a symlink", path=str(output))
    if output.exists() and any(output.iterdir()):
        raise ValidationError("report output must be a fresh/empty directory", path=str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".audio-bench-report-", dir=output.parent) as temporary:
        staged = Path(temporary) / "report"
        result = _write_report(bundle, staged, site_cap_bytes=site_cap_bytes, index_cap_bytes=index_cap_bytes)
        os.replace(staged, output)
    result["output"] = str(output)
    return result


def _write_report(
    bundle: Path,
    output: Path,
    *,
    site_cap_bytes: int,
    index_cap_bytes: int,
) -> dict[str, Any]:
    report = validate_bundle(bundle)
    if not report.valid:
        raise ValidationError("refusing to build a report from an invalid bundle: " + "; ".join(report.errors[:5]))
    rows = collect_rows(bundle)
    if not rows:
        raise ValidationError("bundle contains no sealed attempts to report")
    if output.exists() and any(output.iterdir()):
        raise ValidationError(f"report output must be a fresh/empty directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
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


def build_public_report(
    public_bundle: Path,
    approval: Mapping[str, Any],
    destination: Path,
) -> dict[str, Any]:
    """Render a static report only from the exact directory bytes covered by approval."""
    from .schemas import Validator

    Validator().validate("export", approval)
    verify_export(public_bundle, approval)
    if destination.exists() or destination.is_symlink():
        raise ValidationError("public report destination must be new", path=str(destination))
    core_bytes = _read_beneath(public_bundle, "core.json", limit=1024 * 1024)
    core = canonical.require_canonical(core_bytes, path="core.json")
    if core.get("schema_id") != "audio-bench/public-core/0.1":
        raise ValidationError("unsupported public core schema")
    if core.get("public_core_digest", core.get("core_digest")) != approval["public_core_digest"]:
        raise ValidationError("approval does not bind this public core")
    if canonical.content_id(core, "core_digest") != core.get("core_digest"):
        raise ValidationError("public core digest does not recompute")
    inventory_bytes = _read_beneath(public_bundle, "inventory.json", limit=1024 * 1024)
    inventory = canonical.require_canonical(inventory_bytes, path="inventory.json")
    jsonschema.Draft202012Validator(PUBLIC_INVENTORY_SCHEMA).validate(inventory)
    if core.get("inventory_digest") != ledger.sha256_bytes(inventory_bytes):
        raise ValidationError("public core does not bind the approved inventory")
    public_files = inventory.get("files")
    if not isinstance(public_files, list):
        raise ValidationError("public inventory files must be an array")
    paths = [entry.get("path") for entry in public_files if isinstance(entry, Mapping)]
    if len(paths) != len(public_files) or len(paths) != len(set(paths)):
        raise ValidationError("public inventory paths are malformed or duplicated")
    if inventory.get("actual_artifact_set_id") != canonical.digest_of(paths):
        raise ValidationError("public inventory artifact-set identity does not recompute")
    if core.get("payload_digest") != canonical.digest_of([
        [entry["path"], entry["sha256"]] for entry in public_files
    ]):
        raise ValidationError("public core does not bind the projected payload digests")
    for entry in public_files:
        payload = _read_beneath(public_bundle, entry["path"], limit=100_000_000)
        if entry["bytes"] != str(len(payload)) or entry["sha256"] != ledger.sha256_bytes(payload):
            raise ValidationError(f"public inventory payload digest mismatch: {entry['path']}")

    observations = []
    observations_bytes = _read_beneath(
        public_bundle, "observations.jsonl", limit=100_000_000
    )
    for line in observations_bytes.splitlines():
        row = canonical.strict_loads(line, path="observations.jsonl")
        jsonschema.Draft202012Validator(PUBLIC_RECORD_SCHEMAS["observation"]).validate(row)
        observations.append(row)
    public_run = None
    public_outputs = []
    for kind in ("run", "output", "summary"):
        relative = f"{kind}.json"
        path = public_bundle / relative
        if path.is_file():
            row = canonical.require_canonical(
                _read_beneath(public_bundle, relative, limit=1024 * 1024), path=relative
            )
            jsonschema.Draft202012Validator(PUBLIC_RECORD_SCHEMAS[kind]).validate(row)
            if kind == "run":
                public_run = row
            elif kind == "output":
                public_outputs.append(row)
    if public_run is None:
        raise ValidationError("approved report is missing its public run record")
    configs = {row["configuration_id"] for row in observations}
    configs.update(row["configuration_id"] for row in public_outputs)
    configs.add(public_run["configuration_id"])
    if configs != {approval["public_config_digest"]}:
        raise ValidationError("approval configuration digest does not match public records")
    provider_digest = public_run.get("provider_digest")
    if provider_digest is not None and provider_digest != approval["public_descriptor_digest"]:
        raise ValidationError("approval descriptor digest does not match the public run")
    for row in observations:
        if (row.get("configuration_id") != public_run["configuration_id"]
                or row.get("comparison_cohort_id") != public_run["comparison_cohort_id"]):
            raise ValidationError("public observation does not bind to the approved run")
    observed_cases = {row.get("case_id") for row in observations}
    for row in public_outputs:
        if (row.get("configuration_id") != public_run["configuration_id"]
                or row.get("sdk_config_digest") != public_run["configuration_id"]):
            raise ValidationError("public output configuration does not bind to the approved run")
        if row.get("case_id") not in observed_cases:
            raise ValidationError("public output case is absent from public observations")

    rows = []
    for row in observations:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('case_id', '')))}</td>"
            f"<td>{html.escape(str(row.get('metric_id', '')))}</td>"
            f"<td>{html.escape(str(row.get('execution_status', '')))}</td>"
            f"<td>{html.escape(str(row.get('value', '—')))}</td>"
            f"<td>{html.escape(str(row.get('unit', '')))}</td>"
            "</tr>"
        )
    page = (
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>Approved offline benchmark report</title>"
        "<style>body{font:16px system-ui;max-width:72rem;margin:2rem auto;padding:0 1rem}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #bbb;padding:.45rem;text-align:left}"
        "code{overflow-wrap:anywhere}</style><body><h1>Approved offline benchmark report</h1>"
        f"<p>Approval <code>{html.escape(str(approval['export_id']))}</code></p>"
        f"<p>Public core <code>{html.escape(core['core_digest'])}</code></p>"
        f"<p>Approved by {html.escape(approval['approval_actor'])} at "
        f"{html.escape(approval['approved_at'])}</p>"
        "<table><thead><tr><th>Case</th><th>Metric</th><th>Status</th><th>Value</th><th>Unit</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></body></html>"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(page, encoding="utf-8")
    temporary.replace(destination)
    return {
        "report": str(destination),
        "observations": len(observations),
        "public_core_digest": core["core_digest"],
        "approval_export_id": approval["export_id"],
        "inventory_entries": len(inventory.get("files", [])),
    }
