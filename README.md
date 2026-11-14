# audio-bench

Reproducible evaluation, explicit asset/case manifests, canonical immutable evidence, honest native
runtime measurement, safe export and an offline static report for the audio SDK. This directory
contains the independent Python evidence core, a native driver/collector integrated with pinned SDK
Candidate 09, and synthetic functional tests.

## Status

- **Implemented locally:** strict duplicate-free JSON and RFC 8785 identities; closed evidence
  schemas; immutable ledger primitives; deterministic synthetic assets/manifests; metric/statistics
  pipeline; native SDK driver/collector; frame-completion-aligned local 10 ms paced fixture path; checked offline
  projection, exact approval, and public static report generation.
- **Still gated/incomplete:** the full paced workload/fault matrix, hostile-child isolation and
  independent security review; VoiceBank evaluation (rights and bytes unverified); public
  publication/browser gallery acceptance; workload qualification (no approved target/criteria).
- Synthetic data is correctness/scenario evidence only. No performance, corpus, SDK conformance or
  qualification claim is made.

See [HANDOFF.md](HANDOFF.md) for task states, dependency digests, artifacts, test results and exact
reproduction commands. Normative contracts are [EVIDENCE_SPEC.md](EVIDENCE_SPEC.md) and the pinned
SDK contract described in [deps/lock.json](deps/lock.json).

## Local setup and checks

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r locks/requirements-dev-macos-arm64.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m pytest tests/unit -q
.venv/bin/python -m audio_bench validate <bundle>
.venv/bin/python -m audio_bench catalog registry/catalog.json
```

Validation never executes candidate code or downloads schemas. `validate` returns 0 for a valid
bundle, 1 for invalid/coverage errors and 2 for a bad invocation. Third-party native execution and
the public `export` command remain disabled until isolation and independent adversarial checks pass.
Local offline projection/report helpers do not authorize publication.
