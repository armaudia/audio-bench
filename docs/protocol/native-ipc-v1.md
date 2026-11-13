# Native driver IPC protocol v1

This is the wire contract for the B04 collector/driver pair. It is transport-neutral over a
bounded byte stream (the implementation uses inherited anonymous pipes). Integers are little
endian. No message contains a path, URL, executable, approval, or publisher credential. A receiver
validates the fixed header and payload length before allocating or reading payload storage.

## Frame header

All frames begin with exactly 24 bytes, `struct.Struct("<IHHIIQ")`:

| Offset | Type | Meaning |
|---:|---|---|
| 0 | u32 | magic `0x41425530` (`ABU0`) |
| 4 | u16 | version `1` |
| 6 | u16 | message type: PREPARE=1, READY=2, INPUT=3, OUTPUT=4, END_INPUT=5, DRAINED=6, ERROR=7, RESET=8, CLOSE=9 |
| 8 | u32 | exact following payload byte count |
| 12 | u32 | stream index, `[0,64)` |
| 16 | u64 | per-stream sequence, begins at zero and increases by exactly one |

A frame is at most 65,536 bytes; payload is at most 65,512 bytes. Unknown types/versions,
truncation, trailing bytes, wrong sequence, duplicate sequence, and invalid fields are protocol
errors. Clean EOF between frames is distinct from EOF in a header/payload. Readers handle fragmented
reads and do not allocate from an unchecked declared length.

## Payloads

All formats use explicit `struct.Struct` sizes; audio carries 160 little-endian IEEE float32 values.

| Type | Payload layout | Purpose |
|---|---|---|
| PREPARE | 32 raw SHA-256 bytes, u32 config length, canonical UTF-8 JSON bytes | Bind exact effective config before driver creates an SDK session; digest must match. Config <= 61,440 bytes. |
| READY | 32-byte build digest, 32-byte descriptor digest | Driver readiness and implementation identity. |
| INPUT | `<QqIII` (epoch, first source sample, valid count, input flags, reserved=0), then 160 f32 | Input. Flags are **input-only**: bit 0 `INPUT_FINAL`; otherwise valid count must be 160. Final count is 1–159 and remaining padded samples must be zero. |
| OUTPUT | `<QqIIIIIqq` (epoch, source_first, produced count, valid offset/count, output flags, phase, diagnostic service begin/end ns), then 160 f32 | Process or drain audio. Produced count is 0–160. Valid samples are `[valid_offset, valid_offset+valid_count)` within the produced prefix. `source_first` maps sample 0; first valid source position is `source_first+valid_offset`. Phase: PROCESS=0, DRAIN=1. |
| END_INPUT | `<Qq` (epoch, exclusive accepted source end) | Closes admission after the final INPUT. |
| DRAINED | `<Qq` (epoch, acknowledged accepted source end) | Completion acknowledgement only; **contains no audio**. Drain audio is emitted in OUTPUT/phase DRAIN before this acknowledgement. |
| ERROR | `<QiI` (epoch, SDK status int32, UTF-8 byte count), then strict UTF-8 bytes | Bounded failure diagnostic; status is an SDK v0 status. |
| RESET | `<Qq` (strictly increasing epoch, first source sample) | Explicitly resets a session between independent recordings; collector waits for READY acknowledgement before next case. |
| CLOSE | empty | Closes a drained session and exits normally; EOF without CLOSE is incomplete protocol. |

OUTPUT flags are the SDK `AS_RESULT_*` values: startup padding=1, final padding=2, concealment=4.
They do not share INPUT flag semantics: numeric bit 0 on INPUT means final input; bit 0 on OUTPUT
means startup padding. Concealment must have zero valid samples. Service timestamps are
candidate-reported diagnostics only; collector receive clocks own availability/deadline evidence.

For partial drain output, `produced_count` counts actual samples present at the start of the output
buffer; it is independent of `valid_count`. `source_first_sample` and valid offset/count give the
exact source interval. The collector never infers produced samples from valid samples or uses
DRAINED as an audio frame. It checks non-overlap, epoch, interval union, and the accepted end.

## Golden bytes and boundary tests

`tests/fixtures/ipc-v1-golden.json` contains one complete encoded frame per type. The unit tests
round-trip all types and reject malformed lengths, reserved bits, unknown flags/types, invalid UTF-8,
non-finite/overflowing f32, signed/unsigned overflow, duplicate/out-of-order sequences, truncated
streams and oversized declarations. These vectors are frozen before the native consumer is compiled.
