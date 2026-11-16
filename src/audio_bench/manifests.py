# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Asset/case/cohort manifests, deterministic selection and frozen interval maps.

Everything here is frozen *before* a candidate runs. Synthetic fixtures produce
labelled correctness evidence; external real-corpus preparation is managed by
the dedicated acquisition scripts and status manifests.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np

from . import audio, canonical
from .errors import BlockedError, ValidationError
from .schemas import (
    Validator,
    case_inventory_digest as schemas_case_inventory_digest,
    dataset_content_id as schemas_dataset_content_id,
    verify_dataset_identity,
)

SYNTHETIC_TASK = "noise_suppression.synthetic.v1"
SYNTHETIC_DATASET_LABEL = "synthetic conformance fixtures (not speech, not corpus evidence)"
SMOKE_SELECTION_SALT = "ns-smoke-v1"
SMOKE_CASE_COUNT = 24

#: Rights review dates for first-party synthetic fixtures. These are deliberately explicit: the
#: generator is first-party code with no third-party samples, so no external clearance exists.
SYNTHETIC_RIGHTS_REVIEWER = "audio-bench maintainer (unassigned role)"
SYNTHETIC_RIGHTS_DATE = "2026-11-13T00:00:00Z"
SYNTHETIC_RIGHTS_EVIDENCE = "first-party deterministic generator; no third-party recording or model bytes"


@dataclass(frozen=True)
class SyntheticCase:
    case_id: str
    speaker_id: str
    session_id: str
    samples: int
    noise_seed: int
    duration_s: float


def _rng(seed: int) -> np.random.Generator:
    return np.random.Generator(np.random.PCG64(seed))


def _voiced_burst(rng: np.random.Generator, samples: int, f0: float) -> np.ndarray:
    """Harmonic phrase with an amplitude envelope. Deterministic given ``rng`` state."""
    t = np.arange(samples, dtype=np.float64) / audio.SAMPLE_RATE
    phase = 2.0 * np.pi * np.cumsum(f0 * (1.0 + 0.02 * np.sin(2.0 * np.pi * 3.0 * t))) / audio.SAMPLE_RATE
    signal = np.zeros(samples, dtype=np.float64)
    for harmonic, weight in ((1, 0.6), (2, 0.25), (3, 0.1), (5, 0.05)):
        signal += weight * np.sin(harmonic * phase)
    envelope = np.minimum(1.0, np.minimum(t / 0.05, (t[-1] - t) / 0.05))
    envelope = np.clip(envelope, 0.0, 1.0)
    pauses = ((t > 0.35) & (t < 0.45)) | ((t > 0.7) & (t < 0.78))
    envelope = envelope * (~pauses)
    return 0.28 * signal * envelope


def synthetic_pair(case: SyntheticCase) -> tuple[np.ndarray, np.ndarray]:
    """Return (clean, noisy) as float32 mono. Seeded, byte-identical across platforms."""
    clean_rng = _rng(case.noise_seed)
    noise_rng = _rng(case.noise_seed + 1)
    f0 = 110.0 + 7.0 * (case.noise_seed % 11)
    clean = _voiced_burst(clean_rng, case.samples, f0)
    noise = noise_rng.normal(0.0, 1.0, case.samples)
    # Deterministic coloured noise so the task is not trivial broadband denoising.
    kernel = np.array([1.0, -0.6, 0.2], dtype=np.float64)
    noise = np.convolve(noise, kernel, mode="same")
    noise = 0.06 * noise / max(1e-12, float(np.sqrt(np.mean(noise**2))))
    noisy = clean + noise
    return clean.astype(np.float32), noisy.astype(np.float32)


def synthetic_cases(*, pairs_per_speaker: int = 4, speakers: int = 6, duration_s: float = 1.0) -> list[SyntheticCase]:
    if pairs_per_speaker < 1 or speakers < 1:
        raise ValidationError("synthetic fixture dimensions must be positive")
    samples = int(round(duration_s * audio.SAMPLE_RATE))
    cases: list[SyntheticCase] = []
    for speaker_index in range(speakers):
        speaker = f"synthspk{speaker_index:02d}"
        for pair_index in range(pairs_per_speaker):
            case_id = f"{speaker}-p{pair_index:02d}"
            cases.append(
                SyntheticCase(
                    case_id=case_id,
                    speaker_id=speaker,
                    session_id=f"{speaker}-s{pair_index // 2:02d}",
                    samples=samples,
                    noise_seed=1_000 + speaker_index * 100 + pair_index,
                    duration_s=duration_s,
                )
            )
    return cases


