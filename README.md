# audio-bench

Reproducible evaluation, explicit asset/case manifests, canonical immutable evidence, honest native
runtime measurement, safe export and an offline static report for the audio SDK. This directory
now contains the independent Python evidence core and synthetic tests; it does **not** yet contain
a working native driver or real SDK integration.

## Status

- **Implemented locally:** strict duplicate-free JSON and RFC 8785 identities; closed evidence
  schemas; immutable ledger primitives; deterministic synthetic assets/manifests; metric/statistics
  groundwork; fixed-rate schedule and IPC reference codec; adversarial export checks; offline
  report shell.
- **Blocked:** native driver/collector and SDK-backed execution (no installed SDK package,
  conformance artifacts or public schema files); VoiceBank evaluation (rights and bytes not
  verified); submitted execution/public export (no disposable isolation infrastructure); workload
  qualification (no approved target/criteria).
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
public export are disabled until isolation and independent adversarial checks pass.
