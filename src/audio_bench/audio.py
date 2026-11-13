"""Decode/encode and PCM identity helpers.

Migration provenance: selected the small ``resample``, ``sample_interval``, ``chunks`` and
``pcm16`` primitives from the read-only source ``src/audioml_eval/audio.py`` (SHA-256 and exact
file path are in ``deps/source-inventory.json``). The no-resampling-at-16k policy, float32 PCM
identity and explicit signed-zero semantics below are new audio-bench rules; the source file was
not edited. No dataset/model/result directory was copied.

Canonical decoded PCM identity is SHA-256 over little-endian interleaved float32 bytes with **no
normalization and no signed-zero rewriting** (EVIDENCE_SPEC "Encoding and identity"). The encoded
container digest is recorded separately: a WAV container hash and a decoded PCM hash are different
artifacts and must never be interchanged.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import numpy as np
import soundfile as sf

from .errors import ValidationError

SAMPLE_RATE = 16000
CHANNELS = 1
FRAME_SAMPLES = 160


def encoded_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def pcm_digest(samples: np.ndarray) -> str:
    """Canonical decoded PCM digest: interleaved little-endian float32, bits preserved."""
    array = np.ascontiguousarray(np.asarray(samples, dtype="<f4"))
    return "sha256:" + hashlib.sha256(array.tobytes(order="C")).hexdigest()


def read_wav(path: Path, *, expected_rate: int = SAMPLE_RATE, expected_channels: int = CHANNELS) -> np.ndarray:
    """Decode to float32 mono; reject rate/channel surprises instead of resampling silently."""
    with open(path, "rb") as handle:
        head = handle.read(40)
    if head.startswith(b"version https://git-lfs.github.com/spec/"):
        raise ValidationError("Git LFS pointer is not audio", path=str(path))
    data, rate = sf.read(str(path), dtype="float32", always_2d=True)
    if rate != expected_rate:
        raise ValidationError(f"expected {expected_rate} Hz, found {rate} Hz", path=str(path))
    if data.shape[1] != expected_channels:
        raise ValidationError(f"expected {expected_channels} channel(s), found {data.shape[1]}", path=str(path))
    if not np.isfinite(data).all():
        raise ValidationError("non-finite samples in decoded audio", path=str(path))
    return np.ascontiguousarray(data[:, 0], dtype=np.float32)


def write_wav(path: Path, samples: np.ndarray, *, rate: int = SAMPLE_RATE) -> None:
    array = np.asarray(samples, dtype=np.float32)
    if array.ndim != 1 or not np.isfinite(array).all():
        raise ValidationError("audio must be finite mono float32 samples")
    if rate <= 0:
        raise ValidationError("sample rate must be positive")
    pcm = np.ascontiguousarray(array.astype("<f4", copy=False)).tobytes()
    # Minimal deterministic RIFF/WAVE IEEE float32 container. Some libsndfile builds add a
    # timestamped PEAK chunk; writing the 44-byte canonical header directly avoids that source
    # of cross-run container-hash variation while leaving decoded PCM unchanged.
    fmt = struct.pack("<HHIIHH", 3, 1, rate, rate * 4, 4, 32)
    riff_size = 4 + 8 + len(fmt) + 8 + len(pcm)
    if riff_size > 0xFFFFFFFF:
        raise ValidationError("WAV exceeds the RIFF 32-bit size limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"RIFF")
        handle.write(struct.pack("<I", riff_size))
        handle.write(b"WAVEfmt ")
        handle.write(struct.pack("<I", len(fmt)))
        handle.write(fmt)
        handle.write(b"data")
        handle.write(struct.pack("<I", len(pcm)))
        handle.write(pcm)


def pcm16(samples: np.ndarray) -> tuple[np.ndarray, int]:
    """PCM16 preview + clipping count; previews never replace the float32 evidence artifact."""
    array = np.asarray(samples, dtype=np.float64)
    rounded = np.rint(array * 32768.0)
    clipped = int(np.count_nonzero((rounded < -32768) | (rounded > 32767)))
    return np.clip(rounded, -32768, 32767).astype(np.int16), clipped


def to_frames(samples: np.ndarray, *, frame_samples: int = FRAME_SAMPLES) -> list[np.ndarray]:
    """Split into fixed frames; the final frame is zero-padded by the caller, never silently dropped."""
    padded = samples
    remainder = len(samples) % frame_samples
    if remainder:
        padded = np.concatenate([samples, np.zeros(frame_samples - remainder, dtype=np.float32)])
    return [padded[index : index + frame_samples] for index in range(0, len(padded), frame_samples)]


def valid_count_for_frame(total_samples: int, frame_index: int, *, frame_samples: int = FRAME_SAMPLES) -> int:
    """Valid samples in frame ``frame_index``; only the final frame may be short."""
    start = frame_index * frame_samples
    return max(0, min(frame_samples, total_samples - start))
