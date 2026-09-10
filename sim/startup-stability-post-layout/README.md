# `startup-stability-post-layout` — divergence finding

Post-layout (`provenance: extracted`) re-run of `sim/startup-stability`'s
degenerate-state / single-equilibrium claim against the ROUTED, LVS-clean
`layout/bandgap-core/` GDS (issue #62) wired to the SCHEMATIC-netlisted
`design/startup_injector.sch` (issue #10 has no layout yet for the
injector), for issue #16. Records here are append-only and are **new**
evidence — they neither overwrite nor retire `sim/startup-stability/`'s
schematic-level records.

This file exists because issue #16 requires any divergence from the
schematic-level result to be **documented as a finding, not reconciled
away**. The core claim — exactly one DC equilibrium, actively driven away
from the degenerate state — holds identically post-layout; the divergence is
a quantitative one, in the injector-attach cost (`dvref`), that grows at
every corner but stays well inside the bench's own bound.

## What the record says

Record `20260812-065107-7eb5be4` — worst-corner 8-point subset (process in
{ff, ss} x temperature in {-40, 125} °C x supply in {2.97, 3.63} V; see the
record body for the full subset justification), `Overall: PASS`, 8/8.

| Quantity | Post-layout (extracted) range | Limit | Verdict |
|---|---|---|---|
| `ncross_su` (equilibrium count, injector attached) | 1 at every corner | == 1 | pass, 8/8 |
| `ncross_bare` (control: bare-core equilibrium count) | ~1.00001 … 3 | reported, not gated | n/a (control) |
| `dvref` (injector-attach cost) | 0.0215 … 15.5479 mV | ±20 mV | pass, 8/8 |
| `vgdrv_dut` spread check | 0.9136 V observed | ≥ 0.3 V | pass |
| `vref_dut` spread check | 0.0512 V observed | ≥ 0.01 V | pass |

## Why a new schematic-level baseline was needed

`sim/startup-stability/`'s existing committed records all predate the `n_r2`
resize chain (`54 -> 50`, DR-003 close-out issue #99, PR #105/#110/#111/#113)
— the same conflation-with-a-resize trap `sim/line-regulation-post-layout/README.md`
and `sim/startup-ramp-post-layout/README.md` already document for their own
benches. A new same-sizing schematic-level record,
`sim/startup-stability/records/20260812-081515-7eb5be4`, was appended at the
identical 8-point worst-corner subset for a clean, corner-for-corner
comparison against this post-layout record (same bench, same manifest, same
measurement expressions, same commit `7eb5be4`; the only variable is the DUT
body).

## The divergence: `dvref` (injector-attach cost) grows at every corner

`dvref` is `v(vrefd)[0] - v(vrefr)[0]` — the shift attaching the injector
puts on the reference, measured within one DUT (free-running core+injector
minus the bare-core control at the same corner), not a schematic-vs-layout
comparison by itself. Comparing the two same-sizing, same-corner records:

| Corner | schematic `dvref` | post-layout `dvref` | delta |
|---|---|---|---|
| `ff_-40c_2.97v` | 0.2845 mV | 0.4537 mV | +0.1692 mV |
| `ff_-40c_3.63v` | 0.9242 mV | 1.4633 mV | +0.5391 mV |
| `ff_125c_2.97v` | 0.2442 mV | 0.3911 mV | +0.1468 mV |
| `ff_125c_3.63v` | **8.0001 mV** | **15.5479 mV** | **+7.5479 mV** |
| `ss_-40c_2.97v` | 0.0215 mV | 0.0349 mV | +0.0134 mV |
| `ss_-40c_3.63v` | 0.0748 mV | 0.1206 mV | +0.0458 mV |
| `ss_125c_2.97v` | 0.0594 mV | 0.0910 mV | +0.0316 mV |
| `ss_125c_3.63v` | 0.2154 mV | 0.7592 mV | +0.5438 mV |

`dvref` grows at all 8 corners, roughly in proportion to its own schematic
value (worst corner nearly doubles: 8.00 -> 15.55 mV), and the worst corner
is the same one in both records (`ff/125 °C/3.63 V`) — the same shape as
`sim/quiescent-current-post-layout/README.md`'s finding that extraction acts
as a *scale factor* rather than a new mechanism. `dvref`'s own note in
`sim/startup-stability/experiment.json` explains why: it is a residual
current out of the high-impedance `GDRV` node read back as a voltage
(roughly 0.2 mV per nA), so anything that changes the resistance network
around that node moves it — exactly the star-R parasitic network
`sim/quiescent-current-post-layout/README.md` (R1 +55 %) and
`sim/line-regulation-post-layout/README.md` (K = R2/R1 -0.2 % from
parasitics alone, +9.7 % from the drawn chained array) already attribute
this extraction's other shifts to.

**The claim itself does not weaken.** `ncross_su` is exactly 1 at every one
of the 8 corners in both records — the single-equilibrium property `sim/startup-stability`
exists to verify is untouched by extraction. Even at its worst corner,
post-layout `dvref` (15.5 mV) is comfortably inside the bench's own ±20 mV
bound, with headroom to spare; the finding is that the margin shrinks from
schematic's 12.0 mV to 4.45 mV at that one corner, not that the bound is
threatened.

## Update (2026-09-10, issue #279): re-run against the post-#193 chained-array design — margin now thin, not just narrowed

Issue #279 re-ran this bench (and its schematic-level sibling, at the same
8-point worst-corner subset) against the current design after issue #193
changed `design/bandgap_core.sch`'s resistor network (chained-array model,
`n_r2` 50 → 51). New records:
`sim/startup-stability/records/20260909-232410-e8e2e46.md` (schematic,
supersedes `20260815-032111-001d1b7`) and
`sim/startup-stability-post-layout/records/20260909-232410-e8e2e46.md`
(post-layout, supersedes `20260815-040144-001d1b7`), both against the routed
layout report `layout/bandgap-core/reports/20260817-020222-13476b7/`.

