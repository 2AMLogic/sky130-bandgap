# Generator notes

The routed-flow generator's friction and decision notes, moved verbatim out
of `layout/bin/gen_bandgap_routed.py` (12 notes) and
`layout/bin/bus_routing.py` (`MOS_COMB_NOTE`) in issue #552. They were
assigned as module-level `*_NOTE` string constants but never loaded as a
value anywhere, while the records the generator writes cited them by bare
name -- prose a record reader could not resolve from the record. Anchored
sections here give those citations a target:
`layout/generator-notes.md#<anchor>` (lowercased constant name, underscores
to hyphens -- the `<a id>` beside each heading carries it).

Each section keeps the constant name it was cited by, and carries the note
body plus the `#:` lead-in prose that sat above it in the source, verbatim.
The notes the record *interpolates* deliberately stay in the source files,
next to the code they explain; a `*_NOTE` name this document's prose
mentions without a section of its own refers to one of those.

<a id="mos-gate-note"></a>
## MOS_GATE_NOTE

RESOLVED upstream, and the reason this increment exists. Kept as a named
note because record.md still has to say *why* the layout now draws what it
draws, and because the contact stack the fix makes possible is still this
flow's own geometry, not the router's.

Until 2AMLogic/klayout-tools#461 (merged via #474) every `klt gen` MOS generator on sky130 drew the gate poly with exactly the active region's extent and reported the gate port on the shared poly/diff boundary, so no contact could be placed legally -- one at the port straddled the diff edge (`poly.enclosing.licon.1` / `diff.enclosing.licon.1`) and one moved inward sat on poly over the channel. `diff_pair`/`mos_array` now extend the first finger's poly past the diffusion into a contact-region landing pad and report the gate port at its centre, so a gate is contactable. Placing that contact is still this flow's job: `gen-compose`'s router resolves only `metal`/`metal2` roles and never drops a licon, so met1_bus.py's `gate_contact` draws the licon on the pad and the li1 riser down into the device row itself.

<a id="res-flavor-note"></a>
## RES_FLAVOR_NOTE

`klt gen res_array` on sky130 could only draw the base `res_generic_po` flavour until 2AMLogic/klayout-tools#463 (merged via #475): the generator's `res_implant`/`res_block` layer roles were None for the sky130 family, while the same tool's sky130 extraction deck recognises three flavours (`res_generic_po` 48.2, `res_high_po` 319.8, `res_xhigh_po` 2000 ohm/sq) distinguished by implant masks the generator never drew. `res_array` now takes a `flavor` parameter resolved through the same per-flavour layer table the extraction deck keys off, so this layout draws the schematic's own `res_high_po` -- which is also what gives the resistor blocks a bulk terminal at all (the deck marks `res_high_po` `bulk_to_substrate`). That terminal is not a drawn pad, though: the deck ties it to the same shared `deck.substrate_net` global identity every NMOS body ties to, which resolves to this layout's real, drawn `VSS` net -- see SUBSTRATE_NET_NOTE.

<a id="routing-plane-note"></a>
## ROUTING_PLANE_NOTE

RESOLVED upstream, and the reason this increment exists. Through issue
#62's seventeenth increment this note recorded a live blocker: the corridor
congestion behind AC1's unrouted trio was this flow's own router running
out of free metal, with no metal-level lever left -- layout/matching-plan.md
Sections 7d-7o rule out every router/floorplan lever this repo can pull,
and klayout-tools#454's own `metal2` role was not one, because on sky130 it
resolved to the same met1 layer this flow's bussing already occupies
(Section 7d). Filed generically as 2AMLogic/klayout-tools#508; merged via
#511. Kept as a named note because the escape plane is still *this flow's*
own hand-drawn geometry, and because the record has to say why the layout
now draws met2 at all.

sky130's curated extraction deck declared exactly two connectivity levels (`EXTRACTION_DECK.metals = (li1, met1)`) through issue #62's seventeenth increment, so klayout-tools#454/#468's `metal2` role resolved to the same met1 layer this flow's own met1_bus.py already routes every bus and inter-block net on (MET1_BUS_NOTE) -- not a distinct plane above it. A router that needs a second, independent routing plane once its own intra-block bussing has saturated the only other level the deck exposes had no escape short of deck curation adding a third connectivity level. Filed generically as 2AMLogic/klayout-tools#508 and merged via #511: sky130's deck now declares met2 (69/20) over a met1<->met2 `via.drawing` (68/44) as a genuine third level, which is what MET2_ESCAPE_NOTE's escape hatch is drawn on.