def smoke_selection(cases: Iterable[Mapping[str, Any]], *, limit: int = SMOKE_CASE_COUNT) -> list[str]:
    """Deterministic round-robin speaker selection (B03 step 3).

    Speakers ascend lexicographically; inside a speaker, cases sort by
    ``sha256("ns-smoke-v1:<case-id>")`` with the case ID as tie-break. Cases are taken in
    round-robin speaker order until ``limit`` is reached.
    """
    if limit < 1:
        raise ValidationError("smoke selection limit must be positive")
    grouped: dict[str, list[tuple[str, str]]] = {}
    for entry in cases:
        case_id = entry["case_id"]
        speaker = entry["speaker_id"]
        if not isinstance(case_id, str) or not isinstance(speaker, str):
            raise ValidationError("case_id and speaker_id must be strings")
        key = hashlib.sha256(f"{SMOKE_SELECTION_SALT}:{case_id}".encode("utf-8")).hexdigest()
        grouped.setdefault(speaker, []).append((key, case_id))
    for entries in grouped.values():
        entries.sort()
    speakers = sorted(grouped)
    selected: list[str] = []
    position = 0
    while len(selected) < limit:
        progressed = False
        for speaker in speakers:
            entries = grouped[speaker]
            if position < len(entries):
                selected.append(entries[position][1])
                progressed = True
                if len(selected) == limit:
                    break
        if not progressed:
            break
        position += 1
    return selected


def _rights_entry() -> dict[str, str]:
    return {
        "decision": "allowed",
        "evidence_ref": SYNTHETIC_RIGHTS_EVIDENCE,
        "reviewer": SYNTHETIC_RIGHTS_REVIEWER,
        "reviewed_at": SYNTHETIC_RIGHTS_DATE,
    }


def _synthetic_generator_digest() -> str:
    """Content ID of the generator recipe (seeds live in the recipe, not in random state)."""
    recipe = {
        "generator": "audio_bench.manifests.synthetic_pair",
        "sample_rate_hz": audio.SAMPLE_RATE,
        "channels": audio.CHANNELS,
        "signal": "harmonic-phrase+coloured-noise",
        "seeds": {"base": 1000, "speaker_stride": 100, "noise_offset": 1},
        "normalization": "none",
        "sample_dtype": "float32",
    }
    return canonical.digest_of(recipe)


