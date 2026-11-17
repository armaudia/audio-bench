# Submit a pipeline

Audio-bench accepts a small JSON registration in `submissions/<submission-id>.json`.
The manifest records public metadata and immutable identities; it must not contain
source code, weights, audio, credentials, or private data. Start from
[`submissions/_template.json`](../submissions/_template.json). Pull request CI
validates only metadata. It does not fetch or execute the referenced repository,
and benchmark execution starts only after an enabled registration is merged to
`main`.

## Runner choices

`runner_mode: "audio-bench"` is for public repositories. Pin the exact
40-character source commit and export a provider using the C plugin contract below.
When the registration is merged to `main`, a separate workflow fetches and builds
the pinned source, then runs the dataset and suite pinned in the manifest. The first scored real cohort is the full VoiceBank+DEMAND paired test split. Candidate checkout/build and
execution have no publishing token; Pages publishes the result artifact only after
the benchmark workflow succeeds.

`runner_mode: "submitter-owned"` runs in the submitter's own CI or infrastructure.
Audio-bench never receives a checkout credential. Use
`scripts/run_submitter_owned.py` to run the pinned built-in reference first and
then the candidate on the same machine and selected suite. It requires a
published central reference result for normalization and emits a JSON record only;
it does not upload anything. Review the record, then submit it under
`submissions/results/` in a PR. The published result is labeled as submitter-run
and not independently verified.

Latency can be reported both raw and as an estimated reference-runner value:

```text
estimated candidate latency = candidate latency on submitter runner
                             × reference latency on audio-bench runner
                             ÷ reference latency on submitter runner
```

This hardware ratio is an estimate and assumes the candidate scales like the
reference provider. Never normalize quality metrics with it. Publish raw quality
scores and, optionally, their within-run difference from the reference provider.
An attestation can bind a result to a workflow and artifacts; it cannot prove the
runner reported honest measurements.

## Supported scored scope

`voicebank-demand-test-v1` uses all 824 paired official test utterances (two speakers),
resampled from 48 kHz mono to 16 kHz with the pinned SciPy polyphase recipe. It reports
SI-SDR improvement as the primary measure, with SI-SDR, STOI and ESTOI. Per-utterance
scores are summarized by mean and median; median intervals are deterministic 5,000-draw
resampling intervals stratified within each speaker. The interval describes variation
within this fixed cohort, not uncertainty over a wider population. The complete protocol
and limitations are in [`suites/voicebank-demand-paired-v1/protocol.json`](../suites/voicebank-demand-paired-v1/protocol.json).

For submitter-owned VoiceBank runs, first prepare the approved cache with
`python scripts/fetch_voicebank_demand.py --cache ~/.cache/audio-bench/datasets`,
then pass `--dataset-cache ~/.cache/audio-bench/datasets` to
`scripts/run_submitter_owned.py`. The result remains local until the submitter
reviews and adds the JSON file in a PR.

VoiceBank audio is downloaded after merge into the external verified Actions cache, or
into a submitter's local cache for submitter-owned execution. It is never committed,
uploaded as an artifact, or copied to Pages. Results retain archive, case-manifest,
protocol, source commit, SDK and effective-configuration hashes. Public scores are
measurements on this corpus, not a general qualification claim.

The synthetic 24-case suite remains a functional integration check. VOiCES is a
separate real-room/reference track and is not mixed into VoiceBank scores. DNS5's
selected development data do not have paired clean references and have no frozen
no-reference scoring protocol here; it is acquisition-only. Neither dataset is
eligible for the paired leaderboard.

## Submitter-owned results

Keep private source, weights, and corpus audio in your own repository or runner.
The submitter runner reads the private checkout locally, checks it against the
manifest's pinned commit, runs the built-in reference and candidate with identical
harness/dataset/settings, and writes a result-only JSON file. It never uploads
anything. Submit the result under `submissions/results/<submission-id>-<run-id>.json`.

The record contains only:

- a SHA-256 identity for the private repository (`sha256(owner/repository)`),
  the full source commit, and model digest;
- dataset, harness, and runner fingerprints;
- candidate metrics and a same-run baseline's raw metrics; and
- raw candidate/reference latencies plus the central reference latency used for
  the estimate.

Do not include the private repository name or URL, source code, model weights,
audio, credentials, or raw recordings. PR validation checks the closed schema,
finite measurements, and latency formula without fetching or running source. After
merge, Pages publishes the record with the fixed **Submitter-run · not independently
verified** label. Quality metrics remain raw and are never hardware-normalized.
The audio-pro manifest example is disabled by default. For a private candidate whose
submitter has cleared model and corpus rights, enable its manifest locally and run the
VoiceBank protocol with `--dataset-cache`. Submit only the result record; private source,
weights, and corpus audio stay on the submitter's runner.

## Public provider plugin contract

At the pinned source commit, provide a CMake target named
`audio_bench_provider` that builds one shared library. Include
`audio-bench-provider.json` at the repository root:

```json
{
  "schema_id": "audio-bench/provider-plugin/0.1",
  "provider_id": "example.noise-suppressor.v0",
  "descriptor_path": "path/to/provider.descriptor.json"
}
```

The descriptor must be canonical JSON and use the SDK provider descriptor schema.
The shared library exports `audio_bench_provider_table_v0()` and
`audio_bench_provider_descriptor_v0(uint32_t*)` as declared by the SDK C API.
Audio-bench compares the exported descriptor byte-for-byte with the committed
descriptor, loads candidate code only in the driver child process, and validates
the output protocol. The package artifact contains only the shared library,
descriptor, manifest, and source revision metadata. The workflow uses a fresh
build job and a fresh execution job, both with `contents: read` and no secrets.

Candidate source is arbitrary native code. The child process and separate jobs
reduce accidental data exposure and do not grant publishing credentials, but the
collector is not a sandbox: candidate code can interfere with its benchmark job.
Public-run results should be read as measured functional results, not an
independently qualified claim.

## Dataset files

Audio shards do not belong in Git or result artifacts. Keep only corpus
manifests, source identities, and hashes in the repository. Enabled corpus
acquisition adapters download to an external runner cache and verify source and
file hashes; audio stays outside GitHub Pages and workflow artifacts. See the
rights scope and current scoring support in [Corpus plan](CORPUS.md).

## Examples and publishing

- [`audio-sdk.json`](../examples/submissions/audio-sdk.json) demonstrates public
  source metadata and the audio-bench runner mode. It is a disabled example.
- [`audio-pro.json`](../examples/submissions/audio-pro.json) demonstrates
  submitter-owned mode and a private source reference. It is intentionally
  disabled until weights and model/data rights are cleared.

After a successful main push, CI exports built-in synthetic smoke records. A
separate post-merge candidate workflow exports public plugin results. The Pages
publisher accepts only successful push-to-main CI or candidate workflow artifacts,
merges validated records into the `benchmark-results` branch, and deploys the
cumulative index to [armaudia.github.io/audio-bench](https://armaudia.github.io/audio-bench/).
PR checks do not run the benchmark and cannot publish results.
