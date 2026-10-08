# sim/ — the simulation harness and its evidence records

This directory holds the reproducible xschem + ngspice + sky130 harness and the
results it produces. Two rules from the root `CLAUDE.md` shape everything here:

- **Verification is the product.** No claim without a testbench. Every recorded
  result carries the PVT corner matrix (−40/27/125 °C, ±10 % supply, process
  corners) unless the record states why a subset was used — the runner
  *enforces* that by refusing to write a subset record without a
  `--subset-reason`.
- **`sim/` is append-only evidence.** Records are never edited or deleted. A
  re-run — even one that corrects a mistake — mints a new record id; a
  correction points at what it replaces via a `Supersedes` field. The runner
  refuses to start if the record id it would mint already exists on disk.

The directory layout, record-id scheme and summary-record fields follow the
house convention established in the sibling `gf180-bandgap` repo, so the two
ports read as one evidence trail. Extensions specific to this harness (PDK
version pin, tool versions, machine-readable `.json` twin of each record,
corner-sensitivity check) are documented below.

### Block-level roll-up

[`design/block-characterization-report.md`](../design/block-characterization-report.md)
rolls every ratified spec row up into one current artifact (target / measured /
binding corner / verdict / evidence citation), plus the DRC/LVS/PVT/Monte
Carlo/post-layout verification-status summary and known blind spots (T1
checklist item 8). It is a snapshot, not a live view: per its own regeneration
rule, it goes stale the moment a new record lands under any `sim/*/records/`
or `layout/**/reports/` directory it cites, or a spec/DR changes — re-derive
its rows from the newest record on disk before trusting it, don't assume it
tracks `main` automatically.

### Draft-graded vs. ratified-graded records — read the claim text, not the date

