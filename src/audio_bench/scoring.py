"""Case-level scoring: frozen intervals, digest checks, explicit failure rows.

Scoring runs *after* rendering and outside timing jobs. Every expected case x metric receives
exactly one observation, including failed or undefined ones. A missing row is an invalid bundle,
never a silent exclusion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from . import audio, metrics
from .errors import ValidationError


@dataclass(frozen=True)
class CaseInput:
    case_id: str
    clean: np.ndarray
    noisy: np.ndarray
    output: np.ndarray
    output_pcm_digest: str
    clean_pcm_digest: str
    noisy_pcm_digest: str


def check_case_input(entry: CaseInput, *, interval: tuple[int, int], sample_count: int) -> None:
    start, end = interval
    if not (0 <= start < end <= sample_count):
        raise ValidationError(f"{entry.case_id}: scored interval {interval} is outside the case")
    for name in ("clean", "noisy", "output"):
        samples = getattr(entry, name)
        if samples.ndim != 1:
            raise ValidationError(f"{entry.case_id}: {name} must be mono")
        if not np.isfinite(samples).all():
            raise ValidationError(f"{entry.case_id}: {name} contains non-finite samples")
        if len(samples) < end:
            raise ValidationError(f"{entry.case_id}: {name} shorter than the scored interval")
    if audio.pcm_digest(entry.output) != entry.output_pcm_digest:
        raise ValidationError(f"{entry.case_id}: output PCM digest does not match the scored audio")
    if audio.pcm_digest(entry.clean) != entry.clean_pcm_digest:
        raise ValidationError(f"{entry.case_id}: clean PCM digest mismatch")
    if audio.pcm_digest(entry.noisy) != entry.noisy_pcm_digest:
        raise ValidationError(f"{entry.case_id}: noisy PCM digest mismatch")


def crop(samples: np.ndarray, interval: tuple[int, int]) -> np.ndarray:
    start, end = interval
    return np.asarray(samples[start:end], dtype=np.float64)


def observation(
    *,
    run_id: str,
    attempt_id: str,
    configuration_id: str,
    comparison_cohort_id: str,
    case_id: str,
    metric_id: str,
    execution_status: str = "passed",
    reason: str | None = None,
    value: float | int | None = None,
    numerator: str | None = None,
    denominator: str | None = None,
    valid_interval: tuple[int, int, int] | None = None,
    output_pcm_digest: str | None = None,
) -> dict[str, Any]:
    spec = metrics.METRICS.get(metric_id)
    if spec is None:
        raise ValidationError(f"unknown metric_id {metric_id!r}")
    return {
        "schema_id": "audio-bench/observation/0.1",
        "run_id": run_id,
        "attempt_id": attempt_id,
        "configuration_id": configuration_id,
        "comparison_cohort_id": comparison_cohort_id,
        "case_id": case_id,
        "metric_id": metric_id,
        "metric_revision": spec.revision,
        "execution_status": execution_status,
        "reason": reason,
        "value": value,
        "unit": spec.unit,
        "direction": spec.direction,
        "numerator": numerator,
        "denominator": denominator,
        "valid_interval": None
        if valid_interval is None
        else {
            "start_sample": str(valid_interval[0]),
            "end_sample": str(valid_interval[1]),
            "sample_rate_hz": valid_interval[2],
        },
        "output_pcm_digest": output_pcm_digest,
    }


def failure_observations(
    *,
    metric_ids: Iterable[str],
    execution_status: str,
    reason: str,
    **common: Any,
) -> list[dict[str, Any]]:
    """Failure rows are preserved for every expected metric; they are never dropped."""
    if execution_status not in ("failed", "blocked", "invalid", "not_applicable", "not_run"):
        raise ValidationError("failure_observations requires a non-passed status")
    return [
        observation(metric_id=metric_id, execution_status=execution_status, reason=reason, **common)
        for metric_id in metric_ids
    ]


def score_case(
    entry: CaseInput,
    *,
    interval: tuple[int, int],
    metric_ids: Sequence[str],
    run_id: str,
    attempt_id: str,
    configuration_id: str,
    comparison_cohort_id: str,
    sample_rate: int = audio.SAMPLE_RATE,
) -> list[dict[str, Any]]:
    check_case_input(entry, interval=interval, sample_count=len(entry.output))
    reference = crop(entry.clean, interval)
    raw = crop(entry.noisy, interval)
    estimate = crop(entry.output, interval)
    common = {
        "run_id": run_id,
        "attempt_id": attempt_id,
        "configuration_id": configuration_id,
        "comparison_cohort_id": comparison_cohort_id,
        "case_id": entry.case_id,
    }
    rows: list[dict[str, Any]] = []
    for metric_id in metric_ids:
        value, reason = metrics.metric_value(metric_id, reference=reference, estimate=estimate, raw=raw)
        numerator = denominator = None
        if metric_id == "clipping_count":
            numerator = str(int(value))  # type: ignore[arg-type]
            denominator = str(len(estimate))
        rows.append(
            observation(
                metric_id=metric_id,
                value=value,
                reason=reason,
                numerator=numerator,
                denominator=denominator,
                valid_interval=(interval[0], interval[1], sample_rate),
                output_pcm_digest=entry.output_pcm_digest,
                **common,
            )
        )
    return rows


def case_input_from_arrays(
    *,
    case_id: str,
    clean: np.ndarray,
    noisy: np.ndarray,
    output: np.ndarray,
) -> CaseInput:
    return CaseInput(
        case_id=case_id,
        clean=np.asarray(clean, dtype=np.float32),
        noisy=np.asarray(noisy, dtype=np.float32),
        output=np.asarray(output, dtype=np.float32),
        output_pcm_digest=audio.pcm_digest(output),
        clean_pcm_digest=audio.pcm_digest(clean),
        noisy_pcm_digest=audio.pcm_digest(noisy),
    )
