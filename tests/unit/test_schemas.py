from pathlib import Path
import json

import pytest

from audio_bench import canonical
from audio_bench.errors import ValidationError
from audio_bench.schemas import Validator, load_sdk_schema, validate_sdk_record


def test_all_schema_documents_load_offline():
    validator = Validator()
    for kind in ("dataset", "case", "case-set", "recipe", "cohort", "scored-intervals", "request", "run", "observation", "output", "inventory", "core", "review", "export"):
        assert validator.schema(kind)["$schema"].endswith("2020-12/schema")


def test_case_shape_closed_object():
    validator = Validator()
    digest = "sha256:" + "a" * 64
    case = {
        "schema_id": "audio-bench/case/0.1", "case_id": "case-1", "dataset_id": digest,
        "source_path": "audio/case.wav", "noisy_file_digest": digest, "clean_file_digest": digest,
        "sample_rate_hz": 16000, "channels": 1, "sample_count": "160", "speaker_id": "speaker-1",
        "session_id": "session-1", "task": "ns", "annotations_digest": None,
        "source_partition": "synthetic", "allowed_use": ["evaluation"],
    }
    validator.validate("case", case)
    with pytest.raises(ValidationError):
        validator.validate("case", {**case, "private_path": "/Users/test"})


def test_no_remote_schema_fetch_or_unknown_schema():
    validator = Validator()
    with pytest.raises(ValidationError, match="unknown record kind"):
        validator.validate("not-a-schema", {})


def test_schema_index_digests_exist():
    from importlib import resources

    from audio_bench.schemas import schema_index
    index = schema_index()
    assert index["entries"]
    for item in index["entries"]:
        assert len(item["sha256"]) == 71
    checked_in = json.loads(Path("schemas/index.json").read_text())
    assert checked_in == index
    packaged = Path(resources.files("audio_bench").joinpath("schema_data"))
    for item in index["entries"]:
        assert (packaged / item["file"]).read_bytes() == (Path("schemas") / item["file"]).read_bytes()


def test_pinned_sdk_schema_bytes_and_actual_provider_descriptors_validate():
    for name in ("descriptor", "effective-config"):
        schema = load_sdk_schema(name)
        assert schema["$id"] == f"audio-sdk/{name}/0.1"
    for provider in ("speex.ns.v0", "dsp.highpass80.v0"):
        record = json.loads(Path(f"schemas/sdk/providers/{provider}.descriptor.json").read_text())
        validate_sdk_record("descriptor", record)
