# Work Log

Merged PRs and closed issues recorded by Guide. Initial history covers the
30-day window beginning 2026-09-07; earlier history remains in GitHub.

## Archives

- [2026-09](work_log/WORK_LOG_2026-09.md)

### 2026-11-24

- **PR #674**: fix: keep the label-collision gate running headless via extract.json
- **Issue #671** (closed): Label-collision gate loses its headless check of the current LATEST record once LATEST is store-backed
- **PR #670**: Re-run the seven post-layout benches on #620's thick-oxide record: verified input resolution, flavour gate, and an all-FAIL campaign dominated by the record's unrouted VDD
- **Issue #621** (closed): Re-extract and rerun the seven post-layout benches on the verified thick-oxide GDS
- **PR #663**: refactor: reuse corner-run installed_commit in post-layout snapshot lookup
- **Issue #656** (closed): Reuse the harness PDK revision reader in post-layout snapshot lookup
- **PR #666**: chore: ignore account-ranking.codex in loom-managed gitignore block
- **PR #664**: feat(layout): keep routed-flow summary files out of the artifact store
- **PR #661**: test: catch short+long add_argument forms in SharedOptionTailGuard
- **Issue #665** (closed): gitignore the daemon's account-ranking runtime state
- **Issue #657** (closed): Follow-on from PR #627: filter reports/<record-id>/ summary files out of publish
- **Issue #660** (closed): SharedOptionTailGuard: registration regex misses the short+long add_argument form
- **PR #659**: test: make SharedOptionTailGuard quote-agnostic and guard --corners repo-wide
- **PR #658**: refactor(sim): share the MC batch CLI block and dry-run print
- **PR #627**: feat(layout): draw the MOS blocks at 5 V thick-oxide and gate flavour, HV DRC and supply ERC in the routed flow
- **PR #652**: refactor(sim): share the injector runners' CLI option tail in parse_injector_args
- **PR #649**: refactor: build seed_stability keys with corner_id and pin them to the producer
- **Issue #655** (closed): Widen the psrr-injector shared-option-tail guard to all of sim/**.py, matching NoHandRolledCopiesTests
- **Issue #653** (closed): Share the duplicated Monte Carlo CLI parsing and batch dry-run blocks in batch_sim
- **Issue #620** (closed): Generate and verify the thick-oxide MOS geometry in the routed bandgap core
- **Issue #650** (closed): Share the 42-line CLI option and validation block in the two PSRR injector runners
- **Issue #647** (closed): Fold run_amp_offset_mc.py's two inlined corner-id format strings onto sim_common.corner_id

### 2026-11-23

- **Issue #638** (closed): Remove unconditional confirmation from the resistor head-resistance report
- **PR #640**: fix(sim): derive res-array-head-resistance determination from its checks
- **PR #646**: refactor: fold pex-native shims onto canonical corner-run types
- **Issue #554** (closed): Dedup pex-native's three duck-type shims onto corner-run's Corner/Experiment/Measurement dataclasses (_C has no .id, blocking batch_sim's collectors)
- **PR #644**: fix(sim): derive res-array-resize determination from its checks
- **Issue #642** (closed): Remove unconditional confirmation and duplicate check logic from sim/res-array-resize
- **PR #622**: Bind post-layout extraction to the PDK: temperature-behaved resistors on the extracted side (rows 1b/3b, item 7)
- **Issue #614** (closed): Post-layout benches simulate temperature-flat resistors: extract with klt's --pdk model binding and retire the hand resistor translation
- **Issue #633** (closed): generator-notes.md MET2_ESCAPE_NOTE: qualify the "what klt drc passes clean" sentence with the stricter-enclosure difference
- **PR #639**: docs: qualify met2 escape note's klt-drc pass-clean claim
- **Issue #545** (closed): Consolidate the VREF accuracy window: 4 copies of DR-005's ratified band under 4 names, plus 2 live gates still on the superseded draft band
- **PR #635**: refactor: consolidate DR-005's ratified VREF window into sim_common; rename the draft band DRAFT_VREF_WINDOW_V
- **Issue #636** (closed): Remove the hardcoded match narrative from trivial-cell LVS records
- **PR #637**: fix: drop hardcoded match narrative from trivial-cell records
- **PR #632**: Correct stale m2.6 / no-met2-rule prose; restate met2_drc as cross-check + orphan-via gate
- **Issue #517** (closed): Correct stale m2.6 / "no met2 rule" prose around layout/bin/met2_drc.py while keeping the full independent re-check

