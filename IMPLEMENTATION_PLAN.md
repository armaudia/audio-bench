# audio-bench implementation plan

Owner: benchmark maintainer, assigned in B01. Read [shared handoff](../plan/implementation_handoff_20261113.md), [EVIDENCE_SPEC.md](EVIDENCE_SPEC.md) and [TEST_PLAN.md](TEST_PLAN.md). B01–B09 are required for a manually published evidence-ready release. B10 is required for workload qualification; B11 for automated publication. B12 contains separately gated expansion. Existing results remain historical and are not rerun or certified by this plan.

## Target layout and dependency policy

```text
src/audio_bench/             strict ingestion, manifests, scoring, aggregation, export
native/                     fixed-rate SDK driver and trusted collector
schemas/                    evaluation-only JSON schemas
registry/                   providers, models, implementations, engines, pipelines, hosts
suites/                     explicit expected matrices and protocols
manifests/                  asset/case/interval identities, no large audio
locks/                      per-target Python/metric/toolchain dependencies
qualification/              target fingerprints and frozen criteria
report/                     plain HTML/CSS/ES modules, compact JSON, A/B player
runs/                       small immutable records or pointers in results branch
tests/fixtures/              synthetic public vectors and malicious bundle fixtures
scripts/                    task CLI entry points and offline report build
.github/workflows/          coordinator, disposable execution, trusted publisher
```

Migrate reusable functions from `../../src/audioml_eval/{assets,audio,metrics,records,runner,benchmarks,vad_benchmark}.py` and relevant tests by allowlist, not the entire research store. `../../scripts/evaluate_noise_suppression.py` contains a zero-mean SI-SDR implementation distinct from the simpler `snr()` in metrics.py; audit the actual function before moving it. Its current SI-SDR returns ±300 dB caps for degenerate cases; replace those with null/reason under the new protocol while preserving historical scores. The existing record ledger is research evidence; keep a read-only legacy importer instead of writing new benchmark records into old research snapshots.

Initial runtime dependencies: Python 3.12, NumPy/SciPy/SoundFile/jsonschema/filelock/psutil/pystoi 0.4.1 plus a tested JCS library. Dev: pytest and pip-tools, hashes locked per platform. Native: CMake/C++20 and installed SDK/conformance. No pandas, PyArrow, React, database or cloud SDK is required initially. Large traces are bounded JSONL shards; add Parquet as a derived format only in B12 when measured volume justifies it.

## B01 — Freeze migration/provenance and local execution environment (8–16h)

Dependencies: none; coordinate S01/P01.

1. Hash the existing harness/scripts/tests, historical result manifests and exact source paths. Record source snapshot and map legacy research IDs to new catalog IDs without changing old hashes.
2. Inventory all candidate/model/dataset/scorer assets and rights scopes with S01. Exclude customer data and private local path names from public manifests. Native source execution occurs only in approved disposable infrastructure; current developer machine inspection is not permission to execute submitted code there.
3. Create per-platform dependency input files and resolve/install hash locks in a clean environment. Run migrated primitive tests. Record exact libsndfile runtime version, Python patch and wheel digests; SoundFile package version alone does not identify decoder behavior.
4. Add offline synthetic fixtures, initial readme/contributor guide and explicit command documentation. Keep no imported historical claim qualified by default.

Exit: B-T01; provenance inventory complete and synthetic test environment installs without model/data downloads.

## B02 — Implement schemas, canonicalization, immutable ledger (20–36h)

Dependencies: B01; SDK descriptor/schema draft from S03 for compatibility integration.

1. Create every schema in EVIDENCE_SPEC.md plus its positive/negative fixtures. Bundle SDK schema by release/digest, with source attribution, without changing runtime ownership. Validate schema syntax and all references offline.
2. Implement strict duplicate-key/nonfinite/Unicode parser, JCS serializer and `content_id()` preimage rules. Pin the tested JCS package/version and RFC vectors; don't extend the old ASCII serializer under the same ID.
3. Implement request/run/attempt creation with UUIDs and monotonic request sequence from a trusted coordinator. Implement explicit expected case×metric sets, inventory closure, unique paths, referential checks and result status precedence.
4. Implement content-addressed cache and sealed core generation in the defined order. Write to a private temporary path, fsync file/directory, rename atomically on the same filesystem. Reject mutation of an existing digest path with different bytes.
5. Implement correction/review/reproduction/qualification append records referencing existing immutable cores. Enforce no circular hashes and no review inheritance across corrected cores. Add read-only legacy importer, preserving legacy algorithm identity and original scope.
6. Define CLI to create in this task: `python -m audio_bench validate <bundle>` (0 valid, 1 validation/coverage error, 2 bad invocation). CLI never executes candidate code while validating.

