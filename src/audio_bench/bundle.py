"""Offline bundle validation.

A bundle is a directory of canonical control records:

    dataset.json, cases-*.jsonl, case-set.json, scored-intervals.json, cohort.json,
    recipe-*.json, requests/<request_id>.json,
    runs/<run_id>/<attempt_id>/{run,core,inventory,summary}.json + {observations,outputs}.jsonl,
    reviews/<review_id>.json, exports/<export_id>.json, audio/*.wav

Validation never executes candidate code, never fetches a remote schema and never repairs a
record: an altered payload fails. Every error is collected so an operator sees the whole block.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from . import aggregate, audio, canonical, ledger, metrics, schemas
from .errors import ValidationError
from .schemas import Validator

ALLOWED_TOP_LEVEL_FILES = {
    "dataset.json",
    "case-set.json",
    "scored-intervals.json",
    "cohort.json",
    "export-candidate.json",
    "manifest.json",
}
ALLOWED_PREFIXES = ("cases-", "files-", "recipe-")
ALLOWED_DIRECTORIES = {"audio", "requests", "runs", "reviews", "exports"}


@dataclass
class BundleReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return not self.errors

    def add(self, message: str) -> None:
        self.errors.append(message)

    def as_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "errors": self.errors, "warnings": self.warnings, "counts": self.counts}


def _rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def _check_layout(root: Path, report: BundleReport) -> None:
    for entry in root.iterdir():
        name = entry.name
        if entry.is_dir():
            if name not in ALLOWED_DIRECTORIES:
                report.add(f"undeclared directory in bundle: {name}")
            continue
        if name in ALLOWED_TOP_LEVEL_FILES or any(name.startswith(prefix) for prefix in ALLOWED_PREFIXES):
            continue
        report.add(f"undeclared file in bundle: {name}")


def validate_bundle(root: Path, *, validator: Validator | None = None) -> BundleReport:
    validator = validator or Validator()
    report = BundleReport()
    root = root.resolve()
    if not root.is_dir():
        report.add(f"bundle directory does not exist: {root}")
        return report
    _check_layout(root, report)

    records: dict[str, dict[str, Any]] = {}
    cases: list[dict[str, Any]] = []
    file_records: list[dict[str, Any]] = []

    def load(relative: str, kind: str) -> dict[str, Any] | None:
        path = root / relative
        if not path.is_file():
            report.add(f"missing required record: {relative}")
            return None
        try:
            record = canonical.require_canonical(path.read_bytes(), path=relative)
            validator.validate(kind, record, path=relative)
        except ValidationError as exc:
            report.add(str(exc))
            return None
        records[kind] = record
        return record

    dataset = load("dataset.json", "dataset")
    case_set = load("case-set.json", "case-set")
    intervals = load("scored-intervals.json", "scored-intervals")
    cohort = load("cohort.json", "cohort")

    shard_files = sorted(root.glob("cases-*.jsonl"))
    if not shard_files:
        report.add("missing case shard (cases-*.jsonl)")
    for shard in shard_files:
        try:
            for record in canonical.parse_jsonl(shard.read_bytes(), path=_rel(shard, root)):
                validator.validate("case", record, path=_rel(shard, root))
                cases.append(record)
        except ValidationError as exc:
            report.add(str(exc))
    file_shards = sorted(root.glob("files-*.jsonl"))
    if not file_shards:
        report.add("missing encoded file inventory shard (files-*.jsonl)")
    actual_file_shards = []
    for shard in file_shards:
        try:
            payload = shard.read_bytes()
            parsed = canonical.parse_jsonl(payload, path=_rel(shard, root))
            for record in parsed:
                validator.validate("asset-file", record, path=_rel(shard, root))
                file_records.append(record)
            actual_file_shards.append(
                {
                    "shard_digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
                    "records": str(len(parsed)),
                    "bytes": str(len(payload)),
                }
            )
        except ValidationError as exc:
            report.add(str(exc))
    ids = [record.get("case_id") for record in cases]
    if len(set(ids)) != len(ids):
        report.add("duplicate case_id across case shards")

    if dataset is not None and cases:
        try:
            schemas.verify_dataset_identity(dataset, cases, path="dataset.json")
        except ValidationError as exc:
            report.add(str(exc))
        declared = sorted(dataset["file_shards"], key=lambda entry: entry["shard_digest"])
        actual = sorted(actual_file_shards, key=lambda entry: entry["shard_digest"])
        if declared != actual:
            report.add("encoded file inventory shards do not match dataset.json")
        case_ids = {record["case_id"] for record in cases}
        file_paths = [record["relative_path"] for record in file_records]
        if len(file_paths) != len(set(file_paths)):
            report.add("duplicate relative_path in encoded file inventory")
        file_case_roles = [(record["case_id"], record["role"]) for record in file_records]
        if len(file_case_roles) != len(set(file_case_roles)):
            report.add("duplicate case_id/role in encoded file inventory")
        cases_by_id = {record["case_id"]: record for record in cases}
        for entry in file_records:
            case = cases_by_id.get(entry["case_id"])
            if case is None:
                report.add(f"asset file inventory references unknown case {entry['case_id']}")
                continue
            if (
                entry["speaker_id"] != case["speaker_id"]
                or entry["session_id"] != case["session_id"]
                or entry["partition"] != case["source_partition"]
                or entry["sample_count"] != case["sample_count"]
            ):
                report.add(f"asset file metadata disagrees with case {entry['case_id']}")
        for case in cases:
            expected_roles = {"noisy"} | ({"clean"} if case["clean_file_digest"] is not None else set())
            actual_roles = {item["role"] for item in file_records if item["case_id"] == case["case_id"]}
            if expected_roles != actual_roles:
                report.add(f"case {case['case_id']} file roles mismatch: expected {sorted(expected_roles)}, got {sorted(actual_roles)}")
            for role, digest_field in (("clean", "clean_file_digest"), ("noisy", "noisy_file_digest")):
                if case[digest_field] is None and role == "clean":
                    continue
                file_entry = next(
                    (
                        item for item in file_records
                        if item["case_id"] == case["case_id"] and item["role"] == role
                    ),
                    None,
                )
                if file_entry is None:
                    report.add(f"case {case['case_id']} lacks {role} file inventory")
                elif file_entry["decoded_pcm_sha256"] != case[digest_field]:
                    report.add(f"case {case['case_id']} {role} PCM digest differs from file inventory")
        for entry in file_records:
            path = root / entry["relative_path"]
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
                info = path.lstat()
                if not path.is_file() or path.is_symlink() or info.st_nlink != 1:
                    raise ValidationError("asset is not an unlinked regular file", path=str(path))
                if str(path.stat().st_size) != entry["file_bytes"]:
                    raise ValidationError("encoded file byte count mismatch", path=str(path))
                if audio.encoded_digest(path) != entry["file_sha256"]:
                    raise ValidationError("encoded file SHA-256 mismatch", path=str(path))
                samples = audio.read_wav(path)
                if str(len(samples)) != entry["sample_count"]:
                    raise ValidationError("decoded sample count mismatch", path=str(path))
                if audio.pcm_digest(samples) != entry["decoded_pcm_sha256"]:
                    raise ValidationError("decoded PCM SHA-256 mismatch", path=str(path))
            except (OSError, ValueError, ValidationError) as exc:
                report.add(f"asset file validation failed for {entry['relative_path']}: {exc}")
        if case_set is not None:
            if case_set["dataset_id"] != dataset["dataset_id"]:
                report.add("case-set references a different dataset")
            if {entry["case_id"] for entry in case_set["cases"]} != case_ids:
                report.add("case-set case IDs do not match the case shards")
            if case_set["task"] != next(iter({record["task"] for record in cases}), case_set["task"]):
                report.add("case-set task differs from the case records")
        for record in cases:
            if record["dataset_id"] != dataset["dataset_id"]:
                report.add(f"case {record['case_id']} references a different dataset")

    if intervals is not None and case_set is not None:
        if intervals["case_set_id"] != case_set["case_set_id"]:
            report.add("scored intervals reference a different case set")
        expected_ids = {entry["case_id"] for entry in case_set["cases"]}
        delivered_ids = {entry["case_id"] for entry in intervals["entries"]}
        if expected_ids != delivered_ids:
            report.add(
                f"scored interval coverage mismatch: missing {sorted(expected_ids - delivered_ids)}, "
                f"extra {sorted(delivered_ids - expected_ids)}"
            )
        for entry in intervals["entries"]:
            match = next((case for case in case_set["cases"] if case["case_id"] == entry["case_id"]), None)
            if match is not None and int(entry["end_sample"]) > int(match["sample_count"]):
                report.add(f"scored interval for {entry['case_id']} exceeds the case length")

    if cohort is not None:
        if dataset is not None and cohort["dataset_manifest_id"] != dataset["dataset_id"]:
            report.add("cohort references a different dataset manifest")
        if case_set is not None and cohort["case_set_id"] != case_set["case_set_id"]:
            report.add("cohort references a different case set")
        if intervals is not None and cohort["scored_interval_set_id"] != intervals["scored_interval_set_id"]:
            report.add("cohort references a different scored interval set")
        for metric in cohort["metric_set"]:
            if metric["metric_id"] not in metrics.METRICS:
                report.add(f"cohort metric {metric['metric_id']} is not implemented here")
        recipe_files = {
            canonical.require_canonical(path.read_bytes(), path=_rel(path, root))["recipe_id"]
            for path in sorted(root.glob("recipe-*.json"))
        }
        for name, value in (
            ("preprocessing_recipe_id", cohort["preprocessing_recipe_id"]),
            ("alignment_protocol_id", cohort["alignment_protocol_id"]),
        ):
            if recipe_files and value not in recipe_files:
                report.add(f"cohort {name} does not match a bundled recipe record")

    requests: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "requests").glob("*.json")) if (root / "requests").is_dir() else []:
        try:
            record = canonical.require_canonical(path.read_bytes(), path=_rel(path, root))
            validator.validate("request", record, path=_rel(path, root))
            requests[record["request_id"]] = record
        except ValidationError as exc:
            report.add(str(exc))

    attempts = 0
    for attempt_dir in ledger.find_attempts(root):
        attempts += 1
        relative = _rel(attempt_dir, root)
        try:
            run = canonical.require_canonical((attempt_dir / "run.json").read_bytes())
            request = requests.get(run["request_id"])
            if request is None:
                report.add(f"{relative}: request {run['request_id']} is not bundled")
                continue
            ledger.verify_attempt(attempt_dir, request=request, validator=validator)
            entry = ledger.matrix_entry_for(request, run)
            observations = canonical.parse_jsonl((attempt_dir / "observations.jsonl").read_bytes())
            expected = {
                (case_id, metric_id)
                for case_id in entry["expected_case_ids"]
                for metric_id in entry["expected_metric_ids"]
            }
            matrix = aggregate.check_matrix(expected, observations)
            if not matrix["complete"]:
                report.add(
                    f"{relative}: incomplete expected matrix (missing {matrix['missing']}, "
                    f"extra {matrix['extra']}, duplicates {matrix['duplicates']})"
                )
            if run["status"] != matrix["status"]:
                report.add(
                    f"{relative}: run status {run['status']} disagrees with observation status {matrix['status']}"
                )
            core = canonical.require_canonical((attempt_dir / "core.json").read_bytes())
            if cohort is not None and run["comparison_cohort_id"] != cohort["comparison_cohort_id"]:
                report.add(f"{relative}: run cohort does not match cohort.json")
            if cohort is not None and core["comparison_cohort_id"] != cohort["comparison_cohort_id"]:
                report.add(f"{relative}: core cohort does not match cohort.json")
            if case_set is not None:
                missing_cases = set(entry["expected_case_ids"]) - {case["case_id"] for case in case_set["cases"]}
                if missing_cases:
                    report.add(f"{relative}: expected cases absent from the case set: {sorted(missing_cases)}")
            for row in observations:
                if row["attempt_id"] != run["attempt_id"]:
                    report.add(f"{relative}: observation belongs to a different attempt")
                    break
        except ValidationError as exc:
            report.add(str(exc))

    core_digests = {
        canonical.require_canonical((path / "core.json").read_bytes())["core_digest"]
        for path in ledger.find_attempts(root)
        if (path / "core.json").is_file()
    }
    for path in sorted((root / "reviews").glob("*.json")) if (root / "reviews").is_dir() else []:
        try:
            review = canonical.require_canonical(path.read_bytes(), path=_rel(path, root))
            validator.validate("review", review, path=_rel(path, root))
            if review["result_core_digest"] not in core_digests:
                report.add(f"{_rel(path, root)}: review references an unknown core")
        except ValidationError as exc:
            report.add(str(exc))

    report.counts.update(
        {
            "cases": len(cases),
            "requests": len(requests),
            "attempts": attempts,
            "reviews": len(list((root / "reviews").glob("*.json"))) if (root / "reviews").is_dir() else 0,
        }
    )
    if not core_digests and attempts:
        report.warnings.append("no sealed cores present")
    return report
