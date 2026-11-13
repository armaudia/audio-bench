# Contributing evaluation metadata and evidence

## Before adding an entry

1. Use `registry/catalog.json` as a template and keep provider, model, implementation, engine,
   pipeline and host IDs distinct. A DSP/filtering implementation does not get a model ID.
2. Record upstream source/revision, attribution, license, rights evidence, source availability,
   maintenance owner and vendor endorsement independently. Unknown stays unknown; do not infer
   endorsement from a public adapter.
3. Do not add model/data bytes or private local paths. Acquisition uses immutable revisions and
   inspected SHA-256/size values; rights must explicitly allow the requested scope.
4. A catalog record is metadata, not execution, review, reproduction or qualification evidence.
   `blocked` is a valid outcome. Qualification requires actual target access and frozen criteria.

## Local synthetic checks

```sh
python -m pip install --require-hashes -r locks/requirements-dev-macos-arm64.lock
python -m pip install --no-deps -e .
python -m pytest tests/unit -q
python -m audio_bench catalog registry/catalog.json
python -m audio_bench synthetic build --output /path/to/new-fixture-dir
```

Synthetic inputs are deterministic correctness/scenario fixtures, not speech, corpus, quality or
capacity evidence. Do not execute third-party native code on a personal workstation. SDK-backed
smoke execution remains blocked until the installed SDK package and standalone conformance are
available and the execution environment is approved.

## Corrections and evidence labels

Attempt records and sealed cores are immutable. A correction creates a new attempt/core with
`predecessor_core_digest` and a reason. Never edit or delete old failures. Review and independent
reproduction are separate records; a same-organization rerun is not independent reproduction.
Execution, source availability, maintenance, vendor endorsement, review and qualification are
separate report dimensions.

## Maintenance boundary

The public catalog is community metadata, not a promise of ongoing support. Planned maintenance is
capped at three hours per week; broad provider/model expansion is outside the initial v0.1 scope.
