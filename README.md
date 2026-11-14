# audio-bench

Local reproducible evaluation and offline evidence reports for audio-sdk contract
0.1. Implemented scope: two built-in DSP providers, 24 deterministic synthetic
cases, seven quality/diagnostic metrics, immutable evidence, validation, and a
static browser report with filters and CSV/JSON downloads.

## Setup

Use Python 3.12 and a C/C++ compiler. Clone the public SDK repository at the exact
revision recorded in `deps/sdk-source.json`; the preparation command rejects a
mismatched or modified SDK checkout.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r locks/requirements-ci.txt
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python scripts/prepare_sdk.py --sdk-source /path/to/audio-sdk
.venv/bin/python scripts/ci.py
```

The preparation command builds/tests/installs the source-pinned SDK and refreshes
the local artifact lock and packaged resources for this host. It is an explicit
dependency update, not a bypass of hash checking. Both commands require new build
output directories. The complete check tests the native collector, requires all
unit/integration tests to run without skips, exercises both providers, and tests
a fresh dependency and wheel installation outside the checkout. CI records pip
installation reports; the original macOS wheel hash locks remain historical.

## Run an evaluation

After the complete check, use its verified native binaries and SDK:

```sh
.venv/bin/python -m audio_bench smoke --output /path/to/new-bundle \
  --native-build build/ci/native --sdk-prefix build/sdk/candidate/audio-sdk-0.1.0 \
  --provider speex.ns.v0
.venv/bin/python -m audio_bench validate /path/to/new-bundle
.venv/bin/python -m audio_bench report build --bundle /path/to/new-bundle --output /path/to/new-report
.venv/bin/python -m http.server 8000 --bind 127.0.0.1 --directory /path/to/new-report
```

Open `http://127.0.0.1:8000` for interactive filtering and downloads. A local file
URL does not support the report's JSON fetches reliably. Reports show execution,
review, reproduction and qualification separately. They contain no preview media;
listening controls are disabled when media is unavailable.

Other commands: `synthetic build --output NEW`, `catalog registry/catalog.json`,
and `schemas --index`. Run `python -m audio_bench --help` for details. Synthetic
generation supports speaker count, pairs and duration; smoke uses the frozen suite.

## Distributed package

`build/ci/dist/` contains a platform ZIP with the wheel, native binaries and the
exact SDK archive/install tree. Extract it, install its wheel with Python 3.12,
then pass `--native-build bin --sdk-prefix sdk/audio-sdk-0.1.0` to smoke from that
directory. The wheel does not silently download or execute candidate code.

## Limits and status

This is synthetic functional evidence, not representative speech evaluation,
performance ranking or workload qualification. Real corpus acquisition, hostile
submissions, public export/publication, a listening gallery and production timing
qualification remain gated. The collector is not an isolation boundary for hostile
native code. Tiny16 and other neural processors are not included.

[RELEASING.md](RELEASING.md) describes CI and intended GitHub controls.
[Release-hardening evidence](docs/task-evidence/release-readiness-20261114.md)
records current local checks; [HANDOFF.md](HANDOFF.md) retains the earlier task
history. Hosted runs and GitHub settings readback are required before claiming
that the new controls are enforced. First-party software is Apache-2.0; synthetic asset terms are separate in DATA_LICENSE.md. The maintainer is Tsakanyan Hovhannes, acting individually.
