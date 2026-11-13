import numpy as np
import pytest

from audio_bench.metrics import clipping_count, estoi, rms_gain_ratio, si_sdr, si_sdr_improvement, stoi
from audio_bench.stats import paired_bootstrap


def test_si_sdr_analytic_orthogonal_noise():
    ref = np.tile(np.array([1.0, -1.0, 1.0, -1.0]), 32)
    noise = np.tile(np.array([1.0, 1.0, -1.0, -1.0]), 32) * 0.25
    value, reason = si_sdr(ref, ref + noise)
    assert reason is None
    assert value == pytest.approx(20 * np.log10(1 / 0.25), abs=1e-9)


def test_si_sdr_undefined_values_are_null_reasons():
    assert si_sdr(np.zeros(10), np.zeros(10)) == (None, "zero_reference_energy")
    ref = np.arange(10, dtype=float)
    assert si_sdr(ref, ref * 2) == (None, "perfect_reconstruction")
    assert si_sdr(ref, np.zeros(10)) == (None, "zero_output_energy")


def test_gain_clipping_and_improvement():
    ref = np.sin(np.linspace(0, 20, 100))
    noisy = ref + 0.2 * np.cos(np.linspace(0, 20, 100))
    scaled = 0.5 * ref
    ratio, reason = rms_gain_ratio(ref, scaled)
    assert reason is None and ratio == pytest.approx(0.5)
    assert clipping_count(np.array([0.0, 1.0, -1.1])) == 1
    improvement, reason = si_sdr_improvement(ref, ref, noisy)
    assert improvement is None and reason == "perfect_reconstruction"


def test_stoi_ids_separate_but_synthetic_short_case_undefined():
    short = np.zeros(160)
    assert stoi(short, short) == (None, "insufficient_active_speech")
    assert estoi(short, short) == (None, "insufficient_active_speech")


def test_bootstrap_is_deterministic_and_speaker_stratified():
    first = paired_bootstrap({"a": [1.0, 1.0, 1.0], "b": [3.0]}, seed=12, draws=100)
    second = paired_bootstrap({"b": [3.0], "a": [1.0, 1.0, 1.0]}, seed=12, draws=100)
    assert first == second
    assert first.delta == 1.5
    assert first.speakers == 2
    assert first.utterances == 4
