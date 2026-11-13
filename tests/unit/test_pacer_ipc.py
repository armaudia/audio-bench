import io
import json
import struct
import hashlib
from pathlib import Path

import pytest

from audio_bench import canonical
from audio_bench.errors import ValidationError
from audio_bench.ipc import (
    AUDIO,
    END,
    ERROR_HEADER,
    HEADER,
    HEADER_BYTES,
    INPUT_FINAL,
    INPUT_META,
    MAX_MESSAGE_BYTES,
    OUTPUT_META,
    PHASE_DRAIN,
    PHASE_PROCESS,
    UINT64_MAX,
    Drained,
    DriverError,
    EndInput,
    InputFrame,
    Message,
    MessageType,
    OutputFrame,
    Prepare,
    Ready,
    Reset,
    SequenceGuard,
    read_exact,
    read_message,
    write_all,
)
from audio_bench.pacer import (
    Accounting,
    availability_delay_ns,
    conservation,
    deadline_missed,
    frame_complete_ns,
    latency_summary,
    sample_capture_ns,
)


def test_frame_schedule_is_at_completion_not_frame_start():
    assert frame_complete_ns(7, 0) == 10_000_007
    assert frame_complete_ns(7, 1) == 20_000_007
    assert sample_capture_ns(7, 160) == 10_000_007


def test_availability_and_deadline_use_first_valid_sample():
    assert availability_delay_ns(20_000_000, 0, 160) == 10_000_000
    assert deadline_missed(20_000_001, 0, 160, 10_000_000)
    assert not deadline_missed(20_000_000, 0, 160, 10_000_000)
    with pytest.raises(ValidationError, match="negative"):
        availability_delay_ns(1, 0, 160)


def test_exact_accounting_fixture():
    result = Accounting(cpu_ns=2_000_000_000, wall_ns=1_000_000_000, accepted_samples=64_000).as_dict()
    assert result["cpu_occupancy_cores"] == "2"
    assert result["compute_cost_cpu_s_per_audio_s"] == "1/2"
    assert result["throughput_audio_s_per_wall_s"] == "4"


def test_large_clock_is_exact_string_and_nearest_rank():
    value = 9_007_199_254_740_993
    assert str(value) == "9007199254740993"
    assert latency_summary([1, 2, 3, 4])["p95"] == "4"


def test_conservation_rejects_midstream_gap_and_accepts_edges():
    assert conservation([(0, 100)], [(0, 40), (40, 100)])[0]
    assert not conservation([(0, 100)], [(0, 40), (50, 100)])[0]
    assert conservation([(0, 100)], [(10, 90)], [(0, 10), (90, 100)])[0]


def _payload_messages():
    config = canonical.dumps({"provider_id": "raw.control.v0"})
    audio = (0.0,) * 160
    return [
        Message(MessageType.PREPARE, 0, 0, Prepare(__import__("hashlib").sha256(config).digest(), config).encode()),
        Message(MessageType.READY, 0, 1, Ready(b"b" * 32, b"d" * 32).encode()),
        Message(MessageType.INPUT, 0, 2, InputFrame(1, 0, 160, 0, audio).encode()),
        Message(MessageType.OUTPUT, 0, 3, OutputFrame(1, -256, 160, 96, 64, 1, PHASE_PROCESS, 10, 20, audio).encode()),
        Message(MessageType.END_INPUT, 0, 4, EndInput(1, 160).encode()),
        Message(MessageType.OUTPUT, 0, 5, OutputFrame(1, 160, 16, 0, 5, 2, PHASE_DRAIN, 20, 21, audio).encode()),
        Message(MessageType.DRAINED, 0, 6, Drained(1, 160).encode()),
        Message(MessageType.ERROR, 0, 7, DriverError(1, 4, "fixture failure").encode()),
        Message(MessageType.RESET, 0, 8, Reset(2, 0).encode()),
        Message(MessageType.CLOSE, 0, 9, b""),
    ]


def test_every_message_type_round_trips_and_drain_completion_has_no_audio():
    messages = _payload_messages()
    assert {message.type for message in messages} == set(MessageType)
    for message in messages:
        assert Message.decode(message.encode()) == message
    drained = messages[6]
    assert drained.type is MessageType.DRAINED
    assert len(drained.payload) == END.size
    drain_audio = messages[5]
    assert drain_audio.type is MessageType.OUTPUT
    assert OutputFrame.decode(drain_audio.payload).phase == PHASE_DRAIN


def test_input_and_output_flags_are_distinct_and_partial_input_padding_is_zero():
    final = InputFrame(1, 0, 3, INPUT_FINAL, (1.0, 2.0, 3.0) + (0.0,) * 157)
    assert InputFrame.decode(final.encode()) == final
    with pytest.raises(ValidationError, match="final padding must be zero"):
        InputFrame(1, 0, 3, INPUT_FINAL, (1.0, 2.0, 3.0, 4.0) + (0.0,) * 156).encode()
    with pytest.raises(ValidationError, match="unknown INPUT flags"):
        InputFrame(1, 0, 160, 2, (0.0,) * 160).encode()
    with pytest.raises(ValidationError, match="unknown OUTPUT flags"):
        OutputFrame(1, 0, 160, 0, 160, 8, PHASE_PROCESS, 1, 2, (0.0,) * 160).encode()


