# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0

import json
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_voicebank as voicebank
from audio_bench.errors import ValidationError


def test_voicebank_protocol_is_pinned_to_full_test_cohort():
    assert voicebank.PROTOCOL["protocol_id"] == voicebank.SUITE_ID
    assert voicebank.PROTOCOL["dataset_id"] == voicebank.DATASET_ID
    assert voicebank.PROTOCOL["bootstrap_draws"] == 5000
    cases = [json.loads(line) for line in (ROOT / "manifests/voicebank-demand/voicebank-demand-test-v1/cases-0000.jsonl").read_text().splitlines()]
    assert len(cases) == 824
    assert len({item["speaker_id"] for item in cases}) == 2


def test_voicebank_resampling_is_deterministic_and_alignment_preserving(tmp_path):
    samples = np.sin(np.arange(4800, dtype=np.float32) * 0.03)
    path = tmp_path / "source.wav"
    sf.write(path, samples, 48000, subtype="PCM_16")
    first = voicebank._load_resampled(path)
    second = voicebank._load_resampled(path)
    assert len(first) == 1600
    np.testing.assert_array_equal(first, second)


def test_voicebank_output_map_requires_complete_exact_coverage(tmp_path):
    raw = tmp_path / "output.raw.f32"
    mapping = tmp_path / "output.intervals.jsonl"
    np.arange(6, dtype="<f4").tofile(raw)
    mapping.write_text(
        json.dumps({"source_start": "0", "source_end": "3", "output_offset_samples": "0",
                    "valid_offset": 0, "valid_count": 3}) + "\n" +
        json.dumps({"source_start": "3", "source_end": "6", "output_offset_samples": "3",
                    "valid_offset": 0, "valid_count": 3}) + "\n")
    np.testing.assert_array_equal(voicebank._reconstruct(raw, mapping, 6), np.arange(6, dtype=np.float32))
    mapping.write_text(json.dumps({"source_start": "1", "source_end": "6", "output_offset_samples": "0",
                                   "valid_offset": 0, "valid_count": 5}) + "\n")
    with pytest.raises(ValidationError, match="gap, overlap"):
        voicebank._reconstruct(raw, mapping, 6)


def test_voicebank_bootstrap_is_reproducible_and_speaker_stratified():
    values = list(range(10))
    speakers = ["a"] * 5 + ["b"] * 5
    one = voicebank._bootstrap(values, speakers, 42)
    two = voicebank._bootstrap(values, speakers, 42)
    assert one == two
    assert one[0] <= np.median(values) <= one[1]