<a id="met2-escape-note"></a>
## MET2_ESCAPE_NOTE

The layout-side consequence of #511, and its own residual gap.

Inter-block hops that no met1 form can clear are lifted onto met2 by `_connect_met2`: a via1 stack (met1 pad + `via.drawing` cut + met2 pad) at each endpoint and met2 wire between them, all hand-drawn by met1_bus.py exactly as the met1 routing is. met2 is tried strictly last, after every met1 elbow, channel path and Z-detour has been rolled back. That deck declares met2 as a *connectivity* level (klayout-tools#511); its *DRC* rule coverage for the level was added later and is still partial -- klayout-tools#513 (merged via #515) gave `klt drc` the met2/via1 width, spacing and enclosure rules (`met2.width.1`, `met2.space.1`, `via.width.1`, `via.space.1`, `met1.enclosing.via.1`, `met2.enclosing.via.1`), but not the met2 min-area rule (`m2.6`) -- #515 left it out because the curated deck's rule vocabulary has no `area` check primitive. This flow holds the sky130A source deck's own full threshold set by construction instead (`m2.1`/`m2.2`/`m2.6`, `via.1a`/`via.2`/`via.4a`/`via.5a` -- see met1_bus.py's DRC-budget docstring) and re-proves the spacing half with `Met1Bus.conflicts()`, which scores met2 and via1 alongside met1 and li1 for a *net-aware* short that a plain width/space DRC rule cannot see (two different nets' met2 touching is not a spacing violation -- there is no gap to measure). The residual `m2.6` gap was deliberately scoped out of #515 rather than left unfiled -- see that PR's own summary; connectivity itself is the tool's, and is what `klt extract` reads back.

<a id="mos-half-note"></a>
## MOS_HALF_NOTE

NOT a tool gap -- a flow correctness rule this increment adds. A
`diff_pair` reports its two devices as two port families (`M1_*`/`M2_*`,
or `Q1_*`/`Q2_*` when `mirror` is false), and which family is which
schematic transistor is *this flow's* choice, not the generator's. Before
MOS_HALVES existed, every net picked whichever candidate pad sat nearest
its own centroid, independently -- so two nets that the schematic says are
the drains of two *different* transistors could both land on the same
half, and a gate pin label could name a half whose drain another net had
already claimed for the other transistor. Both happened: `PN` took a
finger of the same amp_pmirr half the `AOUT` label named, and amp_nload's
`D1` route and `D1_GATE` label disagreed about which half is MN1.

A diff_pair's two port families are bound to named schematic devices once, in MOS_HALVES, and every route and pin label resolves through it. Without that binding the centroid-nearest pick is free to hand two different schematic nodes two fingers of the same physical transistor, which is a topology error that neither DRC nor the drawn-short check can see -- both terminals are legal, well-separated metal.

<a id="res-trim-topology-note"></a>
## RES_TRIM_TOPOLOGY_NOTE

What actually keeps R2A/R2B/R1 unpaired now that RES_BULK_ARITY_NOTE's
class mismatch is fixed -- found while measuring that fix's (null) effect
on `mismatch_count` in issue #62's sixteenth increment.

design/bandgap_core.sch's CORE_PARAMS carries `n_r2_trim=0` (DR-002's untrimmed code): at code 0 the schematic has no trim devices at all, and the reference correctly does not enumerate any -- R2A/R2B's length is a single `res_high_po` device each, full stop. `res_trim`'s 32 unit resistors are drawn as real physical devices in the layout unconditionally, regardless of code (a metal-option tap ladder, not a code-gated one), so the layout has trim devices and `TRIM_A`/`TRIM_A_CODE_0`/`TRIM_B`/`TRIM_B_CODE_0` nodes the schematic does not have at all at this code -- not a value difference on an otherwise-matched device, a genuine extra branch in the layout's device graph that `combine_devices` cannot fold away, because folding combines devices that already share the same two-sided identity, not devices the reference has no counterpart for. `klt lvs`'s own `net.split`/`net.merged` categories on `VOUT`/`VB`/`VBQ` (the R2A/R2B/R1 nodes the trim branch hangs off of) are this, read from the comparer's own output, not inferred. **Half of this is fixed in the eighteenth increment** -- see INTERNAL_NODE_LABEL_NOTE and RES_TRIM_LENGTH_NOTE, which between them separate the two things this note had conflated: the *labelling* that made the trim ladder look like extra devices, and the *length* it genuinely adds.

