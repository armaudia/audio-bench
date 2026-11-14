# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Frame schedule, lateness and accounting arithmetic (EVIDENCE_SPEC "Timing and runtime equations").

All quantities are exact integers in one monotonic clock domain. Absolute sample indexes are never
converted to float; large counters travel as canonical decimal strings.

Definitions used by the collector (B05) and by the report (B09):

* source sample ``n`` is captured at ``t0 + n * 62_500 ns`` (16 kHz).
* frame ``k`` is complete, and is scheduled for submission, at ``t0 + (k + 1) * 10_000_000 ns``
  — never at frame start.
* availability delay of a delivered block = collector receive time minus the capture time of the
  block's first *valid* source sample.
* the deadline for that block is that capture time plus the frozen delivery budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .errors import ValidationError

NS_PER_SECOND = 1_000_000_000
NS_PER_SAMPLE_16K = 62_500
FRAME_SAMPLES = 160
FRAME_NS = FRAME_SAMPLES * NS_PER_SAMPLE_16K  # exactly 10 ms
INT64_MAX = 2**63 - 1


def _require_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{name} must be an exact integer (got {type(value).__name__})")
    return value


def frame_complete_ns(t0_ns: int, frame_index: int) -> int:
    """Scheduled submission time of frame ``frame_index`` (0-based)."""
    _require_int(t0_ns, "t0_ns")
    _require_int(frame_index, "frame_index")
    if frame_index < 0:
        raise ValidationError("frame_index must be non-negative")
    return t0_ns + (frame_index + 1) * FRAME_NS


def sample_capture_ns(t0_ns: int, sample_index: int) -> int:
    _require_int(t0_ns, "t0_ns")
    _require_int(sample_index, "sample_index")
    return t0_ns + sample_index * NS_PER_SAMPLE_16K


def availability_delay_ns(receive_ns: int, t0_ns: int, first_valid_sample: int) -> int:
    """Delay from capture of the first valid sample to collector availability.

    Negative values are impossible evidence, not small wins; they raise.
    """
    delay = _require_int(receive_ns, "receive_ns") - sample_capture_ns(t0_ns, first_valid_sample)
    if delay < 0:
        raise ValidationError("negative availability delay: invalid clock evidence")
    return delay


def deadline_ns(t0_ns: int, first_valid_sample: int, delivery_budget_ns: int) -> int:
    budget = _require_int(delivery_budget_ns, "delivery_budget_ns")
    if budget < 0:
        raise ValidationError("delivery budget must be non-negative")
    return sample_capture_ns(t0_ns, first_valid_sample) + budget


def deadline_missed(receive_ns: int, t0_ns: int, first_valid_sample: int, delivery_budget_ns: int) -> bool:
    """A late block is a miss even when it arrives later in a catch-up burst."""
    return _require_int(receive_ns, "receive_ns") > deadline_ns(t0_ns, first_valid_sample, delivery_budget_ns)


def submit_lateness_ns(actual_submit_ns: int, scheduled_submit_ns: int) -> int:
    """Pacer lateness, kept as a signed integer; negative means early submission."""
    return _require_int(actual_submit_ns, "actual_submit_ns") - _require_int(scheduled_submit_ns, "scheduled_submit_ns")


def classify_lateness(
    actual_submit_ns: int,
    scheduled_submit_ns: int,
    *,
    allowed_collector_lateness_ns: int,
) -> str:
    """Separate collector/harness lateness from candidate deadline failures."""
    lateness = submit_lateness_ns(actual_submit_ns, scheduled_submit_ns)
    if lateness > allowed_collector_lateness_ns:
        return "harness_late"
    return "ok"


