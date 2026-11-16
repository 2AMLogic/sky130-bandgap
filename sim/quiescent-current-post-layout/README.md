# `quiescent-current-post-layout` — divergence finding

Post-layout (`provenance: extracted`) re-run of `sim/quiescent-current`'s Iq
claim against the routed, LVS-clean `layout/bandgap-core/` GDS (issue #62),
for issue #16. Records here are append-only and are **new** evidence — they
neither overwrite nor retire `sim/quiescent-current/`'s schematic-level
records.

This file exists because issue #16 requires any divergence from the
schematic-level result to be **documented as a finding, not reconciled
away**, and the divergence here is large (−35.8 % at `tt/27 °C/3.30 V`).
It is written alongside the record, not into it, for the same reason
`sim/output-voltage-tc/README.md` exists: the record format has no field for
a cross-record investigation.

## What the record says

Record `20260812-000420-2d88289` — full 45-point PVT matrix, **no** collapsed
axis, `Overall: PASS`.

| Quantity | Post-layout (extracted) | Limit |
|---|---|---|
| `iq` | 14.90 µA (`ss/−40 °C/3.63 V`) … 26.61 µA (`sf/125 °C/3.63 V`) | 1 µA … 50 µA — **pass, 45/45** |
| `vref` (degenerate-state guard) | 1.16706 … 1.20367 V | 1.0 … 1.4 V — pass |
| `vgdrv` (degenerate-state guard) | 1.596 … 2.609 V | 1.0 … 2.9 V — pass |
| `iq` spread check | 11.71 µA observed | ≥ 1 µA — pass |

Both degenerate-state guards passing at every corner is what rules out the
"the translation silently dropped devices / a parasitic opened a rail, and
the small current is an all-off solution" reading of the low number below.

## The divergence

Closest schematic-level reference: `sim/quiescent-current/records/20260803-115334-7759435`
(same bench, same manifest, same measurement expressions; `design/bandgap_core.sch`
at `n_r1=7`, `n_r2=54`, single-device resistors).

| | schematic | post-layout | delta |
|---|---|---|---|
| `iq` @ `tt/27 °C/3.30 V` | 31.165 µA | 19.999 µA | **−35.8 %** |
| `iq` matrix min | 24.19 µA (`ss/−40 °C/3.63 V`) | 14.90 µA (same corner) | −38.4 % |
| `iq` matrix max | 39.10 µA (`sf/125 °C/3.63 V`) | 26.61 µA (same corner) | −31.9 % |

Two things say this is a *scale factor*, not a changed operating point:
the extreme corners are the **same** corners in both records, and the
per-corner ratio post/schematic is tightly clustered (0.616 … 0.689, mean
0.649) rather than scattered.

## Attributed cause: R1 is 55 % larger in the extracted netlist

Iq in this Kuijk core is set by the PTAT branch current `ΔV_BE/R1` (both core
legs plus the mirrored amp tail scale with it), so Iq should track `1/R1`.
Effective DC resistance between the relevant nodes, computed directly from
the committed netlist snapshot
(`netlist-snapshots/20260812-000420-2d88289.spice`) by nodal analysis, and
from the `res_high_po` unit model the extraction's own two unit values solve
to (`R = 379.71 Ω + 324.83 Ω/µm × L`):

| R1 (`VB`–`VBQ`) | value | vs schematic |
|---|---|---|
| schematic, single device, `L = 5 × 7 = 35 µm` | 11 749 Ω | — |
| layout, 7 separately-contacted chained units (each pays its own head R) | 14 027 Ω | +19.4 % |
| layout + `klt extract --parasitics` star-R network | 18 208 Ω | **+55.0 %** |

Each R2 leg (`VOUT`–`VA`, `VOUT`–`VB`) moves the same way: 88 083 Ω
schematic → 107 027 Ω drawn → 138 650 Ω with the star-R network (+57.4 %).

Feeding those into the `1/R1` relation, against the schematic record's own
31.165 µA:

| model | predicted `iq` @ `tt/27 °C/3.30 V` |
|---|---|
| chained-array head resistance only | 26.10 µA |
| + star-R routing parasitics | 20.11 µA |
| **measured (this record)** | **20.00 µA** |

The full model predicts the measured value to 0.6 %, so the −35.8 % is fully
accounted for by resistance, in two separately-identifiable parts:

1. **≈ −16 % — real, a known property of the drawn array, not a surprise.**
   The layout draws R1/R2 as separately-contacted series unit devices
   (`bus_res_series`), so each unit pays the `res_high_po` model's ~380 Ω
   head resistance instead of one device paying it once. This is the same
   effect `sim/res-array-head-resistance` and `sim/res-array-resize`
   characterized at schematic level (DR-003, issue #99); the *schematic*
   `design/bandgap_core.sch` still nets out as one lumped device per leg, so
   the 2026-08-03 records do not contain it. No apples-to-apples
   chained-sizing schematic-level Iq record exists to isolate it directly —
   that gap is noted below rather than fabricated.

2. **≈ −23 % — an extraction artifact, not a property of the silicon.**
   See below.

## Finding: the star-R network double-counts the poly resistor bodies

`klt extract --parasitics` builds a per-net star: one series R per device
terminal into a net hub, sized from the net's own conductor squares. Its poly
conductor role measures the net's shapes on `poly.drawing` (66/20) and
subtracts **only** the MOS gate regions — the drawn `res_high_po` bodies live
on that same `poly.drawing` layer and are *not* subtracted. So the poly a
resistor device's own model already accounts for is counted a second time as
net parasitic resistance:

- every internal node of a resistor chain reports ≈ 459 Ω, against
  ≈ 482 Ω predicted by 10 squares (the two abutting 5 µm × 1 µm unit bodies)
  × the deck's 48.2 Ω/sq generic poly value — a 5 % match, which is what
  identifies the mechanism;
- summed over the chains this is the +29.5 … +29.8 % inflation tabulated
  above, i.e. ≈ 6 µA of the 11 µA Iq delta.

Filed generically (tool-scoped, no design detail) as
[2AMLogic/klayout-tools#800](https://github.com/2AMLogic/klayout-tools/issues/800),
per this repo's canary-block friction protocol. **The record is left exactly
as measured** — issue #16 says divergence is a finding to investigate, not
something to average away — but the number to carry forward as "the layout's
Iq" is bracketed by 20.0 µA (as-extracted, this record) and ≈ 26.1 µA (the
same layout with the double-counted poly removed). Both are inside the
ratified `< 50 µA` target with margin, so the spec line is not in question at
either end of the bracket; the artifact matters for how much of the delta is
attributed to the layout.

A secondary observation from the same extraction, not filed separately
because it does not move this measurement: `VDD` reports 75.7 kΩ of net
resistance split across 120 terminal legs (≈ 630 Ω each) for a drawn met1/met2
power bus. That is the documented conservative bias of the
equivalent-rectangle square count on a many-fragment net; at this block's
µA-level branch currents it contributes millivolts.

## Update (2026-09-10, issue #279): re-run against the post-#193 chained-array design — divergence narrows

Issue #279 re-ran this bench (and its schematic-level sibling) against the
current design after issue #193 changed `design/bandgap_core.sch`'s resistor
network (chained-array model, `n_r2` 50 → 51). New records:
`sim/quiescent-current/records/20260909-232410-e8e2e46.md` (schematic,
supersedes `20260816-085818-69a8867`) and
`sim/quiescent-current-post-layout/records/20260909-232410-e8e2e46.md`
(post-layout, supersedes `20260815-035028-001d1b7` — this record is also the
bench's **first ratified-graded** record; the superseded one still cited the
draft spec text), both against the routed layout report
`layout/bandgap-core/reports/20260817-020222-13476b7/`.

Both records are `Overall: PASS 45/45`, well inside the ratified `< 50 µA`
target: schematic Iq 20.08–32.82 µA, post-layout 14.61–26.11 µA. The spec
verdict does not change.

**The extraction-driven divergence narrowed.** The "Attributed cause" section
above measured a **−35.8 %** mean Iq shift (post-layout below schematic) on
the design current at that time. Recomputing the same per-corner percentage
delta on this cycle's paired records gives a **mean of −23.8 %** (range −27.2
to −19.5 % across the 45 corners) — still the same direction and still driven
by the same mechanism (the star-R network double-counting the drawn resistor
body's own resistance, filed as
[2AMLogic/klayout-tools#800](https://github.com/2AMLogic/klayout-tools/issues/800),
still unfixed in the installed `klt` build), but smaller in magnitude than
before. This is consistent with the resistor-array resize itself changing R1's
baseline drawn resistance (and therefore what fraction of it the double-counted
parasitic term represents), not a change in the artifact's underlying cause.
Both ends of the artifact-bracketed range remain comfortably inside the `< 50
µA` target, so this narrowing does not change any verdict — it is reported
here per this bench's own "measured as-is, not averaged away" convention.

Per this repo's append-only convention, the "Attributed cause" and "Finding"
sections above are left exactly as written — this is a dated addendum, not a
rewrite.

## Known gaps (not closed by this record)

- No schematic-level Iq record exists at the adopted chained-array sizing, so
  part 1 above is derived from the resistance arithmetic rather than measured
  head-to-head. A schematic-level chained-sizing Iq run would close it.
- `sim/quiescent-current/experiment.json`'s `claim` string still says the
  target spec is a draft "PROVISIONAL until issue #1 ratifies it"; DR-005
  ratified it on 2026-08-11 with the same `< 50 µA` value. The manifest is
  the schematic-level experiment's and is deliberately **not** edited here
  (this record reuses it unchanged so the two are comparable), so this
  record's inherited claim head carries the stale wording. The limit itself
  is unchanged, so no verdict depends on it.

## Experiment description and record history

Moved verbatim from the "Experiments that do not go through the corner runner" table in `sim/README.md` (issue #339). The newest entry under `records/` is authoritative for the current verdict; the text below was written when the cited records were current.

**Post-layout (`provenance: extracted`) re-run of `sim/quiescent-current`'s Iq claim (issue #16)**, same extracted-layout DUT body as the row above, wrapping `sim/quiescent-current/testbench/tb_vref_iq.sch` unmodified. Runs the FULL 45-point matrix (nothing swept inside the deck, so no axis is collapsed). Its `README.md` carries the divergence finding required by issue #16 — post-layout Iq is 35.8 % below the schematic-level record, attributed to R1 growing 55 % (the drawn chained array's per-unit head resistance, plus a `klt extract --parasitics` short/wide-fragment resistance overstatement on the array's internal nodes — klayout-tools#2359; previously mis-attributed to the since-refuted klayout-tools#800, corrected by issue #283)

> **Row 6b's `#2359` attribution is unsupported, and the pending re-measurement has now happened (issue #560, 2026-11-15).**
> klayout-tools#2359 closed `completed` 2026-09-23 and its fix is present in the ratified
> `klayout-tools==0.8.0` pin. Issue #540 re-extracted the same routed GDS
> (`20260923-070209-dbd57a9`) at that pin and re-ran **row 1b/3b only**: row 1b, which shared
> this exact `#2359` cause claim, got **worse** (`vref_min` FAIL 14/15 → 15/15), so the
> claim is refuted there. The parasitic resistance did not simply fall — it redistributed,
> with `VSS` the one net that rose (+62 %, 16 013 → 25 948 Ω over 229 star arms) while
> `VOUT`/`VBQ`/`VA`/`VB` all fell 24–65 %. The re-measurement this pending status called for
> is recorded in the dated update below; the numbers above stand as the klt-0.5.0
> measurements they were.
>
> **Note on snapshot resolution:** this bench holds no local parasitics snapshot, so
> `resolve_parasitics_snapshot`'s sibling glob resolved #540's klt-0.8.0 snapshot
> (`sim/output-voltage-tc-post-layout/parasitics-snapshot/20260923-070209-dbd57a9/`, which
> sorts ahead of `sim/startup-time-post-layout/`'s). **The 2026-11-15 re-run below therefore
> measured the 0.8.0 extraction, not the 0.5.0 one its committed records used.**

## Update (2026-11-15, issue #560): re-measured at the klt-0.8.0 pin — the divergence narrows to −10.5 %, and the +55 % R1-growth figure does not survive

Issue #560 re-ran this bench on the batch fleet against the klt-0.8.0 extraction that
sibling resolution now serves for it (correction recorded above). New record:
`records/20261115-185501-d4ae166e` (supersedes `20261112-172211-ffb50731`;
`layout_provenance.parasitics_snapshot.source` =
`reused:sim/output-voltage-tc-post-layout/parasitics-snapshot/20260923-070209-dbd57a9`,
`total_resistance_ohm` 179 145.6648). `Overall: PASS`, 45/45 — the verdict does not move
and stays well inside the ratified `< 50 µA` target (matrix `iq` 17.1–31.2 µA).

The divergence moved **toward agreement**, as the pending status above anticipated for a
divider-leg claim, against the same-cycle schematic record
(`sim/quiescent-current/records/20261112-074405-f9871d93`):

| | klt 0.5.0 (superseded record) | klt 0.8.0 (this record) |
|---|---|---|
| `iq` @ `tt/27 °C/3.30 V` | 19.637 µA (−24.4 %) | 22.988 µA (**−11.5 %**) |
| mean per-corner divergence (45 points) | −23.5 % (−27.2 … −17.0) | **−10.5 %** (−14.8 … −3.5) |
| post/schematic ratio cluster | — | 0.852 … 0.965, mean 0.895 |

**Re-derived R1, same nodal method as the table above** (validated first: it reproduces
this file's August rows exactly — 18 208 Ω for R1 and 138 650 Ω for an R2 leg on the
`20260812-000420-2d88289` snapshot; the drawn-device-only figure lands on the same
14 027 Ω in both extractions, since the drawn topology is unchanged and only the star-R
values moved):

| R1 (`VB`–`VBQ`) effective DC R | value | vs schematic 11 749 Ω |
|---|---|---|
| drawn chained array, device cards only | 14 027 Ω | +19.4 % — unchanged, both snapshots |
| + klt 0.5.0 star-R network | 18 521 Ω | +57.6 % — what the "55 %" figure measured |
| + klt 0.8.0 star-R network | **15 864 Ω** | **+35.0 %** |

R2 legs move the same way: 141 253 / 141 441 Ω at 0.5.0 → 116 902 / 117 021 Ω at 0.8.0.

**Verdict on the headline claim:** the *direction* survives — extracted R1 is still well
above the schematic device, for the two separately-identifiable reasons already on file
(chained-array head resistance, plus the star-R poly-body double-count). The *magnitude*
does not: at the 0.8.0 pin the star-R term over the drawn array is +1 837 Ω (was
+4 494 Ω), consistent with the per-net falls the divider-leg parasitics shed
(`VBQ` −64.7 %, `VA`/`VB` ≈ −24.5 %, `VOUT` −41.8 %, `PN` −27.8 %), so the measured R1
growth is **+35.0 %, not +55 %**. Consistently, the divergence narrows but does not close:
the 1/R1 resistance-scaling account that predicted the 0.5.0 measurement to 0.6 % now
over-predicts the drop (head-only 21.8 µA, with-star-R 19.2 µA, measured 23.0 µA at the
tt corner), so resistance scaling alone no longer explains the residual −10.5 %. Re-fitting
that residual is issue #541's `--critical-net`/`--distributed-rc` work, deliberately out of
scope here; no ratified limit is touched by any of this.

Per the append-only convention, everything above is left exactly as written — this is a
dated addendum, not a rewrite.
