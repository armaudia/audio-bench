# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Offline schema loading, validation and code-level invariants.

JSON Schema (Draft 2020-12) covers shape and closed objects. Anything that needs recomputation or
cannot be expressed declaratively is enforced in :func:`check_semantics`: content IDs, digest
recomputation, sorted sets, uint64/int64 bounds, UTC parsing, interval arithmetic and referential
closure. No remote schema is ever fetched.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import importlib.resources
import os
import uuid
from pathlib import Path
from typing import Any, Mapping

import jsonschema
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource
from referencing.jsonschema import DRAFT202012

from . import canonical
from .errors import ValidationError

SCHEMA_FILE_NAMES = {
    "dataset": "dataset.schema.json",
    "asset-file": "asset-file.schema.json",
    "case": "case.schema.json",
    "case-set": "case-set.schema.json",
    "recipe": "recipe.schema.json",
    "cohort": "cohort.schema.json",
    "scored-intervals": "scored-intervals.schema.json",
    "request": "request.schema.json",
    "run": "run.schema.json",
    "observation": "observation.schema.json",
    "output": "output.schema.json",
    "inventory": "inventory.schema.json",
    "core": "core.schema.json",
    "review": "review.schema.json",
    "export": "export.schema.json",
    "impact-plan": "impact-plan.schema.json",
    "reconciliation-event": "reconciliation-event.schema.json",
    "latest-snapshot": "latest-snapshot.schema.json",
}

SDK_SCHEMA_FILES = {
    "descriptor": "descriptor.schema.json",
    "effective-config": "effective-config.schema.json",
}
SDK_SCHEMA_DIGESTS = {
    "descriptor": "sha256:9db5fee497272ecf2c734f31cfb0a4662b43c01d745f856745ca9bcdcdc9c2ba",
    "effective-config": "sha256:55956e149b3b8c420599c1a115e2b880ba4659c562128c207f89842b79cc5eea",
}

IDENTITY_ID_FIELD = {
    "case-set": "case_set_id",
    "recipe": "recipe_id",
    "cohort": "comparison_cohort_id",
    "scored-intervals": "scored_interval_set_id",
}

#: Dataset identity omits only its own ID. Encoded asset shards contain no dataset_id, and the
#: semantic case inventory digest is computed with each case's dataset_id omitted; this avoids a
#: cycle while binding both file bytes and the case/speaker/partition inventory.
DATASET_IDENTITY_OMITTED = ("dataset_id",)

DIGEST_FIELDS = {
    "dataset": ("dataset_id", "source.archive_sha256", "source.generator_digest", "case_inventory_digest", "file_shards[].shard_digest"),
    "case": ("dataset_id", "noisy_file_digest", "clean_file_digest", "annotations_digest"),
    "case-set": ("case_set_id", "dataset_id", "cases[].noisy_file_digest", "cases[].clean_file_digest", "protocol_digest"),
    "recipe": ("recipe_id",),
    "cohort": (
        "comparison_cohort_id",
        "dataset_manifest_id",
        "case_set_id",
        "preprocessing_recipe_id",
        "alignment_protocol_id",
        "scored_interval_set_id",
        "protocol_digest",
        "metric_set[].code_digest",
        "metric_set[].lock_digest",
        "metric_set[].settings_digest",
    ),
    "scored-intervals": ("scored_interval_set_id", "case_set_id", "protocol_digest"),
    "request": ("sdk_package_digest", "harness_digest", "registry_snapshot_id", "matrix[].cohort_id"),
    "run": (
        "comparison_cohort_id",
        "expected_case_metric_set_id",
        "sdk_package_digest",
        "provider_digest",
        "conformance_digest",
        "source_build_digest",
        "toolchain_lock_digest",
        "environment_digest",
    ),
    "observation": ("comparison_cohort_id", "output_pcm_digest"),
    "output": ("native_container_sha", "decoded_pcm_sha", "source_map_digest", "source_input_digest", "sdk_config_digest"),
    "inventory": ("expected_artifact_set_id", "actual_artifact_set_id", "files[].sha256", "files[].parent_digests[]"),
    "core": (
        "core_digest",
        "run_manifest_digest",
        "request_digest",
        "dataset_id",
        "comparison_cohort_id",
        "scored_interval_set_id",
        "metric_set_digest",
        "registry_snapshot_id",
        "observations_file_digest",
        "outputs_file_digest",
        "summary_digest",
        "inventory_digest",
        "predecessor_core_digest",
    ),
    "review": ("result_core_digest",),
    "export": ("public_core_digest", "public_descriptor_digest", "public_config_digest", "file_inventory[].sha256"),
}


