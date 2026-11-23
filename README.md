# audio-bench

Audio-bench provides reproducible benchmarks for C audio pipelines. It currently
supports two result categories:

- **Speech enhancement:** paired quality and runtime measurements on the frozen
  824-pair VoiceBank+DEMAND test cohort, plus synthetic integration checks.
- **Real-time processing:** paced synthetic-load measurements of stream capacity,
  CPU use, memory, throughput, and frame-completion lateness.

The public report is [armaudia.github.io/audio-bench](https://armaudia.github.io/audio-bench/).
This repository is being released with a clean report: there are no active
submission manifests, submitter result records, removal requests, or published
result rows. The blank report is intentional; the first accepted benchmark will
populate it.

## Submit a pipeline

Start with [`submissions/_template.json`](submissions/_template.json) and follow
the [submission guide](docs/SUBMISSIONS.md). A submission PR contains metadata
and immutable source/model identities only. PR checks validate metadata and do
not download corpora or execute candidate code. For a public source repository,
the benchmark runs only after the registration is merged to `main`. Private
source stays on a submitter-owned runner; only a reviewed JSON result can be
submitted to this public repository.

Results appear in one sortable, filterable table. Public-run and submitter-owned
measurements have distinct provenance labels. Submitter-owned measurements are
marked as not independently verified. Removal requests and cumulative publication
are documented in the [submission guide](docs/SUBMISSIONS.md).

## Development

Use Python 3.12 and a C/C++ compiler. Clone the public SDK at the immutable
revision in `deps/sdk-source.json`, then prepare the pinned SDK and run CI:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r locks/requirements-ci.txt
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python scripts/prepare_sdk.py --sdk-source /path/to/audio-sdk
.venv/bin/python scripts/ci.py
```

The full check builds the native collector, runs unit and integration checks,
executes the 24-case synthetic smoke suite, and tests a fresh wheel install. CI
uses Linux (`ubuntu-24.04`). Main-branch CI runs are quality checks; they do not
publish their built-in smoke measurements. Candidate results are published by
the separate post-merge workflow.

To run one local smoke evaluation and build an interactive report:

```sh
.venv/bin/python -m audio_bench smoke --output /path/to/new-bundle \
  --native-build build/ci/native --sdk-prefix build/sdk/candidate/audio-sdk-0.1.0 \
  --provider speex.ns.v0
.venv/bin/python -m audio_bench validate /path/to/new-bundle
.venv/bin/python -m audio_bench report build --bundle /path/to/new-bundle --output /path/to/new-report
.venv/bin/python -m http.server 8000 --bind 127.0.0.1 --directory /path/to/new-report
```

Open `http://127.0.0.1:8000`. See the
[corpus policy](docs/CORPUS.md) for pinned sources, acquisition, caching, rights,
and scoring scope. Audio files are not included in Actions artifacts or Git,
except the attributed five-clip VOiCES smoke fixture; selected real cohorts are
downloaded to verified local or eligible GitHub Actions caches.

Use the [provider and composed-chain evidence template](docs/PROVIDER_EVIDENCE_TEMPLATE.md)
to record matched controls, raw validity, and the scope of benchmark claims.

## Release status

The code supports VoiceBank+DEMAND scoring and real-time throughput profiles,
but target-specific qualification criteria have not been approved. DNS5 is
acquisition-only until its source-component mapping and scoring protocol are
complete. See [release preparation](RELEASING.md) and
[archived implementation evidence](docs/task-evidence/README.md). The Apache-2.0
software license does not replace any dataset or model license; see
[`DATA_LICENSE.md`](DATA_LICENSE.md).
