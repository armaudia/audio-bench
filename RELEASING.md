# Release and maintenance policy

## Branches and ownership

`main` accepts squash merges through pull requests. The intended GitHub rules
require a fresh code-owner approval, approval of the last push, resolved review
threads, and the `quality` check from GitHub Actions with an up-to-date branch.
Force pushes, deletion and merge commits are blocked, without ruleset bypass
actors. A second reviewer is therefore required when the owner authors a change.
CODEOWNERS names the initial maintainer; change it through a reviewed PR.

To audit the complete source history and inspect the exact destination:

```sh
python scripts/publish_repository.py
```

With an authenticated GitHub CLI, add `--apply` to create the repository with its
requested visibility and push the audited commit to main. It refuses a dirty
working tree, an unexpected origin, model/key files or common secret patterns in
history, and a mismatched existing repository visibility. It never force-pushes.

After the initial push and passing CI, an organization administrator runs:

```sh
python scripts/github_admin.py --repo audio-bench
```

Replace audio-bench with this repository's name. The script requires an
already authenticated GitHub CLI, checks admin access, verifies the current
commit's real CI status, applies the settings and reads them back. Actual
readback is saved under `build/github-settings.json`. Configuration files alone
are not proof that GitHub enforces a policy. Private-repository protection and
environment support depend on the organization's GitHub plan; an API refusal
must be resolved rather than described as enforced.

## CI and publishing

CI uses immutable GitHub Action commits, read-only tokens, clean Linux/macOS
runners, and an aggregate `quality` check that fails if any required job fails or
is cancelled. Workflow changes are reviewed as code. Dependabot proposes action
updates. Repository Actions must not approve their own pull requests.

Public release tags are `v0.1.0` or `v0.1.0-rc.1` (and alpha/beta equivalents).
The release workflow reruns CI, requires the tag's commit to be on main, requires
approval in the `release` environment, verifies both platform archive checksums,
and attests the artifacts before publishing them. Assets are attached to a draft
first, then the release is published with repository release immutability enabled. Only organization owners may create release tags. Separate immutable-tag rules
without bypass actors prevent those tags from being rewritten or deleted. A corrected release uses a new version. PyPI upload, public third-party execution and model distribution are not enabled by these workflows. `pages.yml` deploys the static results UI and publishes validated result-only records from successful main CI and candidate runs to the `benchmark-results` branch. Synthetic records remain functional checks. VoiceBank+DEMAND records cover the full 824-pair test cohort and link to the frozen metric protocol. Submitter-owned records are labeled unverified. DNS5 remains acquisition-only and VOiCES remains a separate non-leaderboard real-room track.

Before creating a stable release, record scope-specific source/license decisions,
passing hosted runs for the advertised targets, clean install evidence, remaining
limitations, and release notes. Local tests or a CI configuration are not a
production qualification. Do not reclassify pending legal, model, data, parity or
workload evidence as passing. Historical task handoffs retain their original scope.

## Dataset release checks

Follow the frozen choices and storage policy in [docs/CORPUS.md](docs/CORPUS.md).
Run the full Python suite and repository CI. Run `Prepare corpus data` on the
release commit for VoiceBank+DEMAND twice: first verify a cache miss, successful
acquisition, offline verification and post-job cache save; then verify an exact
cache hit and offline verification. Record run links, revision, cache key and
elapsed time. No benchmark runs during PR validation. Repeat acquisition checks
when source pins, downloader, rights or cache inputs change. Optional VOiCES and
DNS5 preparation is not evidence of qualified scoring. Before advertising the new
real-corpus path, run the enabled `audio-sdk-speex-voicebank` registration through
the post-merge candidate workflow, verify all 824 outputs and the published Pages
record, and run the submitter-owned path on a supported private provider. These
measurements do not establish general model qualification.