<a id="res-head-resistance-note"></a>
## RES_HEAD_RESISTANCE_NOTE

What issue #62's twenty-third increment found after bumping past
2AMLogic/klayout-tools#518/#519 (merged) and #521/#526 (merged): the
fixed per-instance head-resistance term the extractor now applies does
NOT close this cause -- it makes the disclosed `r` delta larger, because
this repo's own `res_array`-drawn trim ladder represents one schematic
resistor as many separately-contacted series primitives. Filed as
2AMLogic/klayout-tools#559.

Update, issue #62's twenty-eighth increment: the upstream fix for
klayout-tools#559 landed (#583, deferring the correction until after
`combine_devices()` folds) and #587 made it reachable from this flow's own
pre-extracted request shape. Measured under all four accounting variants by
`layout/bin/measure_fixed_offset_variants.py` and deliberately NOT adopted:
since issue #108 settled `reference.spice` on the CHAINED value, the shipped
per-primitive accounting is the only variant that matches, and #587's own
defer-plus-deck pairing would take `mismatch_count` 1 -> 4. See item 20 in
this module's docstring and layout/matching-plan.md Section 7z.

2AMLogic/klayout-tools#518 (merged via #519) added `ResistorDevice.fixed_offset_ohm`, a per-instance fixed head/end-resistance term measured against the real `sky130_fd_pr__res_high_po` two-term SPICE model (`sheet_rho_ohm_sq=324.827244`, `fixed_offset_ohm=379.705147`, both on by default for this flavour -- no opt-in flag this repo's own code needs to pass). 2AMLogic/klayout-tools#521 (merged via #526) was needed alongside it: #519's correction was applied only inside `klt extract`'s JSON-report path, not to the `kdb.Netlist` the written `.spice` file -- and therefore this flow's own `klt lvs` step, which compares two already-written `.spice` files -- actually reads. Picking up both closes that JSON-vs-netlist gap cleanly, but does NOT close this cause: it makes the disclosed `r` delta *larger*, not smaller. The fixed offset is charged once per *drawn* resistor primitive, and `res_array`'s trim ladder represents each schematic `R1`/`R2A`/`R2B` device as many separate, individually-contacted series primitives -- 50 coarse 5um + 20 fine 1um = 70 per R2 leg, 7 for R1 -- so that `klt draw`'s met1 jumpers can reach every DR-002 trim tap (RES_TRIM_LENGTH_NOTE). `klt lvs`'s `combine_devices` folds that series chain into the one lumped device the schematic states, summing the corrected `r` of every primitive -- which sums the offset once per primitive, not once for the logical device design/bandgap_core.sch's own `R ~ 380 + 325*L` model states. Measured exactly: each R2 leg now reads 114,282.71617 ohm (= 324.827244 x 270 + 70 x 379.705147, to the ohm) against the reference's 88,130, and R1 reads 14,026.889569 (= 324.827244 x 35 + 7 x 379.705147) against 11,755 -- both exact to the digit, confirmed directly against `lvs.combined.json`. The `r` delta is now larger than the pre-bump body-only shortfall it replaced (R2: 26,152.7 ohm over vs. 1,784 ohm under; R1: 2,271.9 ohm over vs. 562 ohm under), though `mismatch_count` and `category_counts` are unchanged (still 4; still `device.property`: 3, `device.unmatched`: 1) -- the *count* the flow gates on did not regress, but the *reason* moved from 'no per-device term at all' to 'the wrong number of per-device terms for this flow's own drawn topology'. Not worked around here: rewriting design/bandgap_core.sch's simplified single-device `R` model to account for this flow's own multi-primitive decomposition would be exactly the reference-edit-to-accommodate-the-layout CLAUDE.md and RES_BULK_ARITY_NOTE's own convention refuse -- and the alternative, drawing the ladder as one continuous poly body with intermediate tap contacts instead of `res_array`'s discrete unit-per-primitive geometry, is a `klt gen` capability this repo does not have (`res_array` has no continuous-body-with-taps mode). Filed as friction: 2AMLogic/klayout-tools#559.

