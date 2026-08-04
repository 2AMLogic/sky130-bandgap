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

## 8. Known limitations / follow-on work

- **LVS is not clean.** *(Still open; the reason has now changed three
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
  `mismatch_count` did not move -- see cause 1. The residual causes, in the
  order they matter (the routed record's "LVS mismatch analysis" section
  quantifies each):
  1. **Three schematic nodes are still not joined end to end** -- this
     flow's own router running out of corridors, *not* a tool gap, and
     confirmed by the fifth increment to survive a per-net rip-up-and-retry,
     not just a whole-cell reorder. It is the first time in this issue's
     history that the top cause is this repo's own.
  2. **klayout-tools#490** -- the extraction deck's synthesized substrate
     net, which no drawn shape can join. Declared to `klt lvs` through
     `hints.same_nets` rather than worked around; the layout's genuinely
     drawn `VSS` is then a second layout net the reference has no
     counterpart for.
  3. **klayout-tools#491** -- array dummies still extract as real devices.
  4. **MCC** is in the reference and deliberately not drawn (Section 6).
  5. **Resistor values** differ by the schematic's per-device 380 ohm head
     term, which the extractor (drawn body squares x sheet rho) does not
     model, and by the DR-002 trim taps, which the layout draws as series
     devices where the schematic carries them as a length term.
  Rewriting the reference netlist to enumerate the layout's own shortfalls
  would make LVS compare the layout against itself and is explicitly not
  done. The one declaration made -- the substrate correspondence in cause 2
  -- is a `hints` entry stating something true of the design, not a netlist
  edit.
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
  from 6/12, and 4/12 before that), via met1 (Section 5a). The three still
  short (`D1`, `VDD`, `VSS`) are `partial`: each is drawn between the blocks
  the router reached and stops where it did not. **The cause is no longer
  upstream.** Every one of these nodes is expressible now; what is missing
  is corridor in a floorplan whose widest block spans 180 of the cell's 300
  um and whose own comb trunks are the obstacle. Issue #62's criterion 1 is
  scored PARTIAL, not MET, on this. The fifth increment (Section 7c) tried
  the first candidate the fourth increment's own record proposed here -- a
  per-hop rip-up-and-reroute instead of the whole-cell per-order one -- and
  it did not free any of the three hops, which is real evidence the limit is
  the floorplan's free corridor, not a single net's choice of path. The two
  candidates left, in rough order of expected return: taking up
  klayout-tools#468's metal2/via1 roles so the router (not this repo) plans
  the wires; or a floorplan revision that breaks `amp_input_pair` into two
  stacked halves so something can cross the middle of the cell.
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
