# DR-008: PSRR DC–1 kHz floor — post-layout margin shortfall, proposed disposition (NOT ratified)

- **Status**: **ratified 2026-08-14 — Option B**. See "Ratification
  (2026-08-14)" at the end of this record for the operator's ruling and the
  evidence that closes it out. DR-006's `>= 60 dB DC–1 kHz` floor is
  unchanged and stands as ratified; this record's Option A (relaxing it) is
  rejected.
- **Date**: 2026-08-12 (investigation); ratified 2026-08-14.
- **Decided by**: operator ruling on issue #140 (2026-08-14), implemented by
  issue #170. Originally drafted by a Loom Builder agent (issue #140) per
  CLAUDE.md's instruction that agents propose but do not unilaterally ratify
  a spec relaxation.

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

## Addendum (2026-08-14): the routing-fix path is now closed on real-pipeline evidence too, not just the resistor-scaling proxy above

Per the operator's 2026-08-14 ruling on issue #140 ("unparked as
engineering, with a guardrail: if routing cannot recover the margin, do
NOT touch the ratified spec"), this addendum redid the `ROUTE_WIDTH_UM`
0.5 -> 0.65 µm experiment above through the REAL end-to-end harness
(`klt extract --parasitics` on the regenerated layout, translated,
simulated over the full 45-point matrix) rather than the resistor-scaling
proxy against the original FAIL record's network. Two findings:

