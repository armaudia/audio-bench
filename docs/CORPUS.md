# Corpus plan for noise-cancellation benchmarks

Verified cold/warm run timings and scope: [dataset release evidence](DATASET_RELEASE_EVIDENCE.md).

## Release dataset policy (2026-11-17)

| Track | Selection | Role | Acquisition and persistence |
| --- | --- | --- | --- |
| VoiceBank+DEMAND | Official test split, 824 pairs, 2 speakers | Default paired enhancement cohort | Two official archives, 324,910,918 bytes total; local cache or approved public Actions cache |
| VOiCES | 40 test speakers, 4 conditions each, 160 cases | Optional real-room robustness cohort | Stream 27.5 GiB devkit once per cache miss; retain selected files only |
| DNS5 | Track 2 development, 600 noisy clips plus transcript | Optional evaluation; no clean-reference scores | Download 3.02 GiB archive on demand; local/temporary storage only until component mapping is resolved |
| VOiCES smoke | 5 recordings of 1 utterance | Integration checks only | Existing tiny attributed fixture in Git |

Use the entire frozen VoiceBank test cohort, rather than a hand-picked easy subset.
Report its two-speaker limitation and training-data overlap declarations. Keep tracks
separate; do not average their scores into one ranking. For paired enhancement,
use STOI and SI-SDR improvement over the noisy input, with a frozen resampling,
alignment, channel, and failure policy before qualifying a leaderboard. DNS5
requires a separately pinned non-intrusive metric implementation/weights or
listening protocol; DNSMOS predictions must not be labeled human MOS.

### When and where to fetch

- PR validation: schemas, rights records, downloader tests and code contracts only.
  No corpus download and no benchmark execution.
- Manual `Prepare corpus data`: select a cohort before its first evaluation, or
  warm a cache after eviction. Default is VoiceBank+DEMAND with public caching.
  DNS5 must use `use_public_actions_cache=false`; its public-cache gate rejects
  the request before restoring or saving audio.
- Local and submitter-owned runners: run the matching script with `--cache PATH`
  or `AUDIO_BENCH_DATA_CACHE`; the default is `~/.cache/audio-bench/datasets`.
  Keep this directory outside the source checkout. Fetch once, then use `--offline`.
- GitHub runners: data lives in `${runner.temp}/audio-bench-datasets`. A public
  Actions cache is an optional disposable acceleration layer, never the source
  of truth. A miss fetches upstream; an exact hit verifies files offline. No
  prefix restore keys or unverified fallback data. GitHub eviction is expected.
  Main-branch caches can be restored by eligible PR branches; treat all public
  cache contents as public. PRs never populate the trusted main cache.
- Git contains versioned selection recipes, source URLs, pins, legal notices,
  and results. New corpus audio does not go in Git, Git LFS, release assets,
  Pages, or workflow artifacts. The existing five-case smoke fixture is the
  explicit exception. No private corpus or credentials enter public caches.

VoiceBank verifies both archive SHA-256 values and all 1,648 WAV byte hashes
against committed provenance. Downloads use bounded ranges and transient-error
retries; error pages are rejected. A failed hash never publishes an archive.
Keep `.part` files for a retry; remove a failed/incomplete local extraction
before reacquiring if needed. `--archive-dir` supports previously downloaded
matching official ZIPs, without changing source pins. No silent mirror fallback.

A cache entry contains `RIGHTS_NOTICE.json` with attribution, component license
links, approval evidence and the cohort identity. The workflow checks rights
before restoring a public cache, verifies offline reuse after preparation, and
reports the exact cache-hit outcome. Check the post-job cache-save step before
claiming that a cold run populated GitHub's cache. Audio access can be revoked
operationally by disabling its status and deleting existing GitHub cache entries;
changing a status alone does not delete previously distributed copies.

### Release scope

Dataset registration/preparation is implemented independently of scoring. The
current automatic candidate runner still executes `synthetic-16k-v1` only.
Preparing these datasets does not enable real-corpus leaderboard scores. A
release may advertise verified acquisition and caching, but must not advertise
real-corpus scoring until execution, metric protocol, result provenance and Pages
presentation are implemented and qualified end to end. See `RELEASING.md`.

## Committed VOiCES smoke subset

`manifests/voices/voices-dev-clean-smoke-v1/` contains a small, committed subset
for local and CI integration checks. It is **not a leaderboard or quality
benchmark**: all five noisy samples are the same 10.885-second utterance from
the LibriSpeech `dev-clean` partition. They vary in room, microphone placement,
and distractor condition, but do not provide independent speech examples. Do not
describe scores on this subset as representative real-speech performance.