### 2026-11-22

- **PR #629**: refactor(layout): emit the empty inner-compose pins array directly
- **Issue #628** (closed): Remove the retired MOS gate label selector from inner compose

### 2026-11-21

- **Issue #624** (closed): Unit-test the shared resistor-chain substitution loop (sim_common.substitute_chained_arrays)
- **PR #625**: test: pin substitute_chained_arrays ordering, diagnostics, and wrapper delegation
- **Issue #617** (closed): Reuse the shared resistor-chain substitution and temperature sweep in the head-resistance bench
- **PR #623**: refactor(sim): reuse shared resistor-chain substitution and temp-sweep control in head-resistance bench

### 2026-11-20

- **PR #616**: feat: screen three bandgap temperature corrections on batch

### 2026-11-18

- **PR #610**: ci: add the merge_group trigger and gate merge-queue readiness
- **Issue #609** (closed): Merge queue: add the merge_group trigger and adapt the PR-metadata gates

### 2026-11-17

- **PR #585**: docs(signoff): sync status prose with the graded report and pins
- **Issue #543** (closed): signoff/README.md and README status text disagree with the committed signoff report and pins
- **PR #604**: fix(signoff): derive item-9 harness list from tracked sim/bin/*.py
- **Issue #602** (closed): T1 item-9 harness attestation hashes only 2 of 5 sim/bin modules; bench-family shared modules are uncovered
- **PR #567**: refactor(sim): split the psrr-injector-only surface out of sim_common into injector_common.py
- **Issue #557** (closed): Split the psrr-injector-only surface out of sim_common.py: 359 of its 1776 lines serve exactly two benches
- **PR #599**: chore(loom): resync installed Loom to v0.19.1306
- **PR #597**: fix: compare script_module origin on uncached lookups too
- **Issue #596** (closed): load_script_module(cached=False) still rebinds a name registered from a different file silently
- **PR #589**: fix: refuse an empty --variants selection in both psrr-injector benches
- **Issue #583** (closed): psrr-injector benches: --dry-run tracebacks with IndexError on an empty --variants selection
- **PR #595**: fix: refuse cross-file cache hits and clean up failed execs in load_script_module
- **Issue #592** (closed): load_script_module caches on the module name alone, so a name reused for a different file silently returns the wrong module

### 2026-11-16

