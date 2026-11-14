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
- A Chromium regression is configured in hosted CI; its hosted execution remains
  pending. No listening-gallery acceptance or authorized real corpus is claimed.

## Prepared, requiring hosted verification

- Linux x86-64 and macOS arm64 CI, with pinned official Action commits, read-only
  tokens, machine-readable test reports and an aggregate required quality check.
- SDK CI additionally runs address/undefined and thread sanitizer jobs.
- Code ownership, dependency update configuration, main/tag rulesets and an
  administration script with preconditions and settings readback.
- Public-repository release workflows rerun CI, verify reviewed ancestry and
  archive checksums, require release-environment approval and attest artifacts.
- Source history was checked for common GitHub/AWS/private-key secret patterns;
  no matches were found. This is not an independent security audit.

## Outstanding

Repository creation/push, hosted job results, policy and
visibility readback, and release-environment configuration are not yet complete.
The owner approved the mixed SDK licensing and Apache benchmark software license. The individual CLA is published in his personal name. Workload/target acceptance,
independent security review, corpus and model rights/reference evidence remain
outside the locally verified scope. Do not call the private neural product a
qualified commercial release.
