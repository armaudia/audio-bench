"""Quality metrics with explicit undefined outcomes.

Migration provenance: SI-SDR's zero-mean projection formula was audited and ported from the
allowlisted ``scripts/evaluate_noise_suppression.py`` function ``si_sdr`` (source digest in
``deps/source-inventory.json``). The two ±300 dB sentinels were intentionally removed and replaced
by null/reason results per the new evidence contract; historical scores remain untouched.

`si_sdr` follows EVIDENCE_SPEC.md exactly:

    center s, y; alpha = dot(y, s) / dot(s, s); target = alpha * s;
    residual = y - target; 10*log10(sum(target^2) / sum(residual^2))

Degenerate cases return ``None`` plus a stable reason. No epsilon cap and no +/-300 dB sentinel
enters an authoritative score; the historical research script's caps are *not* reproduced.
Plain SNR is intentionally absent: relabelling SNR as SI-SDR is forbidden by the plan.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np

METRIC_REGISTRY_VERSION = "0.1"
PYSTOI_VERSION = "0.4.1"


@dataclass(frozen=True)
class MetricSpec:
    metric_id: str
    revision: str
    unit: str
    direction: str
    implementation: str
    settings: dict[str, Any]

    def as_registry_entry(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "revision": self.revision,
            "unit": self.unit,
            "direction": self.direction,
            "implementation": self.implementation,
            "settings": self.settings,
        }


METRICS: dict[str, MetricSpec] = {
    "si_sdr_db": MetricSpec("si_sdr_db", "zero-mean.v1", "dB", "higher", "audio_bench.metrics.si_sdr", {}),
    "si_sdr_improvement_db": MetricSpec(
        "si_sdr_improvement_db",
        "zero-mean.v1",
        "dB",
        "higher",
        "audio_bench.metrics.si_sdr_improvement",
        {"baseline": "raw_input"},
    ),
    "stoi": MetricSpec(
        "stoi", "pystoi-0.4.1.non-extended", "index", "higher", "pystoi.stoi", {"extended": False}
    ),
    "estoi": MetricSpec(
        "estoi", "pystoi-0.4.1.extended", "index", "higher", "pystoi.stoi", {"extended": True}
    ),
    "rms_gain_ratio": MetricSpec(
        "rms_gain_ratio", "linear.v1", "ratio", "diagnostic", "audio_bench.metrics.rms_gain_ratio", {}
    ),
    "clipping_count": MetricSpec(
        "clipping_count", "abs-gt-1.v1", "count", "lower", "audio_bench.metrics.clipping_count", {}
    ),
    "max_abs_sample": MetricSpec(
        "max_abs_sample", "float64.v1", "none", "diagnostic", "audio_bench.metrics.max_abs_sample", {}
    ),
}

DEFAULT_QUALITY_METRICS = ("si_sdr_db", "stoi", "estoi")


def _finite_pair(reference: np.ndarray, estimate: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    ref = np.asarray(reference, dtype=np.float64).reshape(-1)
    est = np.asarray(estimate, dtype=np.float64).reshape(-1)
    if ref.shape != est.shape or ref.size == 0:
        return None
    if not np.isfinite(ref).all() or not np.isfinite(est).all():
        return None
    return ref, est


def si_sdr(reference: np.ndarray, estimate: np.ndarray) -> tuple[float | None, str | None]:
    """Zero-mean scale-invariant SDR in dB, or (None, reason)."""
    pair = _finite_pair(reference, estimate)
    if pair is None:
        return None, "invalid_input"
    ref, est = pair
    ref = ref - ref.mean(dtype=np.float64)
    est = est - est.mean(dtype=np.float64)
    reference_energy = float(np.dot(ref, ref))
    if reference_energy <= 0.0:
        return None, "zero_reference_energy"
    alpha = float(np.dot(est, ref)) / reference_energy
    target = alpha * ref
    target_energy = float(np.dot(target, target))
    if target_energy <= 0.0:
        return None, "zero_output_energy"
    residual = est - target
    residual_energy = float(np.dot(residual, residual))
    if residual_energy <= 0.0:
        return None, "perfect_reconstruction"
    return float(10.0 * math.log10(target_energy / residual_energy)), None


def si_sdr_improvement(
    reference: np.ndarray, estimate: np.ndarray, raw: np.ndarray
) -> tuple[float | None, str | None]:
    output, output_reason = si_sdr(reference, estimate)
    baseline, baseline_reason = si_sdr(reference, raw)
    if output_reason or baseline_reason:
        return None, output_reason or baseline_reason
    assert output is not None and baseline is not None
    return output - baseline, None


def _pystoi(reference: np.ndarray, estimate: np.ndarray, rate: int, *, extended: bool) -> tuple[float | None, str | None]:
    pair = _finite_pair(reference, estimate)
    if pair is None:
        return None, "invalid_input"
    ref, est = pair
    if not np.any(ref):
        return None, "insufficient_active_speech"
    try:
        from pystoi import stoi as calculate
    except ImportError:  # pragma: no cover - dependency is pinned
        return None, "missing_dependency"
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            value = float(calculate(ref, est, rate, extended=extended))
    except Exception:  # pystoi raises on degenerate framing; the outcome stays explicit
        return None, "metric_undefined"
    if caught:
        if all(
            issubclass(item.category, RuntimeWarning)
            and "Not enough STFT frames" in str(item.message)
            for item in caught
        ):
            return None, "insufficient_active_speech"
        return None, "metric_undefined"
    if not math.isfinite(value):
        return None, "metric_undefined"
    return value, None


def stoi(reference: np.ndarray, estimate: np.ndarray, rate: int = 16000) -> tuple[float | None, str | None]:
    return _pystoi(reference, estimate, rate, extended=False)


def estoi(reference: np.ndarray, estimate: np.ndarray, rate: int = 16000) -> tuple[float | None, str | None]:
    return _pystoi(reference, estimate, rate, extended=True)


def rms_gain_ratio(reference: np.ndarray, estimate: np.ndarray) -> tuple[float | None, str | None]:
    """RMS(output)/RMS(input); null when the input has no energy (never a fabricated 1.0)."""
    pair = _finite_pair(reference, estimate)
    if pair is None:
        return None, "invalid_input"
    ref, est = pair
    ref_rms = float(np.sqrt(np.mean(np.square(ref))))
    if ref_rms <= 0.0:
        return None, "zero_input_energy"
    est_rms = float(np.sqrt(np.mean(np.square(est))))
    if est_rms <= 0.0:
        return None, "zero_output_energy"
    return est_rms / ref_rms, None


def clipping_count(samples: np.ndarray) -> int:
    values = np.asarray(samples, dtype=np.float64)
    return int(np.count_nonzero(np.abs(values) > 1.0))


def max_abs_sample(samples: np.ndarray) -> float:
    return float(np.max(np.abs(np.asarray(samples, dtype=np.float64))))


def metric_value(metric_id: str, *, reference: Any, estimate: Any, raw: Any = None) -> tuple[float | int | None, str | None]:
    """Dispatch one metric by ID using already-cropped float64 arrays."""
    if metric_id == "si_sdr_db":
        return si_sdr(reference, estimate)
    if metric_id == "si_sdr_improvement_db":
        if raw is None:
            return None, "missing_dependency"
        return si_sdr_improvement(reference, estimate, raw)
    if metric_id == "stoi":
        return stoi(reference, estimate)
    if metric_id == "estoi":
        return estoi(reference, estimate)
    if metric_id == "rms_gain_ratio":
        if raw is None:
            return None, "missing_dependency"
        return rms_gain_ratio(raw, estimate)
    if metric_id == "clipping_count":
        return clipping_count(estimate), None
    if metric_id == "max_abs_sample":
        return max_abs_sample(estimate), None
    return None, "not_implemented"
