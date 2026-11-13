"""Frozen paired bootstrap from EVIDENCE_SPEC.md.

The estimand is the paired mean delta over utterances, with resampling **within each observed
speaker**: each replicate draws N_s utterances with replacement for every speaker, pools the draws
with the original speaker counts, and computes the paired mean delta. Percentiles are NumPy linear
(2.5 / 97.5). Inference is conditional on the observed speakers only.

This is deliberately not the grouped VAD bootstrap from the research store; that code answers a
different estimand and cannot be reused.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import numpy as np

BOOTSTRAP_SEED = 20261111
BOOTSTRAP_DRAWS = 10_000
QUANTILES = (2.5, 97.5)


@dataclass(frozen=True)
class BootstrapResult:
    delta: float
    low: float
    high: float
    seed: int
    draws: int
    speakers: int
    utterances: int
    estimand: str = "paired_mean_delta_within_speaker_bootstrap"

    def as_dict(self) -> dict[str, object]:
        return {
            "estimand": self.estimand,
            "delta": self.delta,
            "ci95": [self.low, self.high],
            "seed": str(self.seed),
            "draws": str(self.draws),
            "speakers": str(self.speakers),
            "utterances": str(self.utterances),
            "quantile_rule": "linear_2.5_97.5",
            "inference_scope": "conditional_on_observed_speakers",
        }


def paired_bootstrap(
    deltas_by_speaker: Mapping[str, Sequence[float]],
    *,
    seed: int = BOOTSTRAP_SEED,
    draws: int = BOOTSTRAP_DRAWS,
) -> BootstrapResult:
    """Bootstrap the paired mean delta with per-speaker resampling."""
    speakers = sorted(deltas_by_speaker)
    if not speakers:
        raise ValueError("no speakers to resample")
    groups = [np.asarray(list(deltas_by_speaker[speaker]), dtype=np.float64) for speaker in speakers]
    if any(group.size == 0 for group in groups):
        raise ValueError("every speaker needs at least one paired observation")
    if any(not np.isfinite(group).all() for group in groups):
        raise ValueError("bootstrap input must be finite")

    counts = np.array([group.size for group in groups], dtype=np.int64)
    pooled = np.concatenate(groups)
    point = float(pooled.mean())
    generator = np.random.Generator(np.random.PCG64(seed))
    replicate_means = np.empty(draws, dtype=np.float64)
    for replicate in range(draws):
        total = 0.0
        drawn = 0
        for group, count in zip(groups, counts):
            picks = generator.integers(0, count, size=int(count))
            total += float(group[picks].sum())
            drawn += int(count)
        replicate_means[replicate] = total / drawn
    low, high = np.percentile(replicate_means, QUANTILES, method="linear")
    return BootstrapResult(
        delta=point,
        low=float(low),
        high=float(high),
        seed=seed,
        draws=draws,
        speakers=len(speakers),
        utterances=int(counts.sum()),
    )


def paired_mean_delta(pairs: Iterable[tuple[float, float]]) -> float:
    """Mean of (candidate - baseline) over an explicit finite intersection."""
    deltas = [candidate - baseline for candidate, baseline in pairs]
    if not deltas:
        raise ValueError("no paired observations")
    return float(np.mean(np.asarray(deltas, dtype=np.float64)))
