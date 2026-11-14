> Release-hardening update, 2026-11-14: see
> [current evidence](docs/task-evidence/release-readiness-20261114.md) and
> [release policy](RELEASING.md). The Candidate 09/task snapshot below is
> historical; current consumer builds use the exact source pin and host-specific
> artifact lock. Public source is now at armaudia/audio-bench. Hosted Linux
> and macOS CI passed, including clean-wheel execution and Chromium acceptance.
> Read current evidence for release scope; the task snapshot below is historical.

# audio-bench implementation handoff

**Status:** local implementation and synthetic functional path are available. Nothing is published,
deployed, or qualified. All work remains uncommitted. Named maintainer: **unassigned**.

Normative inputs: [EVIDENCE_SPEC.md](EVIDENCE_SPEC.md),
[audio-sdk CONTRACTS.md](../audio-sdk/CONTRACTS.md), [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md),
and [TEST_PLAN.md](TEST_PLAN.md). The latest cross-repository update also refreshed the SDK
Candidate 09 snapshot and Pro lock. Changes remain local and uncommitted.

## 1. Task status

| Task | Status | Evidence | Remaining gate |
|---|---|---|---|
| B01 provenance/environment | partial | [B01](docs/task-evidence/B01.md) | named owner, rights inventory, independent Linux lock/environment |
| B02 schemas/canonicalization/ledger | implemented locally | [B02](docs/task-evidence/B02.md) | independent review/signing |
| B03 assets/cases/intervals | partial | [B03](docs/task-evidence/B03.md) | VoiceBank archive bytes and scope-specific rights decision |
| B04 native driver/collector | Candidate 09 regression and local integration pass | [B04](docs/task-evidence/B04.md) | disposable hostile-child tests, descendant cleanup verification, independent security review |
| B05 paced runtime | partial: 10-second continuous warmup, frame-completion schedule, separate sender/receiver and bounded three-frame window | [B05](docs/task-evidence/B05.md) | separately configurable queues, injected backpressure/stall/coverage/catch-up/workload matrix, measured-only denominators |
| B06 metrics/analysis | implemented for synthetic suite | [B06](docs/task-evidence/B06.md) | corpus evaluation and qualification are not assessed |
| B07 registry/submission | partial | [B07](docs/task-evidence/B07.md) | arbitrary/untrusted candidate execution remains disabled |
| B08 isolation/export | typed offline projection, exact approval and public report path tested; execution/publication gates closed | [B08](docs/task-evidence/B08.md) | disposable isolation, reviewer/security approval, authorized public media |
| B09 report/package | installed-wheel smoke/validate/report pass; browser acceptance unverified | [B09](docs/task-evidence/B09.md) | clean hash-locked dependency install and browser/accessibility/player acceptance |
| B10 frozen qualification | blocked / not assessed | [B10](docs/task-evidence/B10.md) | target access and signed frozen criteria/quality margin |
| B11 durable automation | local groundwork only | [B11](docs/task-evidence/B11.md) | manual gates, external durable ledger/runner/reviewer/publisher remain absent |
| B12 expansion | out of scope | — | separate budget/release |

“Blocked” is not a pass and is not counted as one.

## 2. Pinned SDK and local native path

The installed macOS arm64 SDK Candidate 09 package is verified against its archive and 38-file
manifest:

- Archive SHA-256: `5707c4ff688d12876c3ff3e290db7c5eda76f8bdd2fa28e6fe197abd1353a464`
- Build ID: `audio-sdk/0.1.0+sha256:15959d8f04e8080c5804b3019decea7c720b27e1593a43352cf9ba97d5a6cb1c`
- Public installed schemas, headers, libraries, provider descriptors, conformance reports, and file
  manifest are pinned in `deps/`. The historical `82bb8f64…` artifact remains the defective prior
  pin; its first-frame failure is demonstrated by the corrected regression.
- Standalone conformance: Speex 37/37; high-pass 37/37. D=256 startup-validity regression passes;
  the old archive fails `(valid_offset,valid_count)=(160,96)` on the first frame; Candidate 09
  reports the expected `(160,0)`.