- **PR #579**: chore(loom): resync installed Loom to v0.19.1302
- **PR #591**: test: run local test:unit/test:compile under the Python 3.11 CI pin
- **Issue #587** (closed): Dev hosts run Python 3.12 while CI pins 3.11, with no declared floor — newer-API use passes locally and fails in CI
- **PR #588**: feat(pex-native): geometry check shows VB total is an extractor series-sum
- **Issue #573** (closed): pex-native: settle whether VB's 5114.5 Ohm extracted total is physical (the question #541's ladder could not reach)
- **PR #582**: refactor: dedupe the 15 importlib loader copies into scripts/ci/script_module.py
- **Issue #555** (closed): Dedup the hand-rolled importlib loader: 15 copies across 13 files, only one honors the documented #267 contract
- **PR #548**: refactor(sim): one shared batch CLI flag block for all six harnesses
- **Issue #544** (closed): Dedup the batch CLI flag block onto sim_common.add_common_args() (6 harnesses, help text already drifted into 3 wordings)
- **PR #586**: docs(layout): retarget 25 stale *_NOTE citations to generator-notes anchors
- **Issue #565** (closed): Retarget the 25 stale `*_NOTE` pointers left behind by the generator-notes.md move (#552)
- **PR #584**: test: lock MC batch default-off request shape in the shared fixture
- **Issue #577** (closed): Lock amp-offset's batch-flag default-off request shape in the shared MC fixture
- **PR #581**: docs: link docs/ROADMAP.md from README and regenerate signoff attestations
- **Issue #578** (closed): docs/ROADMAP.md is not reachable from the README
- **Issue #580** (closed): Vendored Loom suite test-champion-premise-false-close.sh asserts against this repo's own CLAUDE.md and fails
- **PR #576**: refactor: share the MC batch group builder across both Monte Carlo runners
- **Issue #568** (closed): Dedup the last two duplicated MC batch helpers: batch_measurements and build_batch_groups
- **PR #575**: bench: add --dry-run to the psrr-injector-candidates batch harness
- **Issue #572** (closed): psrr-injector-candidates has no --dry-run path its sibling bench already has (plus a dead VARIANTS_BY_NAME rebinding)
- **PR #574**: sim: re-run the five post-layout benches resolving the klt 0.8.0 parasitics snapshot
- **Issue #560** (closed): Re-run the five post-layout benches that resolve the klt 0.8.0 parasitics snapshot
- **PR #569**: refactor: route qualify_dr005.py file digests through content_hash.sha256_file
- **Issue #547** (closed): Dedup the last bare file-hash copy: qualify_dr005._sha() duplicates content_hash.sha256_file()
- **PR #564**: feat(pex-native): distributed-RC record refutes the star-allocation hypothesis
- **Issue #541** (closed): pex-native: second record with --critical-net VB --critical-net VBQ --distributed-rc to split star-model allocation from the net total R
- **PR #558**: refactor(sim): store each fleet worker_environment once in a record table
- **Issue #549** (closed): batch_sim records 1149 copies of 2 distinct worker_environment blocks: 1.4 MB of redundant fleet attestation in sim/ records
- **PR #539**: docs: roadmap as of 2026-11-14

### 2026-11-15

- **PR #570**: refactor(sim): hash the trim-lsb netlist body via content_hash.sha256_text
- **Issue #562** (closed): Retire the last reachable HASHLIB_ALLOWED entry: run_trim_lsb_chained.py:270 hand-rolls content_hash.sha256_text()
- **Issue #553** (closed): Retire the two remaining HASHLIB_ALLOWED Python entries — content_hash already covers both
- **PR #566**: refactor(layout): move 13 never-loaded *_NOTE constants into anchored layout/generator-notes.md
- **Issue #552** (closed): Consolidate 13 never-loaded *_NOTE constants (299 lines) out of layout/bin: the records that cite them by name never carry their text
- **PR #563**: refactor(sim): share the MC batch-collector tests in mc_batch_shared
- **Issue #536** (closed): Share the duplicated Monte Carlo batch-collector test fixture between the two MC bench test files
- **PR #561**: refactor(tests): split test_routed_flow_gates.py into four per-concern files
- **Issue #556** (closed): test_routed_flow_gates.py: a mid-file unittest.main() hides 85 of its 142 tests from the documented direct-run path
- **PR #537**: refactor(sim): move the four batch/seed predicates into batch_sim
- **Issue #533** (closed): Share the four duplicated batch/seed predicates between the two Monte Carlo runners
- **Issue #571** (closed): No test pins the byte value of batch_sim.FLEET_JOB_OVERHEAD_S / FLEET_JOB_CEILING_S

### 2026-11-14

- **PR #559**: measure row 1b on a klt 0.8.0 extraction: the #2359 attribution is refuted
- **Issue #540** (closed): Re-extract parasitics at the pinned klt 0.8.0 and re-measure row 1b (klayout-tools#2359 is closed)
- **PR #551**: feat(signoff): cite the failing klt pex pilot for T1 item 7
- **Issue #542** (closed): T1 item 7: cite the klt pex pilot in the signoff manifest, or record why the pinned grader refuses it
- **PR #546**: refactor: one sha256 helper, with a separate name per return convention
- **Issue #538** (closed): Consolidate the 10 copies of sha256_file(): two incompatible return conventions share one name
- **PR #531**: refactor(sim): build trim-lsb-chained requests with batch_sim.build_adhoc_group
- **Issue #525** (closed): Dedup run_trim_lsb_chained.py's hand-rolled batch request onto batch_sim.build_adhoc_group (drifted: no remote.hosts, no ngspice_init)
- **PR #535**: fix(sim): refuse an over-ceiling Monte Carlo batch budget and size the MC shard count
- **Issue #528** (closed): Monte Carlo batch requests ask for one Spot host per sample, and nothing refuses a per-shard bound over the fleet ceiling
- **PR #529**: docs(spec): re-confirm the reference set and measure the MC shard loss in DR-021
- **PR #532**: refactor(sim): one Monte Carlo batch collector for both MC benches
- **Issue #522** (closed): Dedup collect_batch/record_tools/samples_path between the two Monte Carlo runners into batch_sim