def test_partial_drain_output_maps_only_valid_samples_to_source():
    output = OutputFrame(8, 256, 100, 10, 35, 2, PHASE_DRAIN, 11, 12, (0.0,) * 160)
    decoded = OutputFrame.decode(output.encode())
    assert decoded.produced_count == 100
    assert (decoded.source_first_sample + decoded.valid_offset,
            decoded.source_first_sample + decoded.valid_offset + decoded.valid_count) == (266, 301)


@pytest.mark.parametrize("bad", [-1, 1 << 64])
def test_epoch_uint64_boundaries_are_checked(bad):
    with pytest.raises(ValidationError, match="uint64"):
        EndInput(bad, 0).encode()


def test_int64_boundaries_and_overflow_are_checked():
    assert EndInput(0, -(1 << 63)).encode()
    assert EndInput(UINT64_MAX, (1 << 63) - 1).encode()
    with pytest.raises(ValidationError, match="int64"):
        EndInput(0, 1 << 63).encode()
    with pytest.raises(ValidationError, match="int64"):
        InputFrame(0, -(1 << 63) - 1, 160, 0, (0.0,) * 160).encode()


def test_each_payload_rejects_truncation_and_reserved_or_invalid_fields():
    messages = _payload_messages()
    for message in messages:
        with pytest.raises(ValidationError):
            Message.decode(message.encode()[:-1])
    input_payload = bytearray(messages[2].payload)
    struct.pack_into("<I", input_payload, 24, 1)
    with pytest.raises(ValidationError, match="reserved"):
        InputFrame.decode(input_payload)
    output_payload = bytearray(messages[3].payload)
    struct.pack_into("<I", output_payload, 28, 1 << 5)  # output flags field
    with pytest.raises(ValidationError, match="unknown OUTPUT flags"):
        OutputFrame.decode(output_payload)
    with pytest.raises(ValidationError, match="not UTF-8"):
        DriverError.decode(ERROR_HEADER.pack(1, 4, 1) + b"\xff")


def test_message_header_rejects_unknown_type_bad_lengths_and_oversize_before_read():
    good = _payload_messages()[1].encode()
    unknown = bytearray(good)
    struct.pack_into("<H", unknown, 6, 999)
    with pytest.raises(ValidationError, match="unknown message type"):
        Message.decode(unknown)
    declared_too_large = HEADER.pack(0x41425530, 1, int(MessageType.READY), 65_000, 0, 0)
    with pytest.raises(ValidationError, match="payload length"):
        Message.decode(declared_too_large)
    with pytest.raises(ValidationError, match="64 KiB"):
        Message.decode(b"x" * (MAX_MESSAGE_BYTES + 1))
    with pytest.raises(ValidationError, match="uint64"):
        Message(MessageType.READY, 0, -1, Ready(b"b" * 32, b"d" * 32).encode()).encode()


def test_sequence_guard_rejects_duplicate_out_of_order_and_exhaustion():
    guard = SequenceGuard()
    guard.accept(Message(MessageType.READY, 1, 0, Ready(b"b" * 32, b"d" * 32).encode()))
    with pytest.raises(ValidationError, match="expected sequence 1"):
        guard.accept(Message(MessageType.READY, 1, 0, Ready(b"b" * 32, b"d" * 32).encode()))
    with pytest.raises(ValidationError, match="expected sequence 1"):
        guard.accept(Message(MessageType.READY, 1, 2, Ready(b"b" * 32, b"d" * 32).encode()))
    guard.next_sequence[2] = UINT64_MAX
    guard.accept(Message(MessageType.READY, 2, UINT64_MAX, Ready(b"b" * 32, b"d" * 32).encode()))
    with pytest.raises(ValidationError, match="expected sequence None"):
        guard.accept(Message(MessageType.READY, 2, UINT64_MAX, Ready(b"b" * 32, b"d" * 32).encode()))


class FragmentReader:
    def __init__(self, payload, fragment=1):
        self.stream = io.BytesIO(payload)
        self.fragment = fragment

    def read(self, size=-1):
        return self.stream.read(min(size, self.fragment))


def test_fragmented_reads_and_truncated_streams():
    encoded = _payload_messages()[2].encode()
    assert read_message(FragmentReader(encoded, 3)) == Message.decode(encoded)
    assert read_message(FragmentReader(b"")) is None
    with pytest.raises(ValidationError, match="truncated"):
        read_message(FragmentReader(encoded[:-1], 2))
    with pytest.raises(ValidationError, match="before allocation"):
        read_message(FragmentReader(HEADER.pack(0x41425530, 1, 2, 65_513, 0, 0), 4))


def test_fragmented_write_completes_all_bytes():
    class ShortWriter(io.BytesIO):
        def write(self, value):
            return super().write(value[:3])
    message = _payload_messages()[0]
    sink = ShortWriter()
    write_all(sink, message.encode())
    assert sink.getvalue() == message.encode()


def test_frozen_golden_vector_for_every_message_type():
    vectors = json.loads(Path("tests/fixtures/ipc-v1-golden.json").read_text())
    actual = {message.type.name: message.encode().hex() for message in _payload_messages()}
    assert {row["type"]: row["frame_hex"] for row in vectors} == actual
