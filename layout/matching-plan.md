# Bandgap core -- floorplan and matching plan (issue #15)

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
| `res_r2` (R2A/R2B) | 16 units (8/leg) | 108 units (54/leg) | a single-row `res_array` at 108 units is ~710 um long (measured directly: `klt gen res_array --params '{"num":108,...}'` reports `bbox_um.x1 - x0 = 709.6`) -- pairing that with any other block in a floorplan forces the whole composition's bounding box past the 0.05 mm^2 budget on width alone, even though the segments' own drawn area is small. `klt gen res_array` has no row-folding/meander parameter to keep a long unit-resistor string's *footprint* compact the way `mos_array`/`bjt_array`'s `rows`/`cols` do -- filed as new friction, [2AMLogic/klayout-tools#415](https://github.com/2AMLogic/klayout-tools/issues/415). Until that lands (or a hand-folded layout is built), a full-scale single-row R2A/R2B ladder does not fit this budget; the skeleton uses a representative 1/6.75-scale count instead, to prove the interdigitated composition + DRC-clean mechanism now and keep the real-count constraint on record for whoever builds the tape-out-ready version. |
| `res_r1` | 7 units | 7 units | drawn 1:1 (small enough to be tractable at full scale) |
| `res_trim` | 32 units (16/leg) | 32 units (16/leg) | drawn 1:1 |
| `amp_input_pair` | mult=16 (splits=16) | mult=16 | drawn 1:1 |
| `amp_nload` / `amp_nmirr` | mult=4 each | mult=4 each | drawn 1:1 |
| `amp_pmirr` | mult=8 (splits=8) | mult=8 | drawn 1:1 |
| `core_mirror` | mult=2 (splits=2) | mult=2 | drawn 1:1 |

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
  code-select tap on the trim ladder feeds which net) are explicitly
  deferred -- see "Known limitations" below. The floorplan-level placement
  above (short, direct paths from each block's own ring to a shared VDD/
  VSS trunk running along the guard ring's own tap contacts) is the
  intended strategy, not yet drawn.

## 6. Area budget

| Item | Area |
|---|---|
| Amp transistors (MP1/MP2 + MN1-MN4 + MP3/MP4), analytic | 10,880 um^2 (`design/error-amp-offset-budget.md` Section 4) |
| MCC compensation cap, analytic (single-ended, not a matched pair -- see Section 2) | 9,600 um^2 |
| Core PNP + resistor + mirror devices, analytic (drawn/emitter area only) | ~735 um^2 (MPOUT+MPAMP 64, Q1 3.7, Q2 92.5, R1 35, R2A+R2B 540) |
| **Analytic device total** | **~21,215 um^2** |
| **Skeleton composed floorplan bbox** (measured, includes guard rings, dummies, spacing, and the reduced R2A/R2B count from Section 4) | **35,763 um^2** (`layout/bandgap-core/reports/LATEST/record.md`) |
| **Budget** | **50,000 um^2 (0.05 mm^2)** |

The skeleton's measured footprint (35,763 um^2) is within budget with
~29% margin, but it does **not** yet include the R2A/R2B ladder at its
real 108-unit count (Section 4) -- closing that gap (via
2AMLogic/klayout-tools#415's folding capability, or a hand-folded layout)
is the largest open item standing between this skeleton and a budget
claim over the real design. `design/device-characterization-summary.md`'s
own note on `MPOUT`/`MPAMP` sizing (a potential 6.25x per-unit-area
increase to size E, flagged there for this issue) is a small fraction of
the remaining margin even before folding closes the resistor gap, and is
not expected to be a blocker on its own.

## 7. `klt` generator mapping and friction

| Matched group | Generator | DRC-clean | LVS-recognized |
|---|---|---|---|
| PNP arrays (Q1, Q2) | `bjt_array` | yes | no -- draws generic bipolar-shaped geometry from base layers, not the PDK's own vendor `pnp_05v5` cell (2AMLogic/klayout-tools#176's own design note); confirmed directly: `klt extract` on a `bjt_array` output reports `device_count: 0` |
| Resistor ladders (R2A/R2B, R1, trim) | `res_array` | yes | no -- never draws the PDK's resistor-ID marker layer (2AMLogic/klayout-tools#369, already tracked before this issue) |
| Amp input pair, NMOS loads/mirrors, PMOS mirror, core mirror | `diff_pair` | yes | not attempted (composed output is DRC-only this issue; see `gen_bandgap_floorplan.py`'s module docstring) |
| Overall + per-group guard rings | `guard_ring` (standalone) / `add_guard_ring`/`add_collector_ring` (built into `diff_pair`/`bjt_array`) | yes | n/a |
| 2D floorplan composition | `gen-compose` `placement.strategy: "explicit"` | n/a | n/a |

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

## 8. Known limitations / follow-on work

- **No LVS on the composed floorplan.** Both `bjt_array` and `res_array`
  output are not recognized by `klt extract` as `pnp`/`resistor` devices
  (Section 7). DRC-clean is this issue's acceptance bar; full LVS closure
  on the bandgap core's actual layout is later work, and depends on
  upstream `klt` capability this issue does not control.
- **R2A/R2B ladder is at reduced scale** (Section 4) -- the real 108-unit
  count needs either 2AMLogic/klayout-tools#415's folding capability or a
  hand-folded layout to fit the area budget.
- **The amp's 4-device NMOS load/mirror group (MN1-MN4) is split into two
  matched pairs** (MN1/MN2 in row 2, MN3/MN4 in row 3) because `diff_pair`
  only common-centroids two devices at a time; a true 4-device
  common-centroid quad (the textbook ABBA/BAAB arrangement for a group
  this size) is not directly expressible with today's generators. Not
  filed as new friction this pass -- flagged here for whoever picks up
  full tape-out-ready layout, since it may be resolvable by a different
  placement of two `diff_pair` instances relative to each other rather
  than needing a new generator.
- **Metal-trunk VDD/VSS routing and trim-tap connectivity are not drawn**
  (Section 5) -- the floorplan states the intended strategy; routing
  itself is later work.
- **Inter-block routing between matched groups** (e.g. Q1's emitter to
  R2A, the amp's AOUT to GDRV) is not drawn -- this issue's skeleton
  proves placement + DRC, not full-cell connectivity.

## 9. Evidence

- Floorplan generation/placement/DRC driver:
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