Both are `Overall: PASS`, 45/45 and 8/8 respectively — `ncross_su` is still
exactly 1 at every corner in both, so the single-equilibrium claim itself is
untouched. **But the worst-corner `dvref` margin has shrunk sharply**, not
merely narrowed as the prior cycle's finding described:

| Corner | prior schematic | prior post-layout | **new schematic** | **new post-layout** |
|---|---|---|---|---|
| `ff_125c_3.63v` (worst) | 8.00 mV | 15.55 mV | **14.66 mV** | **19.31 mV** |

Post-layout `dvref` at the worst corner is now **19.31 mV against the ±20 mV
bound — 0.69 mV of headroom**, down from the prior cycle's 4.45 mV headroom
and the cycle before that's comfortable margin. The verdict is still PASS,
but this is materially closer to the bound than either prior record showed,
and worth flagging explicitly rather than only noting "the margin shrinks":
a further resistor-network change of similar magnitude to #193's could flip
this corner to FAIL without any change to the single-equilibrium property
itself. All 7 non-worst corners remain far from the bound (see the record for
full values), so this is a single-corner watch item, not a broad regression.
Same attributed mechanism as before (the `GDRV`-node residual-current
readback scaling with the resistance network around it) — `dvref` grew at
schematic level too (8.00→14.66 mV), confirming the shift is the design
change, not a new extraction artifact.

Per this repo's append-only convention, the sections above are left exactly
as written — this is a dated addendum, not a rewrite.

## Known gaps (not closed by this record)

- This record and its schematic-level comparison baseline only cover the
  8-corner worst-case subset, not the full 45-point matrix — see the record
  body's subset justification (citing `sim/startup-ramp`'s and
  `sim/startup-stability`'s own notes for where this design's margin is
  thinnest). The sibling `sim/startup-ramp-post-layout/` runs the full
  matrix instead, since a single corner there is far cheaper.
