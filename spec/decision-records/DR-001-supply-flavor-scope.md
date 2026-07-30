# DR-001: Supply/flavor scope — 3.3 V primary only for wave 1

- **Status**: proposed (input to spec ratification, see #1)
- **Date**: 2026-07-30
- **Decided by**: Loom agent (issue #7), citing the topology survey (#3) and
  the gf180-bandgap port-parity precedent; narrows flavor scope only — does
  not itself constitute #1's formal spec ratification.

## Context

The DRAFT spec table in `README.md` ("Target specification") conflates two
possible products under one table: a 1.20 V ±1% untrimmed reference on
3.3 V I/O (thick-oxide) devices at 3.3 V ±10% supply (the **Target**
column), and a sub-1 V Banba-style variant on the 1.8 V core (the
**Stretch** column). Every downstream design issue (#8 schematic entry, #9
error amp, #10 startup, #11 testbench suite, #13 trim network, #15
floorplan) either references this scope directly or implicitly assumes a
single core topology. Left unresolved, agents curating or building those
issues would each have to guess at scope independently.

The topology survey (#3 → `spec/topology-survey.md`) landed on `origin/main`
and evaluates five candidate topologies against every draft spec line. It
recommends **CMOS-amp Kuijk-style** (fallback Brokaw) for the 3.3 V primary,
and **Banba** (fallback Malcovati) for the 1.8 V stretch — and is explicit
that these are *structurally distinct* cores (voltage-mode divider vs.
current-mode resistor-summing), not one shared core with a swappable output
stage. The only things they share are the general sky130 device menu (the
fixed-geometry PNP unit array, `res_high_po` for ratio-critical legs) and
layout conventions — not a schematic.

Issue #1 (formal spec ratification) remains open and `loom:operator-only`:
per its delegation comment, Robb's ratification is required before layout
work locks to the spec, and #1's own body explicitly leaves open whether the
flavor-scope call is folded into that ratification or delegated to this
record. This record is the input that settles it for #1 to reference.

Port-parity precedent: this repo's README states the spec deliberately
mirrors gf180-bandgap (the sibling first canary). gf180-bandgap resolved the
identical question — 3.3 V-only vs. dual 3.3 V/5 V flavor — in its own
`spec/decision-records/0001-supply-voltage-scope.md` (2026-07-29): 3.3 V-only
for wave 1, the 5 V stretch flavor explicitly deferred to a future,
separately-scoped block.

## Decision

**Single 3.3 V flavor for wave 1.** This block targets the 1.20 V ±1%
untrimmed reference on 3.3 V I/O (thick-oxide) devices at 3.3 V ±10% supply
exclusively. The 1.8 V sub-bandgap (Banba-style) variant in the README's
Stretch column is explicitly **deferred to a separate, later-scoped block**
— not designed, not partially designed, and not architected-for in wave 1.

This decision does not amend any Target-column value; it scopes wave 1 to
the Target column and defers the Stretch column in full. It narrows flavor
scope only — it does not constitute #1's formal ratification of the
Target-column values themselves.

## Alternatives considered

- **Dual flavor from wave 1.** Rejected. The survey shows the two
  recommended cores are structurally distinct topologies, not a shared core
  with a variant output stage — so dual-flavor scope means building two
  independent designs (two schematics, two offset budgets, two startup
  analyses, two floorplans, two full PVT-testbench suites) rather than one
  core plus a variant. That roughly doubles wave-1 scope across #8, #9,
  #10, #11, #13, #15, working against the canary's purpose (fastest path to
  measured silicon, tool-forcing-function proof) and against the README's
  own framing of the 1.8 V line as "Stretch," not committed scope.
- **Defer-with-placeholder** (design the 3.3 V primary now, but architect
  the core so a 1.8 V variant isn't foreclosed later). Rejected as an
  explicit wave-1 commitment. Because the two flavors use different core
  topologies entirely — not a shared core with a swappable output stage —
  there is no meaningful forward-compatibility architecture to build now; a
  future 1.8 V block would be closer to a new design than an extension of
  this one. Stating this explicitly (rather than gesturing at unspecified
  future-proofing) prevents wave 1 from quietly absorbing hidden dual-flavor
  scope under the guise of "keeping options open."
- **Single 3.3 V flavor for wave 1, 1.8 V deferred to a separate future
  block (this decision).** Accepted. Matches the README's own Target/Stretch
  framing, matches the survey's structurally-distinct-cores finding, and
  matches the port-parity precedent already set by gf180-bandgap's identical
  scope decision.

## Spec lines affected

| README target-spec row | Wave-1 scope |
|---|---|
| Output reference | Target column only (1.20 V ±1% untrimmed, 3.3 V I/O devices). Stretch ("sub-1V Banba variant on 1.8 V core") is deferred — not designed or simulated in wave 1. |
| Temp coefficient | Target column only (< 50 ppm/°C). Stretch (< 20 ppm/°C) deferred with the 1.8 V variant. |
| PSRR @ DC | Target column only (> 60 dB). Stretch (> 70 dB) deferred. |
| Supply | Target column only (3.3 V ±10%). Stretch (1.8 V variant) deferred. |
| Iq | Target column only (< 50 µA). Stretch (< 20 µA) deferred. |
| Area | Target column only (< 0.05 mm²); Stretch has no value (`—`) — unaffected. |
| Startup | Target column only (self-starting, < 1 ms); Stretch has no value (`—`) — unaffected. |

No Target-column value is amended by this decision. The entire Stretch
column is deferred to a future, separately-scoped block. Formal ratification
of the Target-column values remains #1's responsibility; this record should
be cited from #1 for the Supply and Output-reference rows rather than
re-litigated there.

## Consequences

- **Unlocks scope for #8** (schematic entry): a single 3.3 V schematic using
  the survey's recommended Kuijk-style core (fallback Brokaw) — not a
  dual-flavor schematic set. #8 remains `loom:blocked` pending its own
  curation, but this decision resolves the scope question that curation
  needs answered.
- **Scopes #9** (error-amp offset budget): one offset budget against the
  Kuijk `R2/R1` divider-gain term, not two independent budgets across two
  topologies.
- **Scopes #10** (startup/degenerate-state verification): one analysis for
  the Kuijk-style amp-plus-mirror loop, not two.
- **Scopes #11** (testbench suite): one PVT-corner testbench set at
  3.3 V ±10%, not a second supply-range sweep at 1.8 V.
- **Scopes #13** (trim network): scoping proceeds against the single
  3.3 V / 1.20 V target only.
- **Scopes #15** (floorplan/matching plan): one PNP-array + resistor +
  amplifier floorplan, not two.
- **Does not unblock #1**: formal spec ratification still requires Robb's
  ruling on all seven Target-column rows plus the port-parity
  confirmation/waiver. This record answers #1's open question of whether
  the flavor-scope call is folded into that ratification or delegated to
  this record — **delegated to this record.** #1 should cite this DR for
  the Supply and Output-reference rows rather than re-decide flavor scope.
- **Port-parity**: matches gf180-bandgap's own resolution (3.3 V-only for
  wave 1, alternate-supply stretch deferred) — no divergence to record.
- **Defers, does not drop**: the 1.8 V sub-bandgap variant remains a valid
  future block, to be scoped as its own separate issue and decision record
  if and when pursued. This record commits to nothing about its timing.
