# DR-003: The routed R2A/R2B/R1 array's per-instance head resistance is real and material — sizing must be re-derived against it

- **Status**: accepted (input to spec ratification, see #1). The follow-up
  resizing issue this record unlocked (#99) is delivered and verified — see
  the "Closure (issue #99)" section at the end of this record.
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

## Closure (issue #99, 2026-08-05) — the resize landed; the schematic now models the array

This record's "Consequences" handed a corrective resize to issue #99. That
issue is now implemented and verified; this section records what it found so
the record can be read end to end without chasing the follow-up.

**Evidence**: `sim/res-array-resize/records/20260805-213454-2c83c7a.md`
(runner `sim/res-array-resize/run_res_array_resize.py`, 4 phases,
overall PASS, same pinned PDK `c6d73a35`).

### What changed in the design

1. **`design/bandgap_core.sch` now models the chained topology, not the
   single-device approximation.** Each divider leg is stated on a new
   project-local symbol `design/res_high_po_series.sym` as ONE unit-length
   `sky130_fd_pr__res_high_po` instance carrying `mult = n` (the real series
   unit count, which the PDK model card uses only in its
   `MC_MM_SWITCH`-gated Pelgrom mismatch terms) and `m = 1/n` (the SPICE
   instance multiplicity, which scales one unit's resistance up by `n` —
   the series value). Phase 0 of the runner measures that form against an
   *explicit* n-instance chain in every run and gates on agreement:
   R1 12,023.05 Ω vs 12,023.05 Ω, R2A/R2B 90,236.61 Ω vs 90,236.52 Ω
   (1.0e-6 relative). The R2 leg is now two series blocks — a coarse block
   and the DR-002 trim ladder's fine block, joined at `TRIMA`/`TRIMB` —
   mirroring `gen_bandgap_routed.py`'s own `res_r2` + `res_trim` split.
   **This is the substantive part of the fix**: with it, every existing
   harness in `sim/` measures the topology the layout builds, and the "what
   the schematic simulates vs. what the layout draws" gap this record names
   has nowhere left to hide.
2. **`n_r1` 7 → 6, `n_r2` 54 → 42** (38 coarse 5 µm units + the unchanged
   20 fine 1 µm trim units per R2 leg). On the chained array that is
   R1 = 12,023.05 Ω, R2A = R2B = 90,236.61 Ω, **K = 7.5053** — against
   K = 8.1474 for the old counts carried onto the same array (this record's
   own measurement) and K = 7.4973 for the single-device model they were
   originally sized against.
3. **The branch current is held on its anchor, deliberately.** The
   derivation rejects any candidate more than ±5 % off the ~5.3 µA operating
   point the PNP ideality (#4/#35), error-amp offset budget (#9) and
   quiescent-current (#15) characterizations were all taken at — restoring
   `VOUT` by moving the current a long way would silently invalidate all
   three. `n_r1 = 5` / `n_r2 = 34` lands `VOUT` even closer to 1.200 V
   (+0.29 mV vs −0.66 mV) and is rejected on exactly that ground (+18.1 %
   branch current). The selected pair runs 5.1934 µA, −2.0 %.

### AC2 — full PVT re-verification (the rigor bar issue #46 set)

All **15** points of `sim/output-voltage-tc/experiment.json`'s own matrix
(tt/ss/ff/sf/fs × 2.97/3.30/3.63 V, temperature swept in-deck −40..125 °C by
the box method) pass: `VOUT(27 °C)` spans **1.19904–1.20094 V**, i.e. inside
the draft ±1 % window (1.188–1.212 V) with ≥ 11 mV of margin at every point,
against ≈ 1.233–1.235 V (outside the window at every point) for the
unresized array this record measured. **No hot-corner regulation collapse**:
the −40..125 °C excursion stays within 1.1722–1.2086 V everywhere, including
`ff`/2.97 V and `fs`/2.97 V — the two corners where this record found the
unresized array reproducing issue #46's ~2.85 V / ~8,000 ppm/°C
operating-point bifurcation.

**One honest regression to record**: the box TC is **167.2–184.0 ppm/°C**
across the 15 points, against **152.9–169.3 ppm/°C** for the single-device
model at the old counts (issue #11's record `20260803-115356-7759435`) — a
~+14 ppm/°C shift. Both are far above the draft's < 50 ppm/°C target, which
issue #46 already established as a *floor finding* this lever cannot reach
(`R2/R1` alone cannot close the TC gap on this device menu and loop). The
shift is expected on the mechanism this record documents: `rhead` and
`rbody` carry different temperature coefficients (`tc1 = −4.3e-4` vs
`tc1rpolybody`), and the head fraction of a leg now differs between R1
(6 heads in 12.0 kΩ, ~18.9 %) and R2 (58 heads in 90.2 kΩ, ~24.3 %), so `K`
itself acquires a small temperature dependence the single-device model did
not have. It is a real property of the drawn array, not an artifact of the
resize — the unresized array has it too, only masked there by a far larger
accuracy failure. Closing the TC target remains #13's curvature/trim scope
and the #9/`n_pnp_ptat` levers #46 named, unchanged by this record.

### AC3 — DR-002's trim range still covers what it was sized for

Re-run (not re-cited) against the resized baseline over
`sim/trim-range-monotonicity/`'s own 5 (process, supply) points at codes
0/−8/−16: **monotonic downward and collapse-free at every point**, and the
certified 0..−16 range spans **58.49–58.91 mV** of downward correction
against the **15.62 mV** worst-case 3σ untrimmed spread DR-002 sized it to
cover — **3.74× margin at the worst corner**, up from the ~1.6–1.8× DR-002
recorded. **The certified code range does not need to widen.**

What *did* change is the resolution: the step is now **3.66–3.68 mV/code**
against DR-002's ~1.72 mV/code, for the same reason this whole record
exists — each fine 1 µm trim unit is separately contacted, so tapping one
out removes 704.5 Ω per leg, not the 325 Ω the single-device `R ≈ 380 +
325·L` approximation implied. That is a resolution cost, not a coverage gap:
6.5 codes still span the 24 mV ±1 % window, i.e. ±1.84 mV (±0.15 % of
1.20 V) of worst-case quantization error. DR-002's own resolution
requirement ("small compared with the ±12 mV window — comfortably
resolvable, not snapping across it") still holds; its *stated* ~1.72 mV/code
and ~27.6 mV figures are now superseded by the numbers above and should be
read as single-device-model values.

### What this closure does NOT do — the layout is now the stale side

`layout/bin/gen_bandgap_routed.py` still draws the **pre-resize** array
(`N_R1 = 7`, `N_R2_COARSE = 50`, `SCH_N_R2 = 54` — 270 µm/leg), and
`layout/bandgap-core/reference.spice` still transcribes the pre-resize
values (88,130 Ω / 11,755 Ω). Propagating the resize into the drawn array is
deliberately **not** folded in here: it changes the `res_r2` fold geometry
(2 × 38 units no longer divides into the current 10 rows), the composed
area, and every drawn-vs-specified gate and unit test built on the 270 µm
figure (issue #91's `r2_leg_length()` and ~10 assertions in
`layout/tests/`), and it needs its own DRC / area-budget / `klt lvs`
evidence record — a separate increment under the same
one-lever-per-increment discipline this record invoked to hand the resize to
issue #99 in the first place. It is filed as issue #108 and noted in
`layout/matching-plan.md` Section 7x.

Until that lands, the direction of the schematic-vs-layout gap is
**inverted, and smaller**: before, the schematic modelled a topology the
layout does not build; now the schematic is correct and the layout draws a
superseded sizing. That is a strictly better place to be — the design of
record is the one that meets spec — but it is a real, disclosed gap, and
`klt lvs`'s `mismatch_count` should be expected to move (resistor *values*
now differ by design) until the layout is regenerated.

### Status

This record moves from **proposed** to **accepted**: the finding stands, and
the corrective action it scoped is delivered and verified. Its input to #1's
ratification is unchanged — the wave-1 3.3 V primary's untrimmed ±1 % target
is now met, on the layout's real resistor topology, at all 15 PVT points, at
the as-shipped `n_r2_trim = 0` code.