Update, issue #62's twenty-eighth increment: #559 closed upstream via 2AMLogic/klayout-tools#583, which defers the fixed-offset correction until after `combine_devices()` folds the series chain and applies it once per combined device, and #587 (closes #585/#586) made that correction reachable from this flow's own pre-extracted `{netlist, top}` request shape -- not, as an earlier draft of that increment wrongly claimed, because `klt lvs` ignores `layout.deck` on that shape (`layout_deck` resolves unconditionally in `run_lvs`), but because the post-combine lookup keyed its device class case-sensitively (`res_high_po`) while a `kdb.NetlistSpiceReader` round-trip reports it UPPERCASED (`RES_HIGH_PO`). Measured under all four accounting variants by `layout/bin/measure_fixed_offset_variants.py` and deliberately NOT adopted: since issue #108 settled `reference.spice` on the CHAINED value, the shipped per-primitive accounting is the only variant that matches, and #587's own defer-plus-deck pairing would take `mismatch_count` 1 -> 4 and `devices.matched` 15 -> 12. See layout/matching-plan.md Section 7z.

<a id="res-resize-note"></a>
## RES_RESIZE_NOTE

Why n_r2 (and only n_r2) moved from 54 to 50, and why this file's own
drawn decomposition had to follow it. Not a layout-side finding --
transcribes issue #99/DR-003's sizing decision, made against the same
chained-array topology RES_HEAD_RESISTANCE_NOTE quantifies.

RES_HEAD_RESISTANCE_NOTE's finding -- that this flow's own multi-primitive R2A/R2B/R1 decomposition pays the fixed per-instance head offset once per drawn primitive, not once per logical device -- is a real electrical effect on the fabricated part, not just an LVS value mismatch (issue #98/DR-003, sim/res-array-head-resistance/). At the pre-resize n_r2=54 that makes the REAL chained topology's K = R2/R1 read 8.1474 against design/bandgap_core.sch's single-device model of 7.4973, pushing VOUT(27 degC) to ~1.233 V (outside the draft +/-1% window) at all 5 PVT corners and collapsing regulation at ff/2.97 V and fs/2.97 V. Issue #99 (DR-003's closure, PR #105) resizes n_r2 54 -> 50 in design/bandgap_core.sch against that real chained topology -- verified with a real-SPICE harness that chains res_high_po unit instances at this flow's own decomposition into the core testbench, not the single-device model -- bringing K back to 7.576 and VOUT(27 degC) to ~1.198 V, in-spec and collapse-free at all 5 corners (sim/res-array-resize/records/20260805-204809-2c83c7a.md). n_r1 stays at 7: holding R1 (and so the branch current) fixed corrects K without raising the hot-corner headroom demand the collapse depends on. That record's own 'Layout follow-up' explicitly deferred re-transcribing this file's N_R1/N_R2_COARSE/SCH_N_R2 to the resized decomposition and re-running DRC/LVS as the next increment, per this project's one-lever-per-increment discipline -- done here, issue #108. See item 19 in this module's own docstring and layout/matching-plan.md Section 7y for the drawn-side consequence (rows fold, LVS mismatch delta).

<a id="res-trim-lsb-note"></a>
## RES_TRIM_LSB_NOTE

Why r_lseg_trim (and only r_lseg_trim) halved 1 -> 0.5, and why
N_R2_COARSE had to move again (46 -> 48) to keep it. Not a layout-side
finding -- transcribes DR-002's "Revision (issue #106 -- chained
fine-trim LSB)" re-partition, propagated into this file's own drawn
decomposition by issue #112.