**1. The harness-fragility side finding above is confirmed and root-caused
precisely, and fixed generically.** The 0.65 µm layout's `--parasitics`
extraction promotes the synthesized substrate net (`vsubs`) to an explicit
12th `.SUBCKT bandgap_core_routed` port (`... VSS vsubs`) that the 0.5 µm
layout's extraction does not carry (11 ports, no `vsubs`). After
`translate_extracted_netlist`'s existing blanket `vsubs` -> `VSS` text
substitution, that header reads `... VSS VSS` — a legal, if unusual, SPICE
subckt header (the same net name twice is not an error). The actual bug
was on the CALLER side: `sim/bin/post_layout_common.py`'s
`build_core_wrapper()` bound its `XCORE` call against a hardcoded 11-name
`core_port_order` tuple, so a 12-port header received only 11 positional
nodes — ngspice cannot resolve the call (reported as a "singular"/failed
subckt match rather than a clean "wrong argument count" message, which is
why the original side finding above described it only as "every corner
comes back n/a" rather than naming the exact mechanism). Fixed by having
`build_extracted_body()` parse the ACTUAL `.SUBCKT` header
(`parse_subckt_ports()`, new) from each run's own extraction instead of
assuming a fixed pin count, so the wrapper self-adapts to however many
ports a given layout's `--parasitics` pass promotes. Verified a no-op for
the current shipped (0.5 µm, 11-pin) layout: byte-identical `XCORE` call
across all seven `sim/*-post-layout/run_*.py --dry-run` outputs,
before/after the fix.

**2. With the port-count bug out of the way, the 0.65 µm layout's real
extracted network fails to converge at all, at every corner.** Every one
of the 45 corners' ngspice runs reports `Warning: singular matrix: check
node xbg.xcore.$195`, `Dynamic gmin stepping failed`, `True gmin stepping
failed`, `source stepping failed` — the DC operating-point solver cannot
find a bias point on this specific extracted network, and the AC
measurements it still prints are consequently garbage (`psrr_dc` reading
approximately 0 dB at every corner, i.e. no attenuation at all, not a
plausible circuit measurement). This is a DIFFERENT, and independent,
failure from the insufficient-margin finding in the body above: even
setting the margin question aside entirely, this specific widened-layout
attempt does not yield a usable measurement without further, open-ended
solver/netlist debugging (a probable candidate: the 196-net/196-R/196-C
`--parasitics` network this extraction produces is a coarser, one-R-plus-
one-C-per-net star model, structurally different from the original FAIL
record's 151-net/813-R/151-C per-terminal-fanout model — not simply the
same topology at a scaled resistance — though the exact cause was not
pursued further, since finding 3 below already closes the disposition
regardless of it).

**3. Disposition unchanged, now on two independent grounds.** The
resistor-scaling proxy analysis in the body above already showed this
lever cannot close the ~1.2-1.7 dB gap at the worst corner even under
generous, non-physical assumptions (the unphysical zero-resistance limit
only reaches ~60.3-60.5 dB, a razor-thin, untrustworthy ceiling). This
addendum's real-pipeline attempt does not overturn that — it cannot even
produce a converged measurement to check it against — and additionally
surfaces a genuine numerical-robustness cost this specific width value
carries on the real extracted network, which is itself a reason not to
ship it even setting the margin question aside. The `ROUTE_WIDTH_UM`
change is reverted again (not committed), same disposition as the
investigation above. **No new `sim/psrr-dc-post-layout/records/` entry is
appended**: this addendum did not produce a converged, trustworthy
measurement, so appending one would violate CLAUDE.md's "no claim without
a testbench" standard rather than satisfy it — the existing FAIL record
(`20260812-011520-5df01bf`) remains the current, valid evidence. The
`parse_subckt_ports()` harness fix IS kept (it is independently correct,
verified non-regressing, and closes a real gap for any future attempt at
this or any other post-layout lever that promotes a different pin set).

Both dispositions (Option A / Option B above) remain exactly as laid out;
this addendum adds evidence, not a new option. Routed back to the operator
per the guardrail — see issue #140.

## Ratification (2026-08-14): Option B implemented, closing this record

The operator ruled Option B on issue #170: increase the error amplifier's
schematic-level PSRR margin to absorb the measured post-layout cost, keep
DR-006's `>= 60 dB` floor exactly as ratified. Issue #170 implemented it and
measured the result; this section is the ratification and the closing
evidence.

**What changed**: `design/error_amp.sch`'s `amp_m_in` (the PMOS input
pair's device multiplicity) halved 16 -> 8. This addendum's own Finding 1
pointed at the amplifier's own internal high-impedance nodes, not the
VDD/VSS rails, as the dominant post-layout sensitivity; issue #170's PR
found (see that PR and `error_amp.sch`'s own header for the full
circuit-level account) that the input pair's own capacitive loading of the
D1/D2 diode-load nodes — not the mirror devices DR-008's text names as
"internal mirrors" — is the dominant contributor to that sensitivity, and
that decoupling capacitors and mirror-device resizing (the other two
candidates this record and issue #170 both named) measurably do not help
or actively hurt. Halving the input pair's area raises its own non-dominant
pole frequency (capacitance falls faster than gm as area shrinks at fixed
branch current), which is a gain-redistribution lever in the same family
this record's Option B description named, applied to the node the evidence
actually implicates.

**Schematic-level result** (`sim/psrr-dc/records/20260815-020301-001d1b7`,
45/45 PASS): `psrr_band_min` moves from 62.65–66.73 dB (pre-#170) to
70.24–81.47 dB (post-#170), a uniform +7.1..+15.6 dB per corner — well
past the −4.05 ± 0.36 dB gap this record measured, with design margin to
spare.

**Post-layout result** (`sim/psrr-dc-post-layout/records/20260815-034139-001d1b7`,
against the re-routed, re-extracted, LVS-clean layout at record
`20260815-034022-001d1b7`; the pre-#170 FAIL record
`20260812-011520-5df01bf` is unedited and unretired per `sim/README.md`):
**45/45 PASS**, `psrr_band_min` 72.31–93.74 dB, worst corner
`sf_125c_2.97v` at 72.31 dB — 12.31 dB above the 60 dB floor. Notably the
post-layout shift on this design is **positive** (mean +3.10 dB, corner
range +0.02..+12.27 dB versus this same design's own schematic-level
matrix) rather than the −4.05 ± 0.36 dB this record measured on the
pre-#170 design: the smaller input pair draws less routing/parasitic
loading of its own, so the mechanism this record's Finding 1 identified
(internal-node parasitic loading) costs less absolute margin on the
smaller device. This is evidence *for* Finding 1's mechanism, not a
contradiction of it — less area at the sensitive node means less
post-layout cost, exactly as Finding 1 would predict, and is not itself
re-litigated by this ratification.

**Cost, disclosed rather than hidden**: the amplifier's own random offset
(`design/error-amp-offset-budget.md`, updated in the same PR, see its
Section 9) worsens — halving the input pair's area is the opposite
direction from that budget's own area lever. The offset-budget acceptance
criterion was already **not met** before this change (Section 3's
1.53–1.88x shortfall); this ratification widens that gap further
(estimated ~2.0–2.5x, analytic re-derivation, not a fresh Monte Carlo
measurement — see that document's Section 9 for why). This is not a
criterion DR-006 or issue #170's acceptance criteria gate, and is flagged
forward the same way the original budget flagged it, not engineered around
silently. A second, separately measured cost of the same input-pair-area
lever — a uniform ~1.14 % post-layout `vref_27` drop and ~13 % relative
`tc_ppm` increase on `sim/output-voltage-tc-post-layout/` — is documented
in the Regression check below rather than folded into this paragraph.

**Regression check** (both levels, per issue #170's test plan):
`sim/error-amp-loop/` 45/45 PASS on its own acceptance criteria (phase
margin, gain margin, DC loop gain, systematic offset, Iq — all comfortably
inside their floors, several *improved* by the change); `sim/quiescent-
current(-post-layout)/`, `sim/startup-stability(-post-layout)/` PASS;
`sim/line-regulation/` and `sim/output-voltage-tc/` (schematic level) carry
pre-existing FAILs whose measurements genuinely do move by noise-level
amounts against the last committed pre-#170 record at each bench
(line-regulation `vref_nom` < 0.001 V; schematic-level `output-voltage-tc`
`vref_27` +0.21..+0.24 mV and `tc_ppm` −0.9 ppm/°C on matched corners).
Full accounting, including one post-layout-only numerical-solver anomaly at
a single DC-sweep corner, is in issue #170's PR description.

**`output-voltage-tc-post-layout` is the one exception, and it is a real
side effect of this change, not noise.** Against the same 15 corners of
the last committed pre-#170 record (`20260811-231900-84ef136` →
`20260815-035841-001d1b7`):

- `vref_27` drops **~13.5–14.0 mV (~1.14 %) uniformly at every one of the
  15 corners** (1.19328–1.19513 V → 1.17966–1.18113 V).
- `tc_ppm` rises **~+21..+24 ppm/°C (+12.4..+14.5 % relative)** at every
  corner (166.8–185.8 → 191.0–208.9 ppm/°C).
- The testbench's `vref_27 >= 1.188 V` sanity-band guard, which tripped at
  **0/15** corners in the baseline record, now trips at **15/15**.

A uniform, single-signed, corner-independent shift of that size is not
simulation noise; it is attributable to this ratification's change. The
bench's overall verdict does not flip — it was FAIL before and after on the
`tc_ppm` >> 50 ppm/°C floor, and neither DR-006/DR-008 nor issue #170's
acceptance gates cover the untrimmed `vref`/TC targets — so this is
disclosed as a measured cost, not claimed as fixed or as unaffected.

**Mechanism (measured, not speculative)**: on matched 27 °C / 3.30 V
corners the extracted layout previously read **+27.7..+28.6 mV above** its
own schematic-level `vref_27`; with the halved input pair it reads
**+13.9..+14.7 mV above** — the post-layout offset roughly halves, and the
layout's TC-flattering effect shrinks the same way (tt: −84.0 → −59.4
ppm/°C versus schematic). This is the *same* "a smaller device at the
sensitive node carries less parasitic loading" effect that makes this
design's post-layout PSRR shift positive (see the post-layout result
above). The post-layout `vref_27`/`tc_ppm` numbers therefore now track the
(already out-of-spec) schematic-level values more closely instead of being
flattered by a layout artifact. It belongs to the same family of
input-pair-area trade as the offset cost disclosed above and in
`design/error-amp-offset-budget.md` Section 9, and closing the untrimmed
±1 % accuracy gap (issue #11) remains separate work that this record does
not attempt.

Closes DR-008. Issue #140 re-runs the full 45-point post-layout bench
against this ratification and closes on the 45/45 result above.
