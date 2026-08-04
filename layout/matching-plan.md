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

**What still isn't drawn, and why.** Every remaining gap -- the unrouted
12th net, the rest of the partial schematic nodes, and all MOS finger
bussing -- terminates on a MOS gate. Every `klt gen` MOS generator on sky130
draws gate poly with **exactly** the active region's extent (poly and diff
share both edges), so there is no poly landing area outside the channel a
contact could legally sit on. A gate cannot be connected to anything through
drawn geometry today. Filed as
[klayout-tools#461](https://github.com/2AMLogic/klayout-tools/issues/461).
This flow deliberately does not draw a contact over the channel to make a
number move -- that would be illegal geometry the curated DRC deck simply
doesn't happen to model, not real connectivity.

The routed record's "Schematic inter-block nets: drawn vs. labelled only"
table is the measured, per-net version of this. Issue #62's criterion 1 is
scored **PARTIAL** on it -- the reference netlist is *not* adjusted to
accommodate any of it (an earlier revision bridged `AOUT`/`GDRV` with a
0-ohm device -- that stays removed).

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

Status as of issue #62's routed flow, second increment (the #15 column is
kept because the skeleton's own checked-in records were produced under it):

| Matched group | Generator | DRC-clean | Extraction status at #15 | Extraction status at #62 (current) |
|---|---|---|---|---|
| PNP arrays (Q1, Q2) | `bjt_array` | yes | no -- `klt extract` on a `bjt_array` output reports `device_count: 0` | **yes, 24 `pnp` devices** (dummies included), drawn by the generator itself since upstream [klayout-tools#440](https://github.com/2AMLogic/klayout-tools/issues/440) (the first increment's local recognition overlay is retired) |
| Resistor ladders (R2A/R2B, R1, trim) | `res_array` | yes | no -- never drew the PDK's resistor-ID marker layer (2AMLogic/klayout-tools#369) | **yes, 159 `res_generic_po` devices** -- #369 merged upstream via klayout-tools#382. Only the base flavour is drawable -- [klayout-tools#463](https://github.com/2AMLogic/klayout-tools/issues/463) |
| Amp input pair, NMOS loads/mirrors, PMOS mirror, core mirror | `diff_pair` | yes | not attempted | **yes, 52 `pfet` + 16 `nfet`** -- the nfet flavour needed klayout-tools#421 (guard-ring well tie enclosing nfet devices in nwell), merged via klayout-tools#426. Gates are unconnectable regardless of flavour -- [klayout-tools#461](https://github.com/2AMLogic/klayout-tools/issues/461) |
| Overall guard ring | `guard_ring` (standalone) | yes | n/a | n/a -- composed in a **second** `gen-compose` pass, because a ring enclosing the whole floorplan reports a bbox that the router treats as an obstacle vetoing every net |
| Per-group guard rings | `add_guard_ring`/`add_collector_ring` (built into `diff_pair`/`bjt_array`) | yes | n/a | **on**, with a routing opening (klayout-tools#441) -- see Section 5a |
| Intra-block bussing (array units, ladder segments) | `met1_bus.py` (`klt draw`, this repo) | yes | n/a | **drawn on met1**, not through `gen-compose` -- see Section 5a and `MET1_BUS_NOTE` |
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

Two gaps the first increment **picked up rather than filed**, having landed
upstream in the interval: klayout-tools#415 (`res_array` row folding,
Section 4a) and klayout-tools#421 (`diff_pair`'s nfet-in-nwell
misclassification). Both are covered by `layout/requirements.txt`'s pin
bump; #421's fix was verified effective before relying on it (an isolated
`flavor: "nfet"` `diff_pair` now extracts `{"nfet": 8}`, not `pfet`).

## 8. Known limitations / follow-on work

- **LVS is not clean.** *(Still open; the reason has changed twice now.)* At
  #15 the blocker was device recognition -- neither `bjt_array` nor
  `res_array` output extracted as devices at all. The first increment (PR
  #64) closed that and hit the single-routing-metal bussing gap
  (klayout-tools#433). This increment closes *that* with a layout-side met1
  bus (Section 5a): the routed layout now extracts 24 `pnp` (dummies
  included), 16 `nfet`, 52 `pfet` and 159 `res_generic_po` devices with 24
  named top-level pins, and `klt lvs` compares 97 layout devices (after
  `combine_devices` folds the busses) against the reference's 16. The
  remaining blocker is **klayout-tools#461** (MOS gate poly has no
  contactable landing area): every split MOS group's fingers stay separate
  devices, and six of the schematic's twelve inter-block nodes -- everything
  that lands on a gate -- stay open. Secondary contributors are
  klayout-tools#462 (dummy edge units of the PNP/resistor arrays extract as
  real, unmatched devices) and #463 (the layout can only draw
  `res_generic_po`, not the schematic's higher-sheet-rho flavour). `klt lvs`
  runs and reports `mismatch`; the routed record's "LVS mismatch analysis"
  section quantifies and attributes each cause. Rewriting the reference
  netlist to enumerate the layout's own shortfalls would make LVS compare
  the layout against itself and is explicitly not done.
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
- **Inter-block connectivity is now mostly drawn, but not complete** -- 6 of
  12 schematic inter-block nets are joined across every block they reach (up
  from 4/12), via met1 (Section 5a). The rest terminate on a MOS gate and
  stay open -- klayout-tools#461. Issue #62's criterion 1 is scored PARTIAL,
  not MET, on this.
- **Intra-block bussing is drawn for PNP arrays and resistor ladders**, on
  met1 (Section 5a) -- closed for those device families. **MOS finger
  bussing is still not drawn**, for the same klayout-tools#461 gate-contact
  reason; each matched MOS pair's split fingers remain separate devices in
  the extracted netlist.
- **Array dummy edge units extract as real devices** with no schematic
  counterpart (klayout-tools#462) -- turning them off to shrink the LVS
  mismatch count would trade a real matching property for a smaller number,
  so this flow keeps them and reports the count honestly.
- **The resistor flavour drawn (`res_generic_po`) does not match the
  schematic's higher-sheet-rho flavour** (klayout-tools#463) -- a
  device-class mismatch with no layout-side workaround.
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