DR-002's original per-code LSB derivation (~1.72 mV/code) simulated the fine trim ladder as ONE length-tapped device per leg -- the schematic-level approximation design/bandgap_core.sch's XR2A/XR2B still draw. This flow's own chained topology is not that: `res_trim` chains N_R2_TRIM_UNITS=20 separately-contacted unit instances per leg, so a downward trim code does not shorten one device's body by r_lseg_trim -- it removes a whole separately-contacted unit instance, paying that instance's fixed per-instance head/end resistance (RES_HEAD_RESISTANCE_NOTE's rhead ~379.7 ohm) in addition to its r_lseg_trim of body. Issue #106 measured the real per-code step at the adopted n_r1=7/n_r2=50 sizing (issue #99) against DR-002's own <=3.000 mV/code comfort bound (25% of the +/-1% window's 12 mV half-width), over the same 5-corner PVT set sim/trim-range-monotonicity/ and issue #99's AC3 used: at the shipped r_lseg_trim=1 um the chained topology reads 3.123-3.146 mV/code -- a real, measured violation at every corner, not merely a carried-over assumption (sim/trim-lsb-chained/records/). Because rhead is a fixed PDK model-card constant per removed unit instance, independent of the unit's drawn body length, halving r_lseg_trim to 0.5 um does not halve the per-code step -- it removes enough of the scaling rbody (sheet/fringe, ~324.8 ohm/um) term to bring the step from 704.53 to 542.12 ohm/code, restoring the LSB to 2.403-2.421 mV/code, comfortably under the bound at every corner, with monotonicity and the downward-span coverage target unaffected (both already PASS). The fine ladder's unit COUNT (N_R2_TRIM_UNITS=20) and DR-002's certified 0..-16 downward code range are unchanged -- this is a pure re-partition of the fixed 250 um leg length between its coarse and fine segments, not a resize of n_r1/n_r2 (RES_RESIZE_NOTE's lever) or a change to the certified code range. Holding the untrimmed leg fixed at `5*N_R2_COARSE + 0.5*N_R2_TRIM_UNITS == 250` forces N_R2_COARSE 46 -> 48. `design/bandgap_core.sch`'s `.param r_lseg_trim` moved 1 -> 0.5 in issue #106/PR #111; this file's own R_LSEG_TRIM_UM/SCH_R_LSEG_TRIM_UM/N_R2_COARSE re-transcription and the routed layout's klt DRC/LVS re-verification were explicitly deferred there (DR-002's Revision section, 'Scope of this revision') as the next one-lever-per-increment step -- done here, issue #112. See item 21 in this module's own docstring.

<a id="startup-injector-note"></a>
## STARTUP_INJECTOR_NOTE

Why the injector's three single-transistor blocks are `mos_array` rather
than `diff_pair`, and why that needs no new intra-block bus kind.

design/startup_injector.sch has six devices and only ONE matched pair among them: MPC1/MPC2, the two-high diode-connected PMOS reference (both W=1 L=20, both bulk-on-VDD), which is drawn as a `diff_pair` with `splits=1` and bussed by the same `bus_mos_comb` every other MOS group in this cell uses. MNS (W=48 L=0.5), MNI (W=10 L=0.5) and MNC (W=4 L=1) share no W/L with anything, so each is a `mos_array` at `rows=1, cols=1, dummy=0` -- a single unit device. A one-unit array has no fingers to bus, so those three blocks declare no `bus` entry at all and the inter-block router reaches their `U0_S`/`U0_D`/`U0_G` pads directly through the same named-pad terminal shape the resistor blocks use. They are the only MOS blocks here generated with the generator's own `gate_contact` param: the `diff_pair` groups get their gate licon and li1 riser drawn by this flow instead (met1_bus.gate_contact, MOS_GATE_NOTE), which is the cheaper choice across 52 pfet fingers but buys nothing on a single device -- and `gate_contact` is what turns `U0_G` from a bare-poly port into the li1 pad a met1 route can via down to.

<a id="startup-composed-note"></a>
## STARTUP_COMPOSED_NOTE

What the composed cell now measures, and what it did not before. Kept as a
note rather than a comment because record.md quotes it: the extracted
netlist every post-layout bench runs on is only a netlist of the ratified
schematic if the injector is in it.

Before this increment the composed cell was the core + error amplifier only. `design/startup_injector.sch` was drawn as a schematic block and never laid out, so `klt extract` on the composed GDS produced a netlist of a DIFFERENT circuit from the one the schematic-level benches measure -- and the two startup rows of design/block-characterization-report.md said so: row 8a (schematic, core+injector) PASSed while row 8e (composed, no injector) FAILed 45/45 by construction. LVS was clean across that gap because both sides of the comparison omitted the injector: `reference.spice` transcribed `design/bandgap_core.sch` alone. Both sides now carry it -- six devices (MPC1, MPC2, MNS, MNI, MNC, QS) and three nodes internal to the injector (NC1, NG, NE) -- so the extracted netlist is a netlist of the whole ratified design and the post-layout suite measures the circuit the schematic rows describe. VSENSE is not a separate node in the composed cell: design/startup_injector.sym's VSENSE input is driven by the core's VOUT, so MNS's and MNC's gates land on the drawn VOUT net directly.

<a id="mcc-mim-infeasible-note"></a>
## MCC_MIM_INFEASIBLE_NOTE

