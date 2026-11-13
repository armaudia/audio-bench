# audio-bench testing and acceptance plan

The test IDs below define work to implement. No benchmark was run while writing the handoff. Unit tests use only synthetic fixtures; real corpora/hardware/rights are integration prerequisites. `blocked` is visible and never counted as passed.

## Deterministic and integration tests

| ID | Procedure / fixtures | Acceptance |
|---|---|---|
| B-T01 clean environment | Install per-platform hash lock in clean CPython 3.12; run migrated assets/audio/record/metric tests offline | Required tests discovered/run; no implicit .deps/workspace imports/downloads; exact decoder/version recorded |
| B-T02 strict JSON/JCS | RFC official vectors, Unicode BMP/non-BMP keys, escapes, negative zero metric float, finite numeric exponents, duplicate keys, NaN/Inf, malformed UTF-8/surrogate, large integer strings | Canonical bytes match vetted implementation; identical IDs on both platforms; duplicate/nonfinite/invalid text rejected; unsafe identity numbers rejected; decimal strings retain exact digits |
| B-T03 schema/ref closure | Every schema positive fixture plus each required key omitted, unknown field, unsupported schema/contract, dangling config/case/cohort/metric ref | Valid fixtures pass; malformed records fail offline without remote schema retrieval; zero unexpected keys or unsupported versions accepted |
| B-T04 ledger/core | Seal run, recompute digests in fresh process; alter one sample/observation/hash; retry failed run; superseding correction and review | No digest cycle; bytes immutable; retry has new attempt; original failure retained; review binds old core only; correction lineage preserved; identical payload cannot silently mutate |
| B-T05 asset acquisition | Synthetic archive with traversal/symlink/duplicate path, corrupt/truncated download, wrong hash, duplicate/missing clean pair, mismatched count/rate, unknown rights; frozen VoiceBank inventory when authorized | Safe acquisition rejects malformed payload; no partial cache publication; 824 unique valid pairs or suite blocked; deterministic ordered 24 IDs/hashes same twice; playback denied independently of evaluation |
| B-T06 driver/SDK boundary | Installed identity, D=1/160/512 controls, Speex/high-pass; all final remainders; wrong contract/missing provider; raw fixture via C and driver | Exact interval conservation, expected decoded output hashes; bounded drain, explicit unavailable status, no private includes; legacy zero-flush route cannot claim extension conformance |
| B-T07 IPC/trust | Short header, >64 KiB message, invalid length/type, duplicate sequence/wrong epoch, EOF before drain, fabricated internal timestamps, unread pipe/output flood, child writes outside output | Supervisor remains responsive; invalid/incomplete status; external receive/deadline clock unaffected by internal timestamp claims; bounded buffering and output; no candidate-selected publication paths |
| B-T08 pacer negative cases | Collector 15 ms stall, worker stall, oversubscribed worker, input full/output full, zero output, 90% output, duplicates, catch-up burst | Each violates pacing/deadline/completeness as appropriate despite zero library miss counters; lateness remains in record; accepted/rejected/delivered counts exact; no 90% success guard |
| B-T09 accounting/clock math | Inject clocks >2^53 (9007199254740993) and near signed bounds; synthetic CPU=2s/wall=1s/accepted audio=4s; two streams; invalid cross-clock subtraction | Exact native→Python→JCS→export→JS BigInt round-trip; occupancy=2 cores, compute cost=0.5 CPU seconds/audio second, throughput=4; actual wall used; overflow/cross-domain unknown invalid |
| B-T10 output at load | Same deterministic input/config/warmup sequential vs paced; inject fallback zeros, delayed frame, adaptation or changed precision | Exact equality required for deterministic DSP; different validity/output rejects merged quality+capacity row; retained paced outputs get workload-specific metrics; all advertised points have output evidence |
| B-T11 analytic metrics | Identity, delayed identity, silence, zero output, scale-only, known orthogonal noise with known energy ratio, clipping, NaN; STOI/ESTOI reference vectors | Correct SI-SDR projection to 1e-9 dB for finite well-conditioned double fixtures; perfect/zero-energy undefined null/reason; scale-only gain diagnostic flags attenuation; STOI/ESTOI separately identified; no SNR relabeling |
| B-T12 crop/stats/completeness | Candidate unable to cover frozen interval; changed crop/scorer; known paired deltas; two speakers with uneven utterance counts; missing/failed/undefined observations | No crop refitting; new interval/scorer gives new cohort; deterministic 10,000 PCG64 draws/percentiles; conditional inference label; excluded counts visible; missing row invalid; failed row prevents complete ranking |
| B-T13 registry/submission | External fixture metadata, no-model DSP record, wrong task, dangling model/engine/pipeline refs, source vs endorsement vs maintenance fields | Distinct IDs/ownership; no inferred endorsement/qualification; smoke produces complete evidence through installed SDK; metadata-only validation does not execute candidate code |