### 2026-11-13

- **PR #530**: docs(layout): condense matching-plan Section 7, archive increments to a sibling file
- **Issue #499** (closed): Condense layout/matching-plan.md Section 7: ~3,500 lines of per-increment changelog
- **PR #524**: fix(sim): record every fleet job id and drop setseed wording from batch records
- **Issue #523** (closed): Batch sim records: job_id is null for sharded requests, and MC record prose says setseed on the batch path
- **PR #521**: docs: regenerate the characterization report onto the f6eeac7 records, and re-qualify error-amp-offset-mc
- **PR #520**: refactor(sim): one definition of the psrr-injector run orchestration
- **Issue #511** (closed): Dedup verify/explore/build_deck/run_point between the two psrr-injector sim scripts
- **PR #516**: sim: re-qualify the four analysis_steps post-layout benches and psrr-injector-attribution under open_pdks f6eeac7 (DR-021 slice C'+D4)
- **PR #515**: sim: collect error-amp-offset-mc batch reports into a record
- **PR #513**: docs(spec): record slice D3 dispositions in DR-021 and the stale C' batch refusal
- **PR #512**: sim: run the four analysis_steps post-layout benches on the batch fleet
- **PR #508**: sim: re-qualify psrr-injector-candidates under open_pdks f6eeac7 (DR-021 slice D2)
- **PR #507**: test: run emit_klt record-selector guard under sim/tests discovery
- **Issue #514** (closed): error-amp-offset-mc: batch collector has no open tracking issue (DR-021 cites closed #398)
- **Issue #510** (closed): sim: enable --backend batch for the four analysis_steps post-layout benches (fleet runner now accepts them)
- **Issue #506** (closed): Wire orphaned selector test into CI: sim/signoff-envelopes/test_emit_klt_sim_envelopes.py is never run

### 2026-11-12

- **PR #504**: sim: re-qualify trim-lsb-chained under open_pdks f6eeac7 (DR-021 slice D1)
- **PR #501**: sim: re-qualify three post-layout benches under open_pdks f6eeac7 (DR-021 slice C)
- **PR #500**: sim: re-qualify six pre-layout benches under open_pdks f6eeac7 (DR-021 slice B)
- **PR #498**: sim: re-qualify psrr-dc-with-injector under open_pdks f6eeac7 (DR-021 slice)
- **PR #497**: Bump Repo Skills 0.25.10 -> 0.26.1
- **PR #495**: sim: re-qualify startup-stability under open_pdks f6eeac7 (DR-021 index)

### 2026-11-11

- **PR #493**: feat(sim): enable batch backend for the four analysis_steps pre-layout benches
- **Issue #395** (closed): Enable --backend batch for remaining pre-layout corner-run benches (prereq of #370)

### 2026-11-10

- **PR #491**: chore: remove unreferenced guard-review-332 hook replay
- **Issue #485** (closed): Remove docs/guard-review-332 replay: closed one-off Loom hook review, unreferenced

### 2026-11-07

- **PR #487**: docs: attribute pex-native pilot Vref delta to resistor-leg parasitics
- **Issue #486** (closed): Attribute the pex-native pilot's −27.8 mV Vref delta by leg resistance and node voltage
- **PR #483**: Bump Repo Skills 0.25.1 -> 0.25.10

### 2026-11-06