The target spec was ratified on **2026-08-11** by
[DR-005](../spec/decision-records/DR-005-ratify-target-spec.md) (output
accuracy re-cast to ±2 % untrimmed / ±0.5 % trimmed) and its PSRR row amended
by [DR-006](../spec/decision-records/DR-006-psrr-frequency-qualification.md).
The benches that grade the untrimmed accuracy rows were only re-pointed at the
ratified bounds on **2026-08-16** (issue #177) — five days later.

**A record's date therefore does not tell you which spec it was graded
against; its own claim text does.** A record is *draft-graded* iff its
`**Claim**` line contains `Target specification (DRAFT)` or `PROVISIONAL
against the draft spec`, and *ratified-graded* iff that line cites DR-005 (and
DR-006 for the PSRR row). Grep the record rather than inferring from the
record id:

```bash
# every draft-graded record on disk, whatever its date
git grep -l "Target specification (DRAFT)\|PROVISIONAL against the draft spec" \
  -- 'sim/*/records/*.md'
```

Consequences worth stating explicitly:

- Every record dated **before 2026-08-11** is draft-graded (pre-ratification).
- The **13 records dated 2026-08-11 → 2026-08-16** that the grep above still
  returns are post-ratification *by date* but draft-graded *in fact* — they
  were emitted in the gap between DR-005 and the bench re-pointing. Do not
  read them as ratified-spec evidence.
- **No bench remains unconverted as of issue #279 (2026-09-10).** As of the
  2026-08-16 re-pointing, the post-layout wrappers `sim/line-regulation-post-layout/`,
  `sim/quiescent-current-post-layout/` and `sim/startup-time-post-layout/` each
  inherited its wrapped bench's re-pointed manifest but still had a draft-graded
  newest record on disk. `sim/line-regulation-post-layout/` was cleared by issue
  #193's same-day re-run; `sim/quiescent-current-post-layout/` and
  `sim/startup-time-post-layout/` are cleared by issue #279's re-run — each now has
  a ratified-graded newest record (citing DR-005, DR-006 where applicable). The grep
  above returns only historical records that are no longer the newest in their
  directory. (`sim/trim-range-monotonicity/` grades the **trimmed** claim under
  DR-002 and is outside #177's untrimmed scope; its runner still carries the draft
  sentence — unaffected by #279.)

Per the append-only rule, no draft-graded record is ever edited or deleted;
read them as draft-spec evidence and let a newer record carry the ratified
verdict.

---

## Quick start (cold machine)

```bash
# 1. install the pinned PDK (~1 min; see sim/pdk.json for the pin)
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b

# 2. sanity-check the toolchain and PDK resolution
python3 sim/bin/corner-run.py --print-env

# 3. run the harness smoke test over the full PVT matrix (45 points, ~1 min)
python3 sim/bin/corner-run.py sim/pdk-smoke
```

Prerequisites, all machine-level (not vendored here): `ngspice`, `xschem`,
`volare`, `python3` (3.9+, standard library only). Provisioning them on a dev
box is issue #17's scope; this harness only *verifies* they are present and
records the versions it used.

### Driving the tools by hand

```bash
source sim/bin/pdk-env.sh      # exports PDK_ROOT, PDK, SKY130_MODEL_LIB, XSCHEM_RCFILE
xschem --rcfile "$XSCHEM_RCFILE" sim/pdk-smoke/testbench/tb_pdk_smoke.sch
cp sim/spiceinit ./.spiceinit  # ngspice needs these settings to read PDK libs
```

`sim/bin/pdk-env.sh` is a thin wrapper around `corner-run.py --print-env`, so
interactive sessions and the runner resolve the PDK identically.

---

## How the harness is wired

| Piece | File | Role |
|---|---|---|
| PDK pin | `sim/pdk.json` | open_pdks commit, variant, model-library path, the process-corner names that actually exist in the PDK library |
| ngspice settings | `sim/spiceinit` | `ngbehavior=hsa` etc. required to read the sky130 libs; copied into the scratch run dir as `.spiceinit` |
| xschem config | `sim/xschemrc` | project-local rc that sources the PDK's own xschemrc (so `sky130_fd_pr/*.sym` resolves) and keeps generated netlists out of the tracked tree |
| corner runner | `sim/bin/corner-run.py` | netlist → deck → ngspice → parse → record |
| env helper | `sim/bin/pdk-env.sh` | `source` it for interactive xschem/ngspice work |
| experiment | `sim/<slug>/experiment.json` | what is being claimed, which corners, which measurements and their limits |

**PDK resolution order**: `$PDK_ROOT` → `volare path` → `default_pdk_root` from
`sim/pdk.json`; variant from `$PDK` → `variant` in `sim/pdk.json`. The runner
resolves the PDK directory symlink back to its volare version hash and
**refuses to run against a version other than the pin** unless
`--allow-pdk-mismatch` is passed — in which case the record says so. That is
what makes a record re-runnable months later.

**What the runner injects** (so one testbench serves the whole matrix): the
`.lib <models> <corner>` include, `.temp`, `.param vsup=<supply>`, `.option`s
from the manifest, and the `.control` block that runs the analyses, evaluates
each measurement expression into a `meas_<name>` vector and prints it. The
testbench schematic therefore contains no corner, no temperature, no numeric
supply and no analysis block.

**Per-corner artifacts**: each corner's `.log` embeds the exact deck that was
fed to ngspice (prefixed with `|`) plus raw stdout/stderr, so a record is
auditable without regenerating anything. Scratch decks and xschem output live
in the gitignored `sim/build/`; only the netlist snapshot, the per-corner logs
and the record are committed.

---

## Directory / naming convention

```
sim/
  README.md                          # this file
  pdk.json                           # PDK version pin
  spiceinit                          # ngspice init settings
  xschemrc                           # project-local xschem config
  bin/
    corner-run.py                    # PVT corner runner
    pdk-env.sh                       # `source` for interactive use
  build/                             # gitignored scratch (decks, xschem netlists)
  tests/                             # unit coverage for the evidence-minting
                                     # harnesses (run by `npm run check:ci`)
  <experiment-slug>/                 # e.g. pdk-smoke, output-voltage-tc, psrr-dc
    experiment.json                  # manifest: claim, corners, measurements, limits
    testbench/                       # xschem schematic(s) for this experiment
    netlist-snapshots/
      <record-id>.spice              # frozen netlist used for this record
    corners/
      <record-id>/
        <corner-id>.log              # deck + raw ngspice output per PVT point
    records/
      <record-id>.md                 # append-only summary record (human)
      <record-id>.json               # same record, machine-readable
```

- **`<experiment-slug>`** — kebab-case name for the claim under test
  (`output-voltage-tc`, `psrr-dc`, `startup`, `mc-untrimmed`, …). One directory
  per distinct claim, not per run.
- **`<record-id>`** — `<YYYYMMDD>-<HHMMSS>-<short-git-sha>` in UTC, e.g.
  `20260730-032150-080179e`. The same id ties together the netlist snapshot,
  the per-corner logs and both record files for one run. Re-runs mint a new id.
- **`<corner-id>`** — `<process>_<temp>c_<supply>v`, e.g. `ss_-40c_2.97v`,
  `tt_27c_3.30v`, `ff_125c_3.63v`.
- **`testbench/`** is not versioned per record. If a testbench change could
  affect comparability across records, say so in the new record (the frozen
  netlist snapshot is what actually pins what ran).

## Summary record fields

Each run writes `records/<record-id>.md` (and a `.json` twin with every parsed
number, limit and verdict, for tooling):

| Field | Meaning |
|---|---|
| Record ID | matches the filename, the snapshot and the `corners/` subdirectory |
| Experiment | slug + title from the manifest |
| Claim | which spec parameter/line this substantiates (`spec/<file>.md#<anchor>` once specs are ratified — see issue #1) |
| Netlist provenance | `schematic` (`design/…`, `sim/…/testbench/…`) or `extracted` (post-layout, `layout/…`) — required so post-layout re-runs are distinguishable |
| PDK | variant + open_pdks commit actually used, whether it matches `sim/pdk.json`, and the model library path |
| Tools | ngspice / xschem / OS / python versions used |
| Jobs | how many corners ran concurrently (`--jobs`/`-j`; `1` = serial, today's default) |
| Repo state | short sha, branch, and whether the working tree was dirty at run time |
| Corner matrix run | the (process, temperature, supply) points actually executed; must be the full PVT matrix unless a subset reason is recorded |
| Statistical convention | N samples and sigma level for distribution claims (e.g. Monte Carlo mismatch); `N/A` for corner-matrix claims |
| Result | per-corner pass/fail with measured values, plus an overall verdict |
| Links | testbench, manifest, netlist snapshot, raw logs, json record |
| Timestamp / author | UTC timestamp and who (human or agent) ran it |
| Supersedes | prior `<record-id>` this corrects or re-runs (post-layout deltas included); `(none)` otherwise |

### Append-only rule

`records/*` files are never edited or deleted after creation — this applies
even to typo fixes, because the append-only guarantee is the whole point of an
evidence trail. Corrections mint a new record that references the prior one via
**Supersedes**. This mirrors the status/supersession language used for `spec/`
decision records, so both conventions read as one house style.

**Re-minting a derived envelope.** A record's *derived* artifacts — a `klt
yield` envelope emitted from the record's own corner logs, say — are records
too, and the rule is the same: when one has to be regenerated (a harness bug
baked something wrong into it), it is re-minted under a **new** record id
beside the original, never rewritten. `sim/monte-carlo-untrimmed/
emit_klt_yield.py --envelope-id <new-id>` is that mode: it reads the source
record's committed corner logs, writes `<new-id>-klt-yield{-input}.json` plus a
`<new-id>-klt-yield.md` note carrying the **Supersedes** line and the reason,
leaves the source record's own `.json`/`.md` untouched, and refuses outright if
any of the three target files already exists. Worked example:
`records/20260923-062524-1e38c62-klt-yield.md` (issue #288 — the superseded
envelope had leaked an absolute, machine-local `samples` path).

**Provenance hygiene applies to what a harness writes, not only to what a
human writes.** Repo-relative paths only; an external input is pinned by
identity (name/version/`content_hash`), never by its location on one machine.
The full rule is `signoff/design-evidence-tiers.md` → "Provenance hygiene in
evidence records"; `sim/tests/` holds the checks that keep committed records
honest about it.

---

## Writing a new experiment

1. `mkdir -p sim/<slug>/{testbench,netlist-snapshots,corners,records}`
2. Draw the testbench in xschem (`--rcfile sim/xschemrc`). Leave out the
   corner include, `.temp`, the numeric supply (use `'vsup'`) and any
   `.control` block — the runner owns those. Name the nets you intend to
   measure; connectivity by `lab_pin` label is fine.
3. Write `sim/<slug>/experiment.json`:

```json
{
  "slug": "output-voltage-tc",
  "title": "…",
  "claim": "spec/bandgap.md#output-voltage-tc — …",
  "provenance": "schematic",
  "provenance_source": "sim/output-voltage-tc/testbench/tb_vref_tc.sch",
  "schematic": "testbench/tb_vref_tc.sch",
  "statistical_convention": "N/A (corner-matrix claim)",
  "corners": {
    "process": ["tt", "ss", "ff", "sf", "fs"],
    "temperature_c": [-40, 27, 125],
    "supply_v": [2.97, 3.3, 3.63]
  },
  "quick_subset": [["tt", 27, 3.3]],
  "deck": { "options": ["wnflag=1"], "params": {}, "analyses": ["op"] },
  "measurements": [
    { "name": "vref", "expr": "v(vref)", "unit": "V", "min": 1.188, "max": 1.212 }
  ],
  "spread_checks": []
}
```

   - `analyses` is a list of ngspice `.control` commands (`op`, `dc …`,
     `tran …`) run before measurements are evaluated.
   - `measurements[].expr` is any ngspice expression valid after those
     analyses; `min`/`max` are the pass window (omit either for one-sided).
   - `spread_checks` assert that a measurement *moves* across the matrix — a
     cheap guard against a harness that silently stops applying corners.
   - Process-corner names must appear in `sim/pdk.json` `process_corners`
     (which lists what the PDK's ngspice library really defines: `tt`, `ss`,
     `ff`, `sf`, `fs`; resistor/cap skew, `*_mm` mismatch and `mc` sections
     also exist in the library and can be added there once used).
4. Run it: `python3 sim/bin/corner-run.py sim/<slug>`
5. Commit the produced record, netlist snapshot and per-corner logs. (The
   root `.gitignore` ignores `*.log` globally but un-ignores
   `sim/*/corners/**/*.log`, which is committed evidence.)

### Experiments that do not go through the corner runner

`corner-run.py` runs **one deterministic deck per PVT point**. A claim about a
*distribution* — local mismatch, circuit-level Monte Carlo — needs the same deck
resampled N times at a single process point, which is a different axis. Those
experiments ship a bespoke run script next to their testbench instead of an
`experiment.json`:

| Experiment | Script | Why not the corner runner |
|---|---|---|
| `sim/pnp-mismatch/` | `run_pnp_mismatch.py` | N = 300 Monte Carlo samples per point; the PDK's `MC_MM_SWITCH` mismatch terms are re-drawn on each ngspice `reset` |
| `sim/error-amp-offset-mc/` | `run_amp_offset_mc.py` | N = 300 Monte Carlo samples per point of the error amplifier's input-referred offset; same `MC_MM_SWITCH` resampling-per-`reset` need as `sim/pnp-mismatch/` |
| `sim/monte-carlo-untrimmed/` | `run_mc_untrimmed.py` | N = 300 Monte Carlo samples per point, wrapping `sim/output-voltage-tc`'s own bench unmodified to report the untrimmed ±2 % claim's σ/yield with a PNP/resistor/amp-mirror contributor breakdown (issue #12); isolates each family by zeroing the PDK's own `sw_mm_*` coefficients for the other two |
| `sim/trim-range-monotonicity/` | `run_trim_sweep.py` | Sweeps `design/bandgap_core.sch`'s own `n_r2_trim` trim-code parameter (issue #13); wraps `sim/output-voltage-tc`'s bench unmodified but needs a different value of a `.subckt`-internal `L=` parameter per run, which the corner runner's manifest-level `deck.params` cannot override (they land before the netlisted body; SPICE resolves that expression at `.subckt` definition time) — this script edits the netlisted body's own default line in place instead |
| `sim/res-array-resize/` | `run_res_array_resize.py` | Re-derives and PVT-verifies `n_r1`/`n_r2` against the routed layout's real *chained*-array R1/R2A/R2B topology (issue #99, DR-003 follow-up); a *body-substitution* claim, not a `deck.params` override — it replaces each single `res_high_po` device line with a chain of separately-instantiated unit devices at the layout's own decomposition, parameterized on arbitrary `n_r1`/`n_r2`/trim code, extending `sim/res-array-head-resistance`'s Phase B pattern |
| `sim/trim-lsb-chained/` | `run_trim_lsb_chained.py` | Re-derives DR-002's monotonic/span/LSB trim criteria against the chained fine-trim topology at the adopted `n_r1=7`/`n_r2=50` sizing, and verifies a fine-unit-length (`r_lseg_trim`) fix (issue #106, DR-002 revision); extends `sim/res-array-resize`'s body-substitution pattern with one more axis (candidate fine-trim unit length) it did not sweep |
| `sim/output-voltage-tc-post-layout/` | `run_post_layout_vref_tc.py` | Post-layout (`provenance: extracted`) re-run of `sim/output-voltage-tc`'s claim (issue #16). The DUT body comes from `klt extract --parasitics` on the routed `layout/bandgap-core/` GDS, translated to simulatable sky130 vendor models (`sim/bin/post_layout_common.py` module docstring), which xschem-netlisting a schematic cannot produce. Wraps `sim/output-voltage-tc/testbench/tb_vref_tc.sch` unmodified, swapping the netlisted `.subckt bandgap_core`/`.subckt error_amp` blocks for the extracted layout. Details: [`output-voltage-tc-post-layout/README.md`](output-voltage-tc-post-layout/README.md). |
| `sim/quiescent-current-post-layout/` | `run_post_layout_iq.py` | Post-layout re-run of `sim/quiescent-current`'s Iq claim (issue #16): same extracted-layout DUT body as the row above, wrapping `sim/quiescent-current/testbench/tb_vref_iq.sch` unmodified, over the full 45-point matrix. Its `README.md` carries the divergence finding issue #16 requires. Details: [`quiescent-current-post-layout/README.md`](quiescent-current-post-layout/README.md). |
| `sim/psrr-dc-post-layout/` | `run_post_layout_psrr.py` | Post-layout re-run of `sim/psrr-dc`'s PSRR claim (issue #16): same extracted-layout DUT body, wrapping `sim/psrr-dc/testbench/tb_vref_psrr.sch` unmodified, over the full 45-point matrix (the AC sweep lives inside the deck). Its `README.md` carries the divergence finding issue #16 requires. Details: [`psrr-dc-post-layout/README.md`](psrr-dc-post-layout/README.md). |
| `sim/line-regulation-post-layout/` | `run_post_layout_linereg.py` | Post-layout re-run of `sim/line-regulation`'s large-signal DC claim (issue #16): same extracted-layout DUT body, wrapping `sim/line-regulation/testbench/tb_vref_linereg.sch` unmodified. Runs the same 15-point subset (process x temperature, supply collapsed) as the schematic-level bench, via the shared runner's `supply_override` (symmetric to `output-voltage-tc-post-layout`'s `temp_override`). Its `README.md` carries the divergence findings issue #16 requires and the same-sizing schematic baseline they are measured against. Details: [`line-regulation-post-layout/README.md`](line-regulation-post-layout/README.md). |
| `sim/startup-time-post-layout/` | `run_post_layout_startup_time.py` | Post-layout re-run of `sim/startup-time`'s supply-ramp startup-time claim (issue #16), same extracted-layout DUT body, wrapping `sim/startup-time/testbench/tb_vref_startup.sch` unmodified, over the full 45-point matrix. The composed cell draws `design/startup_injector.sch` (issue #285), so the post-layout DUT is core+injector while the schematic-level bench it wraps stays the bare core; the two halves measure different circuits on purpose. Verdict and the history of earlier record shapes are in its `README.md`. Details: [`startup-time-post-layout/README.md`](startup-time-post-layout/README.md). |
| `sim/startup-stability-post-layout/` | `run_post_layout_startup_stability.py` | Restructured by issue #299: does not wrap its schematic-level sibling. It carries its own `testbench/tb_startup_stability_pl.sch` and `experiment.json`; the DUT is the composed cell alone (`design/bandgap_core.sym` instances only), because the extracted body supplies the injector itself. Measurements that need a bare-core control instance are not expressible on a drawn monolithic cell and stay at schematic level; a bound plus a precondition replaces them, and `post_layout_common.require_layout_draws_injector()` refuses the run against a layout record whose LVS reference netlist does not state the injector's six device cards (`MMPC1`, `MMPC2`, `MMNS`, `MMNI`, `MMNC`, `QQS`). Newest evidence is the latest entry under `sim/startup-stability-post-layout/records/`; the pre-#299 shape and its findings are in the bench `README.md`. Details: [`startup-stability-post-layout/README.md`](startup-stability-post-layout/README.md). |
| `sim/startup-ramp-post-layout/` | `run_post_layout_startup_ramp.py` | Restructured by issue #299, same shape and same `require_layout_draws_injector()` precondition as the row above: own `testbench/tb_startup_ramp_pl.sch` (each `design/bandgap_core.sym` alone, no separate injector instance) and own `experiment.json`, which drops the bare-core-control-copy measurements. Those claims stay at schematic level. The numerical stand-in for the control is `t_start_g`: a cell with no working injector never produces its `v(VREFG)` crossing, so the corner fails outright. Newest evidence is the latest entry under `sim/startup-ramp-post-layout/records/`; verdicts and the pre-#299 shape are in the bench `README.md`. Details: [`startup-ramp-post-layout/README.md`](startup-ramp-post-layout/README.md). |
| `sim/psrr-injector-attribution/` | `run_psrr_injector_attribution.py` | Device-branch attribution, not a spec claim (issue #306, follow-up to #300): answers which device inside `design/startup_injector.sch` dominates the PSRR collapse `sim/psrr-dc-with-injector` records. It needs its own script because the axis is body variant x corner (five bodies, each cutting one GDRV-touching branch, over the full 45-point matrix), and because the circuit under test is the committed netlist snapshot `sim/psrr-dc-with-injector/netlist-snapshots/20260923-124813-af9ff1e.spice`, not a fresh netlist of `design/`, so a later design fix cannot silently re-point the attribution. Measurement expressions, limits and solver options are byte-identical to `sim/psrr-dc-with-injector/experiment.json`'s. Its checks are attribution assertions, not spec verdicts. Newest evidence is the latest entry under `sim/psrr-injector-attribution/records/`; the findings are in its `README.md`. Details: [`psrr-injector-attribution/README.md`](psrr-injector-attribution/README.md). |

`startup-stability-post-layout` and `startup-ramp-post-layout` instantiate `design/bandgap_core.sym` alone; `build_extracted_body()` and its `.subckt`-scoped `strip_schematic_subckts()` (only the NAMED blocks are removed) are shared by every post-layout bench. The history of how those two benches' DUT shape changed (issue #285/#299) is in [`startup-stability-post-layout/README.md`](startup-stability-post-layout/README.md).

### Issue #16's `sim/monte-carlo-untrimmed` (#12) conditional: judgment call

Issue #16's Acceptance Criteria make `sim/monte-carlo-untrimmed`'s (#12)
post-layout re-run **conditional**: only if extraction "meaningfully shifts
the operating point or the trim range," and the AC explicitly requires that
judgment to be documented, not skipped silently. `sim/monte-carlo-untrimmed`
wraps `sim/output-voltage-tc`'s bench unchanged and reports the untrimmed
±2 % `vref` claim's mismatch-driven σ/yield, so the question this conditional
actually asks is: does the *extraction* (not any other change already
committed to `design/bandgap_core.sch`) move `vref`'s nominal operating point
or the resistor ratio the trim ladder walks enough to change that
distribution's story?

**Judgment: no — the extraction-specific contribution is not meaningful, and
`sim/monte-carlo-untrimmed` does not need a post-layout re-run for issue
#16.** The evidence, all already measured and committed by the five
completed post-layout benches above:

- `sim/line-regulation-post-layout/README.md`'s nodal-analysis attribution is
  the most directly on-point data available: separating the extracted
  netlist's 143 resistor devices from its 813 `klt extract --parasitics`
  star-R elements shows `K = R2/R1` — the ratio that sets `vref`'s nominal
  operating point and that the trim ladder walks — moves by **−0.2 %** from
  parasitics alone (7.6301 drawn-only → 7.6148 extracted). A −0.2 % shift on
  the quantity a mismatch-driven yield/sigma claim is most sensitive to is
  far below anything that would change which corners pass or fail a ±2 %
  window.
- The much larger shifts the other benches document (`sim/quiescent-current-post-layout/`'s
  −35.8 % Iq, `sim/psrr-dc-post-layout/`'s −4.05 dB PSRR,
  `sim/line-regulation-post-layout/`'s +29.6 mV `vref_nom`) are, per those
  same README's own attributions, either (a) the **drawn chained-array
  topology** — a `design/bandgap_core.sch` change from the DR-003 resize
  (issue #99) that already exists at schematic level, independent of
  extraction — or (b) an **AC small-signal** effect (`psrr_dc`/`psrr_1k`)
  that a DC mismatch/yield claim does not probe. Neither is the extraction
  effect this conditional is asking about.
- `startup-ramp-post-layout` and `startup-stability-post-layout` (this
  increment) both diverge from their schematic baselines by margins
  (a handful of near-threshold `vref_spread` corners, dvref +15.5 mV vs
  +8.70 mV) that are consistent in kind and scale with the resistance-network
  effects the other benches already attribute to the same extraction — no
  new mechanism, and nothing that touches `vref`'s nominal value or the trim
  ladder directly. (**Restated 2026-09-24, issue #299**: both benches were
  restructured onto the all-extracted composed cell, so `dvref` is no longer
  measured post-layout at all and the `vref_spread` comparison is no longer a
  clean extraction delta — the DUT construction and the layout record moved
  together. The conclusion this bullet draws is unaffected: neither bench's
  post-layout record touches `vref`'s nominal value or the trim ladder. See
  each bench's own `README.md` addendum.)

**What this judgment call did not close, at the time it was written.**
`sim/monte-carlo-untrimmed`'s newest record at the time
(`20260803-142259-544cc5e`) predated the DR-003 resize (`n_r2` 54→50, later
51) the same way the pre-this-increment
`sim/startup-ramp`/`sim/startup-stability`/`sim/line-regulation` schematic
records did — a schematic-level re-run at the current chained-array sizing
was an open, pre-existing gap, orthogonal to issue #16's scope (a
resize-currency gap, not a layout/extraction verification gap) and not
created or worsened by that increment. **Closed by issue #180**:
`sim/monte-carlo-untrimmed/records/20260817-121131-d7d85b6` re-runs this
same bench against the current chained-array design (`n_r2=51`, issue #178)
and the ratified ±2 % window (DR-005), superseding `20260816-091855-69a8867`
(issue #177's re-point, itself still `n_r2=50`) in turn. This paragraph is
kept for the historical record of the judgment call's own scope statement,
not because the gap it named is still open.

For any future post-layout bench whose DUT is fully covered by the existing
all-extracted (or, per the two rows above, mixed-provenance) path, the whole
run — extraction, device translation, body substitution, record minting,
corner loop, record schema — is
`sim/bin/post_layout_common.run_post_layout_experiment()`; a new bench is a
~40-line file declaring its slug, the schematic-level experiment it wraps,
that experiment's testbench, and its claim sentence (see
`sim/quiescent-current-post-layout/run_post_layout_iq.py`, the shortest
example). Only pass `temp_override`/`supply_override`/`subset_reason` if the
bench's own deck sweeps that axis internally.

Such a script still has to behave like the harness:

- reuse `sim/bin/corner-run.py`'s PDK resolution and **pin enforcement**
  (import it; don't re-implement it), so a record is reproducible the same way;
- mint the same `<record-id>`, refuse to overwrite anything under
  `sim/<slug>/`, and write **both** the `.md` and the `.json` twin;
- commit the netlist snapshot and one raw log per ngspice invocation, with the
  exact deck embedded in the log;
- state the process/temperature/supply subset justification **in the record
  body**. Since issue #284 the shared runner *does* accept
  `--process` / `--temp` / `--supply` / `--subset-reason` on this path too, and
  enforces the reason exactly as `corner-run.py` does — but only for an axis the
  bench's own script leaves open. An axis the script pins deliberately (because
  the deck sweeps it internally, or because the bench's acceptance criteria scope
  it to worst corners) is refused from the command line with an error naming the
  pin, so a per-invocation override can never quietly undo a pin whose reason
  lives in the script. Anything the flags do not cover is still a prose
  obligation;
- carry a **control point that must fail if the mechanism under test is not
  actually active** (e.g. `sim/pnp-mismatch/` re-runs its deck on the plain
  `tt` section, where every σ must come back exactly 0). A Monte Carlo harness
  that silently sampled nothing would otherwise produce a plausible record.

### Runner options

| Flag | Effect |
|---|---|
| `--print-env` | print PDK env exports and exit |
| `--process tt,ss` / `--temp 27` / `--supply 3.3` | override a matrix axis (marks the run a subset). A **negative** temperature needs the `=` form, `--temp=-40,125` — a bare `--temp -40` is read by argparse as a missing argument followed by an unknown option |
| `--quick` | run the manifest's `quick_subset` only |
| `--subset-reason "…"` | **required** for any subset; recorded verbatim |
| `--supersedes <record-id>` | record which prior record this replaces |
| `--author`, `--timeout` | record author (default `git config user.email`), per-corner ngspice timeout (default 300 s locally, 10800 s with `--backend batch`) |
| `--backend local\|batch` | where corners run (default `local`). `batch` sends the matrix to the Spot batch fleet through `klt sim --backend batch`; enabled for `startup-stability` only. See "Batch backend" below. A failed submission is an error, never a local fallback |
| `--batch-capacity-wait-s N`, `--batch-runner-version-check enforce\|warn` | batch only: how long to wait out a Spot capacity refusal per submission (default 3600), and klt's runner/client version-skew policy (default `enforce`; leave it) |
| `-j N`, `--jobs N` | run up to `N` corners concurrently (default: `1`, serial -- today's unchanged behavior). Each corner is an independent `ngspice` process with its own scratch deck and its own `--timeout`, enforced per-process regardless of `N`; corner results are always written into the record in matrix order, never completion order. Recorded in the written record's `jobs` field |
| `--allow-pdk-mismatch` | run against a non-pinned PDK; the record flags it |
| `--dry-run` | netlist, print the corner list and one deck, write nothing under `sim/<slug>/` |

Exit status: `0` all checks passed, `2` a record was written but something
failed, `1` harness/setup error (no record written).

### Batch backend (`--backend batch`, issue #320)

`startup-stability`'s 45-corner matrix is dominated by a 251-point `.dc valpha`
sweep with `gmin` homotopy stepping: measured at roughly 114 s fixed + 25 s per
sweep point on the AWS sweep hosts, i.e. ~1.8 h for one corner and a 17-33 h
serial matrix (issue #320). That must not run on a shared dispatch host, so
the runner can hand the matrix to the Spot batch fleet:

```bash
# on a dispatch host: only the klt client runs locally (xschem netlisting + S3 put/get + polling)
sim/bin/corner-run.py sim/startup-stability --backend batch --supersedes <newest-stock-record-id>
sim/bin/corner-run.py sim/startup-stability --backend batch --dry-run   # print the requests, submit nothing
```

What it does, and what it deliberately does not change:

- **Unchanged**: the xschem netlist, the pinned model library (`sim/pdk.json`),
  the `.param vsup` / `.option wnflag=1` preamble, `sim/spiceinit` (sent as
  `options.ngspice_init`), the exact `dc valpha 0 1 0.004` sweep (251 points,
  never partitioned or shortened), every measurement expression and limit, and
  the spread checks. Verdicts are graded by the same `evaluate_measurements()`
  the local runner uses, not by klt's own pass/fail.
- **Request shape**: one `klt sim` request per supply voltage (3 jobs x 15
  process/temperature corners, submitted concurrently). `klt sim` applies
  `corners.supply_v` with ngspice `alter`, which cannot change the `.param vsup`
  this bench's B-sources multiply into the swept forcing voltage (klayout-tools#2725), so
  `vsup` is pinned in each request's netlist instead. The `let ifsu = ...` /
  `let ssu = ...` intermediates of the local deck are inlined into each
  measurement (klt accepts one analysis plus scalar `expr` measurements); a unit
  test runs both forms through ngspice and requires identical output, and
  another compares klt's own generated deck against `build_deck()` (allowed
  differences: `.lib` quoting, `.temp -40` vs `-40.0`, measurement `let`
  naming/inlining).
- **Records** (`records/`, `corners/`, `netlist-snapshots/`, append-only as
  always) additionally carry an `Execution` block: fleet job ids, klt client
  version, remote ngspice version, instance type/AMI, per-corner remote engine
  time, per-job fleet time, submit-to-collect wall time, and the queue/
  provisioning/transfer overhead (submit-to-collect wall minus the fleet's own
  job time). `corners/<record-id>/` holds each corner's retained deck+log and,
  per supply, the exact `request.json`, `netlist.cir` and `klt-report.json`.
  Per-corner `elapsed_s` is the remote engine wall clock; it is never a
  dispatch-call duration.
- **Failure semantics**: a corner is PASS only if klt reports no error
  diagnostic, no timeout, and every measurement is present and in limits.
  The `timeout` diagnostic (per-corner budget) and the fleet job's own
  timeout are recorded as TIMEOUT; other simulator errors keep their klt
  diagnostic text. **`klt sim` does not return the engine's exit code or a
  killing signal** (klayout-tools#2848), so those fields are `null` for batch
  corners and an external kill reads as a missing measurement, not as
  "SIGKILL". Missing, duplicate or unexpected corners, a remote model library
  whose sha256 differs from the pinned local one, and runner/client klt skew
  all land in the record's `overall_blockers` and force `Overall: FAIL`.
- **No local fallback**: if submission or collection fails, or a fleet job dies
  before simulating anything (e.g. the runner-image klt is older than the
  client), the runner exits 1 with the job ids and writes no record. It never
  runs a corner locally.
- **Prerequisites**: klt with the `batch` backend; the `batch-runner-submit`
  AWS profile; `KLT_BATCH_PROVISION_SCRIPT` pointing at 2am's
  `infra/aws/batch-fleet-provision.sh` (the bucket comes from the fleet config
  beside it). The model library is resolved **on the fleet image**
  (`models.pdk: sky130A`), not shipped with the job, so the runner compares klt's
  reported `models_lib_sha256` against the sha256 of the pinned local
  `libs.tech/combined/sky130.lib.spice` and blocks PASS on any difference.
  The image's klt must be at least the client's (klt enforces exact equality) and
  must support `measurements[].expr`, `options.ngspice_init` and the generated `save all`
  (klayout-tools#2533, #2520, #2521).

**Status (2026-10-08): the live 45-corner run has NOT been completed.** The
current fleet image pins klt `0.5.0` (2am `batch-image-pins.env`), which is
older than every batch-capable client and lacks `expr` measurements,
`ngspice_init` and `save all`. Three jobs (`klt-sim-0f561d9a9bf6`,
`klt-sim-7c9d083c37df`, `klt-sim-da5df48657e7`) were submitted and exited 87 in
under 10 s with `batch_runner_version_mismatch` before any simulation; the
runner reported the infrastructure fault and wrote no record. Waiving the check
(`--batch-runner-version-check warn`) would not help: `klt 0.5.0` rejects
this request outright. Unblocked by 2am#2193 (image klt pin bump). Until then
no batch timings or numerical comparison against
`20260909-232410-e8e2e46` exist; do not infer a speed-up from the fleet.

---

## `pdk-smoke` — the harness's own testbench

`sim/pdk-smoke/` is not a spec claim. A 1 MΩ resistor biases a diode-connected
sky130 `nfet_g5v0d10v5` (the 5 V I/O device family the 3.3 V supply implies)
and the runner measures `vgs` and the supply current. Both quantities are
strongly process- and temperature-dependent, so this experiment proves four
things at once: the PDK models load, xschem netlists headlessly, ngspice parses
the deck, and the corner/temperature/supply knobs actually reach the
simulator (asserted by the `vgs` spread check, not just eyeballed).

Keep it green: it is the first thing to run when a testbench misbehaves, to
tell "my circuit is wrong" apart from "my harness is broken".
