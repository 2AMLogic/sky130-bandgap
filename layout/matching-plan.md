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
is what turns the 108-unit ladder into two real series resistors and each
8-unit PNP array into one real `m=8` device, instead of N unconnected units.

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
| **Routed composed floorplan bbox** (measured, #62 second increment -- includes intra-/inter-block met1 bussing, per-group **and** cell-level guard rings, and the **real 108-unit** R2A/R2B ladder) | **40,019 um^2** (`layout/bandgap-core/reports/LATEST/record.md`) |
| **Budget** | **50,000 um^2 (0.05 mm^2)** |

The skeleton's measured footprint (35,763 um^2) was within budget with ~29%
margin, but did **not** include the R2A/R2B ladder at its real 108-unit
count. Issue #62 closed that gap (Section 4a): the routed cell draws the
full 108-unit ladder *and* its inter-block routing and measures 40,019 um^2
-- ~20% inside the 50,000 um^2 budget (the second increment's restored
per-group guard rings and met1 busing cost ~1,848 um^2 versus the first
increment's ring-off, unbussed 38,171 um^2, still comfortably inside
budget). The budget claim now covers the real device counts, not a
reduced-scale stand-in.
`design/device-characterization-summary.md`'s own note on `MPOUT`/`MPAMP`
sizing (a potential 6.25x per-unit-area increase to size E) is a small
fraction of the remaining ~11,800 um^2 margin and is not expected to be a
blocker on its own. The largest un-budgeted item is now MCC, still carried
analytically (9,600 um^2) rather than drawn -- adding it would consume most
of the remaining margin, so it is the next real area question.

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

### 7a. Friction filed while routing the core (issue #62)

**First increment (PR #64), all three now CLOSED upstream:**

- **[klayout-tools#432](https://github.com/2AMLogic/klayout-tools/issues/432)**
  (closed via #440) -- `gen bjt_array` now draws the bipolar
  device-recognition marker and well tap itself; the local recognition
  overlay PR #64 had to compose is retired.
- **[klayout-tools#433](https://github.com/2AMLogic/klayout-tools/issues/433)**
  (closed via #439) -- the router now *rejects* a same-block bus attempt
  instead of certifying it as a routed short. It does not make bussing
  drawable -- see #454 below, and Section 5a for the met1 workaround this
  increment uses instead.
- **[klayout-tools#434](https://github.com/2AMLogic/klayout-tools/issues/434)**
  (closed via #441) -- `ring_gap_side` lets the router cross into a
  guard-ringed block, so per-group rings and connectivity are no longer
  mutually exclusive (Section 5a).

**Second increment (this PR), the residual blockers on LVS closure:**

- **[klayout-tools#454](https://github.com/2AMLogic/klayout-tools/issues/454)**
  -- re-raises #433's un-shipped half: there is still no metal2/via role or
  via-drop routing, so `gen-compose` itself cannot draw an intra-block bus;
  this flow's `met1_bus.py` is a layout-side workaround, not a fix.
- **[klayout-tools#461](https://github.com/2AMLogic/klayout-tools/issues/461)**
  -- MOS gate poly is drawn exactly coincident with the diffusion edge, so
  no contact can land on a gate at all. **This is the dominant blocker on
  criterion 4** (Section 8): it blocks all MOS finger bussing and every
  schematic node that terminates on a gate.
- **[klayout-tools#462](https://github.com/2AMLogic/klayout-tools/issues/462)**
  -- the dummy-device marker-layer suppression path only covers MOS gates,
  never bipolar or resistor devices, so this layout's array dummy edge
  units extract as real, unmatched devices.
- **[klayout-tools#463](https://github.com/2AMLogic/klayout-tools/issues/463)**
  -- `res_array` on sky130 can only draw the base `res_generic_po` flavour;
  a schematic built on a higher-sheet-rho flavour has no matching drawable
  device class.

**Third increment, one new filing (since CLOSED via klayout-tools#481):**

- **[klayout-tools#470](https://github.com/2AMLogic/klayout-tools/issues/470)**
  -- when two different net labels land on one electrical net, KLayout names
  it `A|B`, and `klt extract` emits that net with an empty `warnings[]`
  while `klt lvs` compares it without comment. The most dangerous error this
  toolchain can produce -- "the layout asserts two schematic nodes are one"
  -- is reported only as a punctuation mark inside a net name, invisible to
  DRC (the collision is between labels, through a pad, not between wires).
  Found because the second increment's own layout had shipped one; see
  Section 5b item 4. The flow now scans the extracted netlist for it and
  gates on the result, but every caller having to reinvent a `"|" in name`
  check is the gap.

None of #461/#462/#463 moved upstream during the third increment, so none of
their consequences changed. What changed is how much is attributed to them:
Section 5b lists four things that had been recorded as blocked by #461 and
were not.

### 7b. Fourth increment: every named blocker closed, three new ones found

All five gaps the third increment was waiting on merged upstream, and
`layout/requirements.txt`'s pin is bumped past all of them:

| upstream gap | fixed by | what it changed here |
|---|---|---|
| [#461](https://github.com/2AMLogic/klayout-tools/issues/461) MOS gate poly has no contact landing area | #474 | **the increment.** Gates are contactable, so every split MOS group is bussed into one `m=N` device and the six schematic nodes that terminate on a gate are drawn |
| [#462](https://github.com/2AMLogic/klayout-tools/issues/462) dummy marker is MOS-gate-only | #471 | nothing, on sky130 -- see #491 below |
| [#463](https://github.com/2AMLogic/klayout-tools/issues/463) `res_array` base flavour only | #475 | the resistor blocks draw the schematic's own `res_high_po`, so the device class matches |
| [#454](https://github.com/2AMLogic/klayout-tools/issues/454) no metal2/via role | #468 | not yet taken up: `met1_bus.py` still hand-plans its wires. Moving onto router-planned routing is real rework, called out in `MET1_BUS_NOTE` |
| [#470](https://github.com/2AMLogic/klayout-tools/issues/470) silent `A|B` merged net names | #481 | the flow's own label-collision gate stays (it is what caught the original), but the upstream silence is fixed |

Three new filings, all generic tool-gap descriptions:

- **[klayout-tools#490](https://github.com/2AMLogic/klayout-tools/issues/490)**
  -- the sky130 extraction deck registers an **empty** region as the body
  terminal source for every nfet, every `bulk_to_substrate` resistor and
  every bipolar collector, and `connect_global`s it to a synthesized
  `vsubs` net. No drawn shape can ever join that net, so a reference
  netlist that names its substrate node (every real schematic does) can
  never match. **This is the dominant remaining LVS term**, and unlike every
  previous dominant term it cannot be attacked from the layout side at all.
- **[klayout-tools#491](https://github.com/2AMLogic/klayout-tools/issues/491)**
  -- #462's extractor-side fix is unreachable on sky130: the curated deck
  declares no `dummy` layer, no generator draws one, and `klt extract`
  exposes no override. So array dummy edge units still extract as real,
  unmatched devices.
- **[klayout-tools#492](https://github.com/2AMLogic/klayout-tools/issues/492)**
  -- `gen-compose`'s router resolves only metal roles, so it cannot reach
  the poly gate port #461's landing pad exists for. Not a blocker (this
  repo draws the licon and li1 riser itself in `met1_bus.gate_contact`), but
  every consumer that wants a gate wired now re-derives the same stack from
  layer numbers read out of the extraction deck.

Two gaps the first increment **picked up rather than filed**, having landed
upstream in the interval: klayout-tools#415 (`res_array` row folding,
Section 4a) and klayout-tools#421 (`diff_pair`'s nfet-in-nwell
misclassification). Both are covered by `layout/requirements.txt`'s pin
bump; #421's fix was verified effective before relying on it (an isolated
`flavor: "nfet"` `diff_pair` now extracts `{"nfet": 8}`, not `pfet`).

### 7c. Fifth increment: rip-up-and-reroute, no filing, no number moved

The fourth increment's own record named the highest-value next lever as its
own router, not an upstream gap: `D1`, `VDD` and `VSS` each have exactly one
hop that comes up short on every one of `ROUTE_ORDER_PASSES`' whole-cell
reorderings, because reordering *which net draws first* cannot express "net
J's own greedy first solution sits exactly where net K's one remaining hop
needs to go, and no order changes that because J must still be drawn before
K". This increment builds that missing mechanism:
`gen_bandgap_routed._route_one_net` (the per-net solver, split out of
`route_inter_block_nets` so it can be called in isolation),
`_replay_tail` and `_repair_unrouted_hops` run once, after the order-search
above picks its winner: find a still-unrouted hop, read which already-drawn
net blocked it, and -- when that net is itself earlier in the same draw
order -- roll back to just before it, redraw it forced past its own first
`skip_first` fully-routed solutions (its "next-best" routing against the
same geometry), and replay everything after it so the forward pass's "a net
only ever sees final geometry" invariant still holds. Kept only if the
total unrouted-hop count drops and no new drawn-short conflict appears;
reverted and blacklisted otherwise, bounded to `REPAIR_MAX_SKIPS_PER_NET`
(3) attempts per blocker net and `REPAIR_MAX_ATTEMPTS` (8) total, so a
genuine capacity deadlock costs a fixed, small multiple of one order-search
pass rather than looping.

**It ran, found real targets, and did not move the number.** The repaired
record's `bus-summary.json` shows the repair pass's own attempt entry in
`_route_order_attempts` (`"repair_pass": true`): it identified `VSS`'s
failing hop as blocked by the already-routed `VOUT` (drawn nine positions
earlier in the winning order) and `D1`'s as blocked by `D2` (drawn first),
both legitimate rip-up targets by the ordering rule above, and forced each
through its available alternate solutions. Neither alternate freed the
target hop; the repaired attempt's score tied the order-search's own best
(`"kept": false`), so the original geometry was kept unchanged.
`mismatch_count` is unchanged at **106**, `pin_count` unchanged at **16**,
`device_counts` unchanged, and the same three schematic nets (`D1`, `VDD`,
`VSS`) are still `partial` in the coverage table -- a clean, evidence-backed
negative result, not a regression.

**What this narrows for the next increment.** The remaining congestion
survives being asked "what is your next-best routing against the same
geometry" at the per-net level (`CANDIDATE_ASSIGNMENTS`/chain-order
granularity), which is real evidence that a single net's own alternate
choices are not the limiting resource here -- the floorplan's free
corridors themselves are. That leaves the fourth increment's other two
candidates as the ones actually worth attempting next: taking up
klayout-tools#468's metal2/via1 roles so the router (not this repo) plans
the wires on a second layer entirely, or a floorplan revision that splits
`amp_input_pair` (180 of the cell's 300 um) so something can cross the
middle. No new upstream friction filed this increment -- the gap this
increment closes (a router capability, not a `klt` capability) and the gap
it leaves open (floorplan congestion) are both this repo's own.

### 7d. Sixth increment: both remaining candidates investigated -- one ruled out, one narrowed, no code shipped

The fifth increment's own record left two candidates for closing AC1: take
up klayout-tools#468's metal2/via1 roles, or split `amp_input_pair`. This
increment investigated both against `origin/main` (`a969fee`) before
committing to either, and found the first is not viable at all and the
second would not, by itself, be sufficient -- so no router or floorplan
change is shipped here. Both findings are worth recording so a future
increment does not re-spend time re-discovering them.

**klayout-tools#468 is already merged, already in this repo's pinned `klt`
commit, and does not add routing capacity for this design.**
`2AMLogic/klayout-tools#468` (`de334e5`, closing issue #454) merged
2026-08-04, and `git merge-base --is-ancestor` against the two commits
confirms it is an *ancestor* of `8c277eb` -- the commit this repo's
`layout/requirements.txt` already pins as of PR #71 -- so no pin bump is
needed to have it. But reading `klayout_tools.gen._PDK_ROLE_LAYERS` and
`klayout_tools.decks.sky130.EXTRACTION_DECK` directly (source, not the PR
description) shows why it does not help here: for the `sky130` family,
`"metal2"` resolves to `(68, 20)` and `"via1"` to `(67, 44)` -- i.e.
`EXTRACTION_DECK.metals[1]`/`.vias[0]`, which are exactly met1 and mcon,
the same two layers `met1_bus.py` already hand-draws every bus and
inter-block net on (MET1_BUS_NOTE). sky130's curated extraction deck
declares only two metal levels in total (`metals=((67,20),(68,20))` --
li1, met1); there is no third physical layer for `"metal2"` to expose. The
role lets `gen-compose`'s own router *plan* wires on met1 with via-drops to
li1 pads -- capability this repo's hand-written router already has and
already fully exercises. Separately, `gen_compose.route_two_pin` is a
two-pin-only Manhattan-backbone planner (one jog, five diagnostic checks);
it has no equivalent of this repo's own per-net candidate-assignment
search, multi-order chain routing, or the channel-track/detour search
`_connect`/`_channel_paths` run. Swapping onto it would trade a more
capable per-net router for a less capable one, on the same physical layer,
for zero new capacity. **Ruled out**: klayout-tools#468 is not a lever for
AC1 closure on this floorplan, and no further increment should re-evaluate
it without new evidence (e.g. a *third* metal level being curated for
sky130 upstream, which #468 is not).

**Widening this repo's own router search by 2-3x reproduces the identical
result, at roughly double the runtime.** As a second, independent
experiment (not committed -- see below), `CANDIDATE_ASSIGNMENTS` (3->6),
`CANDIDATES_PER_TERMINAL` (3->5), `REPAIR_MAX_SKIPS_PER_NET` (3->8) and
`REPAIR_MAX_ATTEMPTS` (8->24) were all raised together and the full flow
re-run against the unmodified floorplan. Runtime went from ~13 min to
26:04 (`time` total); the result was byte-identical to the fifth
increment's own record in every gated field: `mismatch_count=106`,
9/12 schematic nets drawn, and the same three hops unrouted with the same
`blocked_by` attributions (`D1` by `D2`, `VDD` by `GDRV`/`TAIL`, `VSS` by
`VOUT`). This is stronger evidence than the fifth increment's own (which
tried a bounded `skip_first<=3` search) that the remaining congestion is a
genuine floorplan free-corridor deadlock, not a search-depth limit -- and
it is not worth carrying as a permanent cost (2x runtime, zero
improvement), so the parameter changes were reverted rather than kept.
**Ruled out**: increasing this router's own search depth, at least up to
this multiple, is not a lever either.

**New data narrowing the floorplan-split candidate itself.** Reading
`bus-summary.json`'s `_inter_block` records (not just the coverage table)
for the three still-unrouted hops shows the floorplan-split candidate is
not sufficient on its own, even if it works:

- `VDD`'s two failing hops are blocked by `GDRV` and `TAIL` respectively,
  both of which are drawn *after* `VDD` in the winning net order. The
  repair pass's own eligibility rule
  (`net_index[blocker] < net_index[failing_net]`, `_repair_unrouted_hops`)
  permanently excludes a later-drawn blocker from ever being a rip-up
  target -- so no amount of `REPAIR_MAX_SKIPS_PER_NET`/`REPAIR_MAX_ATTEMPTS`
  budget could ever free `VDD` via this mechanism, independent of the
  search-depth finding above. A structural note, not a tuning one.
- `VSS`'s failing hop (`pnp_ptat:VSS trunk` -> `pnp_ctat:VSS trunk`,
  blocked by `VOUT`) is entirely within **row 0** (the resistor/PNP row,
  `pnp_ctat` at x~7 to `pnp_ptat` at x~280) -- physically unrelated to
  `amp_input_pair`, which lives in row 1. **A floorplan revision that
  splits `amp_input_pair` would, even if fully successful, close at most
  `D1` and `VDD` -- it cannot touch `VSS`'s hop**, which competes with
  `VOUT`'s own route for the same row-0 corridor near the floorplan's
  bottom margin. Full AC1 closure needs two independent floorplan fixes,
  not one: a row-1/row-2 corridor (the `amp_input_pair` split already
  proposed) *and* a separate row-0 corridor fix between `pnp_ctat` and
  `pnp_ptat`.

**Why no code change ships in this increment.** Splitting `amp_input_pair`
is a real floorplan/matching redesign (today it is one `diff_pair`
instance interdigitating MP1/MP2 for common-centroid matching; no
generator param exists to place it as two gapped halves, so doing this
means either a new upstream generator capability or two separate
`diff_pair` instances placed by hand -- the latter changes the device's own
matching topology, `matching-plan.md` Section 1's "dominant mismatch
contributor" device, and is not a change to make inside a search-and-
report increment). Combined with the row-0 finding above (the split alone
would not even complete AC1), attempting it as this increment's own scope
would not fit the same bounded, single-lever pattern every prior increment
here has followed. Recorded as ruled-in-scope-but-not-attempted for
whoever picks it up next, with the two-separate-corridors framing above so
it is scoped correctly from the start.

### 7e. Seventh increment: the channel-search-window lever, run to completion -- not a monotonic win, ruled out

Section 7d's same-day follow-up pass named one still-untried, apparently
"safe" lever and could not verify it: widening `CHANNEL_NEAR_TRACKS` (8->16)
and `CHANNEL_DOGLEG_TRACKS` (5->9) in `gen_bandgap_routed.py`'s
`_channel_paths` -- the per-*hop* path-search candidate window, distinct
from the whole-cell net-order/repair search Section 7d's other experiment
widened. That pass reasoned the change was "monotonic (a strict superset of
the current candidate paths, so it can only match or improve on the current
result, never regress it)" for a single hop in isolation, made the edit,
started a flow run, and reverted unverified when the run did not finish
within that session.

This increment made the identical edit and ran `run-bandgap-routed-flow.sh`
to completion (`20260804-100209-f3b4908`, 24m19s wall time, DRC clean,
`device_counts`/`pin_count` unchanged) to get a real answer. **The
single-hop monotonicity reasoning does not extend to the whole-cell
result**, and the run demonstrates why: widening the window changes which
paths are *available* to the per-net candidate search, which changes which
whole-cell net order wins `gen_bandgap_routed.py`'s own order-search scoring
(the same order/repair search Section 7c's repair pass and Section 7d's
other experiment operate over) -- so a wider per-hop window can free one hop
by routing an *earlier* net differently, at the cost of consuming the
corridor a *later* net's now-unrouted hop needed. That is exactly what
happened:

| net | baseline (`496ab43`) | this experiment (`f3b4908` + window widened) |
| --- | --- | --- |
| `VDD` | NO (blocked by `GDRV`/`TAIL`) | **yes** -- now fully drawn |
| `TAIL` | yes (fully drawn) | **NO** -- blocked by `VOUT` |
| `D1` | NO (blocked by `D2`) | NO (blocked by `D2`, unchanged) |
| `VSS` | NO (blocked by `VOUT`) | NO (blocked by `VOUT`, unchanged) |

`VDD` gained; `TAIL` -- previously one of the 9 fully-drawn nets -- lost.
Schematic inter-block coverage stayed at **9/12** (membership shifted, count
did not), `mismatch_count` moved **106 -> 105** (one fewer mismatch, not a
material change against the causes catalogued in the routed record's "LVS
mismatch analysis"), and runtime nearly doubled (24m19s vs. the ~13 min
baseline). `VSS`'s hop is unaffected either way, consistent with Section
7d's finding that it is a row-0 corridor problem unrelated to this window.

**Ruled out, and reverted (not shipped)**: a wider per-hop candidate window
is not a lever for AC1 closure on this floorplan -- it is a lateral trade
between hops chosen by the whole-cell order search, not a net gain, and it
costs real runtime. This closes out the last lever named in the issue
thread as "genuinely untested"; the remaining candidate is unchanged from
Section 7d: a floorplan revision splitting `amp_input_pair` (for `D1`/`VDD`)
plus a separate row-0 corridor fix between `pnp_ctat` and `pnp_ptat` (for
`VSS`) -- both real floorplan/matching redesigns, not parameter tuning, and
still not attempted.

### 7f. Eighth increment: widening row 0's own block margin, run to completion -- `VSS`'s blocker unchanged, `GDRV` regresses, ruled out

Sections 7d/7e narrowed the remaining candidate for `VSS`'s hop
(`pnp_ctat:VSS trunk` -> `pnp_ptat:VSS trunk`) to "a separate row-0 corridor
fix between `pnp_ctat` and `pnp_ptat`" but flagged that an actual
`amp_input_pair` split is a real matching-topology redesign, out of scope
for a single bounded increment. This increment looked for a smaller,
row-0-only lever short of that redesign: `place_blocks()`'s
`BLOCK_MARGIN_UM` (the horizontal clearance between blocks placed
side-by-side in the same row) is a single global constant, applied to every
row's gaps identically. Row 0 (`pnp_ctat`/`res_r2`/`res_trim`/`res_r1`/
`pnp_ptat`, 5 blocks, 4 gaps) is not the floorplan's widest row -- row 1
(driven by `amp_input_pair`) is, at 308.2 um vs. row 0's 299.28 um measured
from the `20260804-065252-496ab43` record's `compose.inner.json` -- so
widening only row 0's own gaps looked like a plausible, bounded, mostly-free
lever: up to ~9 um of it costs nothing (row 0 is re-centered under row 1's
already-wider span), and the < 0.05 mm^2 area budget (Section 6) had ~9.8%
headroom (45,508 / 50,000 um^2 used) for the rest.

**What was tried.** Added a `ROW_BLOCK_MARGIN_OVERRIDE_UM = {0: 24.0}` table
to `gen_bandgap_routed.py` (row 0's margin 16 -> 24 um, i.e. +8 um per gap x
4 gaps = +32 um of row-0 width), consulted by `place_blocks()` in place of
the flat `BLOCK_MARGIN_UM` on a per-row basis -- every other row's geometry
is untouched. Chosen conservatively so the resulting composed bbox
(estimated ~48.7k um^2 from the width delta) stayed under the 50,000 um^2
budget with margin to spare, confirmed by the actual run below.

**The run completed** (record `20260804-104732-fc95614`, ~16 min wall
time -- inside the flow's normal ~13-16 min range, not the prior session's
unexplained hang). DRC stayed clean, `device_counts`/`pin_count` unchanged,
composed bbox grew **45,508 -> 48,708 um^2** (still under the 50,000 budget,
but consuming nearly all the remaining headroom for a change that, per the
comparison below, bought nothing).

| net | baseline (`496ab43`) | this experiment (row 0 margin 16->24) |
| --- | --- | --- |
| `VDD` | partial (blocked at `amp_input_pair`) | partial (blocked at `amp_input_pair`, unchanged) |
| `D1` | partial (blocked at `amp_nmirr`) | partial (blocked at `amp_nmirr`, unchanged) |
| `VSS` | partial (blocked at `pnp_ctat`) | partial (blocked at `pnp_ctat`, unchanged) |
| `GDRV` | **drawn** | **partial** -- newly blocked at `core_mirror` |

**`VSS`'s own blocker did not move at all** -- the coverage table's "not
drawn" column names the identical block (`pnp_ctat`) before and after, so
the extra row-0 corridor this change added was not the resource the router
was short of for that hop; whatever `VSS`'s actual path needs, more
horizontal gap between row 0's blocks is not it. `D1` and `VDD` were
similarly untouched (both still blocked at the same block as baseline).
Worse, `GDRV` -- fully drawn at baseline -- regressed to partial: the
whole-cell net-order search picked a different winning order once row 0's
blocks sat further apart, and that reshuffle cost `GDRV`'s route through
`core_mirror` even though nothing about `GDRV`'s own hop touches row 0.
Schematic inter-block coverage moved **9/12 -> 8/12** (a net regression, not
a lateral trade this time) and `mismatch_count` moved **106 -> 107** (one
worse). This is the same failure mode Section 7e already demonstrated for
the per-hop channel window -- widening a router resource anywhere on this
floorplan reshuffles the whole-cell order search's winner, and a hop
untouched by the widened resource can still lose from the reshuffle -- now
confirmed for a floorplan-geometry lever too, not just a search-parameter
one.

**Ruled out, and reverted (not shipped)**: widening row 0's own
`BLOCK_MARGIN_UM` is not a lever for `VSS` (or `D1`/`VDD`) -- it left the
actual blocking contention untouched while regressing a previously-drawn
net and consuming most of the remaining area-budget headroom for zero
gain. `ROW_BLOCK_MARGIN_OVERRIDE_UM` and the `place_blocks()` per-row
lookup it drove were reverted after this measurement, not shipped; the new
report directory this run produced was not committed either, per this
issue's established convention for a tried-and-ruled-out lever (Sections
7d/7e). This closes out "wider gap, same floorplan" as a category of
lever for `VSS`'s hop specifically (distinct from the whole-row-1-blocking
`amp_input_pair` split candidate, which this increment does not bear on
either way): the remaining candidates for AC1 closure are unchanged from
Section 7d/7e -- a floorplan revision splitting `amp_input_pair` (for
`D1`/`VDD`) and a `pnp_ctat`/`res_r2`/`pnp_ptat` **re-placement** (not
just re-spacing) for `VSS` -- both real floorplan/matching redesigns, still
not attempted.

### 7g. Ninth increment: `blocked_by` names one veto of many -- a per-hop blocker tally, and what it says about the three hops left after #78

Every increment from 7c on characterized each still-unrouted hop by *one*
net: the `blocked_by` value the hop's own record carries. That value comes
from `_LAST_BLOCKER` (`gen_bandgap_routed.py`), which is only ever the
*last* candidate path `_connect()` happened to try before giving up -- an
artifact of search order, not necessarily the net actually holding the
corridor. This increment tested that framing directly and found it
incomplete, then used the corrected picture to ask what is really left.

**The set of failing hops changed under this increment's feet, and the
analysis is against the new one.** An earlier draft of this section
analysed `D1`, `VDD` x2 and `VSS`. PR #78 (`bulk_terminal()` offering all
three ring taps) landed while that draft was open and moved the failure:
`VDD` now routes end to end, `GDRV` takes the corridor `VDD` used to leave
free, and `mismatch_count` is 92 rather than 106. Everything below is
measured against the post-#78 floorplan -- record
`20260804-113412-4fb2a3a`, this increment's own full flow run, whose
`device_counts`/`pin_count`/`mismatch_count=92`/`violation_count=0` are
identical to the `20260804-105025-25d02e6` baseline on `main`. The three
hops in play are now **`D1`, `VSS`, `GDRV`**, one hop each.

**The tally is now part of the flow's own record, not a one-off
diagnostic.** `_connect()`'s per-candidate blocker tracking (previously
`_LAST_BLOCKER`, overwritten on every rejection) is joined by
`_BLOCKER_COUNTS`, a per-call tally reset at the start of every `_connect()`
invocation and surfaced on a failed hop as `blocked_by_counts`
(`bus-summary.json`'s `_inter_block` entries, and so every future record)
alongside the existing `blocked_by`. `blocked_by` is unchanged, for
backward compatibility with the repair pass's own targeting and any
existing reader; `blocked_by_counts` is strictly additive. Unit-covered in
`layout/tests/test_routed_flow_gates.py` (`TestConnectRouter`'s two
blocker-tally tests, `TestDrawChainBlockedByCounts`). The table below is
read straight out of that record -- no standalone harness required to
reproduce it:

| hop | recorded `blocked_by` | distinct vetoing nets | rejected candidates (attempts / distinct geometries) | breakdown |
| --- | --- | --- | --- | --- |
| `D1` (`amp_nmirr:D1:far0` -> `amp_input_pair:D1:far1`) | `D2` | 8 | 5262 / 4780 | `D2` 3091, `GDRV` 806, `TAIL` 732, `VA` 256, `VB` 238, `D1` 82, `PN` 55, `VSS` 2 |
| `VSS` (`pnp_ptat:VSS trunk` -> `pnp_ctat:VSS trunk`) | `VOUT` | 20 | 5230 / 4748 | `VOUT` 2546, `VA` 1445, `VSS` 407, `VBQ` 271, `TAIL` 101, `VB` 91, `D2` 33, plus **13** distinct `res_r2` intra-block bus segments totalling 336 |
| `GDRV` (`core_mirror:GDRV:far1` -> `amp_pmirr:GDRV:far0`) | `TAIL` | 3 | 5636 / 5154 | `VDD` 2851, `TAIL` 2778, `GDRV` 7 |

Two things fall out of the table immediately. `VSS`'s recorded blocker
(`VOUT`) accounts for under half its rejections, with `VA` nearly as large
and `res_r2`'s own intra-block series-chain bus (the 108-unit ladder folded
into 9 rows, Section 4a) a real contributor -- row 0's internal wiring is
part of that deadlock, which no prior increment's per-net framing
surfaced. `GDRV`'s recorded blocker (`TAIL`) is likewise not its largest;
`VDD` is, and `GDRV` is contested by only **three** nets, the narrowest
congestion of the three hops.

**These are exhaustive counts, not samples.** A hop that fails has had
*every* candidate `_connect()` can generate rejected, and each rejection
tallies exactly one net, so the tally's sum is the size of the search:
5230, 5262 and 5636 candidate attempts respectively for the three hops
above (4748 / 4780 / 5154 distinct geometries -- the detour ladder re-offers
the two plain elbows at each of its 241 offsets, which the attempt count
includes and the geometry count does not). That is every elbow, every
floorplan-channel crossing, and every Z-detour/four-segment escape across
the full +/-48 um `DETOUR_OFFSETS_UM` range, for that hop's endpoints.
Summed over each net's whole per-net search (`_route_one_net` enumerates
`CANDIDATE_ASSIGNMENTS` pad assignments x `_chain_orders` visit orders,
each re-running `_connect` on every hop), the three nets between them burn
**66,478 / 57,937 / 39,452** rejected candidate paths for `VSS` / `D1` /
`GDRV`. "The router's search just needs to be smarter" is not a live
hypothesis for any of them.

**Which blockers are actually rippable?** A pure-Python replay harness
(reads a record's per-block `*.gen.json`, rebuilds the intra-block busses
and re-runs `route_inter_block_nets` on the recorded winning order -- no
`klt` calls, ~70 s per configuration instead of a ~15 min flow run)
reproduces the record's routing exactly, then re-runs it with one net's
*inter-block* wiring removed from the order entirely. Removing a net this
way does not remove its intra-block metal: `_draw_intra_block_busses` draws
every MOS group's combs and every array's trunks before the inter-block
router starts, and those carry net names too. That distinction is what the
test measures:

| removed net | effect on the hop that named it |
| --- | --- |
| `VA` | **`VSS`'s hop routes completely** -- all five terminals joined, zero conflicts |
| `VOUT` | **`VSS`'s hop routes completely** as well |
| `VDD` | `GDRV` still fails; `VDD` still vetoes 819 candidates (down from 2851) purely from intra-block comb metal, and `TAIL` grows to 4045 |
| `TAIL` | `GDRV` still fails, with a **byte-identical** blocker tally (`VDD` 2851, `TAIL` 2778, `GDRV` 7) -- not one of `TAIL`'s 2778 vetoes came from its inter-block route |
| `D2` | `D1` still fails, and gets *worse* (two failing hops instead of one); `D2` still vetoes 2854 of its original 3091 from intra-block metal |

So the three hops are not the same kind of failure, and the old
one-blocker-per-hop framing hid that:

- **`VSS` is genuine inter-block corridor contention.** Two different nets'
  drawn routes each independently hold it, and removing *either* frees it.
- **`GDRV` and `D1` are not.** The metal in their way is overwhelmingly
  intra-block comb/trunk geometry that exists before the inter-block router
  runs at all -- so no net order, no rip-up target, and no repair budget can
  move it. `GDRV`'s corridor is bounded by `core_mirror`'s and
  `amp_pmirr`'s own `VDD`/`TAIL` combs; `D1`'s by `amp_nmirr`'s and
  `amp_input_pair`'s own `D2` combs.

That also explains a result Section 7c's repair pass has been producing
ever since: this record's repair pass ran, found all three named blockers
*eligible* (each is drawn earlier in the winning order than the net it
blocks -- `VOUT` at 4 vs `VSS` at 9, `TAIL` at 10 vs `GDRV` at 11, `D2` at
0 vs `D1` at 12), tried them, and produced a result identical to the
forward pass (`_route_order_attempts`' last entry: `repair_pass: true`,
`kept: false`). For `GDRV`/`D1` no rerouting of the named net could have
helped -- the blocking metal is not the part the repair pass can move. For
`VSS` the target selection was right and the *alternate solutions* were the
limit: `_route_one_net`'s `skip_first` search never reaches a `VOUT`
routing that vacates the corridor, even though deleting `VOUT` outright
does. Widening the repair pass's targeting to the full `blocked_by_counts`
list (so it could also reach `VA`) was considered and is **not** shipped:
for two of the three hops it targets metal the pass cannot move by
construction, and for the third the constraint is the alternate-solution
search, not the target -- it would cost runtime for no reachable gain,
which is the same test Sections 7e/7f applied to their own levers.

**What this narrows for the next increment.** The remaining candidate is
still the floorplan revision Section 7d named, but the reason is now
sharper and the two halves are genuinely different problems:

- `D1` and `GDRV` need **block-internal** relief -- either splitting
  `amp_input_pair` (Section 7d) or otherwise re-planning `amp_nmirr`'s,
  `amp_pmirr`'s and `core_mirror`'s comb escapes so their own `D2`/`VDD`/
  `TAIL` fingers do not wall off the one corridor between them. Nothing in
  the inter-block router reaches this.
- `VSS` needs **corridor** relief in row 0 -- and specifically enough of it
  to clear `VOUT` *and* `VA` *and* `res_r2`'s own bus, since removing any
  single one of the first two is sufficient in isolation but the floorplan
  has to accommodate all of them at once. Section 7f already ruled out
  simply widening row 0's block margin as a way to get it.

Neither is a router parameter, and this increment ships no routing change:
only the `blocked_by_counts` diagnostic, so the next increment can read
this breakdown out of any record instead of re-deriving it.

### 7h. Tenth increment: PR #78 changed the unrouted set from `D1`/`VDD`/`VSS` to `D1`/`GDRV`/`VSS` -- re-ran the search-depth lever against the new set, still not a lever

PR #78 (merged after Section 7f) fixed `VDD`'s two blocked hops by offering
every PMOS guard-ring tap (`TAP_N`/`TAP_S`/`TAP_E`) as a routing candidate
instead of pinning `bulk_terminal()` to `TAP_S` -- `core_mirror` and
`amp_input_pair` now route their n-well taps through `TAP_N`, and `VDD` is
fully drawn (`klt lvs` correspondence went from `0`/`0` to `3`/`1` as a
result, since every reference PMOS bulk is on `VDD`). The fix's own record
disclosed a cost rather than burying it: the corridor `VDD` now uses through
`core_mirror` is one `GDRV` previously had, so **`GDRV`'s hop from
`core_mirror` to `amp_pmirr`/`amp_nmirr` is now blocked** (`blocked_by:
TAIL`) where it was fully drawn before. Schematic inter-block coverage is
unchanged at 9/12 -- a different net in the short column, not a net gain --
so this section's job is to re-run the checks Sections 7d-7f already
performed against the *new* unrouted set (`D1`, `GDRV`, `VSS`) rather than
assume a finding measured against the old set (`D1`, `VDD`, `VSS`) still
holds for a floorplan whose winning route order has changed.

**What was tried.** Section 7d's router-search-depth widening
(`CANDIDATE_ASSIGNMENTS` 3->6, `CANDIDATES_PER_TERMINAL` 3->5,
`REPAIR_MAX_SKIPS_PER_NET` 3->8, `REPAIR_MAX_ATTEMPTS` 8->24) was re-applied,
unmodified, against current `main` (`75db569`, i.e. post-PR-#78) and run to
completion.

**The result: byte-identical to the post-#78 baseline in every gated
field.** `mismatch_count=92` (unchanged from the `20260804-105025-25d02e6`
baseline), `devices.matched=3`/`nets.matched=1` (unchanged), `device_counts`/
`pin_count` unchanged, met1 routing `nets=13, unrouted=3` with the identical
three nets (`D1`, `GDRV`, `VSS`) blocked at the identical points
(`GDRV`'s hop still reports `blocked_by=TAIL`). DRC stayed clean. This
matches Section 7d's original finding for the pre-#78 net set exactly:
widening this repo's own router's search budget 2x is not a lever, whether
the specific net it fails to free is `VDD` (pre-#78) or `GDRV` (post-#78) --
the mechanism ruled out in Section 7d is the *search*, not any one net's
path, so re-verifying against the changed net set was expected to (and did)
reproduce the same negative result, not superseded by it.

**Also checked, by inspection rather than a further flow run**: `_connect`'s
existing per-hop search (two direct elbows, `free_channels()`'s block-edge
channel tracks restricted to `CHANNEL_NEAR_TRACKS`/`CHANNEL_DOGLEG_TRACKS`
nearest options, then `DETOUR_OFFSETS_UM`'s 0.4 um-pitch Z-detour sweep out
to +-48.4 um from each endpoint) is already a near-continuous search of the
plane around both of a hop's endpoints, bounded only by already-drawn met1 --
`free_channels()`'s own docstring states a block's bbox is not an obstacle to
this router, only another node's drawn metal is. **Section 7g -- a
concurrently developed increment that merged while this one was in review --
has since measured exactly that, and independently confirms this section's
result at the mechanism level.** Its per-`_connect()`-call blocker tally
(now carried in every record as `blocked_by_counts`) shows `GDRV`'s hop
rejecting **all 5636** candidate paths `_connect()` can generate -- every
elbow, every floorplan-channel crossing, and the full +/-48 um detour sweep
-- against just three vetoing nets (`VDD` 2851, `TAIL` 2778, `GDRV` 7); and
its replay harness shows that deleting `TAIL`'s *inter-block* route leaves
that tally byte-identical, i.e. the metal walling off the corridor is
`core_mirror`'s and `amp_pmirr`'s own intra-block comb geometry, drawn
before the inter-block router runs at all. A search that already exhausts
its candidate space against obstacles no net order can move cannot be
improved by giving it a larger budget -- which is precisely the negative
result this section measured end to end, arrived at from the opposite
direction. This section therefore does not re-derive that tally or re-run
that harness; see Section 7g for the per-hop breakdown.

**Ruled out, and reverted (not shipped)**: router search-depth widening is
not a lever for the current (`D1`, `GDRV`, `VSS`) unrouted set, exactly as
Section 7d found for the prior (`D1`, `VDD`, `VSS`) set. No code change
ships from this increment; the report directory this run produced was not
committed, per this issue's established convention (Sections 7d-7f). The
remaining candidates for AC1 closure are unchanged in kind from Section
7d-7f, updated only in which net stands in for the row-1/row-2 corridor
problem: a floorplan revision splitting `amp_input_pair` (now for `D1`/
`GDRV` -- `GDRV`'s blocked hop, like `VDD`'s before it, touches
`core_mirror`'s row-1/row-2 crossing, the same region a split would open)
and a separate `pnp_ctat`/`res_r2`/`pnp_ptat` re-placement for `VSS` -- both
real floorplan/matching redesigns, still not attempted. Section 7g sharpens
that same pair by naming what kind of relief each half needs: `D1` and
`GDRV` need **block-internal** relief (their blockers are comb geometry the
inter-block router never reorders), while `VSS` needs **corridor** relief in
row 0 wide enough for `VOUT`, `VA` and `res_r2`'s own bus at once.

### 7i. Eleventh increment: `VSS`'s row-0 re-placement attempted directly -- fixes `VSS`, at the cost of a different row-0 net each time, no net win, not shipped

Every prior increment on `VSS`'s hop (7d/7f/7g) narrowed the candidate to "a
`pnp_ctat`/`res_r2`/`pnp_ptat` **re-placement**, not just re-spacing" without
attempting one, on the grounds that a real floorplan/matching redesign does
not fit the bounded, single-lever pattern the other levers here were tested
under. This increment attempted the cheapest possible re-placement move --
reordering row 0's five `BLOCKS` entries left-to-right, which changes no
device's own topology or generator params and costs zero area (row 0's width
is a sum of the same five block widths plus `BLOCK_MARGIN_UM` regardless of
order, and row 0 has never been the floorplan's widest row -- row 1,
driven by `amp_input_pair`, is, per Section 7f) -- to test the theory
directly with two concrete orderings, each run to completion.

**Why this is a real placement change, not a parameter sweep.** Baseline row
0 order is `pnp_ctat, res_r2, res_trim, res_r1, pnp_ptat` -- `VSS`'s two
trunks (`pnp_ctat`/`pnp_ptat`) sit at opposite ends of the row, so its hop
must cross all three resistor blocks, competing for the same corridor
`VA`'s and `VOUT`'s own routes already use (Section 7g's replay-harness
finding). Moving the PNP blocks adjacent to each other removes that
crossing entirely for `VSS` -- which is exactly what both experiments below
confirm happens -- but the resistor blocks' own inter-block partners
(`VA`/`VB`/`VBQ`, each anchored on `res_trim`/`res_r1`) do not go away, so
the question was always whether *something* has to give, not whether `VSS`
itself can be fixed.

**Experiment 1: `res_r2, res_trim, res_r1, pnp_ctat, pnp_ptat`** (both PNP
blocks moved to the row's right end, resistor blocks keep their existing
relative order). Full flow run to completion, DRC clean,
`device_counts`/`pin_count` unchanged, composed bbox unchanged (row 1 is
still the width-driving row, confirmed with `place_blocks()` called
directly against the recorded `*.gen.json` bboxes before spending a flow
run on it). Result:

| net | baseline (`496ab43`/`4fb2a3a`) | experiment 1 |
| --- | --- | --- |
| `VSS` | partial (blocked at `pnp_ctat`) | **drawn** -- all 5 hops routed, 0 conflicts |
| `VB` | drawn | **partial** -- blocked at `amp_input_pair`, vetoed 4764/5636 times by `VA` alone |
| `D1`, `GDRV` | partial (unchanged) | partial (unchanged) -- confirms Section 7g's finding that these two are untouched by row 0, since neither block moved |

`VSS` routes cleanly for the first time in this issue's history: every hop
of its 5-terminal chain succeeds with zero rejected candidates worth
naming. But `VB`'s hop into `amp_input_pair` -- previously fully drawn --
now fails, vetoed overwhelmingly by `VA`'s own route (which, with
`pnp_ctat` now two blocks further from `res_trim` than at baseline, has to
cross more of row 0's own width to reach it, and claims the same ascent
corridor into `amp_input_pair` that `VB` needs). Schematic coverage stays
at **9/12** (a lateral trade, not a gain), `mismatch_count` stays at **92**
-- byte-identical to baseline in the one metric AC4 actually gates on.

**Experiment 2: `res_r2, res_trim, pnp_ctat, pnp_ptat, res_r1`** (PNP blocks
moved between `res_trim` and `res_r1` instead, preserving `res_trim`-`pnp_ctat`
adjacency for `VA` and `pnp_ptat`-`res_r1` adjacency for `VBQ`, hypothesising
that keeping *two* of the three resistor-to-PNP relationships short would
cost less than experiment 1's one-sided move). Full flow run to completion,
DRC clean, same device/pin counts. Result: **worse, not better**.

| net | baseline | experiment 2 |
| --- | --- | --- |
| `VA` | drawn | drawn (unchanged -- the adjacency this ordering targeted held) |
| `VB` | drawn | **drawn** (fixed -- routes via a different chain now that `res_trim`/`res_r1` are not forced adjacent) |
| `VBQ` | drawn | drawn (unchanged -- the other adjacency this ordering targeted held) |
| `TRIM` | drawn | **labelled only** -- new casualty, `res_r2`-`res_trim` no longer joins |
| `VSS` | partial | **partial** (still not fixed -- `amp_nload`/`pnp_ctat`/`pnp_ptat` join but `amp_nmirr` does not, a different missing leg than baseline's) |

Schematic coverage drops to **8/12** (down from 9/12) and `mismatch_count`
rises to **94** (up from 92, `nets.layout` also grew 191 -> 193) -- a net
regression on both of AC1's and AC4's own gated numbers. Putting the two PNP
blocks *between* the three resistor blocks fixes `VB` (this ordering's own
target) but breaks `TRIM` (`res_r2`-`res_trim`, previously trivial since
they were adjacent at baseline) and only partially helps `VSS` (three of its
four legs join, not all).

**Neither experiment ships.** Per this issue's established convention for a
tried-and-not-net-positive lever (Sections 7d-7h), `BLOCKS`'s row 0 order is
reverted to baseline and neither experiment's report directory is committed.
Experiment 1 is the closer of the two -- proof that `VSS` itself is fixable
by placement alone, with a measured, named cost (`VB`) rather than a vague
one -- but "byte-identical `mismatch_count`, one schematic net traded for
another" is not a criterion-1 or criterion-4 improvement, and shipping it
would just swap which section of this document explains the remaining 3/12
gap without changing its size.

**What this closes off, and what it leaves open.** A single 1D reordering of
row 0's five blocks cannot satisfy all four of the row's own adjacency
wants at once: `VA` (`res_trim`-`pnp_ctat`), `VB` (`res_trim`-`res_r1`,
mediated through `amp_input_pair`), `VBQ` (`res_r1`-`pnp_ptat`), and `VSS`
(`pnp_ctat`-`pnp_ptat`) form a 4-edge cycle over the row's own two PNP
blocks and two of its three resistor blocks (`res_r2` is not part of the
cycle and never moved in either experiment). Five slots in a line supply at
most four adjacent pairs, and the cycle needs all four simultaneously to
avoid trading one for another -- confirmed twice now, in both directions
this increment tried. This rules out "row 0, reordered" as a category, on
top of Section 7f's already-ruled-out "row 0, respaced" -- consistent with
Section 7d/7g's original framing that `VSS` needs **corridor** relief (more
physical room for `VOUT`/`VA`/`res_r2`'s bus to coexist with `VSS`'s own
hop), not just a different arrangement of the same room. The remaining
candidate is unchanged in kind: a genuine 2D floorplan revision (e.g. a
second row for the resistor group, freeing row 0 for the two PNP blocks
alone -- not attempted here because it adds a full `ROW_MARGIN_UM` and a new
row height to the height budget; a back-of-envelope check against this
increment's own `place_blocks()` figures -- new row 0 (PNPs only) 58.2 x
9.14 um, new row 1 (resistors) 225.08 x 12.2 um, rows 2/3 (the former
row 1/row 2, unchanged) 308.2 x 43.38 um and 274.06 x 19.08 um, stacked with
the existing 22 um `ROW_MARGIN_UM` between each -- puts the resulting
composed bbox (guard ring included, `+20` um each dimension per Section 6's
own convention) at `(308.2+20) x (149.8+20) = 55,728` um^2 against the
50,000 um^2 budget, over by about 11%, so that specific shape of fix would
need to shrink the budget's consumption elsewhere first, not just add a row)
or a corridor carved out of the existing row 0/row 1 margin specifically for
`VSS`'s trunk-to-trunk hop. Both remain real redesigns, not attempted in
this pass.

### 7j. Twelfth increment: the genuine 2D revision attempted directly -- fixes `VSS`'s named hop, costs two other nets, net regression, not shipped

Section 7i's own back-of-envelope named the only two candidates left after
ruling out 1D row-0 reordering as a category: a second resistor row (freeing
row 0 for the two PNP blocks alone), measured 11% over the 50,000 um^2
budget at this floorplan's sizing, or a dedicated row 0/row 1 corridor. This
increment attempted the first candidate directly, with the budget overrun
closed by tightening `ROW_MARGIN_UM` (the between-*row* channel, never
touched by any prior increment -- Sections 7f/7h/7i all tightened or widened
`BLOCK_MARGIN_UM`, the between-*block*-in-a-row channel, a different axis).

**What was tried.** `BLOCKS`' row 0 (`pnp_ctat`, `res_r2`, `res_trim`,
`res_r1`, `pnp_ptat`) was split into two physical rows, keeping each
sub-group's existing left-to-right order (a minimal-diff split, not a new
reordering): row 0 now holds only `pnp_ctat`/`pnp_ptat` -- adjacent, which
is exactly Section 7i's experiment 1 arrangement, the one already shown to
fully route `VSS`'s own trunk-to-trunk hop in isolation -- and a new row 1
holds `res_r2`/`res_trim`/`res_r1`. The former row 1 (amp band) and row 2
(mirror band) shift to row 2/row 3 unchanged in content. This adds a third
`ROW_MARGIN_UM` channel to the height budget (PNP row to resistor row,
alongside the pre-existing resistor-to-amp and amp-to-mirror channels), which
at the un-widened 22 um value reproduces Section 7i's own estimate almost
exactly (measured this increment: composed bbox would be 328.2 x 169.8 =
**55,728** um^2 by direct `place_blocks()` computation against the current
recorded block bboxes -- 11.5% over budget, confirming the back-of-envelope
was accurate). `ROW_MARGIN_UM` was lowered 22 -> 15 um, uniformly across
**every** row boundary (not a per-boundary override) -- 1 um under
`BLOCK_MARGIN_UM`'s own already-proven-workable 16 um same-row clearance, so
not an untested minimum, just the existing block-to-block value applied on
the row axis. Recomputed against the same block bboxes before spending a
flow run on it: composed bbox 328.2 x 148.8 = 48,836.16 um^2, 2.3% under
budget.

**The run completed** (record `20260804-150853-a074ca5`, not committed --
see below -- DRC clean, `device_counts`/`pin_count` unchanged, composed bbox
**48,836 um^2**, matching the hand computation to the um^2, confirming
`place_blocks()`'s bbox-derived math is exactly what the flow draws).

| net | baseline (`4fb2a3a`) | this experiment (row split + `ROW_MARGIN_UM` 22->15) |
| --- | --- | --- |
| `VSS` | partial (`pnp_ctat` hop fails) | **partial, but a different hop**: `pnp_ctat`<->`pnp_ptat` now routes end to end (confirmed in `bus-summary.json`'s per-hop trace -- `routed: true`), but `amp_nload:VSS:far0` -> `amp_nmirr.TAP_S` now fails, blocked by `D1` |
| `TRIM` | drawn (`res_r2`-`res_trim`, both legs) | **partial** -- both `TRIM_A` and `TRIM_B` now fail, overwhelmingly vetoed by `VA` (3278/5268 and 1952/5282 rejections respectively) and, for `TRIM_B`, by `TRIM_A`'s own now-longer route (1484) |
| `GDRV` | partial (blocked at `core_mirror`) | partial (blocked at `core_mirror`, unchanged) -- `blocked_by_counts` (`TAIL` 2705, `VDD` 2293, `VOUT` 630) is the same magnitude as the pre-split baseline's tally (Section 7g: `TAIL` 2778, `VDD` 2851), confirming yet again this hop's blocker is `core_mirror`/`amp_pmirr`'s own intra-block comb geometry, untouched by any floorplan change on either side of the row-0/row-1 boundary |
| `D1` | partial (blocked at `amp_nmirr`) | partial (blocked at `amp_nmirr`, unchanged) -- same mechanism as `GDRV` above |

Schematic inter-block coverage moved **9/12 -> 8/12** (a regression, not a
lateral trade) and `mismatch_count` moved **92 -> 94** (two worse). `VSS`'s
own named hop (`pnp_ctat`<->`pnp_ptat`) is genuinely fixed -- direct,
per-hop evidence, not a coverage-table inference -- which is real
confirmation that Section 7i's finding generalizes from a 1D reorder to an
actual 2D floorplan split: PNP adjacency removes that specific corridor
contention regardless of which axis freed the room. But the same session
that fixes it introduces **two** new casualties (`TRIM_A`, `TRIM_B`) and
shifts `VSS`'s own remaining congestion onto a different hop
(`amp_nload`-`amp_nmirr`) rather than clearing it -- a worse trade than any
prior increment's, including Section 7i's own experiments (which cost at
most one net for one net).

**Why this happened, read from the tally.** `TRIM_A`'s dominant blocker is
`VA` (3278 of 5268 rejections) -- the net that already had to cross from
`pnp_ctat` (now in its own row) up through the resistor row to reach
`amp_input_pair` two rows further up. Moving `pnp_ctat` off the resistor
row's own band and compressing every row-to-row channel to fit the budget
both worked against `TRIM_A`/`TRIM_B` at once: `VA`'s path is now longer
(crosses one more row boundary than at baseline) and every channel it
crosses is narrower (15 um vs. 22 um) than before. The uniform
`ROW_MARGIN_UM` cut is not neutral background -- it is exactly the axis
`VA`'s new, longer path depends on, so shrinking it to fit the split's own
height cost took room away from the net most exposed by the split itself.

**Ruled out, and reverted (not shipped)**: a genuine 2D floorplan revision
-- not a parameter tweak, not a 1D reorder -- was run to completion on this
issue for the first time this increment, and it is *worse* than doing
nothing, not merely a lateral trade. `BLOCKS`' row assignments and
`ROW_MARGIN_UM` are both reverted to baseline (`22.0`, uniform); the
report directory this run produced (`20260804-150853-a074ca5`) is not
committed and `reports/LATEST` still points at `4fb2a3a`, per this issue's
established convention for a tried-and-not-net-positive lever (Sections
7d-7i). This closes the "second resistor row" half of Section 7i's own
remaining-candidate pair -- it does not merely need the earlier
increment's 11% area cut, it needs that area cut to come from *somewhere
that is not `VA`'s own crossing budget*, which the uniform `ROW_MARGIN_UM`
reduction this increment tried is not. The one candidate left, genuinely
unexplored, is a **non-uniform** channel budget: keep the row 0/row 1
(PNP/resistor) and row 1/row 2 (resistor/amp) boundaries wide enough for
`VA`'s and the other resistor-row nets' existing crossings, and take the
area saving from elsewhere in the floorplan entirely (not the row-margin
axis at all) -- e.g. the amp band's or mirror band's own internal spacing,
or accepting a smaller `RING_MARGIN_UM`. That is a different, still
untried shape of the same "second row" idea, not a re-run of this one.

### 7k. Thirteenth increment: Section 7j's own "non-uniform channel budget" candidate attempted, in two shapes -- neither avoids the trade, and the mechanism turns out not to be channel width at all

Section 7j left exactly one candidate open: the same PNP-row/resistor-row
split, but with the area saving sourced from a channel `VA`'s route does
*not* cross, instead of a uniform `ROW_MARGIN_UM` cut across every boundary.
This increment attempts that candidate directly, in two independent shapes,
plus a third control run (the same split with every margin left at its
un-widened baseline value, over budget but otherwise untouched) to isolate
what the uniform cut in Section 7j was actually doing.

**Setup, common to all three runs.** `ROW_MARGIN_UM` is generalized from a
single scalar to a `ROW_MARGIN_OVERRIDES_UM` dict keyed by boundary index (the
channel between row `i` and row `i + 1`), defaulting to the unchanged `22.0`
for any boundary not named -- a backward-compatible generalization, not a
behavior change on its own by construction (an empty override dict makes
`.get(row_index, ROW_MARGIN_UM)` return the same `22.0` for every boundary
the unmodified scalar did; this permutation -- the mechanism with no split
and no override -- was not run separately as its own flow record, since the
code path is unconditionally identical to the pre-existing scalar lookup).
`BLOCKS`' row
0 is split the same way Section 7j did it: row 0 = `pnp_ctat`/`pnp_ptat`
(adjacent), new row 1 = `res_r2`/`res_trim`/`res_r1`, former row 1 (amp band)
and row 2 (mirror band) shift to row 2/row 3.

| run | change from baseline split | composed bbox | gate | coverage | `mismatch_count` |
| --- | --- | --- | --- | --- | --- |
| A (control) | row-0 split only, every margin at its original value (`ROW_MARGIN_UM=22`, `RING_MARGIN_UM=8`) | 328.2 x 169.8 = **55,728 um^2** (11.5% over) | fails `within_budget` | 8/12 | 95 |
| B | row-0 split + `RING_MARGIN_UM` 8 -> 2 (every row boundary, including both channels `VA` crosses, left at 22) | **49,896 um^2** (0.2% under) | passes | 8/12 | 95 |
| C | row-0 split + `ROW_MARGIN_OVERRIDES_UM={2: 4.0}` (only the row-2/row-3 amp-to-mirror boundary cut, the one channel none of `VA`/`VB`/`VBQ`/`TRIM` crosses; `RING_MARGIN_UM` and every other row boundary untouched) | **49,821 um^2** (0.4% under) | passes | 8/12 | 94 |

All three ran to completion with `violation_count=0` (DRC clean) and
identical `device_counts`/`pin_count` to the baseline record -- run A's sole
gate failure is `within_budget`, confirming every other gate (DRC, device
classes, pin promotion) still passed. None of the three beats the shipped
baseline's 9/12 / 92. Per-net detail:

| net | baseline (`4fb2a3a`) | A (uncut, over budget) | B (`RING_MARGIN_UM` cut) | C (row-2/3 boundary cut) |
| --- | --- | --- | --- | --- |
| `VA` | drawn | **partial** -- loses `res_trim` even though its own crossing channels are untouched | drawn | drawn |
| `VB`, `VBQ` | drawn | drawn | drawn | drawn |
| `TRIM` | drawn | drawn | **labelled only** -- `res_r2`/`res_trim` are in the *same* row in every one of these runs, no row boundary between them at all | **labelled only**, same mechanism |
| `VSS` | partial (`pnp_ctat` hop) | **drawn** -- both PNP arrays' adjacency (Section 7i/7j's own finding) fully fixes it here | partial, but a *different* hop (`amp_nmirr` now missing, not `pnp_ctat`) | partial, `amp_nmirr` missing, same as B |
| `GDRV` | partial (`core_mirror`) | partial, unchanged | **labelled only** -- worse: `amp_nmirr`/`amp_pmirr` both now missing, not just `core_mirror` | partial, unchanged (matches baseline exactly) |
| `D1` | partial (`amp_nmirr`) | **labelled only** -- worse, loses `amp_input_pair`/`amp_nload` too | partial, unchanged | partial, unchanged |
| `D2` | drawn | **labelled only** -- a regression on a previously-fully-working net, from a boundary (row 2/row 3) whose width run A does not even touch | drawn | drawn |

**The finding this run set adds, beyond Section 7j's own:** `TRIM` is a
same-row net (`res_r2` and `res_trim` are both in the new row 1 in every one
of these runs) that never crosses a row boundary at all, yet it breaks in
both B and C -- the two runs that touch *any* margin elsewhere in the
floorplan -- and survives intact in A, the one run that touches nothing. That
rules out Section 7j's own explanation (`TRIM_A`/`TRIM_B` failing because
`VA`'s crossing channel got narrower) as the general mechanism: C leaves
every channel `VA`, `VB`, `TRIM`, or `VBQ` could plausibly use at its full
22 um width, and `TRIM` still fails. Run A independently confirms the same
point from the other direction -- it changes nothing about any margin at all
(the split is the only difference from baseline) and still trades `D1`
further and breaks `D2` outright, a previously-fully-working net whose own
row-2/row-3 boundary width A does not touch either. `GDRV`/`D1`'s specific
blocker (block-internal comb geometry, Section 7g/7j) is unaffected across
all three, exactly as every prior increment found -- but which *other*,
previously-working nets get displaced changes completely between A, B, and C
despite each one touching a different (or no) parameter. The mechanism is
the whole-cell route-**order** search (`ROUTE_ORDER_PASSES`, ~14
candidate orders tried per run) re-converging on a different winning order
for *any* change to the floorplan's own geometry -- including one, like A,
that changes no channel width at all, only which rows exist -- not a specific
channel's available width. A per-boundary margin budget cannot target a
failure mode that is global to the order search, so this closes off
"non-uniform row-margin budget" as a category, the same way Section 7i closed
off 1D row-0 reordering: not because the specific values tried were wrong,
but because the axis itself (channel width, uniform or not) does not control
which order the search picks.

**Ruled out, and reverted (not shipped)**: all three runs' code (the
`ROW_MARGIN_OVERRIDES_UM` generalization, the row-0 split, and the
`RING_MARGIN_UM` change from run B) is reverted to baseline; none of the
three runs' report directories are committed and `reports/LATEST` still
points at `4fb2a3a`, per this issue's established convention. The
`ROW_MARGIN_OVERRIDES_UM` mechanism itself is a legitimate, backward-compatible
generalization by construction (see the Setup note above) -- it is not
shipped here only because nothing in this increment found a value for it
that helps; a future increment that needs a genuine per-boundary margin for
an unrelated reason does not need to re-derive it.

**What is left.** The 2D-split path (Section 7i/7j/7k) is now three-for-three
on "fixes `VSS`'s named hop but nets a regression via order-search
sensitivity," across a 1D reorder, a uniform 2D margin cut, and two
non-uniform 2D margin cuts. `GDRV`/`D1` have never moved under any floorplan
change tried across all thirteen increments -- their blocker is
block-internal comb geometry the inter-block router draws before it starts
routing between blocks at all (Section 7g), which no placement change reaches
by construction. The remaining candidates for AC1's last 3/12 gap are
qualitatively different from everything tried so far: (a) a router change
that either reorders *intra*-block bussing relative to inter-block routing,
or makes the order search itself route-order-stable under small floorplan
perturbations (so a future margin/placement change can be evaluated on its
own merit instead of via a different emergent global order every time); or
(b) accepting the corridor deadlock as a hard floorplan-generation limit of
this router and pursuing klayout-tools' own two-pin router / a genuine second
metal role instead (klayout-tools#454 is merged, but Section 7d already found
its `"metal2"` role aliases to the same met1 layer on sky130 -- a *third*
routing layer, not merely a second role name, would be the actual capability
gap to file).

### 7l. Fourteenth increment: `klt` pin bump picks up five upstream fixes; a stale `hints.same_nets` declaration turns out to be actively blocking, not neutral -- `mismatch_count` 92 -> 32

Sections 7d-7k are all router/floorplan-geometry attempts on AC1's remaining
`D1`/`GDRV`/`VSS` trio and all came up empty. This increment does not touch
routing or the floorplan at all -- it re-checks the friction-tracker
blockers named in the last several records (klayout-tools#490, #491, #492,
#504) and finds all four closed upstream since the current `klt` pin
(`8c277eb9`, set at the fifth increment) was cut, none of them picked up
yet. Bumping the pin to `147602af` (current `klayout-tools` `main`) pulls in
the fixes:

- **klayout-tools#490 -> #495**: an NMOS body / `bulk_to_substrate` resistor
  bulk / bipolar collector terminal now resolves to a real drawn `tap.drawing`
  ring outside `nwell` when one is present and contacted, instead of an
  unconditional synthesized `vsubs` global.
- **klayout-tools#491 -> #494**: sky130's curated deck now declares a
  `dummy` marker layer, and `mos_array`/`res_array`/`bjt_array` draw it over
  each array's own `dummy_cells` footprint, so `klt extract`'s existing
  dummy-suppression (since #462) finally fires on sky130.
- **klayout-tools#492 -> #497**: `mos_array`/`diff_pair` gain an opt-in
  `gate_contact` param; not adopted here (default off, byte-identical
  geometry) -- this flow already hand-draws the gate contact via
  `met1_bus.py`'s own `gate_contact` helper (MOS_GATE_NOTE), and swapping to
  the generator-side version is a separate rework, not a pin-bump side
  effect.
- **#496 -> #498**: `gen-compose`'s Manhattan backbone stub now widens to
  match a wide north/south pad (e.g. this flow's `TAP_N`/`TAP_S` taps) --
  measured to change nothing in this flow's own composed geometry (DRC
  stayed clean before and after).
- **klayout-tools#504 -> #505**: a dedicated `device.class_arity` mismatch
  category for a bulk-terminal-vs-plain resistor class pair, diagnostic
  only.

**The pin bump alone broke the flow.** `klt lvs` returned
`{"status": "error", "error": "layout net 'vsubs' not found"}` for every one
of the flow's three LVS attempts (combined-from-netlist, combined-from-GDS,
uncombined). Root cause: `gen_bandgap_routed.py`'s `run_lvs()` unconditionally
sent `hints.same_nets: [["vsubs", "VSS"]]` -- a declaration that was load-bearing
through the pin bump above, and became actively wrong the moment it landed.
This layout already draws the exact shape #495 keys off (both NMOS groups'
substrate guard-ring taps and both PNP base ties, wired to `VSS`), so once any
such tap is drawn anywhere in the design, sky130's single shared
`deck.substrate_net` global identity resolves to that real net everywhere it
is used -- confirmed by reading the extracted netlist back: every nfet's `b`
terminal and every `res_high_po`'s `w` terminal now read `VSS` directly, not
`vsubs`. There is no longer a `vsubs` net in this layout's extracted netlist
at all, so a `hints.same_nets` entry naming it is not a no-op -- it is a
request for a correspondence between a net that exists (`VSS`) and one that
does not (`vsubs`), which `klt lvs` correctly rejects as a hard error instead
of running.

**The fix: `SUBSTRATE_SAME_NETS` is now empty.** Verified by manually
constructing the same LVS request with the `hints` key removed and running it
directly against this run's own `bandgap_core_routed.gds`/`.extract.spice`:
`status: "mismatch"` (not `error`), and no mismatch entry mentions `vsubs`
anywhere -- the correspondence the flow previously had to *declare* is now
something `klt lvs` *discovers* on its own from the drawn geometry. Landed as
a code change (`SUBSTRATE_SAME_NETS: list[list[str]] = []`), not a one-off
manual patch, with the surrounding `SUBSTRATE_NET_NOTE`/`DUMMY_DEVICE_NOTE`
prose and the record generator's per-cause writeup updated to match (both
retired causes moved to a new "Retired since the last increment" record
section instead of being silently dropped).

**Measured result** (`layout/bandgap-core/reports/20260804-174203-ddf7f17/record.md`,
full flow re-run to completion after the fix, DRC clean,
`run-trivial-cell-flow.sh` re-run unmodified -- see below):

| metric | baseline (`4fb2a3a`, post-PR-#78) | this increment |
| --- | --- | --- |
| `mismatch_count` | 92 | **32** |
| `devices.matched` | 3 | **6** |
| `nets.matched` | 1 | **3** |
| `pins.matched` | 17 | 16 |
| `device_counts` | `{"nfet": 16, "pfet": 52, "pnp": 24, "res_high_po": 159}` | `{"nfet": 16, "pfet": 52, "pnp": 16, "res_high_po": 147}` (dummy suppression: `dummy_devices_dropped: 20`) |
| `pin_count` | 16 | 15 |
| AC1 schematic coverage | 9/12 | **9/12 (unchanged)** -- this increment does not touch routing |
| AC5 friction | 5 closed gaps named | **9 closed gaps named** (#490/#491/#492/#496/#504 added) |

`mismatch_count` category breakdown moved from
`{"device.body_unverified": ..., "device.unmatched": ..., "net.merged": ...,
"net.split": ...}`-shaped (dominated by the unresolvable substrate
declaration) to `{"device.unmatched": 19, "net.merged": 3, "net.split": 10}`
-- no `device.body_unverified` warnings at all now, confirming every body
terminal resolves to a real net. The remaining `device.unmatched` entries are
1 NFET + 4 PFET + 4 PNP + 10 `RES_HIGH_PO` (reference + layout sides
combined); the `RES_HIGH_PO` entries are cause 4 above (arity), not a
substrate or dummy artifact.

**Non-regression proof carried an unexpected finding of its own.**
`layout/bin/run-trivial-cell-flow.sh`'s hand-authored `reference.spice`
enumerates 8 M-cards (`klt gen mos_array`'s pinned defaults draw 4 real + 4
dummy units) -- written that way specifically because, through this pin,
sky130 could not suppress dummies at all (the fixture's own header said so).
Once #494 lands, `klt extract` correctly drops the 4 dummy units
(`dummy_devices_dropped: 4`), and the fixture's LVS-match proof regressed to
`status: "mismatch"` (`layout: 4, reference: 8` devices) -- caught by
`render-record.py`'s own verdict-flip assertion (`run-trivial-cell-flow.sh`
exited 1). Fixed by updating `reference.spice` (and both negative controls)
to 4 M-cards: a dummy unit has no schematic counterpart by construction (it
exists only for layout-matching symmetry), so 4 real devices is the
topologically correct reference now that the layout side can express the
distinction -- not a relaxation to chase a smaller number, the mirror image
of the `res_generic_po` -> `res_high_po` correction PR #71 made for the same
reason. Re-run after the fix: DRC clean, LVS match (`devices.matched: 4/4`,
`nets.matched: 13/13`), both negative controls still `mismatch` -- the
four-way verdict restored. See `layout/trivial-cell/reference.spice`'s own
header and `layout/README.md` for the full writeup.

**What this does and does not move.** AC4 (LVS-clean) is still NOT MET, but
`mismatch_count` more than halved and two of six previously-disclosed causes
are fully retired, both with a real mechanism (not a workaround): the
substrate correspondence is discovered from drawn geometry instead of
declared, and dummy devices are excluded from the comparison because the
tool can now tell them apart from real ones, not because this flow hid them.
AC1 (routing) is untouched -- `D1`/`GDRV`/`VSS` remain exactly where
Sections 7g-7k left them, and this increment does not claim otherwise. No new
friction filed: every gap this increment interacts with was already on the
tracker and is now closed, re-verified against the current pin rather than
assumed from the issue history.

## 8. Known limitations / follow-on work

- **LVS is not clean.** *(Still open; the reason has now changed four
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
  matches to `3`/`1` and `mismatch_count` from 106 to **92**. **Update,
  fourteenth increment (Section 7l)**: `mismatch_count` is now **32**,
  `devices.matched` **6**, `nets.matched` **3** -- the deck-synthesized
  substrate net and undeclarable array dummies (causes 2/3 below, through
  the prior update) are both **retired**, not just improved. Cause 1's
  unrouted trio (`D1`/`GDRV`/`VSS`) is unchanged -- this increment did not
  touch routing or the floorplan, only the `klt` pin and the LVS request.
  1. **Three schematic nodes are still not joined end to end** -- this
     flow's own router running out of corridors, *not* a tool gap, and
     confirmed by the fifth increment to survive a per-net rip-up-and-retry,
     not just a whole-cell reorder. The ninth increment (Section 7g) went
     further: the per-hop blocker tally now in every record shows each of
     the three remaining hops rejecting *every* candidate path `_connect()`
     can generate (5230-5636 per hop), against 3 to 20 distinct already-drawn
     nets -- and that for two of them (`D1`, `GDRV`) the metal in the way is
     block-internal comb geometry the inter-block router cannot reorder at
     all. A real corridor deadlock, not a single-net or search-depth problem
     a router-side change can still solve. It is the first time in this
     issue's history that the top cause is this repo's own.
  2. **MCC** is in the reference and deliberately not drawn (Section 6).
  3. **Resistor values** differ by the schematic's per-device 380 ohm head
     term, which the extractor (drawn body squares x sheet rho) does not
     model, and by the DR-002 trim taps, which the layout draws as series
     devices where the schematic carries them as a length term. Unreached in
     practice -- cause 4 stops the comparer one step earlier.
  4. **No resistor can be paired at all**: `res_high_po`'s sky130 device
     class carries a bulk terminal (`DeviceClassResistorWithBulk`, 3 nodes)
     the reference's plain `R` cards do not (`DeviceClassResistor`, 2
     nodes) -- filed as klayout-tools#504 (closed via #505, a diagnostic-only
     fix; see Section 7l).
  Rewriting the reference netlist to enumerate the layout's own shortfalls
  would make LVS compare the layout against itself and is explicitly not
  done. **Retired as of Section 7l**: the substrate correspondence no
  longer needs a `hints` declaration at all (it is real drawn connectivity
  now), and array dummies are no longer counted as devices.
- ~~**R2A/R2B ladder is at reduced scale**~~ -- **closed** by issue #62, see
  Section 4a. The ladder is drawn at its real 108-unit count.
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
- **Inter-block connectivity is now mostly drawn, but not complete** -- 9 of
  12 schematic inter-block nets are joined across every block they reach (up
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
  Section 7d -- not the same thing as a second physical layer).
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