Exit: B-T02/B-T03/B-T04; identical fixtures resolve identical IDs across clean runs/platforms; altered payload fails.

## B03 — Verified assets, cases and common interval maps (16–28h)

Dependencies: B02, rights decisions; SDK timing fixtures can be synthetic initially.

1. Implement allowlisted HTTPS acquisition before execution, using immutable source revisions/archive SHA-256, resumable `.part` downloads and post-download verification. Block redirects to unapproved hosts/private addresses; no credentials in URLs/logs. Safe extraction rejects traversal/links/devices and enforces output byte/file/count limits. Use trusted source inventory to populate hashes from inspected downloads, never placeholders.
2. For VoiceBank mirror revision `4497db342d7312978c45690591fda86117831940`, verify official provenance/terms; enumerate all 824 unique matching clean/noisy pairs. Check mono/16k, finite samples, equal lengths, nonempty speaker IDs and partition. Record encoded and canonical decoded PCM hashes (little-endian interleaved float32, no normalization, exact signed-zero policy preserve bits). Any mismatch blocks that official corpus; synthetic conformance continues.
3. Select smoke IDs deterministically: lexicographic speaker IDs; within speaker sort by SHA-256 UTF-8 `ns-smoke-v1:<case-id>`, ties by case ID; round-robin speakers until 24 pairs. Store ordered IDs, hashes, selection script digest and dataset manifest ID before running any candidate. Too few complete pairs blocks this suite.
4. Generate clean/noise/marker/quiet-onset synthetic inputs from fixed integer seeds and specified sample lengths. Treat these as correctness/scenario fixtures, not representative speech evidence.
5. Freeze a single valid source interval per case for each comparison using verified buffering offsets/edge exclusions; no optimization against scores. Store interval-set ID and apply to clean/raw/every candidate. Inspect candidate eligibility before freezing; late addition requiring another interval yields a new cohort.
6. Gallery is separate: choose scenario strata before scoring, collect per-track playback permission and notices, and store panel selection. Initially synthetic authorized clips suffice, clearly labeled synthetic. No VoiceBank playback without allowed scope, even if internal evaluation is allowed. A smaller panel displays actual counts rather than pretending it has 24 clips.

Exit: B-T05; two clean manifest resolutions match; exact missing/blocked assets listed. Real hashes and filenames are B03 outputs, not fabricated planning text.

## B04 — Native SDK rendering driver and collector (24–40h)

Dependencies: S06 installed SDK/conformance, B02, B03 synthetic fixtures. Outputs: `native/audio_bench_driver`, `native/audio_bench_collect`, protocol tests and public CMake consumer.

1. Build against only installed SDK artifacts and run its pinned conformance first. Keep an explicit legacy application-ABI adapter for earlier evidence; label its zero-flush protocol and extension support absent. No private Stage includes.
2. Implement the bounded IPC format in EVIDENCE_SPEC.md with exact byte-length validation, nonblocking supervisor endpoints and trusted schedule/receive clocks. Candidate process receives no publisher/signing credentials or filesystem outside approved mounts. Internal driver service/queue clocks are candidate-reported; external collector observations are the deadline authority.
3. Preload input, prepare provider once per condition and allocate all buffers outside timed loops. Submit sequential 160-sample frames preserving state for an entire case; reset between independent recordings; use FINAL_INPUT and bounded drain to collect the tail exactly once.
4. Persist native float32 WAV output, source interval map, flags and exact clock counters. Validate all returned intervals and finite samples. If a case fails midway, retain partial diagnostics, complete expected status rows and explicit failure intervals; never score a cropped success as a complete case.
5. Raw control passes identical decode/crop/serialization with provider bypass; identity remains a conformance control. Compare direct driver output with SDK C/Python examples on the same fixture.
6. Record exact executable/package/config/source digests. Add `render` subcommand contract: frozen request + local verified cache -> attempt directory and sealed evidence candidate, no publication. CLI/paths are implemented here, not assumed existing.

Exit: B-T06/B-T07; exact conservation, reset and bounded tail; malformed IPC/output cannot fabricate passed coverage.

## B05 — Honest paced runtime measurement (24–40h)

Dependencies: B04.

