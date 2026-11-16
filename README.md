# audio-bench

Local reproducible evaluation and evidence reports for audio-sdk contract 0.1.
Implemented benchmark scope: two built-in DSP providers, 24 deterministic
synthetic cases, seven quality/diagnostic metrics, immutable evidence, validation,
and an interactive static report. Synthetic cases are functional fixtures, not a
speech-quality benchmark.

## Submit a pipeline

See [the submission protocol](docs/SUBMISSIONS.md). A submission PR contains only
metadata and is validated without checking out or executing the referenced code.
The merged `main` CI runs the built-in synthetic smoke suite. An enabled public
candidate registration is built and benchmarked by a separate post-merge workflow.
Successful records are validated and added to the cumulative Pages results at
<https://armaudia.github.io/audio-bench/>. These are synthetic functional checks,
not third-party speech-quality rankings. Submitter-owned runs can be performed
locally and submitted as JSON without exposing private source; they are clearly
marked unverified.

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

The current score suite uses synthetic fixtures only. VOiCES, VoiceBank+DEMAND,
and DNS5 have external-cache preparation paths; their selection, cache, and
rights decisions are documented in [docs/CORPUS.md](docs/CORPUS.md). The
repository maintainer has enabled acquisition and evaluation for all three
corpora, with attribution and aggregate-score publication. Public Actions cache
use is enabled by default in manual preparation for the selected VoiceBank and
VOiCES cohorts; DNS5 public caching is disabled pending component mapping. Cached
audio stays outside Git, Pages, and result artifacts. Corpus preparation
does not yet mean real-corpus scores are produced: the benchmark runner remains
synthetic-only. Native candidate code is
arbitrary code and runs only on an ephemeral benchmark job with read-only GitHub
permissions and no publishing credential; this is not an OS security boundary.
See [the submission protocol](docs/SUBMISSIONS.md) for supported runner flows.
Neural models remain gated on their pinned weights and scope-specific rights.
audio-pro's Tiny16 weights are now recorded by hash, but model evaluation rights
remain unresolved, so that candidate stays disabled.

[RELEASING.md](RELEASING.md) describes CI and intended GitHub controls.
GitHub settings readback is retained by the administration script under build/. First-party software is Apache-2.0; synthetic asset terms are separate in DATA_LICENSE.md. The maintainer is Tsakanyan Hovhannes, acting individually.