def build_synthetic_dataset(
    output: Path,
    *,
    validator: Validator | None = None,
    pairs_per_speaker: int = 4,
    speakers: int = 6,
    duration_s: float = 1.0,
) -> dict[str, Any]:
    """Write deterministic fixtures, case shard, case set, interval map and dataset manifest."""
    validator = validator or Validator()
    if output.exists() and any(output.iterdir()):
        raise ValidationError(f"synthetic manifest output must be a fresh/empty directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    audio_dir = output / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    cases = synthetic_cases(pairs_per_speaker=pairs_per_speaker, speakers=speakers, duration_s=duration_s)
    case_records: list[dict[str, Any]] = []
    file_records: list[dict[str, Any]] = []
    for case in cases:
        clean, noisy = synthetic_pair(case)
        clean_path = audio_dir / f"{case.case_id}.clean.wav"
        noisy_path = audio_dir / f"{case.case_id}.noisy.wav"
        audio.write_wav(clean_path, clean)
        audio.write_wav(noisy_path, noisy)
        if audio.pcm_digest(audio.read_wav(noisy_path)) != audio.pcm_digest(noisy):
            raise ValidationError(f"decode round trip changed PCM identity for {case.case_id}")
        case_records.append(
            {
                "schema_id": "audio-bench/case/0.1",
                "case_id": case.case_id,
                "dataset_id": "sha256:" + "0" * 64,  # assigned after the dataset identity is frozen
                "source_path": f"audio/{noisy_path.name}",
                "noisy_file_digest": audio.pcm_digest(noisy),
                "clean_file_digest": audio.pcm_digest(clean),
                "sample_rate_hz": audio.SAMPLE_RATE,
                "channels": audio.CHANNELS,
                "sample_count": str(len(noisy)),
                "speaker_id": case.speaker_id,
                "session_id": case.session_id,
                "task": SYNTHETIC_TASK,
                "annotations_digest": None,
                "source_partition": "synthetic",
                "allowed_use": ["evaluation", "redistribution", "public_playback"],
            }
        )
        for role, path, samples in (
            ("clean", clean_path, clean),
            ("noisy", noisy_path, noisy),
        ):
            file_records.append(
                {
                    "schema_id": "audio-bench/asset-file/0.1",
                    "relative_path": f"audio/{path.name}",
                    "file_sha256": audio.encoded_digest(path),
                    "file_bytes": str(path.stat().st_size),
                    "decoded_pcm_sha256": audio.pcm_digest(samples),
                    "sample_rate_hz": audio.SAMPLE_RATE,
                    "channels": audio.CHANNELS,
                    "sample_count": str(len(samples)),
                    "case_id": case.case_id,
                    "role": role,
                    "speaker_id": case.speaker_id,
                    "session_id": case.session_id,
                    "partition": "synthetic",
                }
            )
    file_payload = canonical.jsonl_bytes(sorted(file_records, key=lambda entry: entry["relative_path"]))
    (output / "files-0000.jsonl").write_bytes(file_payload)
    for record in file_records:
        validator.validate("asset-file", record)
    dataset = {
        "schema_id": "audio-bench/dataset/0.1",
        "identity_algorithm": canonical.JCS_IDENTITY_ALGORITHM,
        "dataset_id": "sha256:" + "0" * 64,
        "label": SYNTHETIC_DATASET_LABEL,
        "source": {
            "kind": "generated",
            "generator_digest": _synthetic_generator_digest(),
            "generator_recipe": "deterministic harmonic phrase + coloured noise; see audio_bench.manifests",
        },
        "file_shards": [
            {
                "shard_digest": "sha256:" + hashlib.sha256(file_payload).hexdigest(),
                "records": str(len(file_records)),
                "bytes": str(len(file_payload)),
            }
        ],
        "case_inventory_digest": schemas_case_inventory_digest(case_records),
        "decode_recipe": {
            "implementation": "soundfile",
            "version": _soundfile_version(),
            "container": "wav",
            "dtype": "float32",
            "channel_policy": "reject_non_mono",
        },
        "rights": {
            "acquisition": _rights_entry(),
            "evaluation": _rights_entry(),
            "redistribution": _rights_entry(),
            "public_playback": _rights_entry(),
        },
        "training_exposure": {"status": "known", "evidence_refs": [SYNTHETIC_RIGHTS_EVIDENCE]},
    }
    dataset["dataset_id"] = schemas_dataset_content_id(dataset)
    for record in case_records:
        record["dataset_id"] = dataset["dataset_id"]
        validator.validate("case", record)
    shard_payload = canonical.jsonl_bytes(sorted(case_records, key=lambda entry: entry["case_id"]))
    shard_path = output / "cases-0000.jsonl"
    shard_path.write_bytes(shard_payload)
    verify_dataset_identity(dataset, case_records)
    validator.validate("dataset", dataset)
    (output / "dataset.json").write_bytes(canonical.dumps(dataset))

    case_set = make_case_set(case_records, dataset["dataset_id"])
    validator.validate("case-set", case_set)
    (output / "case-set.json").write_bytes(canonical.dumps(case_set))

    intervals = make_intervals(case_records, case_set["case_set_id"], task=SYNTHETIC_TASK)
    validator.validate("scored-intervals", intervals)
    (output / "scored-intervals.json").write_bytes(canonical.dumps(intervals))

    smoke = smoke_selection(case_records)
    (output / "smoke-selection.json").write_bytes(
        canonical.dumps(
            {
                "schema_id": "audio-bench/smoke-selection/0.1",
                "case_set_id": case_set["case_set_id"],
                "algorithm": "round_robin_speakers_sha256_salt",
                "salt": SMOKE_SELECTION_SALT,
                "limit": str(SMOKE_CASE_COUNT),
                "case_ids": smoke,
            }
        )
    )
    return {
        "dataset": dataset,
        "case_set": case_set,
        "intervals": intervals,
        "cases": case_records,
        "files": file_records,
        "smoke_case_ids": smoke,
    }


def _soundfile_version() -> str:
    import soundfile

    version = getattr(soundfile, "__version__", None)
    if not version:
        raise BlockedError("asset_unavailable", "soundfile does not report a version")
    return str(version)


def make_case_set(case_records: list[Mapping[str, Any]], dataset_id: str) -> dict[str, Any]:
    if not case_records:
        raise ValidationError("a case set needs at least one case")
    entries = [
        {
            "case_id": record["case_id"],
            "noisy_file_digest": record["noisy_file_digest"],
            "clean_file_digest": record["clean_file_digest"],
            "sample_count": record["sample_count"],
            "speaker_id": record["speaker_id"],
            "source_partition": record["source_partition"],
        }
        for record in sorted(case_records, key=lambda item: item["case_id"])
    ]
    protocol = {
        "case_set": "sorted_by_case_id",
        "selection": "deterministic round-robin speakers",
        "task": SYNTHETIC_TASK,
    }
    case_set = {
        "schema_id": "audio-bench/case-set/0.1",
        "identity_algorithm": canonical.JCS_IDENTITY_ALGORITHM,
        "case_set_id": "sha256:" + "0" * 64,
        "dataset_id": dataset_id,
        "task": SYNTHETIC_TASK,
        "cases": entries,
        "selection_script_digest": None,
        "protocol_digest": canonical.digest_of(protocol),
    }
    case_set["case_set_id"] = canonical.content_id(case_set, "case_set_id")
    return case_set


def make_intervals(
    case_records: list[Mapping[str, Any]],
    case_set_id: str,
    *,
    task: str,
    protocol: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One frozen interval per case, shared by clean/raw/every candidate in the cohort."""
    entries = []
    for record in sorted(case_records, key=lambda item: item["case_id"]):
        sample_count = int(record["sample_count"])
        if sample_count <= 0:
            raise ValidationError(f"{record['case_id']}: empty case")
        entries.append(
            {
                "case_id": record["case_id"],
                "start_sample": "0",
                "end_sample": str(sample_count),
                "edge_exclusion_start": "0",
                "edge_exclusion_end": "0",
            }
        )
    intervals = {
        "schema_id": "audio-bench/scored-intervals/0.1",
        "identity_algorithm": canonical.JCS_IDENTITY_ALGORITHM,
        "scored_interval_set_id": "sha256:" + "0" * 64,
        "case_set_id": case_set_id,
        "entries": entries,
        "protocol_digest": canonical.digest_of(
            {"task": task, "rule": "single_interval_per_case", "refit_after_scoring": False, **(protocol or {})}
        ),
    }
    intervals["scored_interval_set_id"] = canonical.content_id(intervals, "scored_interval_set_id")
    return intervals


def load_case_records(dataset_dir: Path, dataset_manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Load case records and verify the semantic case inventory digest."""
    records: list[dict[str, Any]] = []
    shard_files = sorted(dataset_dir.glob("cases-*.jsonl"))
    if not shard_files:
        raise ValidationError("no case shards found")
    for shard in shard_files:
        payload = shard.read_bytes()
        for record in canonical.parse_jsonl(payload, path=shard.name):
            records.append(record)
    ids = [record["case_id"] for record in records]
    if len(set(ids)) != len(ids):
        raise ValidationError("duplicate case_id in dataset shards")
    verify_dataset_identity(dataset_manifest, records)
    return records


def load_file_records(dataset_dir: Path, dataset_manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Load the encoded-file inventory shards and verify their exact digests/counts."""
    shards = sorted(dataset_dir.glob("files-*.jsonl"))
    if not shards:
        raise ValidationError("no encoded file inventory shards found")
    actual: dict[str, tuple[str, int]] = {}
    records: list[dict[str, Any]] = []
    for shard in shards:
        payload = shard.read_bytes()
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        parsed = canonical.parse_jsonl(payload, path=shard.name)
        actual[digest] = (str(len(payload)), len(parsed))
        records.extend(parsed)
    declared = {
        entry["shard_digest"]: (entry["bytes"], int(entry["records"]))
        for entry in dataset_manifest["file_shards"]
    }
    if actual != declared:
        raise ValidationError("encoded file inventory shard digest/size/count mismatch")
    paths = [record["relative_path"] for record in records]
    if len(paths) != len(set(paths)):
        raise ValidationError("duplicate asset path in file inventory")
    return records


def verify_case_bytes(dataset_dir: Path, case_records: list[Mapping[str, Any]]) -> None:
    """Recompute encoded and decoded digests and verify case↔file-role closure."""
    dataset_path = dataset_dir / "dataset.json"
    dataset = canonical.require_canonical(dataset_path.read_bytes(), path=str(dataset_path))
    file_records = load_file_records(dataset_dir, dataset)
    file_by_case_role = {(entry["case_id"], entry["role"]): entry for entry in file_records}
    for record in case_records:
        for role, digest_key in (("noisy", "noisy_file_digest"), ("clean", "clean_file_digest")):
            if role == "clean" and record["clean_file_digest"] is None:
                continue
            entry = file_by_case_role.get((record["case_id"], role))
            if entry is None:
                raise ValidationError(f"missing {role} file inventory for {record['case_id']}")
            path = dataset_dir / entry["relative_path"]
            if not path.is_file():
                raise ValidationError(f"missing {role} file for {record['case_id']}", path=str(path))
            if audio.encoded_digest(path) != entry["file_sha256"]:
                raise ValidationError(f"{role} encoded file digest mismatch for {record['case_id']}", path=str(path))
            decoded = audio.read_wav(path)
            if audio.pcm_digest(decoded) != entry["decoded_pcm_sha256"] or entry["decoded_pcm_sha256"] != record[digest_key]:
                raise ValidationError(f"{role} decoded PCM digest mismatch for {record['case_id']}", path=str(path))
