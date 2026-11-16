# Corpus plan for noise-cancellation benchmarks

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
selected cohort. Temporary runner storage is the default. The optional public
Actions cache is approved for this selected cohort and writes a rights notice;
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
Temporary runner storage is the default. The opt-in public Actions cache is
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

The repository maintainer approved acquisition, evaluation, public Actions
caching, and attributed aggregate results for DNS5 Track 2; the recorded scope
is limited to this selected cohort. The source archive is pinned by its official
Azure ETag, byte length, and Content-MD5; acquisition also records SHA-256 for
the archive and selected files. The downloader retains the 600 non-enrollment
speakerphone clips and official transcript TSV in an external cache. It fails
closed if the source identity or inventory changes. Audio publishing remains
disabled. The manual workflow defaults to temporary runner storage. Its
optional public Actions cache is approved for the selected cohort; it records
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
`actions/cache`; the cache includes a `RIGHTS_NOTICE.json`. The default workflow
path uses temporary runner storage and does not persist audio. A cache is
branch-scoped: runs on the same branch can reuse it, while caches created on
topic branches are not available to `main` or sibling branches.

The official VOiCES devkit is about 27.5 GiB. This repository stores only the
small five-recording smoke subset; the larger cohort is created in an external
cache from the official test partition. The Lab41 90-degree mirror is not used
for scoring because it does not establish an independent held-out test
selection. Evaluation, aggregate reporting, and public Actions caching of the
selected cohorts are approved for VOiCES, VoiceBank+DEMAND, and DNS5. Playback
remains disabled in the status manifests. The benchmark runtime still
executes the synthetic suite only; real-corpus scoring and Pages publication
are not yet implemented.
