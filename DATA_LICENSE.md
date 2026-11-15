# Data and hosted-service scope

Apache-2.0 covers the benchmark software, runners, adapters and documentation.
It does not automatically license recordings, model weights, third-party datasets,
uploads, evaluation submissions or hosted-service participation.

The bundled generated harmonic/noise fixtures retain their explicit use grants
in `manifests/synthetic/synthetic-16k-v1/dataset.json`; see
`LICENSES/LicenseRef-Synthetic-Fixtures.txt`. They are not representative human
speech.

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
archives and every clean/noisy member. A named review of source-component and
voice-talent scope is still required before public benchmark scoring; audio
redistribution and playback remain disabled. See `docs/CORPUS.md`.

The Pages workflow is configured to publish only repository-reviewed result
metadata. It does not accept uploads or private source/audio. Automated result
ingestion, public-audio playback, and customer-data processing are not enabled.
Separate approved terms and consent controls are prerequisites before accepting
external artifacts or media.
