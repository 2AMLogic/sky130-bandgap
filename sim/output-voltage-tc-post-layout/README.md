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

## The residual — corrected 2026-09-23 (issue #283): NOT a fixed-upstream artifact. It is a different, still-open `klt` defect (klayout-tools#2359), not physics, and not clearable by a version bump

**This section previously said klayout-tools#800 was "closed upstream
2026-08-12" and that bumping `klt` past its fix would clear this row. That
premise was wrong**, and issue #283 re-investigated it directly rather than
carrying the error forward. klayout-tools#800 was closed **`not_planned`**,
not fixed: the tool maintainer reproduced this repo's own repro steps against
a synthetic layout and found the described mechanism — the poly parasitics
role subtracting only MOS gates, not recognised resistor bodies — **does not
exist in the code**. `_resolve_resistors` already removes every recognised
resistor body from the `poly` region used for net parasitics *before* the
MOS-gate subtraction step runs (confirmed directly against the installed
source, `klayout_tools/extract.py`, klt v0.5.0). The closer explicitly
invited a fresh repro against real geometry if the anomaly persisted.

**It does persist — re-verified against the currently-installed build, not
assumed.** The bare `klt` on `PATH` this module invokes is now **v0.5.0**
(git `6bf5610939a096b81605a381e70454bf1cb20316`, tag `v0.5.0`, released
2026-09-15 — five weeks past #800's closure; `klt version --format json`).
Running `klt extract <this record's GDS> --deck sky130 --top
bandgap_core_routed --parasitics --format json` directly against that build
reproduces this snapshot's numbers **bit for bit**: `total_resistance_ohm`
226256.0625 (unchanged to four decimal places) and the internal chain-node
signature still exactly `2 × 229.7271/229.7272 = 459.4543` ohm. A `klt`
version bump alone does not — and, per the root cause below, cannot — clear
this row.

**The real mechanism: klayout-tools#2359 (open), a sibling finding, not
#800.** A parallel investigation (issue #284, same date) filed
[klayout-tools#2359](https://github.com/2AMLogic/klayout-tools/issues/2359)
against the actual cause: `_n_squares` fits **one** equivalent rectangle to a
net's *total* merged area/perimeter, which overstates R by roughly an order
of magnitude for a short, wide fragment whose current crosses along its short
axis — exactly what is left on a chain-internal net once the (correctly
subtracted) marked resistor bodies are removed: two contacted, unmarked
resistor heads plus a metal jumper. That issue's own minimal repro (generic
sky130 `res_generic_po` dimensions, no design-specific values) reports
**359.96 Ω** of poly-role resistance on such an internal net — matching this
snapshot's own by-layer breakdown (poly role 359.9576 Ω of the 459.4543 Ω
total) to four significant figures. klayout-tools#2359 is **open, unfixed**
as of 2026-09-23.

Every number this section previously attributed to #800 is still numerically
correct — it was the *citation*, not the arithmetic, that was wrong:

- +29.8 % on a chain's end-to-end DC resistance ↔ this record's +29.5 / +29.7 %
  on `R2A`/`R2B`;
- ≈ 459 Ω per internal-node net ↔ this snapshot's 2 × 229.727 Ω = 459.45 Ω,
  now matched to #2359's own generic repro rather than #800's refuted one;
- total parasitic resistance (226 256 Ω) is still 97.5 % of total device
  resistance (232 088 Ω).

**Consequence for this record.** The FAIL is real and, as of this writing,
not clearable by any `klt` build — but the strength and specificity of the
#2359 match (same mechanism, same magnitude, matching digits against a
generic repro built independently of this design) is evidence *against*
reading it as a real design defect in the drawn resistor network. It remains
far more consistent with a still-open extraction-geometry limitation than
with the divider's actual electrical behavior, so **the correct disposition
is still not** to re-size `n_r2` and **not** to re-route the array's
inter-unit jumpers — both would compensate a tool bug (now correctly
identified, not yet fixed) with silicon. See
`design/block-characterization-report.md` row 1b for the re-graded verdict
text.

**A second, repo-side gap this still exposes, not closed by this record**:
`sim/bin/post_layout_common.py` invokes bare `klt` from `PATH` (currently
v0.5.0), while `layout/bin/run-bandgap-routed-flow.sh` uses the
commit-pinned `layout/.venv/bin/klt` (`layout/requirements.txt`'s
`acb0ae6`, 2026-08-06). So the layout records and the post-layout sim
records can be — and are — produced by *different* `klt` builds, with
nothing in either record forcing them to agree. Left open: no
`layout/.venv` exists in this environment to safely bump and re-verify
`layout/requirements.txt`'s pin under that file's own non-regression
discipline, and it does not bear on this finding either way (this section's
re-verification used the same bare-`PATH` `klt` the sim harness itself
invokes). Each post-layout record's own parasitics-snapshot
(`parasitics-snapshot/<layout-record-id>/bandgap_core_routed.pex.json`)
already records exactly which `klt`/`klayout` build produced it, in its own
`provenance.klt_version`/`provenance.klayout_version` fields — that is the
per-record pin of record for this bare-`PATH` flow, since no dedicated
version-pin file exists for it (unlike `layout/requirements.txt`'s commit
pin for the layout DRC/LVS flow).

**Why no re-size was attempted anyway.** Even taking the extracted numbers at
face value, the untrimmed lever is an integer `n_r2` worth ≈ 8.9 mV per step:
`n_r2=52` would move the extracted curve up ≈ 8.9 mV (still ≈ 0.5 mV short at
`fs`) while pushing the *schematic* `vref_max` over the 1.224 V ceiling at 6 of
15 (process, supply) points. There is no integer `n_r2` at which both
representations sit inside DR-005's window while a 17 mV offset separates them.
