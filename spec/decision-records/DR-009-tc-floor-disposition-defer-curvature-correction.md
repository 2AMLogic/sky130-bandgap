# DR-009: Temp-coefficient floor above the ratified `< 50 ppm/°C` row — disposition (proposed, NOT ratified)

- **Status**: **proposed**. Ratification occurs via the operator's approval
  of the PR this record ships in
  (2AMLogic/2am#357, 2026-08-19 standing policy: canary spec/DR
  ratification-via-PR — a Builder drafts the record on the evidence, and the
  operator's PR review/approval is the ratification act). Not ratified by
  this Builder.
- **Date**: 2026-08-19 (drafted); proposed disposition.
- **Decided by**: proposed by a Loom Builder agent (issue #179); pending
  operator ruling.
- **Relates to**: [DR-005](DR-005-ratify-target-spec.md) (ratifies the
  `< 50 ppm/°C` box-method row this record disposes of), issue #46 (root
  cause), issue #178 / PR #193 (the sizing re-derivation that produced the
  current, exhausted floor), issue #179 (source operator question).

## Context

DR-005 ratified the temp-coefficient row at `< 50 ppm/°C` (box method),
stretch `< 20 ppm/°C (curvature correction)`, explicitly at gf180-bandgap
parity. Issue #46 (2026-08-03) root-caused a persistent floor: sky130's
substrate PNPs carry `nf = 1.028` (small device) vs `1.000` (large device),
putting ~18.1 mV of the 62.3 mV ΔVBE at 27 °C on a fixed fraction of a CTAT
quantity rather than true PTAT — a shortfall that grows with temperature and
that no `R2/R1` ratio choice cancels.

Issue #178 (PR #193, merged 2026-08-17) re-derived the core sizing against
the current, ratified accuracy row and the chained-array resistor model
(closing an unrelated modelling error that had inflated the previously
recorded floor). The result, at `n_r2=51` — the only integer that clears
DR-005's accuracy row at all 45 corners — is:

| representation | box TC | corners | binding | record |
|---|---|---|---|---|
| schematic | **142.4–159.0 ppm/°C** | 45/45 FAIL | `fs` | `sim/output-voltage-tc/records/20260817-015751-13476b7.md` |
| extracted (post-layout) | **167.9–186.9 ppm/°C** | 15/15 FAIL | `fs` | `sim/output-voltage-tc-post-layout/records/20260817-020357-13476b7.md` |

This is ~2.8–3.7× the ratified row, and the `R2/R1` ratio lever is now
exhausted: `n_r2=50` fails the *accuracy* row (`vref_min` ~1.3 mV under
floor at every corner) and `n_r2=52` fails it too (`vref_max` over ceiling
at 6/15 process/supply points). Issue #179 asked which of three paths the
block takes now that this is a measured, non-hypothetical floor rather than
a hypothetical one.

## Decision

**Recommend Option 3: accept item 5 (temp coefficient) stays FAIL against
the ratified `< 50 ppm/°C` row, disclose the gap honestly in `README.md`
and `design/block-characterization-report.md`, and defer curvature
correction to a later milestone.** The ratified row itself is **not**
amended by this record — DR-005 stands as ratified, in full, including its
gf180-parity rationale.

This record does **not** propose scoping curvature correction now (Option
1) and does **not** propose revising the ratified row (Option 2). See
Consequences for what each of those would require if the operator instead
rules for them.

## Alternatives considered

