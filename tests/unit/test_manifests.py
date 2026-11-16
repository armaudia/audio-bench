# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
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


def test_voicebank_corpus_rights_status_records_maintainer_approval():
    import json

    status = json.loads(Path("manifests/voicebank.status.json").read_text())
    assert status["status"] == "allowed"
    assert status["rights"]["acquisition"] == "allowed"
    assert status["rights"]["evaluation"] == "allowed"
    assert status["rights"]["public_aggregate_results"] == "allowed"
    assert status["rights"]["redistribution"] == "not_authorized"
    assert status["rights"]["public_playback"] == "not_authorized"
    assert status["provenance_review"]["license"] == "Creative Commons Attribution 4.0 International Public License"
    assert status["archive_sha256"] is None
    assert status["verified_pair_count"] == 824
    assert len(status["archive_inventory"]) == 2
    assert status["corpus_evaluation_claim"] == "approved_by_maintainer"


def test_voicebank_test_manifest_pins_all_official_pairs_without_audio_payloads():
    import hashlib
    import json
    import jsonschema

    root = Path("manifests/voicebank-demand/voicebank-demand-test-v1")
    provenance = json.loads((root / "provenance.json").read_text())
    case_manifest = (root / "cases-0000.jsonl").read_bytes()
    cases = [json.loads(line) for line in case_manifest.decode("utf-8").splitlines()]
    schema = json.loads(Path("schemas/paired-corpus-provenance.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(provenance)
    assert provenance["case_manifest_sha256"] == "sha256:" + hashlib.sha256(case_manifest).hexdigest()
    assert provenance["counts"]["paired_utterances"] == len(cases) == 824
    assert provenance["counts"]["distinct_speakers"] == len({case["speaker_id"] for case in cases}) == 2
    assert len({case["case_id"] for case in cases}) == 824
    assert all(case["clean"]["bytes"] > 0 and case["noisy"]["bytes"] > 0 for case in cases)
    assert all(case["clean"]["sha256"].startswith("sha256:") and case["noisy"]["sha256"].startswith("sha256:") for case in cases)
    assert not list(root.rglob("*.wav"))
