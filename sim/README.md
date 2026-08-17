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
- The **still-unconverted benches** as of the 2026-08-16 re-pointing are the
  post-layout wrappers `sim/line-regulation-post-layout/`,
  `sim/quiescent-current-post-layout/` and `sim/startup-time-post-layout/`:
  each inherits its wrapped bench's re-pointed manifest, so its *next* record
  will be ratified-graded, but the newest record on disk today predates the
  re-point and is draft-graded. (`sim/trim-range-monotonicity/` grades the
  **trimmed** claim under DR-002 and is outside #177's untrimmed scope; its
  runner still carries the draft sentence.)

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
| `sim/output-voltage-tc-post-layout/` | `run_post_layout_vref_tc.py` | **Post-layout (`provenance: extracted`) re-run of `sim/output-voltage-tc`'s claim (issue #16)** against the routed, LVS-clean `layout/bandgap-core/` GDS (issue #62) instead of `design/bandgap_core.sch` — the DUT body is not something xschem-netlisting a schematic can produce, since it comes from `klt extract --parasitics` (real per-net routing RC) with its generic LVS device-class placeholders translated to simulatable sky130 vendor models; see `sim/bin/post_layout_common.py`'s module docstring for the full translation methodology (including a discovered, worked-around ngspice/sky130-BSIM-binning unit-suffix quirk) and `sim/output-voltage-tc-post-layout/records/` for the evidence. Wraps `sim/output-voltage-tc/testbench/tb_vref_tc.sch` unmodified (same body-substitution convention as the two rows above), swapping the netlisted `.subckt bandgap_core`/`.subckt error_amp` blocks for the translated, extracted layout instead of a resistor-array edit |
| `sim/quiescent-current-post-layout/` | `run_post_layout_iq.py` | **Post-layout (`provenance: extracted`) re-run of `sim/quiescent-current`'s Iq claim (issue #16)**, same extracted-layout DUT body as the row above, wrapping `sim/quiescent-current/testbench/tb_vref_iq.sch` unmodified. Runs the FULL 45-point matrix (nothing swept inside the deck, so no axis is collapsed). Its `README.md` carries the divergence finding required by issue #16 — post-layout Iq is 35.8 % below the schematic-level record, attributed to R1 growing 55 % (the drawn chained array's per-unit head resistance, plus a `klt extract --parasitics` poly double count filed as klayout-tools#800) |
| `sim/psrr-dc-post-layout/` | `run_post_layout_psrr.py` | **Post-layout (`provenance: extracted`) re-run of `sim/psrr-dc`'s PSRR claim (issue #16)**, same extracted-layout DUT body as the two rows above, wrapping `sim/psrr-dc/testbench/tb_vref_psrr.sch` unmodified. Runs the FULL 45-point matrix (the AC sweep lives entirely inside the deck, so no PVT axis is collapsed). Its `README.md` carries the divergence finding required by issue #16 — post-layout `psrr_band_min`/`psrr_1k` (the DC-1 kHz band floor, issue #127) drops by a tight, near-constant 4.05 dB ± 0.36 dB across every one of the 45 corners regardless of process/temperature/supply, flipping 34/45 corners from PASS to FAIL against the ratified > 60 dB floor (schematic-level margin was already thin, 62.65-66.73 dB). Attributed to the extracted VDD/VSS-path parasitics sitting directly in the small-signal supply-to-VREF transfer function this bench measures — unlike Iq, where the same parasitic network is only a second-order bias-point effect — though the finding does not isolate which specific net's R or C in the shared 813 R + 151 C snapshot dominates |
| `sim/line-regulation-post-layout/` | `run_post_layout_linereg.py` | **Post-layout (`provenance: extracted`) re-run of `sim/line-regulation`'s large-signal DC line-regulation claim (issue #16)**, same extracted-layout DUT body as the three rows above, wrapping `sim/line-regulation/testbench/tb_vref_linereg.sch` unmodified. Runs the SAME 15-point subset (process x temperature in full, supply collapsed) `sim/line-regulation`'s own schematic-level records use, via the shared runner's new `supply_override` (symmetric to `output-voltage-tc-post-layout`'s `temp_override`, added by this bench since the collapsed axis here is supply, not temperature). `Overall: PASS`, 15/15, ~755x margin to the 24 mV limit. Its `README.md` carries the two divergence findings required by issue #16, measured against a NEW same-sizing schematic-level baseline appended alongside it (`sim/line-regulation/records/20260812-014944-9a2360a`, at the adopted `n_r1=7`/`n_r2=50`; the newest pre-existing schematic-level record is at the superseded `n_r2=54`, which conflates the extraction with the resize on exactly the quantity the second finding is about). They point in opposite directions: (1) the line-regulation quantity degrades — shift 1.46x larger, informational `line_psrr_db` down a mean 2.57 dB, though with 3.9 dB corner-to-corner scatter, so it is a directional but much blunter corroboration of `psrr-dc-post-layout`'s tight -4.05 dB, never threatening the 755x margin; (2) `vref_nom` rises +29.6 mV and flips the OVERALL verdict from FAIL (schematic, on its 1.14 V sanity floor at all five 125 degC corners) to PASS. That rise is accounted for to within 2 mV at every corner by `K = R2/R1` rising 6.944 -> 7.630, and separating the snapshot's 143 resistor devices from its 813 parasitic elements shows it is the DRAWN chained array's per-unit head resistance that does it, NOT the parasitics (which move K by -0.2 %) — a different mechanism from the same extraction than the Iq row above reports |
| `sim/startup-time-post-layout/` | `run_post_layout_startup_time.py` | **Post-layout (`provenance: extracted`) re-run of `sim/startup-time`'s supply-ramp startup-time claim (issue #16)**, same extracted-layout DUT body as the four rows above, wrapping `sim/startup-time/testbench/tb_vref_startup.sch` unmodified. Runs the FULL 45-point matrix (nothing swept inside the deck, so no axis is collapsed) — the LAST of the five spec lines issue #16's "full #11 testbench suite" Acceptance Criteria bullet enumerates. `Overall: FAIL`, 45/45, but this is the **same pre-existing, expected FAIL** `sim/startup-time`'s own schematic-level record already documents: the routed layout this bench measures is the bare core (`layout/bandgap-core/` composes core + amplifier only; `design/startup_injector.sch`, issue #10, has no layout yet), so it lands in the same degenerate zero-current state the bare core does at schematic level too — `vref_final`/`gdrv_final` track the schematic-level record within ~1 % at every one of the 45 corners, confirming extraction did not introduce a *new* divergence here, just reproduced the known no-injector limitation on the extracted netlist |
| `sim/startup-stability-post-layout/` | `run_post_layout_startup_stability.py` | **Post-layout (`provenance: extracted`) re-run of `sim/startup-stability`'s degenerate-state / single-equilibrium claim (issue #16, the first of the two remaining "#10 startup/degenerate-state checks" increments)** — a MIXED-provenance DUT, not all-extracted like the six rows above: the extracted, translated `bandgap_core` swaps in for every `design/bandgap_core.sym` instance, but `design/startup_injector.sch` stays netlisted unmodified since it has no layout yet (`layout/bandgap-core/` composes core + amplifier only). Worst-corner 8-point SUBSET (process in {ff, ss} x temperature in {-40, 125} C x supply in {2.97, 3.63} V — issue #16's Acceptance Criteria phrase this bullet "at worst corners", unlike the full-matrix "#11 testbench suite" bullet). `Overall: PASS`, 8/8 — exactly one DC operating point at every corner, the degenerate zero-current state actively driven away from by microamps. Its own worst injector-attach cost (`dvref`) is +15.5 mV at `ff/125 C/3.63 V`, well inside the bench's ±20 mV bound but nearly double the schematic-level design's own +8.70 mV worst case (record `20260803-204236-f41373d`) — a real, documented divergence, see its `README.md`. This pair of benches is also where a `sim/bin/post_layout_common.py` `strip_schematic_subckts()` bug was found and fixed: a lazy-wildcard header-matching gap could let stripping `error_amp` collaterally delete the `startup_injector` block sandwiched between it and `bandgap_core` in netlisting order — see that function's docstring |
| `sim/startup-ramp-post-layout/` | `run_post_layout_startup_ramp.py` | **Post-layout (`provenance: extracted`) re-run of `sim/startup-ramp`'s supply-ramp startup-TIME claim (issue #16, the second of the two remaining "#10 startup/degenerate-state checks" increments)** — the same MIXED-provenance DUT as the row above (extracted core, schematic-netlisted injector). Runs the FULL 45-point matrix, not a worst-corner subset: unlike `startup-stability`'s heavy DC-sweep deck, a single transient corner of this bench completes in about a minute even on the extracted netlist, so the full matrix is not a burden. `Overall: FAIL`, 12/45 — but this is a marginal *widening* of a pre-existing schematic-level margin problem, not a new failure mode: extraction nudges four already-near-threshold `vref_spread` corners across the 0.001 V cliff (three newly failing, one newly passing) while every other already-failing `ff`/`sf` cold/room corner stays failing in both records. Its `README.md` carries the divergence finding required by issue #16, measured against a NEW same-sizing schematic-level baseline appended alongside it (`sim/startup-ramp/records/20260812-073050-7eb5be4`, at the adopted `n_r1=7`/`n_r2=50`; the newest pre-existing schematic-level records all predate the DR-003 resize) |

