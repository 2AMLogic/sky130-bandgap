# Work Log

Merged PRs and closed issues recorded by Guide. Initial history covers the
30-day window beginning 2026-09-07; earlier history remains in GitHub.

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

### 2026-09-23

- **PR #309**: sim(startup-ramp): re-run the full 45-point matrix on the post-#284 manifest
- **Issue #300** (closed): PSRR post-layout FAILs 25/45 (22.75 dB worst vs DR-006's 60 dB floor) once the startup injector is drawn into the composed cell
- **PR #307**: sim(psrr): add schematic-level injector PSRR bench; cause is design, not extraction
- **Issue #284** (closed): Startup convergence-spread FAILs 13/45 (schematic) and 16/45 (post-layout), both worsened by #193's resize — untracked
- **PR #305**: sim(startup-ramp): gate vref convergence directly and disposition the vref_spread FAILs under DR-010
- **Issue #302** (closed): Signoff hygiene after #285: re-pin T1 items 3/11 to the injector-inclusive layout record, plus two doc-rendering artifacts
- **PR #304**: fix(signoff): re-pin T1 items 3/11 to injector-inclusive layout
- **Issue #285** (closed): The startup injector has no layout, so the composed cell omits it — item 2 and item 7 cannot be claimed complete
- **PR #301**: layout: draw the startup injector into the composed cell; re-run the post-layout suite against it
- **Issue #288** (closed): klt lvs mismatch-count regression (0->12) + leaked absolute path in klt-yield evidence block items 4 and 6 from the T1 signoff manifest
- **PR #298**: fix(evidence): repo-relative klt yield paths; measure the klt lvs combine flake
- **Issue #283** (closed): Post-layout row 1b is an artifact FAIL from klayout-tools#800, fixed upstream 2026-08-12 — bump klt and re-grade
- **PR #297**: Row 1b post-layout FAIL: klayout-tools#800 was closed not-planned (not fixed) — real, still-open cause is klayout-tools#2359
- **Issue #292** (closed): signoff: CI does not detect a change to the artifact a manifest pin describes (input_verified is null on every citation)
- **PR #296**: signoff: re-hash the artifact behind every manifest pin in CI (#292)
- **Issue #286** (closed): 2am: reuse rule 9 — in-tree error amplifier duplicates sibling canary sky130-opamp — add reuse.lock.json in_tree entry (evaluate), then adopt or record
- **PR #294**: chore: add reuse.lock.json in_tree entry for error_amp (2am rule 9)
- **Issue #293** (closed): README: embed the fleet burndown chart (one line)
- **PR #295**: README: embed the fleet burndown chart
- **Issue #281** (closed): T1 item 11 (power delivery, structural): no klt erc supply spec or report in this repo
- **PR #290**: layout: klt erc supply spec + report for T1 item 11 (power delivery, structural)

### 2026-09-22

- **Issue #282** (closed): Commit a klt signoff block manifest so this block's T1 state is graded, not hand-read
- **PR #289**: signoff: commit a klt signoff block manifest for this block's T1 state

### 2026-09-14

- **Issue #179** (closed): OPERATOR QUESTION: if the core's TC floor stays above the ratified < 50 ppm/°C, scope curvature correction or stand non-qualifying on item 5?
- **PR #197**: spec: propose DR-009 — TC floor disposition (recommend disclosed-FAIL, not spec relaxation)
- **PR #240**: fix(ratification): remove unwrapped private-repo reference from market-key/SKILL.md

### 2026-09-10

- **Issue #279** (closed): sim: re-run the PSRR / Iq / startup benches (schematic + post-layout) against the post-#193 design and layout, then regenerate the block characterization report (T1 items 5, 7, 8)
- **PR #280**: sim: re-run PSRR/Iq/startup benches against post-#193 design and regenerate characterization report

### 2026-09-08

- **Issue #277** (closed): Dedupe record-assembly/write block: post_layout_common.py should share it with corner-run.py
- **PR #278**: refactor(sim): dedupe record-assembly/write block into sim_common.py
- **Issue #275** (closed): Dedupe klt draw subprocess call in met1_bus.py into layout_common.run_klt_json()
- **PR #276**: refactor: dedupe klt draw subprocess call in met1_bus.py into layout_common.run_klt_json()
- **Issue #270** (closed): Dedupe klt --format json subprocess call in render-record.py into layout_common.run_klt_json()
- **PR #274**: Dedupe klt --format json subprocess call in render-record.py into layout_common.run_klt_json()
- **Issue #214** (closed): Dedupe write_log() boilerplate across 3 sim/*/run_*.py scripts
- **Issue #272** (closed): Dedupe write_log() corner-log boilerplate into sim_common
- **PR #273**: refactor: dedupe write_log() corner-log boilerplate into sim_common
- **Issue #269** (closed): Dedupe klt --format json subprocess calls in measure_mim_overlay_feasibility.py into layout_common.run_klt_json()
- **PR #271**: refactor: dedupe klt --format json calls in measure_mim_overlay_feasibility.py

### 2026-09-07

- **Issue #267** (closed): sim_common.load_corner_run() re-execs corner-run.py every call: except cr.HarnessError silently misses errors from sim_common's own helpers
- **PR #268**: fix: make load_corner_run() idempotent to fix HarnessError class-identity bug
- **Issue #265** (closed): Dedupe ngspice-subprocess invocation in corner-run.py's run_corner() into sim_common
- **PR #266**: refactor: extract shared ngspice-invocation helper into sim_common
- **Issue #263** (closed): Dedupe git repo-state (sha/branch/dirty) block in render-record.py and routed_record.py
- **PR #264**: refactor: dedupe git repo-state block in render-record.py and routed_record.py
- **Issue #261** (closed): Dedupe ngspice-subprocess invocation in run_pnp_mismatch.py into sim_common.run_ngspice()
- **PR #262**: refactor: dedupe ngspice-subprocess invocation in run_pnp_mismatch.py
- **Issue #259** (closed): Remove duplicate git rev-parse subprocess call in measure_fixed_offset_variants.py
- **PR #260**: Dedupe git rev-parse HEAD subprocess call in measure_fixed_offset_variants.py
- **Issue #257** (closed): Dedupe klt --version subprocess call: render-record.py and routed_record.py
- **PR #258**: Dedupe klt --version subprocess call: render-record.py and routed_record.py
- **Issue #255** (closed): Remove unused git import in gen_bandgap_routed.py (leftover from #253/#254)
- **PR #256**: fix: remove unused git import in gen_bandgap_routed.py
- **Issue #253** (closed): Dedupe git() subprocess wrapper: gen_bandgap_routed.py and render-record.py
- **PR #254**: Dedupe git() subprocess wrapper: gen_bandgap_routed.py and render-record.py
- **Issue #251** (closed): Extract zero_detour() context manager + shared wall fixture in test_routed_flow_gates.py
- **PR #252**: Extract zero_detour() context manager + wall_bus() fixture in test_routed_flow_gates.py
