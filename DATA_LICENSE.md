# Data and hosted-service scope

Apache-2.0 covers the benchmark software, runners, adapters and documentation.
It does not automatically license recordings, model weights, third-party datasets,
uploads, evaluation submissions or hosted-service participation.

The bundled generated harmonic/noise fixtures retain their explicit use grants
in `manifests/synthetic/synthetic-16k-v1/dataset.json`; see
`LICENSES/LicenseRef-Synthetic-Fixtures.txt`. They are not representative human
speech.

## Third-party datasets

Each third-party corpus remains under its upstream license and any additional
rights applying to its recordings. Users who download or receive corpus data
must follow applicable source licenses, preserve attribution and notices, and
check component-specific and privacy/publicity terms. This repository's
software license, this notice, and a dataset's evaluation approval do not grant
rights to redistribute or publicly cache its audio.

Dataset status manifests are the authority for this repository's approved
operations. Public redistribution and GitHub Actions caching are separate
operations and require explicit `allowed` decisions with source-license
references, attribution, and approval evidence. A public Actions cache is
accessible to people who can open pull requests against this public repository;
do not place audio in it unless the approved scope permits that distribution.
When enabled, the cache must include a `RIGHTS_NOTICE.json` beside its audio.

The repository also includes five VOiCES noisy recordings and their one
LibriSpeech clean reference under
`manifests/voices/voices-dev-clean-smoke-v1/`. The VOiCES corpus publisher and
OpenSLR list the respective corpora under CC BY 4.0. Attribution, immutable
source references, archive and file SHA-256 digests, and limitations are
recorded in that subset's `provenance.json` and `docs/CORPUS.md`. This is a
single-utterance `dev-clean` smoke fixture, not benchmark leaderboard evidence.
CC BY does not grant privacy, publicity, or personality rights. Public audio
playback remains disabled pending a separate review of that use and suitable
consent controls.

The repository also registers the official 824-pair VoiceBank+DEMAND test
split in `manifests/voicebank-demand/voicebank-demand-test-v1/`. Its audio stays
outside Git and is fetched from the official University of Edinburgh DataShare
record only when requested. DataShare lists CC BY 4.0 and describes VCTK speech
and DEMAND noise as source components. The manifest pins the exact downloaded
archives and every clean/noisy member. Repository approval covers acquisition
for evaluation and attributed aggregate reporting. Public audio redistribution,
Actions caching, and playback are not authorized by the current status record.
See `docs/CORPUS.md` and `manifests/voicebank.status.json`.

The Pages workflow is configured to publish only repository-reviewed result
metadata. It does not accept uploads or private source/audio. Automated result
ingestion, public-audio playback, and customer-data processing are not enabled.
Separate approved terms and consent controls are prerequisites before accepting
external artifacts or media.
