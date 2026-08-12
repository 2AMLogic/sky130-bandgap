# DR-008: PSRR DC–1 kHz floor — post-layout margin shortfall, proposed disposition (NOT ratified)

- **Status**: **proposed** — requires operator/Champion ratification before
  it changes anything. This record documents an investigation and lays out
  options; it does **not** by itself relax DR-006's `> 60 dB DC–1 kHz`
  target.
- **Date**: 2026-08-12
- **Decided by**: not yet decided — drafted by a Loom Builder agent (issue
  #140) per CLAUDE.md's instruction that agents propose but do not
  unilaterally ratify a spec relaxation.

## Context

`sim/psrr-dc-post-layout/records/20260812-011520-5df01bf` (issue #16/#139)
found that the routed, LVS-clean `bandgap-core` layout's extracted-netlist
`psrr_band_min` (the DC–1 kHz band floor DR-006 ratifies at `>= 60 dB`)
fails at 34 of 45 PVT corners, 58.27–62.55 dB measured, a tight
`-4.05 ± 0.36 dB` shift off the schematic-level baseline at every corner
regardless of process/temperature/supply (see that record's README for the
full finding). Issue #140 was filed to root-cause the shift and choose
between a routing fix and a schematic-level margin/spec change.

## What this record adds: the routing-fix path is empirically closed, not just judged infeasible

The originating README left the mechanism as an order-of-magnitude argument
from the extracted network's aggregate R/C totals (813 R + 151 C elements,
264.3 kΩ / 1.55 pF) and did not attribute the shift to a specific part of
that network. This investigation (issue #140) went further: it extracted
one real corner deck from the existing FAIL record and directly perturbed
the star-network resistor values in place (ngspice-only, no layout
regeneration needed to test the hypothesis), giving a fast, precise
sensitivity sweep instead of another blind layout iteration.

**Finding 1 — the dominant resistance is on the amplifier's own internal
nodes, not the VDD/VSS supply rails.** The extracted star network gives
every one of the 11 top-level pins (`D1`/`D2`/`GDRV`/`PN`/`TAIL`/`VA`/`VB`/
`VBQ`/`VDD`/`VOUT`/`VSS`) its own per-terminal fan-out resistors, plus a
much larger set of the same kind of resistor on ~200 anonymous internal
nets (`$10`, `$100`, ... — the amplifier's own gate/bias/mirror nodes).
Scaling only the 11 named pins' resistors to 10% of their extracted value
(a 10x reduction) moved the representative corner `tt_27c_3.30v`'s
`psrr_band_min` from 59.377 dB to only 59.449 dB (+0.07 dB) — supply-rail
IR drop is nearly irrelevant here. Scaling only the ~200 internal-node
resistors by the same 10x moved it to 61.405 dB (+2.03 dB) — almost the
entire effect. This contradicts the originating README's working
hypothesis (a fixed impedance "between the supply pins and the circuitry");
the impedance that matters sits inside the amplifier's own internal wiring,
not on the supply rails it measures.

**Finding 2 — a realistic, DRC-clean routing-width fix does not close the
gap.** `layout/bin/gen_bandgap_routed.py`'s `ROUTE_WIDTH_UM` (currently
0.5 µm) is the only lever the composer exposes over the whole design's
routing width uniformly. A prior (uncommitted) attempt at this issue raised
it to 0.65 µm (+30%) and regenerated the layout: `klt drc` stayed clean
(0 violations) and `klt lvs` stayed a clean match (11/11 nets, 16/16
devices), with **no change to the composed bbox area** (73,989 µm² before
and after — the routing width is not the area driver). That 30%-wider
network, replayed as a uniform 0.5/0.65 = 0.769x scale on every star-R in
the same real corner deck, moved the representative corner from 59.377 to
59.873 dB — **still 0.13 dB short of the 60 dB floor at the corner that
already had the least margin to make up**, and at the actual worst corner
(`sf_-40c_2.97v`, 58.27 dB baseline, needs +1.73 dB) the same 0.769x scale
only reached 58.77 dB, **1.23 dB short**.

**Finding 3 — even an unrealistic, non-physical routing improvement falls
short at the worst corner.** Scaling every star-R in the worst corner's
network (not just the width-affected fan-out set) down to 30% of its
extracted value — equivalent to roughly a >3x routing-width increase,
already well past what the composed cell's area/DRC headroom could
plausibly absorb — only reaches 59.86 dB, still under the floor. Isolating
just the internal-node resistors (leaving supply-pin resistors alone, an
upper bound on what routing alone could ever achieve since it ignores the
capacitive part of the network entirely) and taking the resistance to the
unphysical limit of zero shows the effect asymptoting around **60.3–60.5 dB
at the worst corner — a ceiling only ~0.3–0.5 dB above the floor**, using a
change that cannot be built (real copper/metal traces are never
zero-resistance). There is no finite, DRC-legal routing-width change that
reliably clears every corner with real margin; the theoretical ceiling
itself is too thin to trust across the 11 untested (mismatch/`ll`/`hh`)
corner axes this 45-point matrix does not even cover.

**Conclusion: this is not a routing bug to fix, it is a genuine, small,
structural post-layout PSRR-band cost of the drawn topology**, most likely
from RC loading (not resistance alone — the ceiling analysis above shows
resistance alone cannot explain the full gap either) on the amplifier's own
internal high-impedance nodes. A full per-net attribution (which specific
internal node's R+C pole/zero pair is responsible) was not pursued further
here — see Known gaps below — because it would not change the disposition:
the *routing* side of the fix (path 1 in issue #140) is closed regardless
of which specific net turns out to be the largest single contributor,
since even zeroing an entire *class* of parasitic (all internal-node
resistance) does not reliably clear the floor.

### A harness-fragility side finding (not itself evidence for or against the routing path)

The 0.65 µm regenerated layout also changed `klt extract --parasitics`'s
own pin-promotion behavior: `vsubs` (the implicit substrate net, already
present as an *internal* node in the 0.5 µm extraction) was promoted to an
explicit `.SUBCKT bandgap_core_routed` port, breaking
`sim/bin/post_layout_common.py`'s `build_core_wrapper()` fixed 11-pin
`core_port_order` assumption (`XCORE ...` calls the subckt with 11 actual
nodes against a 12-port formal list, ngspice reports "unknown subckt" and
every corner comes back `n/a` rather than measured). This was not
investigated further since Finding 2/3 above already rule out the width
change on electrical grounds regardless of the harness issue — but it is
worth recording so a future attempt at this same lever does not waste time
rediscovering it: raising `ROUTE_WIDTH_UM` is not a drop-in change even
setting the PSRR result aside.

## Decision

**Not made here.** Two dispositions are laid out for the operator/Champion
to choose between; this record does not choose one:

**Option A — amend DR-006's target-band floor to reflect the measured,
structural post-layout cost.** The schematic-level `psrr_band_min` range
was 62.65–66.73 dB (thin margin above 60 dB even before extraction, per the
originating README); post-layout the range is 58.27–62.55 dB. A floor
lowered to, e.g., `>= 57 dB DC–1 kHz` (leaving ~1.3 dB margin below the
worst observed corner, an admittedly ad hoc buffer, not derived from a
fresh corner sweep) would pass today's layout at all 45 corners. This is a
genuine spec relaxation and needs the same scrutiny DR-006 itself got
before ratification — in particular whether `>= 57 dB` is an acceptable
system-level PSRR floor for whatever downstream application wave 1 targets,
which is outside a Builder's authority to judge.

**Option B — invest in a schematic-level PSRR margin increase** (e.g.
raising the error amplifier's loop gain/bandwidth so post-layout parasitic
loading costs less rejection, or reducing the internal nodes' own
impedance sensitivity by design rather than by routing) **and keep DR-006's
`>= 60 dB` floor as-is.** This is real design work — likely a new
`design/error_amp.sch` revision plus a full re-run of every bench that
depends on the amplifier (loop stability, PSRR, line regulation, Iq,
output accuracy) — scoped as a follow-up issue, not something to attempt
inside this investigation.

Both options are legitimate; neither is free. Option A costs nothing in
design effort but weakens the ratified spec by exactly the margin this
layout is short. Option B preserves the spec as ratified but is an
open-ended amplifier redesign with its own re-verification cost across
every bench that touches the amp. The originating issue (#140) is being
routed to the operator with this record attached rather than resolved
either way by the Builder that investigated it.

## Alternatives considered

- **A routing-only fix (issue #140's path 1).** Investigated in depth and
  rejected on the evidence in "What this record adds" above — not
  infeasible in the sense of "hard," but empirically incapable of closing
  the gap at the worst corner even under generous, non-physical
  assumptions.
- **Silently accept the post-layout FAIL and move on.** Rejected: CLAUDE.md
  is explicit that "Spec changes go through `spec/` with a decision record
  — agents do not relax the ratified spec to make results pass," and a
  divergence must be "documented as a finding, not reconciled away" per
  issue #16's own framing. Doing nothing leaves a ratified spec line the
  current layout provably fails, with no record of why that's tolerated.

## Spec lines affected

None yet. If Option A is later ratified: `README.md`'s "Target
specification" table, `PSRR` row (currently `> 60 dB DC–1 kHz`, per
DR-006), and `spec/decision-records/DR-006-...`'s status would be marked
"superseded by DR-008" per this repo's decision-record convention (never
edited in place).

## Consequences

- **If Option A is ratified**: the post-layout PSRR-band FAIL record
  (`20260812-011520-5df01bf`) would need a superseding note (not a rewrite
  — `sim/` records are append-only) once the amended floor is in place,
  and `sim/psrr-dc-post-layout/` would need re-scoring against the new
  limit (no new simulation required — the existing corner data already has
  the measured values; only the pass/fail limit changes).
- **If Option B is chosen**: issue #140 stays open as a design-scope
  problem (amplifier PSRR margin increase) rather than a layout/spec
  problem, and a new issue should be filed scoping that redesign — this
  record's "Finding 1" (internal-node parasitic loading, not supply-rail
  IR drop, is the dominant mechanism) is a useful starting point for
  whoever designs that fix: the amplifier's own high-impedance internal
  nodes are the sensitive ones, not the VDD/VSS distribution.
- **If neither is ratified promptly**: the ratified spec continues to have
  a documented, unresolved FAIL against the current layout. That is the
  status quo already established by PR #139/issue #140's filing and is not
  made worse by this record — it is made more precise.

## Known gaps (not closed by this record)

- No per-net attribution of *which* internal node's R (and/or C) dominates
  the residual gap beyond the R-only ceiling shown in Finding 3 — a
  reduced-order model of the amplifier's loop with the extracted parasitics
  folded in, or a per-net zeroing sweep, would be needed to name the single
  worst offender. Not attempted here because the routing-path disposition
  does not depend on it (see Conclusion above).
- The R-only ceiling in Finding 3 (~60.3–60.5 dB at the worst corner) does
  not isolate the capacitive contribution's own sign/magnitude — an
  informal check (scaling all 151 star-C elements to 10% of their extracted
  value at the `tt_27c_3.30v` corner) moved `psrr_band_min` from 59.377 dB
  *down* to 58.739 dB, i.e. **less** capacitance made the measured PSRR
  *worse*, not better. That is counter to a simple single-pole-rolloff
  model and was not investigated further; it suggests the network's
  R and C terms interact (a genuine pole/zero pair, not two independent
  degradation mechanisms), which is exactly the kind of thing Option B's
  amplifier redesign would need to model properly and this record does not
  attempt to.
- Option A's specific proposed number (`>= 57 dB`) is illustrative, not
  derived from any fresh analysis beyond "clears the worst observed
  corner with a round-number buffer" — an operator ratifying Option A
  should treat the exact floor as open, not pre-decided by this record.
