# `output-voltage-tc-post-layout` — record index and divergence finding

Post-layout (`provenance: extracted`) re-run of `sim/output-voltage-tc`'s
untrimmed output-reference + box-method TC claim against the routed,
DRC-clean / LVS-matching `layout/bandgap-core/` GDS, via
`klt extract --parasitics` translated by `sim/bin/post_layout_common.py`.
Records here are append-only and are **new** evidence — they neither
overwrite nor retire `sim/output-voltage-tc/`'s schematic-level records.

## Record index

This index is **not exhaustive** — it stops at `20260817-020357-13476b7`
plus the newest row below, and the four records in between
(`20260923-061116-1e38c62`, `20260923-074724-dbd4dda`,
`20261113-095223-bcacdb6`, `20261113-111050-7efdcf3b`) are not tabulated
here. `records/` itself is authoritative; the newest record there always
carries the current verdict.

| Record | Layout record measured | Status |
|---|---|---|
| `20261114-184650-4a9f2c97` | `20260923-070209-dbd57a9` (same routed GDS as the record it supersedes — `layout/bandgap-core/reports/LATEST`) | **Standing post-layout result (issue #540).** First record measured on a `klt extract --parasitics` snapshot produced by the **pinned `klayout-tools==0.8.0`**, which carries klayout-tools#2359's fix. `vref_min` 1.153502–1.168538 V — **FAIL 15/15**, i.e. *worse* than the 14/15 it superseded, and the one corner that used to clear the 1.176 V floor (`ff_27c_3.63v`) no longer does. Box TC 136.5–212.0 ppm/degC, **FAIL 15/15**. `Overall: FAIL`. **This refutes this bench's own standing attribution of row 1b to klayout-tools#2359** — see "The #2359 attribution is refuted" below. Supersedes `20261113-111050-7efdcf3b`. |
| `20260817-020357-13476b7` | `20260817-020222-13476b7` (`n_r2=51`, 49 coarse + 20 fine units/leg; DRC 0, LVS `match`, `mismatch_count=0`) | Earlier standing result, with a stated tool caveat (**the caveat is now refuted — see below**). 15/15 corners. `vref_27` 1.19291–1.19477 V (inside DR-005's 1.176–1.224 V window), but `vref_min` 1.16658–1.16970 V — 8.5…9.4 mV **below** the 1.176 V floor at every corner. Box TC 167.9–186.9 ppm/degC, binding corner `fs`. `Overall: FAIL`. The miss is **not** a sizing error: it is the `klt extract --parasitics` poly double-count of klayout-tools#800 (fixed upstream 2026-08-12, absent from the build that produced this snapshot) — see below. |
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

## SUPERSEDED 2026-11-14 (issue #540) — the residual as attributed on 2026-09-23 (issue #283) to a then-open `klt` defect (klayout-tools#2359)

> **Read "The #2359 attribution is refuted" below first.** klayout-tools#2359
> closed `completed` on 2026-09-23 and its fix is present in the pinned
> `klayout-tools==0.8.0`. Record `20261114-184650-4a9f2c97` re-extracted this
> same routed GDS at that pin and row 1b **still fails — 15/15 instead of
> 14/15**. The section below is kept verbatim as the reasoning of record on
> 2026-09-23 (it was correct about the arithmetic and about #800), but its
> central claim — that #2359 is the cause and that the row is therefore not a
> design defect — is **no longer supported by measurement**. Every sentence
> below that calls #2359 "open" or "unfixed" was true when written and is
> false now.

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

## The #2359 attribution is refuted — measured at the pinned `klt` 0.8.0, 2026-11-14 (issue #540)

**Record `20261114-184650-4a9f2c97` is the single-variable test of this
bench's own standing explanation, and the explanation fails it.**

klayout-tools#2359 closed **`completed`** on 2026-09-23T21:54:42Z via
upstream PR #2392 ("fix(extract): count parasitic squares per conductor
fragment, not per merged net"). That fix is absent from `v0.6.0` and present
in `v0.7.0` and `v0.8.0`, so the pin this repo already ratified in
`layout/requirements.txt` — `klayout-tools==0.8.0` — carries it. Every
post-layout record before this one measured a snapshot extracted at `klt`
**0.5.0** (released 2026-09-15, eight days *before* the fix merged), so the
attribution had never actually been tested.

### The experiment had exactly one variable

| | superseded record | this record |
|---|---|---|
| record | `20261113-111050-7efdcf3b` | `20261114-184650-4a9f2c97` |
| layout record / routed GDS | `20260923-070209-dbd57a9` | **same** |
| snapshot `provenance.klt_version` | `0.5.0` | **`0.8.0`** (the ratified pin) |
| snapshot `schema_version` | 3 | 4 |
| snapshot resolution | `reused:sim/startup-time-post-layout/…` | `local` |
| `device_counts` | `nfet 19, pfet 54, pnp 24, res_high_po 145` | **identical** |
| translated device counts | `mos 73, pnp 24, res 145` | **identical** |
| `.SUBCKT` port order | `D1 D2 GDRV NE NG PN TAIL VA VB VBQ VDD VOUT VSS` | **identical** |
| `r_count` / `c_count` / `cc_count` | 799 / 156 / 194 | **identical** |
| `total_capacitance_ff` | 1487.344084 | **identical** |
| `total_resistance_ohm` | 234007.2692 | **179145.6648 (−23.44 %)** |
| PDK | open_pdks `f6eeac7` | **same** |

The DUT, the testbench, the device set, the netlist topology and the
capacitance are all bit-identical; the translated **device** resistor cards
are identical too (verified in
`sim/tests/test_post_layout_resistor_dialects.py`). Only the extracted
**parasitic** resistance moved. That is as clean as this experiment can be.

### Result: the row did not recover — it got worse at every corner

`vref_min` floor is 1.176 V; `tc_ppm` limit is ≤ 50 ppm/degC.

| corner | `vref_min` 0.5.0 (V) | `vref_min` 0.8.0 (V) | Δ (mV) | 1b | `tc_ppm` 0.5.0 | `tc_ppm` 0.8.0 | Δ | 3b |
|---|---|---|---|---|---|---|---|---|
| `fs_27c_2.97v` | 1.167045 | 1.153502 | −13.54 | FAIL | 185.578 | 212.017 | +26.4 | FAIL |
| `ss_27c_2.97v` | 1.167068 | 1.153514 | −13.55 | FAIL | 181.904 | 208.361 | +26.5 | FAIL |
| `ss_27c_3.30v` | 1.167124 | 1.153549 | −13.58 | FAIL | 181.911 | 208.434 | +26.5 | FAIL |
| `tt_27c_2.97v` | 1.167495 | 1.153893 | −13.60 | FAIL | 178.791 | 205.330 | +26.5 | FAIL |
| `tt_27c_3.30v` | 1.167687 | 1.154017 | −13.67 | FAIL | 178.632 | 205.409 | +26.8 | FAIL |
| `fs_27c_3.30v` | 1.167877 | 1.154066 | −13.81 | FAIL | 181.491 | 209.250 | +27.8 | FAIL |
| `ss_27c_3.63v` | 1.167978 | 1.154070 | −13.91 | FAIL | 177.963 | 206.109 | +28.1 | FAIL |
| `ff_27c_2.97v` | 1.168181 | 1.154498 | −13.68 | FAIL | 176.638 | 203.105 | +26.5 | FAIL |
| `ff_27c_3.30v` | 1.169756 | 1.155370 | −14.39 | FAIL | 171.297 | 201.032 | +29.7 | FAIL |
| `sf_27c_2.97v` | 1.170882 | 1.157001 | −13.88 | FAIL | 172.923 | 197.109 | +24.2 | FAIL |
| `sf_27c_3.30v` | 1.171026 | 1.157114 | −13.91 | FAIL | 180.576 | 204.107 | +23.5 | FAIL |
| `fs_27c_3.63v` | 1.171097 | 1.156624 | −14.47 | FAIL | 165.307 | 196.298 | +31.0 | FAIL |
| `sf_27c_3.63v` | 1.171990 | 1.157715 | −14.28 | FAIL | 185.610 | 211.002 | +25.4 | FAIL |
| `tt_27c_3.63v` | 1.172176 | 1.157141 | −15.04 | FAIL | 156.858 | 190.292 | +33.4 | FAIL |
| `ff_27c_3.63v` | **1.186483 (PASS)** | 1.168538 | −17.94 | **FAIL** | 89.811 | 136.545 | +46.7 | FAIL |

- **Row 1b (`vref_min`): FAIL 14/15 → FAIL 15/15.** Span 1.167045–1.186483 V
  → 1.153502–1.168538 V. Mean −14.22 mV, worst −17.94 mV, best −13.54 mV. The
  sole passing corner `ff_27c_3.63v` lost 17.94 mV and now fails.
- **Row 3b (`tc_ppm`): FAIL 15/15 → FAIL 15/15**, every corner worse by
  +23.5…+46.7 ppm/degC. Span 89.811–185.610 → 136.545–212.017 ppm/degC.
  Row 3b shares this bench, this record and this snapshot with row 1b
  (both signoff envelopes pin the same netlist snapshot), so it moves with
  the re-extraction whether or not anyone writes it down. Written down here.

**So the standing attribution is wrong.** The repo stated that row 1b fails
because of an open, unfixed klayout-tools#2359 and is therefore "not confirmed
as a design defect". The fix is in the measured extraction and the row fails
harder. #2359 cannot be the cause of what remains.

### Why a 23 % *drop* in total parasitic R made `VREF` *lower*

Because #2359's fix **redistributes** resistance, and the one net it moved
*upward* is the one that matters. Per-net parasitic R, aggregated from each
snapshot's own star arms (hub node = net, `R<net>_t<k>` cards):

| net | 0.5.0 (Ω) | 0.8.0 (Ω) | Δ | star arms |
|---|---|---|---|---|
| **`VSS`** | 16 012.97 | **25 948.43** | **+62.0 %** | 229 |
| `VDD` | 72 093.12 | 70 625.28 | −2.0 % | 107 |
| `GDRV` | 21 469.91 | 18 696.66 | −12.9 % | 35 |
| `TAIL` | 10 827.24 | 10 386.88 | −4.1 % | 18 |
| `D1` / `D2` | 9 645.71 / 9 664.47 | 8 465.95 / 8 484.72 | −12.2 % | 20 / 20 |
| `PN` | 8 920.93 | 6 440.11 | −27.8 % | 28 |
| `VA` | 6 894.38 | 5 206.23 | −24.5 % | 17 |
| `VB` | 6 783.06 | 5 114.54 | −24.6 % | 10 |
| `NG` | 1 948.62 | 1 732.89 | −11.1 % | 4 |
| `NE` | 1 897.87 | 1 602.28 | −15.6 % | 9 |
| `VOUT` | 1 682.14 | 979.56 | −41.8 % | 6 |
| `VBQ` | 564.47 | 199.52 | −64.7 % | 9 |

`VSS` is the **only** net that rose, and it rose by +9 935 Ω. It is also the
shared return for all 229 of its terminals — every PNP emitter/base return
and the whole ladder's bulk return. In the star model each of those terminals
sees its own arm of a single lumped per-net R, so an inflated `VSS` lifts the
local ground under the PNP stack and the divider taps, and that offset
subtracts directly from `v(vref)` as measured against the testbench's global
0. The totals are dominated by `VDD` (70 kΩ, barely moved); the
*signal-relevant* return path is what got 62 % worse. Hence lower total R,
lower `VREF`.

That inflation is a known and **deliberately-defaulted** extractor behaviour,
not a new defect: klayout-tools#2458 ("sums a net's per-level lumped R in
series, so via-stitched strapping raises the reported resistance instead of
lowering it") closed `completed` 2026-10-22, but its fix is **opt-in** — the
upstream disposition states the legacy series sum "remains the default path"
for backward compatibility, with a graph-based alternative behind
`--resistance-graph` (present in this pin's `klt extract --help`, and *not*
passed by `run_klt_extract_parasitics`). A via-stitched `VSS` plane is exactly
the geometry #2458 describes. The snapshot's own `parasitics.model_revision`
is `2` here and absent at 0.5.0 — the disclosure field klayout-tools#2957
asked for, which is what makes this cross-version comparison auditable at all.

### What this does and does not establish

- **Established, by measurement**: klayout-tools#2359 is not the cause of row
  1b's residual. Any statement in this repo that row 1b fails because #2359
  is open is false and has been corrected.
- **Established, by measurement**: the residual is dominated by the extracted
  `VSS` return allocation under the default lumped-star resistance model, not
  by the resistor-ladder legs the 2026-09-23 section analysed.
- **NOT established**: that the row is a real design defect. Nothing here
  measures the drawn part against a *physical* return-path model; a 25.9 kΩ
  series ground return distributed to 229 terminals is a modelling artifact of
  the default lumped star, not a credible property of a via-stitched plane.
- **NOT established, and deliberately not attempted here**: whether the
  residual survives a distributed/in-path model. That is **issue #541**'s
  question (`--critical-net` / `--distributed-rc` on the `sim/pex-native/`
  pilot). This record holds `distributed_rc: false` and `critical_nets: []`
  at default flags, exactly as the record it supersedes did.
- **Disposition unchanged**: still do **not** re-size `n_r2` and do **not**
  re-route the array's inter-unit jumpers on the strength of this row. The
  reason has changed — not "a tool bug is about to be fixed upstream" but "the
  default extraction resistance model is not yet a physical return-path model,
  and #541 is what will tell us" — and the ratified spec is not relaxed either
  way (`spec/`, DR-005).
- The repo-side `klt`-version gap the 2026-09-23 section flagged is now
  **partly closed in this record and nowhere else**: this snapshot was
  extracted at the ratified `layout/requirements.txt` pin, by prepending a
  throwaway `klayout-tools==0.8.0` virtualenv to `PATH` for the extraction
  step. The host's own `klt` is a `0.9.2.dev` build and
  `run_klt_extract_parasitics` still shells out to a bare `klt` from `PATH`,
  so **nothing forces the next extraction to use the pin**. No override was
  added to the shared harness (out of scope for issue #540).

### This snapshot now wins sibling resolution for every other post-layout bench

`resolve_parasitics_snapshot` step 2 globs
`sim/*/parasitics-snapshot/<layout_record_id>` and takes `sorted()[0]`.
With this bench's `20260923-070209-dbd57a9/` committed,
`output-voltage-tc-post-layout` sorts **ahead of**
`startup-time-post-layout`, so **every other post-layout bench that has no
local snapshot for this layout record will now resolve this klt-0.8.0
snapshot** instead of the klt-0.5.0 one it used before.

The consequence is disclosed, not hidden — no resolver change was made
(explicitly out of scope for issue #540), and the directory name is forced:
resolution keys on the layout record id, so a fresh-timestamp name would
never be read by anything.

**Update (2026-11-15, issue #560): the follow-up has landed.** The five benches with no
local snapshot for this layout record — `quiescent-current`, `psrr-dc`, `startup-ramp`,
`line-regulation`, `startup-stability` (all `-post-layout`) — have been re-run and now
measure **this klt-0.8.0 extraction** (their newest records cite
`total_resistance_ohm` 179 145.6648 from this snapshot via `resolve_parasitics_snapshot`
step 2). The one bench this did not reach is `sim/startup-time-post-layout/`, which
resolves its **own** local klt-0.5.0 snapshot at step 1 before the sibling glob ever runs;
it is disclosed in its own README and deliberately left there (append-only forbids
re-extracting over its committed snapshot, and it is bound to no ratified spec row).

The superseded records below remain valid as append-only evidence of what was measured
then; the module's cross-bench invariant now holds for every post-layout bench except
`startup-time-post-layout`, whose residual 0.5.0 divergence is disclosed, not hidden.

### A third `klt` resistor card dialect, and a new tool-gap filing

The 0.8.0 extraction writes each `res_high_po` as
`X$n <a> <b> <bulk> res_high_po r=<value> L=.. W=..`, where 0.5.0 wrote
`R$n <a> <b> <bulk> <value> res_high_po L=.. W=..`. The shared translator
matched neither prefix nor parameter shape, so all 145 resistors fell through
and `build_extracted_body`'s `device_counts` cross-check aborted the run —
the guard working correctly. `sim/bin/post_layout_common.py` now matches both
dialects additively (the 0.5.0 path translates byte-identically, so the other
six benches are untouched), covered by
`sim/tests/test_post_layout_resistor_dialects.py`.

An `X`-prefixed card with no matching `.SUBCKT` is valid SPICE for a
subcircuit call, so an unrecognised resistor would have reached ngspice as a
call to an undefined subckt rather than failing to parse. Filed generically,
per this repo's friction protocol, as
[klayout-tools#5741](https://github.com/2AMLogic/klayout-tools/issues/5741)
(third card-syntax change across releases with no stated contract; asks for a
machine-readable device table in the JSON summary so consumers stop parsing
SPICE text).

## Experiment description and record history

Moved verbatim from the "Experiments that do not go through the corner runner" table in `sim/README.md` (issue #339). The newest entry under `records/` is authoritative for the current verdict; the text below was written when the cited records were current.

**Post-layout (`provenance: extracted`) re-run of `sim/output-voltage-tc`'s claim (issue #16)** against the routed, LVS-clean `layout/bandgap-core/` GDS (issue #62) instead of `design/bandgap_core.sch` — the DUT body is not something xschem-netlisting a schematic can produce, since it comes from `klt extract --parasitics` (real per-net routing RC) with its generic LVS device-class placeholders translated to simulatable sky130 vendor models; see `sim/bin/post_layout_common.py`'s module docstring for the full translation methodology (including a discovered, worked-around ngspice/sky130-BSIM-binning unit-suffix quirk) and `sim/output-voltage-tc-post-layout/records/` for the evidence. Wraps `sim/output-voltage-tc/testbench/tb_vref_tc.sch` unmodified (same body-substitution convention as the two rows above), swapping the netlisted `.subckt bandgap_core`/`.subckt error_amp` blocks for the translated, extracted layout instead of a resistor-array edit
