# VoiceBank+DEMAND primary-source review

Source research reviewed: 2026-11-14. Repository-use decision recorded: 2026-11-16.
This document records source provenance and the maintainer's repository decision;
it does not alter the upstream license or provide legal advice.

## Primary-source observations

- University of Edinburgh DataShare identifies the official item as **“Noisy speech database for training speech enhancement algorithms and TTS models”**, DOI [10.7488/ds/2117](https://doi.org/10.7488/ds/2117), handle [10283/2791](https://datashare.ed.ac.uk/handle/10283/2791). The record describes paired clean/noisy 48 kHz speech, names the VCTK corpus and DEMAND as source material, and exposes separate clean/noisy test/train archives plus an “End-user Licence” link and a direct archive-download link.
- The linked end-user licence is the **Creative Commons Attribution 4.0 International Public License**. Its grant covers reproduction, sharing, and adapted material subject to attribution and other conditions. Section 2(b) excludes moral, publicity, privacy, and similar personality rights from the licence. The official licence notice separately states that the licence does not affect voice talent moral rights and says derogatory use is prohibited.
- The DataShare description says some noises were obtained from DEMAND and the speech source was VCTK. The official test archives were inspected and the 824 clean/noisy pairs were verified. The underlying license remains the upstream CC BY 4.0 license and its terms.
- The current VCTK DataShare record (DOI [10.7488/ds/2645](https://doi.org/10.7488/ds/2645), replacing the older 10.7488/ds/1994 identifier) lists CC BY 4.0 for that VCTK item. This does not itself decide the rights status of the VoiceBank+DEMAND derivative or all underlying noise recordings.
- A request to the linked legacy DEMAND site did not return content during this review. No DEMAND-specific terms were inferred from that failure.

## Local-byte and decision status

- On 2026-11-15, the official clean and noisy test archives were downloaded to temporary storage and inspected. The clean archive is 154,332,064 bytes (`sha256:b60bfc2b9df38466d8eb45057c087c6e5dee196c67a0ed7bca628ae2a8611c4e`); the noisy archive is 170,578,854 bytes (`sha256:ba4a893f45b627f15209ba30ab584dd495b3680cd6f216dd08d143a257611993`). Each archive contains 824 WAVs; names pair one-to-one, all files are mono PCM16 at 48 kHz, and every paired clean/noisy sample count matches.
- Per-member byte lengths and SHA-256 digests are recorded in `manifests/voicebank-demand/voicebank-demand-test-v1/cases-0000.jsonl`. The audio files themselves remain outside Git. `scripts/fetch_voicebank_demand.py` verifies both pinned archives, safely extracts them to an external cache, and checks every cohort member.
- **Repository-use decision (2026-11-16):** the repository maintainer confirmed acquisition, evaluation, and publication of attributed aggregate results for the official test cohort. This decision is recorded in `manifests/voicebank.status.json`; it does not change the upstream license. Audio redistribution and public playback are not authorized by this repository decision. Preserve attribution and source provenance with every result.
- Synthetic fixtures remain the only locally available paired audio. Their rights and evidence labels are separate from VoiceBank.

## Reproduction references

Fetched 2026-11-14:

1. <https://datashare.ed.ac.uk/handle/10283/2791>
2. <https://datashare.ed.ac.uk/bitstreams/7e7bc32f-e94a-436a-8e97-416a972c7e1a/download> (linked end-user CC BY 4.0 licence)
3. <https://datashare.ed.ac.uk/items/30e7453c-9ea8-48b4-8e18-f96d0dc62928/full> (current VCTK record and licence metadata)
4. <http://parole.loria.fr/DEMAND/> (request failed; no terms observed)
5. <https://datashare.ed.ac.uk/bitstreams/dec213d3-bf57-4777-9663-c24bdce92d5e/download> (official clean test archive)
6. <https://datashare.ed.ac.uk/bitstreams/13c1bfbf-14a6-41db-9b41-8f7310f01ad7/download> (official noisy test archive)

## 2026-11-17 source URL correction

The historical noisy-archive link above contains a transcription error (`ad7`).
The official DataShare record links to bitstream
`13c1bfbf-14a6-41db-9b41-8f7310f01ad5`. Current provenance uses the
canonical `/server/api/core/bitstreams/<id>/content` endpoints. Expected
archive SHA-256 values, WAV hashes and the frozen cohort remain unchanged.