The selected clean source is speaker `1272`, chapter `135031`, utterance
`0000`. Five corresponding 90-degree VOiCES recordings are included: two
babble recordings in room 2 (far/mid mic), one babble recording in room 1
(mid mic), one room 1 recording without distractor (far mic), and one room 2
television-distractor recording (behind mic). The frozen source paths, archive
hashes, file hashes, sample metadata, and attribution are in
[`voices-dev-clean-smoke-v1/provenance.json`](../manifests/voices/voices-dev-clean-smoke-v1/provenance.json)
and [`files.json`](../manifests/voices/voices-dev-clean-smoke-v1/files.json).

Attribution and terms:

- VOiCES corpus: IQT Labs, *VOiCES: A Corpus for Learning Voice in Noisy
  Environments*, CC BY 4.0, [project page](https://iqtlabs.github.io/voices/),
  [download page](https://iqtlabs.github.io/voices/downloads/), and
  [corpus README](https://iqtlabs.github.io/voices/Lab41-SRI-VOiCES_README/).
- 90-degree subset files: Lab41, [archived VOiCES-subset repository](https://github.com/Lab41/VOiCES-subset),
  pinned at commit
  [`6284c9f83d1190c0a5c5054c32bcb666cb3d44a9`](https://github.com/Lab41/VOiCES-subset/tree/6284c9f83d1190c0a5c5054c32bcb666cb3d44a9).
- Clean reference: LibriSpeech, speaker `1272`, chapter `135031`, utterance
  `0000`, from the official [OpenSLR SLR12 distribution](https://www.openslr.org/12),
  CC BY 4.0.
- License text: [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/).

The CC BY 4.0 corpus terms permit redistribution with attribution. They do not
grant rights of privacy, publicity, or personality. This subset is committed
for benchmark evaluation and reproducibility; the website must not add audio
playback without a separate review. The clean reference comes from a `dev`
partition, so this subset must never be used as a hidden test set. See
[`DATA_LICENSE.md`](../DATA_LICENSE.md) for the repository-wide boundary.

## VOiCES balanced real-room cohort

`manifests/voices/voices-balanced-realroom-v1/selection.json` freezes a second,
independent selection recipe over the official VOiCES devkit test partition. It
selects one utterance for each of 40 speakers (20 male and 20 female in the
corpus metadata) and four recordings per utterance (no distractor, babble, music,
and television), rotating the room across the four VOiCES rooms. All cases use
the 90-degree source position and the far studio microphone. The preparation script checks that the selected noisy audio
and clean source are mono 16 kHz PCM16 WAV files and records SHA-256 for every
selected file.

The media is not committed. Run:

```sh
python scripts/prepare_voices_cohort.py
```

The script streams the official 27.5 GiB VOiCES devkit archive, writes only the
selected cohort into `~/.cache/audio-bench/datasets/voices-balanced-realroom-v1`,
and discards the stream. An existing subset is hash-verified before reuse. Use
`--archive` to process an official archive already on disk, or `--offline` to
require an existing verified cache. The archive ETag, source paths, selection
recipe, per-file hashes, and attribution are recorded in the generated cache
manifest. The current five-case committed subset remains a smoke fixture; this
larger cohort is the candidate real-room evaluation cohort. Neither cohort
enables audio playback in the report site.

The `Prepare corpus data` workflow can prepare this subset on a manual dispatch.
Each cache miss streams the full 27.5 GiB archive, then retains only the
selected cohort. The manual workflow defaults to an approved public
Actions cache for this selected cohort and writes a rights notice;
it never uploads audio artifacts or runs benchmarks. Caches are scoped by
GitHub to the workflow branch; a cache populated on a topic branch is not
available to `main` or sibling branches. The workflow is separate from PR
validation and the merge-triggered benchmark workflow.

VOiCES is real recorded-room audio with source speech references, but acoustic
channel and room response differ from the clean source. Treat its reference
metrics as a separate real-room track; do not combine those numbers with the
VoiceBank+DEMAND paired-mixture scores as though the cohorts were equivalent.

## VoiceBank+DEMAND paired test cohort

`manifests/voicebank-demand/voicebank-demand-test-v1/` registers the official
VoiceBank+DEMAND test split. It contains 824 exact clean/noisy pairs from two
speakers, mono PCM16 at 48 kHz. The noisy recordings combine real speech with
recorded environmental noise; this is a controlled mixture cohort, not speech
re-recorded in real rooms. It is useful as a standard comparison result, but
the two-speaker test set does not support broad demographic claims.

The DataShare record describes a clean/noisy parallel corpus and identifies
VCTK speech and DEMAND noise among the source components. Attribution, stable
archive URLs, downloaded archive sizes and SHA-256 digests, and every member's
size and SHA-256 are recorded in `provenance.json` and `cases-0000.jsonl`.
Retrieve and verify the data outside the checkout with:

```sh
python scripts/fetch_voicebank_demand.py
```

The optional `--cache`, `--archive-dir`, and `--offline` arguments are shown by
`--help`. Audio files are not stored in Git. The repository maintainer approved
acquisition, evaluation, and public aggregate results after review of the
official DataShare CC BY 4.0 record and the named VCTK/DEMAND source components.
Preserve the corpus attribution and license link in result records. This
approval enables public Actions caching of this pinned selected test cohort,
but not playback. See
[`voicebank-primary-source-review.md`](task-evidence/artifacts/voicebank-primary-source-review.md).

The manual `Prepare corpus data` workflow checks
`manifests/voicebank.status.json` before acquiring anything. It verifies every
archive and selected WAV digest and writes a rights notice beside the cohort.
The manual workflow defaults to public Actions caching, which is
approved for this pinned test cohort with evidence, license references, and
attribution. Audio playback remains disabled.

## DNS Challenge real-world quality cohort

The [official DNS Challenge repository](https://github.com/microsoft/DNS-Challenge)
provides a speakerphone development set of real 48 kHz
recordings and challenge-aligned metrics (P.835-style speech, noise, and overall
quality plus word accuracy). The pinned official archive is 3,236,752,796 bytes
(about 3.02 GiB). The speakerphone development track contains 600 ten-second
48 kHz clips, separate enrollment audio, and a transcript TSV. It has no paired clean waveform reference for the
speakerphone recordings, so reference-based SI-SDR/STOI scores are not
appropriate; use DNSMOS/P.835-style scores and word accuracy as a separate
non-intrusive track. The development split is intended for model iteration,
not a hidden leaderboard test. See the [ICASSP 2023 challenge paper](https://arxiv.org/abs/2303.11510).

The repository maintainer approved acquisition, evaluation, and attributed
aggregate results for DNS5 Track 2; public caching is disabled until selected
clip license mapping is documented; the recorded scope
is limited to this selected cohort. The source archive is pinned by its official
Azure ETag, byte length, and Content-MD5; acquisition also records SHA-256 for
the archive and selected files. The downloader retains the 600 non-enrollment
speakerphone clips and official transcript TSV in an external cache. It fails
closed if the source identity or inventory changes. Audio publishing remains
disabled. The manual workflow defaults to temporary runner storage. Its
public Actions cache is disabled for this cohort. Local evaluation must retain
the source notices and attribution beside the cached audio. No audio artifacts
are uploaded.

## Larger corpora and storage

Do not commit full corpora or multi-gigabyte releases to Git or Git LFS. Keep
large, reviewed datasets at a stable public object-store or archival URL and
commit a versioned, hash-pinned manifest. Local and CI runs should fetch only
the selected assets and verify SHA-256 before decoding. Cache by full manifest
digest, never by a moving `latest` URL. Private corpora use submitter-owned
runners; neither audio nor credentials belong in public results.

For a public GitHub Actions cache, set `public_actions_cache` to `allowed` only
after the corresponding redistribution decision is also `allowed` and the
status manifest records source-license evidence, per-component license
references, and attribution. The workflow checks these fields before invoking
`actions/cache`; the cache includes a `RIGHTS_NOTICE.json`. Disable `use_public_actions_cache` to use temporary runner storage only. A cache is
branch-scoped: runs on the same branch can reuse it, and eligible branches can restore the
default branch cache; topic-branch entries are not available to `main`.

The official VOiCES devkit is about 27.5 GiB. This repository stores only the
small five-recording smoke subset; the larger cohort is created in an external
cache from the official test partition. The Lab41 90-degree mirror is not used
for scoring because it does not establish an independent held-out test
selection. Evaluation and aggregate reporting have maintainer approval for all three
cohorts. Public caching is enabled for VOiCES and VoiceBank+DEMAND only. Playback
remains disabled in the status manifests. The benchmark runtime still
executes the synthetic suite only; real-corpus scoring and Pages publication
are not yet implemented.