1. Implement absolute schedule at frame completion, 10-second warmup then 60 measured seconds; five paired candidate/control repetitions, fresh process per condition. Sequence candidate/control AB,BA,AB,BA,AB; alternate initial order in the next independently identified experiment. Store order and source/workload identities. Drain after the measurement window; record tail delivery separately and include full actual elapsed/CPU intervals in their declared denominator.
2. Record scheduled/actual submit and delivery, output receiver clocks, internal diagnostic service/queue records, accepted/rejected/concealed/output samples, process-tree CPU, RSS, host load/thermal/power/OS/toolchain. Use exact sample and ns counters. Classify collector lateness separately from candidate deadline failures; either can invalidate qualification.
3. Initial runtime workloads: (a) all-active distinct speech clips for each stream from the frozen manifest, concatenated in case order with a manifest-declared seam; (b) all-zero; (c) 2 seconds active/2 seconds zero repeated, per-stream phase offset by stream_index*160 samples; (d) synchronized 5 seconds zero then 5 seconds speech. Freeze duration/loop rules before comparing. Speech source rights gate speech workloads; synthetic substitutes are separate labeled protocol IDs.
4. Start concurrency 1,2,4,8, doubling through the frozen cap (default cap=64), stop after first failed point; test remaining integers between last success and first failure in ascending order. Cap/resource exhaustion is reported as sweep limit, not proof of maximum capacity. Never drop failed points. One official performance job per physical machine.
5. Inject a 15 ms collector stall at frame 500 and worker stall at frame 700 separately. With the fixture profile (1 ms allowed collector lateness, 10 ms source-frame delivery budget), assert pacing/deadline failure even if library counters are zero. Repeat output-queue fill/input rejection and delayed drain. Do not use the fixture's deliberately strict deadline as a customer acceptance target.
6. Retain actual paced outputs for every advertised point. For initial deterministic DSP use exact decoded float sample equality and identical interval maps against sequential rendering of the same warmup+workload stream. A mismatch prohibits combining sequential quality and that runtime point. If outputs vary, B06 scores those paced outputs under a workload-specific cohort.
7. Quantiles use nearest-rank on raw observations, with counts, p50/p95/p99/p99.9/max; store all event counts/denominators. No rare-tail reliability claim from a short run. Hosted/sanitizer timings stay exploratory.

Exit: B-T08/B-T09/B-T10; stalled/empty/lossy runs fail, actual elapsed denominators retained, quality linked to actual output.

## B06 — Metrics, completeness and paired analysis (16–28h)

Dependencies: B02–B04, B03 real corpus for VoiceBank claims.

1. Audit SI-SDR from the existing NS script against the analytic formula/fixtures; do not rename plain SNR into SI-SDR. Implement STOI/ESTOI separate settings/IDs with pystoi 0.4.1. Store gain/clipping/max diagnostics and null/reasons without finite caps.
2. Execute scoring after rendering, outside timing jobs, using frozen common intervals. Validate correct clean/noisy pairing/output digest before invoking each metric. Every expected case×metric gets one status, including skipped dependency failures.
3. Compute paired deltas vs raw and per-speaker/case summaries, means/medians and the exact conditional bootstrap specified in EVIDENCE_SPEC.md. Persist sample draw seed/method/lock; do not reuse the existing grouped VAD bootstrap for the different VoiceBank estimand.
4. Emit missing/failed/excluded/undefined counts. Partial intersections are diagnostic and clearly separated from complete tables. Metric/scorer upgrades create a new cohort and rescore retained validated output, preserving old cores.
5. Add independent metric environment locks; ASR/PESQ/DNSMOS are not installed by default. Unknown scorer rights/assets produce blocked rows only when explicitly requested by a suite.

Exit: B-T11/B-T12; analytic values match, crop identities cannot mix, same outputs give same summaries on clean rerun.

## B07 — Registry and reproducible local submission path (8–16h)

Dependencies: B02, S05 descriptors, B06.

