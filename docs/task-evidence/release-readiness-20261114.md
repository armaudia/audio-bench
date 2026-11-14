# Local release-hardening evidence, 2026-11-14

Status: local engineering checks, not a production or public-release qualification.
The user's publication request authorizes repository preparation and publishing;
it does not supply missing third-party model or dataset permissions.

## Verified locally

- Full unit/SDK integration suite: 82 passed, no skips.
- Native CTest: 2/2 passed.
- Speex and high-pass each passed 24 synthetic cases x 7 metrics, sealing,
  validation and offline report generation.
- A fresh venv installed the built wheel and all runtime dependencies from an
  independently downloaded wheelhouse. No borrowed PYTHONPATH or system packages.
  Installed smoke, bundle validation and report generation passed outside source.
- Browser inspection confirmed all four attempt evidence dimensions remain visible
  after JavaScript renders, and unavailable media controls are disabled.
- Report output accepts empty directories, rejects symlinks and publishes
  atomically; a size-limit failure leaves no partial report directory.
- Native collector package/build/config/provider identities and frozen Python dependency versions are checked before sealing. Mismatched old binaries are rejected.
- Hosted Chromium acceptance passed for evidence badges, filters, CSV download,
  unknown-filter errors and disabled unavailable-media controls. No authorized
  real corpus or listening-gallery acceptance is claimed.

## Hosted verification and publication

- Public source: https://github.com/armaudia/audio-bench
- Linux x86-64 (Ubuntu 24.04) and macOS arm64 (macOS 15) acceptance passed:
  https://github.com/armaudia/audio-bench/actions/runs/43609204288
- Each host builds the exact public SDK source pin, tests native integration,
  runs all 82 unit/integration tests without skips, evaluates both providers,
  builds the wheel and executes installed smoke/validation/report outside source.
- Chromium acceptance on Linux passed. The initial clean-wheel failure exposed
  an omitted schema identity path; wheel execution now resolves that input from
  its packaged authoritative schema_data. GCC algorithm includes and integer-type
  portability defects were also fixed before the successful run.
- The dependency-update scan passed after retrying a GitHub container failure.
- CI actions are commit-pinned, ordinary workflow tokens are read-only, and a
  quality aggregate requires every matrix and licensing job. Public release jobs
  verify tagged main ancestry, archive checksums and provenance before publishing.
- Main and immutable release-tag policy definitions are under .github/;
  scripts/github_admin.py applies and reads back GitHub enforcement after CI.
  Its machine-readable API evidence is retained at build/github-settings.json.
- Software licensing: Apache-2.0; synthetic fixtures retain independent asset terms.
  SDK core/MPL source and third-party notices accompany bundled SDK distributions.

## Remaining qualification gates

Representative speech/corpus permissions and acquisition; hostile submission
isolation and adversarial review; public evidence export and an authorized
listening gallery; target workload criteria, real performance/quality acceptance
and production deployment qualification. These are disabled or not assessed,
not release claims. This is a synthetic evaluation tool prerelease.
