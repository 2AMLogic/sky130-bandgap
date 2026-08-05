# DR-003: The routed R2A/R2B/R1 array's per-instance head resistance is real and material — sizing must be re-derived against it

- **Status**: proposed (input to spec ratification, see #1). The follow-up
  resizing issue this record unlocked (#99) has landed — see
  "Closure (issue #99)" at the end of this record. The finding itself is
  unchanged; nothing in the sections below is amended.
- **Date**: 2026-08-05
- **Decided by**: Loom agent (issue #98), citing
  `sim/res-array-head-resistance/records/20260805-113409-6caa9f8.md`,
  2AMLogic/klayout-tools#518/#519/#526 (upstream `res_high_po` head-
  resistance fix), issue #46's hot-corner regulation-collapse precedent, and
  issue #91's R2-leg-length precedent.

## Context

Issue #62's routed-layout flow draws each of `R1`/`R2A`/`R2B`'s divider legs
not as one `res_high_po` device (what `design/bandgap_core.sch` models, and
what every PVT/trim-range sim record in this repo simulates today) but as a
*chain* of separately-contacted `res_high_po` unit instances wired in series
through real drawn metal+via (`layout/bin/gen_bandgap_routed.py`'s
`res_r2`/`res_trim`/`res_r1` blocks and `bus_res_series`): 7 units for R1
(7 × 5 µm), 70 for R2A/R2B (50 × 5 µm + 20 × 1 µm). 2AMLogic/klayout-tools
#518/#519/#526 taught `klt extract` the real sky130 PDK's `res_high_po`
model card, which carries a fixed per-*instance* head/end-effect resistance
term — and picking that fix up (issue #62's PR #97, still open) makes the
layout's extracted `R1`/`R2A`/`R2B` read +19.3%/+29.7% higher than the
schematic's model. Issue #98 asked whether that is (1) an LVS-comparison-
only modelling-granularity artifact, or (2) a real electrical effect the
fabricated part experiences at every internal riser of the folded array —
and, if real, whether it is material.

`sim/res-array-head-resistance/run_res_array_head_resistance.py` answers
both questions with real-SPICE evidence, not extraction-tool re-analysis:

- **Phase A** chains N real `sky130_fd_pr__res_high_po` unit-device SPICE
  model instances (the PDK's own `rhead`/`rbody` semiconductor-resistor
  cards, via ideal zero-resistance wires) at the layout's own N/L shapes.
  The chained totals — R1 = 14,026.89 Ω, R2A/R2B = 114,282.70 Ω — reproduce
  `klt`'s LVS-extracted values to 5-6 significant figures, using a
  completely independent computation (real ngspice device-model evaluation,
  not `klt`'s analytic `L/W·sheet_rho + fixed_offset` formula). That level
  of agreement rules out an extraction-only artifact: **reading 2 is
  correct**. The model card's own structure explains why — `rhead`'s length
  is a hardcoded `l=1.0`, independent of the caller's drawn body length, so
  a real device pays this term once per physically separate, individually-
  contacted instance. The routed layout's `bus_res_series` draws real
  contacts at every one of the array's internal unit boundaries, which is
  exactly the structure this term represents.
- **Phase B** substitutes the same chained topology into the real core
  testbench (`sim/output-voltage-tc/testbench/tb_vref_tc.sch`, the same
  box-method `-40..125 °C` sweep `sim/trim-range-monotonicity/` already
  uses) at the 5 (process, supply) corners issue #46/#91 already flagged as
  the ones that matter (`tt`/3.30 V, `ss`/3.30 V, `ff`/2.97 V, `sf`/2.97 V,
  `fs`/2.97 V). `VOUT(27 °C)` lands outside the draft ±1% window
  (1.188-1.212 V) at **all 5** corners (≈1.233-1.235 V vs. the single-device
  model's ≈1.1995-1.2013 V baseline at the same points). At `ff`/2.97 V and
  `fs`/2.97 V specifically, the shift reproduces the *exact*
  regulation-collapse signature issue #46 and `sim/trim-range-monotonicity/`
  already characterized for a positive R2/K increase (`VOUT` pinned near
  2.85 V, box TC ≈8,000 ppm/°C) — triggered here not by a resize or a trim
  code, but by the routed layout's own real electrical topology at the
  untrimmed, as-shipped `n_r2_trim=0` code.

K = R2/R1 moves from 7.4973 (single-device model) to 8.1474 (real chained
topology), **+8.67%** — not a uniform scale on both resistors, because R1's
delta (+19.39%) and R2A/R2B's delta (+29.74%) differ.

## Decision

**The finding is ratified as real and material.** `design/bandgap_core.sch`'s
sizing (`n_r1=7`, `n_r2=54`) and every PVT/trim-range verification record in
this repo to date were computed and checked against the single-device
`res_high_po` model, not the routed layout's actual folded-array topology.
That gap is not cosmetic: at the untrimmed, as-shipped operating point, the
real part's `K` is high enough to leave the draft ±1% spec window at every
corner checked, and to fully collapse regulation at the two corners this
project already treats as margin-thin.

**This record does not itself change `n_r1`/`n_r2` or any drawn geometry.**
Per this project's established one-lever-per-increment discipline
(`layout/matching-plan.md` Sections 7a-7u) and issue #98's own
investigation-only scope, the corrective resizing is left to a dedicated
follow-up issue (see "Consequences" below) so it gets the same full-corner
verification rigor issue #46 applied to the original `n_r2=54` sizing and
issue #91 applied to the R2-leg-length fix, rather than being folded into an
investigation PR.

**No `reference.spice` / `gen_bandgap_routed.py` code change is needed to
act on this finding.** `layout/bandgap-core/reference.spice`'s `RR1`/`RR2A`/
`RR2B` cards and `design/bandgap_core.sch`'s `R ~ 380 + 325*L` comment
remain accurate *single-device* approximations — Phase A's own single-
instance-at-combined-L measurements confirm they still track the real PDK
model to within 0.06% (unchanged from Section 7t's finding). What they are
not accurate for is the routed layout's *own* topology, which was never
their claim in the first place. The gap this record closes is between "what
the schematic models" and "what the layout draws," not an error in either
file considered alone.

## Alternatives considered

- **Treat as an LVS-only artifact (reading 1), no action.** Rejected —
  Phase A's independent-mechanism reproduction (real SPICE vs. `klt`'s
  extraction formula landing on the same number to 5-6 significant figures)
  is strong enough evidence against a bookkeeping-only explanation that
  dismissing it would be the same class of mistake issue #46's own header
  warns against: a real effect wrongly waved off as measurement noise.
- **Fix the sizing inline in this same PR.** Rejected — a `n_r1`/`n_r2`
  resize needs its own full PVT corner re-verification (the same rigor
  issue #46 applied), which is a separate, sizeable increment in its own
  right, not a natural extension of an investigation-scoped issue. Bundling
  it here would also make this record's own evidence (the *unresized*
  chained-array collapse) harder to audit independently once the fix lands
  on top of it.
- **Change the layout topology instead of the schematic sizing** (e.g. draw
  each divider leg as fewer, longer `res_high_po` instances instead of many
  small folded units, cutting N and therefore the aggregate head-resistance
  term). Not rejected, but explicitly left open as an alternative for the
  follow-up issue to weigh against a pure resize — `res_array`'s `rows` fold
  parameter and the DR-002 trim ladder's own tap requirements are why the
  array is folded into small units in the first place (issue #62, Section 7
  generator-mapping notes), so a topology change interacts with the trim
  network's own tap resolution and is not obviously free.

## Spec lines affected

| README target-spec row | Effect of this decision |
|---|---|
| Output reference (1.20 V ±1% untrimmed, 3.3 V primary) | Not amended by this decision. This record documents that the untrimmed operating point, evaluated against the routed layout's *real* resistor topology (not the single-device model the Target column's existing verification used), misses the ±1% window at every corner checked — a **sizing** gap distinct from DR-002's already-ratified mismatch-yield gap. Closing it is the follow-up resizing issue's job, not this record's. |

No Target-column numeric value is amended by this decision; it is a
sizing-scope record, not a spec-value change.

## Consequences

- **Unlocks (does not itself perform) a follow-up resizing issue (#99)**
  against `design/bandgap_core.sch`'s `n_r1`/`n_r2` (or an alternative that
  reduces the array's per-instance-contact count — see "Alternatives considered"),
  re-verified against the same full PVT corner set issue #46 used before
  being adopted, with the routed layout's chained-array topology (not the
  single-device approximation) as the ground truth to size against going
  forward.
- **Every existing PVT/trim-range/Monte-Carlo sim record in this repo is
  now understood to model a resistor topology the routed layout does not
  build.** This does not retroactively invalidate those records for their
  own stated purposes (DR-002's mismatch-yield finding, issue #46's original
  TC/operating-point characterization, etc. are all still correct
  statements about the single-device model they were run against) — but it
  means none of them are evidence that the *routed, LVS-verified* part
  meets the same numbers, and the follow-up resizing issue's own
  verification should re-run (not merely re-cite) the corner set that
  matters once a corrected sizing exists.
- **Interacts with DR-002's downward-only trim ladder.** The shift this
  record measures is entirely in the direction DR-002's trim ladder already
  corrects (K/`VOUT` too high) — so a die built to the *current* sizing is
  not necessarily unsalvageable at the metal-option trim stage, provided
  the trim range DR-002 sized (0..-16, ~27.6 mV) still covers this shift's
  magnitude in addition to the mismatch spread it was originally sized for.
  This record does not check that combined coverage — flagging it
  explicitly as a gap the follow-up resizing issue (or a dedicated trim-
  range re-check) needs to close, since DR-002's own range derivation
  assumed the single-device model's baseline `VOUT`, not this record's
  shifted one.
- **Feeds #1's ratification** the same way DR-002 did: a factual finding
  about what the wave-1 3.3 V primary's untrimmed target actually measures
  against the layout that will really be fabricated, for #1's amendment-prep
  list to weigh.
- **No `klayout-tools` friction filed by this record.** Per issue #98's own
  provenance note, the finding is this design's own array-folding choice
  interacting with a now-correct extractor (2AMLogic/klayout-tools#518/#519/
  #526 are doing exactly what they should) — not a tool gap.

## Closure (issue #99, 2026-08-05)

The corrective resize this record's "Consequences" handed to issue #99 has
landed. Evidence:
`sim/res-array-resize/records/20260805-211755-2c83c7a.md`
(runner `sim/res-array-resize/run_res_array_resize.py`, which extends
`sim/res-array-head-resistance/`'s Phase B chained-topology harness with a
candidate screen, the full PVT matrix, a fine hot-corner sweep, DR-002's trim
ladder, and a single-device control — 45 real ngspice points, no re-cited
numbers).

**The pure-resize path closed the gap; the topology change was not needed.**
`design/bandgap_core.sch` now carries `n_r1=6` / `n_r2=42` (was 7 / 54). Sized
against the routed array's *real* chained values, not the single-device model:

| quantity | single-device model @ 7/54 | routed chain @ 7/54 (this record's finding) | routed chain @ 6/42 (shipped) |
| --- | --- | --- | --- |
| R1 | 11,748.66 Ω | 14,026.89 Ω | 12,023.0 Ω |
| R2A/R2B | 88,083.06 Ω | 114,282.70 Ω | 90,236.6 Ω |
| K = R2/R1 | 7.4973 | 8.1474 | 7.5053 |
| VOUT(27 °C), tt/3.30 V | 1.199721 V | 1.233408 V (**out of window**) | 1.199328 V |

K lands within 0.11 % of the 7.4973 the original single-device sizing
targeted, and R1 within +2.34 % of its single-device value (against the
as-drawn chain's +19.39 %), so the branch current returns to the ~5.3 µA the
PNP pair was characterized at. The screen re-ran the as-drawn 7/54 control
through the same harness and measured 1.233408 V at tt/3.30 V — reproducing
this record's own number, so the resize was chosen in the same frame of
reference the finding was measured in.

**Full PVT re-verification (issue #46's rigor bar): passes.** 5 process × 3
supply = 15 points, each a box-method `-40..125 °C` sweep. VOUT(27 °C) is
inside the draft ±1 % window (1.188-1.212 V) at **every** point (worst case
1.199040 V at ff/2.97 V, −0.08 % of nominal), and no point leaves the sanity
band anywhere in the sweep. The two corners this record found collapsing
(ff/2.97 V, fs/2.97 V) were additionally swept at 1 °C resolution from 110 to
140 °C — 15 °C past the qualified ceiling — with no bifurcation: VOUT stays in
1.1698-1.1755 V throughout.

Box TC over the matrix is 167.2-184.0 ppm/°C, the same family as the
pre-existing single-device baseline (152.9-169.3 ppm/°C) and still far above
the draft's < 50 ppm/°C target — for the reason issue #46 already established
as a floor on this lever, not because of this resize. Note the as-drawn,
*out-of-spec* 7/54 chain measured a **better** TC (96.8 ppm/°C at tt)
precisely because its K was 8.7 % too high; buying that TC costs the ±1 %
accuracy line, which this project does not trade away to make a result pass.

**The trim-range question this record flagged is answered — and splits in
two.** DR-002's downward 0..−16 ladder was re-run (not re-cited) on the
resized chained baseline at its own five corners:

- **Range: still covers.** The span is 58.5-58.9 mV (vs ~27.6 mV under the
  single-device model), against DR-002's own criterion of ≥ 1.5 × the 15.62 mV
  worst-case 3σ mismatch spread = 23.4 mV. Monotonic in code at every corner,
  collapse-free at the −16 extreme. So the concern this record raised — that
  the shift might eat the mismatch headroom DR-002 sized for — does **not**
  materialize: after the resize there is no sizing shift left for the ladder to
  absorb, and the ladder keeps its full budget for mismatch.
- **Granularity: no longer within DR-002's comfort bound.** The LSB is
  3.655-3.682 mV/code against DR-002's own ≤ 3.000 mV/code bound (25 % of the
  window half-width), because a trim code in the *chained* ladder removes a
  whole unit **instance** — its head/fringe terms as well as its 1 µm of body —
  roughly doubling the step DR-002 assumed. That is a DR-002 revision, not a
  sizing question; filed as issue #106.

**What is still open after this closure** (stated so no reader takes the
resize as making the schematic and the layout agree):

- **The schematic's own netlist now under-reads.** `design/bandgap_core.sch`
  still netlists ONE `res_high_po` device per leg, so a schematic-only
  simulation of the shipped sizing measures +39.0…+39.4 mV *below* the chained
  topology it is sized for (measured at the same five corners, reported but not
  gated in the record). Every schematic-only bench under `sim/` inherits that
  offset. This is a **modelling** gap, not a trim target — it is in the
  direction DR-002's downward-only ladder cannot correct — and closing it needs
  either issue #101's topology change (fewer, longer instances per leg, which
  makes the single-device model correct again) or a schematic device-model
  change. It is stated in the schematic's own `EPISTEMIC STATUS` block.
- **The drawn layout still implements the pre-#99 counts.**
  `layout/bin/gen_bandgap_routed.py`'s `N_R1` / `SCH_N_R2` / `N_R2_COARSE` were
  deliberately left at 7 / 54 / 50: re-drawing the array moves block extents,
  the met1 busses, and every routed corridor, so it is its own layout increment
  with its own route/DRC/LVS run. Filed as issue #107, narrated in
  `layout/matching-plan.md` Section 7x, and flagged in the generator itself.
- **Issue #101's premise has moved.** The topology alternative was filed as a
  way to stop the head resistance from pushing VOUT out of spec; the resize has
  done that. Its remaining value is the *modelling* gap above (making the
  single-device schematic model correct again) plus whatever it does to issue
  #106's LSB — a different case than the one it was filed on, and one that
  should be re-argued before it is built.
- **No numeric spec value is amended by this closure**, exactly as the
  "Spec lines affected" table above states. The untrimmed ±1 % row is now met
  at all 15 PVT points *against the routed layout's resistor topology*, which
  is new evidence for #1's ratification to weigh — not a spec change made by an
  agent.
