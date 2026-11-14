# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Strict protocol-v1 codec for the supervised native driver/collector boundary.

A DRAINED message is an end-of-stream acknowledgement only. Drain audio is always an OUTPUT
message with phase=DRAIN; this keeps completion distinct from audio data. INPUT flags are
``INPUT_FINAL`` only. OUTPUT flags are SDK ``AS_RESULT_*`` validity flags and are never interpreted
as INPUT flags.
"""
from __future__ import annotations

import hashlib
import io
import math
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import BinaryIO

from . import canonical
from .errors import ValidationError

MAGIC = 0x41425530
PROTOCOL_VERSION = 1
HEADER = struct.Struct("<IHHIIQ")
HEADER_BYTES = HEADER.size
MAX_MESSAGE_BYTES = 64 * 1024
MAX_PAYLOAD_BYTES = MAX_MESSAGE_BYTES - HEADER_BYTES
MAX_STREAMS = 64
FRAME_SAMPLES = 160
UINT32_MAX = (1 << 32) - 1
UINT64_MAX = (1 << 64) - 1
INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1

INPUT_META = struct.Struct("<QqIII")  # epoch, first_sample, valid_count, input_flags, reserved
OUTPUT_META = struct.Struct("<QqIIIIIqq")  # epoch, source_first, produced, offset, valid, flags, phase, service_begin/end
AUDIO = struct.Struct("<160f")
END = struct.Struct("<Qq")
READY = struct.Struct("<32s32s")
PREPARE = struct.Struct("<32sI")
ERROR_HEADER = struct.Struct("<QiI")


class MessageType(IntEnum):
    PREPARE = 1
    READY = 2
    INPUT = 3
    OUTPUT = 4
    END_INPUT = 5
    DRAINED = 6
    ERROR = 7
    RESET = 8
    CLOSE = 9


INPUT_FINAL = 1
INPUT_FLAGS = INPUT_FINAL
OUTPUT_STARTUP_PADDING = 1
OUTPUT_FINAL_PADDING = 2
OUTPUT_CONCEALMENT = 4
OUTPUT_FLAGS = OUTPUT_STARTUP_PADDING | OUTPUT_FINAL_PADDING | OUTPUT_CONCEALMENT
PHASE_PROCESS = 0
PHASE_DRAIN = 1


def _uint(value: int, bits: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 1 << bits:
        raise ValidationError(f"{field_name} must be uint{bits}")


def _sint(value: int, bits: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not -(1 << (bits - 1)) <= value < 1 << (bits - 1):
        raise ValidationError(f"{field_name} must be int{bits}")


def _digest(value: bytes, name: str) -> bytes:
    if not isinstance(value, bytes) or len(value) != 32:
        raise ValidationError(f"{name} must be exactly 32 raw SHA-256 bytes")
    return value


def _samples(values: tuple[float, ...]) -> tuple[float, ...]:
    if len(values) != FRAME_SAMPLES:
        raise ValidationError("audio payload must carry exactly 160 float32 samples")
    if any(not math.isfinite(value) for value in values):
        raise ValidationError("non-finite sample in audio payload")
    try:
        packed = AUDIO.pack(*values)
    except (OverflowError, struct.error):
        raise ValidationError("audio sample is not representable as finite float32") from None
    result = AUDIO.unpack(packed)
    if any(not math.isfinite(value) for value in result):
        raise ValidationError("audio sample overflows finite float32")
    return result


@dataclass(frozen=True)
class Prepare:
    config_sha256: bytes
    config_json: bytes

    def encode(self) -> bytes:
        _digest(self.config_sha256, "config_sha256")
        if not self.config_json or len(self.config_json) > 60 * 1024:
            raise ValidationError("PREPARE config length out of range")
        if hashlib.sha256(self.config_json).digest() != self.config_sha256:
            raise ValidationError("PREPARE config digest mismatch")
        try:
            self.config_json.decode("utf-8", "strict")
        except UnicodeDecodeError:
            raise ValidationError("PREPARE config is not UTF-8") from None
        config = canonical.require_canonical(self.config_json)
        if not isinstance(config, dict):
            raise ValidationError("PREPARE config must be a canonical JSON object")
        return PREPARE.pack(self.config_sha256, len(self.config_json)) + self.config_json

    @classmethod
    def decode(cls, payload: bytes) -> "Prepare":
        if len(payload) < PREPARE.size:
            raise ValidationError("PREPARE payload truncated")
        digest, length = PREPARE.unpack_from(payload)
        if length == 0 or length > 60 * 1024 or len(payload) != PREPARE.size + length:
            raise ValidationError("PREPARE config length mismatch or out of bounds")
        value = cls(digest, payload[PREPARE.size:])
        value.encode()
        return value


@dataclass(frozen=True)
class Ready:
    build_sha256: bytes
    descriptor_sha256: bytes

    def encode(self) -> bytes:
        return READY.pack(_digest(self.build_sha256, "build_sha256"), _digest(self.descriptor_sha256, "descriptor_sha256"))

    @classmethod
    def decode(cls, payload: bytes) -> "Ready":
        if len(payload) != READY.size:
            raise ValidationError(f"READY payload must be {READY.size} bytes")
        return cls(*READY.unpack(payload))


@dataclass(frozen=True)
class InputFrame:
    epoch: int
    first_sample: int
    valid_count: int
    flags: int
    samples: tuple[float, ...]

    def encode(self) -> bytes:
        _uint(self.epoch, 64, "epoch")
        _sint(self.first_sample, 64, "first_sample")
        _uint(self.valid_count, 32, "valid_count")
        _uint(self.flags, 32, "INPUT flags")
        if self.flags & ~INPUT_FLAGS:
            raise ValidationError("unknown INPUT flags")
        if self.flags & INPUT_FINAL:
            if not 1 <= self.valid_count < FRAME_SAMPLES:
                raise ValidationError("INPUT_FINAL requires valid_count 1..159")
        elif self.valid_count != FRAME_SAMPLES:
            raise ValidationError("non-final INPUT requires 160 valid samples")
        samples = _samples(self.samples)
        if self.flags & INPUT_FINAL and any(sample != 0.0 for sample in samples[self.valid_count:]):
            raise ValidationError("INPUT final padding must be zero")
        return INPUT_META.pack(self.epoch, self.first_sample, self.valid_count, self.flags, 0) + AUDIO.pack(*samples)

    @classmethod
    def decode(cls, payload: bytes) -> "InputFrame":
        expected = INPUT_META.size + AUDIO.size
        if len(payload) != expected:
            raise ValidationError(f"INPUT payload must be exactly {expected} bytes")
        epoch, first, valid, flags, reserved = INPUT_META.unpack_from(payload)
        if reserved:
            raise ValidationError("INPUT reserved field must be zero")
        frame = cls(epoch, first, valid, flags, AUDIO.unpack_from(payload, INPUT_META.size))
        frame.encode()
        return frame


@dataclass(frozen=True)
class OutputFrame:
    epoch: int
    source_first_sample: int
    produced_count: int
    valid_offset: int
    valid_count: int
    flags: int
    phase: int
    service_begin_ns: int
    service_end_ns: int
    samples: tuple[float, ...]

    def encode(self) -> bytes:
        _uint(self.epoch, 64, "epoch")
        _sint(self.source_first_sample, 64, "source_first_sample")
        for name, value in (("produced_count", self.produced_count), ("valid_offset", self.valid_offset),
                            ("valid_count", self.valid_count), ("OUTPUT flags", self.flags), ("phase", self.phase)):
            _uint(value, 32, name)
        _sint(self.service_begin_ns, 64, "service_begin_ns")
        _sint(self.service_end_ns, 64, "service_end_ns")
        if self.produced_count > FRAME_SAMPLES:
            raise ValidationError("OUTPUT produced_count exceeds 160")
        if self.valid_offset > self.produced_count or self.valid_count > self.produced_count - self.valid_offset:
            raise ValidationError("OUTPUT valid interval exceeds produced samples")
        if self.flags & ~OUTPUT_FLAGS:
            raise ValidationError("unknown OUTPUT flags")
        if self.flags & OUTPUT_CONCEALMENT and self.valid_count != 0:
            raise ValidationError("concealment OUTPUT must have valid_count=0")
        if self.phase not in (PHASE_PROCESS, PHASE_DRAIN):
            raise ValidationError("unknown OUTPUT phase")
        if self.service_begin_ns < 0 or self.service_end_ns < 0:
            raise ValidationError("diagnostic service clocks must be nonnegative")
        if self.service_end_ns and self.service_begin_ns > self.service_end_ns:
            raise ValidationError("diagnostic service clocks are reversed")
        samples = _samples(self.samples)
        return OUTPUT_META.pack(self.epoch, self.source_first_sample, self.produced_count, self.valid_offset,
                                self.valid_count, self.flags, self.phase, self.service_begin_ns,
                                self.service_end_ns) + AUDIO.pack(*samples)

    @classmethod
    def decode(cls, payload: bytes) -> "OutputFrame":
        expected = OUTPUT_META.size + AUDIO.size
        if len(payload) != expected:
            raise ValidationError(f"OUTPUT payload must be exactly {expected} bytes")
        frame = cls(*OUTPUT_META.unpack_from(payload), AUDIO.unpack_from(payload, OUTPUT_META.size))
        frame.encode()
        return frame


@dataclass(frozen=True)
class EndInput:
    epoch: int
    end_sample: int

    def encode(self) -> bytes:
        _uint(self.epoch, 64, "epoch")
        _sint(self.end_sample, 64, "end_sample")
        return END.pack(self.epoch, self.end_sample)

    @classmethod
    def decode(cls, payload: bytes) -> "EndInput":
        if len(payload) != END.size:
            raise ValidationError(f"END_INPUT payload must be {END.size} bytes")
        value = cls(*END.unpack(payload))
        value.encode()
        return value


@dataclass(frozen=True)
class Drained:
    epoch: int
    accepted_end_sample: int

    def encode(self) -> bytes:
        _uint(self.epoch, 64, "epoch")
        _sint(self.accepted_end_sample, 64, "accepted_end_sample")
        return END.pack(self.epoch, self.accepted_end_sample)

    @classmethod
    def decode(cls, payload: bytes) -> "Drained":
        if len(payload) != END.size:
            raise ValidationError(f"DRAINED acknowledgement must be {END.size} bytes")
        value = cls(*END.unpack(payload))
        value.encode()
        return value


@dataclass(frozen=True)
class Reset:
    epoch: int
    first_input_sample: int

    def encode(self) -> bytes:
        _uint(self.epoch, 64, "epoch")
        _sint(self.first_input_sample, 64, "first_input_sample")
        return END.pack(self.epoch, self.first_input_sample)

    @classmethod
    def decode(cls, payload: bytes) -> "Reset":
        if len(payload) != END.size:
            raise ValidationError(f"RESET payload must be {END.size} bytes")
        value = cls(*END.unpack(payload))
        value.encode()
        return value


@dataclass(frozen=True)
class DriverError:
    epoch: int
    status: int
    message: str

    def encode(self) -> bytes:
        _uint(self.epoch, 64, "epoch")
        _sint(self.status, 32, "status")
        if self.status not in range(0, 11):
            raise ValidationError("ERROR status is not an audio-sdk v0 status")
        if not isinstance(self.message, str):
            raise ValidationError("ERROR message must be text")
        text = self.message.encode("utf-8", "strict")
        if len(text) > MAX_PAYLOAD_BYTES - ERROR_HEADER.size:
            raise ValidationError("ERROR message exceeds payload bound")
        return ERROR_HEADER.pack(self.epoch, self.status, len(text)) + text

    @classmethod
    def decode(cls, payload: bytes) -> "DriverError":
        if len(payload) < ERROR_HEADER.size:
            raise ValidationError("ERROR payload truncated")
        epoch, status, length = ERROR_HEADER.unpack_from(payload)
        if length > MAX_PAYLOAD_BYTES - ERROR_HEADER.size or len(payload) != ERROR_HEADER.size + length:
            raise ValidationError("ERROR message length mismatch or out of bounds")
        try:
            text = payload[ERROR_HEADER.size:].decode("utf-8", "strict")
        except UnicodeDecodeError:
            raise ValidationError("ERROR message is not UTF-8") from None
        value = cls(epoch, status, text)
        value.encode()
        return value


def _decode_empty(payload: bytes, name: str) -> None:
    if payload:
        raise ValidationError(f"{name} payload must be empty")


_PAYLOAD_DECODERS = {
    MessageType.PREPARE: Prepare.decode,
    MessageType.READY: Ready.decode,
    MessageType.INPUT: InputFrame.decode,
    MessageType.OUTPUT: OutputFrame.decode,
    MessageType.END_INPUT: EndInput.decode,
    MessageType.DRAINED: Drained.decode,
    MessageType.ERROR: DriverError.decode,
    MessageType.RESET: Reset.decode,
    MessageType.CLOSE: lambda payload: _decode_empty(payload, "CLOSE"),
}


@dataclass(frozen=True)
class Message:
    type: MessageType
    stream: int
    sequence: int
    payload: bytes = b""

    def encode(self) -> bytes:
        try:
            kind = MessageType(self.type)
        except (ValueError, TypeError):
            raise ValidationError(f"unknown message type {self.type!r}") from None
        _uint(self.stream, 32, "stream")
        _uint(self.sequence, 64, "sequence")
        if self.stream >= MAX_STREAMS:
            raise ValidationError("stream index out of range")
        if not isinstance(self.payload, bytes) or len(self.payload) > MAX_PAYLOAD_BYTES:
            raise ValidationError("message payload exceeds 64 KiB frame cap")
        _PAYLOAD_DECODERS[kind](self.payload)
        return HEADER.pack(MAGIC, PROTOCOL_VERSION, int(kind), len(self.payload), self.stream, self.sequence) + self.payload

    @classmethod
    def decode(cls, frame: bytes) -> "Message":
        if len(frame) < HEADER_BYTES:
            raise ValidationError("short header: message is truncated")
        if len(frame) > MAX_MESSAGE_BYTES:
            raise ValidationError("message exceeds 64 KiB")
        magic, version, type_value, payload_bytes, stream, sequence = HEADER.unpack_from(frame)
        if magic != MAGIC:
            raise ValidationError(f"bad magic 0x{magic:08x}")
        if version != PROTOCOL_VERSION:
            raise ValidationError(f"unsupported protocol version {version}")
        if payload_bytes > MAX_PAYLOAD_BYTES or len(frame) != HEADER_BYTES + payload_bytes:
            raise ValidationError("declared payload length mismatch or exceeds 64 KiB")
        try:
            kind = MessageType(type_value)
        except (ValueError, TypeError):
            raise ValidationError(f"unknown message type {type_value}") from None
        if stream >= MAX_STREAMS:
            raise ValidationError("stream index out of range")
        payload = frame[HEADER_BYTES:]
        _PAYLOAD_DECODERS[kind](payload)
        return cls(kind, stream, sequence, payload)


@dataclass
class SequenceGuard:
    next_sequence: dict[int, int | None] = field(default_factory=dict)

    def accept(self, message: Message) -> None:
        expected = self.next_sequence.get(message.stream, 0)
        if expected is None or message.sequence != expected:
            raise ValidationError(f"stream {message.stream}: expected sequence {expected}, got {message.sequence}")
        self.next_sequence[message.stream] = None if expected == UINT64_MAX else expected + 1


def read_exact(reader: BinaryIO, count: int, *, allow_clean_eof: bool = False) -> bytes | None:
    """Read exactly count bytes despite fragmented pipes; distinguish clean EOF from truncation."""
    if count < 0 or count > MAX_MESSAGE_BYTES:
        raise ValidationError("read size out of bounds")
    chunks = bytearray()
    while len(chunks) < count:
        chunk = reader.read(count - len(chunks))
        if chunk is None:
            raise ValidationError("nonblocking IPC read would block; poll before retrying")
        if not chunk:
            if allow_clean_eof and not chunks:
                return None
            raise ValidationError("truncated IPC stream")
        chunks.extend(chunk)
    return bytes(chunks)


def read_message(reader: BinaryIO) -> Message | None:
    header = read_exact(reader, HEADER_BYTES, allow_clean_eof=True)
    if header is None:
        return None
    magic, version, kind, payload_bytes, stream, sequence = HEADER.unpack(header)
    if magic != MAGIC or version != PROTOCOL_VERSION:
        raise ValidationError("invalid IPC header magic/version")
    if payload_bytes > MAX_PAYLOAD_BYTES:
        raise ValidationError("declared payload exceeds 64 KiB before allocation")
    try:
        MessageType(kind)
    except ValueError:
        raise ValidationError(f"unknown message type {kind}") from None
    if stream >= MAX_STREAMS:
        raise ValidationError("stream index out of range")
    payload = read_exact(reader, payload_bytes)
    assert payload is not None
    return Message.decode(header + payload)


def write_all(writer: BinaryIO, frame: bytes) -> None:
    view = memoryview(frame)
    sent = 0
    while sent < len(view):
        count = writer.write(view[sent:])
        if count is None:
            raise ValidationError("nonblocking IPC write would block; poll before retrying")
        if count <= 0:
            raise ValidationError("IPC write made no progress")
        sent += count
    if hasattr(writer, "flush"):
        writer.flush()


ERROR_CODES = {0: "ok", 1: "invalid_argument", 2: "unsupported", 3: "resource_exhausted", 4: "backend_failure",
               5: "needs_reset", 6: "not_ready", 7: "end_of_stream", 8: "busy", 9: "closed", 10: "duplicate"}
