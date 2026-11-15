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
`--help`. Audio files are not stored in Git. Current rights state remains
blocked pending a named review of component provenance and voice-talent scope;
the metadata registration is not approval to run public scoring, redistribute
audio, or add playback. The benchmark runtime is also not yet wired to score
this cohort.

## Larger corpora and storage

Do not commit full corpora or multi-gigabyte releases to Git or Git LFS. Keep
large, reviewed datasets at a stable public object-store or archival URL and
commit a versioned, hash-pinned manifest. Local and CI runs should fetch only
the selected assets and verify SHA-256 before decoding. Cache by full manifest
digest, never by a moving `latest` URL. Private corpora use submitter-owned
runners; neither audio nor credentials belong in public results.

The official VOiCES devkit is about 27.5 GiB. This repository stores only the
small five-recording subset above; the other downloaded archive files were
discarded. The Lab41 90-degree mirror includes LibriSpeech train and dev source
partitions but does not provide the official held-out evaluation split, so it
is not used as a quality cohort. A qualified real-room VOiCES cohort still
needs a feasible, held-out subset source. The current benchmark runtime still
executes the synthetic suite only; neither external corpus is an enabled
scoring cohort.