def nearest_rank_quantile(sorted_observations: list[int], numerator: int, denominator: int) -> int:
    """Nearest-rank quantile on raw observations (p in [0, 1] as an exact fraction)."""
    if not sorted_observations:
        raise ValidationError("quantile of an empty observation set")
    if not (0 <= numerator <= denominator) or denominator <= 0:
        raise ValidationError("invalid quantile fraction")
    rank = max(1, -(-numerator * len(sorted_observations) // denominator))
    return sorted_observations[rank - 1]


def latency_summary(observations_ns: list[int]) -> dict[str, int | str]:
    """p50/p95/p99/p99.9/max with the exact sample count."""
    values = sorted(_require_int(value, "observation") for value in observations_ns)
    if not values:
        return {"count": "0"}
    summary: dict[str, int | str] = {"count": str(len(values))}
    for label, numerator, denominator in (
        ("p50", 50, 100),
        ("p95", 95, 100),
        ("p99", 99, 100),
        ("p999", 999, 1000),
        ("max", 1, 1),
    ):
        summary[label] = str(nearest_rank_quantile(values, numerator, denominator))
    return summary


@dataclass(frozen=True)
class Accounting:
    """Exact CPU/elapsed accounting over one measured interval.

    ``cpu_seconds`` covers the whole candidate process tree as observed by the collector; ``wall``
    is the actual monotonic elapsed time, never a planned duration.
    """

    cpu_ns: int
    wall_ns: int
    accepted_samples: int
    streams: int = 1

    def __post_init__(self) -> None:
        for name in ("cpu_ns", "wall_ns", "accepted_samples"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValidationError(f"{name} must be a non-negative exact integer")
        if self.streams < 1:
            raise ValidationError("streams must be at least 1")
        if self.wall_ns <= 0:
            raise ValidationError("wall_ns must be positive for occupancy")
        if self.accepted_samples == 0:
            raise ValidationError("accepted_samples must be positive; an empty stream has no compute cost")

    @property
    def cpu_occupancy(self) -> Fraction:
        """Whole-process-tree CPU seconds / actual wall seconds (cores-equivalent)."""
        return Fraction(self.cpu_ns, self.wall_ns)

    @property
    def audio_seconds(self) -> Fraction:
        return Fraction(self.accepted_samples, 16000)

    @property
    def compute_cost(self) -> Fraction:
        """CPU seconds per accepted audio second: CPU / (samples / 16000)."""
        return Fraction(self.cpu_ns, NS_PER_SECOND) / self.audio_seconds

    @property
    def throughput(self) -> Fraction:
        """Accepted audio seconds per actual wall second."""
        return self.audio_seconds / Fraction(self.wall_ns, NS_PER_SECOND)

    def as_dict(self) -> dict[str, str]:
        return {
            "cpu_ns": str(self.cpu_ns),
            "wall_ns": str(self.wall_ns),
            "accepted_samples": str(self.accepted_samples),
            "streams": str(self.streams),
            "cpu_occupancy_cores": _fraction_text(self.cpu_occupancy),
            "compute_cost_cpu_s_per_audio_s": _fraction_text(self.compute_cost),
            "throughput_audio_s_per_wall_s": _fraction_text(self.throughput),
        }


def _fraction_text(value: Fraction) -> str:
    """Exact rational text: no rounding hides a real overrun."""
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def assert_single_clock_domain(*receive_ns: int) -> None:
    """Guard against subtracting across clock domains by reminding callers of the contract.

    A collector may only subtract values produced by its own monotonic clock; this helper exists
    so callers pass values explicitly rather than mixing candidate-reported and supervisor times.
    """
    for index, value in enumerate(receive_ns):
        _require_int(value, f"receive_ns[{index}]")


def assert_int64(value: int, name: str) -> int:
    _require_int(value, name)
    if not (-INT64_MAX - 1 <= value <= INT64_MAX):
        raise ValidationError(f"{name} is outside int64")
    return value


def assert_uint64(value: int, name: str) -> int:
    _require_int(value, name)
    if not (0 <= value <= 2**64 - 1):
        raise ValidationError(f"{name} is outside uint64")
    return value


def sample_union_is_clean(intervals: list[tuple[int, int]]) -> tuple[bool, str]:
    """Half-open interval union used for conservation checks (no overlaps, positive lengths)."""
    previous_end: int | None = None
    for start, end in sorted(intervals):
        if end <= start:
            return False, "non_positive_interval"
        if previous_end is not None and start < previous_end:
            return False, "overlapping_intervals"
        previous_end = end
    return True, "ok"


def conservation(
    accepted: list[tuple[int, int]],
    delivered_valid: list[tuple[int, int]],
    declared_exclusions: list[tuple[int, int]] | None = None,
) -> tuple[bool, str]:
    """Accepted source union must equal delivered valid union plus declared edge exclusions.

    Midstream gaps cannot be relabelled as a cropped edge: exclusions must be prefix/suffix only.
    """
    clean, reason = sample_union_is_clean(accepted)
    if not clean:
        return False, f"accepted_{reason}"
    clean, reason = sample_union_is_clean(delivered_valid)
    if not clean:
        return False, f"delivered_{reason}"
    exclusions = sorted(declared_exclusions or [])
    if exclusions:
        clean, reason = sample_union_is_clean(exclusions)
        if not clean:
            return False, f"exclusion_{reason}"
    if not accepted:
        return (not delivered_valid and not exclusions), "ok" if not delivered_valid else "delivered_without_input"
    first = accepted[0][0]
    last = accepted[-1][1]
    for start, end in exclusions:
        if not ((start == first and end <= last) or (end == last and start >= first)):
            return False, "exclusion_not_at_edge"
    for start, end in delivered_valid:
        if start < first or end > last:
            return False, "delivered_outside_accepted"
    remaining = subtract_intervals(accepted, exclusions)
    if merge_intervals(remaining) != merge_intervals(delivered_valid):
        return False, "interval_union_mismatch"
    return True, "ok"


def merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    ordered = sorted((start, end) for start, end in intervals if end > start)
    merged: list[tuple[int, int]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def subtract_intervals(base: list[tuple[int, int]], cuts: list[tuple[int, int]]) -> list[tuple[int, int]]:
    remaining = merge_intervals(base)
    for cut_start, cut_end in merge_intervals(cuts):
        next_remaining: list[tuple[int, int]] = []
        for start, end in remaining:
            if cut_end <= start or cut_start >= end:
                next_remaining.append((start, end))
                continue
            if start < cut_start:
                next_remaining.append((start, cut_start))
            if cut_end < end:
                next_remaining.append((cut_end, end))
        remaining = next_remaining
    return remaining


def scheduled_stream_t0(base_t0_ns: int, stream_index: int) -> int:
    """Each stream gets an identical schedule; only the source data is phase-shifted."""
    _require_int(base_t0_ns, "base_t0_ns")
    if stream_index < 0:
        raise ValidationError("stream_index must be non-negative")
    return base_t0_ns


def workload_phase_offset_samples(stream_index: int) -> int:
    """Specified per-stream phase offset for the intermittent workload (stream_index * 160)."""
    if stream_index < 0:
        raise ValidationError("stream_index must be non-negative")
    return stream_index * FRAME_SAMPLES
