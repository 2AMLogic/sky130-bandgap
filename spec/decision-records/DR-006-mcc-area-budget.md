# DR-006: Relax the Area budget to accommodate a drawn `MCC` compensation cap

- **Status**: proposed (input to issue #62's AC4 closure; not itself a ratification)
- **Date**: 2026-08-11
- **Decided by**: Loom agent (issue #62), drafting the operator's own
  2026-08-11 ruling on #62 into a `spec/` proposal for the operator to
  accept, amend, or reject by comment on #62 -- the same "propose, don't
  self-ratify" pattern DR-004's amendments used against #1, per `CLAUDE.md`
  ("agents do not relax the ratified spec to make results pass").

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
| Current composed `bandgap-core` bbox (`layout/bandgap-core/reports/LATEST/record.md`) | 45,968 um^2 |
| Ratified Area budget (DR-005, README.md "Target specification") | 50,000 um^2 (0.05 mm^2) |
| Remaining margin before `MCC` | 4,032 um^2 (~8%) |
| `MCC`'s own analytic footprint (`mult=16 x W=30um x L=20um`) | 9,600 um^2 |
| `MCC` projected **drawn** footprint, at this design's own measured analytic-to-drawn overhead ratio (2.17x -- 21,215 um^2 analytic vs. 45,968 um^2 composed today, `layout/matching-plan.md` Section 6) | ~20,800 um^2 |
| Projected composed bbox with `MCC` drawn | ~66,800 um^2 |
| Projected overrun vs. the current 50,000 um^2 budget | ~34% |

This is a projection from this design's own measured drawn/analytic ratio,
not yet a measured drawn `MCC` block -- the actual number will be recorded
once a follow-on increment draws it (see "Consequences" below) and this
record's proposed value re-checked against the real figure at that time.

## Decision (proposed)

**Relax the README "Target specification" Area row from `< 0.05 mm²` to
`< 0.07 mm²` (70,000 um^2)**, keeping ~3,200 um^2 (~5%) of margin above the
~66,800 um^2 projection above -- enough to absorb `MCC`'s real drawn
overhead once measured, without immediately reopening this same question at
a fresh floor. `design/device-characterization-summary.md`'s already-flagged
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
  future path that would let a later DR revert this one.
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
| Area | `< 0.05 mm²` -> `< 0.07 mm²` (Target column only; Stretch column unaffected, per DR-001 it has no value) |

## Consequences

- **Gates the next `MCC`-drawing increment.** `layout/bin/gen_bandgap_routed.py`'s
  `budget_um2` constant (currently hard-coded to the ratified 50,000 um^2)
  is not changed by this record itself -- per `CLAUDE.md`, a repo-side gate
  tracks the ratified spec value, it does not lead it. Once this record (or
  an operator amendment to it) is ratified, a follow-on increment updates
  `budget_um2` to match, draws `MCC` as a `pfet` MOS-cap block, and
  re-verifies DRC/extract/`klt lvs` end to end -- expected to close AC4
  (`mismatch_count: 0`) if the extracted netlist's shape is otherwise
  unchanged.
- **No other spec-review row is touched.** DR-005's remaining rows
  (accuracy, trim, temp coefficient, PSRR, supply, Iq, startup) are
  unaffected; this record proposes exactly one line.
- **If declined**, issue #62's AC4 stays open pending either
  2AMLogic/klayout-tools#775 landing (unblocking the zero-footprint MIM
  path) or a redesign of the compensation network (the deferred
  alternative above).
