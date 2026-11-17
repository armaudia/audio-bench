# Dataset release evidence — 2026-11-17

Validated implementation: `7808008a80aec1e35f50eeedab8b15420cfa5e44`
([PR #12](https://github.com/armaudia/audio-bench/pull/12)).
Dataset policy and commands: [CORPUS.md](CORPUS.md).
Applicable data notices: [DATA_LICENSE.md](../DATA_LICENSE.md).

## Frozen release choice

VoiceBank+DEMAND official test split is the primary paired cohort: 824 pairs,
1,648 WAV files, two speakers, 48 kHz mono PCM16. The canonical official content
URLs resolve the clean archive and corrected noisy bitstream UUID (`…ad5`).
Archive sizes/hashes and every WAV hash are unchanged from the frozen inventory.
The archives total 324,910,918 bytes; ZIPs plus extracted files use approximately
695 MiB locally. No new audio is committed, released or published on Pages.

VOiCES 160-case selection remains an optional independent real-room track; the
five committed clips remain smoke only. DNS5 local evaluation remains approved;
public caching is disabled pending selected-clip component-license mapping.
Optional VOiCES/DNS5 full downloads were not repeated in this verification.

## Hosted cold and warm trials

Both successful workflow_dispatch trials ran on main at the implementation
revision above, on clean GitHub Ubuntu runners, with `dataset=voicebank-demand`
and `use_public_actions_cache=true`.

| Trial | Run | UTC interval on 2026-11-16 | Duration | Observed outcome |
| --- | --- | --- | --- | --- |
| Cold | [43946598778](https://github.com/armaudia/audio-bench/actions/runs/43946598778) | 20:08:14–20:21:57 | 13m 43s | Cache miss; official downloads; all 824 pairs verified; offline verification passed; cache saved |
| Warm | [43949128209](https://github.com/armaudia/audio-bench/actions/runs/43949128209) | 20:22:37–20:23:09 | 32s | Exact cache hit; restore succeeded; all 824 pairs verified offline twice; no corpus download |

Exact key:

```
audio-bench-corpus-voicebank-demand-ef32e3ca21a0a84086497d72a1b08a52d548faa2e66987618261dd3f61d9e59a
```

GitHub reported a compressed cache of 653,587,423 bytes (~623 MiB). The warm
restore took approximately eight seconds. Each offline corpus verification took
under one second on that runner. These are observations, not a timing guarantee;
source bandwidth, GitHub queueing and cache eviction can change future durations.
Budget approximately 15–20 minutes for a cold VoiceBank preparation and about a
minute for a warm run, excluding unusual queue delays.

The cache includes `RIGHTS_NOTICE.json`. Both rights gates passed before cache
access. A cache is disposable; the official source and committed identity pins
remain authoritative. Dataset preparation never runs a candidate benchmark.

## Other verification

- Full local Python suite: **118 passed, 9 skipped**.
- PR #12: Linux, macOS, DCO and aggregate quality checks passed before merge.
- Merged implementation: Linux/macOS, DCO, quality, Pages build/deploy passed.
- Fresh local official-source download verified both archive hashes and all
  1,648 WAV hashes. Offline reuse took approximately one second.
- Live negative check: changing one byte in cached `p232_001` clean WAV caused
  offline verification to reject it. Original bytes were restored and the
  entire cohort verified again.
- Unit coverage checks bounded retries, error-page rejection, archive integrity,
  cache integrity, path safety and the DNS5 public-cache denial.

## Release claim boundary

This evidence qualifies VoiceBank acquisition, integrity checks and public
Actions cache reuse. It does not qualify denoising accuracy or real-corpus
leaderboard execution. The candidate runner still accepts synthetic scoring
only. A stable release advertised as a real-corpus benchmark still needs a
frozen metric/preprocessing protocol, candidate execution on these pairs,
provenance-linked result ingestion, and Pages presentation tested end to end.
DNS5 needs its own pinned non-intrusive metric protocol. No release tag was
created on the strength of acquisition evidence alone.