def schema_dir() -> Path:
    """Locate the bundled schema directory without ever reaching the network."""
    override = os.environ.get("AUDIO_BENCH_SCHEMA_DIR")
    candidates = []
    if override:
        candidates.append(Path(override))
    here = Path(__file__).resolve()
    candidates.extend(
        [
            here.parents[2] / "schemas",  # editable/source checkout: <repo>/src/audio_bench/schemas.py
        ]
    )
    for candidate in candidates:
        if (candidate / "_defs.schema.json").is_file():
            return candidate
    packaged = Path(str(importlib.resources.files("audio_bench").joinpath("schema_data")))
    if (packaged / "_defs.schema.json").is_file():
        return packaged
    raise ValidationError("cannot locate bundled schemas; set AUDIO_BENCH_SCHEMA_DIR explicitly")


def load_schemas(directory: Path | None = None) -> dict[str, Any]:
    directory = directory or schema_dir()
    schemas: dict[str, Any] = {}
    for path in sorted(directory.glob("*.schema.json")):
        try:
            payload = path.read_bytes()
        except OSError as exc:  # pragma: no cover - local IO failure
            raise ValidationError(f"cannot read schema {path.name}: {exc}") from None
        record = canonical.strict_loads(payload, path=path.name, max_bytes=4 * 1024 * 1024)
        schema_id = record.get("$id")
        if not isinstance(schema_id, str):
            raise ValidationError(f"schema {path.name} has no $id", path=path.name)
        if schema_id in schemas:
            raise ValidationError(f"duplicate $id {schema_id!r}", path=path.name)
        record["__file__"] = path.name  # local index only, never part of validation
        schemas[schema_id] = record
    if not schemas:
        raise ValidationError(f"no schemas found in {directory}")
    return schemas


def schema_index(directory: Path | None = None) -> dict[str, Any]:
    """Exact schema IDs, files and digests, suitable for pinning in a lock file."""
    directory = directory or schema_dir()
    entries = []
    for path in sorted(directory.rglob("*.schema.json")):
        payload = path.read_bytes()
        entries.append(
            {
                "file": path.relative_to(directory).as_posix(),
                "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
            }
        )
    return {"schema_dir_version": "0.1", "entries": entries}


def load_sdk_schema(kind: str, directory: Path | None = None) -> Mapping[str, Any]:
    """Load an exact SDK-owned schema snapshot; do not copy or reinterpret its semantics."""
    if kind not in SDK_SCHEMA_FILES:
        raise ValidationError(f"unknown SDK schema kind {kind!r}")
    root = directory or schema_dir()
    path = root / "sdk" / SDK_SCHEMA_FILES[kind]
    payload = path.read_bytes()
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    if digest != SDK_SCHEMA_DIGESTS[kind]:
        raise ValidationError(f"pinned SDK schema digest mismatch for {kind}: {digest}", path=str(path))
    schema = canonical.strict_loads(payload, path=str(path), max_bytes=4 * 1024 * 1024)
    jsonschema.Draft202012Validator.check_schema(schema)
    return schema


def validate_sdk_record(kind: str, record: Any, directory: Path | None = None) -> None:
    schema = load_sdk_schema(kind, directory)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(record), key=lambda error: list(map(str, error.absolute_path)))
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.absolute_path) or "<root>"
        raise ValidationError(f"SDK {kind} schema error at {location}: {first.message}")