- **PR #480**: feat: native klt pex pilot for output-voltage TC with recorded 15-corner result
- **PR #478**: fix: skip already-tracked bytes when publishing sim evidence
- **PR #477**: docs: add inert guard replay report and script for write-confinement review
- **Issue #476** (closed): publish_corner_evidence: skip staged files whose bytes are already tracked in git
- **Issue #335** (closed): Produce native klt pex comparison evidence for T1 item 7
- **Issue #332** (closed): Guard decision review: Review historical variable resolution for scoped scratch writes
- **PR #473**: chore(layout): run ERC flow from shared layout venv, drop separate klt pin
- **Issue #466** (closed): Consolidate ERC klt pin into the main layout venv (both pins now ==0.8.0)

### 2026-11-05

- **PR #471**: sim: add --batch-resume pass-through to the untrimmed MC harness
- **PR #470**: sim: add batch max-concurrent-jobs throttle and record throttled N=20 smoke attempt
- **PR #469**: sim: record second N=20 batch smoke attempt as failure evidence

### 2026-11-04

- **PR #463**: fix(sim): netlist testbenches via klt netlist instead of raw xschem
- **Issue #442** (closed): Replace raw-xschem netlist_with_xschem in corner-run.py with klt netlist
- **PR #465**: sim: record failed N=20 batch smoke run (fleet capacity losses)

### 2026-10-31

- **PR #461**: Bump Repo Skills 0.24.7 -> 0.25.1

### 2026-10-28

- **PR #457**: fix: select item-5 corner records by netlist match; re-mint 8a from main's injector
- **Issue #456** (closed): T1 item 5 (Full corner verification): re-mint row 8a startup-stability from a record of main's injector, not the DR-018 three-high candidate
- **PR #455**: chore: move superseded bandgap-core report GDS to artifact store
- **Issue #440** (closed): Prune GDS blobs from superseded bandgap-core report runs
- **PR #452**: fix(layout): snap drawn bus rects to the 5 nm grid for DRC-clean routed flow under klt 0.8.0
- **Issue #448** (closed): Bump klayout-tools pin 0e2362bda730, acb0ae6c11e6 → 0.8.0

### 2026-10-27

- **PR #449**: build: pin klayout-tools==0.8.0 in layout requirements
- **PR #438**: feat(sim): collect batch Monte Carlo reports into the untrimmed-Vref record
- **Issue #437** (closed): monte-carlo-untrimmed: implement --backend batch record collection (blocks #435)
- **PR #439**: feat(signoff): cite minted klt sim envelopes for T1 item 5
- **Issue #434** (closed): T1 item 5 (Full corner verification): cite klt sim envelopes for every DR-005 ratified row

### 2026-10-23

- **PR #431**: feat(layout): publish routed-flow outputs to the artifact store
- **Issue #426** (closed): Adopt the artifact store for new layout/bandgap-core report runs
- **PR #429**: refactor(layout): drop unused mos_pad and fmt_findings helpers
- **Issue #428** (closed): Remove unused mos_pad() and fmt_findings() from layout/bin
- **PR #427**: feat(sim): store new corner evidence in the artifact store, commit manifests only
- **Issue #424** (closed): Adopt the common artifact store for sim evidence (manifests in git, bytes via klt artifact)

### 2026-10-22

- **PR #422**: feat: compute n-well ties in ERC supply spec on klt 0.7.0, item 11 met
- **Issue #389** (closed): T1 item 11: declare both nwell tie classes with the new well-side box selectors (klayout-tools#2552) and re-mint ERC
- **PR #419**: signoff: cite a klt 0.7.0 LVS report for T1 item 4 and pin item 11's LVS half
- **Issue #388** (closed): T1 item 4: mint a hash-pinned LVS report now that klayout-tools#2374 is fixed, with a determinism re-measure
- **PR #417**: fix(signoff): regenerate stale attestation artifacts after PDK re-pin
- **Issue #416** (closed): CI red on main at 87e95da: attest_inventories tests and signoff freshness (T1 item 11 citation drift)
- **PR #390**: feat(signoff): attest T1 items 1, 2, 9, 10 on klt 0.7.0
- **Issue #387** (closed): T1 items 1, 2, 9, 10: move the grader to klt 0.7.0 and cite artifact-anchored inventory envelopes

### 2026-10-21

