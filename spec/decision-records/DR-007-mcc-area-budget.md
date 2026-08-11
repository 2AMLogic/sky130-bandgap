# DR-007: Relax the Area budget to accommodate a drawn `MCC` compensation cap

- **Status**: **ratified 2026-08-11** (operator, issue #62). Supersedes DR-005's Area row (`< 0.05 mm²`); the Target-specification Area row is now `< 0.08 mm²`.
- **Date**: 2026-08-11
- **Decided by**: operator (spec-ratification authority), issue #62 — accepting the fallback path the operator's own 2026-08-11 #62 ruling pre-authorized (realize `MCC` in-plane as a MOS cap, since the `cap_mim` overlay was found tooling-infeasible — klayout-tools#775 — and relax the Area budget by decision record rather than silently exceed it). Drafted by Loom agent as the "propose, don't self-ratify" record; ratified here by the operator.
- **Numbering note**: filed as `DR-006` when first proposed (issue #62's
  thirtieth increment, PR #124); renumbered to `DR-007` in the thirty-first
  increment after a concurrently-merged, unrelated record
  (`DR-006-psrr-frequency-qualification.md`, issue #123/PR #125) claimed
  `DR-006` first at merge time. Content unchanged by the rename.

## Context

`klt lvs` on the composed, routed `bandgap-core` layout has exactly one
disclosed mismatch left (`mismatch_count: 1`, `MMCC`): `MCC`, the error
amp's ~29 pF Miller compensation cap
(`design/error_amp.sch`, `sky130_fd_pr__pfet_g5v0d10v5`, `mult=16`,
`W=30 um`, `L=20 um`), is not drawn in the layout at all. The operator
ruled (2026-08-11, on issue #62) that this is **not** a waivable LVS
exception: `MCC` sets the amp's dominant pole, and the schematic's own
45-PVT-corner loop-stability testbench (`sim/error-amp-loop/`) assumes it
exists, so an as-fabricated block without it would be a different,
uncompensated circuit than the one that passed sim. `MCC` must be realized
in the layout for the block to be genuinely LVS-clean / T1-ready.

The operator's ruling's primary path -- realize `MCC` as a `cap_mim`
MIM-cap overlay above the existing layout, at ~zero incremental composed
footprint -- was checked and found infeasible with today's tooling, not
area: `layout/matching-plan.md` Section 7bb reproduces (empirically,
against two `klt` pins) that sky130's `cap_mim`/`cap_mim_m4` device
recognition cannot wire a two-terminal capacitor's top plate out to
ordinary routing metal without either an isolated terminal or a false short
between the two plates, filed as 2AMLogic/klayout-tools#775. The ruling's
explicit fallback governs: draw `MCC` in-plane as the MOS cap it already is
in the schematic, and, since that draws well over the current budget,
propose a decision record relaxing it rather than silently exceeding it.

## The measured trade

| Item | Area |
|---|---|
| Prior composed `bandgap-core` bbox, `MCC` undrawn (`layout/bandgap-core/reports/20260806-094830-90ef982/record.md`) | 45,968 um^2 |
| Ratified Area budget (DR-005, README.md "Target specification") | 50,000 um^2 (0.05 mm^2) |
| Remaining margin before `MCC` | 4,032 um^2 (~8%) |
| `MCC`'s own analytic footprint (`mult=16 x W=30um x L=20um`) | 9,600 um^2 |
| **`MCC` drawn footprint, measured** (issue #62's thirty-first increment, `amp_cc` block: `layout/bandgap-core/reports/20260811-220511-6814b56/record.md`) | **73,989 - 45,968 = 28,021 um^2** |
| **Composed bbox with `MCC` drawn, measured** | **73,989 um^2** |
| Overrun vs. the current 50,000 um^2 budget, measured | **48.0%** |

This record originally carried a *projection* (~66,800 um^2, from this
design's own average analytic-to-drawn overhead ratio) rather than a
measured number. The thirty-first increment drew `MCC` and measured it
directly: the real composed bbox (73,989 um^2) is higher than that
projection -- the average 2.17x ratio understates `amp_cc`'s own guard
ring, comb/spine bussing and row-3 placement-channel cost specifically
(a single, non-matched-pair block placed in its own row pays a full
`ROW_MARGIN_UM` channel on both sides, which the average across ten
already-packed blocks does not reflect). `klt lvs` on this drawn cell
reports `mismatch_count: 0` -- the LVS-comparator side of AC4 is
satisfied; only this record's own budget ratification is outstanding.

## Decision (proposed)

**Relax the README "Target specification" Area row from `< 0.05 mm²` to
`< 0.08 mm²` (80,000 um^2)**, keeping ~6,000 um^2 (~8%) of margin above the
measured 73,989 um^2 figure above -- enough to absorb ordinary
re-measurement noise (a `klt`/PDK pin bump, a router re-run that finds a
different tie-break) without immediately reopening this same question at a
fresh floor. Revised from this record's own first draft (`< 0.07 mm²`,
70,000 um^2), which was sized against the pre-measurement ~66,800 um^2
projection and does not hold the real 73,989 um^2 figure.
`design/device-characterization-summary.md`'s already-flagged
`MPOUT`/`MPAMP` up-sizing option is not included in this margin and would
need its own accounting if pursued later.

This decision, if accepted, would supersede DR-005's Area row (ratified
2026-08-11 as part of the overall target-spec ratification, at the
unchanged `< 0.05 mm²` draft value -- DR-005 did not itself revisit Area;
it inherited the draft value while amending the accuracy/trim rows).

## Alternatives considered

- **Retry the `cap_mim` MIM-cap overlay once klayout-tools#775 lands.**
  Preferred in principle (zero incremental footprint, no spec change
  needed) but not actionable today: #775 is filed, unmerged, and this
  issue's own history (`klayout-tools#559`/#583/#587, Sections 7u-7z) shows
  waiting on an unscoped upstream fix can stall AC4 for many increments.
  Not chosen as *this* record's decision, but not foreclosed either --
  Section 7bb's "Suggested next increment" keeps it open as a lower-cost
  future path that would let a later DR revert this one. **A second,
  independent obstacle found while drawing the MOS-cap fallback
  (`layout/matching-plan.md` Section 7cc, `gen_bandgap_routed.py`'s
  `MCC_MIM_INFEASIBLE_NOTE`)**: even once #775 lands, `klt lvs` has no
  device-class equivalence mechanism, and `reference.spice`'s `MMCC` card
  is a `pfet` transistor, not a capacitor model -- a drawn `cap_mim`
  overlay would extract under a different device class and cannot reach
  `mismatch_count: 0` against the *current* reference netlist on
  comparator grounds alone, independent of drawability. Reopening the
  MIM-cap path for real needs `reference.spice`'s `MMCC` card rewritten to
  a capacitor model too (a schematic-level device-type change to a closed,
  sim-verified cell), not just #775 landing.
- **Redesign the compensation smaller** (a smaller `Cc` plus a nulling
  resistor, the LDO's own topology) to shrink the ~29 pF closer to the
  current margin instead of growing the budget. The operator's own ruling
  flagged this as "the principled long-term fix if the cap is
  over-designed" but explicitly deferred it: it reopens #9's offset budget
  and the 45-corner loop-stability verification, and touches a closed cell
  -- out of scope for gating T1. Recorded here as a future optimization for
  the amp designer, not adopted by this record.
- **Accept the `mismatch_count: 1` gap permanently** (treat the undrawn
  `MCC` as a documented, accepted deviation rather than a defect). Rejected
  outright by the operator's 2026-08-11 ruling: `MCC` is stability-critical,
  not a waivable tier exception, so the block is not T1-ready without it
  drawn.
- **Shrink another block to compensate**, holding the 50,000 um^2 budget
  fixed. Not pursued in this record -- the operator's ruling named it as a
  possible design-level trade but did not direct it, and no specific block
  has ~20,800 um^2 of give without its own re-verification (every other
  block's sizing is itself ratified by a schematic parameter or a DR, e.g.
  DR-003's resistor-array sizing). Left open as an alternative the operator
  can direct instead of accepting this record's proposed value.

## Spec lines affected

| README target-spec row | Proposed change |
|---|---|
| Area | `< 0.05 mm²` -> `< 0.08 mm²` (Target column only; Stretch column unaffected, per DR-001 it has no value) |

## Consequences

- **`MCC` is already drawn and LVS-verified; only this record's ratification
  is outstanding.** Unlike this record's first draft (written before the
  drawing increment), the follow-on work this record originally described
  as a *future* consequence has already landed:
  `layout/bin/gen_bandgap_routed.py` now composes an `amp_cc` block
  (a `pfet` MOS-cap matching `design/error_amp.sch` exactly), and
  `klt lvs` on the resulting composed cell reports `mismatch_count: 0`
  against `reference.spice` -- the first time in issue #62's history.
  `gen_bandgap_routed.py`'s `budget_um2` constant is deliberately left at
  the current ratified 50,000 um^2: per `CLAUDE.md`, a repo-side gate
  tracks the ratified spec value, it does not lead it, so the flow's own
  `within_budget` gate condition correctly, honestly fails
  (`gen_bandgap_routed.py: FAILED gate conditions: within_budget`) until
  this record (or an operator amendment) is ratified. The only remaining
  step to a fully green flow run is a one-line follow-up bumping
  `budget_um2` to match this record's ratified value -- no further
  drawn-geometry change is expected.
- **No other spec-review row is touched.** DR-005's remaining rows
  (accuracy, trim, temp coefficient, PSRR, supply, Iq, startup) are
  unaffected; this record proposes exactly one line.
- **If declined**, issue #62's AC4 stays formally open (the flow's
  `within_budget` gate stays failing) even though `klt lvs` itself is
  already clean, pending either 2AMLogic/klayout-tools#775 landing
  *and* a `reference.spice` device-model change (unblocking the
  zero-footprint MIM path for real, per the updated "Alternatives
  considered" note above) or a redesign of the compensation network (the
  deferred alternative above).
