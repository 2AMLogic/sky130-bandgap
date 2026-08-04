# Bandgap core -- floorplan and matching plan (issues #15, #62)

Written matching plan + initial placed layout skeleton for the sky130
Kuijk-style bandgap core (`design/bandgap_core.sch`, `design/error_amp.sch`).
This document states the matching-effort allocation and the reasoning
behind it; `layout/bin/gen_bandgap_floorplan.py` /
`layout/bin/run-bandgap-floorplan-flow.sh` generate, place, and DRC-check
the skeleton this document describes -- see
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
> ground -- the R2A/R2B ladder is now drawn at its **real 108-unit count**,
> inter-block routing and top-level pins **are** drawn, and PNP/NMOS/
> resistor devices **do** extract with correct classes. Where a statement
> below is now historical, it is marked as such rather than deleted, so the
> #15 skeleton's own records stay readable against the document that
> described them. The routed flow is
> `layout/bin/run-bandgap-routed-flow.sh` /
> `layout/bin/gen_bandgap_routed.py`; its record is the newest directory
> under `layout/bandgap-core/reports/`. Read that record for measured
> results; this document remains the rationale.

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

## 2. Device inventory

From `design/bandgap_core.sch` and `design/error_amp.sch` (read-only
references for this issue; not modified here):