- **PR #413**: Bump Repo Skills 0.24.3 -> 0.24.7
- **PR #412**: refactor(sim): share psrr-injector batch helpers in sim_common
- **Issue #410** (closed): Dedup batch-backend helpers between the two psrr-injector sim scripts
- **PR #409**: feat(sim): add --backend batch and --dry-run to psrr-injector-attribution
- **PR #408**: feat(sim): build klt Monte Carlo batch requests for monte-carlo-untrimmed
- **PR #407**: refactor(sim): reuse batch_sim.sha256_file in run_trim_lsb_chained
- **PR #406**: feat(sim): build klt Monte Carlo batch requests for error-amp-offset-mc
- **PR #405**: feat(sim): dry-run batch requests for meas post-layout benches, refuse real runs until the runner supports analysis_steps
- **PR #399**: feat(sim): batch backend for the translatable post-layout runners
- **PR #392**: chore(layout): prune 8 redundant trivial-cell report runs, fix README current-record pointer
- **Issue #404** (closed): Dedup sha256_file(): run_trim_lsb_chained.py reimplements batch_sim's canonical helper
- **Issue #398** (closed): Batch backend for the remaining post-layout and MC/offset/attribution runners
- **Issue #396** (closed): Add --backend batch to post-layout, MC and attribution runners (prereq of #370)
- **Issue #381** (closed): Prune 12 unreferenced trivial-cell report runs; fix stale README pointer

### 2026-10-20

- **PR #403**: chore: remove stale tracked manifest.json.tmp and gitignore it
- **PR #402**: ci: pin signoff job Python to 3.11
- **PR #397**: feat(sim): batch backend for psrr-dc and quiescent-current; hold meas benches on runner klt
- **Issue #401** (closed): CI: signoff job red on main — klayout sdist build on unpinned python 3.x
- **Issue #400** (closed): Remove stale tracked .loom/manifest.json.tmp (interrupted-install leftover)
- **PR #373**: build(sim): re-pin PDK to open_pdks f6eeac7 via ciel with SOURCES revision check
- **Issue #369** (closed): Re-pin open_pdks to f6eeac7 (ciel) — fleet retires volare c6d73a3

### 2026-10-17

- **PR #385**: refactor(layout): move shared constants to layout_common to break bus_routing import cycle
- **Issue #384** (closed): Break gen_bandgap_routed <-> bus_routing import cycle: drop sys.modules alias and deferred imports
- **PR #380**: refactor(sim): share corner_id/matrix/band-min loader/run_all across psrr-injector scripts
- **Issue #379** (closed): Dedup corner_id/matrix/band-min loader/run_all between the two psrr-injector sim scripts

### 2026-10-16

- **PR #375**: Bump Repo Skills 0.24.1 -> 0.24.3

### 2026-10-15

- **PR #371**: docs(spec): DR-020 MPC2-on-VSENSE injector screen and mpc2_vs bench variants
- **PR #365**: docs(sim): shard batch PSRR screen requests and record mngq failing the 60 dB floor
- **PR #366**: feat(sim): shard batch requests over remote.hosts to fit the fleet job ceiling
- **Issue #364** (closed): sim: shard PSRR injector screen batch requests across remote hosts (15-unit requests exceed the 3600 s fleet job ceiling)
- **PR #362**: feat(sim): run the PSRR injector screen on the batch fleet
- **Issue #361** (closed): Make the PSRR injector candidate screen submittable via the klt sim batch path
- **PR #360**: docs(sim): record three-high injector stack failing startup-stability at 125C (DR-018)
- **PR #358**: docs(sim): VBE-raised NG clamp restores window-edge eviction current (DR-017)
- **PR #357**: docs(sim): record MNG clamp eviction-loss mechanism and add per-node injector probe mode
- **PR #356**: docs(sim): MNG clamp and weak reference stack fail injector eviction floor at 27C corners (DR-015)
- **PR #354**: sim: route startup-stability 45-corner matrix through Spot batch; live run 45/45 PASS (#320)
- **Issue #320** (closed): Route startup-stability’s full 45-corner regression through the Spot batch backend
- **PR #353**: Bump Repo Skills 0.19.5 -> 0.24.1
- **PR #352**: loom: unpin verdict-staleness-guard.sh and forge-helpers test (2am#4345 Q7)
- **PR #351**: ci(pdk-smoke): build xschem 3.4.7 from source -- apt's 3.4.4 leaves sky130 expr() attrs unevaluated (nightly red 74/74)

