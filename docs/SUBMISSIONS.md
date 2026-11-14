# Submit a pipeline

Audio-bench accepts a small JSON registration in `submissions/<submission-id>.json`.
The manifest records public metadata and immutable identities; it must not contain
source code, weights, audio, credentials, or private data. Start from
[`submissions/_template.json`](../submissions/_template.json). The pull request
check validates only this metadata. It does not fetch or execute the referenced
repository.

## Runner choices

`runner_mode: "audio-bench"` is for public repositories. The source must be an
immutable commit from the currently supported public SDK repository and the
provider must be one of the allowlisted built-ins. The normal `main` CI builds
the pinned SDK and runs its synthetic functional suite after a merge.

`runner_mode: "submitter-owned"` is the planned path for private source in the
submitter's own CI or infrastructure. Audio-bench does not receive a checkout
credential. Private-runner execution and result ingestion are not implemented
yet, so this mode is currently a disabled manifest example. When enabled, the
result record should be labeled submitter-run and not independently verified,
and include raw metrics, source/model/dataset/harness digests, runner fingerprint,
and baseline measurements.

The planned submitter-run protocol should run the pinned reference provider first and
then the candidate with the same harness, corpus, process settings, and runner.
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

## Current supported scope

The real-corpus storage plan is documented in [Corpus plan](CORPUS.md). The checked-in runner currently supports only `speex.ns.v0` and
`dsp.highpass80.v0` on the 24-case synthetic smoke suite. The public corpus shard,
third-party provider loading, production model execution, private-runner execution
tooling, and independent isolation review are not yet implemented. Submitter-owned
JSON result ingestion is enabled and does not execute or inspect private code. The
CI submission check is metadata-only; the existing `main` CI smokes the pinned
built-in providers when a change lands. Do not set
`execution.enabled` for a production result until those capabilities and
scope-specific data/model rights are cleared. A synthetic run is functional
evidence, not a speech-quality benchmark or qualification.

## Submitter-owned results

Keep private source, weights, and corpus audio in your own repository or runner.
After you run the benchmark in that environment, submit one JSON record under
`submissions/results/<submission-id>-<run-id>.json`. Start from the
`audio-bench/submitter-result/0.1` schema. The record contains only:

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
verified** label. The normalization is an estimate; it cannot establish that the
submitter reported honest measurements. Quality metrics remain raw and are never
hardware-normalized. Use the built-in reference provider and the identical dataset,
harness, and settings in both measurements. The current audio-pro manifest is still
disabled, so it is not a measured model result.

## Examples

- [`audio-sdk.json`](../examples/submissions/audio-sdk.json) demonstrates public
  source metadata and the audio-bench runner mode. It is a disabled example, not
  an already-published result.
- [`audio-pro.json`](../examples/submissions/audio-pro.json) demonstrates the
  submitter-owned mode and a private source reference. It is intentionally
  disabled: the current audio-pro checkout has no model weights and its rights
  policy blocks model execution. The all-zero mechanics tests are not model
  benchmark results.

After a successful push-to-main CI run, CI exports records from the two validated built-in
synthetic smoke bundles. A separate publisher workflow downloads only that results index,
merges it into the `benchmark-results` branch, validates the cumulative index, and deploys
Pages. It is limited to successful `CI` runs caused by a push to `main`; PR CI and failed
runs cannot publish. The generated rows are explicitly labeled synthetic functional checks
and are not qualification or third-party pipeline results. The publisher needs the
repository Actions token to create/update `benchmark-results` and GitHub Pages to use
Actions as its source.

The registration files are not yet connected to candidate execution: the central runner is
restricted to the pinned SDK revision and its two built-in providers. A future production
submission must extend the reviewed provider interface, dataset rights gate, and result
schema before it can be run or published. Pages stays empty until a successful main push
produces the first validated result index.
