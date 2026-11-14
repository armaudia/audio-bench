# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Immutable attempt storage and core sealing without hash cycles.

Sealing order (EVIDENCE_SPEC "Core sealing without hash cycles"):

1. request/cohort/manifests/expected inventory are frozen before execution (written elsewhere);
2. payload files (observations, outputs, summary, rendered audio) are stored;
3. the inventory covers only those payload files — never itself, ``core.json``, attestations or
   reviews;
4. the run manifest is written with ``core_digest = null`` permanently and hashed;
5. ``core.json`` references that digest and the payload digests and is written exactly once.

Existing paths are immutable: rewriting identical bytes is idempotent, different bytes raises
:class:`ImmutableViolation`. Corrections create a new attempt and a new core with explicit lineage.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from filelock import FileLock

from . import aggregate, canonical
from .errors import ImmutableViolation, ValidationError
from .schemas import Validator

PAYLOAD_NAMES = ("observations.jsonl", "outputs.jsonl", "summary.json")
CONTROL_NAMES = ("run.json", "core.json", "inventory.json", "attestation.json")


def sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def sealed_write(path: Path, payload: bytes) -> None:
    """Write once, atomically, with fsync of file and directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == payload:
            return
        raise ImmutableViolation(f"{path} already exists with different bytes; evidence is immutable")
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    with open(temporary, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    # Hard-link publication is atomic and fails if another writer created ``path`` first.
    # ``replace`` would silently overwrite an immutable record in a race.
    try:
        os.link(temporary, path)
    except FileExistsError:
        if path.read_bytes() != payload:
            temporary.unlink(missing_ok=True)
            raise ImmutableViolation(f"{path} was concurrently created with different bytes")
    finally:
        temporary.unlink(missing_ok=True)
    try:
        fd = os.open(path.parent, os.O_RDONLY)
    except OSError:  # pragma: no cover - platform without directory fsync
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def request_digest(request: Mapping[str, Any]) -> str:
    return canonical.digest_of(request)


def store_request(root: Path, request: Mapping[str, Any], *, validator: Validator | None = None) -> Path:
    validator = validator or Validator()
    validator.validate("request", request)
    root.mkdir(parents=True, exist_ok=True)
    requests_dir = root / "requests"
    requests_dir.mkdir(parents=True, exist_ok=True)
    path = requests_dir / f"{request['request_id']}.json"
    sequence = int(request["sequence"])
    payload = canonical.dumps(request)
    if sequence < 1:
        raise ValidationError("trusted request sequence starts at 1")
    with FileLock(str(requests_dir / ".sequence.lock")):
        if path.exists():
            if path.read_bytes() == payload:
                return path
            raise ImmutableViolation(f"{path} already exists with different bytes")
        prior = []
        for existing in requests_dir.glob("*.json"):
            record = canonical.require_canonical(existing.read_bytes(), path=str(existing))
            validator.validate("request", record, path=str(existing))
            if record["source_request_key"] == request["source_request_key"]:
                prior.append(int(record["sequence"]))
        if prior and sequence <= max(prior):
            raise ValidationError(
                f"request sequence {sequence} is not greater than prior sequence {max(prior)} "
                f"for source_request_key {request['source_request_key']}"
            )
        sealed_write(path, payload)
    return path


def start_attempt(root: Path, run: Mapping[str, Any], *, validator: Validator | None = None) -> Path:
    validator = validator or Validator()
    validator.validate("run", run)
    directory = root / "runs" / run["run_id"] / run["attempt_id"]
    sealed_write(directory / "run.json", canonical.dumps(run))
    return directory


def seal_attempt(
    attempt_dir: Path,
    *,
    request: Mapping[str, Any],
    matrix_entry: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
    outputs: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
    dataset_id: str,
    comparison_cohort_id: str,
    scored_interval_set_id: str,
    metric_set_digest: str,
    registry_snapshot_id: str,
    predecessor_core_digest: str | None = None,
    correction_reason: str | None = None,
    validator: Validator | None = None,
) -> dict[str, Any]:
    validator = validator or Validator()
    run_bytes = (attempt_dir / "run.json").read_bytes()
    run = canonical.require_canonical(run_bytes)
    validator.validate("run", run)
    if run["core_digest"] is not None:
        raise ValidationError("run manifest must keep core_digest null")
    if run["configuration_id"] != matrix_entry["configuration_id"]:
        raise ValidationError("run configuration identity differs from its frozen request matrix")
    for row in observations:
        validator.validate("observation", row)
        if row["configuration_id"] != run["configuration_id"]:
            raise ValidationError("observation configuration identity differs from run")
    for row in outputs:
        validator.validate("output", row)
        if row["configuration_id"] != run["configuration_id"]:
            raise ValidationError("output configuration identity differs from run")

    expected = {
        (case_id, metric_id)
        for case_id in matrix_entry["expected_case_ids"]
        for metric_id in matrix_entry["expected_metric_ids"]
    }
    matrix = aggregate.check_matrix(expected, observations)
    summary_record = dict(summary)
    summary_record["attempt_status"] = matrix["status"]
    summary_record["complete"] = matrix["complete"]
    summary_record["missing"] = [f"{case}/{metric}" for case, metric in matrix["missing"]]
    summary_record["extra"] = [f"{case}/{metric}" for case, metric in matrix["extra"]]
    summary_record["duplicates"] = [f"{case}/{metric}" for case, metric in matrix["duplicates"]]
    summary_record["expected_case_metric_count"] = str(matrix["expected"])
    summary_record["delivered_case_metric_count"] = str(matrix["delivered"])

    observations_payload = canonical.jsonl_bytes(observations)
    outputs_payload = canonical.jsonl_bytes(outputs)
    summary_payload = canonical.dumps(summary_record)
    sealed_write(attempt_dir / "observations.jsonl", observations_payload)
    sealed_write(attempt_dir / "outputs.jsonl", outputs_payload)
    sealed_write(attempt_dir / "summary.json", summary_payload)

    payload_files = sorted(
        [
            path
            for path in attempt_dir.rglob("*")
            if path.is_file() and path.name not in CONTROL_NAMES and not path.name.startswith(".")
        ]
    )
    files = []
    for path in payload_files:
        relative = str(path.relative_to(attempt_dir))
        if relative.startswith("inventory"):
            continue
        payload = path.read_bytes()
        classification = (
            "observation"
            if path.name == "observations.jsonl"
            else "output"
            if path.name == "outputs.jsonl"
            else "summary"
            if path.name == "summary.json"
            else "preview"
            if path.suffix == ".wav"
            else "attestation"
        )
        files.append(
            {
                "path": relative,
                "media_type": "audio/wav" if path.suffix == ".wav" else "application/jsonl" if path.suffix == ".jsonl" else "application/json",
                "bytes": str(len(payload)),
                "sha256": sha256_bytes(payload),
                "classification": classification,
                "parent_digests": [],
            }
        )
    inventory = {
        "schema_id": "audio-bench/inventory/0.1",
        "files": files,
        "expected_artifact_set_id": expected_artifact_set_id(
            matrix_entry, request.get("required_artifact_types", ())
        ),
        "actual_artifact_set_id": canonical.digest_of(sorted(entry["path"] for entry in files)),
        "expected_case_metric_count": str(matrix["expected"]),
        "actual_case_metric_count": str(len({(row["case_id"], row["metric_id"]) for row in observations})),
        "missing_ids": [f"{case}/{metric}" for case, metric in matrix["missing"]],
        "extra_ids": [f"{case}/{metric}" for case, metric in matrix["extra"]],
        "complete": matrix["complete"] and matrix["status"] in ("passed", "failed", "not_applicable"),
    }
    validator.validate("inventory", inventory)
    inventory_payload = canonical.dumps(inventory)
    sealed_write(attempt_dir / "inventory.json", inventory_payload)

    core = {
        "schema_id": "audio-bench/core/0.1",
        "identity_algorithm": canonical.JCS_IDENTITY_ALGORITHM,
        "core_digest": "sha256:" + "0" * 64,
        "run_manifest_digest": sha256_bytes(run_bytes),
        "request_digest": request_digest(request),
        "dataset_id": dataset_id,
        "comparison_cohort_id": comparison_cohort_id,
        "configuration_id": run["configuration_id"],
        "scored_interval_set_id": scored_interval_set_id,
        "metric_set_digest": metric_set_digest,
        "registry_snapshot_id": registry_snapshot_id,
        "observations_file_digest": sha256_bytes(observations_payload),
        "outputs_file_digest": sha256_bytes(outputs_payload),
        "summary_digest": sha256_bytes(summary_payload),
        "inventory_digest": sha256_bytes(inventory_payload),
        "predecessor_core_digest": predecessor_core_digest,
        "correction_reason": correction_reason,
    }
    core["core_digest"] = canonical.content_id(core, "core_digest")
    validator.validate("core", core)
    core_payload = canonical.dumps(core)
    sealed_write(attempt_dir / "core.json", core_payload)
    verify_attempt(attempt_dir, request=request, validator=validator)
    return core


def expected_artifact_set_id(
    matrix_entry: Mapping[str, Any],
    required_artifact_types: Iterable[str] = ("observation", "output", "summary"),
) -> str:
    """Hash the exact expected payload paths; payload byte hashes are verified separately."""
    declared = matrix_entry.get("expected_artifact_paths")
    if declared is not None:
        if len(set(declared)) != len(declared):
            raise ValidationError("expected_artifact_paths contains duplicates")
        return canonical.digest_of(sorted(declared))
    names = {
        "observation": "observations.jsonl",
        "output": "outputs.jsonl",
        "summary": "summary.json",
    }
    paths = sorted({names[item] for item in required_artifact_types if item in names})
    return canonical.digest_of(paths)


def verify_attempt(
    attempt_dir: Path,
    *,
    request: Mapping[str, Any] | None = None,
    validator: Validator | None = None,
) -> dict[str, Any]:
    """Recompute every digest in a sealed attempt in a fresh process."""
    validator = validator or Validator()
    run_bytes = (attempt_dir / "run.json").read_bytes()
    run = canonical.require_canonical(run_bytes, path="run.json")
    validator.validate("run", run)
    config_path = attempt_dir / "effective-config.json"
    if not config_path.is_file():
        raise ValidationError("attempt is missing frozen effective-config.json", path=str(attempt_dir))
    config_bytes = config_path.read_bytes()
    canonical.require_canonical(config_bytes, path="effective-config.json")
    if sha256_bytes(config_bytes) != run["configuration_id"]:
        raise ValidationError("effective config bytes do not match run configuration_id", path=str(attempt_dir))
    environment_path = attempt_dir / "environment.json"
    if environment_path.is_file():
        environment = canonical.require_canonical(environment_path.read_bytes(), path="environment.json")
        if canonical.digest_of(environment) != run["environment_digest"]:
            raise ValidationError("environment snapshot does not match run environment_digest")
    descriptor_path = attempt_dir / "provider-descriptor.json"
    if run["provider_digest"] is not None:
        if not descriptor_path.is_file() or sha256_bytes(descriptor_path.read_bytes()) != run["provider_digest"]:
            raise ValidationError("provider descriptor bytes do not match run provider_digest")
    core = canonical.require_canonical((attempt_dir / "core.json").read_bytes(), path="core.json")
    validator.validate("core", core)
    inventory = canonical.require_canonical((attempt_dir / "inventory.json").read_bytes(), path="inventory.json")
    validator.validate("inventory", inventory)
    observations = canonical.parse_jsonl((attempt_dir / "observations.jsonl").read_bytes(), path="observations.jsonl")
    outputs = canonical.parse_jsonl((attempt_dir / "outputs.jsonl").read_bytes(), path="outputs.jsonl")
    for row in observations:
        validator.validate("observation", row)
        if row["configuration_id"] != run["configuration_id"]:
            raise ValidationError("observation configuration identity differs from run")
    for row in outputs:
        validator.validate("output", row)
        if row["configuration_id"] != run["configuration_id"]:
            raise ValidationError("output configuration identity differs from run")

    if core["run_manifest_digest"] != sha256_bytes(run_bytes):
        raise ValidationError("core does not reference this run manifest", path=str(attempt_dir))
    if core["configuration_id"] != run["configuration_id"]:
        raise ValidationError("core configuration identity differs from run", path=str(attempt_dir))
    if request is not None and core["request_digest"] != request_digest(request):
        raise ValidationError("core does not reference this request", path=str(attempt_dir))
    for field, name in (
        ("observations_file_digest", "observations.jsonl"),
        ("outputs_file_digest", "outputs.jsonl"),
        ("summary_digest", "summary.json"),
        ("inventory_digest", "inventory.json"),
    ):
        if core[field] != sha256_bytes((attempt_dir / name).read_bytes()):
            raise ValidationError(f"{field} does not match {name}", path=str(attempt_dir))

    declared = {entry["path"]: entry for entry in inventory["files"]}
    present = {
        str(path.relative_to(attempt_dir))
        for path in attempt_dir.rglob("*")
        if path.is_file() and path.name not in (*CONTROL_NAMES, "inventory.json") and not path.name.startswith(".")
    }
    if set(declared) != present:
        raise ValidationError(
            f"inventory/payload mismatch: declared {sorted(declared)}, present {sorted(present)}",
            path=str(attempt_dir),
        )
    for relative, entry in declared.items():
        payload = (attempt_dir / relative).read_bytes()
        if entry["sha256"] != sha256_bytes(payload) or entry["bytes"] != str(len(payload)):
            raise ValidationError(f"payload digest mismatch for {relative}", path=str(attempt_dir))
    actual_artifact_set_id = canonical.digest_of(sorted(declared))
    if inventory["actual_artifact_set_id"] != actual_artifact_set_id:
        raise ValidationError("inventory actual_artifact_set_id does not match its paths", path=str(attempt_dir))
    if request is not None:
        expected = expected_artifact_set_id(
            matrix_entry_for(request, run), request.get("required_artifact_types", ())
        )
        if inventory["expected_artifact_set_id"] != expected:
            raise ValidationError("inventory expected_artifact_set_id does not match the frozen request")
    return {"core": core, "run": run, "inventory": inventory, "observations": observations, "outputs": outputs}


def append_review(root: Path, review: Mapping[str, Any], *, validator: Validator | None = None) -> Path:
    """Reviews live outside the core preimage so no hash cycle or inheritance exists."""
    validator = validator or Validator()
    validator.validate("review", review)
    path = root / "reviews" / f"{review['review_id']}.json"
    sealed_write(path, canonical.dumps(review))
    return path


def find_attempts(root: Path) -> list[Path]:
    runs = root / "runs"
    if not runs.is_dir():
        return []
    return sorted(path.parent for path in runs.glob("*/*/run.json"))


def load_request_for_attempt(root: Path, run: Mapping[str, Any]) -> dict[str, Any]:
    path = root / "requests" / f"{run['request_id']}.json"
    if not path.is_file():
        raise ValidationError(f"request {run['request_id']} is missing", path=str(path))
    request = canonical.require_canonical(path.read_bytes(), path=str(path))
    return request


def matrix_entry_for(request: Mapping[str, Any], run: Mapping[str, Any]) -> dict[str, Any]:
    for entry in request["matrix"]:
        if (
            entry["configuration_id"] == run["configuration_id"]
            and entry["cohort_id"] == run["comparison_cohort_id"]
        ):
            if (run.get("provider_digest") is not None
                    and entry.get("provider_digest") != run["provider_digest"]):
                raise ValidationError("run provider identity differs from its frozen request matrix")
            return entry
    raise ValidationError(
        f"run {run['run_id']} does not belong to any frozen request matrix entry"
    )


def copy_attempt(source: Path, destination: Path) -> None:
    """Copy an attempt for export staging; verification happens on the copy's own bytes."""
    if destination.exists():
        raise ImmutableViolation(f"{destination} already exists")
    shutil.copytree(source, destination)