1. Create closed catalog schemas/records for provider/author, model, implementation, engine package, pipeline recipe and host integration. Stable IDs are distinct; a high-pass implementation has no model. Pipeline recipes list ordered component descriptor/config IDs and a chosen engine; do not redefine SDK graph syntax.
2. Required catalog fields: ID/type/display name, upstream URL/revision, attribution/license/rights refs, maintenance owner/status, source availability, vendor endorsement evidence or unknown, supported contract/platform/task IDs, local descriptor digest, acquisition instructions, evaluated attempt refs. Reject dangling refs/cycles in dependency graph.
3. Initial entries cover raw control, Speex, high-pass, basic.v1 legacy chain and reference engine; neural/private entries only when corresponding immutable artifacts actually exist. Do not imply vendor endorsement from a public adapter.
4. Implement `python -m audio_bench smoke <submission.json>`: validate metadata, use local authorized synthetic assets, invoke installed SDK conformance/driver in approved execution context, produce a complete local bundle. No automatic execution of arbitrary acquisition URLs.
5. Contributor guide explains template, task semantics, dependency pins, license/scopes, local command, evidence labels, review queue, corrections and three-hour weekly maintenance cap. Community listing is distinct from company maintenance/qualification.

Exit: B-T13; a fresh engineer can validate metadata and run an eligible synthetic submission with no private service.

## B08 — Isolated execution and trusted export (24–40h)

Dependencies: B02/B04/B07; must pass before third-party execution/public export. Do not attach untrusted jobs to the current personal workstation.

1. Separate acquisition/build from offline measurement. Initial production isolation is a disposable Linux VM on dedicated hardware, recreated per candidate from a reviewed base image digest. No cloud/SSH agent/home/keychain/private network mount. macOS official runs require a dedicated wiped lab host with equivalent data/credential isolation; otherwise only company-reviewed local lab experiments, no third-party execution.
2. Inside VM use unprivileged account, read-only approved input/asset mounts and empty writable output. Network denied after acquisition; host firewall blocks private/metadata addresses. No host Docker socket/devices. Default limits: 8 logical CPUs, 16 GiB RAM, 20 GiB writable disk, 256 processes, no core dump; timeout 15 min ordinary attempt or 45 min soak. Smaller assigned limits override only before request freeze; insufficiency yields resource_exhausted, never an unrecorded adjustment.
3. Trusted collector is outside candidate user/process isolation; protect its inputs, clocks, files and signing keys. Supervisory OS metrics include all candidate descendants. Terminate the complete process group/cgroup on exit/timeout, collect bounded logs, verify no surviving descendants, destroy/recreate VM before another candidate. VM overhead belongs to the protocol; do not claim bare-metal capacity from it.
4. Exporter takes a collector-sealed bundle and explicit field/media allowlist, never a candidate-chosen directory/URL. Linux collector/publisher opens with no-follow/directory-relative operations, rejects links including hardlinks (nlink!=1), absolute paths, `..`, normalization collisions, devices, executables, archives, undeclared files. Copy into a fresh trusted directory and verify copied bytes/hashes; bound reads before parsing/decode. On other OS use equivalent descriptor-based safe copy or refuse untrusted ingest.
5. Limits: bundle <=2 GB decimal, media <=100 MB, each JSON/JSONL record <=1 MB, <=100,000 inventory entries, nesting <=32, audio <=30 min/file and channels<=2 for export validation. Use chunked JSONL shards <=100 MB each; records <=1 MB. Oversize traces require a separate approved inventory, not bypassing caps.
6. Allowed media: canonical JSON/JSONL, validated WAV/FLAC and raster PNG after trusted decode/reencode. No HTML/JS/SVG/executable/archive payload. No candidate URL fetch by publisher. Text is escaped. Public output fields come only from the public schema; no generic metadata, local paths, customer IDs, raw private configs, hidden case IDs or participant mappings.
7. Private bundle export uses explicit approved public descriptor and opaque immutable config ID, a new sanitized public core and rights decisions for every media file. Full private linkage remains private. Manual reviewer approves exact public export digest. Publisher credentials exist solely in a trusted workflow that never checks out/executes candidate source; attestation is a transport/collection claim, not independent model reproduction.

Exit: all B-T14/B-T15 adversarial rows pass. Missing disposable infrastructure blocks third-party execution, while metadata/schema/report work can proceed.

## B09 — Minimal static evidence report and retention (16–28h)

Dependencies: B06–B08, authorized gallery, SDK example links when available.

