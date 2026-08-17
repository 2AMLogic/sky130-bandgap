# `output-voltage-tc-post-layout` — record index and divergence finding

Post-layout (`provenance: extracted`) re-run of `sim/output-voltage-tc`'s
untrimmed output-reference + box-method TC claim against the routed,
DRC-clean / LVS-matching `layout/bandgap-core/` GDS, via
`klt extract --parasitics` translated by `sim/bin/post_layout_common.py`.
Records here are append-only and are **new** evidence — they neither
overwrite nor retire `sim/output-voltage-tc/`'s schematic-level records.

## Record index

| Record | Layout record measured | Status |
|---|---|---|
| `20260817-020357-13476b7` | `20260817-020222-13476b7` (`n_r2=51`, 49 coarse + 20 fine units/leg; DRC 0, LVS `match`, `mismatch_count=0`) | **Standing post-layout result, with a stated tool caveat.** 15/15 corners. `vref_27` 1.19291–1.19477 V (inside DR-005's 1.176–1.224 V window), but `vref_min` 1.16658–1.16970 V — 8.5…9.4 mV **below** the 1.176 V floor at every corner. Box TC 167.9–186.9 ppm/degC, binding corner `fs`. `Overall: FAIL`. The miss is **not** a sizing error: it is the `klt extract --parasitics` poly double-count of klayout-tools#800 (fixed upstream 2026-08-12, absent from the build that produced this snapshot) — see below. |
| `20260816-100445-6ea30d8` | `20260815-034022-001d1b7` | **Do not cite for the resistor legs.** Reused `sim/psrr-dc-post-layout/parasitics-snapshot/20260815-034022-001d1b7`, whose `res_high_po` cards carry **1599 Ω / 5 µm** and **159.9 Ω / 0.5 µm** — i.e. a pure `L/W · sheet_rho` value with **no** per-instance head/end term, unlike the same layout record's own `klt extract` output (2003.841367 / 542.118769 Ω) and unlike a fresh `klt extract --parasitics` at the pinned `klt`. That snapshot's `K = R2/R1` is exactly the drawn length ratio 7.1429 instead of the chained 7.6301, which is why this record reads `vref_27` ≈ 1.1797 V. The snapshot is left in place (append-only) but is a stale-tooling artifact, not a measurement of the drawn part. |
| `20260815-035841-001d1b7` | `20260815-034022-001d1b7` | Same stale snapshot as the row above; same caveat. |
| `20260811-231900-84ef136` | `20260811-221633-a0ee5e7` | Pre-#170 amp, pre-#178 sizing. Head-aware snapshot. `vref_27` 1.19328–1.19513 V. Superseded. |

## The divergence: schematic vs extracted, at the same sizing

Issue #178 made `design/bandgap_core.sch` model the routed chained array
exactly (see that file's CHAINED-ARRAY MODEL block), so the schematic and the
layout now describe the **same device-level leg**: `R1 = 14 026.89 Ω`,
`R2A = R2B = 109 030.60 Ω`, `K = 7.7733`. What remains is measured, at
`tt` / 27 °C:

| node | schematic | extracted | delta |
|---|---|---|---|
| `VREF` | 1.210335 V | 1.192989 V | **−17.35 mV** |
| `VA` (= VEB of Q1) | 0.726279 V | 0.718831 V | −7.45 mV |
| `VB` | 0.726409 V | 0.718945 V | −7.46 mV |
| `VBQ` | 0.664152 V | 0.656837 V | −7.31 mV |
| `ΔVBE = VB − VBQ` | 62.258 mV | 62.107 mV | −0.15 mV |

The cause is the extraction's **series interconnect resistance inside the
folded resistor arrays**, not the devices. Driving the resistor-only subset of
the extracted netlist (900 `R` cards: 145 device + 755 parasitic) terminal to
terminal gives:

| leg | device sum | extracted, incl. parasitics | delta |
|---|---|---|---|
| `R1` (VB→VBQ) | 14 026.89 Ω | **18 520.8 Ω** | +32.0 % |
| `R2A` (VOUT→VA) | 109 030.60 Ω | **141 169 Ω** | +29.5 % |
| `R2B` (VOUT→VB) | 109 030.60 Ω | **141 363 Ω** | +29.7 % |

Every internal chain net carries a two-terminal star of ≈ 229.7 Ω per
terminal (≈ 459 Ω per inter-unit link), so a leg's parasitic burden scales
with its *instance count*, not its resistance. Two consequences, both visible
in the table above:

1. `K` falls from 7.7733 to **7.622** (−1.9 %), removing ≈ 8.6 mV of `VREF`;
2. `R1` rises 32 %, so the branch current falls ≈ 24 %, which drops
   `VEB(Q1)` — and with it the whole curve — by a further ≈ 7.4 mV.

## The residual is a known, already-fixed-upstream `klt` artifact — not physics

It is **not** thin-metal jumper resistance, and it must not be designed
around. It is
[klayout-tools#800](https://github.com/2AMLogic/klayout-tools/issues/800):
`klt extract --parasitics` builds each net's star-R from the net's poly
shapes and subtracts only the MOS **gate** regions, not recognised
**resistor bodies** — so every drawn `res_high_po` body is charged once as
the device's own value *and* again as net parasitic resistance on the two
nets abutting it. That issue was filed from this repo's own friction
protocol and is **closed upstream (2026-08-12)**. The build that produced
this snapshot is not.

Every number above matches that issue's stated signature exactly:

- it reports "+29.8 %" on a chain's end-to-end DC resistance; this record
  measures +29.5 / +29.7 % on `R2A`/`R2B`;
- it predicts an internal-node net reporting ≈ 459 Ω (two abutting 5 µm × 1 µm
  bodies = 10 squares × the deck's 48.2 Ω/sq generic poly); this snapshot's
  internal chain nets report 2 × 229.727 Ω = **459.45 Ω**;
- total parasitic resistance (226 256 Ω) is **97.5 %** of total device
  resistance (232 088 Ω) — i.e. very nearly the whole resistor stack, counted
  twice.

Verified directly against the installed build rather than inferred: the
`klt` on `PATH` that `sim/bin/post_layout_common.py` invokes is
`klayout-tools @ git+…@a482d393` (0.2.0), and its
`extract.py` poly-role construction still reads
`[layer_index["nfet_gate"], layer_index["pfet_gate"]]` as the whole subtract
list, with no resistor-body term. `layout/requirements.txt`'s own pin
(`acb0ae6`, 2026-08-06) also predates the fix.

**Consequence for this record**: its `vref_*` numbers understate the drawn
part by ~17 mV, and its FAIL on the accuracy row is an artifact FAIL. The
correct next increment is to **bump `klt` past klayout-tools#800's fix and
re-extract** (this repo's documented pin-bump discipline: range-check the
commits, re-run `layout/bin/run-trivial-cell-flow.sh` for non-regression,
then re-run this bench), **not** to re-size `n_r2` and **not** to re-route
the array's inter-unit jumpers. Both of those would compensate a tool bug
with silicon.

**A second, repo-side gap this exposed**: `sim/bin/post_layout_common.py`
invokes bare `klt` from `PATH`, while `layout/bin/run-bandgap-routed-flow.sh`
uses the commit-pinned `layout/.venv/bin/klt`. So the layout records and the
post-layout sim records can be — and here are — produced by *different* `klt`
builds, with nothing in either record forcing them to agree. The pin-bump
increment should close that too.

**Why no re-size was attempted anyway.** Even taking the extracted numbers at
face value, the untrimmed lever is an integer `n_r2` worth ≈ 8.9 mV per step:
`n_r2=52` would move the extracted curve up ≈ 8.9 mV (still ≈ 0.5 mV short at
`fs`) while pushing the *schematic* `vref_max` over the 1.224 V ceiling at 6 of
15 (process, supply) points. There is no integer `n_r2` at which both
representations sit inside DR-005's window while a 17 mV offset separates them.
