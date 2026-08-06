# DR-002: Trim network scoping — needed, but safely usable in one direction only

- **Status**: proposed (input to spec ratification, see #1). The fine-trim
  ladder's per-code LSB has been **revised** against the routed layout's real
  chained topology — see "Revision (issue #106 — chained fine-trim LSB)" at
  the end of this record; range and monotonicity are unaffected.
- **Date**: 2026-08-03
- **Decided by**: Loom agent (issue #13), citing #12's Monte Carlo mismatch
  evidence (`sim/monte-carlo-untrimmed/records/20260803-142259-544cc5e.md`),
  issue #46's hot-corner regulation-collapse finding, DR-001's wave-1
  flavor-scope note, and this issue's own
  `sim/trim-range-monotonicity/` design-phase evidence.

## Context

Issue #13 is a two-stage scoping-then-design issue. DR-001 defers the entire
1.8 V "Stretch" flavor for wave 1, which collapses the original two-branch
scoping question ("trim for the ±1 % line, or only for a ±0.5 %-with-trim
stretch line?") into a single go/no-go: **does the 3.3 V primary's untrimmed
±1 % target actually hold up under real (local-mismatch) variation, or does
reality require trim on the flavor the DRAFT spec assumes doesn't need it?**

Issue #12's Monte Carlo mismatch analysis is the evidence source this
question is conditioned on (per the issue body and its multiple curator
passes). That analysis is now closed, merged via PR #51, record
`20260803-142259-544cc5e`. Its headline numbers, at the nominal process
point (`tt_mm`, local mismatch on, all three device families active,
3.30 V, N = 300 Monte Carlo draws per temperature):

| T (°C) | mean VOUT (V) | 1 σ (mV) | 3 σ (% of 1.20 V) | yield inside ±1 % [1.188, 1.212] V |
|---|---|---|---|---|
| −40 | 1.208424 | 4.8785 | 1.220 % | 77.63 % |
| 27 | 1.199852 | 4.9880 | 1.247 % | 99.00 % |
| 125 | 1.174690 | 5.2051 | 1.301 % | **0.67 %** |

The record's own overall verdict is **FAIL**. At 27 °C the untrimmed core is
close to the ±1 % line (99 % yield) but at both temperature extremes the 3 σ
spread (1.22–1.30 % of 1.20 V) already exceeds the ±1 % window on its own —
before any additional global process shift or curvature (the orthogonal axis
`sim/output-voltage-tc` / issue #11 already substantiates) is added. At
125 °C the yield collapses to 0.67 %: essentially no die lands inside the
window from local mismatch alone. This is a mismatch-only, single
process-point measurement (see that record's own "Scope limits" section);
the amp/mirror MOS term dominates the spread at every temperature (4.20–4.46
of the 4.88–5.21 mV total 1 σ), consistent with issue #9's error-amp offset
budget finding (`design/error-amp-offset-budget.md` §6) that the
amplifier's random offset — 74–90 % of the mismatch variance, amplified by
the core's measured 9.65 offset gain — is what makes the untrimmed target
unreachable "with this core and a plain amplifier," and that §6 already
names trim (path 2) as one of the two viable ways forward, requiring a
downward-plus-upward range of **at least ±1.5 % at 3 σ** (mismatch alone,
before #11's global-process/curvature terms add on top).

This is also the factual input #1 and #32 flagged as missing: DR-001 defers
the Stretch column but wave 1's Target column has no explicit
trimmed-accuracy row. This record is that missing factual basis.

## Decision

**A trim network is needed for the wave-1 3.3 V primary target — go.** The
untrimmed ±1 % claim is not met (#12: FAIL, 77.6 % / 0.67 % yield at the
temperature extremes), so this issue proceeds past the scoping stage into
design.

**Trim style**: resistor-ladder tap selection (the spec's default candidate,
confirmed rather than displaced by an alternative). Implemented as a
length-tap addition on the core's own R2A/R2B resistor legs (issue #8's
parameterized resistor segments) — not a new device family, not a
re-entry of the core cell. See `design/bandgap_core.sch`'s `n_r2_trim` /
`r_lseg_trim` parameters.

**Key finding of the design phase — the trim range is DOWNWARD-ONLY, not
bidirectional.** `n_r2_trim` adjusts the same R2/R1 ratio (`K`) that sets
the core's PTAT gain — the exact parameter issue #46 already found controls
a hot-corner (`ff`/2.97 V, `fs`/2.97 V) DC-operating-point bifurcation above
~123–124 °C. #46 rejected a `+5 µm` / `+1.85 %` R2 increase (`n_r2=55`)
because the core lost its operating point entirely at those two corners.
`sim/trim-range-monotonicity/` re-tests this directly for trim and finds it
is **worse** than #46's single data point suggested: on this harness's own
`-40..125 °C` grid, `n_r2_trim=+1` and `+2` **both** collapse the operating
point at `ff`/2.97 V (`VOUT` jumps to ~2.83 V, box TC reads ~8000 ppm/°C),
while `+3` and `+4` do not, and `+5`/`+15` collapse again. That
non-monotonic pass/fail-in-code pattern (collapsed, collapsed, sane, sane,
collapsed, …) is the signature of a coarse verification grid crossing a
genuine bifurcation surface at an angle — consistent with #46's own finding
that the true threshold sits at 123–124 °C, between this harness's 114 °C
and 125 °C grid points, not evidence of a safe zone at `+3`/`+4`. **No
positive trim code can be certified safe from this evidence**: the shipped
baseline (`n_r2=54`, `trim=0`) already has zero headroom for any R2
increase at these corners. Only the downward direction (R2 decrease) was
confirmed monotonic and collapse-free.

**Range and resolution**, derived from #12's MC σ with margin, downward
only (see `sim/trim-range-monotonicity/records/` for the simulated
confirmation):
- Per-code step (LSB): ~1.72 mV at the core's nominal ~5.3 µA branch current
  (one `r_lseg_trim` = 1 µm unit segment on both R2A and R2B), against the
  **single-device** resistor model this design-phase record simulates. Well
  inside the ±12 mV (±1 %) window — comfortably resolvable, not snapping
  across it. **Superseded for the real chained topology**: the routed
  layout does not draw one length-tapped device per leg, it chains
  separately-contacted unit instances that each pay a real per-instance
  head/fringe resistance term (DR-003) this single-device model omits —
  against that real topology the per-code step reads ~3.1–3.2 mV/code at
  the shipped `r_lseg_trim=1 µm`, which **fails** this record's own
  `<= 3.000 mV/code` comfort bound (see "Revision (issue #106)" below,
  which halves the fine unit's drawn length to `r_lseg_trim=0.5 µm` to
  restore it to ~2.4 mV/code).
- Code range: **0 (untrimmed) down to −16**, giving ~27.6 mV of downward
  correction range — covers the worst-case 3 σ spread found above
  (15.62 mV at 125 °C) with ~1.6–1.8× margin. This is enough range to
  correct any die whose mismatch pushed `VOUT` too **high**. It provides
  **no** correction for a die whose mismatch pushed `VOUT` too **low** —
  see "Consequences" below.

**Application for shuttle reality**: **metal option.** One tap per die/run
is selected at the metal-mask stage from post-fabrication / wafer-probe
characterization, fixed for the life of the part. Not a fuse (sky130's
device menu used by this core has no one-time-programmable element to
spend one on) and not a register (a digital trim register would need
SPI/decode logic disproportionate to this small analog core, and this
project has no digital infrastructure elsewhere in the design). A metal
option also adds zero active devices to the trim path itself — the taps are
just more of the same `res_high_po` resistor body, so no new leakage or
offset mechanism is introduced by the trim network.

**TC at the trim extreme is reported, not hidden.** At the full `−16` code,
box TC increases by roughly **+77.6 to +79.5 ppm/°C** above the pre-existing
untrimmed baseline (already ~152–169 ppm/°C, itself over the draft
50 ppm/°C budget for reasons unrelated to trim — issue #46, still open).
This is a real, substantial, disclosed cost of using the same R2/R1 ratio
for both accuracy trim and the core's PTAT/CTAT cancellation weight — see
`sim/trim-range-monotonicity/`'s own "Scope limits" for the exact per-corner
numbers and why a tight delta budget is not achievable on this lever.

## Alternatives considered

- **Trim not needed (scope out at this stage).** Rejected — the evidence
  says otherwise. This was the intended early-exit path if #12 had shown
  the untrimmed target met with margin; it did not (0.67 % yield at
  125 °C is not "met with margin" by any reading).
- **Bidirectional trim (the original design-phase draft).** Rejected after
  direct simulation: the positive direction was implemented and tested
  first, and found to collapse the ff/2.97 V and fs/2.97 V operating point
  non-monotonically across small codes (see "Key finding" above). Shipping
  it would have meant a trim network that looks correct in isolation (each
  code, tested alone, either regulates or doesn't) but is not certifiably
  safe at any positive setting — an unacceptable risk for a metal-option
  trim that cannot be re-tested per die before tape-out commits to it.
- **Binary-weighted parallel resistor DAC** (switches shorting/opening
  parallel trim resistors) instead of a series ladder-tap. Rejected: it
  needs an active switch device per bit in the signal path (adding
  on-resistance variation and a leakage term to a ratio-critical leg),
  where a ladder-tap needs none — the tap is a metal connection, not a
  device. It also would not avoid the hot-corner bifurcation, since that is
  a property of the resulting R2 value, not of how the resistance is
  assembled.
- **Fuse-based one-time trim.** Rejected for this device menu: no
  fusible/OTP element is used elsewhere in this core, and adding one purely
  for trim would be a new device family this issue's acceptance criteria
  do not ask for ("no re-entry of the core cell" beyond extending the
  existing resistor segments).
- **Register-based (test-time programmable) trim.** Rejected as
  disproportionate: it would need a decode/latch block and a digital
  interface this analog-only core and project do not otherwise have.

## Spec lines affected

| README target-spec row | Effect of this decision |
|---|---|
| Output reference (1.20 V ±1 % untrimmed, 3.3 V primary) | This decision does not change the Target-column value. It records that the value is **not met untrimmed** and that a trim network (this record's design) is required to meet it in practice — and that the trim network, as implementable on this core+amplifier, only corrects **half** the mismatch distribution (the high-VOUT tail). The factual input #1's ratification needs to decide whether the Target column's wording should say "±1 % trimmed (downward-only correction)" explicitly (per #1's amendment-prep option (a)) rather than leave the trim network implicit or assume full bidirectional correction. |

No Target-column numeric value is amended by this decision; it is a scoping
record, not a spec-value change. Formal ratification of the wording
implication above remains #1's responsibility, per its own amendment-prep
list.

## Consequences

- **Unlocks the design phase for #13** (this issue): trim taps are added to
  `design/bandgap_core.sch`'s R2A/R2B resistor segments, downward-only;
  range/monotonicity/TC-at-extremes evidence is recorded in
  `sim/trim-range-monotonicity/`.
- **Only half the mismatch distribution is correctable.** A downward-only
  trim helps dies whose random mismatch pushed `VOUT` too high but leaves
  dies whose mismatch pushed it too low uncorrected — roughly half of a
  zero-mean mismatch population (issue #12's own record does not
  characterize skew, so this is a symmetry assumption, not a measured
  fact). Closing this gap needs work outside this issue's scope:
  - **Widen the error amplifier's hot-corner headroom margin (#9)** so a
    higher K does not cost `ff`/`fs`-corner regulation — this is the most
    direct path to reopening positive-direction range in a future revision.
  - **Attack the mismatch at its physical source (#15's layout matching)**
    — issue #12 found amp/mirror MOS mismatch dominant, so tighter layout
    matching on the amplifier's input pair and mirrors would shrink how
    often (and how far) trim is needed in either direction.
- **Feeds #1's ratification**: this record's yield numbers and the
  downward-only finding are the exact factual basis #1's amendment-prep
  list asked for — supporting option (a) (add explicit trimmed-accuracy +
  trim-strategy rows to the Target column, with the downward-only caveat)
  over option (b) ("no trim in wave 1").
- **Feeds #15** (floorplan): the trim network occupies the same R2A/R2B
  resistor legs #15's matching/floorplan work already has to place; #15's
  own body already notes it conditionally integrates trim segments if this
  issue scopes them in — it now should, downward-only.
- **Feeds #16** (post-layout check, per its own cross-reference to #13):
  post-layout verification of the trimmed core now has a defined (and
  range-limited) trim network to verify against.
- **Does not fix the pre-existing TC overage** (issue #46, still open as of
  this record: measured untrimmed core TC is ~152–169 ppm/°C across process
  corners, already above the draft <50 ppm/°C budget, for reasons unrelated
  to trim — see `sim/output-voltage-tc/records/20260803-115356-7759435.md`).
  This record's own TC-at-trim-extreme evidence
  (`sim/trim-range-monotonicity/`) measures the *incremental* TC effect of
  trim against that pre-existing baseline (a further +77.6 to +79.5 ppm/°C at
  the full `−16` code) — not a claim that trim brings TC under the
  50 ppm/°C budget, and not a claim that this incremental cost is small.
  That remains #46's scope; this record only discloses trim's own share of
  it honestly.
- **Reinforces #46's own follow-up list**: #46 already named "curvature
  correction/trim (#13)... or widening the error amp's own headroom margin
  (#9)" as the two paths to closing the TC gap. This record shows the first
  half of that list (trim) is itself gated by the second (#9's headroom
  margin) in the upward direction — the two issues are more coupled than
  #46's text implied.

## Revision (issue #106 — chained fine-trim LSB)

This record's original LSB derivation (~1.72 mV/code, "Range and
resolution" above) simulated the fine trim ladder as **one length-tapped
`res_high_po` device per leg** — the schematic-level approximation
`design/bandgap_core.sch`'s `XR2A`/`XR2B` lines still draw. The routed
layout does not build that: `layout/bin/gen_bandgap_routed.py`'s fine-trim
block (`res_trim`) chains `N_R2_TRIM_UNITS=20` separately-contacted unit
instances per leg (the same `bus_res_series` topology DR-003 / issue #98
found pays a real per-instance head/fringe resistance term the
single-device model omits — `sim/res-array-head-resistance/`). A downward
trim code does not shorten one device's body by 1 µm; it removes a whole
separately-contacted unit instance, paying that instance's head/fringe term
in addition to its 1 µm of body. Issue #106 asked whether this makes the
per-code step exceed this record's own `<= 3.000 mV/code` (25 % of the
±1 % window's 12 mV half-width) comfort bound at the sizing that was
actually adopted (`n_r1=7`, `n_r2=50` — issue #99 / PR #105), since an
earlier estimate against an abandoned `n_r1=6`/`n_r2=42` alternative
(never merged) had reported a larger 3.655–3.682 mV/code violation.

`sim/trim-lsb-chained/run_trim_lsb_chained.py` re-derives all three of this
record's own criteria (monotonic-in-code, downward span, LSB) against the
real chained topology at the adopted sizing, over the same 5-corner PVT set
`sim/trim-range-monotonicity/` and issue #99's AC3 used, at two fine-unit
lengths:

| `r_lseg_trim` | per-code step (analytic, ohm) | measured LSB (mV/code, all 5 corners) | monotonic? | span >= 1.5×3σ? | LSB <= 3.000 mV? |
|---|---|---|---|---|---|
| 1.0 µm (shipped, as drawn) | 704.53 | 3.123–3.146 | yes | yes (49.96–50.33 mV) | **NO** |
| 0.5 µm (revised) | 542.12 | 2.403–2.421 | yes | yes (38.44–38.73 mV) | yes |

**Finding: the shipped `r_lseg_trim=1 µm` chained topology fails this
record's own LSB comfort bound at all 5 corners**, even at the adopted
`n_r1=7`/`n_r2=50` sizing (a smaller violation than the abandoned sizing's
estimate — because the resized sizing's own untrimmed operating point sits
closer to spec center, so its trim span itself is smaller — but a real,
measured one, not merely a carried-over assumption). Monotonicity and the
downward-span coverage target are unaffected and continue to PASS,
confirming DR-003's own prediction that the fine chain's per-instance
head-resistance term is unchanged between the two competing #99 resizes
(both keep 20 fine units of 1 µm each; only the coarse leg count differed).

**Revision: `r_lseg_trim` 1 µm → 0.5 µm.** The per-instance head-resistance
term (`rhead`, ~379.7 Ω) is a PDK model-card constant fixed per removed
unit instance, independent of the unit's drawn body length — only the
smaller `rbody` sheet/fringe term (~324.8 Ω/µm) scales with it. Halving the
fine unit's drawn length from 1.0 to 0.5 µm therefore does not halve the
per-code step, but it removes enough of the `rbody` contribution to bring
the step from 704.53 Ω/code (shipped) down to 542.12 Ω/code (revised) —
enough to restore the LSB to 2.40–2.42 mV/code, comfortably under the
3.000 mV/code bound at every corner. The fine ladder's unit **count**
(`N_R2_TRIM_UNITS=20`) and therefore this record's certified `0..-16` code
range are unchanged — this is a pure re-partition of the fixed `5*n_r2` µm
leg length between its coarse and fine segments (coarse count moves from
46 to 48 units to hold the untrimmed leg length fixed), not a resize of
`n_r1`/`n_r2` (issue #99's lever) or a change to the certified code range.
`design/bandgap_core.sch`'s `.param r_lseg_trim` moves from `1` to `0.5`
accordingly.

**Scope of this revision.** This lands the schematic-level parameterization
and its full chained-topology, 5-corner re-verification
(`sim/trim-lsb-chained/records/`). It does **not** regenerate or
re-DRC/LVS-verify the routed layout: `layout/bin/gen_bandgap_routed.py`'s
`R_LSEG_TRIM_UM`/`SCH_R_LSEG_TRIM_UM` constants still transcribe the old
1 µm fine-unit length, and `klayout`'s extraction/DRC backend is not
importable in this run environment (`python3 -c "import klayout"` fails),
so the routed cell cannot be re-verified here. Per the same
one-lever-per-increment discipline DR-003 used to split issue #99 from
#107/#108 (sizing decision + sim verification first, layout
re-transcription + klayout DRC/LVS as a separate next increment), that
propagation is left as a follow-up issue.

- **Links**:
  - `sim/trim-lsb-chained/run_trim_lsb_chained.py` (runner)
  - `sim/trim-lsb-chained/records/` (append-only evidence, this revision)
  - `sim/res-array-resize/records/20260805-204809-2c83c7a.md` (adopted
    sizing, `n_r1=7`/`n_r2=50`, issue #99 / PR #105)
  - `sim/res-array-head-resistance/records/20260805-113409-6caa9f8.md`
    (chained-array head resistance is real and material, DR-003)
  - `spec/decision-records/DR-003-res-array-head-resistance-sizing.md`
