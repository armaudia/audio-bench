# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Durable local revision planning and serialized latest-snapshot reconciliation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Mapping, Any

from filelock import FileLock

from . import canonical
from .errors import ImmutableViolation, ValidationError
from .ledger import sealed_write
from .schemas import Validator


def impact_plan(paths: Iterable[str]) -> dict[str, Any]:
    """Conservative local invalidation plan; an unknown path invalidates the full manual flow."""
    changed = sorted(set(paths))
    if not changed:
        raise ValidationError("impact planning requires at least one changed path")
    if any(path.startswith(("schemas/", "src/audio_bench/metrics.py", "src/audio_bench/scoring.py")) for path in changed):
        tier = "rescore_and_revalidate_all"
    elif any(path.startswith(("deps/", "native/", "scripts/verify_sdk_snapshot.py")) for path in changed):
        tier = "reexecute_affected_configurations_and_revalidate"
    elif any(path.startswith(("manifests/", "suites/")) for path in changed):
        tier = "rebuild_affected_cohorts_and_reexecute"
    elif any(path.startswith(("report/", "src/audio_bench/report")) for path in changed):
        tier = "rebuild_reports"
    elif all(path.startswith(("docs/", "README", "HANDOFF.md")) for path in changed):
        tier = "documentation_only"
    else:
        tier = "full_revalidation_and_reexecution"
    record = {
        "schema_id": "audio-bench/impact-plan/0.1",
        "changed_paths": changed,
        "tier": tier,
        "requires_manual_review": True,
    }
    Validator().validate("impact-plan", record)
    return record


def _safe_component(value: str, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
        raise ValidationError(f"{name} must be a bounded path-safe identifier")
    return value


def reconcile_latest(
    root: Path,
    *,
    source_branch: str,
    scope: str,
    sequence: int,
    request_id: str,
    core_digest: str | None,
    complete: bool,
) -> dict[str, Any]:
    """Record an immutable local event and advance only a complete, newer snapshot.

    This is not a publisher. Callers still own review, transport, and external append-only storage.
    """
    branch = _safe_component(source_branch, "source_branch")
    scope = _safe_component(scope, "scope")
    request = _safe_component(request_id, "request_id")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1 or sequence > (1 << 64) - 1:
        raise ValidationError("sequence must be uint64 and start at 1")
    if complete and not canonical.is_digest(core_digest):
        raise ValidationError("complete reconciliation requires a core digest")
    if not complete and core_digest is not None and not canonical.is_digest(core_digest):
        raise ValidationError("core_digest must be null or a SHA-256 digest")

    event = {
        "schema_id": "audio-bench/reconciliation-event/0.1",
        "source_branch": branch,
        "scope": scope,
        "sequence": str(sequence),
        "request_id": request,
        "core_digest": core_digest,
        "complete": complete,
    }
    validator = Validator()
    validator.validate("reconciliation-event", event)
    state = "complete" if complete else "incomplete"
    event_path = root / "reconciliation" / branch / scope / f"{sequence:020d}-{request}-{state}.json"
    latest_path = root / "latest" / branch / f"{scope}.json"
    with FileLock(str(root / "machine-owner.lock")):
        sealed_write(event_path, canonical.dumps(event))
        latest = None
        if latest_path.is_file():
            latest = canonical.require_canonical(latest_path.read_bytes(), path=str(latest_path))
            validator.validate("latest-snapshot", latest, path=str(latest_path))
        if not complete:
            return {"event": str(event_path), "advanced": False, "reason": "incomplete_matrix"}
        if latest is not None:
            prior_sequence = int(latest["sequence"])
            if sequence < prior_sequence:
                return {"event": str(event_path), "advanced": False, "reason": "out_of_order"}
            if sequence == prior_sequence:
                if latest["request_id"] == request and latest["core_digest"] == core_digest:
                    return {"event": str(event_path), "advanced": False, "reason": "idempotent"}
                raise ImmutableViolation("same source/scope sequence cannot publish different evidence")
        latest_record = {
            "schema_id": "audio-bench/latest-snapshot/0.1",
            "source_branch": branch,
            "scope": scope,
            "sequence": str(sequence),
            "request_id": request,
            "core_digest": core_digest,
        }
        validator.validate("latest-snapshot", latest_record)
        latest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = latest_path.with_name(latest_path.name + ".new")
        temporary.write_bytes(canonical.dumps(latest_record))
        temporary.replace(latest_path)
        return {"event": str(event_path), "advanced": True, "reason": "new_complete_snapshot"}
