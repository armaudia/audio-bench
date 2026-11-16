<!--
SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
SPDX-License-Identifier: Apache-2.0
-->

# Public Actions cache approval record

- Decision date: 2026-11-16
- Approval source: repository maintainer's explicit instruction in the audio-bench project conversation: “approved. Implement caching, run 2 times, one with a cold run without cache, and one with cache”.
- Scope: public GitHub Actions cache storage for the pinned evaluation cohorts registered as `voices-balanced-realroom-v1`, `voicebank-demand-test-v1`, and `dns5-speakerphone-dev-v1`.
- Purpose: enable reproducible evaluation without committing corpus audio to Git or uploading it to Pages or workflow artifacts.
- Required handling: retain source attribution and license references in the cache's `RIGHTS_NOTICE.json`; preserve upstream license terms for every source component; publish aggregate results only; do not enable audio playback.
- Exclusions: this decision does not cover other corpus versions, training data, model training, public playback, Pages, release artifacts, or any corpus content outside the selected cohort manifests.

The relevant status manifests point here as evidence for the repository's
maintainer approval. This record does not replace or modify any upstream data
license; users who retrieve the cache must comply with the referenced upstream
terms.