Why MCC is drawn as the same MOS-as-capacitor device the schematic
states, rather than a sky130 `cap_mim` overlay (the operator's
2026-08-11 primary-path ruling on issue #62) -- checked, not assumed,
on two independent grounds:

1. **LVS device-class matching.** `reference.spice` states `MMCC` as a
   plain `M`-element (`MMCC VDD GDRV VDD VDD pfet L=20U W=30U m=16`), so
   `klt lvs` registers it under the deck's `pfet_class` (`"pfet"`,
   `DeviceClassMOS4Transistor`, terminals D/G/S/B). A drawn `cap_mim`
   overlay extracts as `klayout_tools.decks.sky130`'s
   `sky130_fd_pr__model__cap_mim` class instead (a two-terminal
   `DeviceClassCapacitor`, P1/P2) -- a different class *name* with a
   different terminal arity. `klt lvs` (`src/klayout_tools/lvs.py`,
   confirmed by reading `_apply_hints`) exposes no device-class
   equivalence declaration (only `hints.same_nets` and
   `hints.equivalent_pins`, both net/pin-level); when
   `NetlistComparer` pairs devices of different classes it reports
   `match_devices_with_different_device_classes`, which
   `_build_mismatches` turns into a `device.class`-category mismatch
   (still `mismatch_count` >= 1), and when the two classes cannot even
   be topologically paired (very likely here: 2-terminal vs. 4-terminal)
   each side reports its own unmatched device instead -- `mismatch_count`
   2, not fewer. So a `cap_mim` overlay cannot reach `mismatch_count: 0`
   against the *current* `reference.spice`, independent of area --
   unless the reference netlist's own `MMCC` card is rewritten to a
   capacitor model, which would be a schematic-level device-type change
   to a closed, sim-verified cell (out of this issue's scope; see the
   operator's "Redesign the compensation smaller" note).
2. **Tooling.** The twenty-ninth increment (PR #124, `Part of #62`)
   independently confirmed a `cap_mim` overlay is not drawable at all
   with the pinned `klt`: neither of sky130's `CapacitorDevice` entries
   sets `top_plate_via`/`top_plate_via_metal`, so every reproduction
   tried either extracted the two plates as disconnected islands, or
   false-shorted them, or left the top plate's via unreachable. Filed as
   2AMLogic/klayout-tools#775; see `layout/matching-plan.md` Section 7bb
   and `spec/decision-records/DR-007-mcc-area-budget.md` for the full
   reproduction.

Both findings independently rule out the MIM-overlay path today --
(1) would still block even if (2) is fixed upstream, since it is a
netlist-shape fact about `klt lvs`'s comparer, not a drawing-capability
gap. This increment therefore proceeds straight to the ruling's own
fallback: draw MCC in-plane as the MOS cap it already is in
design/error_amp.sch.

MCC is drawn as a pfet_g5v0d10v5 MOS-as-capacitor (matching design/error_amp.sch exactly), not a cap_mim overlay. Two independent reasons: (1) `reference.spice`'s MMCC card is a plain pfet M-element, and `klt lvs` has no device-class equivalence mechanism -- a cap_mim overlay would extract under a different device class (sky130_fd_pr__model__cap_mim, 2-terminal) and could not reach mismatch_count: 0 against it regardless of area, only recategorize or double the one mismatch; (2) PR #124 (issue #62's twenty-ninth increment) independently found sky130's cap_mim device recognition cannot wire a top plate out to routing metal without either a false short or a disconnected net with the currently pinned klt (2AMLogic/klayout-tools#775, filed). See layout/matching-plan.md Section 7bb/7cc and spec/decision-records/DR-007-mcc-area-budget.md.

<a id="mos-comb-note"></a>
## MOS_COMB_NOTE

Every split MOS group's fingers are bussed into the one m=N device the schematic states, on met1, with the trunk of each node running *inside* the device row rather than around it. That is deliberate and is what makes the bus crossing-free on a single routing metal: a source/drain pad is a full-height li1 strip, so a trunk may drop its via anywhere along the pad's height, and a gate reaches the same track through the li1 riser met1_bus.gate_contact draws down its own column gap. With every node's via on its own horizontal track, no node ever needs a stub that would cross another node's trunk. Each node then leaves the block on its own vertical spine, and the spines are ordered so that the further out a spine sits, the further from the row's edge its trunk is -- which is what keeps a trunk from crossing an outer spine on its way past.