`audio_bench smoke` runs only the two named installed built-in providers on 24 frozen synthetic
cases. It records 7 metrics per case, seals and validates local evidence, and labels it
“synthetic local functional evidence; not qualification.” Arbitrary candidate code is not run.

## 3. Final verification

On CPython 3.12/macOS arm64:

```text
cmake -S native -B native/build-foundation09 -DPython3_EXECUTABLE="$PWD/.venv/bin/python" \
  -DAUDIO_SDK_PREFIX="$PWD/../audio-sdk/build/candidates/macos-arm64-20261114-foundation-09/audio-sdk-0.1.0"
cmake --build native/build-foundation09 --parallel 2
ctest --test-dir native/build-foundation09 --output-on-failure
  2/2 passed
AUDIO_BENCH_NATIVE_BUILD=native/build-foundation09 .venv/bin/python -m pytest -q
  78 passed
```

The 78-test run used Candidate 09 and included installed-SDK synthetic smoke, bundle validation,
report generation, paced/sequential output comparison and early-child-exit handling. It ran with the project `.venv`; a fresh
locked dependency installation is still unverified. Synthetic smoke report: 1 row, 0 media bytes.

Current source/package lock identities are recorded in `deps/lock.json`; older local attempt identities are historical and should not be used as current release evidence.

See `docs/task-evidence/` for task-specific evidence and boundaries. Local SDK smoke bundles are
ignored under `.runs-local/`; report outputs were written under the approved temporary directory.

## 4. Reproduction

```sh
cmake -S native -B native/build-foundation09 \
  -DPython3_EXECUTABLE="$PWD/.venv/bin/python" \
  -DAUDIO_SDK_PREFIX="$PWD/../audio-sdk/build/candidates/macos-arm64-20261114-foundation-09/audio-sdk-0.1.0"
cmake --build native/build-foundation09 --parallel 2
ctest --test-dir native/build-foundation09 --output-on-failure
AUDIO_BENCH_NATIVE_BUILD=native/build-foundation09 .venv/bin/python -m pytest -q
.venv/bin/python -m audio_bench catalog registry/catalog.json
.venv/bin/python -m audio_bench smoke --output .runs-local/my-new-smoke \
  --native-build native/build-foundation09 \
  --sdk-prefix ../audio-sdk/build/candidates/macos-arm64-20261114-foundation-09/audio-sdk-0.1.0 \
  --provider dsp.highpass80.v0
.venv/bin/python -m audio_bench validate .runs-local/my-new-smoke
.venv/bin/python -m audio_bench report build \
  --bundle .runs-local/my-new-smoke --output /path/to/new-report
```

Smoke requires the verified installed SDK archive/prefix and native build. It refuses to overwrite
its output directory. Bundle validation does not execute candidate code. The report is a local
static artifact; no browser acceptance or public playback is implied.

## 5. Explicit exclusions and blockers

- VoiceBank+DEMAND has a reviewed primary-source/terms note, but no local archive bytes, verified
  inventory, or scope-specific rights approval. No corpus evaluation or public audio is claimed.
- B05 performs a default 10-second continuous warmup and schedules measured frame k at
  t0+(k+1)*10 ms, matching frame completion. A sender and receiver operate independently with no
  more than three frames in flight; sequential output equivalence and a short stateful warmup test
  pass. Collector wall/CPU totals still include warmup/reset overhead. Separately configurable
  queues, injected backpressure/stall/coverage faults,
  multi-stream load and target workload qualification remain open.
- B08 third-party execution and publication remain gated. Approval/report code is local and is not
  containment evidence or reviewer authority.
- B09 browser, accessibility and real synchronized A/B playback checks remain unverified.
- B10 has no target evidence or approved frozen criteria; qualification stays `not_assessed`.
- B11 implements only conservative local impact planning and serialized latest-snapshot
  reconciliation. No workflow, external request service, remote append-only store, dedicated
  runner/lock, publisher credentials, remote, deployment or publication was created.

Do not infer official performance, candidate ranking, rights clearance, qualification or production
readiness from these synthetic/local checks.
