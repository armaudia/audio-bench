# Provider and composed-chain evidence template

Use this checklist with the [evidence specification](../EVIDENCE_SPEC.md) and
[corpus policy](CORPUS.md). The worked example uses only the two built-in
providers and existing generated fixtures. It does not authorize new data,
models, runners, redistribution, playback, or qualification claims.

## Fill in before running

- **Provenance and rights:** Pin Bench and SDK revisions, package/build and
  scorer digests, provider descriptors, effective configs, and any asset IDs.
  For a chain, pin stage order and each stage's descriptor, config, and build.
  Record acquisition, evaluation, redistribution, and playback decisions and
  evidence separately. Unknown scope does not permit the action. Derived
  artifacts inherit their inputs' restrictions.
- **Matched cohort and controls:** Pin dataset, case set, cohort, preprocessing,
  alignment, scored intervals, metric versions/settings, and expected case ×
  metric matrix. Use identical clean references, noisy inputs, and source
  intervals for the noisy-input identity control, task-matched reference, and
  candidate. For an approved chain evaluation, include the full chain and each
  prespecified stage-removal ablation on the same cases. Never change the crop
  after seeing results.
- **Raw validity and timing:** Retain raw float output, source maps, and their
  hashes, exact half-open valid intervals, coverage counts, and failure reasons.
  Check valid-source coverage except for frozen edge exclusions: no gaps,
  duplicate/overlapping spans, out-of-bounds intervals, or nonfinite samples.
  Startup/final padding and concealment are not valid content. For chains,
  check stage offsets, validity through all stages, reset, and final partial
  frame/tail handling. For paced evidence, pin the runner and workload
  separately and distinguish content delay from observed availability.
- **Paired aggregation:** Freeze estimand, grouping, seed, draws, and interval
  rule. Compute deltas on the displayed intersection of finite matched
  observations. Retain expected/delivered counts and missing, failed, blocked,
  and undefined reasons. A missing row is invalid, not `not_applicable`; a
  mathematically undefined result stays null with its reason. If the expected
  cohort is not fully represented, label the result **partial diagnostic
  comparison** and do not rank it as complete.
- **Report labels:** Separate synthetic functional, paired quality,
  unpaired/no-reference, and paced runtime evidence. Record execution, review,
  reproduction, and qualification independently. A no-reference prediction is
  exploratory, not a paired score, human MOS, or qualification. Limit claims to
  the tested host and workload.

## Worked example: extracted package, synthetic only

Bench revision `e623e14a4e85a6be7f6061aa50a30bb8824af132`; SDK source
`84a102112ce83fb519303a832be15ad88e452d74` from
[`deps/sdk-source.json`](../deps/sdk-source.json). Local Darwin arm64,
CPython 3.12.16, sequential (no workload condition). The
[synthetic fixture grants](../LICENSES/LicenseRef-Synthetic-Fixtures.txt) cover
these generated harmonics and noise, not human recordings or third-party model
weights.

Frozen fixtures: [`synthetic-16k-v1`](../manifests/synthetic/synthetic-16k-v1/dataset.json)
and [`synthetic-smoke-v1`](../suites/synthetic-smoke-v1/cohort.json). All 24
pairs (six synthetic speakers, four pairs each) use mono 16 kHz and the same
`[0, 16000)` interval, with zero edge exclusions.

| Frozen record | Content ID |
| --- | --- |
| Dataset | `sha256:b5ff8fc7185216331ed004005189319cd0bc4e2ad538c87176ba6bac91504ce8` |
| Case set | `sha256:be276c862fe8dd9f8482eee8b6ad55a03d1b65ee96f47c0fbf004d40761bf740` |
| Cohort | `sha256:b06e5ea5594527825a3ff28f32d32e1a83c6274c51550081382cc596e3e3e823` |
| Preprocessing | `sha256:b8cef975ed46d3dea869a1e8e5bd16f60cbd13eb31ffa324a3e6cc3a2f958d4d` |
| Alignment | `sha256:22fa37573d1a33b92c55a5b934f3de460eb89a933c098533005b35940735c6d0` |
| Scored intervals | `sha256:7335964c3209495a6fda2697b9ae1654c87ce5669a980c1966a1a60f2050914a` |

