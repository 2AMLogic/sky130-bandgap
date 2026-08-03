# `startup-stability` — record index

Records here are append-only (`sim/README.md`); this index is not a substitute
for that convention, it is a pointer added *alongside* the records so a reader
who lists `records/` does not attribute an old record's numbers to the current
design. Same purpose and format as `sim/output-voltage-tc/README.md` (issue
#55); this one exists because of issue #52.

**Read this before citing any record here.** Three different circuits have been
measured under this slug. Only the newest one is the design in `design/`.

| Record | Design measured | Status |
|---|---|---|
| `20260803-114600-e599e30` | Pre-#41 amp (`amp_m_in=2`) + injector without `MNC` | Superseded. Launched concurrently with `-114658` on one machine; 9 of 12 corners timed out from the contention. |
| `20260803-114658-e599e30` | Pre-#41 amp (`amp_m_in=2`) + injector without `MNC` | Superseded. The other half of that concurrent pair; same 9 timeouts. |
| `20260803-124600-e599e30` | Pre-#41 amp (`amp_m_in=2`) + injector without `MNC` | Superseded. 11 of 12 corners; `ff/125 °C/3.63 V` was killed by an external `SIGKILL` at sweep point 230/251. **Source of the retired "3.2 mV" `dvref` figure** that `design/startup_injector.sch` used to carry — retired, not superseded: the amplifier it was measured on was replaced by issue #9 / PR #41. |
| `20260803-144531-544cc5e` | **Shipped-at-the-time amp (`amp_m_in=16`) + injector without `MNC`** | Regression evidence, kept deliberately. Single corner (`ff/125 °C/3.63 V`), `Overall: FAIL`. Documents the issue-#52 railed branch: `ncross_su=3`, core+injector railed at 3.48 V against 1.17 V on the bare-core control, `isup_dut` 542 µA against a 50 µA budget. Its `dvref=2.31 V` is the signature of that failure, **not** an injector cost — do not quote it. |
| `20260803-144658-4226657` | Same as above | Regression evidence, kept deliberately. Independent re-run of `-144531` with the hardened runner one commit later; identical numbers, which is what rules the harness change out as the cause. |
| `20260803-204236-f41373d` | **Shipped design: `amp_m_in=16` + injector WITH the issue-#52 railed-branch clamp `MNC`** | **Current record. `Overall: PASS`** — the first PASS this experiment has recorded. 12 corners, `ncross_su=1` at every one, `itrav_min` ≥ 6.4 nA, `isup_dut` 24.2–39.1 µA against the < 50 µA Iq budget. **`dvref` worst case `+8.70 mV` at `ff/125 °C/3.63 V`** (range −0.14 … +8.70 mV) — this is the figure issue #11 subtracts. Supersedes `20260803-144658-4226657`. |

## What changed between the last two vintages

The two `-1445xx` records are not a harness problem and were not caused by the
injector. Driving `GDRV` low over-drives the amplifier tail (the tail comes
from the core's `MPAMP`, whose gate *is* `GDRV`); the amplifier's folding node
`PN` collapses toward `VSS`; `MN4` falls into deep triode while `MN3` does not;
and the output current of `design/error_amp.sch` changes **sign**. The core+amp
loop therefore has a genuine second stable equilibrium at `GDRV ≈ 0.78 V` with
`VOUT` railed near the supply.

The evidence that it is the core+amp loop and not the injector is in the
current record itself: `ncross_bare`, measured on the **bare-core control
instance with no injector attached**, reads `3` at `tt`, `ss` and `ff` /
125 °C / 3.63 V while `ncross_su` reads `1` at all twelve corners. The gap
between those two numbers is exactly what `MNC` in
`design/startup_injector.sch` contributes.

## Reading `Supersedes` here

`Supersedes` alone does not read cleanly for this slug — `-114600` and
`-114658` are a concurrent pair that correct nothing, and `-124600`'s
`Supersedes` field names only one of the two. `sim/startup-stability/experiment.json`
carries the full record-chain note; this table is the short form.
