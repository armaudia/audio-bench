from pathlib import Path

import pytest

from audio_bench import canonical
from audio_bench.errors import ValidationError
from audio_bench.manifests import (
    build_synthetic_dataset,
    load_file_records,
    load_case_records,
    smoke_selection,
    verify_case_bytes,
)
from audio_bench.schemas import Validator, verify_dataset_identity


def test_synthetic_manifests_are_deterministic_and_closed(tmp_path):
    first = build_synthetic_dataset(tmp_path / "a")
    second = build_synthetic_dataset(tmp_path / "b")
    assert first["dataset"]["dataset_id"] == second["dataset"]["dataset_id"]
    assert first["case_set"]["case_set_id"] == second["case_set"]["case_set_id"]
    assert first["intervals"]["scored_interval_set_id"] == second["intervals"]["scored_interval_set_id"]
    assert first["smoke_case_ids"] == second["smoke_case_ids"]
    assert len(first["cases"]) == 24
    verify_dataset_identity(first["dataset"], first["cases"])
    first_bytes = (tmp_path / "a" / "audio" / "synthspk00-p00.clean.wav").read_bytes()
    second_bytes = (tmp_path / "b" / "audio" / "synthspk00-p00.clean.wav").read_bytes()
    assert first_bytes == second_bytes
    files = load_file_records(tmp_path / "a", first["dataset"])
    assert len(files) == 48
    loaded_cases = load_case_records(tmp_path / "a", first["dataset"])
    verify_case_bytes(tmp_path / "a", loaded_cases)
    assert canonical.require_canonical((tmp_path / "a" / "dataset.json").read_bytes()) == first["dataset"]


def test_smoke_selection_round_robins_speakers():
    cases = [
        {"case_id": f"{speaker}-case-{number}", "speaker_id": speaker}
        for speaker in ["b", "a", "c"]
        for number in range(3)
    ]
    selected = smoke_selection(cases, limit=6)
    assert len(selected) == 6
    assert {selected[0].split("-")[0], selected[1].split("-")[0], selected[2].split("-")[0]} == {"a", "b", "c"}


def test_tampering_with_case_inventory_fails(tmp_path):
    result = build_synthetic_dataset(tmp_path / "data")
    altered = [dict(record) for record in result["cases"]]
    altered[0]["sample_count"] = "159"
    with pytest.raises(ValidationError, match="case_inventory_digest"):
        verify_dataset_identity(result["dataset"], altered)


def test_unknown_real_corpus_remains_blocked():
    import json

    status = json.loads(Path("manifests/voicebank.status.json").read_text())
    assert status["status"] == "blocked"
    assert status["reason"] == "terms_reviewed_assets_unverified"
    assert status["provenance_review"]["license"] == "Creative Commons Attribution 4.0 International Public License"
    assert status["archive_sha256"] is None
    assert status["verified_pair_count"] is None
    assert status["corpus_evaluation_claim"] == "not_assessed"
