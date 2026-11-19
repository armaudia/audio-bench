# Release and maintenance policy

## Current release state

This cleanup establishes an empty public leaderboard and removes all in-tree
submission and result records. The report is intentionally blank until a new
submission is reviewed and merged. Existing Git history is retained; removing a
row from the current report does not rewrite prior commits or Actions logs.

The repository supports Linux x86-64 (`ubuntu-24.04`) CI and one Linux release
archive. It does not currently claim Windows or macOS support. Numeric workload
qualification is not assessed: there are no approved target-specific deadlines,
quality margins, or workload requirements. Do not describe functional CI or
benchmark results as product qualification.

## Pull requests and repository controls

`main` accepts reviewed pull requests. The intended GitHub rules require a fresh
code-owner approval, approval of the last push, resolved review threads, and the
`quality` check with an up-to-date branch. Force pushes, branch deletion, and
merge commits should be blocked. Verify the live settings; configuration files
alone do not prove that GitHub enforces them.

To audit repository publication controls:

```sh
python scripts/publish_repository.py
python scripts/github_admin.py --repo audio-bench
```

The publication audit refuses a dirty working tree, unexpected origin, common
secret patterns in history, model/key files, and mismatched repository
visibility. The administration script requires an authenticated GitHub CLI and
administrator access, checks current CI status, applies settings, and reads them
back to `build/github-settings.json`. Private-repository protection and release
environment controls depend on the organization plan and must be verified with
live readback.

## CI, benchmark execution, and Pages

CI runs on Linux. PR checks validate code, metadata, policies, and browser
behavior; they do not download real corpora or execute candidate submissions.
Main-branch and release-tag CI exercise the built-in synthetic fixtures and the
paced collector, then run the installed wheel with the native programs from the
extracted release ZIP. Those measurements stay out of the public results index. The candidate workflow runs
after an enabled public submission manifest is merged. It checks out the pinned
public source and executes the candidate without a publishing credential.

The Pages publisher merges candidate-run results, reviewed submitter-owned JSON
records, and exact-result removal requests into the `benchmark-results` branch.
It then deploys the cumulative result table. A removal request affects the
current report, not historical commits or workflow artifacts. The empty report
is the intended release starting point.

Candidate code is arbitrary native code. The isolated build/evaluation jobs and
read-only permissions reduce exposure but do not form an operating-system
sandbox. Keep secrets, private credentials, and source out of public-runner
jobs. Private source must be benchmarked on a submitter-owned runner.

## Data and model scope

The supported paired speech-enhancement cohort is the full VoiceBank+DEMAND
official test split (824 pairs). Its frozen metrics and limits are documented
in [`docs/CORPUS.md`](docs/CORPUS.md) and
[`suites/voicebank-demand-paired-v1/protocol.json`](suites/voicebank-demand-paired-v1/protocol.json).
The 24-case synthetic suite is a functional check. Real-time processing uses a
separate paced synthetic workload and reports the tested stream levels, lateness,
CPU, memory, and throughput; it does not claim unmeasured in-process SDK thread
scaling. VOiCES is a separate real-room track. DNS5 has no paired clean reference
and has no frozen score protocol here; it is not a leaderboard dataset.

Every submitter is responsible for rights to their source, model weights, and
data. Corpus rights and cache decisions are scoped to the versions and
operations recorded in the status manifests. Dataset audio remains outside the
public Git repository, Pages, and workflow artifacts except for the documented
five-clip VOiCES smoke fixture. See [`DATA_LICENSE.md`](DATA_LICENSE.md).

## Versioned software release

Release tags use `v0.1.0` or `v0.1.0-rc.1` (and alpha/beta equivalents). The
release workflow runs CI, checks that the tag points to a commit on `main`, uses
the `release` environment, verifies the Linux archive checksum, attests the
archive, and publishes the GitHub release. Configure that environment to require
the intended approval and verify its live settings before a stable release; the
workflow file alone does not enforce an approval. A corrected release uses a
new version. PyPI upload, Windows/macOS artifacts, public-audio playback, and
third-party model distribution are not enabled.

Before creating a stable release, record the source/license decisions, a passing
hosted run on every advertised target, clean-install evidence, known limitations,
and release notes. Repeat corpus acquisition/cache checks when source pins,
rights, or cache inputs change. Data-acquisition success alone does not qualify
model accuracy or product performance. Historical task handoffs in
[`docs/task-evidence/`](docs/task-evidence/README.md) preserve the status known
at the time; use the current protocol and status documents for present-day
claims.