- **Option 1 — scope curvature correction as a new design program now.**
  DR-005's own stretch column (`< 20 ppm/°C (curvature correction)`)
  anticipates the technique, and it is the only lever left that could close
  the ~3× gap without touching the ratified spec. Not recommended *yet*:
  it is a new sub-block (a device-level PTAT-curvature-cancellation
  addition, not a resistor re-null), and it reopens layout, DRC/LVS, area
  (DR-007), PSRR (DR-008), and the entire post-layout suite — a multi-issue
  program. The block currently has other ratified rows still failing on
  fresher evidence than this one (output accuracy, rows 1a/1b of
  `design/block-characterization-report.md`, and the Monte Carlo yield
  collapse, row 1c/#180) that are *closer* to the ratified line and do not
  require a new sub-block. Committing to a substantial new design program
  for item 5 ahead of those is a sequencing call, not something this record
  should make unilaterally. If the operator wants Option 1, it should be
  scoped as follow-up issue(s) by Curator/Champion, not started here.
- **Option 2 — revisit the TC row via a new decision record.** Rejected on
  the evidence, not merely deferred. The gf180-bandgap sibling **currently
  passes the identical row** — `gf180-bandgap/sim/output-voltage-tc/records/
  20260815-020700-40321ca.md`, 81/81 PASS, `tc_ppm` 13.56–29.84 ppm/°C,
  measured 2026-08-15 — reached from a *worse* starting point (63/81
  corners failing, worst 90.5 ppm/°C) with **no topology change and no
  curvature correction**, only a corner-swept minimax re-null of the
  CTAT-leg resistor (`gf180-bandgap/design/bandgap_core.sch`, "R1
  RE-NULLING (issue #96)"). That is direct, dated evidence that a bandgap
  core of this same topology can clear `< 50 ppm/°C` on a sibling PDK
  without curvature correction — so the ratified target is not
  demonstrated to be unreachable in principle; it is unreached by
  *sky130's* current device menu and sizing lever (the `nf` mismatch #46
  root-caused, and the `R2/R1` ratio lever DR-005's own accuracy row now
  exhausts). Moving sky130's row to match its own floor would directly
  break the parity claim DR-005 built the row on ("same block, two PDKs is
  the portability proof") without a comparable device-level argument for
  *why* sky130 cannot reach it — CLAUDE.md's governing rule ("agents do not
  relax the ratified spec to make results pass") applies squarely here:
  the spec is not shown to be wrong, only unreached by this design so far.
- **Silently ship the FAIL, or round it toward the target.** Rejected —
  `design/block-characterization-report.md`'s own coverage-honesty rule and
  CLAUDE.md both require a FAIL be reported as FAIL, with its number.
  Already the case in both cited docs pre-#178 (item 5, rows 3a/3b); this
  record's only document change is refreshing the *numbers* to the
  post-#178 floor cited above, not the verdict, which was already FAIL.

## Spec lines affected

None. DR-005's target-spec table row (`Temp coefficient (−40…125 °C) | < 50
ppm/°C (box method) | < 20 ppm/°C (curvature correction)`) is unchanged and
remains ratified as-is. No row in `README.md`'s "Target specification"
table is edited by this record.

## Consequences

- **If ratified as proposed (Option 3):** item 5 remains disclosed FAIL —
  `README.md` and `design/block-characterization-report.md` carry the
  refreshed 142.4–159.0 ppm/°C (schematic) / 167.9–186.9 ppm/°C (extracted)
  numbers (this record's companion doc update, sourced from the two
  records above; the report's table rows 3a/3b themselves are left for
  issue #181's full roll-up regeneration, per that report's own §0
  freshness rule — this record only refreshes the narrative disclosure
  text in `README.md`, which is not reserved to another issue).
  Curvature correction (Option 1) remains available as later, deliberately
  deferred work — not foreclosed by this ruling, just not started now.
  No T1/bronze grant is implied or requested by this record either way.
- **If the operator instead rules Option 1:** this record's recommendation
  is overridden; Curator/Champion should scope the curvature-correction
  program as new issue(s) (device-level PTAT-curvature addition, plus the
  full re-verification chain: layout, DRC/LVS, area, PSRR, post-layout,
  echoing DR-008's Option B cost pattern for scale). Nothing in this record
  blocks that path from being taken later.
- **If the operator instead rules Option 2:** a new decision record must
  explicitly address the gf180-parity break this record found — in
  particular whether gf180's row moves too (breaking parity a second way)
  or sky130 diverges from gf180 permanently (ending the "one block, two
  PDKs" portability claim for this row) — neither of which this record
  attempts to resolve, per CLAUDE.md reserving spec relaxation to a
  deliberate, evidenced ruling, not a default.
- **Either way**, the underlying device-level root cause (issue #46,
  `design/device-characterization-summary.md` §1) and the exhausted
  `R2/R1` lever (issue #178/#193) are unaffected by this record and do not
  need re-investigation to act on this disposition.
