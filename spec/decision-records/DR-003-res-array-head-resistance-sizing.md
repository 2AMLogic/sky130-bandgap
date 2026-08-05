# DR-003: The routed R2A/R2B/R1 array's per-instance head resistance is real and material — sizing must be re-derived against it

- **Status**: proposed (input to spec ratification, see #1; unlocks a
  follow-up resizing issue, not undertaken by this record)
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