| Device | Role | Geometry | Matched against |
|---|---|---|---|
| Q1 | CTAT PNP | m=8 x `pnp_05v5_W0p68L0p68` (0.4624 um^2/unit) | itself (8x array) |
| Q2 | PTAT PNP | m=8 x `pnp_05v5_W3p40L3p40` (11.56 um^2/unit) | itself (8x array) |
| R1 | dVBE-to-current leg | `res_high_po`, W=1um, L=35um (7 x 5um unit segments) | R2A/R2B via the K=R2/R1 ratio |
| R2A | VOUT-side divider leg (branch A) | `res_high_po`, W=1um, L=270um + trim (54 x 5um unit segments) | R2B |
| R2B | VOUT-side divider leg (branch B) | `res_high_po`, W=1um, L=270um + trim (54 x 5um unit segments) | R2A |
| trim taps | downward-only ladder-tap trim (DR-002) | `res_high_po`, W=1um, 1um/code, code 0..-16, both legs | integrated into the R2A/R2B array (this issue's acceptance criterion) |
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
- **Row 1 -- resistor network.** R2A/R2B as one interdigitated ladder
  (alternating unit segments -- see "Skeleton vs. real target counts"
  below for why the skeleton draws 16 of the real 108), R1 as its own
  matched group (same flavor/orientation, not interdigitated with R2A/R2B
  since it is a different nominal value with no same-value partner), and
  the downward-only trim taps as a third array of the same flavor/
  orientation, positioned to extend the R2A/R2B ladder (this issue's
  acceptance criterion: trim segments integrated into the same array, not
  a separate bolt-on structure).
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
| `res_r2` (R2A/R2B) | 16 units (8/leg) -- **superseded, see below** | 108 units (54/leg) | *(historical, #15)* a single-row `res_array` at 108 units is ~710 um long (measured directly: `klt gen res_array --params '{"num":108,...}'` reports `bbox_um.x1 - x0 = 709.6`) -- pairing that with any other block in a floorplan forces the whole composition's bounding box past the 0.05 mm^2 budget on width alone, even though the segments' own drawn area is small. `klt gen res_array` had no row-folding/meander parameter to keep a long unit-resistor string's *footprint* compact the way `mos_array`/`bjt_array`'s `rows`/`cols` do -- filed as new friction, [2AMLogic/klayout-tools#415](https://github.com/2AMLogic/klayout-tools/issues/415). |
| `res_r1` | 7 units | 7 units | drawn 1:1 (small enough to be tractable at full scale) |
| `res_trim` | 32 units (16/leg) | 32 units (16/leg) | drawn 1:1 |
| `amp_input_pair` | mult=16 (splits=16) | mult=16 | drawn 1:1 |
| `amp_nload` / `amp_nmirr` | mult=4 each | mult=4 each | drawn 1:1 |
| `amp_pmirr` | mult=8 (splits=8) | mult=8 | drawn 1:1 |
| `core_mirror` | mult=2 (splits=2) | mult=2 | drawn 1:1 |

### 4a. Ladder scale reduction: closed (issue #62)

**2AMLogic/klayout-tools#415 landed** (merged upstream via
klayout-tools#418), adding `res_array`'s `rows` fold parameter. The routed
flow (`layout/bin/gen_bandgap_routed.py`) therefore draws the R2A/R2B ladder
at its **real 108-unit count**, folded into 9 rows:

| | skeleton (#15) | routed (#62) |
|---|---|---|
| `res_r2` unit count | 16 | **108** (2 legs x n_r2=54) |
| `res_r2` footprint | ~110 x 12 um | ~101 x 12 um (9 folded rows) |
| composed cell bbox | 35,763 um^2 | **38,171 um^2** |
| budget | 50,000 um^2 | 50,000 um^2 |

Folding turns the ladder from the floorplan's width-dominating block into
one of its smaller ones: 108 units cost ~1,231 um^2 of footprint, and the
whole routed cell -- at the real count, with routing and the cell-level
guard ring -- still lands ~24% inside the 0.05 mm^2 budget. `res_r1`
(n_r1=7) and the trim ladder (32 taps) were already 1:1 and stay so; the
trim ladder is now folded into 4 rows for the same footprint reason.

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

### 5a. What issue #62's routed flow actually draws, and the ring trade-off

**Update (issue #62's second increment):** the `gen-compose` router
limitation described below (#434) was fixed upstream via
[klayout-tools#441](https://github.com/2AMLogic/klayout-tools/pull/441)
(ring-routing openings), so per-matched-group rings and inter-block
connectivity are no longer mutually exclusive in principle. This increment
did **not** spend its scope reverting the rings-off trade-off, though --
that is left to a follow-up so the increment's effort could go to intra-
block bussing (Section 8) instead. The rest of this subsection (written for
the first increment, PR #64) is otherwise still accurate: the routed layout
still keeps per-group rings off today.


**Drawn now** (measured in the routed record's own net/pin tables):

- Nine inter-block nets carrying the schematic's own names -- `VA`, `TRIM`,
  `VB`, `VBQ` along the core's PNP/resistor string; `TAIL`, `D1`, `PN`
  through the amplifier; and `VDD`/`VSS` supply hops. Each is drawn as
  labelled `li1` metal, so it survives `klt extract`'s pin promotion as a
  *named* `.SUBCKT` pin rather than an anonymous `$N` node.
- Twenty-three promoted top-level pins, including every device gate
  (`GDRV`, the amp's input and mirror gates) and the trim ladder's taps at
  **both ends of the DR-002 downward-only range**: `TRIM_A_CODE_0` /
  `TRIM_A_CODE_MINUS16` and the leg-B pair. That is the concrete answer to
  "which tap feeds which net" -- both range endpoints on both legs are
  addressable by name from a post-layout testbench (issue #16).

**Not drawn, and not claimed as drawn.** Those nine are 2-pin hops, one
adjacent block pair each. Scored against `design/bandgap_core.sch`'s *own*
inter-block node list instead of against that declaration, **4 of 12
schematic inter-block nets are joined across every block they reach**
(`TRIM`, `VBQ`, `TAIL`, `PN`). The rest exist in the layout only as promoted
pin labels on the blocks the metal never reached:

- `VOUT` is a labelled pin on `core_mirror` and is **not** routed to the
  R2A/R2B ladder tops.
- `AOUT` (amp output) and `GDRV` (mirror gate drive) are **one node in the
  schematic** but two separate, unrouted labelled pins in the layout.
- `D2` is not drawn at all; `VA`, `VB`, `D1` are drawn between two of their
  blocks but not to the amp gate they also feed.
- The `VDD` trunk reaches 2 of its 3 blocks and `VSS` 2 of its 7 -- a trunk
  is only expressible as a chain of 2-pin hops between blocks that happen to
  be adjacent across an empty channel. `VSS`'s seven include the three
  resistor blocks: `res_high_po` is a 3-terminal device whose bulk ties to
  `VSS` in the schematic (`design/bandgap_core.sch` `r2ab`/`r2bb`/`r1b`).
  The reference cards drop that bulk terminal because the `klt` LVS reader's
  `res_generic_po` is 2-terminal, but the coverage table states what the
  *schematic* requires, not what the reference happens to model.

The routed record's "Schematic inter-block nets: drawn vs. labelled only"
table is the measured, per-net version of this list, and issue #62's
criterion 1 is scored **PARTIAL** on it. The cap is the same
[klayout-tools#433](https://github.com/2AMLogic/klayout-tools/issues/433)
single-routing-metal limit that blocks LVS closure, plus #434 below; the
reference netlist is *not* adjusted to accommodate any of it (an earlier
revision bridged `AOUT`/`GDRV` with a 0-ohm device -- that is removed).

**The trade-off this forced.** `klt gen-compose`'s router rejects *every*
route to a non-tap port on a block that reports a guard/collector ring (the
route would cross the ring's own metal loop and merge with its tap net), and
offers no opening to route through -- filed as
[2AMLogic/klayout-tools#434](https://github.com/2AMLogic/klayout-tools/issues/434).
So today, a matched group can have its own ring, or it can be wired to the
rest of the circuit, but not both.

The routed layout takes connectivity: **the per-matched-group rings
(`diff_pair`'s `add_guard_ring`, `bjt_array`'s `add_collector_ring`) are
off, and the cell-level ring is kept.** This is a real matching-quality
regression against the strategy stated at the top of this section, recorded
here rather than quietly dropped -- the per-group rings exist precisely to
stop substrate noise near one group from coupling asymmetrically into a
neighbour, which Section 1 identified as the dominant VOS term's mechanism.
It should be reverted as soon as #434 (or a second routing metal, #433)
makes ringed groups routable. The n-well under each PMOS group is still
drawn by `diff_pair` itself, so the well-isolation half of the strategy is
intact; only the local tap ring is absent.

## 6. Area budget

| Item | Area |
|---|---|
| Amp transistors (MP1/MP2 + MN1-MN4 + MP3/MP4), analytic | 10,880 um^2 (`design/error-amp-offset-budget.md` Section 4) |
| MCC compensation cap, analytic (single-ended, not a matched pair -- see Section 2) | 9,600 um^2 |
| Core PNP + resistor + mirror devices, analytic (drawn/emitter area only) | ~735 um^2 (MPOUT+MPAMP 64, Q1 3.7, Q2 92.5, R1 35, R2A+R2B 540) |
| **Analytic device total** | **~21,215 um^2** |
| **Skeleton composed floorplan bbox** (measured, #15 -- includes guard rings, dummies, spacing, and the reduced R2A/R2B count from Section 4) | **35,763 um^2** (`layout/bandgap-core/reports/20260803-192947-e7a30b4/record.md`) |
| **Routed composed floorplan bbox** (measured, #62 -- includes inter-block routing, the cell-level guard ring, and the **real 108-unit** R2A/R2B ladder) | **38,171 um^2** (`layout/bandgap-core/reports/LATEST/record.md`) |
| **Budget** | **50,000 um^2 (0.05 mm^2)** |

The skeleton's measured footprint (35,763 um^2) was within budget with ~29%
margin, but did **not** include the R2A/R2B ladder at its real 108-unit
count. Issue #62 closed that gap (Section 4a): the routed cell draws the
full 108-unit ladder *and* its inter-block routing and still measures
38,171 um^2 -- ~24% inside the 50,000 um^2 budget. The budget claim now
covers the real device counts, not a reduced-scale stand-in.
`design/device-characterization-summary.md`'s own note on `MPOUT`/`MPAMP`
sizing (a potential 6.25x per-unit-area increase to size E) is a small
fraction of the remaining ~11,800 um^2 margin and is not expected to be a
blocker on its own. The largest un-budgeted item is now MCC, still carried
analytically (9,600 um^2) rather than drawn -- adding it would consume most
of the remaining margin, so it is the next real area question.

## 7. `klt` generator mapping and friction

Status as of issue #62's routed flow (the #15 column is kept because the
skeleton's own checked-in records were produced under it):

| Matched group | Generator | DRC-clean | Extraction status at #15 | Extraction status at #62 |
|---|---|---|---|---|
| PNP arrays (Q1, Q2) | `bjt_array` | yes | no -- `klt extract` on a `bjt_array` output reports `device_count: 0` | **yes, 16 `pnp` devices**, via a locally-composed recognition overlay (82/44 marker + 65/44 nwell tap per unit). The generator still draws neither -- [2AMLogic/klayout-tools#432](https://github.com/2AMLogic/klayout-tools/issues/432) |
| Resistor ladders (R2A/R2B, R1, trim) | `res_array` | yes | no -- never drew the PDK's resistor-ID marker layer (2AMLogic/klayout-tools#369) | **yes, 159 `res_generic_po` devices** -- #369 merged upstream via klayout-tools#382 |
| Amp input pair, NMOS loads/mirrors, PMOS mirror, core mirror | `diff_pair` | yes | not attempted | **yes, 52 `pfet` + 16 `nfet`** -- the nfet flavour needed klayout-tools#421 (guard-ring well tie enclosing nfet devices in nwell), merged via klayout-tools#426 |
| Overall guard ring | `guard_ring` (standalone) | yes | n/a | n/a -- composed in a **second** `gen-compose` pass, because a ring enclosing the whole floorplan reports a bbox that the router treats as an obstacle vetoing every net |
| Per-group guard rings | `add_guard_ring`/`add_collector_ring` (built into `diff_pair`/`bjt_array`) | yes | n/a | **off** -- mutually exclusive with routing today, see Section 5a and [klayout-tools#434](https://github.com/2AMLogic/klayout-tools/issues/434) |
| 2D floorplan composition | `gen-compose` `placement.strategy: "explicit"` | n/a | n/a | plus `connectivity[]` routing and `pins[]` pin promotion |

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

### 7a. Friction filed while routing the core (issue #62)

**First increment (PR #64), three gaps filed:**

- **[klayout-tools#432](https://github.com/2AMLogic/klayout-tools/issues/432)**
  -- `gen bjt_array` draws neither the bipolar device-recognition marker nor
  the well tap that the *same tool's* sky130 extraction deck requires, so a
  generated bipolar array extracts as zero devices. **Closed upstream** via
  [klayout-tools#440](https://github.com/2AMLogic/klayout-tools/pull/440):
  `bjt_array` now draws both natively, per unit; the routed flow's local
  recognition-overlay workaround was retired once the pin bumped past it.
- **[klayout-tools#433](https://github.com/2AMLogic/klayout-tools/issues/433)**
  -- the router can only draw on the device-pad metal (sky130's role table
  exposes one metal role and no via, though the extraction deck declares
  two metals and a via), and self-nets were exempt from the obstacle check,
  so intra-block bussing was drawn as a certified-`routed: true` short.
  **Closed upstream** via
  [klayout-tools#439](https://github.com/2AMLogic/klayout-tools/pull/439),
  but only its "fail visibly" option (a crossing self-net now reports
  `unrouted_nets[]` instead of silently shorting) -- the underlying
  capability gap (no metal2/via role, so bussing still cannot be routed by
  `gen-compose` itself) was re-raised as
  [klayout-tools#454](https://github.com/2AMLogic/klayout-tools/issues/454).
- **[klayout-tools#434](https://github.com/2AMLogic/klayout-tools/issues/434)**
  -- no way to route into a guard-ringed block, forcing the ring/connectivity
  trade-off in Section 5a. **Closed upstream** via
  [klayout-tools#441](https://github.com/2AMLogic/klayout-tools/pull/441)
  (ring-routing openings); restoring the rings this repo still keeps off is
  a follow-up (Section 5a's update note).

Two gaps this issue **picked up rather than filed**, having landed upstream
in the interval: klayout-tools#415 (`res_array` row folding, Section 4a) and
klayout-tools#421 (`diff_pair`'s nfet-in-nwell misclassification). Both are
covered by `layout/requirements.txt`'s pin bump; #421's fix was verified
effective before relying on it (an isolated `flavor: "nfet"` `diff_pair` now
extracts `{"nfet": 8}`, not `pfet`).

**Second increment, three new gaps filed** (found while implementing the
hand-drawn met1+mcon bus technique #433/#454 left necessary):

- **[klayout-tools#453](https://github.com/2AMLogic/klayout-tools/issues/453)**
  -- #439's "fail visibly" self-net check misses a same-row, same-direction
  port pair: reproduced directly on an 8-unit `bjt_array`, a self-net
  between two north-facing emitter ports in the same row composed
  `routed: true`, DRC-clean, and, confirmed by extraction, absorbed the
  array's entire shared base node into the route -- the exact silent-short
  shape #439 was meant to close, just not caught by it in this case. Worked
  around by not relying on `gen-compose`'s self-net router for busing at
  all (the hand-drawn met1+mcon technique is verified independently by this
  flow's own extraction check on every run).
- **[klayout-tools#454](https://github.com/2AMLogic/klayout-tools/issues/454)**
  -- re-raises #433's still-open Ask (a `metal2`/`via` routing role, or
  via-drop support), since #439 shipped only the "fail visibly" safety net.
  This is why the routed flow draws its own met1+mcon bus geometry by hand
  via `klt draw` instead of asking `gen-compose` to route it.
- **[klayout-tools#466](https://github.com/2AMLogic/klayout-tools/issues/466)**
  -- `klayout.db.Netlist.combine_devices()` (via `klt lvs`'s
  `options.combine_devices: true`) raises an uncaught `RuntimeError` on a
  partial-match device group: a PNP array's 8 real + 4 dummy units all
  share base and collector, but only the 8 real units additionally share
  the (now-bussed) emitter -- confirmed by isolation that the crash is
  specifically the partial 2-of-3-terminal overlap, not the busing itself.
  The routed flow catches this and falls back to `combine_devices: false`
  for that run rather than aborting.

## 8. Known limitations / follow-on work

- **LVS is not clean.** *(Still open; the reason narrowed again in issue
  #62's second increment.)* At #15 the blocker was device recognition --
  neither `bjt_array` nor `res_array` output extracted as devices at all.
  That half is closed. The first routing increment (PR #64) closed nothing
  on the bussing side -- `klayout-tools#433`'s single-routing-metal limit
  meant no array's units could be bussed at all, so every matched group's
  instances stayed separate devices. The second increment closes it for the
  PNP arrays specifically: each array's 8 real emitters are bussed by hand
  on met1+mcon (verified correct by extraction, not just DRC -- see
  `gen_bandgap_routed.py`'s `MANUAL_BUS_TECHNIQUE_NOTE`), each array's
  shared base is bridged to the VSS trunk
  (`PNP_BASE_VSS_BRIDGE_NOTE`), and `klt lvs` is run with
  `options.combine_devices: true` so a correctly-bussed group *can* collapse
  into the reference's single multiplicity-N device. `diff_pair` MOS finger
  busing was attempted with the same technique and reverted after being
  found geometrically unsafe there (interleaved S/G/D positions across
  nearly the whole block width mean a stacked-bus-level approach cannot
  avoid cross-net shorts without real per-net channel routing -- see
  `MOS_FINGER_BUS_NOTE`), and R2A/R2B/R1's series-chain busing was not
  attempted this increment either (`RESISTOR_CHAIN_NOTE`). A genuine
  upstream `klayout.db.Netlist.combine_devices()` crash on a partial-match
  device group (found while busing the PNP arrays' real+dummy mix) is filed
  as [klayout-tools#466](https://github.com/2AMLogic/klayout-tools/issues/466);
  this flow catches it and falls back to `combine_devices: false` for that
  run rather than aborting. `klt lvs` still reports `mismatch`; the routed
  record's "LVS mismatch analysis" section quantifies it. Rewriting the
  reference netlist to enumerate the layout's own un-bussed devices would
  make LVS compare the layout against itself and is explicitly not done.
- ~~**R2A/R2B ladder is at reduced scale**~~ -- **closed** by issue #62, see
  Section 4a. The ladder is drawn at its real 108-unit count.
- **Per-matched-group guard rings are off in the routed layout** -- see
  Section 5a. Revert as soon as klayout-tools#434 or #433 lands.
- **The amp's 4-device NMOS load/mirror group (MN1-MN4) is split into two
  matched pairs** because `diff_pair` only common-centroids two devices at a
  time; a true 4-device common-centroid quad (the textbook ABBA/BAAB
  arrangement for a group this size) is not directly expressible with
  today's generators. Not filed as new friction -- flagged here for whoever
  picks up full tape-out-ready layout, since it may be resolvable by a
  different placement of two `diff_pair` instances relative to each other
  rather than needing a new generator.
- **Inter-block connectivity is only partial** -- 4 of 12 schematic
  inter-block nets are joined across every block they reach; `VOUT`,
  `AOUT`/`GDRV` and `D2` are labelled pins with no metal between them, and
  the `VDD` trunk still stops short of a block it supplies (Section 5a).
  `VSS` improved in issue #62's second increment via the hand-drawn
  PNP-base-to-VSS bridge (`PNP_BASE_VSS_BRIDGE_NOTE`), which is not a
  `gen-compose` hop but is counted in the routed record's coverage table --
  it now reaches 4 of its 7 blocks, up from 2. `klt gen-compose` itself
  still routes 2-pin nets between channel-adjacent blocks only, so the rest
  needs klayout-tools#433/#454 (a second metal + via) or a floorplan whose
  every net happens to fall between neighbours. Issue #62's criterion 1 is
  scored PARTIAL, not MET, on this.
- **Intra-block connectivity is drawn for PNP emitters only.** *(Narrowed
  in issue #62's second increment; see the LVS bullet above for what
  changed and why the rest was not attempted.)* Each PNP array's real
  emitters are bussed and its base bridged to VSS. `diff_pair` split
  fingers and each resistor ladder's series segments remain separate nodes
  -- the former was tried and found unsafe with this flow's technique, the
  latter was not attempted this increment.
- **MCC is still not drawn** (analytic allocation only, Section 6) -- now
  the largest single un-budgeted item.

## 9. Evidence

- Routed layout driver (issue #62 -- gen/draw/compose+route/drc/extract/lvs):
  `layout/bin/gen_bandgap_routed.py`,
  `layout/bin/run-bandgap-routed-flow.sh`
- LVS reference netlist (schematic side, transcribed from
  `design/bandgap_core.sch` + `design/error_amp.sch` and corroborated by the
  checked-in `n_r2=54` xschem snapshot its header cites, never derived from
  the layout): `layout/bandgap-core/reference.spice`
- Floorplan generation/placement/DRC driver (issue #15, unchanged):
  `layout/bin/gen_bandgap_floorplan.py`,
  `layout/bin/run-bandgap-floorplan-flow.sh`
- Current record (read this for the actual pass/fail evidence):
  `layout/bandgap-core/reports/LATEST` -> `layout/bandgap-core/reports/<record-id>/record.md`
- Contributor breakdown: `sim/monte-carlo-untrimmed/records/20260803-142259-544cc5e.md`
- Amp offset budget: `design/error-amp-offset-budget.md`
- Device geometry: `design/bandgap_core.sch`, `design/error_amp.sch`
- Trim network scoping: `spec/decision-records/DR-002-trim-network-scoping.md`
- `klt`-driven DRC/LVS flow this floorplan's DRC check reuses:
  `layout/README.md` (issue #14)
