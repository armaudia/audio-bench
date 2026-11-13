"""Status precedence, expected-matrix completeness and paired summaries.

Rules from EVIDENCE_SPEC.md "Status, completeness and aggregation":

* precedence is ``invalid > failed > blocked > not_run > passed``; declared ``not_applicable`` rows
  do not fail an otherwise complete applicable matrix, but a *missing* row is ``invalid``;
* pairwise summaries use the explicitly displayed intersection of finite paired observations and
  show excluded/missing/failed counts next to the estimate;
* a headline full-cohort comparison requires no unexpected missing/failed cases, otherwise it is a
  partial diagnostic and must not be ranked as complete.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from . import stats
from .errors import ValidationError

STATUS_PRECEDENCE = ("invalid", "failed", "blocked", "not_run", "passed")
NON_SCORING_STATUSES = ("invalid", "failed", "blocked", "not_applicable", "not_run")


def aggregate_status(statuses: Iterable[str]) -> str:
    """Worst applicable status; a passed attempt requires every required row to pass."""
    present = [status for status in statuses if status != "not_applicable"]
    if not present:
        return "not_applicable" if statuses else "not_run"
    for status in STATUS_PRECEDENCE:
        if status in present:
            return status
    raise ValidationError(f"unknown execution status in {sorted(set(present))}")


def check_matrix(
    expected: Iterable[tuple[str, str]],
    observations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare the exact expected case x metric set against delivered observations."""
    expected_set = set(expected)
    seen: set[tuple[str, str]] = set()
    duplicates: list[tuple[str, str]] = []
    for row in observations:
        key = (row["case_id"], row["metric_id"])
        if key in seen:
            duplicates.append(key)
        seen.add(key)
    missing = sorted(expected_set - seen)
    extra = sorted(seen - expected_set)
    applicable = [row for row in observations if row["execution_status"] != "not_applicable"]
    return {
        "expected": len(expected_set),
        "delivered": len(seen),
        "missing": missing,
        "extra": extra,
        "duplicates": sorted(duplicates),
        "complete": not missing and not extra and not duplicates,
        "status": aggregate_status(row["execution_status"] for row in applicable) if observations else "not_run",
    }


def summarize_metric(
    observations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Counts and finite-value statistics for one metric over one configuration."""
    counts: dict[str, int] = defaultdict(int)
    values: list[float] = []
    reasons: dict[str, int] = defaultdict(int)
    for row in observations:
        counts[str(row["execution_status"])] += 1
        if row["execution_status"] == "passed":
            if row["value"] is None:
                reasons[str(row["reason"] or "undefined")] += 1
            else:
                values.append(float(row["value"]))
        elif row["reason"]:
            reasons[str(row["reason"])] += 1
    summary: dict[str, Any] = {
        "counts": {status: counts.get(status, 0) for status in (*STATUS_PRECEDENCE, "not_applicable")},
        "finite_count": len(values),
        "undefined_reasons": dict(sorted(reasons.items())),
    }
    if values:
        array = np.asarray(values, dtype=np.float64)
        summary.update(
            {
                "mean": float(array.mean()),
                "median": float(np.median(array)),
                "min": float(array.min()),
                "max": float(array.max()),
            }
        )
    else:
        summary.update({"mean": None, "median": None, "min": None, "max": None})
    return summary


def paired_summary(
    candidate: Sequence[Mapping[str, Any]],
    baseline: Sequence[Mapping[str, Any]],
    *,
    speakers: Mapping[str, str],
    metric_id: str,
    seed: int = stats.BOOTSTRAP_SEED,
    draws: int = stats.BOOTSTRAP_DRAWS,
) -> dict[str, Any]:
    """Paired mean delta with the frozen within-speaker bootstrap.

    ``speakers`` maps case_id -> speaker_id. Only finite paired observations enter the estimate;
    every exclusion is counted and displayed.
    """
    candidate_all = {row["case_id"]: row for row in candidate if row["metric_id"] == metric_id}
    baseline_all = {row["case_id"]: row for row in baseline if row["metric_id"] == metric_id}
    candidate_by_case = {
        case_id: row for case_id, row in candidate_all.items()
        if row["execution_status"] == "passed" and row["value"] is not None
    }
    baseline_by_case = {
        case_id: row for case_id, row in baseline_all.items()
        if row["execution_status"] == "passed" and row["value"] is not None
    }
    all_cases = sorted({row["case_id"] for row in candidate} | {row["case_id"] for row in baseline})
    paired: dict[str, list[float]] = defaultdict(list)
    excluded: dict[str, int] = defaultdict(int)
    for case_id in all_cases:
        if case_id not in speakers:
            raise ValidationError(f"case {case_id} has no speaker mapping")
        left = candidate_by_case.get(case_id)
        right = baseline_by_case.get(case_id)
        if left is None or right is None:
            left_all = candidate_all.get(case_id)
            right_all = baseline_all.get(case_id)
            if left_all is None:
                excluded["missing_candidate"] += 1
            elif left_all["execution_status"] != "passed":
                excluded[f"candidate_{left_all['execution_status']}"] += 1
            elif left_all["value"] is None:
                excluded["candidate_undefined"] += 1
            if right_all is None:
                excluded["missing_baseline"] += 1
            elif right_all["execution_status"] != "passed":
                excluded[f"baseline_{right_all['execution_status']}"] += 1
            elif right_all["value"] is None:
                excluded["baseline_undefined"] += 1
            continue
        paired[speakers[case_id]].append(float(left["value"]) - float(right["value"]))
    if not paired:
        return {
            "metric_id": metric_id,
            "estimate": None,
            "excluded": dict(sorted(excluded.items())),
            "complete": False,
            "label": "no paired finite observations",
        }
    result = stats.paired_bootstrap(paired, seed=seed, draws=draws)
    body = result.as_dict()
    body.update(
        {
            "metric_id": metric_id,
            "excluded": dict(sorted(excluded.items())),
            "complete": not excluded,
            "label": "full cohort paired comparison" if not excluded else "partial diagnostic comparison",
        }
    )
    return body


def summarize_attempt(
    observations: Sequence[Mapping[str, Any]],
    *,
    expected: Iterable[tuple[str, str]],
    metric_ids: Sequence[str],
) -> dict[str, Any]:
    """Deterministic summary payload written next to the observations."""
    matrix = check_matrix(expected, observations)
    by_metric = {
        metric_id: summarize_metric([row for row in observations if row["metric_id"] == metric_id])
        for metric_id in sorted(set(metric_ids))
    }
    return {
        "schema_id": "audio-bench/summary/0.1",
        "attempt_status": matrix["status"],
        "complete": matrix["complete"],
        "expected_case_metric_count": str(matrix["expected"]),
        "delivered_case_metric_count": str(matrix["delivered"]),
        "missing": [f"{case}/{metric}" for case, metric in matrix["missing"]],
        "extra": [f"{case}/{metric}" for case, metric in matrix["extra"]],
        "duplicates": [f"{case}/{metric}" for case, metric in matrix["duplicates"]],
        "metrics": by_metric,
    }