Both providers produced valid sealed bundles: 168/168 finite observations per
provider (24 cases × seven metrics), one row per offline report and zero media
bytes. Label: **synthetic local functional evidence; not qualification**.
Execution `passed`, review `pending`, reproduction `not_reproduced`, qualification
`not_assessed`. The digests identify the recorded local artifacts, not
byte-for-byte promises about reruns:

| Local artifact | Digest |
| --- | --- |
| `audio-bench-0.1.0-darwin-arm64.zip` | `sha256:51f5462af5ff69bf252455965b61f679e54af1110fd1cd400720de0de3509f0b` |
| `audio_bench-0.1.0-py3-none-any.whl` | `sha256:5eae44fbe5da1f8f26543f144c45b43305dd27330708684646f004c3bd4716b0` |
| `sdk/audio-sdk-0.1.0.tar.gz` | `sha256:9265196547dba1d74f6c05d00d87d23d36b0a86b38f1ad9feabc4945fe0ff372` |
| `dsp.highpass80.v0` sealed core | `sha256:37b50f3fbe0e20470a35466815f48d610b2841870abf1a4db1d3e3b3f1a79f80` |
| `speex.ns.v0` sealed core | `sha256:1d1c19186cf1828eee48d02ba30985eb6f15c38079b59deb7c18ee35e80bbda7` |

A separate local diagnostic used the same scorer and intervals for the
noisy-input identity control (not a sealed attempt); high-pass was a second
integration comparator. Both Speex comparisons had 24 finite pairs for SI-SDR,
STOI, and ESTOI. Aggregation was paired mean delta, a 10,000-draw within-speaker
bootstrap, seed `20261111`, with linear 2.5/97.5 percentiles, conditional on
these synthetic speakers. Simulating an omitted Speex case yielded 23 pairs and
`missing_candidate: 1` per metric, labeled **partial diagnostic comparison**.
No real corpus, no-reference score, or composed chain was evaluated.

## Reproduce and check completeness

Follow the [development setup](../README.md#development) in a disposable
checkout at the pinned revision. Running
`python scripts/prepare_sdk.py --sdk-source <pinned-sdk-checkout>` and then
`python scripts/ci.py` passed 146 Python tests and two native tests locally.
The CI script writes `build/ci/dist/`, then verifies an extracted wheel.
The packaged `smoke` command selects only built-ins; the existing
[driver/collector protocol](protocol/native-ipc-v1.md) is separate from it.
To repeat both built-in checks, set `ARCHIVE` to the absolute path of the
Darwin ZIP and `OUT` to an empty scratch directory outside the checkout
(also an absolute path). With Python 3.12:

```sh
(cd "$(dirname "$ARCHIVE")" && shasum -a 256 -c "$(basename "$ARCHIVE").sha256")
unzip -q "$ARCHIVE" -d "$OUT/extracted"
cd "$OUT"
unset PYTHONPATH
python3.12 -m venv venv
venv/bin/python -m pip install --constraint extracted/requirements-ci.txt \
  extracted/audio_bench-*.whl
for provider in dsp.highpass80.v0 speex.ns.v0; do
  venv/bin/python -m audio_bench smoke --output "${provider}-bundle" \
    --native-build extracted/bin --sdk-prefix extracted/sdk/audio-sdk-0.1.0 \
    --provider "$provider"
  venv/bin/python -m audio_bench validate "${provider}-bundle"
  venv/bin/python -m audio_bench report build --bundle "${provider}-bundle" \
    --output "${provider}-report"
done
```

On separate copies of the high-pass bundle, the installed validator exited 1
for a modified `summary.json`, missing `scored-intervals.json`, and a missing
source-map file. A copy resealed without the `synthspk00-p00/clipping_count`
observation also exited 1; report generation refused it. Resealing a passed
attempt without a frozen source map was rejected during sealing. The installed
CLI exited 1 without `--sdk-prefix` and 2 for an unknown `--provider`.

**Request-only caveat:** Removing `runs/<run_id>/<attempt_id>/run.json` left one
request and zero discovered attempts. `validate` returned exit 0 (`valid: true`);
`report build` returned exit 1 (`bundle contains no sealed attempts to report`).
Check that the intended request/config/cohort has its sealed attempt and
expected matrix; do not use successful validation alone as proof of execution.
This is an operator check, not a change to the validator.
