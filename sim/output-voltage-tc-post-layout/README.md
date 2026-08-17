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
| `20260817-020357-13476b7` | `20260817-020222-13476b7` (`n_r2=51`, 49 coarse + 20 fine units/leg; DRC 0, LVS `match`, `mismatch_count=0`) | **Standing post-layout result.** 15/15 corners. `vref_27` 1.19291–1.19477 V (inside DR-005's 1.176–1.224 V window), but `vref_min` 1.16658–1.16970 V — 8.5…9.4 mV **below** the 1.176 V floor at every corner. Box TC 167.9–186.9 ppm/degC, binding corner `fs`. `Overall: FAIL`. See "The divergence" below: the miss is a post-layout *interconnect-resistance* effect, not a sizing error. |
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

**This is deliberately not compensated by re-sizing.** The untrimmed lever
here is an integer `n_r2`, worth ≈ 8.9 mV per step: `n_r2=52` would move the
extracted curve up ≈ 8.9 mV (still ≈ 0.5 mV short at `fs`) while pushing the
*schematic* `vref_max` over the 1.224 V ceiling at 6 of 15 (process, supply)
points. There is no integer `n_r2` at which both representations sit inside
DR-005's window while a 17 mV structural offset separates them, and sizing the
schematic to cancel an interconnect effect would state a design the schematic
does not describe. The correct lever is the **layout's own inter-unit
routing** (wider / shorter li1 jumpers, or a met1 strap along each chain),
which is a routing increment, not an untrimmed-sizing one.

**Open question, deliberately left open**: ≈ 459 Ω per short li1 inter-unit
jumper is high — li1 is genuinely resistive in sky130, but so is the
head/end poly term the *device* value already carries
(`fixed_offset_ohm = 379.705 Ω`), and the extraction's total parasitic
resistance (226 256 Ω) is 97.5 % of its total device resistance
(232 088 Ω). Whether the chain nets' star resistance double-counts poly that
the `res_high_po` device card already charges, or is a faithful model of thin
local interconnect, is not settled by anything measured here. `klt extract`
offers `--distributed-rc` / `--critical-net` as an alternative parasitic model
this bench does not currently use; re-running the divider nets under it is the
cheapest next probe and is a bench change, out of issue #178's scope.
