# Submit a pipeline

The submission is a JSON manifest in `submissions/<submission-id>.json`. Start
from [`submissions/_template.json`](../submissions/_template.json). The manifest
contains public metadata and immutable source/model identities only. Do not add
pipeline source code, model weights, audio, credentials, or private repository
names to this repository.

This release starts with no active submission manifests, submitter result
records, removal requests, or published result rows. The report is intentionally
empty. The examples directory was removed so old demonstration entries cannot be
mistaken for current measurements.

## What a manifest declares

Set a stable `submission_id`, readable name, category, runner mode, provider ID,
source commit, model digest, baseline provider, dataset, and suite. Keep
`execution.enabled` false while preparing and validating the manifest. Set it to
true only when the pinned source and model are ready to run and all required
dataset/model rights are cleared. A public model must be available from the
pinned public source repository; the audio-bench PR must not contain its code or
weights.

Choose the category and supported workload together:

- **`speech-enhancement`** uses `voicebank-demand-test-v1` with
  `voicebank-demand-paired-v1` for paired speech-quality and runtime results.
  This cohort contains all 824 official test pairs from two speakers. Synthetic
  smoke results are functional checks, not speech-quality rankings.
- **`real-time-processing`** uses `synthetic-16k-v1` with
  `realtime-throughput-v1`. It tests 1, 2, 4, 8, and 16 concurrent worker
  processes and reports the largest tested level meeting the 10 ms p99 frame
  completion-lateness budget, with CPU, memory, and throughput. It does not
  measure in-process SDK thread scaling or capacity above 16 streams.

The Pages report is a single sortable table with category, runner, suite, and
search filters. A category filter narrows the rows and the category-specific
measurements shown for those rows; unavailable measurements are displayed as a
dash.

## Public source runner

Use `runner_mode: "audio-bench"` only for a public source repository. Pin a full
40-character commit. The provider must export the SDK C plugin contract. PR CI
validates metadata only; it never checks out or runs the candidate. After an
enabled manifest is merged to `main`, the Candidate benchmark workflow checks
the dataset rights gate before any download, fetches and builds the pinned
commit, runs the selected workload, validates the result artifact, and publishes
it to the cumulative Pages report. Candidate build/evaluation jobs have
read-only repository access and no publication credential.

Candidate code is arbitrary native code. Job separation and read-only tokens
reduce exposure but do not provide an operating-system sandbox. Never put
secrets or private source in a public-runner job. Public measurements are not a
general product qualification claim.

## Submitter-owned runner for private source

Use `runner_mode: "submitter-owned"` when source or weights must remain private.
The candidate runs on the submitter's own machine or CI. Audio-bench receives no
checkout credential and never fetches the private repository. The runner checks
the declared commit or its declared Git tree, runs the built-in reference and
candidate with the same harness/dataset/settings, then writes a JSON-only result.
It does not upload anything automatically.

Latency is reported raw and, when a matching published calibration anchor exists,
as an estimated audio-bench-runner value:

```text
estimated candidate latency = candidate latency on submitter runner
                             × calibrated audio-bench latency
                             ÷ reference latency on submitter runner
```

The calibration anchors in
[`qualification/runner-calibration.json`](../qualification/runner-calibration.json)
are internal timing references only. They are not leaderboard rows or quality
scores. The ratio assumes the candidate scales like the reference provider. Do
not normalize speech-quality metrics; retain raw candidate and local reference
metrics. The real-time throughput profile does not yet have a central timing
anchor, so submitter-owned real-time latency stays raw and is not normalized.
Results are always labeled **Submitter-run · not independently verified**.

Review the generated record and, if you want it public, add it to
`submissions/results/<submission-id>-<run-id>.json` in a PR. Keep private source,
weights, repository names/URLs, raw recordings, and credentials out of the JSON.
The PR workflow validates the schema and arithmetic only. After merge, Pages
reprojects the validated file into the downloadable report.

## Datasets and rights

VoiceBank+DEMAND is acquired from the pinned official source into a local or
eligible GitHub Actions cache; its 824-pair audio is not in Git, Pages, or
workflow artifacts. See [the corpus policy](CORPUS.md) and
[`DATA_LICENSE.md`](../DATA_LICENSE.md) for rights, attribution, cache, and
scoring boundaries. VOiCES is a separate real-room track, and its five committed
clips are only a one-utterance smoke fixture. DNS5 is acquisition-only here: its
speakerphone development data lack clean references and the project has not
frozen a separate no-reference score protocol. Dataset and model rights remain
the submitter's responsibility.

## Removing a published result

To remove a row, copy
[`submissions/removals/_template.json`](../submissions/removals/_template.json)
to `submissions/removals/<short-description>.json`, then fill in the exact
`result_id` from the row's provenance or the downloadable results JSON and give
a short public reason. A PR validates the request; after merge, the Pages
publisher removes that row from the cumulative index and deploys the update.
Keep the request file while the result must remain suppressed. One request is
required for each result ID.

Removal affects the current report and downloadable index. It does not rewrite
Git history or prior Actions artifacts. If confidential content was published,
use the incident and history-removal process as well.

## Result data and publishing

Audio-bench stores result metadata, source/model digests, dataset identities,
protocols, and evidence hashes. It does not store candidate code, weights,
private checkout credentials, or downloaded cohort audio. The Pages workflow
merges candidate-run artifacts, reviewed submitter-owned records, and removal
requests into the `benchmark-results` branch. Main-branch CI does not publish
its built-in synthetic smoke measurements. PR checks never benchmark or publish.