1. Generate compact escaped JSON shards and plain HTML/CSS/ES modules from validated public cores. No frontend framework required. Row key is configuration+cohort; task/hardware/crop/metric differences split comparisons. Show origin, execution, reproduction, review, qualification separately, with failures and complete counts visible.
2. Encode task/cohort/selected config IDs in URL query parameters; validate against the local index. Export visible rows as CSV/JSON with exact IDs; protect CSV cells beginning =,+,-,@ with a text prefix. Do not auto-fetch external URLs from query parameters.
3. Use same-origin authorized PCM previews and Web Audio A/B switching: decode both buffers before play, shared AudioContext start offset, stop both sources on seek/switch, preserve sample position, no independent gain normalization. Cap initially preloaded preview bytes to 20 MB, load another case on demand; if memory/decode unavailable use explicit linked audio players and disclose lack of synchronized switch. Keyboard controls, labels/focus, errors, pause and identity reveal must work.
4. Publish raw/source/descriptor/methodology/upstream attribution links. Link a pinned SDK example only after it exists; evidence-only reports state integration example unavailable. Include manager summary with task, boundary, measured tradeoff and limits. No unsupported universal winner or hidden pay gate.
5. Store small immutable metadata on results branch, official payload bundles under immutable release/object IDs and small gallery on report host. Actions artifacts are temporary transport only. Pin referenced media before publishing the index. Release assets are downloads, not assumed CORS/range-capable streaming endpoints; copy eligible previews to report hosting.
6. Retention: permanent published metadata; permanent media referenced by releases/panels/regressions until rights withdrawal; ordinary unreferenced outputs 30 days. GC is mark-from-published-manifests then sweep only unreachable objects older than policy, dry-run first. Withdrawal adds tombstone/reason and removes forbidden media while retaining permissible hashes/metadata. Never silently serve a replacement under an old digest.
7. Initial site budget <=500 MB (headroom below Pages' documented 1 GB cap), initial compressed index <=1 MB; fail build if exceeded. Pages hosts open evidence/docs. Commercial offer/intake/transactions stay on separate founder-owned appropriate hosting; only a manually configured approved link is added here.

Exit: B-T16–B-T18; report builds offline from public sanitized fixtures, player and failure views verified in browser.

## B10 — Frozen target qualification (16–32h plus measurements)

Dependencies: S07, B05–B09, target access, founder-signed workload requirements. P04 consumes this protocol.

1. Inventory exact hardware/OS/CPU topology/features/power/thermal/toolchain/container/VM/isolation/thread policy and host version. Linux candidate scope is independent of Mac lab evidence. Do not call a VM target a customer's bare-metal host.
2. Run baseline repeatability study: five fresh-process repetitions per candidate/control with interleaved order and three 30-minute soaks for the proposed supported point. Retain raw outputs and workload provenance. This study informs margins; it is not the acceptance run and cannot be reused as held-out evidence.
3. Freeze `qualification/<target-id>/criteria.json`: all fields from the original technical specification plus metric direction, sample quantile rule, whole-host CPU/RSS definitions, required observation IDs, target fingerprint and signature/reviewer/time. Default investigation target is <=40 ms p99 first-valid-source-sample-to-collector-availability and >=25% whole-host CPU headroom; these are explicitly initial engineering targets, not customer promises. Buyer requirements replace them before freeze. Absolute deadlines/lateness limits and a defensible quality margin must be supplied and approved; absence yields not_assessed, never a filled-in guess.
4. Acceptance: five interleaved 60-second repetitions and one new 30-minute mixed workload soak, all exact criteria checked. Zero unexplained lost/duplicate/rejected/concealed/deadline-missed frames and zero unrecovered backend failures. No silent averaging away one failed repetition. Verify quality on actual paced output or equivalence, including quiet/onset/endings; retain all failed points.
5. Emit qualified/not_qualified per exact package/config/workload/host/target scope, or not_assessed when prerequisites missing. A 30-minute zero-event observation is not an SLA or independent reproduction. If quality margin is absent, separate timing evidence may pass but no combined workload-quality qualification is awarded.

Exit: B-T19; immutable frozen criteria precede new acceptance attempt; target results and claim limits accompany the badge.

## B11 — Durable automation and publication (24–40h)

Dependencies: full manual B01–B09 flow. Qualification automation needs B10.

1. PR workflow: read-only token, disposable hosted runner, synthetic tests/schema/report checks, no private secrets, no pull_request_target checkout/execution of fork code.
2. Trusted push-main/manual/approved-dispatch coordinator: validate exact SDK package/harness/request digests and sender/repository allowlist. Compare push before..after; unknown base/path/dependency => conservative full configured matrix, never empty successful plan. Persist per-revision request/attempt ledger before dispatch. Initial policy is every accepted main revision, no intentional coalescing.
3. Dependency planner: provider -> provider conformance and dependent pipelines/tasks; shared runtime/timestamps/resampling -> all affected; dataset/annotations -> new cohort + rerender/rescore; metric -> rescore retained compatible output; report-only -> report build. Full weekly reconciliation compares main revisions/accepted dispatches to ledger and requeues missing requests idempotently.
4. Performance execution uses one central queue per physical machine plus an OS-level exclusive machine lock shared by every launcher. GitHub concurrency is supplementary, not the durable ledger. Use cancel-in-progress=false; if supported, queue:max holds up to 100 pending jobs. Overflow/cancellation is detected by reconciliation. Never expose dedicated self-hosted credentials to candidate process.
5. Quality job, serialized performance job and trusted publisher are separate identities/permissions. Cross-repo authentication uses a narrowly scoped GitHub App, present only in coordinator control jobs; public tests need none. Private candidate transfer includes only approved binary/assets in isolated execution, never private source in public artifacts.
6. Publisher validates exact export digest and all referenced media, appends immutable results and atomically CAS-updates index generation. Only advance latest when required matrix complete; compare trusted request sequence within the same tracked source branch/scope, not job finish time or unrelated commit timestamps. Old late attempt cannot advance new snapshot. Show pending/failed newest request beside last complete evidence.
7. Serialize index deployment, retry optimistic conflicts by re-reading/merging immutable entries. Deploy explicitly after validated publication; do not depend on bot commits retriggering workflows. Missing upload/deploy is a recorded publication failure and retry, not lost measurement history.
8. Pin actions to reviewed full SHAs and verify workflow syntax with actual provider tooling at implementation. No fabricated action SHAs in this handoff.

Exit: B-T20/B-T21; out-of-order, duplicate dispatch, queue overflow, cancelled job, upload failure, concurrent publication and old results all preserve history/latest correctness.

## B12 — Follow-on capabilities (separate budget and release)

| Work package | Prerequisite, implementation sequence and exit |
|---|---|
| Neural/native/pipeline breadth | S10/P03 cleared provider contracts -> isolated scalar neural quality -> native parity -> basic/full chain ablations with explicit ordered config IDs -> workload scoring. Do not mix isolated models and composed pipelines. Extend B-T06/08/11/19 for every config |
| DNS real/fullband and AEC/dereverb | New rights-verified source manifests with independent groups, rate/target semantics and frozen splits -> exact scorer code/weight lock -> analytic/scenario fixtures -> output generation -> scoring. DNSMOS P.835 separate SIG/BAK/OVRL, exact window/hop/short clip rule; AECMOS scenario crops, ERLE far-end-only; native fullband source required for fullband claim. Unavailable scorer/data blocks that cohort only |
| ASR impact | Authorized wanted-speech transcripts -> one exact local recognizer checkpoint/decoder/language/text normalization -> no hidden ASR VAD -> pooled S/D/I/N WER plus per-case output. Another recognizer is another condition; do not reproduce a vendor multi-recognizer claim with one model |
| Full VAD accuracy | Dense scored speech AND nonspeech labels, two-annotator adjudicated validation subset, independent speaker/session split -> region-aware confusion/boundary/time availability tests -> pinned development threshold -> held-out evaluation and grouped bootstrap. Unknown spans never negatives. Existing EAR-1/InaGVAD exclusions remain; positive-only diagnostics cannot qualify this suite |
| Advanced engines | S11/P07 public contract and conformance -> fixed/off/observe/auto/batch ablations on identical source streams -> quiet speech/onset/ending and synchronized wakeups -> actual loaded output quality -> independent scoped qualification. Batch throughput never substitutes for deadline evidence |
| Formal listening | Rights-cleared frozen output panel -> private campaign mapping/consent/assignment service -> pilot 24–30 cases/3–4 systems + raw, about 10 valid ratings/case-condition -> estimate variance/power before expansion -> prespecified exclusions/paired clustered analysis -> unblind and publish aggregates only. Audit selected ITU edition before conformance claim; initially label style/inspiration. Static public ballots remain informal, never trusted shared votes |
| Rich report / trace scale | Profile real data volume first -> add TypeScript/React/Vite and table/virtualization/chart libraries under tested exact package lock only when needed -> lazy cohort shards and derived Parquet -> browser accessibility/performance tests. Raw JSONL/core remains authoritative; no browser database/backend required for v0 |

Each package begins with a versioned suite/criteria/expected inventory and dedicated tests before scoring. Dataset counts beyond the initial 824/24 are freeze outputs from real inventories, not promises that unavailable recordings exist.
