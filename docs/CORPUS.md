# Corpus plan for noise-cancellation benchmarks

## Candidate corpus

VOiCES is the current candidate for real-room noise-cancellation evaluation. Its
publisher describes noisy room recordings paired with clean source audio and
publishes the corpus under CC BY 4.0. The published devkit is about 27.5 GiB.
See the [VOiCES project page](https://iqtlabs.github.io/voices/), its
[download page](https://iqtlabs.github.io/voices/downloads/), and its
[corpus README](https://iqtlabs.github.io/voices/Lab41-SRI-VOiCES_README/).

Those published terms are a promising starting point, not a completed
audio-bench rights review. Before using the corpus, review the dataset and any
bundled materials for CI evaluation, derived score publication, attribution, and
redistribution of the selected subset. No VOiCES bytes are currently checked in
or downloaded by CI.

## Storage and reproducibility

Do not put corpus audio in Git or Git LFS. Select a fixed, rights-reviewed test
shard, keep it at a stable public object-store or archival URL, and commit only
its versioned manifest to audio-bench. The manifest should list every case,
speaker/split assignment, input and clean-reference digest, file size, sample
format, license/attribution record, and the aggregate manifest digest. The shard
must remain downloadable without credentials for the public audio-bench runner.

Local and CI runs should fetch only the manifest-pinned shard and verify its
SHA-256 digests before decoding. A cache may avoid repeated downloads, keyed by
the complete manifest digest, but cached bytes must pass the same digest check.
Never fetch a moving `latest` URL or use audio supplied in a pull request. For
private corpora, use the submitter-owned runner and do not publish audio or
credentials in results.

## Current state

No fixed VOiCES shard has been selected, reviewed, mirrored, or hashed. The
submission schema therefore allows only `synthetic-16k-v1`; VOiCES benchmark
execution is intentionally unavailable until the shard and its rights evidence
are added and reviewed. The synthetic suite remains a functional check and must
not be shown as real-speech quality evidence.
