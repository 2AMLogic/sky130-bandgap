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