### 2026-10-08

- **PR #348**: README: complete Layout tree (#344)
- **Issue #344** (closed): README Layout section omits signoff, CI scripts, docs, ratification and reuse lock
- **PR #347**: sim/README: move per-bench record history out of runner-bypass table (#339)
- **Issue #339** (closed): sim/README.md experiments table embeds per-bench current-record verdicts that go stale
- **PR #346**: ci: widen syntax and JSON lint coverage (#343)
- **Issue #343** (closed): Widen CI syntax and JSON lint coverage beyond hand-listed files
- **PR #345**: reuse: record error_amp as kept in-tree via DR-014
- **Issue #337** (closed): Resolve reuse.lock.json error_amp 'evaluate' entry now that sky130-opamp has answered
- **PR #342**: signoff: single source of truth for klt grader pin (#338)
- **Issue #338** (closed): Consolidate duplicated klt grader pin and identity assertion into one source of truth
- **Issue #334** (closed): Qualify untrimmed 3-sigma accuracy separately from the Monte Carlo sanity floor
- **PR #340**: sim: derived DR-005 3-sigma qualification of untrimmed MC, separate from sanity floor (#334)
- **Issue #333** (closed): Grade the literal DR-005 trim range separately from DR-002 engineering checks
- **PR #336**: Grade literal DR-005 trim range separately from DR-002 engineering checks (#333)
- **Issue #327** (closed): Refresh trim-network evidence (trim-lsb-chained bench) against the current n_r2=51 design
- **PR #331**: Refresh trim-lsb-chained evidence at n_r2=51 (all DR-002 criteria PASS)
- **PR #329**: docs: compact README status scoreboard (8 spec rows)
- **Issue #328** (closed): README status narrative is a hand-maintained changelog that contradicts itself (seven vs eight spec rows)
- **PR #326**: sim: route startup-stability matrix through klt sim batch backend (#320; live run blocked by fleet klt pin)

### 2026-10-03

- **PR #322**: sim(psrr-injector-candidates): m_ref/m_pnp knobs closed for the hot corner; DR-013 (#315 partial)

### 2026-10-02

- **PR #321**: sim(psrr-injector-candidates): screen non-resize injector PSRR fixes; the three-high stack dies on startup margin
- **Issue #318** (closed): Dedup load_base_body(): run_psrr_injector_attribution.py reimplements sim_common's canonical helper
- **PR #319**: refactor(psrr-injector-attribution): delegate base-body load to sim_common's canonical helper
- **PR #317**: docs(report): transcribe #306's measured MPC1/MPC2 attribution into characterization rows 4b/4d/4e
- **PR #316**: sim(psrr-injector-attribution): identify MPC1/MPC2 as dominant PSRR contributor (#306)

### 2026-10-01

- **Issue #313** (closed): Dedup csv_list/csv_floats: post_layout_common.py reimplements corner-run.py's CSV parsers
- **PR #314**: Dedup csv_list/csv_floats: route post_layout_common.py through sim_common.py

### 2026-09-24

- **Issue #303** (closed): startup-ramp + post-layout: re-run the post-#284 manifest over the full 45-point matrix (the #284 records are 10- and 4-point subsets, host-capacity-limited)
- **Issue #299** (closed): Rows 8b/8d: the post-layout startup benches double-count the injector now that it is drawn — they need their own testbench
- **PR #311**: Rows 8b/8d: give the post-layout startup benches their own DUT shape, re-run, and re-grade
- **Issue #308** (closed): sim/bin/corner-run.py: add a -j parallel-corner mode so slow hosts stop forcing subset records
- **PR #310**: sim: add -j/--jobs concurrent-corner mode to corner-run.py
- **Issue #312** (closed): sim/tests/ is not run by CI — npm run check:ci only discovers layout/tests