class Validator:
    """Offline validator for all bundled schemas."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or schema_dir()
        self.schemas = load_schemas(self.directory)
        resources = []
        for schema_id, schema in self.schemas.items():
            clean = {key: value for key, value in schema.items() if key != "__file__"}
            resources.append((schema_id, Resource.from_contents(clean, default_specification=DRAFT202012)))
        self.registry = Registry().with_resources(resources).with_resource(
            "https://schemas.audio-bench.invalid/defs/0.1",
            Resource.from_contents(
                {k: v for k, v in self.schemas["https://schemas.audio-bench.invalid/defs/0.1"].items() if k != "__file__"},
                default_specification=DRAFT202012,
            ),
        )
        self._validators: dict[str, jsonschema.Draft202012Validator] = {}

    def _validator(self, kind: str) -> jsonschema.Draft202012Validator:
        if kind not in SCHEMA_FILE_NAMES:
            raise ValidationError(f"unknown record kind {kind!r}")
        if kind not in self._validators:
            filename = SCHEMA_FILE_NAMES[kind]
            schema_id = next(
                (sid for sid, schema in self.schemas.items() if schema.get("__file__") == filename),
                None,
            )
            if schema_id is None:
                raise ValidationError(f"missing bundled schema {filename}")
            schema = {k: v for k, v in self.schemas[schema_id].items() if k != "__file__"}
            self._validators[kind] = jsonschema.Draft202012Validator(schema, registry=self.registry)
        return self._validators[kind]

    def schema(self, kind: str) -> Mapping[str, Any]:
        if kind not in SCHEMA_FILE_NAMES:
            raise ValidationError(f"unknown record kind {kind!r}")
        return {
            key: value
            for key, value in self.schemas[
                next(sid for sid, s in self.schemas.items() if s.get("__file__") == SCHEMA_FILE_NAMES[kind])
            ].items()
            if key != "__file__"
        }

    def validate(self, kind: str, record: Any, *, path: str | None = None) -> None:
        errors = sorted(self._validator(kind).iter_errors(record), key=lambda e: list(map(str, e.absolute_path)))
        if errors:
            first = errors[0]
            location = "/".join(str(part) for part in first.absolute_path) or "<root>"
            raise ValidationError(f"{kind} schema error at {location}: {first.message}", path=path)
        check_semantics(kind, record, path=path)

    def validate_bytes(self, kind: str, payload: bytes, *, path: str | None = None, canonical_required: bool = False) -> Any:
        record = (
            canonical.require_canonical(payload, path=path)
            if canonical_required
            else canonical.strict_loads(payload, path=path)
        )
        self.validate(kind, record, path=path)
        return record


# --- semantic invariants ---------------------------------------------------------------------


def _parse_utc(value: str, field: str, *, path: str | None) -> None:
    try:
        parsed = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationError(f"{field} is not a parseable UTC timestamp", path=path) from None
    if parsed.utcoffset() != _dt.timedelta(0):
        raise ValidationError(f"{field} must be UTC", path=path)


def _walk(record: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(record, Mapping):
        for key, value in record.items():
            out.append((f"{prefix}.{key}" if prefix else key, value))
            out.extend(_walk(value, f"{prefix}.{key}" if prefix else key))
    elif isinstance(record, list):
        for index, value in enumerate(record):
            out.append((f"{prefix}[{index}]", value))
            out.extend(_walk(value, f"{prefix}[{index}]"))
    return out


def _digest_values(record: Any, spec: str) -> list[tuple[str, Any]]:
    """Resolve an auditable field path such as ``files[].parent_digests[]`` to (label, value)."""
    segments = spec.split(".")
    current: list[tuple[str, Any]] = [("", record)]
    for index, segment in enumerate(segments):
        is_list = segment.endswith("[]")
        name = segment[:-2] if is_list else segment
        next_values: list[tuple[str, Any]] = []
        for label, value in current:
            if not isinstance(value, Mapping) or name not in value:
                continue
            child = value[name]
            child_label = f"{label}.{name}" if label else name
            if is_list:
                if not isinstance(child, list):
                    continue
                for entry_index, entry in enumerate(child):
                    next_values.append((f"{child_label}[{entry_index}]" + ("." if index < len(segments) - 1 else ""), entry))
            else:
                next_values.append((child_label + ("." if index < len(segments) - 1 else ""), child))
        current = next_values
    return [(label.rstrip("."), value) for label, value in current]


def _check_digest_fields(kind: str, record: Mapping[str, Any], *, path: str | None) -> None:
    for spec in DIGEST_FIELDS.get(kind, ()):  # exact field paths keep this auditable
        for label, value in _digest_values(record, spec):
            if value is not None and not canonical.is_digest(value):
                raise ValidationError(f"{label} is not a sha256 digest", path=path)


def _check_utc_fields(kind: str, record: Mapping[str, Any], *, path: str | None) -> None:
    names = {
        "request": ("created_at",),
        "run": ("started_at", "ended_at"),
        "review": ("reviewed_at",),
        "export": ("approved_at",),
        "dataset": ("rights.acquisition.reviewed_at", "rights.evaluation.reviewed_at", "rights.redistribution.reviewed_at", "rights.public_playback.reviewed_at"),
    }.get(kind, ())
    for name in names:
        value: Any = record
        for part in name.split("."):
            value = value.get(part) if isinstance(value, Mapping) else None
        if not isinstance(value, str):
            raise ValidationError(f"{name} is required", path=path)
        _parse_utc(value, name, path=path)


def check_semantics(kind: str, record: Any, *, path: str | None = None) -> None:
    if not isinstance(record, Mapping):
        raise ValidationError(f"{kind} record must be an object", path=path)
    _check_digest_fields(kind, record, path=path)
    _check_utc_fields(kind, record, path=path)
    # No integer may exceed the safe identity range; counters are canonical strings.
    for field, value in _walk(record):
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and abs(value) > canonical.SAFE_INTEGER_MAX:
            raise ValidationError(f"{field}: integer exceeds safe identity range", path=path)
        if isinstance(value, float) and value != value:  # NaN cannot arrive via strict parse
            raise ValidationError(f"{field}: NaN value", path=path)

    if kind in IDENTITY_ID_FIELD:
        canonical.verify_content_id(record, IDENTITY_ID_FIELD[kind], path=path)

    if kind == "dataset":
        shards = record["file_shards"]
        digests = [entry["shard_digest"] for entry in shards]
        if digests != sorted(digests) or len(set(digests)) != len(digests):
            raise ValidationError("file_shards must be sorted by shard_digest with no duplicates", path=path)
        for entry in shards:
            _check_uint(entry["records"], "file_shards.records", path=path)
            _check_uint(entry["bytes"], "file_shards.bytes", path=path)
        if record["source"]["kind"] == "https_archive":
            _check_uint(record["source"]["archive_bytes"], "source.archive_bytes", path=path)
            if record["source"]["archive_bytes"] == "0":
                raise ValidationError("an official dataset manifest needs a non-empty source archive", path=path)
        for scope in ("acquisition", "evaluation", "redistribution", "public_playback"):
            entry = record["rights"][scope]
            if entry["decision"] == "unknown":
                # Explicitly allowed by the spec: unknown means denied for the scopes that need it.
                continue

    if kind == "asset-file":
        _check_uint(record["file_bytes"], "file_bytes", path=path)
        _check_uint(record["sample_count"], "sample_count", path=path)
        source_path = record["relative_path"]
        if source_path.startswith("/") or any(part in ("", ".", "..") for part in source_path.split("/")):
            raise ValidationError("asset relative_path must be a clean relative path", path=path)

    if kind == "case":
        _check_uint(record["sample_count"], "sample_count", path=path)
        source_path = record["source_path"]
        if source_path.startswith("/") or any(part in ("", ".", "..") for part in source_path.split("/")):
            raise ValidationError("source_path must be a clean relative path", path=path)
        if record["clean_file_digest"] is not None and record["sample_count"] == "0":
            raise ValidationError("a paired case must contain samples", path=path)

    if kind == "case-set":
        cases = record["cases"]
        ids = [entry["case_id"] for entry in cases]
        if len(set(ids)) != len(ids):
            raise ValidationError("case set contains duplicate case_ids", path=path)
        if ids != sorted(ids):
            raise ValidationError("case set entries must be sorted by case_id", path=path)
        for entry in cases:
            _check_uint(entry["sample_count"], f"cases[{entry['case_id']}].sample_count", path=path)

    if kind == "scored-intervals":
        entries = record["entries"]
        ids = [entry["case_id"] for entry in entries]
        if len(set(ids)) != len(ids):
            raise ValidationError("scored intervals contain duplicate case_ids", path=path)
        if ids != sorted(ids):
            raise ValidationError("scored interval entries must be sorted by case_id", path=path)
        for entry in entries:
            start = int(entry["start_sample"])
            end = int(entry["end_sample"])
            if end <= start:
                raise ValidationError(f"{entry['case_id']}: interval must be non-empty half-open", path=path)
            _check_uint(entry["edge_exclusion_start"], "edge_exclusion_start", path=path)
            _check_uint(entry["edge_exclusion_end"], "edge_exclusion_end", path=path)

    if kind == "request":
        _check_uint(record["sequence"], "sequence", path=path)
        _check_uuid(record["request_id"], "request_id", path=path)
        matrix = record["matrix"]
        keys = [(entry["configuration_id"], entry["cohort_id"]) for entry in matrix]
        if len(set(keys)) != len(keys):
            raise ValidationError("request matrix has duplicate configuration/cohort pairs", path=path)
        for entry in matrix:
            canonical.expect_digest(entry["configuration_id"], "configuration_id", path=path)
            if len(set(entry["expected_case_ids"])) != len(entry["expected_case_ids"]):
                raise ValidationError("expected_case_ids contains duplicates", path=path)
            if len(set(entry["expected_metric_ids"])) != len(entry["expected_metric_ids"]):
                raise ValidationError("expected_metric_ids contains duplicates", path=path)

    if kind in ("reconciliation-event", "latest-snapshot"):
        _check_uint(record["sequence"], "sequence", path=path)
        if record["sequence"] == "0":
            raise ValidationError("reconciliation sequence starts at 1", path=path)
    if kind == "reconciliation-event":
        if record["complete"] and record["core_digest"] is None:
            raise ValidationError("complete reconciliation event requires a core digest", path=path)

    if kind == "run":
        _check_uuid(record["run_id"], "run_id", path=path)
        _check_uuid(record["attempt_id"], "attempt_id", path=path)
        canonical.expect_digest(record["configuration_id"], "configuration_id", path=path)
        if record["core_digest"] is not None:
            raise ValidationError("run.core_digest must stay null; the core references the manifest digest", path=path)
        if record["status"] == "passed" and record["reason"] is not None:
            raise ValidationError("a passed run must not carry a failure reason", path=path)
        if record["status"] in ("failed", "blocked", "invalid") and record["reason"] is None:
            raise ValidationError("a non-passed run must name a reason", path=path)
        if record["ended_at"] < record["started_at"]:
            raise ValidationError("run ended before it started", path=path)

    if kind == "observation":
        canonical.expect_digest(record["configuration_id"], "configuration_id", path=path)
        status = record["execution_status"]
        value = record["value"]
        if status == "passed" and value is None and record["reason"] is None:
            raise ValidationError("passed observation with null value needs an undefined-metric reason", path=path)
        if value is not None and status != "passed":
            raise ValidationError("only a passed observation may carry a finite value", path=path)
        if status in ("failed", "blocked", "invalid") and record["reason"] is None:
            raise ValidationError("failed/blocked/invalid observation needs a reason", path=path)
        for name in ("numerator", "denominator"):
            if record[name] is not None:
                _check_uint(record[name], name, path=path)
        interval = record["valid_interval"]
        if interval is not None:
            start = int(interval["start_sample"])
            end = int(interval["end_sample"])
            if end < start:
                raise ValidationError("valid_interval end precedes start", path=path)

    if kind == "output":
        canonical.expect_digest(record["configuration_id"], "configuration_id", path=path)
        _check_uint(record["sample_count"], "sample_count", path=path)
        if record["sdk_config_digest"] != record["configuration_id"]:
            raise ValidationError("output configuration_id must equal the SDK effective-config digest", path=path)
        if record["mode"] == "paced" and record["workload_id"] is None:
            raise ValidationError("paced output requires a workload_id", path=path)
        if record["mode"] == "sequential" and record["workload_id"] is not None:
            raise ValidationError("sequential output must not claim a runtime workload", path=path)
        if record["format"]["subtype"] != "FLOAT" and record["preview"] is None:
            raise ValidationError("PCM16 artifacts must be declared as previews with a recipe", path=path)

    if kind == "inventory":
        paths = [entry["path"] for entry in record["files"]]
        if len(set(paths)) != len(paths):
            raise ValidationError("inventory has duplicate paths", path=path)
        normalized = [os.path.normpath(item) for item in paths]
        if len(set(normalized)) != len(normalized):
            raise ValidationError("inventory paths collide after normalization", path=path)
        for entry in record["files"]:
            _check_uint(entry["bytes"], f"files[{entry['path']}].bytes", path=path)
            for digest in entry["parent_digests"]:
                canonical.expect_digest(digest, "parent_digest", path=path)
        _check_uint(record["expected_case_metric_count"], "expected_case_metric_count", path=path)
        _check_uint(record["actual_case_metric_count"], "actual_case_metric_count", path=path)
        if record["complete"]:
            if record["missing_ids"] or record["extra_ids"]:
                raise ValidationError("an inventory claiming completeness cannot have missing/extra IDs", path=path)
            if record["expected_case_metric_count"] != record["actual_case_metric_count"]:
                raise ValidationError("complete inventory counts disagree", path=path)
            if record["expected_artifact_set_id"] != record["actual_artifact_set_id"]:
                raise ValidationError("complete inventory artifact sets disagree", path=path)

    if kind == "core":
        canonical.expect_digest(record["configuration_id"], "configuration_id", path=path)
        canonical.verify_content_id(record, "core_digest", path=path)
        if (record["predecessor_core_digest"] is None) != (record["correction_reason"] is None):
            raise ValidationError("correction lineage requires predecessor_core_digest and correction_reason together", path=path)
        if record["predecessor_core_digest"] == record["core_digest"]:
            raise ValidationError("a core cannot be its own predecessor", path=path)

    if kind == "review":
        if record["decision"] == "reviewed" and record["reproduction"] == "not_reproduced":
            # Allowed, but the report must not present it as a reproduction.
            return
        qualification = record["qualification"]
        if qualification is not None and qualification["decision"] != "not_assessed":
            if record["decision"] != "reviewed":
                raise ValidationError("qualification requires a reviewed core", path=path)


def _check_uint(value: Any, field: str, *, path: str | None) -> None:
    if not canonical.is_uint_string(value):
        raise ValidationError(f"{field} must be a canonical uint64 string", path=path)


def _check_uuid(value: Any, field: str, *, path: str | None) -> None:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise ValidationError(f"{field} must be a UUID", path=path) from None
    if str(parsed) != value:
        raise ValidationError(f"{field} must be a lowercase canonical UUID", path=path)


CASE_IDENTITY_FIELDS = (
    "case_id",
    "source_path",
    "noisy_file_digest",
    "clean_file_digest",
    "sample_rate_hz",
    "channels",
    "sample_count",
    "speaker_id",
    "session_id",
    "task",
    "annotations_digest",
    "source_partition",
    "allowed_use",
)


def case_inventory_digest(case_records: list[Mapping[str, Any]]) -> str:
    """Digest of the sorted case entries with ``dataset_id`` omitted (no hash cycle)."""
    entries = []
    for record in sorted(case_records, key=lambda item: item["case_id"]):
        missing = [field for field in CASE_IDENTITY_FIELDS if field not in record]
        if missing:
            raise ValidationError(f"case {record.get('case_id', '<unknown>')} lacks {missing}")
        entries.append({field: record[field] for field in CASE_IDENTITY_FIELDS})
    return canonical.digest_of(entries)


def dataset_identity_preimage(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key not in DATASET_IDENTITY_OMITTED}


def dataset_content_id(record: Mapping[str, Any]) -> str:
    return canonical.digest_of(dataset_identity_preimage(record))


def verify_dataset_identity(
    record: Mapping[str, Any], case_records: list[Mapping[str, Any]], *, path: str | None = None
) -> None:
    if record.get("identity_algorithm") != canonical.JCS_IDENTITY_ALGORITHM:
        raise ValidationError("dataset identity_algorithm is not jcs-sha256-v1", path=path)
    if record["case_inventory_digest"] != case_inventory_digest(case_records):
        raise ValidationError("dataset case_inventory_digest does not match the case shards", path=path)
    expected = dataset_content_id(record)
    if record["dataset_id"] != expected:
        raise ValidationError(f"dataset_id {record['dataset_id']} != recomputed {expected}", path=path)