Both `startup-stability-post-layout` and `startup-ramp-post-layout` needed no
new body-assembly code beyond the bugfix above: `build_extracted_body()`'s
`.subckt`-scoped `strip_schematic_subckts()` already only removes the NAMED
`bandgap_core`/`error_amp` blocks, so a testbench that also netlists
`design/startup_injector.sym` (untouched by that name) gets a correct mixed
extracted-core/schematic-injector body for free once the collateral-deletion
bug above is fixed — no separate mixed-provenance assembly path was required
after all. This closes out issue #16's own "Adding the remaining post-layout
re-runs" note that used to live here.

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
  ladder directly.

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
  body** — there is no `--subset-reason` flag on this path, and "the runner
  enforces it" no longer applies, so the justification is a prose obligation;
- carry a **control point that must fail if the mechanism under test is not
  actually active** (e.g. `sim/pnp-mismatch/` re-runs its deck on the plain
  `tt` section, where every σ must come back exactly 0). A Monte Carlo harness
  that silently sampled nothing would otherwise produce a plausible record.

### Runner options

| Flag | Effect |
|---|---|
| `--print-env` | print PDK env exports and exit |
| `--process tt,ss` / `--temp 27` / `--supply 3.3` | override a matrix axis (marks the run a subset) |
| `--quick` | run the manifest's `quick_subset` only |
| `--subset-reason "…"` | **required** for any subset; recorded verbatim |
| `--supersedes <record-id>` | record which prior record this replaces |
| `--author`, `--timeout` | record author (default `git config user.email`), per-corner ngspice timeout |
| `--allow-pdk-mismatch` | run against a non-pinned PDK; the record flags it |
| `--dry-run` | netlist, print the corner list and one deck, write nothing under `sim/<slug>/` |

Exit status: `0` all checks passed, `2` a record was written but something
failed, `1` harness/setup error (no record written).

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
