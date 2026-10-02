# DR-011: Startup injector PSRR fix (issue #306) — resize-only approaches empirically closed; no spec change

- **Status**: proposed (investigation disposition, not a spec change — DR-006's
  `>= 60 dB` DC–1 kHz `psrr_band_min` floor is untouched and not relaxed).
- **Date**: 2026-10-02.
- **Decided by**: Loom Builder agent (issue #306), proposing per CLAUDE.md's
  instruction that agents propose but do not unilaterally ratify a spec
  change — there is no spec change proposed here, but this record documents
  why the issue's own "or, if infeasible, a decision record" clause applies.

## Context

Issue #300 confirmed the DC–1 kHz PSRR collapse `sim/psrr-dc-with-injector`
measures (FAIL 24/45, worst `24.78 dB` at `ff, 125 degC, 3.63 V` against
DR-006's 60 dB floor) is a property of `design/startup_injector.sch`, not of
`klt extract --parasitics`. Issue #306 asked for (1) measurement-based
identification of which of the injector's six devices dominates, and (2) a
circuit fix that clears the floor across the full 45-corner matrix, re-verified
against `sim/startup-stability` and `sim/startup-time-post-layout`.

## Part 1 — isolation (settled, measured)

`sim/psrr-injector-attribution/` (new bench, this issue) cuts one
GDRV-touching device branch at a time from the exact netlist snapshot the
cited FAIL record measured, across the full 45-corner matrix (225 ngspice
points). Record `20261002-070506-29da08e`:

- At the binding corner (`ff, 125 degC, 3.63 V`): `base` 24.78 dB,
  `ref_open` (`MPC1`/`MPC2` cut) 67.07 dB, `inj_open` (`MNI` cut) 54.36 dB,
  `clamp_open` (`MNC` cut) 24.78 dB (negligible). Cutting the reference stack
  alone recovers to within 1.3 dB of the bare-core ceiling (68.4 dB);
  cutting `MNI` alone does not even clear the floor.
- Across the matrix, `MPC1`/`MPC2` is confirmed as the dominant, measured
  contributor at the large majority of corners. The record's own
  self-consistency checks FAIL at exactly two corners
  (`ff, 125 degC, 3.30 V` and `sf, 125 degC, 3.63 V`), where `ref_open`'s and
  `inj_open`'s recoveries are within ~1 dB of each other (both branches
  contribute comparably there) rather than `ref_open` strictly dominating —
  a real, measured nuance, not a methodology failure.
- `MNC` is not a contributor anywhere (confirmed negligible at every
  corner).

**This settles AC1**: the dominant contributor is `MPC1`/`MPC2`, identified
by measurement, not corner-signature inference.

## Part 2 — fix attempts, and why resize-only approaches are now closed

Three resize candidates were built and measured against the full 45-corner
`sim/psrr-dc-with-injector` matrix and (for the first two, see below)
`sim/startup-stability`:

1. **Extend the reference stack from two-high (`MPC1`/`MPC2`) to three-high
   (`+ MPC3`, same unit device), `MNI` unchanged.** `sim/psrr-dc-with-injector`
   improves from FAIL 24/45 (worst 24.78 dB) to FAIL 18/45 (worst 30.35 dB at
   `sf, -40 degC, 3.63 V`) — a real, substantial improvement, but a *different*
   corner signature: the fix fully closes the original hot-corner failure
   (`ff`/`sf` at 125 degC now PASS 67–69 dB) but uncovers a *new* residual at
   cold/room corners. A follow-up isolation at that new worst corner (same
   cut-one-branch method, hand-run against this candidate's netlist) found
   `inj_open` (cut `MNI`, 3-high stack otherwise intact) alone recovers to
   68.35 dB — i.e. with the reference stack already extended, `MNI`'s own
   residual GDRV conductance is now the dominant term at cold corners. A
   further four-high stack (`MPC1..4`) was tried at the same corner and gave
   an unchanged 30.32 dB — confirming more series reference stages do **not**
   help once `MNI` is the dominant term, so this path is closed independent
   of stack height.
2. **Resize `MNI`** (the only remaining device with a measured cold-corner
   contribution), tried at three points:
   - `L=20, W=4` (100x lower W/L than stock `L=0.5, W=10`): clears
     `sim/psrr-dc-with-injector` 45/45 (worst 67.14 dB), but
     `sim/startup-stability`'s DC sweep times out (`--timeout 600`) at 44/45
     corners.
   - `L=5, W=10` (10x lower W/L): also clears `sim/psrr-dc-with-injector`
     45/45 (worst 67.14 dB). `sim/startup-stability` again times out at
     44/45 corners under the harness's normal concurrency; the one corner
     that did complete passed with `itrav_min` within 4% of its required
     floor (`1.04e-9 A` vs. the `1e-9 A` minimum) — razor-thin, not a
     comfortable margin.
   - `L=2, W=10` (4x lower W/L, the gentlest resize tried): clears the single
     worst `sim/psrr-dc-with-injector` corner tested (64.19 dB at
     `sf, -40 degC, 3.63 V`) and converges normally (no timeout) at the
     `startup-stability` corners spot-checked in isolation — **except**
     `ss, 125 degC, 3.63 V`, where `itrav_min` measured `2.82e-10 A`,
     **below** the `1e-9 A` floor (the stock design's own baseline record at
     this corner reads `2.85e-7 A`, i.e. this resize costs ~1000x of margin).
     Confirmed via a standalone, uncontended single-corner probe — not a
     host-load artifact.

   Every tested `MNI` resize that clears PSRR either breaks DC-sweep
   convergence outright or demonstrably erodes `startup-stability`'s own
   margin floor below the ratified minimum at at least one corner. This is
   exactly the trade-off issue #306 itself names as the hard constraint:
   "starving that stack is exactly what would stop the injector working."
3. **The three-high-stack-ONLY change (option 1), re-verified against
   `sim/startup-stability` with `MNI` completely untouched**, was expected to
   be risk-free (bit-identical `MNI` to the always-passing baseline). A clean,
   uncontended full-matrix run instead found the opposite problem from
   option 2: most corners did **not** time out from circuit margin, but the
   DC sweep needed `gmin` homotopy stepping at nearly every one of the
   250 sweep points at the colder corners (observed directly in the raw
   ngspice log for `tt, -40 degC, 2.97 V`), making the sweep's per-corner
   wall-clock cost far higher than the stock two-high design's and preventing
   a conclusive pass/fail classification for most corners within the time
   available to this investigation. The one corner that did complete cleanly
   (`tt, 27 degC, 3.63 V`) passed with healthy margin (`itrav_min = 9.47e-9 A`,
   9.4x the floor), but this is not sufficient evidence to certify the
   regression-free claim across the full matrix.

## Decision

No circuit change lands in this increment. `design/startup_injector.sch` is
unchanged; DR-006's 60 dB floor is unchanged and not relaxed.

What lands: `sim/psrr-injector-attribution/` (the isolation bench and its
measured record), satisfying issue #306's first acceptance criterion, and
this record documenting why a simple device-resize fix is not responsibly
landable yet. The remaining work — a fix for row 4d/4b (schematic and
post-layout PSRR with the injector attached) that does not erode
`startup-stability`'s margin or blow past practical DC-sweep convergence
time — continues in follow-up issue #315.

## Alternatives considered

- **Land the three-high-stack-only change anyway**, trading an
  unverified-but-plausible `startup-stability` regression risk for partial
  PSRR progress (FAIL 24/45 -> FAIL 18/45). Rejected: `sim/startup-stability`
  is itself a ratified claim (spec/topology-survey.md's "self-starting,
  < 1 ms" row) and this repo's own convention (`CLAUDE.md`: "no claim without
  a testbench") does not allow landing a design change next to a regression
  check that could not be run to a conclusion.
- **Raise `sim/startup-stability`'s per-corner `--timeout`** (e.g. to 3600 s)
  and re-run the three-high-stack-only candidate to a clean verdict. Not
  rejected outright — this is the most promising near-term path and is
  recorded as the first task for follow-up issue #315 — but it was not
  completed in this session's compute budget (each corner's DC sweep, once
  `gmin`-stepping-bound, can take many multiples of the stock design's
  per-corner cost; a full 45-corner confirmation at a safely longer timeout
  is itself several-hour-class compute this investigation could not absorb
  on top of what had already run).
- **A non-resize topology** (e.g. a replica-bias reference decoupled from
  `MNI`'s eviction-current path, or a cascode that raises `MNI`'s off-state
  output impedance without touching its strong-inversion drive) — plausible
  in principle (it would let `MNI`'s eviction current stay untouched while
  independently reducing its GDRV-loading conductance), not attempted here:
  it is a larger design change than a single-PR increment, and belongs in
  follow-up issue #315 once the stack-only candidate's `startup-stability`
  convergence question (the "raise timeout" item above) is resolved one way
  or the other.
- **Relax DR-006's 60 dB floor** — explicitly rejected per CLAUDE.md and the
  issue's own text; not seriously considered.

## Spec lines affected

None. DR-006 (`README.md`'s PSRR row, `>= 60 dB` DC–1 kHz `psrr_band_min`)
is unchanged.

## Consequences

- Issue #306 stays open; follow-up issue #315
  tracks: (a) re-running the three-high-stack-only candidate's
  `sim/startup-stability` regression at a longer per-corner timeout to get a
  conclusive verdict, (b) if that fails, designing a non-resize fix for
  `MNI`'s residual conductance, and (c) the layout cycle (DRC/LVS,
  `sim/psrr-dc-post-layout`, `sim/line-regulation-post-layout`,
  `sim/startup-time-post-layout` against a new extraction, report rows
  4b/5c, `signoff/regenerate.sh`) that was already out of scope for a
  single-PR circuit fix even before this investigation.
- `sim/psrr-injector-attribution/`'s bench and record stand as permanent,
  reusable evidence for whichever fix eventually lands: any future candidate
  can be measured against the same five-variant cut-one-branch method this
  record establishes.
- `design/block-characterization-report.md` row 4d is **not** updated in
  this increment (no new record exists for it — the committed schematic is
  unchanged) and continues to cite `20260923-124813-af9ff1e.md`'s FAIL
  24/45 as the current state of the row.
