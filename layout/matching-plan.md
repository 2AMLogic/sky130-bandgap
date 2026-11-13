# Bandgap core -- floorplan and matching plan (issues #15, #62)

Written matching plan + initial placed layout skeleton for the sky130
Kuijk-style bandgap core (`design/bandgap_core.sch`, `design/error_amp.sch`).
This document states the matching-effort allocation and the reasoning
behind it; `layout/bin/gen_bandgap_routed.py` /
`layout/bin/run-bandgap-routed-flow.sh` generate, place, route and
DRC/LVS-check the cell this document describes -- see
[`layout/bandgap-core/reports/LATEST`](bandgap-core/reports/LATEST) for the
current evidence record (DRC-clean, area-budget-clean; read that record's
`record.md` first for the actual pass/fail evidence, this document is the
rationale, not the proof).

Scope, per issue #15's acceptance criteria: a floorplan + this written
matching plan, plus an *initial* placed layout skeleton that passes DRC.
This is not a tape-out-ready layout -- routing, exact spacing
optimization, and full LVS closure on the matched-device generators are
explicitly out of scope here and flagged as follow-on work in "Known
limitations" below.

> **Update (issue #62, routed layout).** Sections 4, 5, 7 and 8 below have
> been revised where issue #62's routed flow changed the facts on the
> ground -- the R2A/R2B ladder is now drawn at its **real full length**
> (92 coarse units + 40 fine trim units = the schematic's 250 um per leg,
> the issue #99/#108-resized sizing; it was 100 coarse units/270 um per leg
> before that resize, and 108 coarse units with a bolt-on ladder before
> issue #91), inter-block routing and top-level pins **are** drawn, and
> PNP/NMOS/resistor devices **do** extract with correct classes. Where a
> statement
> below is now historical, it is marked as such rather than deleted, so the
> #15 skeleton's own records stay readable against the document that
> described them. The routed flow is
> `layout/bin/run-bandgap-routed-flow.sh` /
> `layout/bin/gen_bandgap_routed.py`; its record is the newest directory
> under `layout/bandgap-core/reports/`. Read that record for measured
> results; this document remains the rationale.
>
> The #15 floorplan scripts that sentence used to name
> (`layout/bin/gen_bandgap_floorplan.py` /
> `layout/bin/run-bandgap-floorplan-flow.sh`) are **retired** (issue #215,
> once the routed flow superseded them) -- they are no longer in
> `layout/bin/`, and the routed driver above absorbed their generation,
> placement and DRC work. Where a section below still names
> them it is describing the #15 skeleton historically, against the records
> that skeleton produced; it is not pointing at a file you can run today.

> **Where the per-increment history lives (issue #499).** Section 7 used to
> carry the full narrative of every issue #62 increment (7a-7gg) inline.
> Those narratives now live, verbatim and under their original headings, in
> [`matching-plan-history.md`](matching-plan-history.md); Section 7 keeps a
> two- to three-line entry for each one under the same heading, the full
> text of the sections other files cite directly (7t, 7x, 7bb, 7cc, 7ff),
> and the latest scoreboard table. Nothing was deleted from the tree -- the
> text moved one file across, so the "marked as historical rather than
> deleted" convention above still holds.

## 1. Matching-effort allocation, driven by issue #12's contributor breakdown

Issue #12's Monte Carlo mismatch analysis
(`sim/monte-carlo-untrimmed/records/20260803-142259-544cc5e.md`) isolated
three independent local-mismatch contributors to the untrimmed output
spread by re-running the same testbench with each of the other two
families' PDK mismatch coefficients zeroed. Its own "Contributor breakdown"
table:

| T (degC) | PNP array 1 sigma (mV) | resistor network 1 sigma (mV) | amp/mirror MOS 1 sigma (mV) | measured sigma(all) (mV) |
|---|---|---|---|---|
| -40 | 1.157 | 1.644 | 4.465 | 4.879 |
| 27 | 1.410 | 2.152 | 4.434 | 4.988 |
| 125 | 1.958 | 2.768 | 4.197 | 5.205 |

**The amp/mirror MOS term dominates at every temperature** -- roughly
4.2-4.5 mV of a 4.9-5.2 mV total 1 sigma, i.e. its variance alone (the RSS
decomposition closes to within 0.965-0.996 of the measured total, per that
record's own closure check) accounts for the large majority of the
untrimmed spread. The PNP array and resistor network terms are both
smaller and comparable in magnitude to each other, with the resistor term
growing fastest with temperature (2.77 mV at 125 degC vs. 1.96 mV for the
PNP array).

Issue #9's error-amplifier offset budget
(`design/error-amp-offset-budget.md` Sections 1-4) decomposes that
dominant amp/mirror term one level further, by device group, at 27 degC
(N = 300 Monte Carlo, `sim/error-amp-offset-mc/`):

| Group | W x L x mult | area | contribution to sigma(VOS) |
|---|---|---|---|
| MP1/MP2 input pair | 20 x 10 x 16 | 3200 um^2 each | 0.300 mV |
| MN1-MN4 loads/mirrors | 8 x 20 x 4 | 640 um^2 each | 0.301 mV |
| MP3/MP4 PMOS mirror | 6 x 20 x 8 | 960 um^2 each | 0.190 mV |

Two findings drive this plan's priority order directly:

1. **The amp's input pair and its NMOS load/mirror quad contribute
   essentially equally** (0.300 vs 0.301 mV) -- neither can be treated as
   the "real" matching-critical group with the other as secondary. Both are
   top priority. The PMOS mirror (MP3/MP4) contributes meaningfully but
   less (0.190 mV) -- still matched, but not over-built at the other two
   groups' expense.
2. Through the core's measured 9.65 offset gain
   (`design/error-amp-offset-budget.md` Section 1), this amplifier random
   offset is **74-90% of the untrimmed output variance** at every
   temperature (Section 6) -- i.e. it is not just the largest of three
   comparable terms, it is close to the whole story.

**Allocation, in priority order:**

| Priority | Matched group | Why |
|---|---|---|
| 1 (highest) | Amp input pair (MP1/MP2) | Dominant single contributor (#12), tied with the NMOS quad for largest single-group share of sigma(VOS) (#9) |
| 1 (tied) | Amp NMOS load/mirror quad (MN1-MN4) | Same as above -- #9 measured these two groups contribute equally; layout effort must not favor one over the other |
| 2 | Amp PMOS mirror (MP3/MP4) | Smaller but non-negligible share of sigma(VOS) (0.190 mV of 0.525 mV measured); still common-centroid, not an afterthought |
| 3 | Resistor network (R1/R2A/R2B + trim) | Second-largest of the three #12-isolated families; grows fastest with temperature, so the 125 degC corner is where under-matching it would show up first |
| 4 | PNP array (Q1/Q2) | Smallest of the three #12-isolated families at every temperature, but not zero, and this is the group whose own 8x arraying (already reflected in the skeleton's device counts) is what took its own local mismatch down from a much worse un-arrayed figure (`design/device-characterization-summary.md` Section 4) -- still requires common-centroid + dummy ring, per acceptance criteria and because it still consumes 0.29-0.49% of a 1.2 V output at 1 sigma on its own |

This is the reasoning `layout/bin/gen_bandgap_floorplan.py`'s block list and
placement follow: every matched group gets a common-centroid/cross-quad
layout with dummies, but the amp's three groups (and within that, the
input pair and NMOS quad specifically) are where a layout reviewer's
scrutiny should concentrate first if area or time forces a tradeoff later.

### 1a. The R2 leg's coarse/fine split, and why priority 3's budget is unchanged by it

Issue #91 re-decomposed each R2 divider leg. It used to be drawn as 54
coarse 5 um units (270 um) with a 16 x 1 um trim ladder wired in series
*after* it — 286 um, 16 um more than the schematic states, and a ladder
whose taps could only add. It is now drawn as **50 coarse 5 um units
(250 um) plus 20 fine 1 um units (20 um)**, so the code-0 tap is exactly the
specified 270 um and every tap short of it subtracts. The full argument and
the measured evidence are in Section 7r; what belongs here is its effect on
this section's *matching* budget, which has to be argued rather than
assumed:

- **Total drawn resistor body per leg is identical: 270 um x 1 um.** Before,
  the leg was 270 um of coarse body *plus* 16 um of trim body carrying the
  same current; now it is 250 + 20 of the same total. Random mismatch of a
  poly resistor scales as `sigma(dR/R) = A_rho / sqrt(W*L)` over the body
  that carries the current, so the leg's own 1-sigma is set by `W*L` =
  270 um^2 either way. The change is area-neutral in the only variable that
  term depends on. (Strictly, it is a small *improvement*: the old leg's
  DC path was 286 um^2, i.e. `sqrt(286/270)` = 1.03x more area and therefore
  ~1.5% *less* random mismatch — but 6% of the leg was length the schematic
  never asked for, so trading that back is a spec fix, not a matching
  regression, and the 1.5% is well inside the noise of the resistor term's
  own 1.64-2.77 mV contribution above.)
- **Both legs change identically, so the R2A/R2B *ratio* — the quantity
  that matters — is untouched.** K = R2/R1 is set by matched *ratios*, and
  both legs are drawn from the same two interdigitated arrays, at the same
  unit counts, in the same fold. Nothing here is asymmetric between the
  legs.
- **The number of series units per leg is unchanged at 70** (was 54 + 16,
  now 50 + 20), so the count of unit-to-unit series joints — the other
  per-unit random term, contact resistance — is the same. What moves between
  the two arrays is *which* array carries a given micron, not how many
  junctions the current crosses.
- **The one real cost is fill efficiency, and it is an area cost, not a
  matching one.** A 1 um unit on a 0.5 um pitch spends 1/1.5 of its footprint
  on body; a 5 um unit spends 5/5.5. Moving 4 um/leg from coarse to fine
  therefore grows the composed cell slightly (45,508 -> 45,968 um^2, +1.0%,
  still 8% inside the 0.05 mm^2 budget — Section 6). It does not change
  `W*L`, which is what the mismatch term integrates.

The net effect on this section's priority-3 allocation is therefore **nil**:
the resistor network's contribution to the untrimmed spread (Section 1's
1.64-2.77 mV) is unchanged, and no effort needs to be reallocated between
the five matched groups.

## 2. Device inventory

From `design/bandgap_core.sch` and `design/error_amp.sch` (read-only
references for this issue; not modified here):

| Device | Role | Geometry | Matched against |
|---|---|---|---|
| Q1 | CTAT PNP | m=8 x `pnp_05v5_W0p68L0p68` (0.4624 um^2/unit) | itself (8x array) |
| Q2 | PTAT PNP | m=8 x `pnp_05v5_W3p40L3p40` (11.56 um^2/unit) | itself (8x array) |
| R1 | dVBE-to-current leg | `res_high_po`, W=1um, L=35um (7 x 5um unit segments) | R2A/R2B via the K=R2/R1 ratio |
| R2A | VOUT-side divider leg (branch A) | `res_high_po`, W=1um, L=270um at DR-002 code 0, drawn as 50 x 5um coarse + 20 x 1um fine unit segments | R2B |
| R2B | VOUT-side divider leg (branch B) | `res_high_po`, W=1um, L=270um at DR-002 code 0, drawn as 50 x 5um coarse + 20 x 1um fine unit segments | R2A |
| trim taps | downward-only ladder-tap trim (DR-002) | `res_high_po`, W=1um, 1um/code, code 0..-16 certified (0..-20 drawn), both legs | the last 20um *of* each R2A/R2B leg, not an addition to it -- integrated into the same interdigitated array pair (this issue's acceptance criterion; see Sections 1a and 7r) |
| MPOUT | core PMOS output mirror | mult=2 x W=8/L=2 `pfet_g5v0d10v5` | MPAMP |
| MPAMP | core PMOS bias mirror | mult=2 x W=8/L=2 `pfet_g5v0d10v5` | MPOUT |
| MP1/MP2 | amp PMOS input pair | mult=16 x W=20/L=10 `pfet_g5v0d10v5` | each other |
| MN1/MN2 | amp NMOS diode loads | mult=4 x W=8/L=20 `nfet_g5v0d10v5` | each other, and MN3/MN4 (one 4-device group per #9) |
| MN3/MN4 | amp NMOS mirror outputs | mult=4 x W=8/L=20 `nfet_g5v0d10v5` | each other, and MN1/MN2 |
| MP3/MP4 | amp PMOS mirror | mult=8 x W=6/L=20 `pfet_g5v0d10v5` | each other |
| MCC | amp compensation cap (PMOS-as-cap) | mult=16 x W=30/L=20 `pfet_g5v0d10v5` | single-ended -- not a matched pair |

## 3. Floorplan

Four bands, stacked and horizontally centered (see
`layout/bin/gen_bandgap_floorplan.py`'s `place_blocks()` for the exact,
bbox-derived placement math -- nothing below is a hardcoded pixel
coordinate):

```
 +------------------------------------------------------------------+
 |                  outer guard ring (VSS tap, whole cell)          |
 |  +--------------------------------------------------------------+|
 |  |  MN3/MN4        MP3/MP4              MPOUT/MPAMP              ||  row 3
 |  |  (own ring)     (own ring)            (own ring)              ||
 |  |----------------------------------------------------------------||
 |  |  MP1/MP2 input pair (own ring)     MN1/MN2 (own ring)          ||  row 2
 |  |----------------------------------------------------------------||
 |  |  R2A/R2B interdigitated  R1        trim taps                   ||  row 1
 |  |----------------------------------------------------------------||
 |  |  Q1 (own collector ring)   Q2 (own collector ring)              ||  row 0
 |  +--------------------------------------------------------------+|
 +------------------------------------------------------------------+
```

Row order (bottom to top, increasing y in the generated skeleton):

- **Row 0 -- PNP array.** Q1 (CTAT, small unit, 2x4 common-centroid, 1
  dummy column/side) and Q2 (PTAT, large unit, same arrangement)
  side by side, each with its own collector/substrate guard ring
  (`bjt_array`'s `add_collector_ring`). They are not interleaved with each
  other at the unit-device level -- the PDK offers only two fixed PNP
  geometries, so Q1's and Q2's units cannot physically share a common
  centroid cell the way two same-size devices can. Placing the two arrays
  immediately adjacent, each internally common-centroid and dummy-ringed,
  is the practical equivalent: it minimizes the physical separation (and
  therefore the die-gradient exposure difference) between "the CTAT leg's
  average location" and "the PTAT leg's average location," which is what
  actually matters for the VA/VB comparison the amplifier makes.
- **Row 1 -- resistor network.** R2A/R2B as one interdigitated **coarse**
  ladder (alternating unit segments -- see "Skeleton vs. real target counts"
  below for why the skeleton draws 16 of the real 100), R1 as its own
  matched group (same flavor/orientation, not interdigitated with R2A/R2B
  since it is a different nominal value with no same-value partner), and the
  downward-only trim taps as a second, **fine** array of the same flavor and
  orientation, interdigitated the same way and carrying the last 20 um of
  each leg (this issue's acceptance criterion: trim segments integrated into
  the array, not a separate bolt-on structure).

  **Interdigitation scheme, both arrays.** `bus_res_series` chains unit
  index `i` into leg `i mod 2`: leg A owns the even indices, leg B the odd,
  so the two legs alternate unit by unit across each array and share a
  centroid to first order. That is true of the coarse array (100 units, 10
  folded rows of 10) and of the fine one (40 units, 4 folded rows of 10)
  alike, which is what makes the split of Section 1a matching-neutral: the
  two legs are drawn from the *same* pair of interdigitated arrays at every
  granularity, never one leg coarse and the other fine.

  The split is **50 coarse + 20 fine per leg**, not 54 + 16 (issue #91).
  The trim ladder is the leg's last 20 um, so the code-0 tap is exactly
  the schematic's 270 um and every other tap subtracts; drawn the old way,
  in series after a full-length leg, it made the leg 286 um and could only
  add. Section 7r has the measurement; Section 1a has the matching-budget
  argument.
- **Row 2 -- amp input pair + NMOS loads.** MP1/MP2 (cross-quad
  common-centroid PMOS input pair, in an n-well, own guard ring) and
  MN1/MN2 (cross-quad common-centroid NMOS diode loads, own guard ring),
  adjacent so the two top-priority-tied groups from Section 1 sit in the
  same band, closest to each other of any two matched groups in this
  floorplan.
- **Row 3 -- amp mirrors + core mirror.** MN3/MN4 (NMOS mirror outputs,
  own guard ring), MP3/MP4 (PMOS mirror, own guard ring, in an n-well),
  and MPOUT/MPAMP (the core's own PMOS output/bias mirror, own guard ring,
  in an n-well).

One overall guard ring (`guard_ring` generator, tap ring + well tie)
encloses all four rows, sized and centered from the composed content's own
reported bounding box (`gen_bandgap_floorplan.py`'s `RING_MARGIN_UM`
clearance on every side) -- not a fixed placeholder size, so it stays
correct if any block's size changes.

See
[`layout/bandgap-core/reports/LATEST/renders/overview.png`](bandgap-core/reports/LATEST/renders/overview.png)
(resolve `LATEST` to the current record id) for a rendered top-down view:
every matched group's own inner ring and interdigitated/cross-quad
striping is visible at that scale, which is this issue's test-plan item
for visually verifying common-centroid symmetry and dummy-ring coverage.

## 4. Skeleton vs. real target counts

Every block draws the real schematic W/L/mult/rows/cols/splits **except**
the R2A/R2B interdigitated ladder, which the skeleton draws at reduced
scale:

| Block | Skeleton count | Real target | Why reduced |
|---|---|---|---|
| `pnp_ctat` / `pnp_ptat` | 8 units each (2x4) | 8 units each | drawn 1:1 |
| `res_r2` (R2A/R2B) | 16 units (8/leg) -- **superseded, see below** | 96 coarse units (48/leg), with `res_trim`'s 40 fine units carrying the rest of the same 250 um leg (issue #106/#112's re-partition, forced by `r_lseg_trim` halving 1 -> 0.5 um; was 92 coarse units (46/leg) at the issue #99/#108-resized 250 um leg, 100 units (50/leg) at the pre-resize 270 um leg, and 108 units (54/leg) before issue #91 re-decomposed the leg -- see Sections 1a, 7r, 7y and 7aa) | *(historical, #15)* a single-row `res_array` at 108 units is ~710 um long (measured directly: `klt gen res_array --params '{"num":108,...}'` reports `bbox_um.x1 - x0 = 709.6`) -- pairing that with any other block in a floorplan forces the whole composition's bounding box past the 0.05 mm^2 budget on width alone, even though the segments' own drawn area is small. `klt gen res_array` had no row-folding/meander parameter to keep a long unit-resistor string's *footprint* compact the way `mos_array`/`bjt_array`'s `rows`/`cols` do -- filed as new friction, [2AMLogic/klayout-tools#415](https://github.com/2AMLogic/klayout-tools/issues/415). |
| `res_r1` | 7 units | 7 units | drawn 1:1 (small enough to be tractable at full scale) |
| `res_trim` | 32 units (16/leg) | 40 units (20/leg) | drawn 1:1 -- 20 fine 0.5 um units per leg, the last 10 um *of* that leg, giving DR-002 codes 0..-20 of which 0..-16 are certified (issue #91; was 20 fine 1 um units/last 20 um before issue #106/#112 halved the fine unit body length; was 32 units (16/leg) wired in series *after* a full-length leg before issue #91) |
| `amp_input_pair` | mult=16 (splits=16) | mult=16 | drawn 1:1 |
| `amp_nload` / `amp_nmirr` | mult=4 each | mult=4 each | drawn 1:1 |
| `amp_pmirr` | mult=8 (splits=8) | mult=8 | drawn 1:1 |
| `core_mirror` | mult=2 (splits=2) | mult=2 | drawn 1:1 |

### 4a. Ladder scale reduction: closed (issue #62)

**2AMLogic/klayout-tools#415 landed** (merged upstream via
klayout-tools#418), adding `res_array`'s `rows` fold parameter. The routed
flow (`layout/bin/gen_bandgap_routed.py`) therefore draws the R2A/R2B ladder
at its **real full-length count** -- the schematic's whole 270 um per leg,
never a reduced one:

| | skeleton (#15) | routed (#62) | routed, post-#91 | routed, post-#99/#108 | routed, post-#106/#112 |
|---|---|---|---|---|---|
| `res_r2` unit count | 16 | 108 (2 legs x 54 coarse) | 100 (2 legs x 50 coarse) | 92 (2 legs x 46 coarse) | **96** (2 legs x 48 coarse) |
| `res_trim` unit count | 32 (2 legs x 16) | 32 (2 legs x 16), in series *after* the leg | 40 (2 legs x 20), the last 20 um *of* the leg | 40 (2 legs x 20), unchanged | **40** (2 legs x 20), unit body length halved 1 -> 0.5 um |
| drawn length per leg | -- | 286 um (spec: 270) | 270 um (spec: 270) | 250 um (spec: 250) | **250 um** (spec: 250, unchanged) |
| `res_r2` footprint | ~110 x 12 um, 1 row | 100.9 x 12.2 um, 9 folded rows | 75.6 x 13.6 um, 10 folded rows | 75.6 x 13.6 um, 10 folded rows | **75.6 x 13.6 um**, 10 folded rows (unchanged; re-verified, not re-derived) |
| `res_trim` footprint | -- | 22.9 x 5.2 um, 4 folded rows | 27.6 x 5.2 um, 4 folded rows | 27.6 x 5.2 um, 4 folded rows | **21.6 x 5.2 um**, 4 folded rows (shrinks with the halved unit body) |
| composed cell bbox | 35,763 um^2 | 45,508 um^2 | 45,968 um^2 | 45,968 um^2 (measured identical) | **45,968 um^2** (measured identical) |
| budget | 50,000 um^2 | 50,000 um^2 | 50,000 um^2 | 50,000 um^2 | 50,000 um^2 |

Folding turns the ladder from the floorplan's width-dominating block into
one of its smaller ones: the whole routed cell -- at the real length, with
routing and the cell-level guard ring -- still lands ~8% inside the
0.05 mm^2 budget. `res_r1` (n_r1=7) was already 1:1 and stays so; the trim
ladder is folded into 4 rows for the same footprint reason.

The post-#91 column is issue #91's re-decomposition (Section 7r). Note what
it does and does not move: the drawn *length* per leg goes 286 -> 270 um,
which is the whole point, while the composed bbox goes **up** 1.0%. That is
not a contradiction -- it is fill efficiency. Moving 4 um/leg from 5 um
units (5/5.5 of their pitch is body) to 1 um units (1/1.5 is body) costs
footprint even as it removes drawn resistor body, and the coarse array's own
fold changed from 9 ragged rows to 10 even ones. The issue's own scope note
predicted a small area *improvement* from the shorter leg; the measured
result is a small increase, disclosed here rather than quietly restated.
Both are far inside budget, and Section 1a argues the matching consequence
(none).

The last column is issue #99/#108's resize propagation (Section 7y):
`n_r2` 54 -> 50 (DR-003's closure), re-transcribed into the same coarse/fine
split shape at the shorter 250 um leg (`N_R2_COARSE` 50 -> 46, `N_R2_TRIM_UNITS`
unchanged at 20). `res_r2`'s own `rows` fold is kept at 10 -- unchanged from
before, and re-verified (not re-derived) against the new 92-unit count; see
that block's own `rows` comment in `gen_bandgap_routed.py` for why every true
divisor of 92 was tried and rejected (each pushed the composed cell over
budget) before re-verifying 10 clean. The measured `res_r2` footprint and the
composed cell bbox come out identical to the post-#91 figures to the um^2 --
8 fewer coarse units did not move the fold's own bounding box at this row
count, so all of the resize's area effect is absorbed by the coarse-unit
count without changing the block's footprint at all.

The final column is issue #106/#112's `r_lseg_trim` propagation (Section
7aa): DR-002's revision halves `r_lseg_trim` 1 -> 0.5 um, which forces
`N_R2_COARSE` 46 -> 48 to hold the leg fixed at 250 um (`N_R2_TRIM_UNITS`
stays 20 -- the revision re-partitions the fixed leg length, it does not
touch the fine ladder's unit count). `res_r2`'s `rows` fold is again kept
at 10, re-verified (not assumed) against the new 96-unit count: all 94
fold-turn links route clean. The composed cell bbox again comes out
identical to the prior figure to the um^2 -- the 4 extra coarse units'
length (20 um) is offset almost exactly by the fine ladder's 40 units each
losing 0.5 um of body (also 20 um), so this increment's net effect on the
budget is essentially zero even though both arrays' own unit counts and
footprints moved.

The area-budget claim in Section 6 was previously caveated as "does not yet
include the R2A/R2B ladder at its real count". That caveat is now closed.

## 5. Supply/ground and guard-ring strategy

Consistent with the measured PSRR (77.7 dB at DC, worst case sf/125 degC/
2.97 V, `sim/error-amp-loop/` record `20260803-085320-e599e30`, per
`design/error-amp-offset-budget.md` Section 5):

- **Every matched group gets its own local guard/collector ring**
  (`bjt_array`'s `add_collector_ring`, `diff_pair`'s `add_guard_ring`),
  tied to VSS (NMOS/PNP groups) or wrapping a VDD-tied n-well (PMOS
  groups). This keeps substrate noise injected near one matched group from
  coupling preferentially into a neighboring group's devices -- a supply
  bounce that reaches the amp's input pair asymmetrically (relative to its
  own mirror devices) would show up directly as VOS, the term Section 1
  identified as dominant.
- **One overall cell-level guard ring** (VSS tap + well tie) encloses the
  whole composed floorplan, isolating the analog cell from whatever
  digital or other circuitry sits next to it in a full-chip integration --
  standard practice for a noise-sensitive analog reference, and the
  layer this issue's DRC-clean skeleton actually draws and checks (see
  Section 3).
- **PMOS groups** (MP1/MP2, MP3/MP4, MPOUT/MPAMP) sit in their own n-wells,
  tied to VDD via each block's own guard ring -- `diff_pair`'s
  `flavor="pfet"` draws this well automatically.
- **Metal-trunk VDD/VSS routing and the trim-tap connectivity** (which
  code-select tap on the trim ladder feeds which net) were deferred by #15.
  Issue #62 draws both -- see Section 5a.

### 5a. What issue #62's routed flow actually draws (second increment)

**Per-matched-group rings are back on.** Upstream
[klayout-tools#441](https://github.com/2AMLogic/klayout-tools/issues/441)
added `ring_gap_side`/`ring_gap_um`, cutting one routing opening through a
ring band and reporting it as a `GAP_<side>` port the router may cross. This
retires the first increment's trade-off (below): every matched group in the
routed layout now carries its own guard/collector ring **and** is wired to
the rest of the circuit, closing the matching-quality regression that
increment recorded.

> Historical note (first increment, PR #64): `klt gen-compose`'s router
> rejected every route to a non-tap port on a ringed block, forcing a choice
> between a group's own ring or its connectivity -- filed as
> [klayout-tools#434](https://github.com/2AMLogic/klayout-tools/issues/434)
> (now closed via #441, used above).

**Intra-block bussing is now drawn, on met1.** The router still exposes only
one routing-metal role (`li1`, the same layer every generator draws its
device pads on) --
[klayout-tools#433](https://github.com/2AMLogic/klayout-tools/issues/433)'s
merged fix (#439) made a same-block bus attempt fail *visibly* rather than
silently short, but did not make it *drawable*, and the follow-up capability
request ([klayout-tools#454](https://github.com/2AMLogic/klayout-tools/issues/454))
is still open. This flow therefore draws every intra-block bus itself with
`klt draw`, on met1 over mcon -- the sky130 extraction deck's own second
conductor and via, which `klt extract` already wires up generically. See
`layout/bin/met1_bus.py` and `gen_bandgap_routed.py`'s `MET1_BUS_NOTE`. This
is what turns the coarse ladder (108 units when this was written, 100 since
issue #91 re-decomposed the leg) and its fine trim ladder into two real
series resistors, and each 8-unit PNP array into one real `m=8` device,
instead of N unconnected units.

**Inter-block nets are now drawn on met1 too**, for the same routing-metal
reason -- `gen-compose` only ever routed 2-pin nets between channel-adjacent
blocks; met1 does not care about crossing other blocks' interiors. **11 of
12** declared inter-block nets route; measured against
`design/bandgap_core.sch`'s own node list (not this flow's own
`connectivity[]` declaration), **6 of 12 schematic inter-block nets are
fully drawn across every block they reach** (up from 4/12 in the first
increment) -- see the routed record's "Schematic inter-block nets" table for
the per-net breakdown.

**What still isn't drawn, and why.** *(Superseded by Section 7b -- kept as
the record of what the second increment was blocked on.)* At that point every
remaining gap -- the unrouted 12th net, the rest of the partial schematic
nodes, and all MOS finger bussing -- terminated on a MOS gate, because every
`klt gen` MOS generator on sky130 drew gate poly with **exactly** the active
region's extent (poly and diff sharing both edges), leaving no landing area
outside the channel a contact could legally sit on. Filed as
[klayout-tools#461](https://github.com/2AMLogic/klayout-tools/issues/461),
**closed via klayout-tools#474**, and the fourth increment draws all of it:
see Sections 7b and 8. This flow deliberately never drew a contact over the
channel to make a number move in the meantime -- that would have been illegal
geometry the curated DRC deck simply doesn't happen to model, not real
connectivity.

The routed record's "Schematic inter-block nets: drawn vs. labelled only"
table is the measured, per-net version of this. Issue #62's criterion 1 is
scored **PARTIAL** on it -- the reference netlist is *not* adjusted to
accommodate any of it (an earlier revision bridged `AOUT`/`GDRV` with a
0-ohm device -- that stays removed).

### 5b. Corrections and additions from the third increment (issue #62)

The paragraph above was **not accurate**, and the third increment's first
job was to find out how much of "blocked on the gate gap" was really the
gate gap. Four things were not:

1. **`VSS` was never gate-blocked -- it was simply failing to route.** Its
   terminals are four NMOS sources and two PNP base ties; not one of them is
   a gate. The single unrouted hop (bottom-left PNP trunk to the top-right
   NMOS mirror) was losing its corridor to an earlier net, and the router
   had no way to express the path that exists: out of the block into a free
   vertical channel, across on a free horizontal band, and back in. Its
   four-segment escapes only offered lateral shifts of 1.2-3.6 um. The
   router now derives the floorplan's free channels and bands from the
   placed block extents and tries paths through them (`free_channels()` /
   `_channel_paths()`), and every declared net routes -- `unrouted: 0`,
   still with zero drawn-short conflicts and clean DRC. It is also ~8x
   faster, because the right path is now found immediately instead of after
   a long blind offset sweep.
2. **`GDRV` was never declared at all**, on the stated grounds that it is a
   gate node. Two of its four terminals are gates (MPOUT/MPAMP); the other
   two are MP4's and MN3's **drains**, ordinary li1 pads in two different
   blocks. That link is drawn from this increment on, so `GDRV` is a
   partially drawn node rather than a pair of disconnected labels. Its gate
   end stays open and stays disclosed.
3. **Bulk terminals were floating.** The reference puts every MOS bulk on a
   supply (`... VDD VDD pfet` / `... VSS VSS nfet`). Each `diff_pair`'s
   guard ring *is* that bulk tie and reports it as `TAP_*` on li1 -- nothing
   about the gate gap applies -- but nothing connected them, so every PMOS
   group's well extracted as an anonymous net. They are on the supply trunks
   now; the extracted PMOS bulk terminal reads `VDD` instead of `$186`.
   (The NMOS bulk still reads `vsubs`: sky130's deck ties every NMOS body to
   its global substrate net by `connect_global` rather than deriving it from
   drawn geometry. That is documented deck behaviour, and `klt lvs` reports
   it as a coverage warning of its own -- not something this layout can
   change by drawing more metal.)
4. **The layout was asserting `VOUT` and `TAIL` are one node.** A `pins[]`
   entry labels a *port*, i.e. a pad. The pin selector and the router kept
   separate "already used" sets, so `VOUT`'s label landed on
   `core_mirror.M2_1_D` -- MPAMP's drain, and the pad the drawn `TAIL` net
   contacts. The previous increment's extracted netlist therefore contains a
   net named `TAIL|VOUT`. DRC is clean and the drawn-short check passes,
   because the collision is between *labels*, through a pad, not between
   met1 rectangles. `klt extract` emits it with an empty `warnings[]` and
   `klt lvs` compares it without comment -- filed upstream as
   [klayout-tools#470](https://github.com/2AMLogic/klayout-tools/issues/470),
   where the tool gap is the silence rather than the collision. The two
   selectors now share one claimed-pad set, and the flow gates on a
   scan of the extracted netlist for any `A|B` net name.

**Device halves are now bound, once.** A `diff_pair` reports two port
families (`M1_*`/`M2_*`) and which one is which schematic transistor is this
flow's choice, not the generator's. Nothing was making that choice: each net
took whichever pad sat nearest its own centroid. So `PN` and the `AOUT`
label both landed on amp_pmirr's `M2` -- MP3's drain and MP4's drain on one
physical transistor -- and amp_nload's `D1` route and `D1_GATE` label
disagreed about which half is MN1. `MOS_HALVES` in
`layout/bin/gen_bandgap_routed.py` binds every half to a named schematic
device, and both routes and gate pin labels resolve through it. Neither
error was visible to DRC or to the drawn-short check: every terminal
involved is legal, well-separated metal.

**Net effect on the acceptance criteria.** Criterion 1 stays **PARTIAL** at
6/12 fully drawn -- the six that remain short are genuinely short, and this
increment's honest gain is that the coverage table now credits partially
routed nodes for the blocks they *do* join (union-find over the routed hops,
largest connected component) instead of scoring an all-or-nothing net as
zero. Criterion 4 stays **NOT MET**: `mismatch_count` 365 -> 355, with
`devices.matched` still 0, because no split MOS group can collapse into the
`m=N` device the schematic states while every gate is unreachable. That
number will not move materially until klayout-tools#461 lands. *(It landed;
the fourth increment measures 9/12 and `mismatch_count` 106 -- Section 7b.)*

## 6. Area budget

| Item | Area |
|---|---|
| Amp transistors (MP1/MP2 + MN1-MN4 + MP3/MP4), analytic | 10,880 um^2 (`design/error-amp-offset-budget.md` Section 4) |
| MCC compensation cap, analytic (single-ended, not a matched pair -- see Section 2) | 9,600 um^2 |
| Core PNP + resistor + mirror devices, analytic (drawn/emitter area only) | ~735 um^2 (MPOUT+MPAMP 64, Q1 3.7, Q2 92.5, R1 35, R2A+R2B 540) |
| **Analytic device total** | **~21,215 um^2** |
| **Skeleton composed floorplan bbox** (measured, #15 -- includes guard rings, dummies, spacing, and the reduced R2A/R2B count from Section 4) | **35,763 um^2** (`layout/bandgap-core/reports/20260803-192947-e7a30b4/record.md`) |
| **Routed composed floorplan bbox** (measured, #62 second increment -- includes intra-/inter-block met1 bussing, per-group **and** cell-level guard rings, and the R2A/R2B ladder at its real count) | 40,019 um^2 |
| **Routed composed floorplan bbox, current** (measured -- adds the met2 escape plane of Section 7q and issue #91's coarse/fine leg decomposition) | **45,968 um^2** (`layout/bandgap-core/reports/LATEST/record.md`) |
| **Budget** | **50,000 um^2 (0.05 mm^2)** |

The skeleton's measured footprint (35,763 um^2) was within budget with ~29%
margin, but did **not** include the R2A/R2B ladder at its real count. Issue
#62 closed that gap (Section 4a): the routed cell draws the full ladder
*and* its inter-block routing, and measured 40,019 um^2 at that increment
-- ~20% inside the 50,000 um^2 budget (the second increment's restored
per-group guard rings and met1 busing cost ~1,848 um^2 versus the first
increment's ring-off, unbussed 38,171 um^2, still comfortably inside
budget). The current cell measures **45,968 um^2**, ~8% inside budget: the
met2 escape plane (Section 7q) and issue #91's coarse/fine leg
decomposition (Section 7r, +460 um^2 of fill inefficiency for the same
270 um of drawn resistor body) account for the rest. The budget claim now
covers the real device counts and the real drawn leg length, not a
reduced-scale stand-in.
`design/device-characterization-summary.md`'s own note on `MPOUT`/`MPAMP`
sizing (a potential 6.25x per-unit-area increase to size E) is a small
fraction of the remaining ~11,800 um^2 margin and is not expected to be a
blocker on its own. The largest un-budgeted item is now MCC, still carried
analytically (9,600 um^2) rather than drawn -- adding it would consume most
of the remaining margin, so it is the next real area question.

**Update (Section 7bb, 2026-08-11 operator ruling on issue #62):** a
zero-incremental-footprint `cap_mim` overlay for `MCC` was checked and found
tooling-infeasible today (2AMLogic/klayout-tools#775, filed with a
three-geometry reproduction), not area-infeasible -- met3/met4/met5 are
entirely empty across this cell's footprint, far more than the ~14,500 um^2
a 29 pF MIM cap needs. The fallback path (draw `MCC` in-plane as the MOS
cap it is today, +~20,800 um^2 projected) is gated on
`spec/decision-records/DR-007-mcc-area-budget.md` (status: proposed), which
proposes relaxing this section's 50,000 um^2 budget line -- not yet
ratified, so the budget above remains the enforced gate
(`gen_bandgap_routed.py`'s `budget_um2`) until DR-007 (or an amendment to
it) is decided.

**Update (Section 7cc, thirty-first increment):** `MCC` is now drawn (a
`pfet` MOS-cap block, `amp_cc`, matching the schematic's own device
exactly). Measured, not projected: the composed bbox is **73,989 um^2** --
higher than the projection above (~66,800 um^2) because the projection's
2.17x average analytic-to-drawn overhead ratio understates `amp_cc`'s own
guard ring, spine bussing and row-3 placement channel cost specifically.
`klt lvs` reports `mismatch_count: 0` against this drawn cell. DR-007's
proposed budget line is updated in the same increment (`< 0.07 mm^2` ->
`< 0.08 mm^2`) to hold the real number with margin; still not ratified, so
`gen_bandgap_routed.py`'s `budget_um2` stays at the current ratified
50,000 um^2 and the flow's own `within_budget` gate fails, honestly, until
DR-007 (or an amendment) is decided.

## 7. `klt` generator mapping and friction

Status as of issue #62's routed flow, fourth increment -- the first run
against a `klt` pin in which **no** upstream gap this plan named is still
open (the #15 column is kept because the skeleton's own checked-in records
were produced under it):

| Matched group | Generator | DRC-clean | Extraction status at #15 | Extraction status at #62 (current) |
|---|---|---|---|---|
| PNP arrays (Q1, Q2) | `bjt_array` | yes | no -- `klt extract` on a `bjt_array` output reports `device_count: 0` | **yes, 24 `pnp` devices** (dummies included), drawn by the generator itself since upstream [klayout-tools#440](https://github.com/2AMLogic/klayout-tools/issues/440) (the first increment's local recognition overlay is retired) |
| Resistor ladders (R2A/R2B, R1, trim) | `res_array` | yes | no -- never drew the PDK's resistor-ID marker layer (2AMLogic/klayout-tools#369) | **yes, 159 `res_high_po` devices** -- the schematic's own flavour, drawable since [klayout-tools#463](https://github.com/2AMLogic/klayout-tools/issues/463) merged via #475 (#369 merged earlier via #382) |
| Amp input pair, NMOS loads/mirrors, PMOS mirror, core mirror | `diff_pair` | yes | not attempted | **yes, 52 `pfet` + 16 `nfet`, and every finger bussed** -- the nfet flavour needed klayout-tools#421 (merged via #426); gates needed [klayout-tools#461](https://github.com/2AMLogic/klayout-tools/issues/461) (merged via #474), which draws a poly landing pad past the diffusion. `klt lvs`'s `combine_devices` now folds each group into the schematic's own `m=N` device (W=320 for MP1/MP2, 48 for MP3/MP4, 32 for MN1-MN4, 16 for MPOUT/MPAMP) |
| Overall guard ring | `guard_ring` (standalone) | yes | n/a | n/a -- composed in a **second** `gen-compose` pass, because a ring enclosing the whole floorplan reports a bbox that the router treats as an obstacle vetoing every net |
| Per-group guard rings | `add_guard_ring`/`add_collector_ring` (built into `diff_pair`/`bjt_array`) | yes | n/a | **on**, with a routing opening (klayout-tools#441) -- see Section 5a |
| Intra-block bussing (array units, ladder segments, **MOS fingers**) | `met1_bus.py` + `bus_mos_comb` (`klt draw`, this repo) | yes | n/a | **drawn on met1**, not through `gen-compose` -- see Section 5a, `MET1_BUS_NOTE` and `MOS_COMB_NOTE`. A gate reaches its trunk through a licon on #461's landing pad plus an li1 riser, both drawn here: the router still cannot reach a poly port ([klayout-tools#492](https://github.com/2AMLogic/klayout-tools/issues/492)) |
| 2D floorplan composition | `gen-compose` `placement.strategy: "explicit"` | n/a | n/a | plus `connectivity[]` routing and `pins[]` pin promotion for the li1-reachable nets |

Friction filed or cross-confirmed while building this floorplan, per
`CLAUDE.md`'s protocol (tool-gap description only, no design-specific
detail beyond a generic reproduction):

- **New**: [2AMLogic/klayout-tools#415](https://github.com/2AMLogic/klayout-tools/issues/415)
  -- `res_array` draws a single row with no fold/meander parameter, so a
  matched resistor ladder with 100+ unit segments cannot fit a compact
  floorplan (Section 4 above is the concrete case that surfaced this).
- **Already tracked, confirmed applicable here, not re-filed**:
  [2AMLogic/klayout-tools#176](https://github.com/2AMLogic/klayout-tools/issues/176)
  (no bipolar-device LVS recognition -- closed as "draw geometry from base
  layers" was the accepted mechanism, which is exactly why `bjt_array`
  DRC-cleans but does not extract) and
  [2AMLogic/klayout-tools#369](https://github.com/2AMLogic/klayout-tools/issues/369)
  (resistor-array output does not extract as a recognized resistor either).
- **Picked up, not filed** (a capability gap this issue needed that had
  already landed upstream by the time this issue was built):
  [2AMLogic/klayout-tools#330](https://github.com/2AMLogic/klayout-tools/issues/330)
  added `gen-compose`'s `placement.strategy: "explicit"`, which is what
  makes the real 2D (not single-row) floorplan in Section 3 possible.
  `layout/requirements.txt`'s pin was bumped to pick this up -- see that
  file's own comment, and the refreshed
  `layout/trivial-cell/reports/` record confirming the bump does not
  regress issue #14's own DRC/LVS proof.

**How to read the increments below (issue #499).** Each `7<x>` heading is
unchanged and still numbered as it always was, but most now carry a two- to
three-line entry -- what changed, the issue or PR, the record it cites --
instead of the full narrative. The full narrative is archived verbatim, under
the same heading, in
[`matching-plan-history.md`](matching-plan-history.md); read it when you need
the measurements, the ruled-out levers or the reasoning behind a result rather
than the result itself. Five sections other files cite directly (**7t, 7x,
7bb, 7cc, 7ff**) are kept here in full, and only the latest scoreboard table
(Section 7cc's) is kept in this plan -- the superseded ones are in the history
file too.

### 7a. Friction filed while routing the core (issue #62)

Filed the first three upstream gaps found while routing the core --
klayout-tools#432 (bipolar device-recognition marker), #433 (a same-block bus
certified as a routed short) and #434 (`ring_gap_side`); all three are now
closed upstream.

Issue #62 / PR #64 -- record: none cited.

### 7b. Fourth increment: every named blocker closed, three new ones found

Bumped `layout/requirements.txt` past the five upstream gaps the third
increment was waiting on (klayout-tools#461/#462/#463/#454/#470) -- MOS gates
became contactable, so every split MOS group busses into one `m=N` device --
and filed three new ones (#490, #491, #492).

Issue #62 -- record: none cited.

### 7c. Fifth increment: rip-up-and-reroute, no filing, no number moved

Built this repo's own rip-up-and-reroute repair pass (`_route_one_net`,
`_replay_tail`, `_repair_unrouted_hops`) on top of the order search.
`D1`/`VDD`/`VSS` stayed `partial` with `device_counts` unchanged -- an
evidence-backed negative result that narrows the limit to the floorplan's free
corridors, not any one net's alternate choices.

Issue #62 -- record: none cited.

### 7d. Sixth increment: both remaining candidates investigated -- one ruled out, one narrowed, no code shipped

Investigated both candidates the fifth increment left open for AC1: taking up
klayout-tools#468's metal2/via1 roles (ruled out -- the role resolves to the
same met1 layer this flow already hand-routes on) and splitting
`amp_input_pair` (narrowed, but a real matching-topology redesign). No code
shipped.

Issue #62 (klayout-tools#454/#468) -- record: none cited.

### 7e. Seventh increment: the channel-search-window lever, run to completion -- not a monotonic win, ruled out

Ran the channel-search-window lever to completion (`CHANNEL_NEAR_TRACKS` 8 ->
16, `CHANNEL_DOGLEG_TRACKS` 5 -> 9): not a monotonic win, ruled out.

Issue #62 -- record cited: `20260804-100209-f3b4908`.

### 7f. Eighth increment: widening row 0's own block margin, run to completion -- `VSS`'s blocker unchanged, `GDRV` regresses, ruled out

Widened row 0's own block margin and ran it to completion: `VSS`'s blocker was
unchanged and `GDRV` regressed, so the lever was ruled out.

Issue #62 -- records cited: `20260804-065252-496ab43`,
`20260804-104732-fc95614`.

### 7g. Ninth increment: `blocked_by` names one veto of many -- a per-hop blocker tally, and what it says about the three hops left after #78

Replaced the single-net `blocked_by` characterisation with a per-hop blocker
tally (`blocked_by_counts`, carried in every record since) and read it against
the three hops left after PR #78.

Issue #62 / PR #78 -- records cited: `20260804-113412-4fb2a3a`,
`20260804-105025-25d02e6`.

### 7h. Tenth increment: PR #78 changed the unrouted set from `D1`/`VDD`/`VSS` to `D1`/`GDRV`/`VSS` -- re-ran the search-depth lever against the new set, still not a lever

Re-ran the search-depth lever against the post-#78 unrouted set
(`D1`/`GDRV`/`VSS` instead of `D1`/`VDD`/`VSS`): still not a lever.

Issue #62 / PR #78 -- record cited: `20260804-105025-25d02e6`.

### 7i. Eleventh increment: `VSS`'s row-0 re-placement attempted directly -- fixes `VSS`, at the cost of a different row-0 net each time, no net win, not shipped

Attempted `VSS`'s row-0 re-placement directly: it fixes `VSS` at the cost of a
different row-0 net each time -- no net win, not shipped.

Issue #62 -- record: none cited.

### 7j. Twelfth increment: the genuine 2D revision attempted directly -- fixes `VSS`'s named hop, costs two other nets, net regression, not shipped

Attempted the genuine 2D floorplan revision directly: it fixes `VSS`'s named
hop but costs two other nets, a net regression, not shipped.

Issue #62 -- record cited: `20260804-150853-a074ca5` (not committed).

### 7k. Thirteenth increment: Section 7j's own "non-uniform channel budget" candidate attempted, in two shapes -- neither avoids the trade, and the mechanism turns out not to be channel width at all

Attempted Section 7j's own 'non-uniform channel budget' candidate in two
independent shapes: neither avoids the trade, and the mechanism turns out not
to be channel width at all.

Issue #62 -- record: none cited.

### 7l. Fourteenth increment: `klt` pin bump picks up five upstream fixes; a stale `hints.same_nets` declaration turns out to be actively blocking, not neutral -- `mismatch_count` 92 -> 32

Bumped the `klt` pin for five upstream fixes and found that a stale
`hints.same_nets` declaration was actively blocking rather than neutral --
`mismatch_count` 92 -> 32.

Issue #62 -- record cited: `20260804-174203-ddf7f17`.

### 7m. Fifteenth increment: cause 4 (resistor device-class arity) still has no fix upstream -- filed the missing follow-up, no code change

Cause 4 (resistor device-class arity) still had no upstream fix; filed the
missing follow-up and changed no code. Its operative premise is superseded in
part by Section 7n.

Issue #62 (klayout-tools#506) -- record cited: `20260804-174203-ddf7f17`.

### 7n. Sixteenth increment: `reference.spice`'s resistor bulk-terminal transcription gap fixed -- class arity now matches without waiting on klayout-tools#506, `mismatch_count` unchanged, and the real blocker for R2A/R2B/R1 turns out to be the DR-002 trim ladder's own topology, not the arity or a value difference

Fixed `reference.spice`'s resistor bulk-terminal transcription gap, so class
arity matches without waiting on klayout-tools#506. `mismatch_count`
unchanged, and the real blocker for R2A/R2B/R1 turned out to be the DR-002
trim ladder's own topology, not the arity or a value difference.

Issue #62 -- records cited: `20260803-115356-7759435`,
`20260804-181651-f3b2b2e`, `20260804-190815-092c8cb`.

### 7o. Seventeenth increment: named and filed the metal-level capability gap behind AC1's corridor deadlock, no code change

Named and filed the metal-level capability gap behind AC1's corridor deadlock
(sky130's curated deck carries only two metal levels, so klayout-tools#454's
second *role* is not a second *layer*); no code change.

Issue #62 (klayout-tools#508) -- record: none cited.

### 7p. Eighteenth increment: bumped the `klt` pin past klayout-tools#508's merge, picked up the third connectivity level, no routing change yet

Bumped the `klt` pin past klayout-tools#508's merge (PR #511, which adds
sky130 met2 as a third connectivity level), picking up the third connectivity
level with no routing change yet.

Issue #62 -- record: none cited.

### 7q. Nineteenth increment: AC1 closes on a met2 escape plane built on Section 7p's pin, and removing four labels drops every remaining connectivity mismatch

AC1 closed on a met2 escape plane built on Section 7p's pin, and removing four
interior labels dropped every remaining connectivity mismatch.

Issues #46 / #62 / #91 -- record cited: `20260804-211109-0336eb4`.

### 7r. Twentieth increment: the R2 leg is re-decomposed, not extended -- 286 um -> 270 um, the trim ladder trims downward, and the check that found it becomes a gate (issue #91)

Re-decomposed the R2 leg instead of extending it -- the drawn DC path goes 286
um -> 270 um and the trim ladder now trims downward -- and turned the check
that found it into a flow gate.

Issue #91 -- record cited: `20260804-231410-539e30b`.

### 7s. Twenty-first increment: the PNP `ae`/`pe`/`ne` transcription gap, closed the same way RES_BULK_ARITY_NOTE closed the resistor bulk terminal -- `mismatch_count` 18 -> 4

Closed the PNP `ae`/`pe`/`ne` transcription gap the same way the resistor
bulk-terminal gap closed, from the schematic's own vendor-macro names:
`mismatch_count` 18 -> 4.

Issues #15 / #91 -- record: none cited.

### 7t. Twenty-second increment: confirmed the remaining `res_high_po` cause against the PDK's own model card (not just this repo's schematic-side approximation of it), filed it upstream

No code change; this increment ran concurrently with Section 7s's (same
starting baseline, the `mismatch_count: 18` of the then-latest checked-in
record `20260804-211109-0336eb4`) and is rebased on top of it
rather than duplicating it — see the concurrency note at the end of this
section. Section 7s closed cause 4 (PNP `ae`/`pe`/`ne`); this increment
investigates the two causes Section 7s's own scoreboard names as still
open: `res_high_po`'s head-resistance term, and the R2 leg length (issue
#91, deliberately left to its own concurrent claim, not duplicated here --
it has since landed as Section 7r).

**Re-verified the baseline.** Reinstalled `layout/.venv` at the checked-in
pin (`--force`) and re-ran `run-bandgap-routed-flow.sh` before Section 7s's
fix landed in this session's own working tree: reproduced `mismatch_count:
18` byte-for-byte against the last checked-in record at that point. Sections
7s and 7t were then rebased onto Section 7r (issue #91, merged to `main`
first) and the full flow re-run twice on that combined tree: both runs
reproduce `mismatch_count: 4`, recorded as `20260805-102026-19c521f`, which
is the record this section and Section 7s cite. Section 7r's own
re-decomposition does **not** change the count -- it changes each R2 leg's
extracted `r` from 91,462.8 (a drawn-length defect) to 86,346 (the same
`res_high_po` head term `R1` always showed), which is precisely the cause
this section then goes on to verify against the PDK's own model card.

**Cause 3, checked against the PDK model directly, not just the schematic's
own restatement of it.** The existing record compares the layout's
extracted `res_high_po` value against *this repo's own* `R ~ 380 + 325*L`
approximation (`design/bandgap_core.sch` line 188) — itself a
simplification, not the PDK's ground truth. Built a standalone ngspice
testbench against the real `sky130_fd_pr__res_high_po` model card (via
`sky130.lib.spice`'s `.lib tt` section, nominal corner, `MC_MM_SWITCH=0`) to
check both whether the schematic's approximation is itself accurate and
whether `klt extract`'s gap is what prior records say it is:

| drawn `l` (w=1um) | `klt extract` (`L/W*319.8`) | real PDK model (nominal `tt`) | delta |
| --- | --- | --- | --- |
| 1 um | 319.8 ohm | 704.5 ohm | +120.3% |
| 5 um | 1,599.0 ohm | 2,003.8 ohm | +25.3% |
| 10 um | 3,198.0 ohm | 3,628.0 ohm | +13.4% |
| 35 um | 11,193.0 ohm | 11,748.7 ohm | +5.0% |

Two things confirmed, not assumed: (1) the real model card is literally two
series sub-resistors per instance (`rhead`, a fixed ~300 ohm `w=1um`
end/contact term whose own length parameter is a model constant, independent
of the caller's drawn `l`; and `rbody`, the length-scaling term `klt
extract`'s `L/W*sheet_rho` already approximates) — so the gap is structural,
not a rounding difference in a single coefficient. (2) At `l=35um` the real
model's 11,748.7 ohm agrees with `design/bandgap_core.sch`'s own
`380+325*L` approximation (11,755 ohm) to within 0.05% — the schematic's
simplified formula is itself a good stand-in for the real device, so this
cause's "no drawn shape can add a contact-resistance term the extractor's
sheet-resistance model does not carry" framing holds up under a
from-the-model check, not only a from-the-schematic one.

Filed upstream, generic (the model-card structure and the measured deltas
above, no bandgap-specific detail), as
[klayout-tools#518](https://github.com/2AMLogic/klayout-tools/issues/518) —
searched the tracker first for `res_high_po`, "resistor head/end
resistance", and `ResistorDevice`; found #299/#323 (a different resistor
gap, which sheet-rho flavours are wired into the list at all) and #512 (the
capacitor-side sibling of this exact "area/length-only formula misses a real
device's second term" shape), no existing filing for this one. Also
confirmed no request-side escape hatch exists: `klt lvs`'s per-property
compare epsilon (`_PARAM_ABS_EPSILON`/`_PARAM_REL_EPSILON` in
`klayout_tools/lvs.py`) is a hardcoded module constant, not something a
request document can widen.

**Concurrency note.** This section and Section 7s were both branched from
the same `mismatch_count: 18` baseline by separate sessions at nearly the
same time; a
build hiccup on this session's side briefly force-pushed over Section 7s's
commit on the shared branch before being caught and corrected by rebasing
this section on top of it (same recovery shape as PR #71/#92's own
concurrency notes for this issue). No content was lost; this section is
additive to Section 7s's, not a redo of it.

*(This increment's own scoreboard table is archived in
[`matching-plan-history.md`](matching-plan-history.md) under "Section 7t
scoreboard" -- only the latest scoreboard, Section 7cc's, is kept in this
plan.)*

**Suggested next increment**: there is no actionable AC4 lever left in this
repo's own layout. Issue #91 has landed (Section 7r) and, as this section's
own baseline re-run confirms, it does not move `mismatch_count`: it converts
`R2A`/`R2B`'s residual from a drawn-length defect into the same
head-resistance model term `R1` already carried, which is exactly the
prediction this section made before it landed. All 3 remaining
`device.property` mismatches are now that one term, and the 4th is `MCC`,
deliberately undrawn per issue #15. `mismatch_count` cannot go below 4 from
this side: closing it needs klayout-tools#518 upstream (extractor-side head
resistance) plus a decision on `MCC`, both out of this repo's hands.

### 7u. Twenty-third increment: bumped past klayout-tools#518/#519 and #521/#526 -- and found the fix does not close AC4, because this flow's own trim-tap decomposition breaks the per-instance offset's assumption

Bumped past klayout-tools#518/#519 and #521/#526, and found the fix does not
close AC4: this flow's own trim-tap decomposition breaks the per-instance
`fixed_offset_ohm` assumption.

Issue #62 -- record: none cited.

### 7v. Real-SPICE check of the folded array's head resistance (issue #98) -- reading 2 confirmed, and material: K=R2/R1 shifts +8.67%, VOUT leaves the ±1% window at all 5 corners checked

Real-SPICE check of the folded array's head resistance: reading 2 is confirmed
and material -- `K = R2/R1` shifts +8.67% and `VOUT` leaves the +/-1% window
at all 5 corners checked.

Issue #98 -- record cited: `20260805-113409-6caa9f8`.

### 7w. Twenty-sixth increment: no new lever on klayout-tools#559, but a stale/self-contradictory met2-DRC-coverage claim found and fixed

No new lever on klayout-tools#559, but a stale, self-contradictory
met2-DRC-coverage claim was found and fixed.

Issue #62 -- record cited: `20260805-105719-f126dca`.

### 7x. The sizing resize DR-003 unlocked lands in the schematic (issue #99): n_r2 54 -> 50 re-centres the routed chained array's K, back in spec at all 5 corners with no hot-corner collapse -- layout-generator transcription is the next lever

No layout code change this increment -- the resize lands in
`design/bandgap_core.sch`'s sizing parameter and its own full-PVT
verification, and the routed generator's re-transcription is deliberately
deferred to the next increment (see the scoreboard note). Section 7v (issue
#98, DR-003) established with real-SPICE evidence that the folded
`res_r2`/`res_trim`/`res_r1` array pays real per-instance head resistance,
which raises the *routed* part's `K = R2/R1` from the single-device model's
7.4973 to **8.1474** at the shipped `n_r2=54` -- enough to push
`VOUT(27 °C)` to ~1.233 V, outside the draft ±1 % window (1.188-1.212 V) at
all 5 (process, supply) corners, and to collapse regulation at ff/2.97 V and
fs/2.97 V. DR-003 deferred the corrective resize to issue #99 so it would get
the same full-corner rigor issue #46 applied to the original sizing.

**Issue #99 performed and verified that resize.** A new harness,
`sim/res-array-resize/run_res_array_resize.py`, extends Section 7v's own
Phase B pattern -- it chains real `sky130_fd_pr__res_high_po` unit instances
into the core testbench at the routed layout's own decomposition
(`gen_bandgap_routed.py`'s `N_R1`/`N_R2_COARSE`/`N_R2_TRIM_UNITS`), but
parameterized on arbitrary `n_r1`/`n_r2` so a resize can be searched and then
verified against the real chained topology rather than the single-device
model. The adopted resize is a **pure `n_r2` change, 54 -> 50, with `n_r1`
held at 7** (holding R1 fixes the branch current, so `K` is corrected without
raising the hot-corner headroom demand the collapse depends on). Against the
real chained topology this brings `K` back to **7.576** and `VOUT(27 °C)` to
**1.1976-1.1995 V across all 5 corners -- in spec, and collapse-free** (ff/fs
`VOUT`max ≈ 1.206-1.208 V, on the operating branch, vs. the shipped sizing's
~2.85 V pin). DR-002's downward `0..-16` trim range, re-run (not re-cited) on
the resized baseline, still covers -- the resize corrects the deterministic
head-resistance offset at the sizing lever, leaving the metal-option trim for
the per-die mismatch it was scoped for. Full per-corner tables, the shipped-
sizing control that reproduces Section 7v's collapse, and the trim recheck:
`sim/res-array-resize/records/` and
`spec/decision-records/DR-003-res-array-head-resistance-sizing.md`'s
"Closure" section.

**Consequence for this layout.** `gen_bandgap_routed.py` still transcribes
the old sizing (`N_R1=7`, `SCH_N_R2=54`, `N_R2_COARSE=50`) and therefore still
draws the `n_r2=54` array -- so as of this increment the schematic carries the
resized sizing (`n_r2=50`) and the drawn layout carries the old one. That is
an intentional, documented transient, the same class of schematic-vs-layout
gap Section 7v opened DR-003 to close, now pointing the other way and scoped
to one follow-up: re-transcribe `N_R2_COARSE` 50 -> 46 (the 20-unit fine trim
ladder unchanged; `r2_leg_length()`'s `spec_um` and its gate move 270 -> 250)
and re-verify through `klt drc`/`klt lvs`. That step needs klayout (not
available in issue #99's run environment, which is why the resize decision and
the redraw are split), so it is the next increment rather than folded in here.

*(This increment's own scoreboard table is archived in
[`matching-plan-history.md`](matching-plan-history.md) under "Section 7x
scoreboard" -- only the latest scoreboard, Section 7cc's, is kept in this
plan.)*

**Suggested next increment**: re-transcribe `gen_bandgap_routed.py` to the
`n_r2=50` decomposition (`N_R2_COARSE` 50 -> 46, `SCH_N_R2` 54 -> 50, the
`r2_leg_length()` gate and its `test_routed_flow_gates.py` assertions moving
with it) and re-run `klt drc`/`klt lvs` to confirm the fabricated cell matches
the resized schematic -- the layout half of DR-003's closure.

### 7y. Twenty-seventh increment: the resize lands in the drawn array (issue #108) -- `mismatch_count` 4 -> 1, `res_high_po`'s value cause retired by a transcription-convention decision, not a tool fix

The `n_r2` 54 -> 50 resize landed in the drawn array: `mismatch_count` 4 -> 1,
and `res_high_po`'s value cause was retired by a transcription-convention
decision, not a tool fix.

Issue #108 (DR-003, issue #99) -- record cited: `20260805-204809-2c83c7a`.

### 7z. Twenty-eighth increment: `klt` pin bumped past klayout-tools#583/#587 -- the once-per-combined-device correction is now reachable, measured under all four accounting variants, and deliberately NOT adopted (adopting it would REGRESS `mismatch_count` 1 -> 4)

Bumped the `klt` pin past klayout-tools#583/#587 so the
once-per-combined-device correction became reachable, measured it under all
four accounting variants, and deliberately did NOT adopt it -- adopting it
would regress `mismatch_count` 1 -> 4.

Issue #108 -- record: none cited.

### 7aa. Twenty-ninth increment: DR-002's `r_lseg_trim` revision (1 -> 0.5 um, issue #106/PR #111) propagated into the drawn array -- `N_R2_COARSE` 46 -> 48, `reference.spice` re-derived, `mismatch_count` holds at 1 (issue #112)

Propagated DR-002's `r_lseg_trim` revision (1 -> 0.5 um, issue #106 / PR #111)
into the drawn array: `N_R2_COARSE` 46 -> 48, `reference.spice` re-derived,
`mismatch_count` holds at 1.

Issue #112 -- record: a fresh routed-flow record, id not cited in the
narrative.

### 7bb. Thirtieth increment: the operator's MCC ruling (2026-08-11) -- MIM-cap overlay feasibility checked and found infeasible on tooling grounds, not area; falls back to the draw-as-MOS-cap + DR-007 path

The operator ruled `MMCC` is not a waivable AC4 exception (it sets the
amp's dominant pole -- `sim/error-amp-loop/`'s 45-corner loop-stability
pass assumes it exists) and directed, in priority order: (1) check whether
a `cap_mim` MIM-cap overlay fits above the composed cell at ~zero
incremental footprint; (2) if feasible, draw it there and close AC4; (3) if
infeasible, draw `MCC` as the MOS cap it is today and propose a decision
record relaxing DR-005's now-ratified Area row (50,000 um^2), since that
draws ~20,800 um^2 over budget (Section 6).

**Area side of the feasibility check: ample.** This cell's own drawn
geometry never leaves li1/met1/met2 (Section 5a, MET2_ESCAPE_NOTE) -- met3,
met4 and met5 are entirely empty across the full 45,968 um^2 composed
footprint. A 29 pF `cap_mim` at sky130's real `camimc=2.0 fF/um^2` area
term needs ~14,500 um^2 of plate area (before the smaller `cpmimc` fringe
term), comfortably inside that empty upper-metal real estate. Area was
never the blocker.

**Tooling side: empirically infeasible today, not merely undocumented.**
Independently reproduced (not assumed from a doc read) against both the
currently-pinned `klt` and a build past 2AMLogic/klayout-tools#621 (the
met3-met5 connectivity extension that landed after this issue's twenty-
eighth increment's pin bump), using a minimal `klt draw` fixture: a met1
pad labelled on one net, `via1`->met2->`via2`->met3 (the `cap_mim` bottom
plate) under a `capm` region (the top plate), and a top-plate via climbing
to a met4 pad labelled on a second net -- i.e. exactly the two-terminal
wiring `MCC`'s replacement would need (one plate to `AOUT`, one to `VDD`).
Three geometries, three failure modes, none of them a usable two-terminal
device:

1. **At the pre-#621 pin**: `via2`/`via3` are unregistered `vias` entries
   (`EXTRACTION_DECK.metals` stops at met2), so both plates extract as
   anonymous, disconnected single-net islands -- `net_count: 2`, neither
   label reaches the device.
2. **Past #621, top-plate via landing inside the bottom plate's own
   footprint** (the DRM-legal position -- a real MiM bottom plate is drawn
   large enough to underlie the whole cap, including the top-plate via
   landing): the two labelled nets **merge into one net**, a false short
   between `AOUT` and `VDD` through the cap.
3. **Past #621, bottom plate notched away from the top-plate via's landing
   region** (so the via's footprint clears the bottom plate entirely): no
   false short, but the top label is now its own **disconnected** net --
   the capacitor's real top-plate terminal is a different, unlabelled,
   single-terminal net the via still does not reach.

Root cause, read directly from `klayout_tools.decks.sky130.EXTRACTION_DECK`
and `CapacitorDevice`: the mechanism that should make case 2/3 work
(`top_plate_via`/`top_plate_via_metal`, added closing klayout-tools#314,
with the false-short exclusion added closing #364) is real and does work
generically -- but neither of sky130's own `capacitors[]` entries
(`sky130_fd_pr__model__cap_mim`, `..._cap_mim_m4`) sets it. That was the
documented, correct choice when #314/#364 landed (sky130's real top-plate
vias land on met4/met5, which the curated deck's own `metals` stack didn't
track yet); #621 closed that precondition for a different reason (net
`place_and_route.py` signal-routing gap, unrelated to MiM caps) but nobody
followed up by actually wiring `top_plate_via` for either sky130 capacitor
entry once its precondition existed. Filed generically upstream, with the
three-geometry reproduction above and a concrete two-line fix (the exact
`(layer, datatype)` pairs to set): 2AMLogic/klayout-tools#775.

**Decision: fall back to drawing `MCC` as the MOS cap it is today, and
propose (not ratify) an Area-budget relaxation.** The operator's own
infeasibility trigger was phrased as an area question, but the substance --
"this path cannot be executed as specified" -- is identical whether the
blocker is area or tooling; #775 is a real external blocker no repo-side
lever can route around today (same category `klayout-tools#559` was for 20+
increments before it had an upstream fix to bump a pin past). Opened
`spec/decision-records/DR-007-mcc-area-budget.md`, **status: proposed**,
per CLAUDE.md's "agents do not relax the ratified spec to make results
pass" -- this repo does not flip DR-005's Area row itself; the record
states the measured trade for the operator to accept, amend, or reject by
comment on this issue, the same pattern DR-004's proposed amendments used
against #1.

**Not drawn this increment.** Placing `MCC` as a real `mos_array`/`pfet`
block (guard ring, met1 bus tying all four terminals to `AOUT`/`VDD`,
re-routing, a fresh `klt drc`/`extract`/`lvs` pass) is a new-block layout
increment on the scale of Section 3's other ten blocks, and
`gen_bandgap_routed.py`'s own area gate (`budget_um2` hard-coded to the
current ratified 50,000 um^2, `run-bandgap-routed-flow.sh` fails the flow
below that) would reject the composed cell before LVS is even attempted --
so it cannot land, gated or otherwise, ahead of DR-007 being accepted. Once
DR-007 (or an operator amendment to it) is ratified, the next increment can
bump `budget_um2` to match, add the `MCC` block, and re-run the full
routed-cell flow.

*(This increment's own scoreboard table is archived in
[`matching-plan-history.md`](matching-plan-history.md) under "Section 7bb
scoreboard" -- only the latest scoreboard, Section 7cc's, is kept in this
plan.)*

**Suggested next increment**: DR-007 needs an operator ruling (accept the
proposed budget, amend the target value, or decline and re-open the
redesign-the-compensation-smaller option the operator's own ruling recorded
as "not chosen" for this issue). Once ratified, draw `MCC` as a `pfet`
MOS-cap block and re-run the routed-cell flow end to end -- expected to
close AC4 (`mismatch_count: 0`) if nothing else about the extracted
netlist's shape changes. Independently, 2AMLogic/klayout-tools#775 is worth
re-checking on its own timeline: if it lands, a future MIM-cap increment
could re-open the ~zero-incremental-footprint path instead, without
touching the Area budget at all -- but that is not this increment's gate,
since #775 is unmerged and unreleased as filed.

#### 7bb-1. The same question, as a re-runnable measurement

Because #775 is exactly the fix that would flip this section's answer, the
feasibility check is also committed as a script --
`layout/bin/measure_mim_overlay_feasibility.py`, evidence under
`layout/bandgap-core/mim-overlay-feasibility/<record-id>/` -- so the next
`klt` pin bump can re-measure in one command instead of re-deriving the
argument from prose. It deliberately does **not** repeat 7bb's
three-geometry `klt draw` reproduction (that remains the stronger tooling
evidence); it measures the parts that were asserted above, and adds two:

- **Overlay area, measured off the composed GDS rather than reasoned
  about**: 45,968 um^2 of footprint, of which **0.0 um^2** carries any
  met3/met4/`capm`/`capm2` geometry.
- **Plate area needed, at the measured capacitance**: 10,742 um^2
  (103.6 x 103.6 um), solving the deck's own two-term law
  (`2.0 fF/um^2` area + `0.19 fF/um` perimeter) at the worst-corner
  `cc_mcc`. **This corrects the ~14,500 um^2 figure above**: that number
  sizes from ~29 pF, the analytic `Cox*W*L*m` on MCC's gate area, but
  `design/error_amp.sch` states outright that MCC's capacitance is measured
  rather than computed that way, and `sim/error-amp-loop/`'s 45 corners
  measure `cc_mcc` at **21.04-21.56 pF**. The verdict is unchanged (both
  fit comfortably), but a future revisit should size from the measured
  number, not the analytic one.
- **Connectivity, re-confirmed at the pinned `klt`** in the single most
  favourable geometry (a `capm` plate over met3 laid directly across two
  labelled met2 wires): the cap is recognised, and both its terminals are
  anonymous isolated nodes. Same conclusion as 7bb case 1.
- **DRC coverage, which 7bb did not measure**: of the four MiM stack
  layers, `met3.drawing` and `capm.drawing` appear in
  `drc.json`'s own `layers_in_stream_without_rules` -- the curated sky130
  *DRC* deck stops at met2 while its *extraction* deck now models met3-met5
  and MiM caps, so a drawn MiM overlay would get a `clean` verdict from
  geometry nothing checked. That is the same asymmetry Section 7q filed as
  klayout-tools#513 for met2, four stack levels later; filed generically as
  **2AMLogic/klayout-tools#776**.

One further gap was filed while looking for a more compact way to draw a
wide MOS device: **2AMLogic/klayout-tools#777** -- `mos_array`'s `fingers>1`
draws a *series* chain with unreported interior S/D pads and uncontactable
gates rather than the parallel multi-finger device the parameter implies,
and offers no guard-ring (well-tap) option, which is why a MOS-cap `MCC` is
drawn from `diff_pair` single-finger units instead.

### 7cc. Thirty-first increment: `MCC` drawn as a `pfet` MOS-cap block -- `klt lvs` reports `mismatch_count: 0` for the first time in this issue's history, gated only on DR-007's unratified Area relaxation

Corrects one premise of the prior increment's own text: `run-bandgap-routed-flow.sh`'s `within_budget` is a **reported gate condition checked at the end of the flow**, not a pre-flight guard -- the flow does not "reject the composed cell before LVS is even attempted." It runs DRC, extraction and LVS exactly as it would at any composed size, and only the final exit status (`flow_gate()`'s boolean AND of every named condition) reflects an over-budget result. This increment draws `MCC` and lets the flow run to completion on that basis, rather than waiting on DR-007 first -- the LVS evidence this produces is exactly what DR-007 itself asks a future increment to generate ("the actual number will be recorded once a follow-on increment draws it").

**A second, independent case against the MIM-cap overlay, found while implementing this increment** (see MCC_MIM_INFEASIBLE_NOTE in `gen_bandgap_routed.py`): even setting PR #124's tooling-infeasibility finding aside, `klt lvs` has no device-class equivalence mechanism (`_apply_hints` in `klayout_tools/lvs.py` accepts only `hints.same_nets`/`hints.equivalent_pins`, both net/pin-level). `reference.spice`'s `MMCC` card is a plain `M`-element (`pfet` class, 4-terminal `DeviceClassMOS4Transistor`); a drawn `cap_mim` overlay would extract under `sky130_fd_pr__model__cap_mim` (a different class name, 2-terminal `DeviceClassCapacitor`). `NetlistComparer`'s cross-class event (`match_devices_with_different_device_classes`) still reports a `device.class` mismatch when it *can* topologically pair devices of differing arity, and reports two independent `device.unmatched` entries when it cannot (the likely outcome here, given 2 vs. 4 terminals) -- so a MIM-cap overlay cannot reach `mismatch_count: 0` against the *current* `reference.spice` on LVS-comparator grounds alone, independent of area or drawability. Closing that path for real would need `reference.spice`'s `MMCC` card rewritten to a capacitor model, which is a schematic-level device-type change to a closed, sim-verified cell -- the same "redesign the compensation network" scope the operator's ruling already flagged as out of scope for this issue. This does not change DR-007's conclusion (MOS-cap is the only path that reaches `mismatch_count: 0` today), but it means the MIM-cap path stays closed even after klayout-tools#775 lands, unless a future increment separately reopens the reference-netlist question.

**Implementation**: a new `amp_cc` block (row 3, below `amp_pmirr`/`amp_nmirr`), `diff_pair` generator, `w_um=30, l_um=20, splits=8 (=AMP_M_CC//2), flavor=pfet, mirror=True, add_guard_ring=True` -- two mult-8 groups (`MCC_A`/`MCC_B`, a new `MOS_HALVES` entry) wired to the *exact same* two nets (VDD on both drain and source, GDRV on gate), so `combine_devices` folds all 16 fingers -- both groups, not just each group's own 8 -- into the schematic's single `m=16` `MMCC` device. This is a one-level-deeper application of the same parallel-fold mechanism that already collapses e.g. `MP1`'s 16 fingers into one device; nothing new was needed from `combine_devices` itself, and the result (see below) confirms it folds across the `M1`/`M2` group boundary too, not just within one.

**Results** (`layout/bandgap-core/reports/20260811-220511-6814b56/record.md`):

| Stage | Before this increment | After |
| --- | --- | --- |
| met1/met2 routing | 13 nets, 0 unrouted | 13 nets, 0 unrouted (unchanged net count -- `amp_cc`'s VDD/GDRV hops join existing nets, they do not add new ones) |
| DRC | clean | clean |
| met2 DRC (own check) | clean, via1 cuts=12, met2 polygons=5 | clean, via1 cuts=22, met2 polygons=9 |
| extract | `device_counts={"nfet":16,"pfet":52,"pnp":16,"res_high_po":143}`, `pin_count=11` | `device_counts={"nfet":16,"pfet":68,"pnp":16,"res_high_po":143}`, `pin_count=11` (+16 `pfet` = `amp_cc`'s own drawn finger count before folding) |
| `klt lvs` (combined) | `mismatch_count=1` (`MMCC` unmatched) | **`mismatch_count=0`**, `devices.matched=16` (was 15), `category_counts={}` |
| `klt lvs` (uncombined) | mismatch=405 | mismatch=421 (16 more raw devices to fold, same shape) |
| composed bbox | 45,968 um^2 | **73,989 um^2** |

**Area**: the measured 73,989 um^2 is higher than DR-007's own *projected* ~66,800 um^2 (which used this design's average 2.17x analytic-to-drawn overhead ratio) -- the `amp_cc` block's own guard ring, spine/comb bussing and the wider row-3 placement channel cost more than the average block did. DR-007's proposed `< 0.07 mm^2` (70,000 um^2) line does not hold the real number; see this record's own update to DR-007 for the corrected proposal. `budget_um2` in `gen_bandgap_routed.py` is deliberately left at the current ratified 50,000 um^2 (DR-005) rather than bumped to match -- DR-007 is still `proposed`, not ratified, and bumping the gate constant to make `within_budget` pass would be exactly the "relax the ratified spec to make results pass" CLAUDE.md refuses. The flow's own exit status (`gen_bandgap_routed.py: FAILED gate conditions: within_budget`) is therefore expected and correct at this repo's current ratified state, not a defect this increment introduces.

#### Scoreboard after this increment

| AC | before (7bb) | after |
| --- | --- | --- |
| 1-3, 5 | MET | unchanged |
| 4 (`klt lvs` clean) | NOT MET, `mismatch_count=1` (`MMCC`) | **`klt lvs` itself now reports `mismatch_count=0`** -- the LVS-comparator half of AC4 is satisfied for the first time in this issue's history. The flow's own composed-area gate (`within_budget`) still fails against the current ratified 50,000 um^2 budget, pending DR-007's ratification; AC4 is not marked MET until that gate is genuinely green too (a spec-conformant layout, not merely an LVS-clean one) |

**Suggested next increment**: get an operator ruling on DR-007 (updated in
this same increment with the real 73,989 um^2 measurement, proposing
`< 0.08 mm^2` for margin instead of the prior `< 0.07 mm^2` projection).
Once ratified, a one-line follow-up bumps `gen_bandgap_routed.py`'s
`budget_um2` to match and the flow should report every gate green,
including `within_budget` -- no further drawn-geometry change expected.

### 7dd. Thirty-second increment: the schematic finally *models* the chained array instead of sizing around it (issue #178) -- `n_r2` 50 -> 51, `N_R2_COARSE` 48 -> 49, and a newly measured post-layout interconnect-resistance finding

The schematic finally *models* the chained array instead of sizing around it:
`n_r2` 50 -> 51, `N_R2_COARSE` 48 -> 49, plus a newly measured post-layout
interconnect-resistance finding.

Issue #178 -- record cited: `20260817-020222-13476b7`.

### 7ee. Thirty-third increment (issue #283): the "closed upstream 2026-08-12" premise above was wrong -- klayout-tools#800 was closed **not planned**, not fixed; the residual is a different, still-open upstream defect (klayout-tools#2359)

Corrected Section 7dd's 'closed upstream 2026-08-12' premise:
klayout-tools#800 was closed **not planned**, not fixed, and the residual is a
different, still-open upstream defect (klayout-tools#2359).

Issue #283 -- record cited: `20260817-020222-13476b7`.

### 7ff. Thirty-fourth increment: the "`mismatch_count` 0 -> 12 under a newer `klt`" finding investigated (issue #288) -- it is not a version-to-version regression and not an accounting re-baseline, it is a **nondeterministic** combine; pin NOT bumped, filed as klayout-tools#2374

**What was reported.** Issue #282's signoff-manifest work observed that
re-running the *committed, unmodified* `lvs.combined.request.json` against the
*committed* netlists of
`layout/bandgap-core/reports/20260817-020222-13476b7/`, but under the
currently-installed `klt` (`0.5.0+g2f64ab88bfcc`) instead of the `klt` 0.2.0
that produced the committed report, reported `status: mismatch`,
`mismatch_count: 12` where the committed report says `status: match`,
`mismatch_count: 0`. Read as a version-to-version regression, that would put
this file's whole "`klt lvs` (combined) `mismatch_count=0`" scoreboard line --
and the root README's claim resting on it -- in doubt.

**What it actually is.** The newer build's verdict is **not reproducible run
to run**. `layout/bin/measure_combine_devices_determinism.py` (new, this
increment) re-runs the one committed request N times and tallies the verdict:

| build | `combine_devices_max_attempts` | deterministic | 1000-trial tally |
| --- | --- | --- | --- |
| `acb0ae6c` (this file's pin) | n/a — predates the retry entirely | **yes** | 1000x `mismatch_count: 0` |
| `2f64ab88` (installed) | build default (5) | **NO** | 762x `0`, 238x `12` |
| `2f64ab88` (installed) | `1` | **yes** | 1000x `0` |

Records: `layout/bandgap-core/combine-determinism/20260923-062919-1e38c62/`.

So the committed `mismatch_count: 0` is **not falsified** -- it is exactly
what the pinned build reports, deterministically, 1000 times out of 1000, and
exactly what the newer build reports too whenever its combine step is kept off
the one code path identified below. The "12" is a false `mismatch`, not a
newly-detected defect: all twelve findings are `device.property` on the two
PNP groups (`ae`/`ab`/`pb`/`ac`/`pc`/`ne`), reporting a combined device whose
parameters were accumulated under an inverted rule.

**The isolated variable.** klayout-tools#1185/#1186 added a bounded retry to
`_combine_devices_safely` that runs every attempt but the last against an
independent `Netlist.dup()` copy, adopting the first clean one via
`Netlist.assign()`. With a budget of 1 the only attempt *is* the last one, so
the combine runs directly against the netlist and the `dup()` round trip never
happens -- and determinism returns. Confirmed further, below `klt`'s own API:
the wrong parameter set is already present on the `dup()` copy *before*
`assign()` (24/120 trials), and the device class survives `dup()` byte-identical
in type, name, parameter order and `is_primary` flags (80/80 trials), so
neither `assign()` nor a reshaped device class is the cause. A `git bisect`
over the 920 first-parent commits between the two builds lands on `66f73d0c`
-- the #1186 merge itself -- with its immediate predecessor 300/300
deterministic under the identical probe.

**Disposition: genuine tool regression, not a re-baseline.** This is
deliberately *not* a repeat of Section 7z's question. It is not the
`combine_devices` `fixed_offset_ohm` accounting change (klayout-tools#559/#583/
#587) this file already declined once and DR-003 ratified against. The
measurement record says so mechanically rather than by assertion -- its
`finding_totals` table is, across all 1000 trials, exactly twelve keys, all of
them `device.property/PNP/Q{1,2}/{ae,pe→ab,pb,ac,pc,ne}`-shaped geometry
parameters on the two PNP groups, each appearing on the same 238 trials. No
`res_high_po` finding, no topology finding, no `net.*` finding, ever. The
resistors this file's Section 7z/7y history is about match on every trial of
both outcomes. There is therefore no physical claim to re-ratify and **no
decision record is owed**: nothing about this layout, this repo's per-primitive
accounting, or the ratified spec is in question.

(`layout/bin/measure_fixed_offset_variants.py` was re-run under the installed
build as a cross-check and agrees -- its `primary_nodeck` row, this flow's own
request shape, reports `R2A`/`R2B`/`R1` as `matched` while carrying the twelve
PNP findings. It was deliberately **not** minted as a record: every one of its
four variants uses `options.combine_devices: true`, so its own numbers are
flake-contaminated on this build, and committing a record whose rendered
conclusion is drawn from contaminated numbers would put a false claim about
DR-003 into the evidence trail. Re-run it for a verdict only on a build where
the determinism record above reads `deterministic: yes`.)

Filed under this repo's friction protocol as
**[klayout-tools#2374](https://github.com/2AMLogic/klayout-tools/issues/2374)**
(bug-class-identical to klayout-tools#1497 -- a silent parameter mis-merge with
no exception and no `device.combine_incomplete` warning -- but reached via the
#1185 retry path and affecting `DeviceClassBJT3Transistor`).

**What did NOT change, on purpose.**

- `layout/requirements.txt`'s pin stays at `acb0ae6c`. Section 7dd's suggested
  next increment (bump past klayout-tools#800's `--parasitics` fix) now carries
  a prerequisite it did not have: any bump that crosses `66f73d0c` picks this
  nondeterminism up, so it should wait for klayout-tools#2374, or pass
  `options.combine_devices_max_attempts: 1` in this flow's request documents as
  part of the same bump. Do not bump and hope.
- The root `README.md`'s `mismatch_count: 0` claim stands unchanged -- the
  measurement above is what supports it, not a single lucky invocation.
- `signoff/block-manifest.json` item 4 stays **uncited and `unmet`**. Its
  blocker is unchanged (the committed 0.2.0 report's `provenance.input` is
  `null`, so no `content_hash` can be pinned against it) and this increment
  adds a second, independent reason not to close it the obvious way: the only
  builds that *do* populate `provenance.input.content_hash` are the ones whose
  combine step is intermittently wrong, so minting a fresh, hash-pinnable LVS
  report today would pin a verdict that does not reproduce. Item 4 closes on
  klayout-tools#2374, not on a re-run.

### 7gg. Thirty-fifth increment: the startup injector is drawn into the composed cell (issue #285) -- `devices.matched` 16 -> 22, and the first PSRR number this design has ever had with an injector attached

Drew the startup injector into the composed cell: `devices.matched` 16 -> 22,
and the first PSRR number this design has ever had with an injector attached.

Issue #285 -- record cited: `20260923-070209-dbd57a9`.

## 8. Known limitations / follow-on work

- **LVS is not clean.** *(Still open; the reason has now changed five
  times.)* At #15 the blocker was device recognition -- neither `bjt_array`
  nor `res_array` output extracted as devices at all. The first increment
  (PR #64) closed that and hit the single-routing-metal bussing gap
  (klayout-tools#433). The second closed *that* with a layout-side met1 bus
  and hit the MOS gate-contact gap (klayout-tools#461). The fourth
  increment closes that one too: gates are contacted, every split MOS group
  is bussed, and `klt lvs`'s `combine_devices` folds each into the
  schematic's own `m=N` device. `mismatch_count` is **106**, down from 355,
  and the layout side of the comparison is 39 devices against the
  reference's 16 (was 97). `devices.matched` is still 0. The fifth increment
  (Section 7c) added a rip-up-and-reroute repair pass and re-ran the flow;
  `mismatch_count` did not move -- see cause 1. PR #78 fixed two of `VDD`'s
  PMOS n-well taps (previously pinned to a single pad that had no free
  corridor), which took `klt lvs`'s correspondence from `0`/`0` device/net
  matches to `3`/`1` and `mismatch_count` from 106 to **92**. The fourteenth
  increment (Section 7l): `mismatch_count` is now **32**, `devices.matched`
  **6**, `nets.matched` **3** -- the deck-synthesized substrate net and
  undeclarable array dummies (causes 2/3 below, through the prior update)
  are both **retired**, not just improved. Cause 1's unrouted trio
  (`D1`/`GDRV`/`VSS`) is unchanged -- that increment did not touch routing
  or the floorplan, only the `klt` pin and the LVS request. The fifteenth
  increment (Section 7m) filed klayout-tools#506 for the arity
  reconciliation upstream and changed nothing in the flow. **Update,
  sixteenth increment (Section 7n)**: the former cause 4 (resistor
  device-class arity mismatch) is fixed for real, not just diagnosed, and
  without waiting on #506 --
  `reference.spice`'s R2A/R2B/R1 cards now carry the bulk terminal
  design/bandgap_core.sch already wires on each of them, verified directly
  (`klayout.db`) to reclassify `RES_HIGH_PO` as the same
  `DeviceClassResistorWithBulk` the layout side registers. `mismatch_count`
  did not move (still 32) -- tracing further shows the arity was never the
  *operative* blocker for these three devices; the DR-002 trim ladder's own
  always-drawn topology (new cause 3, below) is.
  **Update, nineteenth increment (Section 7q)**: `mismatch_count` is now
  **18** and `device.unmatched` is **1**. Two more causes are retired --
  the unrouted trio (the met2 escape plane, on klayout-tools#511) and the
  trim ladder's *labelling* -- and **no remaining mismatch is a
  connectivity difference**; every one is a `device.property` value or the
  single deliberately-undrawn device.
  **Update, twentieth increment (Section 7r)**: `mismatch_count` is
  unchanged at **18**, and that is the intended result -- the R2 leg-length
  defect is fixed, and what survives on those two devices is the same
  `res_high_po` model difference `R1` always showed, now arithmetically
  provable as such (both close on `5.2*L + 380`). One more cause is retired
  and, for the first time, **none of the remaining causes is a layout
  defect**. The current causes are:
  1. **MCC** is in the reference and deliberately not drawn (Section 6).
     The only `device.unmatched` entry left on either side.
  2. **`res_high_po`'s resistance model is not drawn geometry.** The
     reference models a segment as `R ~ 380 + 325*L`; the extractor derives
     R from body squares alone at 319.8 ohm/sq. `R1` reads 11,193 against
     11,755 and each R2 leg 86,346 against 88,130 -- differences of
     `5.2*35 + 380` and `5.2*270 + 380` respectively, i.e. the same two
     model constants on both devices, which is also the proof that each
     drawn body length (35 um, 270 um) is exactly the schematic's. No drawn
     shape can add a term the extractor's model does not carry, so this is
     not a layout defect.
  3. **The reference's PNP cards state no emitter count or geometry.**
     `Q1`/`Q2` now pair, and the comparer reports `ne` 8 (layout) vs 1
     (reference) plus zero-valued area/perimeter parameters. The schematic
     instantiates both at `m=8`, so the layout is right and the reference is
     silent -- but a bipolar's emitter area is not a value
     design/bandgap_core.sch states at all, so this is not the same
     one-line transcription fix the resistor bulk terminal was.
  Rewriting the reference netlist to enumerate the layout's own shortfalls
  would make LVS compare the layout against itself and is explicitly not
  done. **Retired as of Section 7l**: the substrate correspondence no
  longer needs a `hints` declaration at all (it is real drawn connectivity
  now), and array dummies are no longer counted as devices. **Retired as of
  Section 7n**: the resistor device-class arity mismatch (`res_high_po`'s
  sky130 device class carries a bulk terminal, `DeviceClassResistorWithBulk`
  / 3 nodes, that the reference's `R` cards previously did not,
  `DeviceClassResistor` / 2 nodes -- filed as klayout-tools#504, closed via
  #505's diagnostic-only fix, with the generic reconciliation #505 deferred
  filed by Section 7m as
  [klayout-tools#506](https://github.com/2AMLogic/klayout-tools/issues/506),
  still open). `reference.spice`'s cards now carry the bulk
  node too, because the schematic already wires it -- a transcription fix,
  not a reference edit to accommodate the layout, so this flow retires the
  cause without #506. #506 is left open on purpose: it remains the right
  ask for a reference that genuinely cannot state a bulk net, which this
  one can. **Retired as of Section 7q**: the unrouted trio (`D1`/`GDRV`/
  `VSS`), closed by the met2 escape plane that klayout-tools#511 made
  possible; and the trim ladder's *labelling* -- four `pins[]` labels on
  nodes interior to R2A/R2B were splitting each leg into three unpairable
  pieces, measured in isolation at 26 -> 18 mismatches and 13 -> 1
  `device.unmatched`. What Section 7n's cause 3 had conflated with that
  labelling artifact -- the trim ladder's real added *length* -- survived it
  as a filed layout defect (issue #91) rather than a structural stalemate.
  **Retired as of Section 7r**: that length. Each leg is now decomposed into
  50 coarse 5 um units plus 20 fine 1 um trim units, so the wired tap is
  exactly the schematic's 270 um (DR-002 code 0) and every other tap
  subtracts -- the direction DR-002 requires. `r2_leg_length()`'s verdict is
  a `flow_gate()` row now, not a recorded number, so the class of defect
  that hid here for nineteen increments fails the flow instead.
  **Retired as of Section 7s**: the PNP `ne`/area transcription gap (former
  cause 4), the same way cause 4's resistor counterpart (Section 7n) was --
  `reference.spice`'s `QQ1`/`QQ2` cards now state `AE`/`PE`/`NE`, derived
  from the vendor's own fixed `pnp_05v5_W0p68L0p68`/`_W3p40L3p40` macro
  geometry, not from anything this layout's own generator draws. Both PNP
  devices clear entirely (all seven parameters each, not just the three this
  fix states -- see Section 7s for why `AB`/`PB`/`AC`/`PC` disagreeing is
  not itself surfaced by `klt lvs`). The current causes, now two:
  1. **MCC** is in the reference and deliberately not drawn (Section 6).
     The only `device.unmatched` entry left on either side.
  2. **`res_high_po`'s per-device 380 ohm head term is not drawn
     geometry** -- unchanged, still an inherent extractor-model limit, and
     since Section 7r the whole of every remaining `r` difference.
  **Update, twenty-second increment (Section 7t)**: cause 2 above is now
  confirmed against the real `sky130_fd_pr__res_high_po` SPICE model card,
  not only this repo's own schematic-side approximation of it -- the real
  device is two series sub-resistors (a fixed end/contact term plus the
  length-scaling term `klt extract` already computes), so the gap is
  structural and has no layout-side fix. Filed generically as
  [klayout-tools#518](https://github.com/2AMLogic/klayout-tools/issues/518).
  `mismatch_count` is unchanged at **4**.
  **Update, twenty-third increment (Section 7u)**: #518 landed (merged via
  #519), and the companion fix that makes the correction reach the netlist
  `klt lvs` actually compares (#521, merged via #526) is picked up in the
  same bump. Neither closes cause 2 -- `mismatch_count` stays **4**, but
  the `r` delta on `R1`/`R2A`/`R2B` gets *larger*, not smaller, because
  this repo's own trim-tap decomposition draws each device as many
  (70, or 7) separately-contacted series primitives, and the per-instance
  offset is charged once per primitive rather than once per logical
  device when `combine_devices` folds the chain. Filed generically as
  [klayout-tools#559](https://github.com/2AMLogic/klayout-tools/issues/559).
  **Update, twenty-sixth increment (Section 7w)**: re-checked #559 directly
  -- still open, no movement; see Section 7w for what this increment found
  instead.
  **Update, twenty-seventh increment (Section 7y), cause 2 RETIRED**:
  klayout-tools#559 is still open upstream (a genuine ask for a `klt gen`
  continuous-poly-with-taps resistor capability), but it is no longer a
  live blocker of this repo's own `klt lvs` result. `reference.spice`
  settles the single-device-vs-chained transcription-convention question
  DR-003/issue #99 left open by switching to the chained value (the sum
  every drawn primitive in this repo's own decomposition pays, using the
  real `sky130_fd_pr__res_high_po` model's own two constants) -- exactly
  what `combine_devices` already sums the layout side to. `mismatch_count`
  moves **4 -> 1**; the only cause left is `MMCC` (below). This lands
  alongside the n_r2 54 -> 50 resize propagation (issue #99/DR-003's
  closure), re-transcribed into the drawn array by the same increment --
  see Section 7y for why the two are separable (the transcription-
  convention fix, not the resize's own sizing, is what closes this cause).
  **Update, twenty-eighth increment (Section 7z)**: the `klt` pin is bumped
  past [#583](https://github.com/2AMLogic/klayout-tools/pull/583) (which
  closed #559 by deferring the `fixed_offset_ohm` correction until after
  `combine_devices()` folds) and
  [#587](https://github.com/2AMLogic/klayout-tools/pull/587) (which made that
  deferral actually reachable on this flow's own pre-extracted request shape).
  Measured across all four accounting variants: adopting the deferral is not
  a lever on this repo's `mismatch_count`, and it is deliberately NOT adopted
  -- Section 7y's chained-value reference convention already states the value
  the layout's own chain sums to. See Section 7z.
- ~~**R2A/R2B ladder is at reduced scale**~~ -- **closed** by issue #62, see
  Section 4a. The ladder is drawn at its real full length: 92 coarse units
  (issue #99/#108-resized; was 100 before) plus 40 fine trim units = the
  schematic's 250 um per leg (was 270 um before).
- ~~**Per-matched-group guard rings are off in the routed layout**~~ --
  **closed** by this increment, see Section 5a. klayout-tools#441 landed;
  every matched group now has its own ring **and** is wired.
- **The amp's 4-device NMOS load/mirror group (MN1-MN4) is split into two
  matched pairs** because `diff_pair` only common-centroids two devices at a
  time; a true 4-device common-centroid quad (the textbook ABBA/BAAB
  arrangement for a group this size) is not directly expressible with
  today's generators. Not filed as new friction -- flagged here for whoever
  picks up full tape-out-ready layout, since it may be resolvable by a
  different placement of two `diff_pair` instances relative to each other
  rather than needing a new generator.
- ~~**Inter-block connectivity is now mostly drawn, but not complete**~~ --
  **closed by the nineteenth increment (Section 7q): 12 of 12 schematic
  inter-block nets are joined across every block they reach, 0 unrouted.**
  The whole history below is retained because it is the negative-result
  record that identified the cause, and because it is the cautionary tale:
  the sixth increment already found that sky130's curated deck had only two
  metal levels and that `"metal2"` was therefore not a second plane, and that
  finding sat here unfiled through six more increments of router-side
  experiments that could not have worked. Filed as klayout-tools#508 in the
  seventeenth increment, merged upstream as #511 within a day, and closed
  here on the escape plane built on it. **Historical detail follows.** 9 of
  12 schematic inter-block nets were joined across every block they reach (up
  from 6/12, and 4/12 before that), via met1 (Section 5a). **As of PR #78
  (Sections 7g/7h), the three still short are `D1`, `GDRV`,
  and `VSS`** (was `D1`, `VDD`, `VSS` through the eighth increment -- PR #78
  freed `VDD` by offering every PMOS guard-ring tap as a routing candidate
  instead of pinning to one, at the disclosed cost of the `core_mirror`
  corridor `GDRV`'s hop to `amp_pmirr`/`amp_nmirr` had been using). Each is
  `partial`: drawn between the blocks the router reached and stops where it
  did not. **The cause is no longer
  upstream.** Every one of these nodes is expressible now; what is missing
  is corridor in a floorplan whose widest block spans 180 of the cell's 300
  um and whose own comb trunks are the obstacle. Issue #62's criterion 1 is
  scored PARTIAL, not MET, on this. The fifth increment (Section 7c) tried
  the first candidate the fourth increment's own record proposed here -- a
  per-hop rip-up-and-reroute instead of the whole-cell per-order one -- and
  it did not free any of the three hops, which is real evidence the limit is
  the floorplan's free corridor, not a single net's choice of path. The
  sixth increment (Section 7d) investigated both candidates the fifth
  increment left open and ruled one out: klayout-tools#468 merged and is
  already in this repo's pinned `klt` commit, but its `"metal2"` role
  resolves to the *same* met1 layer `met1_bus.py` already hand-routes on
  (sky130's curated deck has only two metal levels total), and
  `gen-compose`'s own router is a less capable two-pin planner than this
  repo's own -- no new capacity, so **not a lever**. Widening this repo's
  own router search 2-3x (candidate assignments, chain orders, repair
  budget) also reproduced the identical result at ~2x runtime -- **also not
  a lever**. What is left is a floorplan revision that breaks
  `amp_input_pair` into two stacked halves so something can cross the
  middle of row 1 -- but Section 7d's per-hop data shows this can close at
  most `D1`/`VDD`; `VSS`'s blocked hop is entirely within row 0, unrelated
  to `amp_input_pair`, and needs its own, separate corridor fix between
  `pnp_ctat` and `pnp_ptat`. The seventh increment (Section 7e) ran the one
  remaining candidate -- widening the per-hop channel-search window -- to
  completion (the sixth increment's own same-day follow-up had tried this
  but could not verify it) and found it is **not** a lever either: it
  freed `VDD` but broke a previously-drawn net (`TAIL`) in trade, net
  schematic coverage unchanged at 9/12, `mismatch_count` 106 -> 105 (not
  material), runtime nearly doubled. Reverted, not shipped. The eighth
  increment (Section 7f) tried the row-0-only half of the fix pair without
  the full `amp_input_pair` redesign -- widening `place_blocks()`'s
  block-to-block margin for row 0 alone (16 -> 24 um) -- and found it is
  **not** a lever either: `VSS`'s blocked hop stayed blocked at the exact
  same block (`pnp_ctat`) before and after, so the extra spacing was not the
  resource its route was short of, while a previously-drawn net (`GDRV`)
  regressed to partial as an unrelated side effect of the whole-cell order
  search picking a different winner. Schematic coverage moved 9/12 -> 8/12
  (a net loss, not a lateral trade this time), `mismatch_count` 106 -> 107,
  and composed area grew to within ~3% of the 50,000 um^2 budget for the
  privilege. Reverted, not shipped. The tenth increment (Section 7h)
  re-verified the search-depth lever against PR #78's changed unrouted set
  (`D1`/`GDRV`/`VSS` in place of `D1`/`VDD`/`VSS`) and found the identical
  negative result -- byte-identical `mismatch_count`/coverage/blocked-hop
  attribution to the un-widened baseline, which Section 7g's exhaustive
  per-hop blocker tally then explains mechanically (the search already
  enumerates every candidate it can generate, against obstacles no budget
  reaches). The
  floorplan-split-plus-row-0-*re-placement* pair (not mere re-spacing) above
  remains the only unexplored path to closing AC1; `GDRV`'s blocked hop
  takes over `VDD`'s former role as the split candidate's target (both touch
  `core_mirror`'s row-1/row-2 crossing). The eleventh increment (Section 7i)
  finally attempted the row-0 half directly -- reordering row 0's five
  blocks so both PNP arrays sit adjacent, at zero area cost -- and found
  `VSS` genuinely fixable this way (all 5 hops routed, 0 conflicts) but
  every ordering tried trades it for a different row-0 net (`VB` in the
  cheaper ordering, `VB` fixed but `TRIM` and part of `VSS` itself lost in
  the other), net schematic coverage flat at best (9/12, `mismatch_count`
  byte-identical at 92) and worse at worst (8/12, `mismatch_count` 94).
  Neither shipped. This rules out 1D row-0 reordering as a category (on top
  of Section 7f's already-ruled-out re-spacing) and leaves a genuine 2D
  floorplan revision -- a second row for the resistor group (measured over
  budget by ~11% at this floorplan's current sizing, per Section 7i) or a
  dedicated row 0/row 1 corridor -- as the only path left for `VSS`. The
  twelfth increment (Section 7j) attempted the second-row candidate
  directly -- splitting row 0 into a PNP-only row (adjacent, per Section
  7i's own successful arrangement) and a resistor-only row, with
  `ROW_MARGIN_UM` lowered 22 -> 15 um uniformly to close the resulting 11%
  budget overrun -- and found it **fixes `VSS`'s own named hop** (direct
  per-hop evidence, not inferred) but is a net regression overall: two new
  casualties (`TRIM_A`/`TRIM_B`, both newly blocked by `VA`'s now-longer,
  now-narrower-channel route) plus `VSS`'s own remaining congestion moving
  to a different hop rather than clearing, for a net move of 9/12 -> 8/12
  coverage and `mismatch_count` 92 -> 94 -- worse than either of the
  eleventh increment's own trades. `GDRV`/`D1` are unaffected either way,
  consistent with every prior increment's finding that their blockers are
  intra-block comb geometry no floorplan-corridor change reaches. Reverted,
  not shipped. The thirteenth increment (Section 7k) tried exactly that
  non-uniform channel budget, in two shapes -- cutting only `RING_MARGIN_UM`
  (every row boundary left at its working 22 um width) and cutting only the
  row-2/row-3 (amp-to-mirror) boundary the resistor-row nets never cross --
  plus a control run of the same split with no margin touched at all. Every
  one of the three still nets a regression (9/12 -> 8/12 in all three,
  `mismatch_count` 92 -> 94 or 95), and, tellingly, `TRIM` -- a same-row net
  that crosses no row boundary in any of these runs -- breaks in the two runs
  that touch any margin elsewhere and survives in the one run that touches
  none. That rules out channel width, uniform or not, as the mechanism: the
  failure is the whole-cell route-*order* search re-converging on a different
  winning order for any floorplan perturbation, not a specific corridor
  running short. `GDRV`/`D1` are unaffected across all three runs, unchanged
  from every prior increment's finding. This closes off "non-uniform
  row-margin budget" as a category, the same way Section 7i closed off 1D
  reordering. What is left is qualitatively different from every lever tried
  in Sections 7c-7k: either an order-search change (route-order stability
  under small perturbations, or reordering intra- vs. inter-block drawing)
  or accepting the corridor deadlock as a hard limit of this router and
  pursuing a genuine third routing layer upstream (klayout-tools#454 merged,
  but its `"metal2"` role aliases to the same met1 layer on sky130 per
  Section 7d -- not the same thing as a second physical layer). **Update,
  seventeenth increment (Section 7o)**: that third-routing-layer capability
  gap had never actually been filed upstream, only ruled out locally --
  filed as [klayout-tools#508](https://github.com/2AMLogic/klayout-tools/issues/508).
  No code change; see Section 7o for what was verified against current
  `klayout-tools` source before filing.
- **Intra-block bussing is drawn for every device family**, on met1
  (Section 5a) -- PNP arrays, resistor ladders, and (from the fourth
  increment) MOS fingers. Each split MOS group now extracts and combines
  into the single `m=N` transistor the schematic names.
- **Array dummy edge units extract as real devices** with no schematic
  counterpart (klayout-tools#491 -- #462's extractor fix has no `dummy`
  layer to key off on sky130). Turning them off to shrink the LVS mismatch
  count would trade a real matching property for a smaller number, so this
  flow keeps them and reports the count honestly.
- ~~**The resistor flavour drawn does not match the schematic's**~~ --
  **closed** by klayout-tools#463 (merged via #475). The layout draws
  `res_high_po`, and `layout/bandgap-core/reference.spice`'s model name now
  states the schematic's device rather than the layout's former limit.
- **MCC is still not drawn** (analytic allocation only, Section 6) -- now
  the largest single un-budgeted item.
- **Every substrate-referred bulk terminal is compared against a synthesized
  net, not drawn geometry** -- now filed as
  [klayout-tools#490](https://github.com/2AMLogic/klayout-tools/issues/490).
  Both NMOS groups' substrate guard-ring taps are wired to `VSS` from the
  third increment on (Section 5b item 3), but sky130's extraction deck
  registers an *empty* region as the body source for every nfet, every
  `bulk_to_substrate` resistor and every bipolar collector, and
  `connect_global`s it to `vsubs`. No drawn metal changes that, and the
  reference is not edited to say `vsubs`; from the fourth increment the flow
  declares the correspondence to `klt lvs` as
  `hints.same_nets: [["vsubs", "VSS"]]` instead, which is a statement about
  the design (the substrate *is* grounded here) rather than about the
  layout. `klt lvs` also reports it as a `device.body_unverified` coverage
  warning of its own. The PMOS side *is* derived from drawn geometry
  (sky130's deck has a real tap layer), which is why wiring the PMOS well
  rings changed the extracted bulk from an anonymous net to `VDD`.

## 9. Evidence

- Routed layout driver (issue #62 -- gen/draw/compose+route/drc/extract/lvs):
  `layout/bin/gen_bandgap_routed.py`,
  `layout/bin/run-bandgap-routed-flow.sh`
- LVS reference netlist (schematic side, transcribed from
  `design/bandgap_core.sch` + `design/error_amp.sch`; topology corroborated
  by the checked-in `n_r2=54` xschem snapshot its header cites, resistor
  *values* transcribed from the resized `n_r2=50` chained-array sizing per
  `sim/res-array-resize/records/` -- see the file's own RESISTOR VALUE
  CONVENTION note; never derived from the layout):
  `layout/bandgap-core/reference.spice`
- Floorplan generation/placement/DRC driver (issue #15): **retired** in
  issue #215 -- `layout/bin/gen_bandgap_floorplan.py` /
  `layout/bin/run-bandgap-floorplan-flow.sh` are no longer in the tree; the
  routed driver above absorbed their work. The #15 records they produced
  stay under `layout/bandgap-core/reports/`.
- Per-increment narrative history (issue #62's increments 7a-7gg, condensed
  in Section 7 above): `layout/matching-plan-history.md`
- Current record (read this for the actual pass/fail evidence):
  `layout/bandgap-core/reports/LATEST` -> `layout/bandgap-core/reports/<record-id>/record.md`
- Contributor breakdown: `sim/monte-carlo-untrimmed/records/20260803-142259-544cc5e.md`
- Amp offset budget: `design/error-amp-offset-budget.md`
- Device geometry: `design/bandgap_core.sch`, `design/error_amp.sch`
- Trim network scoping: `spec/decision-records/DR-002-trim-network-scoping.md`
- `klt`-driven DRC/LVS flow this floorplan's DRC check reuses:
  `layout/README.md` (issue #14)