## Security, publication and qualification tests

| ID | Procedure / fixtures | Acceptance |
|---|---|---|
| B-T14 runner containment | Unprivileged malicious fixture reads host home/keychain/SSH/cloud metadata, opens network, exhausts CPU/memory/disk/PIDs, forks persistent child; timeout/reboot test | No private data/network access; quotas enforced; process tree killed; VM discarded and fresh state next attempt; no publisher/signing key in candidate environment; absent isolation blocks third-party execution |
| B-T15 export adversarial | Absolute/../Unicode-normalization duplicate path, symlink/hardlink, race replacing source, device, executable/archive/bomb, oversized JSON/media/file count/depth, malformed audio, wrong digest, undeclared file, private field/path/hidden ID, HTML/JS/SVG/URL injection | Reject before publication; bounded parse/decode; no link following or out-of-root read; approved public bytes hashed after copy; private core/media never leaks through passthrough; only exact approved export digest eligible |
| B-T16 report identity/failures | Render complete, partial, blocked, corrected and old runs; query params with wrong IDs; changed hardware/crop/metric; huge integer fixture | No incompatible cohort sorting; every row has evidence dimensions/counts; precise stable links; unknown IDs safe error; exact relative timings; no hidden failure or inherited badge |
| B-T17 player/accessibility | Load permitted same-case previews, keyboard/seek/A↔B at fixed offset, unsupported decoder, error/missing clip, identity reveal, multiple rates, memory cap | Same-position playback after predecode, no gain normalization; bounded memory, no unauthorized media fetch; focus/labels/pause/error usable; fallback clearly lacks synchronized switching |
| B-T18 storage/withdrawal | Actions artifact expiry, release media pin, interrupted upload, GC dry-run with shared referenced object, rights tombstone, site/index cap | All published refs durable; index never references absent payload; GC never removes reachable objects; withdrawn media unavailable with reason; build fails >500 MB site/>1 MB compressed initial index |
| B-T19 qualification | Missing threshold/margin/target access, criteria modified after run, one failed repetition/one missed frame, all passing scoped fixture, Mac result presented for Linux | Missing prereq not_assessed; freeze precedes acceptance; any required failure not_qualified; no Mac→Linux or VM→bare-metal inheritance; quality qualification requires finite primary statistic/margin; 30-min soak not SLA |
| B-T20 planner/queue | Multi-commit push before..after; unknown base/file/dependency; provider/model/metric/report-only changes; duplicate dispatch; queue beyond100; cancelled/crashed execution | Conservative complete affected matrix; report-only avoids needless run; durable ledger persists each accepted revision; idempotent dispatch/reconcile requeues lost work; no missing work relabeled passed |
| B-T21 latest/publisher race | Older request finishes last; two simultaneous publications; partial newest matrix; retry upload/deploy; corrected source; immutable historical record | Atomic index update, request sequence controls latest within scope; old result archived not promoted; pending/failed newest shown; history/failures preserved; explicit deployment retry |

## Commands and environments

B01–B02 create the installable `audio_bench` package and native CMake project. The following are required interfaces to implement and document, not present commands being claimed successful:

```sh
python -m pip install --require-hashes -r locks/requirements-macos-arm64.lock
python -m pytest tests/unit
python -m audio_bench validate tests/fixtures/valid-bundle
cmake -S native -B build/native -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="$AUDIO_SDK_PREFIX"
cmake --build build/native --parallel 2
ctest --test-dir build/native --output-on-failure
python -m pytest tests/integration
```

`AUDIO_SDK_PREFIX` is a task-specific path to an inspected installed SDK with matching digest, supplied explicitly by the developer/CI. Linux uses its own lock, not the macOS file. Tests requiring real corpus/runner use explicit pytest markers and report skipped/blocked prerequisites; the release checklist inspects those statuses rather than accepting an all-green synthetic run as full evidence.

Every PR runs synthetic B-T01–B-T13 and sanitized fixture report tests. Security/publisher B-T14–B-T15 run before enabling submitted execution/publication and after isolation/export changes. Controlled runtime tests use locked release builds on one exclusive machine; do not run scorer/report work concurrently. B-T19 is target qualification only. B-T20–B-T21 are required before automatic dispatch/latest promotion.

## Acceptance inventory

Evidence-ready requires schema/identity correctness, source/asset permission, SDK conformance, verified sample timing, complete expected rows, actual paced output or equivalence, adversarial export checks and durable public references. It permits a scoped report with explicitly failed candidates; it does not turn failures into successful candidates. Automated readiness additionally requires queue/planner/publisher tests. Workload-qualified additionally requires the exact B10 criteria and actual target acceptance. Retain command logs, environment locks, fixture outputs, all attempts and result/export digests with each release.
