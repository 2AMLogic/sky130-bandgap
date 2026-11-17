# Work Log Archive — 2026-09

Sections moved byte-for-byte from [WORK_LOG.md](../WORK_LOG.md) by `loom-daemon work-docs archive`.

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
