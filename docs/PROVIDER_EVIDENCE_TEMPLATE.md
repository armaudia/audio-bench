# Provider and composed-chain evidence template

Use this checklist with the [evidence specification](../EVIDENCE_SPEC.md) and
[corpus policy](CORPUS.md). The worked example uses only the two built-in
providers and existing generated fixtures. It does not authorize new data,
models, runners, redistribution, playback, or qualification claims.

## Fill in before running

- **Provenance and rights:** Pin Bench and SDK revisions, package/build and
  scorer digests, provider descriptors, effective configs, and any asset IDs.
  Check that the sealed provider descriptor matches the runtime descriptor and
  the descriptor digest named by the effective config.
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

Both providers completed functional smoke: 168/168 finite observations per
provider (24 cases × seven metrics), one row per offline report and zero media
bytes. The validator accepted both bundles despite the descriptor mismatch
below. Label: **synthetic local functional evidence; not qualification**.
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

### Descriptor provenance discrepancy

For both built-ins, `smoke` seals the wheel's stale
`runtime_data/schemas/sdk/providers/` descriptor as `provider-descriptor.json`
and records its hash as `provider_digest` in the request matrix and `run.json`.
The extracted driver's `--descriptor` instead matches the pinned SDK's
`share/audio-sdk/schemas/providers/` copy and the wheel's `schema_data/sdk/providers/`
copy byte for byte after removing the driver's trailing LF. The SDK
`descriptor_digest` inside `--effective-config` matches the **driver** digest,
not the sealed one. The hash of the entire effective config is a separate
identity (`configuration_id` and collector `sdk_config_digest`).

| Compared value (SHA-256) | `dsp.highpass80.v0` | `speex.ns.v0` |
| --- | --- | --- |
| Wheel runtime descriptor / sealed `provider_digest` | `6fcf3621a8d31ba6fe1eaed191ca4dcf71987718dd135b773925092dbac1219f` | `e8f9fdb91181f5ba68477028ffc55dfb0c5c06d2876bc8668a48c57f62297888` |
| Driver / pinned SDK / wheel schema descriptor / effective-config `descriptor_digest` | `d664ddc7977b5ff193e184b12dca48f3923675e8a7f0d4feb79781b0ca7c77e3` | `8dcfbd3ca87ae85f0c1d6390ede34b62b5a44461bef65d52c7bf0cf5c303b733` |
| Entire effective config | `44c6304e693a8b1a46306e730757de7bc509de4fdb03f4e36282de2cf7d3c8d3` | `de37eff9dc87bd971925cc17f7d0c02366c83947859fa048499368e5838bda29` |
| `source_digest` inside the sealed descriptor | `4942fa9083c0d42da76798a177fbaa1cf36d9fda995b7a4906e33b4105a9f337` | `b8e058907560dd08bcabd96a01d7a022869dbfb1093668ca9b487f1a2743277c` |
| `source_digest` inside the SDK descriptor | `9da5ab40e8795dd32b4228674e7d851e054cfbe798034e76944a96e8cbf2538f` | `4f324b89c5dfa81001fe55759e09b939eb964ef3b7dd74f9e89caa4630ae647b` |

High-pass's sealed descriptor says `MIT (existing first-party source; release
license decision pending)` with notice `licenses/first-party-MIT.txt`; the
pinned SDK descriptor says `MPL-2.0` with notice `licenses/MPL-2.0.txt`.
Speex says `BSD-3-Clause` in both. The stale high-pass metadata is not evidence
of the runtime's license. `validate` checks the bundle's internal records and
hashes, but does not reconcile the sealed `provider_digest` with the SDK
descriptor or the effective config's `descriptor_digest`. These runs establish
functional smoke only, not provider provenance or qualification. Any packaging
or validation fix requires a separate maintainer-approved task.

### Paired diagnostic

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

To compare the descriptor provenance in those runs, from `OUT`:

```sh
venv/bin/python - <<'PY'
import hashlib
import json
import subprocess
from pathlib import Path
import audio_bench

def sha(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()

for provider in ("dsp.highpass80.v0", "speex.ns.v0"):
    args = ["extracted/bin/audio_bench_driver", "--provider", provider]
    driver = subprocess.check_output([*args, "--descriptor"]).removesuffix(b"\n")
    config = subprocess.check_output([*args, "--effective-config"]).removesuffix(b"\n")
    bundle = Path(f"{provider}-bundle")
    attempt, = (bundle / "runs").glob("*/*")
    request_path, = (bundle / "requests").glob("*.json")
    request = json.loads(request_path.read_bytes())
    run = json.loads((attempt / "run.json").read_bytes())
    sealed = (attempt / "provider-descriptor.json").read_bytes()
    name = f"providers/{provider}.descriptor.json"
    wheel = Path(audio_bench.__file__).parent
    sdk = Path("extracted/sdk/audio-sdk-0.1.0/share/audio-sdk/schemas")
    assert sealed == (wheel / "runtime_data/schemas/sdk" / name).read_bytes()
    assert driver == (sdk / name).read_bytes() == (wheel / "schema_data/sdk" / name).read_bytes()
    assert sha(sealed) == run["provider_digest"] == request["matrix"][0]["provider_digest"]
    assert sha(driver) == json.loads(config)["descriptor_digest"] != sha(sealed)
    assert config == (attempt / "effective-config.json").read_bytes()
    assert sha(config) == run["configuration_id"]
    print(provider, "sealed/driver/config:", sha(sealed), sha(driver), sha(config))
    for label, data in (("sealed", sealed), ("driver", driver)):
        descriptor = json.loads(data)
        print(label, descriptor["source_digest"], descriptor["upstream"])
PY
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
