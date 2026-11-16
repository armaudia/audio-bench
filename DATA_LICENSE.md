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
references, attribution, and approval evidence. VOiCES and VoiceBank+DEMAND currently have enabled public-cache decisions;
DNS5 public caching is disabled pending selected-clip license mapping. Historical
maintainer approval is recorded in the status
manifests and `task-evidence/artifacts/public-actions-cache-approval.md`. A
public Actions cache is accessible to people who can open pull requests against
this public repository. When enabled, the cache includes a `RIGHTS_NOTICE.json`
beside its audio. This approval is scoped to the selected cohort versions and
does not authorize playback, publication in Git/Pages/artifacts, or unrelated
corpus versions.

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
for evaluation, attributed aggregate reporting, and public Actions caching of
the selected test split, subject to component terms and attribution. Playback
remains unauthorized by the current status record.
See `docs/CORPUS.md` and `manifests/voicebank.status.json`.

The Pages workflow is configured to publish only repository-reviewed result
metadata. It does not accept uploads or private source/audio. JSON-only submitter result ingestion is documented in `docs/SUBMISSIONS.md`.
Public-audio playback and customer-data processing are not enabled.
Separate approved terms and consent controls are prerequisites before accepting
external artifacts or media.

## Notices that accompany data and results

Recipients must comply with each applicable upstream license. This notice does
not add conditions to Apache-2.0 or replace, sublicense, or override dataset
licenses. Maintainer operational approval is not a warranty of third-party rights.
Retain creator credit, title, source/DOI, license links, copyright notices and any
upstream disclaimers. Identify selection and processing changes (for example,
subset selection, resampling, alignment or enhancement) without implying creator
endorsement. Preserve applicable share-alike/database notices for components;
do not describe a mixed collection as entirely Apache-2.0 or CC BY 4.0.

VoiceBank+DEMAND attribution: Valentini-Botinhao, Cassia (2017), *Noisy speech
database for training speech enhancement algorithms and TTS models, 2016*,
University of Edinburgh CSTR, https://doi.org/10.7488/ds/2117, CC BY 4.0 per its
[end-user license](https://datashare.ed.ac.uk/server/api/core/bitstreams/7e7bc32f-e94a-436a-8e97-416a972c7e1a/content).
This repository selects the official test split without modifying cached audio.
VCTK and DEMAND component terms and attribution are linked in
`manifests/voicebank.status.json`. VOiCES/LibriSpeech credit and source links are
in `docs/CORPUS.md` and the cohort provenance. DNS Challenge datasets retain their
original component terms; the repository's CC BY license alone does not establish
licenses for every downloaded clip. See Microsoft's
[dataset terms](https://github.com/microsoft/DNS-Challenge#dataset-licenses).

Downloaded assets are provided by their upstream publishers under their own
terms and disclaimers. Dataset licenses do not necessarily grant privacy,
publicity, trademark or patent rights. Report suspected rights issues using
`SECURITY.md` or a repository issue without posting disputed/private audio;
maintainers can suspend downloads and remove hosted cache copies during review.
