# VoiceBank+DEMAND primary-source review

Reviewed: 2026-11-14. This is provenance research, not legal advice or a rights approval.

## Primary-source observations

- University of Edinburgh DataShare identifies the official item as **“Noisy speech database for training speech enhancement algorithms and TTS models”**, DOI [10.7488/ds/2117](https://doi.org/10.7488/ds/2117), handle [10283/2791](https://datashare.ed.ac.uk/handle/10283/2791). The record describes paired clean/noisy 48 kHz speech, names the VCTK corpus and DEMAND as source material, and exposes separate clean/noisy test/train archives plus an “End-user Licence” link and a direct archive-download link.
- The linked end-user licence is the **Creative Commons Attribution 4.0 International Public License**. Its grant covers reproduction, sharing, and adapted material subject to attribution and other conditions. Section 2(b) excludes moral, publicity, privacy, and similar personality rights from the licence. The official licence notice separately states that the licence does not affect voice talent moral rights and says derogatory use is prohibited.
- The DataShare description says some noises were obtained from DEMAND and the speech source was VCTK. The selected derivative archive and its actual composition have not been inspected; this is not evidence that every component file has identical provenance or permissions.
- The current VCTK DataShare record (DOI [10.7488/ds/2645](https://doi.org/10.7488/ds/2645), replacing the older 10.7488/ds/1994 identifier) lists CC BY 4.0 for that VCTK item. This does not itself decide the rights status of the VoiceBank+DEMAND derivative or all underlying noise recordings.
- A request to the linked legacy DEMAND site did not return content during this review. No DEMAND-specific terms were inferred from that failure.

## Local-byte and decision status

- Searching `audio-bench` and its immediate workspace siblings found no VoiceBank or DEMAND corpus archive/assets; only `manifests/voicebank.status.json` exists. No archive was downloaded. Archive digest, byte count, pair count, and 824-pair manifest remain **unobserved**.
- The public record and licence are now checked rather than assumed absent. Acquisition/evaluation/redistribution/public-playback decisions remain `unknown` in the manifest until a named reviewer resolves the derivative archive, attribution, source-component, and voice-talent scope questions. Therefore no VoiceBank evaluation, public playback, or rights-cleared corpus claim is made.
- Synthetic fixtures remain the only locally available paired audio. Their rights and evidence labels are separate from VoiceBank.

## Reproduction references

Fetched 2026-11-14:

1. <https://datashare.ed.ac.uk/handle/10283/2791>
2. <https://datashare.ed.ac.uk/bitstreams/7e7bc32f-e94a-436a-8e97-416a972c7e1a/download> (linked end-user CC BY 4.0 licence)
3. <https://datashare.ed.ac.uk/items/30e7453c-9ea8-48b4-8e18-f96d0dc62928/full> (current VCTK record and licence metadata)
4. <http://parole.loria.fr/DEMAND/> (request failed; no terms observed)
