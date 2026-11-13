# audio-bench implementation handoff

**Status:** local implementation and synthetic functional path are available. Nothing is published,
deployed, or qualified. All work remains uncommitted. Named maintainer: **unassigned**.

Normative inputs: [EVIDENCE_SPEC.md](EVIDENCE_SPEC.md),
[audio-sdk CONTRACTS.md](../audio-sdk/CONTRACTS.md), [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md),
and [TEST_PLAN.md](TEST_PLAN.md). Only `audio-bench` was modified; sibling repositories were
read-only inputs.

## 1. Task status

| Task | Status | Evidence | Remaining gate |
|---|---|---|---|
| B01 provenance/environment | partial | [B01](docs/task-evidence/B01.md) | named owner, rights inventory, independent Linux lock/environment |
| B02 schemas/canonicalization/ledger | implemented locally | [B02](docs/task-evidence/B02.md) | independent review/signing |
| B03 assets/cases/intervals | partial | [B03](docs/task-evidence/B03.md) | VoiceBank archive bytes and scope-specific rights decision |
| B04 native driver/collector | local SDK integration passes | [B04](docs/task-evidence/B04.md) | disposable hostile-child tests and independent security review |
| B05 paced runtime | incomplete | [B05](docs/task-evidence/B05.md) | pacing, queue/backpressure, stall/coverage/catch-up/equivalence tests |
| B06 metrics/analysis | implemented for synthetic suite | [B06](docs/task-evidence/B06.md) | corpus evaluation and qualification are not assessed |
| B07 registry/submission | partial | [B07](docs/task-evidence/B07.md) | arbitrary/untrusted candidate execution remains disabled |
| B08 isolation/export | offline sanitizer implemented; gates closed | [B08](docs/task-evidence/B08.md) | disposable isolation, reviewer/security approval, public descriptor/config binding |
| B09 report/package | wheel/report path passes; browser acceptance partial | [B09](docs/task-evidence/B09.md) | browser/accessibility/player acceptance |
| B10 frozen qualification | blocked / not assessed | [B10](docs/task-evidence/B10.md) | target access and signed frozen criteria/quality margin |
| B11 durable automation | local groundwork only | [B11](docs/task-evidence/B11.md) | manual gates, external durable ledger/runner/reviewer/publisher remain absent |
| B12 expansion | out of scope | — | separate budget/release |

“Blocked” is not a pass and is not counted as one.

## 2. Pinned SDK and local native path

The installed macOS arm64 SDK package is verified against its archive and 37-file manifest:

- Archive SHA-256: `82bb8f64c882b77a51e708bac0c79eae586c07cb0e96c84c8a9388d2100a387e`
- Build ID: `audio-sdk/0.1.0+sha256:fe66742bc610c4a1d27439c127908d803bc14555c6009a98d3339d594dc8d800`
- Public installed schemas, headers, libraries and provider descriptors are pinned in `deps/`.
- Standalone conformance: Speex 37/37; high-pass 37/37. D=256 startup-validity regression passes;
  this snapshot does **not** demonstrate the suspected defect.

`audio_bench smoke` runs only the two named installed built-in providers on 24 frozen synthetic
cases. It records 7 metrics per case, seals and validates local evidence, and labels it
“synthetic local functional evidence; not qualification.” Arbitrary candidate code is not run.

## 3. Final verification

On CPython 3.12/macOS arm64:

```text
.venv/bin/python -m pytest -q
  72 passed
cmake --build build/native --parallel 2
ctest --test-dir build/native --output-on-failure
  2/2 passed
```

The final wheel was installed in a fresh hash-locked CPython 3.12 environment outside the checkout.
From a separate CWD it successfully ran catalog validation, SDK smoke (Speex, 24×7), bundle
validation and report generation. Report: 1 row, 0 media bytes. Final wheel SHA-256:
`6561e2f7b5fb911aee5e5395f23706322fe08b387944ab326efd956cab33d384`.

See `docs/task-evidence/` for task-specific evidence and boundaries. Local SDK smoke bundles are
ignored under `.runs-local/`; report outputs were written under the approved temporary directory.

## 4. Reproduction

```sh
.venv/bin/python -m pytest -q
cmake --build build/native --parallel 2
ctest --test-dir build/native --output-on-failure
.venv/bin/python -m audio_bench catalog registry/catalog.json
.venv/bin/python -m audio_bench smoke --output .runs-local/my-new-smoke \
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
- B05 paced scheduling and its stall/backpressure/catch-up/coverage/equivalence matrix are not
  implemented.
- B08 third-party execution, export approval and publication remain gated. Offline sanitization is
  not containment evidence.
- B09 browser, accessibility, seeking and synchronized playback checks remain unverified.
- B10 has no target evidence or approved frozen criteria; qualification stays `not_assessed`.
- B11 implements only conservative local impact planning and serialized latest-snapshot
  reconciliation. No workflow, external request service, remote append-only store, dedicated
  runner/lock, publisher credentials, remote, deployment or publication was created.

Do not infer official performance, candidate ranking, rights clearance, qualification or production
readiness from these synthetic/local checks.
