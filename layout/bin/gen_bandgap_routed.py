#!/usr/bin/env python3
"""layout/bin/gen_bandgap_routed.py -- issue #62: route the bandgap-core
floorplan skeleton to real inter-block connectivity, extract it, and LVS it
against the xschem-derived reference netlist.

Standard library only (matches sim/bin/corner-run.py's,
layout/bin/render-record.py's, and layout/bin/gen_bandgap_floorplan.py's
convention). Invoked by layout/bin/run-bandgap-routed-flow.sh, which supplies
--out-dir/--record-id/--klt/--pdk-variant exactly the way
run-bandgap-floorplan-flow.sh invokes gen_bandgap_floorplan.py.

This is the routed successor to gen_bandgap_floorplan.py (issue #15), which
stays untouched as the placement-only DRC record it always was. What is new
here, relative to that skeleton:

1. **The R2A/R2B ladder is drawn at its real full-length count** -- the
   schematic's 250 um per leg, as 48 coarse 5 um units plus 20 fine 0.5 um
   trim units (item 16 below re-decomposed the leg this way at the
   pre-resize n_r2=54/270 um sizing; item 19 re-transcribed the same
   decomposition to the resized n_r2=50/250 um sizing issue #99 adopted;
   item 21 re-partitioned the coarse/fine split again, 46/20 -> 48/20,
   when issue #106/PR #111 halved the fine unit's drawn length --
   it was 54 coarse units plus a 16-unit ladder in series before item 16),
   not the skeleton's reduced 16. `klt gen res_array` gained a `rows` fold
   parameter (2AMLogic/klayout-tools#415, merged upstream via
   klayout-tools#418), so the coarse ladder folds into 10 rows and occupies
   less area than the ~610 um-long single row that would otherwise force
   the skeleton's reduction. The area-budget line in layout/matching-plan.md
   Section 4/6 is closed by this, not deferred.
2. **PNP devices actually extract**, from the generator's own geometry.
   `klt gen bjt_array` used to draw neither the sky130 bipolar
   device-recognition marker (`pnp.drawing` 82/44) its own `klt extract`
   deck keys off nor a well tap for each unit's base pad, so its output
   extracted as *zero* devices; PR #64 composed a local `klt draw` overlay
   to close that. Upstream 2AMLogic/klayout-tools#440 now draws both per
   unit, so the overlay is **retired** here rather than carried.
3. **Real drawn metal and promoted top-level pins.** Inter-block nodes are
   drawn on met1 (see 5 below) and named with met1 labels; gate-only nodes
   and the trim taps are promoted through `gen-compose`'s `pins[]`, which
   draws a label and never a wire.
4. **`klt extract` + `klt lvs` are run and recorded**, instead of being
   skipped as not-yet-meaningful.

5. **Intra-block bussing is drawn, on met1** (added in issue #62's second
   increment). The router still exposes only one metal role, but the same
   tool's sky130 *extraction* deck declares a second conductor and its via
   (`metals = (li1, met1)`, `vias = (mcon,)`) and `klt extract` wires them
   together. This flow therefore draws each matched array's internal bus
   itself, with `klt draw`, on met1 over mcon -- a layer no device pad
   occupies, so a bus may cross its own block without touching anything.
   See `layout/bin/met1_bus.py` and MET1_BUS_NOTE below. That is what turns
   a ladder's unit segments into a real series resistor and a PNP array's
   units into a real m=N device instead of N unconnected ones.
6. **Per-matched-group guard/collector rings are back on.** Upstream
   klayout-tools#441 added `ring_gap_side`, cutting one routing opening
   through a ring band, which retires the PR #64 trade-off recorded in
   layout/matching-plan.md Section 5a.

7. **MOS gates are contacted, and every split MOS group is bussed into the
   one `m=N` device the schematic states** (added in this increment).
   Upstream 2AMLogic/klayout-tools#461 (merged via #474) made MOS generators
   draw a poly landing pad past the diffusion, so a gate contact can finally
   land legally; met1_bus.py's `gate_contact` places the licon and the li1
   riser, and `bus_mos_comb` runs one met1 trunk per node *inside* each
   device row. That is what turns 68 unconnected MOS fingers into ten real
   transistors, and what makes the six schematic nodes that terminate on a
   gate (`VA`, `VB`, `D1`, `D2`, `GDRV`, `PN`) drawable at all.
8. **The resistors are the schematic's own `res_high_po` flavour**, per
   upstream klayout-tools#463 (merged via #475). See RES_FLAVOR_NOTE.
9. **The substrate correspondence is real, drawn connectivity, not a
   declaration -- and array dummies are correctly excluded** (added in
   issue #62's fourteenth increment). Upstream klayout-tools#490 (merged
   via #495) resolves an NMOS body / resistor bulk terminal to a real drawn
   substrate tap when one is present, which this layout already draws
   (wired to `VSS`); klayout-tools#491 (merged via #494) makes sky130's
   deck declare a `dummy` marker layer that `mos_array`/`res_array`/
   `bjt_array` now draw over their own dummy units. Both retire a
   `hints.same_nets` declaration and a "dummies are counted as real
   devices" trade-off this flow previously had to carry -- see
   SUBSTRATE_NET_NOTE and DUMMY_DEVICE_NOTE.
10. **The resistor device-class arity mismatch is fixed, not just
    diagnosed** (issue #62's sixteenth increment). `layout/bandgap-core/
    reference.spice`'s `R2A`/`R2B`/`R1` cards now carry the bulk terminal
    (`VSS`) design/bandgap_core.sch already wires on every one of them
    (`r2ab`/`r2bb`/`r1b` lab_pins) and the checked-in xschem netlist this
    file cites as its own source already states
    (`XR2A VA VOUT VSS sky130_fd_pr__res_high_po ...`) -- a transcription
    fix, not a layout accommodation, since the value on that node (`VSS`)
    is exactly what the schematic wires, not one chosen to make LVS pass.
    Verified directly (`klayout.db.NetlistSpiceReader` on the fixed
    `reference.spice` now registers `RES_HIGH_PO` as
    `DeviceClassResistorWithBulk`, matching the layout side, where it was
    the incompatible `DeviceClassResistor` before). See RES_BULK_ARITY_NOTE.
11. **The metal-level capability gap behind AC1's remaining corridor
    congestion is now named and filed upstream** (issue #62's seventeenth
    increment). Re-verified against current `klayout-tools` source that
    `metal2`/`via1` (klayout-tools#454, merged via #468) resolves to the
    same met1 layer this flow's own intra-block bussing already occupies
    on sky130 -- not a distinct plane above it -- so it was never a lever
    for the `D1`/`GDRV`/`VSS` trio's own congestion (already found
    independently in layout/matching-plan.md Section 7d, but never filed).
    No routing or floorplan change ships from this increment; see
    ROUTING_PLANE_NOTE and 2AMLogic/klayout-tools#508.
12. **The third connectivity level klayout-tools#508 asked for now exists
    upstream** (issue #62's eighteenth increment, `layout/requirements.txt`
    bump only). klayout-tools#508 merged via #511:
    `EXTRACTION_DECK.metals` on sky130 is now `(li1, met1, met2)` with a
    matching `metal2 <-> met1<->met2` via, and `_PDK_ROLE_LAYERS["sky130"]`
    gains `"metal3"`/`"via2"` role names for it, mirroring `"metal2"`/
    `"via1"`. This is the genuinely independent second routing plane
    ROUTING_PLANE_NOTE said sky130 lacked. **Not yet used**: this increment
    only picks up the pin; drawing on met2/via.drawing for the still-
    unrouted `D1`/`GDRV`/`VSS` trio is real new router logic (via1
    landing-pad geometry, met2 DRC thresholds, a second congestion-free
    candidate-path search) left for the next increment, per this issue's
    own one-lever-per-increment discipline -- **done in item 13 below**.
13. **AC1 is MET: every schematic inter-block node is joined across every
    block it reaches** (issue #62's eighteenth increment). Item 11's
    klayout-tools#508 merged upstream via #511, adding met2 (69/20) over a
    met1<->met2 `via.drawing` (68/44) to sky130's curated *extraction* deck
    as a genuine third connectivity level. `_connect_met2` lifts a hop that
    no met1 form can clear onto that plane through a via1 stack at each
    end; the `D1`/`GDRV`/`VSS` trio that PRs #75-#88 could not route on
    met1 by any lever now routes, and so do two `VDD` hops that were only
    reachable through long met1 detours. See MET2_ESCAPE_NOTE. The curated
    *DRC* deck was not extended alongside the extraction deck, so
    `layout/bin/met2_drc.py` checks the new plane against the installed
    PDK's own source rules and the flow gates on it.
14. **The trim ladder's four `pins[]` labels are gone, and with them every
    remaining connectivity mismatch** (same increment). A labelled met1 net
    is promoted to a top-level pin, and `combine_devices` will not fold a
    series chain through a pinned node -- so labelling `TRIM_A`/`TRIM_B`
    and the two code-0 taps, all interior to the schematic's own R2A/R2B
    devices, split each divider leg into three unpairable pieces. Measured
    in isolation: removing only those four pins from the otherwise-identical
    extracted netlist took `mismatch_count` 26 -> 18 and `device.unmatched`
    13 -> 1. See INTERNAL_NODE_LABEL_NOTE.
15. **A real layout-vs-schematic defect surfaced by 14, quantified and
    recorded**: with R2A/R2B finally paired, the comparer reported 91,462.8
    ohm against 88,130 -- a 286 um drawn leg where design/bandgap_core.sch
    specifies 270 um at code 0, i.e. the drawn cell sat at DR-002 trim code
    +16, a direction DR-002 rejects outright. `r2_leg_length()` states this
    from the flow's own constants in every record. See RES_TRIM_LENGTH_NOTE
    and matching-plan Section 7q.
16. **That defect is fixed, and the check that found it is now gated**
    (issue #91). The trim ladder is drawn *inside* the specified 270 um
    rather than after it: `res_r2` is 50 coarse 5 um units per leg (250 um)
    and `res_trim` 20 fine 1 um units (20 um), so the tap `VA`/`VB` join --
    the far end of the fine chain -- is exactly the schematic's 270 um
    (DR-002 code 0) and every other tap *subtracts*, which is the only
    direction DR-002 permits. `r2_leg_length()`'s verdict, which previously
    reached only record.md's table, is now the `r2_leg_length_matches` row
    of :func:`flow_gate`, and :func:`trim_tap_ladder` enumerates every
    drawn code with the leg length it yields -- flagging the four taps
    (-17..-20) that exist in metal but outside DR-002's certified range.
    See RES_TRIM_LENGTH_NOTE and matching-plan Section 7r.
17. **The PNP `ae`/`pe`/`ne` transcription gap is fixed** (issue #62's
    twenty-first increment). `reference.spice`'s `QQ1`/`QQ2` cards now state
    `AE`/`PE`/`NE` derived from the vendor's own fixed
    `pnp_05v5_W0p68L0p68`/`_W3p40L3p40` macro geometry (`AE=W*L`,
    `PE=2*(W+L)`, `NE=m`) instead of the bare `m=` this device class's SPICE
    reader does not recognise at all (unlike MOS, where a bare `m=` folds
    into `W` at read time). `mismatch_count` drops 18 -> 4: the two devices'
    entire seven-parameter mismatch (`ae`/`pe`/`ab`/`pb`/`ac`/`pc`/`ne`) is
    gone, not just the three parameters this fix states, because KLayout's
    own `NetlistComparer` only exercises a device class's `is_primary`
    parameters (`AE`/`NE` for `DeviceClassBJT3Transistor`) when deciding
    whether to flag a property difference at all -- once those two agree,
    the non-primary `PE`/`AB`/`PB`/`AC`/`PC` differences are never surfaced,
    including the base/collector geometry this fix deliberately leaves
    unstated. See PNP_EMITTER_GEOMETRY_NOTE and matching-plan Section 7s.
18. **Bumped past the upstream fix for the remaining `res_high_po` cause --
    and found it does not close AC4** (issue #62's twenty-third increment).
    2AMLogic/klayout-tools#518 (merged via #519) gives `res_high_po` the
    fixed per-instance head/end-resistance term item 17's own list named as
    the last disclosed cause; #521 (merged via #526) was needed alongside it
    to make the correction reach the written `.spice` this flow's `klt lvs`
    step actually reads, not just `klt extract`'s JSON report. Picking up
    both does not reduce `mismatch_count` (still 4, still `device.property`:
    3 / `device.unmatched`: 1): the fixed offset is charged once per *drawn*
    resistor primitive, and this repo's own `res_array`-drawn trim ladder
    represents each schematic `R1`/`R2A`/`R2B` device as many separately-
    contacted series primitives (70 per R2 leg, 7 for R1) so that
    `klt draw`'s met1 jumpers can reach every DR-002 trim tap
    (RES_TRIM_LENGTH_NOTE) -- so `combine_devices`'s series fold sums the
    offset 70 (or 7) times, not once for the logical device
    design/bandgap_core.sch's own `R ~ 380 + 325*L` model states. The
    disclosed `r` delta gets *larger*, not smaller. See
    RES_HEAD_RESISTANCE_NOTE and 2AMLogic/klayout-tools#559 (filed this
    increment).
19. **The n_r2 54->50 resize (issue #99/DR-003's closure, PR #105) is
    propagated into the drawn array, and `klt lvs` goes from 4 mismatches
    to 1** (issue #108). `N_R1` stays 7 (DR-003 deliberately left it fixed);
    `N_R2_COARSE` moves 50 -> 46 and `SCH_N_R2` 54 -> 50, re-transcribing
    issue #91's coarse/fine leg decomposition to the resized 250 um/leg
    (46 coarse + 20 unchanged fine units, still reaching all of DR-002's
    certified 0..-16 downward codes). `res_r2`'s `rows` fold stays at 10,
    unchanged from the pre-resize count -- re-verified empirically against
    the new 92-unit count rather than re-derived from a divisibility rule,
    because every true divisor of 92 (2, 4, 23, 46) pushed the composed
    cell over the 50,000 um^2 budget, and this repo's own fold-turn bus
    router (`bus_res_series`) turned out not to be fold-shape-agnostic at
    every non-divisor count either (9 and 11 each left leg-1 fold-turn
    links unrouted, splitting R2A/R2B's series chain and pushing
    `mismatch_count` to 15-18 -- a genuine connectivity defect, not a value
    mismatch); 10 re-verified clean (0 unrouted links, 0 drawn-short
    conflicts) at the resized count. See RES_RESIZE_NOTE and the `res_r2`
    block's own `rows` comment. Separately, this increment settles the
    single-device-vs-chained transcription-convention question DR-003's
    closure and issue #99 left open for `reference.spice`: it now states
    the CHAINED value (the sum every drawn unit primitive pays, using the
    real `sky130_fd_pr__res_high_po` model's own two-term form) rather than
    design/bandgap_core.sch's single-device approximation, because that is
    what `klt lvs`'s own `combine_devices` actually sums the layout side
    to (RES_HEAD_RESISTANCE_NOTE) and what issue #99's own PVT
    re-verification was sized against -- closing all three `device.property`
    mismatches item 18 disclosed, not just reducing them. `mismatch_count`
    moves 4 -> 1 (the deliberately-undrawn `MMCC` is the only mismatch
    left), and the composed cell lands at 45,968 um^2 against the
    50,000 um^2 budget, matching the pre-resize figure almost exactly. See
    layout/matching-plan.md Section 7y.
20. **klayout-tools#559's fix (#583), made reachable by #587, is picked up in
    the pin and measured -- and deliberately NOT adopted, because adopting it
    would REGRESS `mismatch_count` 1 -> 4** (issue #62's twenty-eighth
    increment). #583 defers the `fixed_offset_ohm` correction until after
    `combine_devices()` folds series primitives, applying it once per
    *combined* device. #583 alone did not reach this flow's pre-extracted
    (`{"netlist", "top"}`) request shape, and the reason is worth stating
    precisely because an earlier draft of this increment got it wrong: it is
    **not** that `klt lvs` ignores `layout.deck` on that shape. `layout_deck`
    resolves unconditionally in `run_lvs`, straight from the request dict,
    independent of layout shape (read directly from klayout-tools'
    `src/klayout_tools/lvs.py` at the pinned commit). The real cause was a
    case-sensitivity bug: the post-combine correction keyed its device-class
    lookup by the deck's lowercase name (`res_high_po`) while a netlist
    round-tripped through `kdb.NetlistSpiceReader` reports class names
    UPPERCASED (`RES_HIGH_PO`), so the lookup silently missed. #587 (merged,
    closes #585/#586) normalizes that lookup case-insensitively and adds
    `run_extract(apply_resistor_fixed_offset=False)`. With the pin past #587
    the once-per-combined-device correction is genuinely reachable here.
    Measured, not asserted, by `layout/bin/measure_fixed_offset_variants.py`,
    which re-runs `klt lvs` against the shipped record's own drawn `.gds`
    under all four accounting combinations (evidence under
    `layout/bandgap-core/fixed-offset-variants/<record-id>/`): the shipped
    per-primitive/no-deck shape reports `mismatch_count=1` with
    `devices.matched=15` and every resistor **matched**, while #587's own
    defer-plus-deck pairing reports `mismatch_count=4`, `devices.matched=12`,
    and R2A/R2B at 81,586.52 ohm against the reference's 106,267.35. Since
    item 19 settled `reference.spice` on the CHAINED value -- what this flow's
    own multi-primitive chain actually sums to -- the shipped accounting is
    the only variant that agrees with the reference at all, so the deferral is
    declined as a measured regression, not merely on principle. The principle
    points the same way: DR-003 (issue #98) ratified, with independent
    real-SPICE evidence, that this layout physically pays the head/end
    resistance once per separately-contacted instance, so re-reporting each
    leg at the single-device value would state a resistance the fabricated
    cell does not have. The LVS request shape is unchanged; the pin bump moves
    no gated or recorded number (non-regression re-confirmed against
    layout/trivial-cell/reports/). See matching-plan Section 7z.
21. **DR-002's revised `r_lseg_trim` (1 -> 0.5 um, issue #106/PR #111) is
    propagated into the drawn array, DRC/LVS-clean at `mismatch_count=1`**
    (issue #112). `R_LSEG_UM`, `N_R1`, `N_R2_TRIM_UNITS` and `SCH_N_R2` are
    unchanged; `R_LSEG_TRIM_UM`/`SCH_R_LSEG_TRIM_UM` move 1.0 -> 0.5 and
    `N_R2_COARSE` moves 46 -> 48 to hold the untrimmed leg fixed at the
    schematic's 250 um (`5*48 + 0.5*20 == 250`, matching DR-002's Revision
    section verbatim; `r2_leg_length()` reports `matches: true`,
    `coarse_um=240.0`, `trim_um=10.0`). `res_r2`'s `num` (`2*N_R2_COARSE`)
    moves 92 -> 96; its `rows` fold (unchanged at 10) was re-verified
    empirically at the new unit count rather than assumed unchanged, per
    RES_RESIZE_NOTE's own precedent -- all 94 fold-turn links route clean,
    0 drawn-short conflicts. `reference.spice`'s chained `RR2A`/`RR2B`
    move 106267.35 -> 107026.76 ohm (`R1` is untouched -- it carries no
    trim ladder), re-derived at the new 48-coarse/20-fine decomposition
    (`48*(324.827244*5+379.705147) + 20*(324.827244*0.5+379.705147)`) and
    verified to the digit against `klt lvs`'s own pre-fix mismatch report
    on the freshly-extracted netlist, the same cross-check convention item
    19 established. Composed bbox holds at 45,968 um^2 (identical to every
    prior increment -- the 4 extra coarse units' length is offset by the
    fine ladder's 40 units each shrinking 0.5 um), DRC and met2 DRC both
    clean, and `mismatch_count` holds at 1 (only the deliberately-undrawn
    `MMCC`) -- this increment does not regress or improve LVS connectivity,
    only re-syncs the value transcription DR-002's revision requires. See
    RES_TRIM_LSB_NOTE and layout/matching-plan.md's routed-flow record for
    the full measured result.

What this script does NOT claim -- read record.md's own "What this record
does NOT claim" section for the authoritative, measured version:

- **Not LVS-clean.** Disclosed causes remain, none of them a topology error
  in either netlist and -- new with the eighteenth increment -- none of them
  a connectivity difference either: the compensation cap MCC, which is in
  the reference and deliberately not drawn (the only `device.unmatched`
  entry left on either side), and `res_high_po`'s value -- since item 18,
  no longer because the extractor's model omits a term, but because this
  flow's own multi-primitive trim ladder makes that term apply the wrong
  number of times when the series chain is folded into one device. The
  deck-synthesized substrate net, undeclarable array dummies, the resistor
  device-class arity mismatch, unrouted schematic nodes, the R2 leg length
  (item 16) and -- as of item 17 -- the reference's PNP cards stating no
  emitter count or geometry are all **retired** as causes; see items 9-17
  above. klayout-tools#506 (filed by the fifteenth increment) asked
  upstream for a generic reconciliation of the arity shape and is now
  CLOSED as COMPLETED (`reference.device_bulk` exists on `klt lvs`
  upstream); this flow still does not depend on it, because its own
  reference can state the bulk net directly -- see RES_BULK_ARITY_NOTE.
- **Fully inter-block routed, but not on one plane, and not on a plane
  `klt drc` fully checks.** record.md's "Schematic inter-block nets" table
  scores every schematic inter-block node against SCHEMATIC_INTER_BLOCK_NETS
  below -- i.e. against design/bandgap_core.sch's node list, not against
  this script's own declaration -- and criterion 1 is PARTIAL while any node
  is short. Several of the hops that close it are drawn on met2, whose
  connectivity is the curated extraction deck's (klayout-tools#511); its
  width/spacing/enclosure DRC rules are too (klayout-tools#513, merged via
  #515), but the met2 min-area rule (`m2.6`) is not, so this repo's own
  `layout/bin/met2_drc.py` still checks the full sky130A source-deck
  threshold set independently.

Every gap still open is filed upstream per CLAUDE.md's friction protocol and
named in the NOTE constants below; record.md restates them with the measured
numbers from the run that produced it.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import met1_bus  # noqa: E402  -- local module, resolved from this script's dir
from layout_common import klt_gen, run_klt_json, union_bbox  # noqa: E402

# bus_routing.py (issue #221) imports several names back from this module at
# its own top level. When this file is run directly (`__name__ ==
# "__main__"`), alias this module's registered name to the same object so
# that import resolves to the already-running instance instead of
# re-executing this file a second time under its real module name.
sys.modules.setdefault("gen_bandgap_routed", sys.modules[__name__])

# ---------------------------------------------------------------------------
# Friction notes (upstream tool gaps this script works around or is limited
# by). Each is filed at 2AMLogic/klayout-tools per CLAUDE.md's protocol as a
# generic tool-gap description; the design-specific consequence lives here and
# in layout/matching-plan.md, never in that tracker.
# ---------------------------------------------------------------------------
MET1_BUS_NOTE = (
    "Every intra-block bus and every inter-block net in this cell is drawn "
    "by this repo with `klt draw`, on met1 over mcon -- see "
    "layout/bin/met1_bus.py. That started as the only option: sky130's "
    "generator/router layer-role table exposed exactly one routing metal "
    "role (`metal` -> li1 67/20), the same layer every generator draws its "
    "device pads on, so `klt gen-compose` could not express a bus at all "
    "(klayout-tools#433; its fix #439 made the failure visible rather than "
    "expressible). klayout-tools#454 (merged via #468) has since added "
    "`metal2`/`via1` roles with via-drop bussing, and #508 (merged via "
    "#511) a third `metal3`/`via2` level, so the router *can* now plan "
    "wires above the pad layer. This flow has not moved its bussing onto "
    "them (its own met2 escape plane is hand-drawn too, MET2_ESCAPE_NOTE): "
    "the "
    "bussing here is a planar lane assignment derived from each block's own "
    "reported geometry (MOS_COMB_NOTE), and swapping it for router-planned "
    "routing is a rework to be measured on its own, not a parameter change "
    "to be slipped into an increment that is already changing the device "
    "topology. Hand-placing what a router could plan remains the residual "
    "gap."
)
#: RESOLVED upstream, and the reason this increment exists. Kept as a named
#: note because record.md still has to say *why* the layout now draws what it
#: draws, and because the contact stack the fix makes possible is still this
#: flow's own geometry, not the router's.
MOS_GATE_NOTE = (
    "Until 2AMLogic/klayout-tools#461 (merged via #474) every `klt gen` MOS "
    "generator on sky130 drew the gate poly with exactly the active "
    "region's extent and reported the gate port on the shared poly/diff "
    "boundary, so no contact could be placed legally -- one at the port "
    "straddled the diff edge (`poly.enclosing.licon.1` / "
    "`diff.enclosing.licon.1`) and one moved inward sat on poly over the "
    "channel. `diff_pair`/`mos_array` now extend the first finger's poly "
    "past the diffusion into a contact-region landing pad and report the "
    "gate port at its centre, so a gate is contactable. Placing that "
    "contact is still this flow's job: `gen-compose`'s router resolves only "
    "`metal`/`metal2` roles and never drops a licon, so met1_bus.py's "
    "`gate_contact` draws the licon on the pad and the li1 riser down into "
    "the device row itself."
)
RES_FLAVOR_NOTE = (
    "`klt gen res_array` on sky130 could only draw the base "
    "`res_generic_po` flavour until 2AMLogic/klayout-tools#463 (merged via "
    "#475): the generator's `res_implant`/`res_block` layer roles were None "
    "for the sky130 family, while the same tool's sky130 extraction deck "
    "recognises three flavours (`res_generic_po` 48.2, `res_high_po` 319.8, "
    "`res_xhigh_po` 2000 ohm/sq) distinguished by implant masks the "
    "generator never drew. `res_array` now takes a `flavor` parameter "
    "resolved through the same per-flavour layer table the extraction deck "
    "keys off, so this layout draws the schematic's own `res_high_po` -- "
    "which is also what gives the resistor blocks a bulk terminal at all "
    "(the deck marks `res_high_po` `bulk_to_substrate`). That terminal is "
    "not a drawn pad, though: the deck ties it to the same shared "
    "`deck.substrate_net` global identity every NMOS body ties to, which "
    "resolves to this layout's real, drawn `VSS` net -- see "
    "SUBSTRATE_NET_NOTE."
)
#: RESOLVED upstream, and the reason this increment exists. Through issue
#: #62's seventeenth increment this note recorded a live blocker: the corridor
#: congestion behind AC1's unrouted trio was this flow's own router running
#: out of free metal, with no metal-level lever left -- layout/matching-plan.md
#: Sections 7d-7o rule out every router/floorplan lever this repo can pull,
#: and klayout-tools#454's own `metal2` role was not one, because on sky130 it
#: resolved to the same met1 layer this flow's bussing already occupies
#: (Section 7d). Filed generically as 2AMLogic/klayout-tools#508; merged via
#: #511. Kept as a named note because the escape plane is still *this flow's*
#: own hand-drawn geometry, and because the record has to say why the layout
#: now draws met2 at all.
ROUTING_PLANE_NOTE = (
    "sky130's curated extraction deck declared exactly two connectivity "
    "levels (`EXTRACTION_DECK.metals = (li1, met1)`) through issue #62's "
    "seventeenth increment, so klayout-tools#454/#468's `metal2` role "
    "resolved to the same met1 layer this flow's own met1_bus.py already "
    "routes every bus and inter-block net on (MET1_BUS_NOTE) -- not a "
    "distinct plane above it. A router that needs a second, independent "
    "routing plane once its own intra-block bussing has saturated the only "
    "other level the deck exposes had no escape short of deck curation "
    "adding a third connectivity level. Filed generically as "
    "2AMLogic/klayout-tools#508 and merged via #511: sky130's deck now "
    "declares met2 (69/20) over a met1<->met2 `via.drawing` (68/44) as a "
    "genuine third level, which is what MET2_ESCAPE_NOTE's escape hatch is "
    "drawn on."
)
#: The layout-side consequence of #511, and its own residual gap.
MET2_ESCAPE_NOTE = (
    "Inter-block hops that no met1 form can clear are lifted onto met2 by "
    "`_connect_met2`: a via1 stack (met1 pad + `via.drawing` cut + met2 pad) "
    "at each endpoint and met2 wire between them, all hand-drawn by "
    "met1_bus.py exactly as the met1 routing is. met2 is tried strictly "
    "last, after every met1 elbow, channel path and Z-detour has been rolled "
    "back. That deck declares met2 as a *connectivity* level "
    "(klayout-tools#511); its *DRC* rule coverage for the level was added "
    "later and is still partial -- klayout-tools#513 (merged via #515) gave "
    "`klt drc` the met2/via1 width, spacing and enclosure rules "
    "(`met2.width.1`, `met2.space.1`, `via.width.1`, `via.space.1`, "
    "`met1.enclosing.via.1`, `met2.enclosing.via.1`), but not the met2 "
    "min-area rule (`m2.6`) -- #515 left it out because the curated deck's "
    "rule vocabulary has no `area` check primitive. This flow holds the "
    "sky130A source deck's own full threshold set by construction instead "
    "(`m2.1`/`m2.2`/`m2.6`, `via.1a`/`via.2`/`via.4a`/`via.5a` -- see "
    "met1_bus.py's DRC-budget docstring) and re-proves the spacing half with "
    "`Met1Bus.conflicts()`, which scores met2 and via1 alongside met1 and "
    "li1 for a *net-aware* short that a plain width/space DRC rule cannot "
    "see (two different nets' met2 touching is not a spacing violation --"
    " there is no gap to measure). The residual `m2.6` gap was deliberately "
    "scoped out of #515 rather than left unfiled -- see that PR's own "
    "summary; connectivity itself is the tool's, and is what `klt extract` "
    "reads back."
)
#: Historical note, kept for context: through issue #62's thirteenth
#: increment, sky130's curated extraction deck had no NMOS-body or
#: resistor-bulk layer to derive from drawn geometry -- `extract.py`
#: registered an *empty* `nfet_body` region, wired it into every nfet's `W`
#: terminal, every `bulk_to_substrate` resistor's `W` terminal and every
#: bipolar's collector, and then `connect_global`'d it to the deck's
#: synthesized `vsubs` net, which no drawn shape could ever join. The
#: correspondence to the schematic's real `VSS` had to be declared via
#: `hints.same_nets` instead.
#:
#: 2AMLogic/klayout-tools#490 (merged via #495, picked up in issue #62's
#: fourteenth increment) resolves the body/bulk/collector terminal to a real
#: drawn `tap.drawing` ring outside `nwell` when one is present and
#: contacted -- and this layout already draws exactly that shape (both NMOS
#: groups' substrate guard-ring taps and both PNP base ties, wired to `VSS`
#: by this flow). Once any such tap is drawn anywhere in the design, sky130's
#: single shared `deck.substrate_net` global identity resolves to that real
#: net everywhere it is used, not just at the tap itself -- confirmed by
#: reading the extracted netlist back: every nfet's `b` terminal and every
#: `res_high_po`'s `w` terminal now read `VSS`, not `vsubs`. There is no
#: longer a `vsubs` net in this layout's extracted netlist at all, so
#: `SUBSTRATE_SAME_NETS` is empty -- declaring a correspondence for a net
#: that no longer exists is not a no-op, it is a hard `klt lvs` error
#: (`hints.same_nets: layout net 'vsubs' not found`), which is exactly what
#: shipping the klt pin bump without this change produced.
SUBSTRATE_NET_NOTE = (
    "Through issue #62's thirteenth increment, sky130's curated extraction "
    "deck had no NMOS-body or resistor-bulk layer to derive from drawn "
    "geometry and tied every such terminal to a synthesized, undrawable "
    "`vsubs` global (2AMLogic/klayout-tools#490). Resolved via #495 "
    "(picked up this flow's fourteenth increment): a real drawn substrate "
    "tap -- which this layout already draws, wired to `VSS` -- now resolves "
    "the whole design's substrate identity to the real `VSS` net directly. "
    "Verified by reading the extracted netlist: every nfet body and every "
    "`res_high_po` bulk terminal reads `VSS`, not `vsubs`."
)
#: NOT a tool gap -- a flow correctness rule this increment adds. A
#: `diff_pair` reports its two devices as two port families (`M1_*`/`M2_*`,
#: or `Q1_*`/`Q2_*` when `mirror` is false), and which family is which
#: schematic transistor is *this flow's* choice, not the generator's. Before
#: MOS_HALVES existed, every net picked whichever candidate pad sat nearest
#: its own centroid, independently -- so two nets that the schematic says are
#: the drains of two *different* transistors could both land on the same
#: half, and a gate pin label could name a half whose drain another net had
#: already claimed for the other transistor. Both happened: `PN` took a
#: finger of the same amp_pmirr half the `AOUT` label named, and amp_nload's
#: `D1` route and `D1_GATE` label disagreed about which half is MN1.
MOS_HALF_NOTE = (
    "A diff_pair's two port families are bound to named schematic devices "
    "once, in MOS_HALVES, and every route and pin label resolves through it. "
    "Without that binding the centroid-nearest pick is free to hand two "
    "different schematic nodes two fingers of the same physical transistor, "
    "which is a topology error that neither DRC nor the drawn-short check "
    "can see -- both terminals are legal, well-separated metal."
)
DUMMY_DEVICE_NOTE = (
    "Through issue #62's thirteenth increment: 2AMLogic/klayout-tools#462 "
    "(merged via #471) extended `klt extract`'s dummy-device suppression "
    "from MOS gates to resistors and bipolars, which was only the "
    "extractor half of the gap. The other half was open on sky130: the "
    "suppression keyed off `ExtractionDeck.dummy`, and the sky130 curated "
    "deck declared no `dummy` layer at all, no `klt gen` generator drew "
    "one, and `klt extract` exposed no override -- so there was no layer "
    "for a layout to mark its dummies with, and every matched array's "
    "dummy edge units extracted as ordinary devices with no schematic "
    "counterpart. Resolved via 2AMLogic/klayout-tools#491 (merged via #494, "
    "picked up in this flow's fourteenth increment): sky130's curated deck "
    "now declares a `dummy` marker layer, and `mos_array`/`res_array`/ "
    "`bjt_array` draw it over each array's own `dummy_cells` footprint, so "
    "`klt extract` correctly drops them. Verified: `extract.json`'s "
    "`dummy_devices_dropped` is non-zero and `pnp`/`res_high_po` device "
    "counts dropped accordingly, with no change to the drawn GDS geometry "
    "-- a dummy unit has no schematic counterpart by construction (it "
    "exists only for layout-matching symmetry), so this is a strictly "
    "*more* correct comparison, not a number chased by hiding matching "
    "geometry."
)
#: Why no resistor could be paired by `klt lvs` at all, whatever the routing
#: did -- found while isolating issue #72's 0/0 correspondence regression and
#: filed as 2AMLogic/klayout-tools#504 (closed via #505) and, for the generic
#: reconciliation #505 deferred, as #506 (closed as COMPLETED -- see below).
#: **Fixed** on this flow's own side in issue #62's sixteenth increment --
#: kept as a historical note plus the fix.
RES_BULK_ARITY_NOTE = (
    "The sky130 deck marks `res_high_po` `bulk_to_substrate`, so `klt "
    "extract` writes a **three-node** R card "
    "(`R<name> <a> <b> <bulk> <value> <model>`), which KLayout's SPICE "
    "reader turns into `DeviceClassResistorWithBulk` (terminals A/B/W). "
    "Through issue #62's fifteenth increment, `reference.spice` carried "
    "only a **two-node** R card (`R<name> <a> <b> <value> <model>`), which "
    "the same reader turns into the incompatible `DeviceClassResistor` "
    "(terminals A/B) -- same model name on both sides, different terminal "
    "count, so `NetlistComparer` could not pair them regardless of value. "
    "2AMLogic/klayout-tools#505 (merged) added a dedicated "
    "`device.class_arity` mismatch category for exactly this shape, "
    "diagnostic only -- it does not itself make the two classes match, and "
    "the generic reconciliation #504 proposed (a request-side hint "
    "normalizing the reference class's implicit bulk terminal, or the "
    "symmetric layout-side drop) was left unimplemented, filed by the "
    "fifteenth increment as 2AMLogic/klayout-tools#506, since closed as "
    "COMPLETED (`reference.device_bulk` now exists upstream). "
    "**Fixed in the sixteenth increment, without needing #506**: "
    "`reference.spice`'s `R2A`/`R2B`/"
    "`R1` cards now carry the bulk node too (`VSS`), because "
    "design/bandgap_core.sch's own schematic wires it there on every one of "
    "them (`r2ab`/`r2bb`/`r1b` lab_pins) and the checked-in xschem netlist "
    "`reference.spice` already cites as its source states it directly "
    "(`XR2A VA VOUT VSS sky130_fd_pr__res_high_po ...`) -- this was a "
    "transcription gap in `reference.spice`, not an invented connection, so "
    "fixing it is not the reference-edit-to-accommodate-the-layout this "
    "flow refuses elsewhere. That distinction is the whole reason #506 was "
    "not needed here and is still a valid ask elsewhere: #506 asks `klt` to "
    "reconcile the arity when the reference genuinely does *not* wire the "
    "bulk net and so cannot state it; this reference always could, and the "
    "fifteenth increment's premise that a reference edit was the only other "
    "option and one this flow refuses was wrong for this device only. "
    "Verified directly with "
    "`klayout.db.NetlistSpiceReader`: `reference.spice` now registers "
    "`RES_HIGH_PO` as `DeviceClassResistorWithBulk`, the same class the "
    "layout side registers. Confirmed to change nothing else: rerunning "
    "the full flow after the fix reproduces byte-identical "
    "`mismatch_count`, `category_counts`, and the identical "
    "`device.unmatched` entry list -- the arity mismatch was real and is "
    "now retired, but was never the operative blocker for these three "
    "devices; RES_TRIM_TOPOLOGY_NOTE's structural gap is. See "
    "layout/matching-plan.md Section 7n."
)
#: Fixed in issue #62's twenty-first increment: the same transcription-gap shape
#: RES_BULK_ARITY_NOTE closed for the resistor bulk terminal, applied to the
#: PNP pair's emitter geometry.
PNP_EMITTER_GEOMETRY_NOTE = (
    "`klt lvs`'s SPICE reader recognises `AE`/`PE`/`AB`/`PB`/`AC`/`PC`/`NE` "
    "on a `Q` card (KLayout's `DeviceClassBJT3Transistor` parameter set) but "
    "has no notion of a `M`/`mult` field for that class at all -- unlike "
    "`DeviceClassMOS3Transistor`, where a bare `m=` folds directly into `W` "
    "at read time (confirmed directly with `klayout.db.NetlistSpiceReader`), "
    "a Q-card's `m=8` is silently dropped and every unstated parameter "
    "defaults to its class default (`AE`/`PE`/`AB`/`PB`/`AC`/`PC` = 0, "
    "`NE` = 1). That is exactly the shape `klt lvs` reported before this fix: "
    "`ne` 8 (layout) vs 1 (reference), plus zero-valued `ae`/`pe`/`ab`/`pb`/"
    "`ac`/`pc`. `AE`/`PE` are knowable independent of this repo's own layout "
    "generator: the instantiated model name IS the vendor's geometry "
    "declaration. `sky130_fd_pr__pnp_05v5_W0p68L0p68`/`_W3p40L3p40` are "
    "SkyWater's own fixed, non-parametric macro cells -- "
    "`sky130_fd_pr/pnp_05v5.sym`'s netlist format is "
    "`... sky130_fd_pr__@model m=@m`, with no W/L/area argument at all, and "
    "the corresponding `.subckt`s in "
    "libs.ref/sky130_fd_pr/spice/sky130_fd_pr__pnp_05v5_W*.model.spice take "
    "only `Collector Base Emitter` plus a `mult` param; every geometry-"
    "dependent SPICE parameter (`is`/`bf`/...) is baked into that specific "
    "model's own cards. The vendor's own naming convention states the "
    "emitter's W and L directly, so the standard SPICE rectangular-junction "
    "formulae give `AE = W*L`, `PE = 2*(W+L)` per unit, and the schematic's "
    "own `m='n_pnp_ctat'`/`m='n_pnp_ptat'` (= 8, design/bandgap_core.sch "
    "lines 186-187) states the parallel count, which `klt lvs`'s "
    "`combine_devices` sums into `AE`/`PE` (not just `NE`) when it folds the "
    "layout's own 8 parallel unit devices into one -- confirmed directly "
    "against this flow's own combined-LVS device table, where the layout's "
    "post-fold Q1 reads `AE=3.6992 PE=21.76 NE=8` and Q2 reads "
    "`AE=92.48 PE=108.8 NE=8`, i.e. exactly `8 * unit_AE` / `8 * unit_PE`, "
    "not the unscaled per-unit value: Q1 (W0p68L0p68) unit AE = "
    "0.68*0.68 = 0.4624 um^2, unit PE = 2*(0.68+0.68) = 2.72 um, x8 = "
    "3.6992 um^2 / 21.76 um; Q2 (W3p40L3p40) unit AE = 3.40*3.40 = 11.56 "
    "um^2, unit PE = 2*(3.40+3.40) = 13.6 um, x8 = 92.48 um^2 / 108.8 um. "
    "`AB`/`PB`/`AC`/`PC` (base/collector area/perimeter) are deliberately "
    "left unstated (0, the class default): unlike the emitter, base/"
    "collector geometry is not part of the vendor's fixed macro at all -- "
    "this layout does not instantiate `sky130_fd_pr__pnp_05v5_W*` as a "
    "vendor cell; `klt gen bjt_array` draws a matching-faithful floorplan "
    "from base layers (this record's own \"What this record does NOT "
    "claim\" section), so the drawn base/collector geometry is this "
    "repository's own generator's choice, not something "
    "design/bandgap_core.sch's `model=pnp_05v5_W*` name declares or could "
    "ever declare -- stating a value here would mean deriving it from the "
    "layout to make the comparison pass, the workaround "
    "RES_BULK_ARITY_NOTE's own convention refuses. Measured effect: fixing "
    "only `AE`/`PE`/`NE` (leaving `AB`/`PB`/`AC`/`PC` unstated) drops "
    "`mismatch_count` 18 -> 4 and removes every mismatch on both PNP "
    "devices, all seven parameters, not just the three this fix states -- "
    "because KLayout's own `NetlistComparer` decides whether a matched "
    "device pair has a property difference using only that device class's "
    "`is_primary` parameters (`AE` and `NE` for `DeviceClassBJT3Transistor`, "
    "confirmed directly via `parameter_definitions()`'s own `is_primary` "
    "flag); once those two agree, `PE`/`AB`/`PB`/`AC`/`PC` are never "
    "compared at all, so this is not evidence that the base/collector "
    "geometry also matches -- it does not, on either device -- only that "
    "the tool's own equivalence check does not exercise it. See "
    "layout/matching-plan.md Section 7s."
)
#: What actually keeps R2A/R2B/R1 unpaired now that RES_BULK_ARITY_NOTE's
#: class mismatch is fixed -- found while measuring that fix's (null) effect
#: on `mismatch_count` in issue #62's sixteenth increment.
RES_TRIM_TOPOLOGY_NOTE = (
    "design/bandgap_core.sch's CORE_PARAMS carries `n_r2_trim=0` (DR-002's "
    "untrimmed code): at code 0 the schematic has no trim devices at all, "
    "and the reference correctly does not enumerate any -- R2A/R2B's length "
    "is a single `res_high_po` device each, full stop. `res_trim`'s 32 unit "
    "resistors are drawn as real physical devices in the layout "
    "unconditionally, regardless of code (a metal-option tap ladder, not a "
    "code-gated one), so the layout has trim devices and "
    "`TRIM_A`/`TRIM_A_CODE_0`/`TRIM_B`/`TRIM_B_CODE_0` nodes the schematic "
    "does not have at all at this code -- not a value difference on an "
    "otherwise-matched device, a genuine extra branch in the layout's "
    "device graph that `combine_devices` cannot fold away, because folding "
    "combines devices that already share the same two-sided identity, not "
    "devices the reference has no counterpart for. `klt lvs`'s own "
    "`net.split`/`net.merged` categories on `VOUT`/`VB`/`VBQ` (the R2A/R2B/"
    "R1 nodes the trim branch hangs off of) are this, read from the "
    "comparer's own output, not inferred. **Half of this is fixed in the "
    "eighteenth increment** -- see INTERNAL_NODE_LABEL_NOTE and "
    "RES_TRIM_LENGTH_NOTE, which between them separate the two things this "
    "note had conflated: the *labelling* that made the trim ladder look like "
    "extra devices, and the *length* it genuinely adds."
)
#: Why the trim ladder's nodes were unpairable, isolated in issue #62's
#: eighteenth increment by removing four labels and re-running `klt lvs`
#: against the otherwise-identical extracted netlist.
INTERNAL_NODE_LABEL_NOTE = (
    "A labelled met1 net is promoted by `klt extract` to a **top-level "
    "pin**, and `klt lvs`'s `combine_devices` will not fold a series chain "
    "through a pinned node -- folding one away would delete an externally "
    "visible port. This flow labelled every declared inter-block net plus "
    "four trim taps, including `TRIM_A`/`TRIM_B` (the junction between "
    "`res_r2`'s leg and `res_trim`'s leg) and "
    "`TRIM_A_CODE_0`/`TRIM_B_CODE_0`. Every one of those four sits on a node "
    "*interior to the schematic's own R2A/R2B device*, which at DR-002's "
    "code 0 the schematic does not have at all -- so each leg's series chain "
    "was pinned into three pieces on the layout side and none of the three "
    "could pair with the reference's single R2A/R2B, and the resulting "
    "orphan nodes dragged `VBQ`, `R1` and `Q2` out of correspondence with "
    "them. Measured in isolation before being fixed: re-running `klt lvs` on "
    "the identical extracted netlist with only those four pins removed took "
    "`mismatch_count` 26 -> 18 and `device.unmatched` 13 -> **1** (the "
    "deliberately-undrawn `MCC`), with `net.unmatched` going 6 -> 0. Fixed "
    "here by not labelling a net declared `internal` to a schematic device, "
    "and by reporting the trim taps into the record instead of into `pins[]` "
    "-- the taps are still documented, they are just no longer asserted to "
    "be device-level ports of this cell."
)
#: The genuine circuit defect the nineteenth increment's LVS clean-up
#: exposed, and how the twentieth (issue #91) closed it.
RES_TRIM_LENGTH_NOTE = (
    "With INTERNAL_NODE_LABEL_NOTE's pins removed the comparer paired R2A "
    "and R2B and reported a *value* difference -- the first time this flow "
    "had been able to see one on these devices: layout 91,462.8 ohm against "
    "the reference's 88,130 ohm. 91,462.8 / 319.8 ohm-per-square = **286 "
    "squares**, i.e. a 286 um drawn leg where design/bandgap_core.sch's "
    "`L = r_lseg*n_r2 + r_lseg_trim*n_r2_trim` at `n_r2=54, r_lseg=5, "
    "n_r2_trim=0` states 270 um. The 16 um was exactly `res_trim`'s 16 x 1 "
    "um leg, which the layout wired in series *after* a full-length 270 um "
    "`res_r2` leg: the drawn cell sat at trim code **+16**, and DR-002 "
    "rejects every positive code outright (issue #46 found n_r2=55, i.e. "
    "+5 um, already collapses the operating point at the ff/2.97 V and "
    "fs/2.97 V hot corners; sim/trim-range-monotonicity/ finds +1/+2 "
    "collapse too). Worse than the 5.9% value error: with the ladder wired "
    "after the full leg, *every* tap moved the leg further up from 270, so "
    "the drawn ladder could not express any of the 16 downward codes DR-002 "
    "certifies. A real layout-vs-schematic defect, not an LVS bookkeeping "
    "artifact. **Fixed in issue #91** by re-decomposing the leg instead of "
    "extending it: `res_r2` draws 50 coarse 5 um units (250 um) and "
    "`res_trim` the remaining 20 fine 1 um units (20 um), so the code-0 tap "
    "-- the far end of the fine chain, which is what `VA`/`VB` join -- is "
    "exactly 270 um and code -k skips k fine units for 270-k um. 50/20 is "
    "the minimal integral decomposition that keeps 270 um and still reaches "
    "DR-002's -16 (51 coarse + 15 fine also totals 270 but stops at -15). "
    "The drawn ladder spans 0..-20; -17..-20 are physically drawn but "
    "flagged out-of-certified-range in the tap table above, not offered as "
    "valid codes. `r2_leg_length()` now reports `matches: true` and is a "
    "**gated** flow condition (`r2_leg_length_matches`) rather than a "
    "recorded number, so this cannot silently regress. See "
    "layout/matching-plan.md Section 7r."
)
#: What issue #62's twenty-third increment found after bumping past
#: 2AMLogic/klayout-tools#518/#519 (merged) and #521/#526 (merged): the
#: fixed per-instance head-resistance term the extractor now applies does
#: NOT close this cause -- it makes the disclosed `r` delta larger, because
#: this repo's own `res_array`-drawn trim ladder represents one schematic
#: resistor as many separately-contacted series primitives. Filed as
#: 2AMLogic/klayout-tools#559.
#:
#: Update, issue #62's twenty-eighth increment: the upstream fix for
#: klayout-tools#559 landed (#583, deferring the correction until after
#: `combine_devices()` folds) and #587 made it reachable from this flow's own
#: pre-extracted request shape. Measured under all four accounting variants by
#: `layout/bin/measure_fixed_offset_variants.py` and deliberately NOT adopted:
#: since issue #108 settled `reference.spice` on the CHAINED value, the shipped
#: per-primitive accounting is the only variant that matches, and #587's own
#: defer-plus-deck pairing would take `mismatch_count` 1 -> 4. See item 20 in
#: this module's docstring and layout/matching-plan.md Section 7z.
RES_HEAD_RESISTANCE_NOTE = (
    "2AMLogic/klayout-tools#518 (merged via #519) added `ResistorDevice."
    "fixed_offset_ohm`, a per-instance fixed head/end-resistance term "
    "measured against the real `sky130_fd_pr__res_high_po` two-term SPICE "
    "model (`sheet_rho_ohm_sq=324.827244`, `fixed_offset_ohm=379.705147`, "
    "both on by default for this flavour -- no opt-in flag this repo's own "
    "code needs to pass). 2AMLogic/klayout-tools#521 (merged via #526) was "
    "needed alongside it: #519's correction was applied only inside `klt "
    "extract`'s JSON-report path, not to the `kdb.Netlist` the written "
    "`.spice` file -- and therefore this flow's own `klt lvs` step, which "
    "compares two already-written `.spice` files -- actually reads. "
    "Picking up both closes that JSON-vs-netlist gap cleanly, but does NOT "
    "close this cause: it makes the disclosed `r` delta *larger*, not "
    "smaller. The fixed offset is charged once per *drawn* resistor "
    "primitive, and `res_array`'s trim ladder represents each schematic "
    "`R1`/`R2A`/`R2B` device as many separate, individually-contacted "
    "series primitives -- 50 coarse 5um + 20 fine 1um = 70 per R2 leg, 7 "
    "for R1 -- so that `klt draw`'s met1 jumpers can reach every DR-002 "
    "trim tap (RES_TRIM_LENGTH_NOTE). `klt lvs`'s `combine_devices` folds "
    "that series chain into the one lumped device the schematic states, "
    "summing the corrected `r` of every primitive -- which sums the offset "
    "once per primitive, not once for the logical device design/"
    "bandgap_core.sch's own `R ~ 380 + 325*L` model states. Measured "
    "exactly: each R2 leg now reads 114,282.71617 ohm (= 324.827244 x 270 "
    "+ 70 x 379.705147, to the ohm) against the reference's 88,130, and R1 "
    "reads 14,026.889569 (= 324.827244 x 35 + 7 x 379.705147) against "
    "11,755 -- both exact to the digit, confirmed directly against "
    "`lvs.combined.json`. The `r` delta is now larger than the pre-bump "
    "body-only shortfall it replaced (R2: 26,152.7 ohm over vs. 1,784 ohm "
    "under; R1: 2,271.9 ohm over vs. 562 ohm under), though "
    "`mismatch_count` and `category_counts` are unchanged (still 4; still "
    "`device.property`: 3, `device.unmatched`: 1) -- the *count* the flow "
    "gates on did not regress, but the *reason* moved from 'no per-device "
    "term at all' to 'the wrong number of per-device terms for this flow's "
    "own drawn topology'. Not worked around here: rewriting design/"
    "bandgap_core.sch's simplified single-device `R` model to account for "
    "this flow's own multi-primitive decomposition would be exactly the "
    "reference-edit-to-accommodate-the-layout CLAUDE.md and "
    "RES_BULK_ARITY_NOTE's own convention refuse -- and the alternative, "
    "drawing the ladder as one continuous poly body with intermediate tap "
    "contacts instead of `res_array`'s discrete unit-per-primitive "
    "geometry, is a `klt gen` capability this repo does not have "
    "(`res_array` has no continuous-body-with-taps mode). Filed as "
    "friction: 2AMLogic/klayout-tools#559.\n\n"
    "Update, issue #62's twenty-eighth increment: #559 closed upstream via "
    "2AMLogic/klayout-tools#583, which defers the fixed-offset correction "
    "until after `combine_devices()` folds the series chain and applies it "
    "once per combined device, and #587 (closes #585/#586) made that "
    "correction reachable from this flow's own pre-extracted `{netlist, "
    "top}` request shape -- not, as an earlier draft of that increment "
    "wrongly claimed, because `klt lvs` ignores `layout.deck` on that shape "
    "(`layout_deck` resolves unconditionally in `run_lvs`), but because the "
    "post-combine lookup keyed its device class case-sensitively "
    "(`res_high_po`) while a `kdb.NetlistSpiceReader` round-trip reports it "
    "UPPERCASED (`RES_HIGH_PO`). Measured under all four accounting "
    "variants by `layout/bin/measure_fixed_offset_variants.py` and "
    "deliberately NOT adopted: since issue #108 settled `reference.spice` on "
    "the CHAINED value, the shipped per-primitive accounting is the only "
    "variant that matches, and #587's own defer-plus-deck pairing would take "
    "`mismatch_count` 1 -> 4 and `devices.matched` 15 -> 12. See "
    "layout/matching-plan.md Section 7z."
)
#: Why n_r2 (and only n_r2) moved from 54 to 50, and why this file's own
#: drawn decomposition had to follow it. Not a layout-side finding --
#: transcribes issue #99/DR-003's sizing decision, made against the same
#: chained-array topology RES_HEAD_RESISTANCE_NOTE quantifies.
RES_RESIZE_NOTE = (
    "RES_HEAD_RESISTANCE_NOTE's finding -- that this flow's own multi-"
    "primitive R2A/R2B/R1 decomposition pays the fixed per-instance head "
    "offset once per drawn primitive, not once per logical device -- is a "
    "real electrical effect on the fabricated part, not just an LVS "
    "value mismatch (issue #98/DR-003, sim/res-array-head-resistance/). "
    "At the pre-resize n_r2=54 that makes the REAL chained topology's "
    "K = R2/R1 read 8.1474 against design/bandgap_core.sch's single-"
    "device model of 7.4973, pushing VOUT(27 degC) to ~1.233 V (outside "
    "the draft +/-1% window) at all 5 PVT corners and collapsing "
    "regulation at ff/2.97 V and fs/2.97 V. Issue #99 (DR-003's closure, "
    "PR #105) resizes n_r2 54 -> 50 in design/bandgap_core.sch against "
    "that real chained topology -- verified with a real-SPICE harness "
    "that chains res_high_po unit instances at this flow's own "
    "decomposition into the core testbench, not the single-device model "
    "-- bringing K back to 7.576 and VOUT(27 degC) to ~1.198 V, in-spec "
    "and collapse-free at all 5 corners (sim/res-array-resize/records/"
    "20260805-204809-2c83c7a.md). n_r1 stays at 7: holding R1 (and so the "
    "branch current) fixed corrects K without raising the hot-corner "
    "headroom demand the collapse depends on. That record's own "
    "'Layout follow-up' explicitly deferred re-transcribing this file's "
    "N_R1/N_R2_COARSE/SCH_N_R2 to the resized decomposition and re-"
    "running DRC/LVS as the next increment, per this project's one-lever-"
    "per-increment discipline -- done here, issue #108. See item 19 in "
    "this module's own docstring and layout/matching-plan.md Section 7y "
    "for the drawn-side consequence (rows fold, LVS mismatch delta)."
)
#: Why r_lseg_trim (and only r_lseg_trim) halved 1 -> 0.5, and why
#: N_R2_COARSE had to move again (46 -> 48) to keep it. Not a layout-side
#: finding -- transcribes DR-002's "Revision (issue #106 -- chained
#: fine-trim LSB)" re-partition, propagated into this file's own drawn
#: decomposition by issue #112.
RES_TRIM_LSB_NOTE = (
    "DR-002's original per-code LSB derivation (~1.72 mV/code) simulated "
    "the fine trim ladder as ONE length-tapped device per leg -- the "
    "schematic-level approximation design/bandgap_core.sch's XR2A/XR2B "
    "still draw. This flow's own chained topology is not that: `res_trim` "
    "chains N_R2_TRIM_UNITS=20 separately-contacted unit instances per "
    "leg, so a downward trim code does not shorten one device's body by "
    "r_lseg_trim -- it removes a whole separately-contacted unit instance, "
    "paying that instance's fixed per-instance head/end resistance "
    "(RES_HEAD_RESISTANCE_NOTE's rhead ~379.7 ohm) in addition to its "
    "r_lseg_trim of body. Issue #106 measured the real per-code step at "
    "the adopted n_r1=7/n_r2=50 sizing (issue #99) against DR-002's own "
    "<=3.000 mV/code comfort bound (25% of the +/-1% window's 12 mV "
    "half-width), over the same 5-corner PVT set "
    "sim/trim-range-monotonicity/ and issue #99's AC3 used: at the shipped "
    "r_lseg_trim=1 um the chained topology reads 3.123-3.146 mV/code -- a "
    "real, measured violation at every corner, not merely a carried-over "
    "assumption (sim/trim-lsb-chained/records/). Because rhead is a fixed "
    "PDK model-card constant per removed unit instance, independent of "
    "the unit's drawn body length, halving r_lseg_trim to 0.5 um does not "
    "halve the per-code step -- it removes enough of the scaling rbody "
    "(sheet/fringe, ~324.8 ohm/um) term to bring the step from 704.53 to "
    "542.12 ohm/code, restoring the LSB to 2.403-2.421 mV/code, "
    "comfortably under the bound at every corner, with monotonicity and "
    "the downward-span coverage target unaffected (both already PASS). "
    "The fine ladder's unit COUNT (N_R2_TRIM_UNITS=20) and DR-002's "
    "certified 0..-16 downward code range are unchanged -- this is a pure "
    "re-partition of the fixed 250 um leg length between its coarse and "
    "fine segments, not a resize of n_r1/n_r2 (RES_RESIZE_NOTE's lever) "
    "or a change to the certified code range. Holding the untrimmed leg "
    "fixed at `5*N_R2_COARSE + 0.5*N_R2_TRIM_UNITS == 250` forces "
    "N_R2_COARSE 46 -> 48. `design/bandgap_core.sch`'s `.param "
    "r_lseg_trim` moved 1 -> 0.5 in issue #106/PR #111; this file's own "
    "R_LSEG_TRIM_UM/SCH_R_LSEG_TRIM_UM/N_R2_COARSE re-transcription and "
    "the routed layout's klt DRC/LVS re-verification were explicitly "
    "deferred there (DR-002's Revision section, 'Scope of this "
    "revision') as the next one-lever-per-increment step -- done here, "
    "issue #112. See item 21 in this module's own docstring."
)
#: Why n_r2 moved again, 50 -> 51, and why N_R2_COARSE followed it 48 -> 49.
#: Not a layout-side finding -- transcribes issue #178's schematic-side
#: sizing decision, which is itself a consequence of finally MODELLING the
#: chained topology RES_HEAD_RESISTANCE_NOTE quantifies instead of sizing
#: around it.
RES_HEAD_SIZING_NOTE = (
    "DR-003 (RES_HEAD_RESISTANCE_NOTE) established that this flow's drawn "
    "decomposition pays the model card's per-instance head/end resistance "
    "once per separately-contacted primitive, and issue #99 resized n_r2 "
    "54 -> 50 so the DRAWN part's K = R2/R1 landed in spec. What it did "
    "NOT do was model that chain in design/bandgap_core.sch, whose "
    "XR1/XR2A/XR2B lines stayed single-device -- so the schematic-level "
    "harness simulated a K about 9% below the drawn part's and read "
    "VOUT(27 degC) ~1.165 V, ~36 mV low. Issue #178 closes that: the "
    "schematic now carries an EXACT lumped equivalent of the N-instance "
    "chain (a body device plus a replica whose drop is multiplied by N-1, "
    "verified identical to an explicit 143-instance chain to 7 significant "
    "figures over the whole -40..125 degC sweep), and with one model "
    "describing both representations n_r2 was re-derived against DR-005's "
    "RATIFIED +/-2 % untrimmed accuracy row (1.176-1.224 V) rather than "
    "the superseded draft +/-1 % window: n_r2=50 leaves vref_min ~1.3 mV "
    "under the floor at every corner, n_r2=52 puts vref_max over the "
    "ceiling at 6 of 15 (process, supply) points, and n_r2=51 sits inside "
    "with 10.0 mV bottom / 6.2 mV top margin at all 15 while cutting box "
    "TC from 175-182 to 142-159 ppm/degC. n_r1 stays at 7 for "
    "RES_RESIZE_NOTE's reason (branch current, hot-corner headroom); no "
    "operating-point collapse is seen at ff/2.97 V or fs/2.97 V at either "
    "n_r2=51 or 52. Drawn-side consequence, and the only one: holding "
    "`5*N_R2_COARSE + 0.5*N_R2_TRIM_UNITS == 5*SCH_N_R2` at the new "
    "SCH_N_R2=51 moves N_R2_COARSE 48 -> 49 (255 um/leg). The fine "
    "ladder's unit count, DR-002's certified 0..-16 downward range and "
    "every other drawn parameter are untouched. Evidence: "
    "sim/output-voltage-tc/records/ (45-point PVT, schematic) and "
    "sim/output-voltage-tc-post-layout/records/ (extracted)."
)

# ---------------------------------------------------------------------------
# Floorplan geometry constants (um)
# ---------------------------------------------------------------------------
#: Outward `direction_deg` each `klt gen` port family faces.
DIRECTION_EAST = 0
DIRECTION_NORTH = 90
DIRECTION_WEST = 180

BLOCK_MARGIN_UM = 16.0  # clearance between blocks placed side by side in a row
ROW_MARGIN_UM = 22.0  # clearance between stacked rows
RING_MARGIN_UM = 8.0  # clearance between the composed content and the outer ring
RING_WIDTH_UM = 2.0
RING_CONTACTS_PER_SIDE = 8
ROUTE_WIDTH_UM = 0.5

# sky130 recognition layers used by the PNP overlay. Both are read straight
# out of the same tool's own published contract -- the sky130 extraction
# deck's `BipolarDevice(base=(64, 20), emitter=(65, 20), marker=(82, 44))`
# entry and its `tap` layer -- not invented here.
PNP_MARKER_LAYER = [82, 44]
NWELL_TAP_LAYER = [65, 44]
#: Margin (um) the 82/44 marker extends past the emitter pad on every side.
#: Must be > 0 (the extractor needs base to strictly enclose emitter, or
#: KLayout raises "Terminal 'C' ... isn't connected") and small enough to
#: stay clear of the adjacent base-tie pad, which sits one
#: min-same-layer-spacing (0.4 um) away.
PNP_MARKER_MARGIN_UM = 0.15
#: Margin (um) the 65/44 nwell tap extends past the base-tie contact.
NWELL_TAP_MARGIN_UM = 0.05

# ---------------------------------------------------------------------------
# Schematic parameters, transcribed from design/bandgap_core.sch's CORE_PARAMS
# and design/error_amp.sch. Every block's generator params below are derived
# from these, so a schematic parameter change is a one-line edit here.
# ---------------------------------------------------------------------------
N_PNP_CTAT = 8
N_PNP_PTAT = 8
#: The sky130 poly-resistor flavour design/bandgap_core.sch specifies
#: (`sky130_fd_pr__res_high_po`), as the `klt gen res_array` `flavor` param
#: names it and as the extraction deck's `ResistorDevice.name` reports it.
RES_FLAVOR = "high"
RES_CLASS = "res_high_po"
R_W_UM = 1.0
R_LSEG_UM = 5.0
#: Fine trim-unit body length (um), design/bandgap_core.sch's
#: `r_lseg_trim=0.5` (halved 1 -> 0.5 by issue #106/PR #111 to restore
#: DR-002's chained-topology LSB comfort bound; see RES_TRIM_LSB_NOTE).
R_LSEG_TRIM_UM = 0.5
#: Held at 7, unchanged by issue #99/#108's n_r2 resize: DR-003's closure
#: deliberately left n_r1 fixed so the resize corrects K = R2/R1 without
#: raising the branch current (and therefore the hot-corner headroom the
#: ff/2.97V, fs/2.97V regulation-collapse margin depends on). See
#: RES_RESIZE_NOTE.
N_R1 = 7
#: The R2 divider leg's **drawn** decomposition (issue #91, re-transcribed
#: to the resized sizing by issue #108, then re-partitioned by issue #112
#: when the fine unit's drawn length halved). The schematic states one
#: length per leg -- `L = r_lseg*n_r2 + r_lseg_trim*n_r2_trim` = 5*50 +
#: 0.5*0 = 250 um at DR-002's untrimmed code 0 (n_r2=50 since issue #99/
#: PR #105; r_lseg_trim halved 1 -> 0.5 by issue #106/PR #111, see
#: RES_TRIM_LSB_NOTE) -- and the layout has to reproduce *that* number
#: while still offering DR-002's downward-only trim codes. It does so by
#: splitting the 250 um, not by adding to it: 48 coarse 5 um units
#: (240 um) in `res_r2` plus 20 fine 0.5 um units (10 um) in `res_trim`.
#: Joining the leg's low node at the far end of the fine chain is then
#: exactly 250 um = code 0, and every tap short of that end *subtracts*
#: 0.5 um per skipped unit -- the only direction DR-002 permits.
#:
#: Before issue #91 the coarse leg was drawn at the full pre-resize count
#: (54 units, 270 um) and the fine ladder was wired in series *after* it,
#: so the drawn leg was 286 um and every tap moved it further up: trim
#: code +16, which DR-002 rejects outright. See RES_TRIM_LENGTH_NOTE.
#:
#: 48/20 is the coarse count DR-002's revision forces to hold the leg
#: fixed at 250 um: `N_R2_TRIM_UNITS` stays 20 (the revision re-partitions
#: the fixed leg length between coarse and fine segments; it does not
#: touch the fine ladder's unit *count*, so all 20 units -- and DR-002's
#: certified 0..-16 downward range -- are still reachable), so
#: `N_R2_COARSE` has to absorb the 0.5 um/unit reduction across all 20
#: units (10 um) to keep `5*N_R2_COARSE + 0.5*20 == 250`: 46 -> 48. See
#: RES_RESIZE_NOTE for why the leg length itself moved (issue #99) and
#: RES_TRIM_LSB_NOTE for why the fine unit length itself halved
#: (issue #106).
#: 48 -> 49 by issue #178 (n_r2 50 -> 51 re-centres the untrimmed VREF
#: inside DR-005's ratified +/-2 % window once the schematic itself models
#: the chained array's per-instance head resistance -- see
#: design/bandgap_core.sch's CHAINED-ARRAY MODEL / SIZING blocks and
#: RES_HEAD_SIZING_NOTE). The fine ladder's unit count is untouched, so
#: `5*49 + 0.5*20 == 255 == 5*51` still holds the leg at the specified
#: length and DR-002's certified 0..-16 downward range is still reachable.
N_R2_COARSE = 49
N_R2_TRIM_UNITS = 20
#: DR-002's **certified** downward code range (0..-16, per leg). The drawn
#: ladder can express 0..-20 -- codes -17..-20 are drawn metal but outside
#: the range spec/decision-records/DR-002-trim-network-scoping.md certifies,
#: and :func:`trim_tap_ladder` marks them as such rather than offering them
#: as valid.
N_R2_TRIM_CODES = 16
#: The specified side of the same comparison, transcribed verbatim from
#: design/bandgap_core.sch's CORE_PARAMS so :func:`r2_leg_length` can state
#: both sides from one place. Deliberately kept as its own constants rather
#: than folded into the drawn ones above: the whole point of the check is
#: that the drawn decomposition and the specified length are independent
#: statements that must agree.
SCH_R_LSEG_UM = 5.0  # .param r_lseg=5
#: 54 -> 50 by issue #99/PR #105 (DR-003's closure); 50 -> 51 by issue #178
#: (chained-array model + DR-005 re-centring); see RES_RESIZE_NOTE and
#: RES_HEAD_SIZING_NOTE.
SCH_N_R2 = 51  # .param n_r2=51
#: 1 -> 0.5 by issue #106/PR #111 (DR-002's chained-LSB revision); see
#: RES_TRIM_LSB_NOTE.
SCH_R_LSEG_TRIM_UM = 0.5  # .param r_lseg_trim=0.5
SCH_N_R2_TRIM = 0  # .param n_r2_trim=0 (DR-002's untrimmed code)
#: The per-leg length design/bandgap_core.sch specifies, in um (250.0 since
#: the issue #99/#108 resize -- unchanged by issue #112's r_lseg_trim
#: halving, since SCH_N_R2_TRIM=0 makes the trim term a no-op here; was
#: 270.0 before #99/#108).
R2_LEG_SPEC_UM = SCH_R_LSEG_UM * SCH_N_R2 + SCH_R_LSEG_TRIM_UM * SCH_N_R2_TRIM
M_OUT = 2
M_AMPBIAS = 2
#: Halved 16 -> 8 by issue #170 (DR-008 Option B): design/error_amp.sch's
#: `.param amp_m_in=8` -- the amp's own PSRR-band margin increase that
#: absorbs the routed layout's measured -4.05 dB post-layout PSRR shift
#: (DR-008). Smaller input pair means less capacitive loading on D1/D2,
#: which raises the amplifier's own non-dominant-pole frequency and with it
#: psrr_band_min at every schematic-level PVT corner (62.6-66.7 dB baseline
#: -> 70.2-81.5 dB); see error_amp.sch's own header for the full rationale
#: and the levers that were tried and empirically rejected first.
AMP_M_IN = 8
AMP_M_NMIRR = 4
AMP_M_PMIRR = 8
#: MCC, the error amp's Miller compensation cap (design/error_amp.sch,
#: `.param amp_m_cc=16`) -- a `pfet_g5v0d10v5` wired D=S=B=VDD, G=GDRV, so it
#: sits in inversion and behaves as a ~21 pF MOS capacitor at every PVT
#: corner (design/error_amp.sch's own MCC comment block). See
#: MCC_MIM_INFEASIBLE_NOTE for why this is drawn as the MOS cap the
#: schematic states rather than a `cap_mim` overlay.
AMP_M_CC = 16

# ---------------------------------------------------------------------------
# Block definitions. Each maps to one `klt gen` call. `row` groups blocks into
# stacked bands; blocks within a row are placed left-to-right in the order
# listed. Relative to gen_bandgap_floorplan.py's BLOCKS this list differs in
# exactly three ways, each of them load-bearing for this issue:
#
#   * `res_r2` is at its real full-length count (96 coarse units, still 10
#     rows; with `res_trim`'s 40 fine units that is the schematic's 250
#     um/leg, the issue #106/#112-repartitioned sizing -- was 92 coarse
#     units before, and 100 coarse units/270 um-leg before that (issue
#     #99/#108), same 10-row fold every time).
#   * every guard/collector ring is back **on**, each with a routing opening
#     (upstream klayout-tools#441's `ring_gap_side`), retiring the PR #64
#     trade-off recorded in layout/matching-plan.md Section 5a.
#   * each block declares the intra-block `bus` its matched group needs, drawn
#     on met1 (MET1_BUS_NOTE). A block with no `bus` entry is one whose units
#     cannot be bussed at all today -- every MOS group, for the gate-contact
#     reason in MOS_GATE_NOTE.
# ---------------------------------------------------------------------------
BLOCKS: list[dict[str, Any]] = [
    {
        "id": "pnp_ctat",
        "row": 0,
        "align": "bottom",
        "generator": "bjt_array",
        "params": {
            "emitter_um": 0.68,
            "rows": 2,
            "cols": 4,
            "dummy": 1,
            "ratio": 8,
            "topology": "common_centroid",
            "add_collector_ring": True,
            "ring_gap_side": "N",
            "ring_gap_um": 2.0,
        },
        "bus": {"kind": "bjt_parallel", "nets": {"_E": "VA", "_B": "VSS"}},
        "matched_group_label": "Q1 (CTAT PNP, small unit W0p68L0p68)",
        "real_target": f"m={N_PNP_CTAT} sky130_fd_pr__pnp_05v5_W0p68L0p68 "
        "(design/bandgap_core.sch); drawn 1:1 (8 real units, 2x4 "
        "common-centroid)",
    },
    {
        "id": "res_r2",
        "row": 0,
        "generator": "res_array",
        "params": {
            "length_um": R_LSEG_UM,
            "width_um": R_W_UM,
            "spacing_um": 0.5,
            "flavor": RES_FLAVOR,
            "num": 2 * N_R2_COARSE,
            "dummy": 2,
            # Kept at 10 (unchanged from the pre-resize 100-unit count),
            # empirically re-verified against both the issue #108 resize's
            # 92-unit count and (this increment, issue #112) the 96-unit
            # count DR-002's r_lseg_trim revision forces, rather than
            # re-derived from a divisibility rule each time. `res_array`'s
            # `rows` fold (2AMLogic/klayout-tools#415/#418) does NOT require
            # an exact divisor of `num` -- klt happily folds a remainder into
            # a shorter last row -- but this repo's OWN `bus_res_series`
            # (below), which draws the fold-TURN met1 jumper at each row
            # boundary as a hand-routed corner hop, is not guaranteed
            # fold-shape-agnostic: at the 92-unit count, re-running the full
            # routed flow at every divisor of 92 (2, 4, 23, 46) put the
            # composed cell over the 50,000 um^2 budget in every case, and a
            # scan of nearby non-divisor counts found two (9, 11) where a
            # subset of leg-1 fold-turn hops fail to route (bus-summary.json's
            # `res_r2.links` reports `"routed": false`), splitting R2B's
            # series chain and taking `klt lvs`'s `mismatch_count` from 1 to
            # 15-18 -- a real connectivity defect, not a value mismatch. 10
            # was re-verified clean at 92 (issue #108) and, this increment,
            # re-verified again at the new 96-unit count: all 94 fold-turn
            # links route with zero failures, zero drawn-short conflicts,
            # DRC clean, and `mismatch_count=1` (just the deliberately-
            # undrawn MMCC); the composed cell lands at 45,968 um^2, matching
            # every prior increment's figure exactly (the 4 extra coarse
            # units' length is offset by the fine ladder's 40 units each
            # shrinking 0.5 um). See RES_RESIZE_NOTE for why N_R2_COARSE
            # first moved (issue #99/#108) and RES_TRIM_LSB_NOTE for why it
            # moved again (issue #106/#112).
            "rows": 10,
        },
        "bus": {"kind": "res_series", "legs": 2},
        "matched_group_label": "R2A/R2B interdigitated ladder (K = R2/R1 divider)",
        "real_target": f"{N_R2_COARSE} coarse {R_LSEG_UM:.0f}um segments PER "
        f"LEG x 2 legs = {2 * N_R2_COARSE} total = "
        f"{R_LSEG_UM * N_R2_COARSE:.0f} um/leg, the coarse part of "
        f"design/bandgap_core.sch's {R2_LEG_SPEC_UM:.0f} um "
        f"(`r_lseg*n_r2` at n_r2={SCH_N_R2}); the remaining "
        f"{R_LSEG_TRIM_UM * N_R2_TRIM_UNITS:.0f} um is `res_trim`'s fine "
        "ladder, so the trim taps subtract from the specified length instead "
        "of adding to it (issue #91). The skeleton's 16-unit reduction is "
        "closed by `res_array`'s `rows` fold parameter "
        "(2AMLogic/klayout-tools#415, merged via #418)",
    },
    {
        "id": "res_trim",
        "row": 0,
        "align": "top",
        "generator": "res_array",
        "params": {
            "length_um": R_LSEG_TRIM_UM,
            "width_um": R_W_UM,
            "spacing_um": 0.5,
            "flavor": RES_FLAVOR,
            "num": 2 * N_R2_TRIM_UNITS,
            "dummy": 2,
            "rows": 4,
        },
        "bus": {"kind": "res_series", "legs": 2},
        "matched_group_label": "Downward-only trim ladder taps (both legs)",
        "real_target": f"{N_R2_TRIM_UNITS} fine {R_LSEG_TRIM_UM:.1f}um units "
        f"PER LEG x 2 legs = {2 * N_R2_TRIM_UNITS} unit taps, the fine part "
        f"of the same {R2_LEG_SPEC_UM:.0f} um leg -- code 0 puts all "
        f"{N_R2_TRIM_UNITS} in circuit and code -k skips k of them, so the "
        f"ladder spans 0..-{N_R2_TRIM_UNITS} of which DR-002 certifies "
        f"0..-{N_R2_TRIM_CODES} (design/bandgap_core.sch CORE_PARAMS, "
        "DR-002); drawn 1:1",
    },
    {
        "id": "res_r1",
        "row": 0,
        "align": "top",
        "generator": "res_array",
        "params": {
            "length_um": R_LSEG_UM,
            "width_um": R_W_UM,
            "spacing_um": 0.5,
            "flavor": RES_FLAVOR,
            "num": N_R1,
            "dummy": 2,
            "rows": 1,
        },
        "bus": {"kind": "res_series", "legs": 1},
        "matched_group_label": "R1 (dVBE-to-current leg)",
        "real_target": f"n_r1={N_R1} unit segments (design/bandgap_core.sch); "
        "drawn 1:1",
    },
    {
        "id": "pnp_ptat",
        "row": 0,
        "align": "bottom",
        "generator": "bjt_array",
        "params": {
            "emitter_um": 3.40,
            "rows": 2,
            "cols": 4,
            "dummy": 1,
            "ratio": 8,
            "topology": "common_centroid",
            "add_collector_ring": True,
            "ring_gap_side": "N",
            "ring_gap_um": 2.0,
        },
        "bus": {"kind": "bjt_parallel", "nets": {"_E": "VBQ", "_B": "VSS"}},
        "matched_group_label": "Q2 (PTAT PNP, large unit W3p40L3p40)",
        "real_target": f"m={N_PNP_PTAT} sky130_fd_pr__pnp_05v5_W3p40L3p40 "
        "(design/bandgap_core.sch); drawn 1:1 (8 real units, 2x4 "
        "common-centroid)",
    },
    {
        "id": "core_mirror",
        "row": 1,
        "generator": "diff_pair",
        "params": {
            "w_um": 8.0,
            "l_um": 2.0,
            "splits": M_OUT,
            "flavor": "pfet",
            "mirror": True,
            "add_guard_ring": True,
            "ring_gap_side": "W",
            "ring_gap_um": 2.0,
        },
        "bus": {
            "kind": "mos_comb",
            "spine_side": "W",
            "nets": [
                {"net": "VDD",
                 "terminals": [("MPOUT", "source"), ("MPAMP", "source")]},
                {"net": "GDRV",
                 "terminals": [("MPOUT", "gate"), ("MPAMP", "gate")]},
                {"net": "TAIL", "terminals": [("MPAMP", "drain")]},
                {"net": "VOUT", "terminals": [("MPOUT", "drain")]}
            ],
        },
        "matched_group_label": "MPOUT/MPAMP (core PMOS output/bias mirror)",
        "real_target": f"m_out=m_ampbias={M_OUT}, W=8 L=2 "
        "(design/bandgap_core.sch); drawn 1:1",
    },
    {
        "id": "amp_input_pair",
        "row": 1,
        "generator": "diff_pair",
        "params": {
            "w_um": 20.0,
            "l_um": 10.0,
            "splits": AMP_M_IN,
            "flavor": "pfet",
            "mirror": False,
            "add_guard_ring": True,
            "ring_gap_side": "W",
            "ring_gap_um": 2.0,
        },
        "bus": {
            "kind": "mos_comb",
            "spine_side": "W",
            "nets": [
                {"net": "D1", "terminals": [("MP1", "drain")]},
                {"net": "D2", "terminals": [("MP2", "drain")]},
                {"net": "VB", "terminals": [("MP1", "gate")]},
                {"net": "VA", "terminals": [("MP2", "gate")]},
                {"net": "TAIL",
                 "terminals": [("MP1", "source"), ("MP2", "source")]}
            ],
        },
        "matched_group_label": "MP1/MP2 (amp PMOS input pair)",
        "real_target": f"amp_m_in={AMP_M_IN}, W=20 L=10 "
        "(design/error_amp.sch); drawn 1:1 -- the dominant mismatch "
        "contributor per layout/matching-plan.md Section 1",
    },
    {
        "id": "amp_nload",
        "row": 1,
        "generator": "diff_pair",
        "params": {
            "w_um": 8.0,
            "l_um": 20.0,
            "splits": AMP_M_NMIRR,
            "flavor": "nfet",
            "mirror": True,
            "add_guard_ring": True,
            "ring_gap_side": "W",
            "ring_gap_um": 2.0,
        },
        "bus": {
            "kind": "mos_comb",
            "spine_side": "E",
            "nets": [
                {"net": "D1",
                 "terminals": [("MN1", "drain"), ("MN1", "gate")]},
                {"net": "D2",
                 "terminals": [("MN2", "drain"), ("MN2", "gate")]},
                {"net": "VSS",
                 "terminals": [("MN1", "source"), ("MN2", "source")]}
            ],
        },
        "matched_group_label": "MN1/MN2 (amp NMOS diode loads)",
        "real_target": f"amp_m_nmirr={AMP_M_NMIRR}, W=8 L=20 "
        "(design/error_amp.sch); drawn 1:1",
    },
    {
        "id": "amp_pmirr",
        "row": 2,
        "generator": "diff_pair",
        "params": {
            "w_um": 6.0,
            "l_um": 20.0,
            "splits": AMP_M_PMIRR,
            "flavor": "pfet",
            "mirror": True,
            "add_guard_ring": True,
            "ring_gap_side": "W",
            "ring_gap_um": 2.0,
        },
        "bus": {
            "kind": "mos_comb",
            "spine_side": "W",
            "nets": [
                {"net": "GDRV", "terminals": [("MP4", "drain")]},
                {"net": "PN",
                 "terminals": [("MP3", "drain"), ("MP3", "gate"),
                               ("MP4", "gate")]},
                {"net": "VDD",
                 "terminals": [("MP3", "source"), ("MP4", "source")]}
            ],
        },
        "matched_group_label": "MP3/MP4 (amp PMOS mirror)",
        "real_target": f"amp_m_pmirr={AMP_M_PMIRR}, W=6 L=20 "
        "(design/error_amp.sch); drawn 1:1",
    },
    {
        "id": "amp_nmirr",
        "row": 2,
        "generator": "diff_pair",
        "params": {
            "w_um": 8.0,
            "l_um": 20.0,
            "splits": AMP_M_NMIRR,
            "flavor": "nfet",
            "mirror": True,
            "add_guard_ring": True,
            "ring_gap_side": "W",
            "ring_gap_um": 2.0,
        },
        "bus": {
            "kind": "mos_comb",
            "spine_side": "E",
            "nets": [
                {"net": "GDRV", "terminals": [("MN3", "drain")]},
                {"net": "PN", "terminals": [("MN4", "drain")]},
                {"net": "D1", "terminals": [("MN3", "gate")]},
                {"net": "D2", "terminals": [("MN4", "gate")]},
                {"net": "VSS",
                 "terminals": [("MN3", "source"), ("MN4", "source")]}
            ],
        },
        "matched_group_label": "MN3/MN4 (amp NMOS mirror outputs)",
        "real_target": f"amp_m_nmirr={AMP_M_NMIRR}, W=8 L=20 "
        "(design/error_amp.sch); drawn 1:1",
    },
    {
        "id": "amp_cc",
        "row": 3,
        "generator": "diff_pair",
        "params": {
            "w_um": 30.0,
            "l_um": 20.0,
            "splits": AMP_M_CC // 2,
            "flavor": "pfet",
            "mirror": True,
            "add_guard_ring": True,
            "ring_gap_side": "W",
            "ring_gap_um": 2.0,
        },
        "bus": {
            "kind": "mos_comb",
            "spine_side": "W",
            "nets": [
                {"net": "VDD",
                 "terminals": [("MCC_A", "drain"), ("MCC_A", "source"),
                               ("MCC_B", "drain"), ("MCC_B", "source")]},
                {"net": "GDRV",
                 "terminals": [("MCC_A", "gate"), ("MCC_B", "gate")]},
            ],
        },
        "matched_group_label": "MCC (amp Miller compensation cap, "
        "PMOS-as-capacitor)",
        "real_target": f"amp_m_cc={AMP_M_CC}, W=30 L=20 "
        "(design/error_amp.sch); drawn as two mult="
        f"{AMP_M_CC // 2} groups (`MCC_A`/`MCC_B`) tied identically to "
        "VDD (drain+source) and GDRV (gate) so `combine_devices` folds "
        f"them into the schematic's single m={AMP_M_CC} device -- see "
        "MCC_MIM_INFEASIBLE_NOTE for why a `cap_mim` overlay (the "
        "operator's primary-path ruling on issue #62) cannot close this "
        "device instead",
    },
]

#: Why MCC is drawn as the same MOS-as-capacitor device the schematic
#: states, rather than a sky130 `cap_mim` overlay (the operator's
#: 2026-08-11 primary-path ruling on issue #62) -- checked, not assumed,
#: on two independent grounds:
#:
#: 1. **LVS device-class matching.** `reference.spice` states `MMCC` as a
#:    plain `M`-element (`MMCC VDD GDRV VDD VDD pfet L=20U W=30U m=16`), so
#:    `klt lvs` registers it under the deck's `pfet_class` (`"pfet"`,
#:    `DeviceClassMOS4Transistor`, terminals D/G/S/B). A drawn `cap_mim`
#:    overlay extracts as `klayout_tools.decks.sky130`'s
#:    `sky130_fd_pr__model__cap_mim` class instead (a two-terminal
#:    `DeviceClassCapacitor`, P1/P2) -- a different class *name* with a
#:    different terminal arity. `klt lvs` (`src/klayout_tools/lvs.py`,
#:    confirmed by reading `_apply_hints`) exposes no device-class
#:    equivalence declaration (only `hints.same_nets` and
#:    `hints.equivalent_pins`, both net/pin-level); when
#:    `NetlistComparer` pairs devices of different classes it reports
#:    `match_devices_with_different_device_classes`, which
#:    `_build_mismatches` turns into a `device.class`-category mismatch
#:    (still `mismatch_count` >= 1), and when the two classes cannot even
#:    be topologically paired (very likely here: 2-terminal vs. 4-terminal)
#:    each side reports its own unmatched device instead -- `mismatch_count`
#:    2, not fewer. So a `cap_mim` overlay cannot reach `mismatch_count: 0`
#:    against the *current* `reference.spice`, independent of area --
#:    unless the reference netlist's own `MMCC` card is rewritten to a
#:    capacitor model, which would be a schematic-level device-type change
#:    to a closed, sim-verified cell (out of this issue's scope; see the
#:    operator's "Redesign the compensation smaller" note).
#: 2. **Tooling.** The twenty-ninth increment (PR #124, `Part of #62`)
#:    independently confirmed a `cap_mim` overlay is not drawable at all
#:    with the pinned `klt`: neither of sky130's `CapacitorDevice` entries
#:    sets `top_plate_via`/`top_plate_via_metal`, so every reproduction
#:    tried either extracted the two plates as disconnected islands, or
#:    false-shorted them, or left the top plate's via unreachable. Filed as
#:    2AMLogic/klayout-tools#775; see `layout/matching-plan.md` Section 7bb
#:    and `spec/decision-records/DR-007-mcc-area-budget.md` for the full
#:    reproduction.
#:
#: Both findings independently rule out the MIM-overlay path today --
#: (1) would still block even if (2) is fixed upstream, since it is a
#: netlist-shape fact about `klt lvs`'s comparer, not a drawing-capability
#: gap. This increment therefore proceeds straight to the ruling's own
#: fallback: draw MCC in-plane as the MOS cap it already is in
#: design/error_amp.sch.
MCC_MIM_INFEASIBLE_NOTE = (
    "MCC is drawn as a pfet_g5v0d10v5 MOS-as-capacitor (matching "
    "design/error_amp.sch exactly), not a cap_mim overlay. Two "
    "independent reasons: (1) `reference.spice`'s MMCC card is a plain "
    "pfet M-element, and `klt lvs` has no device-class equivalence "
    "mechanism -- a cap_mim overlay would extract under a different "
    "device class (sky130_fd_pr__model__cap_mim, 2-terminal) and could "
    "not reach mismatch_count: 0 against it regardless of area, only "
    "recategorize or double the one mismatch; (2) PR #124 (issue #62's "
    "twenty-ninth increment) independently found sky130's cap_mim device "
    "recognition cannot wire a top plate out to routing metal without "
    "either a false short or a disconnected net with the currently "
    "pinned klt (2AMLogic/klayout-tools#775, filed). See "
    "layout/matching-plan.md Section 7bb/7cc and "
    "spec/decision-records/DR-007-mcc-area-budget.md."
)

#: Empty since issue #62's fourteenth increment (see SUBSTRATE_NET_NOTE).
#: Through the thirteenth increment this named a `hints.same_nets`
#: declaration (`[["vsubs", "VSS"]]`) because sky130's curated deck
#: synthesized an undrawable `vsubs` net and no drawn shape could join it.
#: klayout-tools#495 (picked up at the fourteenth increment's `klt` pin
#: bump) resolves the deck's substrate identity to a real drawn tap when one
#: is present -- and this layout already draws one, wired to `VSS` -- so the
#: layout side no longer has a `vsubs` net at all. Leaving the stale
#: declaration in `hints.same_nets` after that pin bump is not a no-op: `klt
#: lvs` hard-errors with `hints.same_nets: layout net 'vsubs' not found`
#: instead of running, which is what shipping the pin bump without this
#: change produced (see this increment's own PR description for the
#: measurement). Kept as a named, typed constant (rather than deleted
#: outright) so a future floorplan revision that stops drawing every
#: substrate tap has an obvious place to reintroduce the declaration, with a
#: test that would catch the regression before a flow run does.
SUBSTRATE_SAME_NETS: list[list[str]] = []

MCC_AREA_UM2_NOTE = (
    "MCC (amp compensation cap, amp_m_cc=16 x W=30 x L=20 = 9600 um^2 "
    "analytic) is now drawn, as of issue #62's thirtieth increment -- see "
    "the `amp_cc` block above and MCC_MIM_INFEASIBLE_NOTE for why it is a "
    "MOS-as-capacitor block rather than a cap_mim overlay. Drawing it pushes "
    "the composed cell over the ratified 50,000 um^2 (DR-005) Area budget; "
    "see spec/decision-records/DR-007-mcc-area-budget.md (proposed, not "
    "ratified) and this record's own `within_budget` gate result"
)


# ---------------------------------------------------------------------------
# klt drivers
# ---------------------------------------------------------------------------
# run_klt_json() and klt_gen() live in layout_common.py (issue #169) --
# imported above, alongside met1_bus.


# ---------------------------------------------------------------------------
# Intra-block bussing / inter-block routing
# ---------------------------------------------------------------------------
# Moved to bus_routing.py (issue #221) -- the file's own section banners at
# this position marked it as a self-delimited concern (see this docstring's
# item 5 and item 13). bus_routing.py imports several names (DIRECTION_EAST,
# DIRECTION_WEST, N_R1, N_R2_COARSE, N_R2_TRIM_UNITS, ...) back from *this*
# module at its own top level, to build its own module-level tables
# (MOS_HALVES, INTER_BLOCK_MET1). This file's own uses of bus_routing's
# symbols (`build_bus_overlay`, `trim_tap_port`, `MOS_HALVES`) are therefore
# each imported locally, inside the function that needs them
# (trim_tap_ladder(), compose_inner(), main()), rather than at this file's
# own top level -- a top-level import here would race bus_routing.py's own
# top-level import of this module, and whichever module a caller happens to
# import first would hit the other one mid-load. See bus_routing.py's own
# docstring for the full list of what moved.


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------
def place_blocks(
    blocks: list[dict[str, Any]], reports: dict[str, dict[str, Any]]
) -> dict[str, dict[str, float]]:
    """Compute an `origins_um` dict for `gen-compose`'s "explicit" strategy.

    Rows are stacked bottom-to-top in `row` order and each row's blocks are
    laid out left-to-right, **vertically centered on the row's own midline**
    rather than bottom-aligned. That centering is what makes an inter-block
    route feasible at all: `klt gen-compose` routes a west-facing `_S`/`_A`
    port to an east-facing `_D`/`_B` port through a single jog, and rejects
    the route outright when the jog would cross a third block's bbox. Rows
    are also spaced with a wide ROW_MARGIN_UM channel so a cross-row route
    has somewhere to go.

    Every number is derived from the blocks' own reported `bbox_um`, never a
    hardcoded coordinate -- so this recomputes correctly if a BLOCKS entry's
    params change.
    """
    rows: dict[int, list[str]] = {}
    alignments: dict[str, str] = {}
    for block in blocks:
        rows.setdefault(block["row"], []).append(block["id"])
        alignments[block["id"]] = block.get("align", "center")

    row_geometry: dict[int, dict[str, float]] = {}
    for row_index, ids in rows.items():
        width = sum(
            reports[bid]["bbox_um"]["x1"] - reports[bid]["bbox_um"]["x0"] for bid in ids
        )
        width += BLOCK_MARGIN_UM * (len(ids) - 1)
        height = max(
            reports[bid]["bbox_um"]["y1"] - reports[bid]["bbox_um"]["y0"] for bid in ids
        )
        row_geometry[row_index] = {"width": width, "height": height}

    overall_width = max(g["width"] for g in row_geometry.values())

    origins: dict[str, dict[str, float]] = {}
    y_cursor = 0.0
    for row_index in sorted(rows):
        ids = rows[row_index]
        row_width = row_geometry[row_index]["width"]
        row_height = row_geometry[row_index]["height"]
        x_cursor = (overall_width - row_width) / 2.0  # center this row
        for bid in ids:
            bbox = reports[bid]["bbox_um"]
            block_width = bbox["x1"] - bbox["x0"]
            block_height = bbox["y1"] - bbox["y0"]
            # Vertical alignment within the row's band. "center" (the
            # default) keeps a west/east port pair between two neighbours on
            # a short jog. "top"/"bottom" exist for one specific, load-bearing
            # reason: a `bjt_array`'s only ports face *north*, so a route into
            # one must descend onto the array from above -- which the router
            # only accepts when the other end's port sits at a y *above* the
            # array's top edge. Pushing the PNP arrays to the bottom of their
            # band and their partner resistor block to the top is what makes
            # that vertical approach legal instead of a rejected
            # plow-through-the-interior backbone.
            align = alignments.get(bid, "center")
            if align == "bottom":
                y_offset = y_cursor
            elif align == "top":
                y_offset = y_cursor + (row_height - block_height)
            else:
                y_offset = y_cursor + (row_height - block_height) / 2.0
            origins[bid] = {"x": x_cursor - bbox["x0"], "y": y_offset - bbox["y0"]}
            x_cursor += block_width + BLOCK_MARGIN_UM
        y_cursor += row_height + ROW_MARGIN_UM

    return origins


# union_bbox() lives in layout_common.py (issue #169) -- imported above.


# ---------------------------------------------------------------------------
# Connectivity
# ---------------------------------------------------------------------------
#: Port-name suffix families each block flavour exposes, and the outward
#: `direction_deg` each faces. `klt gen`'s own generators report these; this
#: table is only a readable index into them, never a second source of truth
#: (every lookup below validates against the block's reported `ports[]`).
#: How many candidate ports per side the router-oracle search below will try
#: before giving up on a net. Kept small: the candidates are ordered by how
#: close they sit to the block edge the route approaches from, so the right
#: one is normally the first or second.
PORT_CANDIDATE_LIMIT = 6


def select_ports(
    report: dict[str, Any],
    suffix: str,
    facing: int,
    toward: str,
    limit: int = PORT_CANDIDATE_LIMIT,
    half: str | None = None,
) -> list[str]:
    """Ordered candidate port names on one block, best-first for a route
    approaching from `toward` ("east"/"west"/"north"/"south").

    `klt gen-compose`'s router draws a straight/single-jog Manhattan backbone
    between two ports and rejects the net outright when that backbone crosses
    a block's interior by more than the port's own edge margin. Which port of
    a 100-segment ladder or a 16-way split pair is chosen therefore decides
    whether a net routes at all -- the one nearest the edge the route arrives
    at is the only one whose approach stays outside the block.

    Ordering is purely geometric (the block's own reported port positions);
    the router itself remains the pass/fail authority, consulted by
    `resolve_connectivity`.
    """
    ports = [
        p
        for p in report["ports"]
        if p["name"].endswith(suffix)
        and int(p.get("direction_deg", 0)) % 360 == facing
        and (half is None or p["name"].startswith(f"{half}_"))
    ]
    if not ports:
        raise KeyError(
            f"no '{suffix}' ports facing {facing} deg "
            f"{'half ' + half + ' ' if half else ''}"
            f"(available: {sorted({q['name'] for q in report['ports']})})"
        )
    key = {
        "east": lambda p: -float(p["x_um"]),
        "west": lambda p: float(p["x_um"]),
        "north": lambda p: -float(p["y_um"]),
        "south": lambda p: float(p["y_um"]),
    }[toward]
    ports.sort(key=key)
    return [p["name"] for p in ports[:limit]]



#: Label-only pin promotions (`pins[]`), i.e. nodes made addressable from a
#: post-layout testbench (issue #16) without any claim of connectivity: a
#: `pins[]` entry draws a label, never a wire.
#:
#: The eight gate entries this list used to carry are **gone**. They existed
#: because a MOS gate could not be wired at all (MOS_GATE_NOTE), so each
#: gate node could only be named -- with a deliberately different name
#: (`GDRV_GATE`, `VA_GATE`, ...) from the schematic node it belonged to, so
#: that two disconnected pieces of metal could not be labelled alike and
#: merged by `klt extract`. With 2AMLogic/klayout-tools#461 merged, every one
#: of those nodes is drawn metal carrying its own schematic name (see
#: INTER_BLOCK_MET1), and re-labelling their pads here would do exactly the
#: damage `routed_ports` exists to prevent.
#:
#: What remains is the trim ladder's read-only probe taps, which are genuinely
#: single-port nodes no schematic net reaches (see :func:`trim_tap_ladder`).
CORE_PIN_LABELS: list[dict[str, Any]] = []


#: The bar criterion 1 is measured against: every node of
#: design/bandgap_core.sch (+ design/error_amp.sch) that joins devices living
#: in *different* layout blocks, with the set of blocks the schematic says it
#: must reach. This is deliberately independent of CORE_NETS -- scoring
#: "9/9 declared nets routed" measures the flow against its own declaration,
#: which is not what issue #62 asks for. `hops` names the CORE_NETS entries
#: that carry this node's label; a node counts as fully drawn only when the
#: blocks those routed hops actually touch cover `blocks`.
SCHEMATIC_INTER_BLOCK_NETS: list[dict[str, Any]] = [
    {
        "net": "VA",
        "blocks": ["pnp_ctat", "res_trim", "amp_input_pair"],
        "hops": ["VA"],
        "schematic": "Q1 emitter + R2A low end (which the layout splits into "
        "ladder + DR-002 trim taps, so the low end sits on res_trim) + MP2 "
        "gate (amp VINN)",
    },
    {
        "net": "VB",
        "blocks": ["res_trim", "res_r1", "amp_input_pair"],
        "hops": ["VB"],
        "schematic": "R2B low end (through the trim taps) + R1 head + MP1 "
        "gate (amp VINP)",
    },
    {
        "net": "TRIM",
        "blocks": ["res_r2", "res_trim"],
        "hops": ["TRIM_A", "TRIM_B"],
        "schematic": "layout-internal split of both R2 legs into ladder + "
        "DR-002 trim taps (one device per leg in the schematic)",
    },
    {
        "net": "VBQ",
        "blocks": ["res_r1", "pnp_ptat"],
        "hops": ["VBQ"],
        "schematic": "R1 tail + Q2 emitter",
    },
    {
        "net": "VOUT",
        "blocks": ["core_mirror", "res_r2"],
        "hops": ["VOUT"],
        "schematic": "MPOUT drain + both R2A/R2B tops (the reference output)",
    },
    {
        "net": "GDRV",
        "blocks": ["core_mirror", "amp_pmirr", "amp_nmirr", "amp_cc"],
        "hops": ["GDRV"],
        "schematic": "amp output (MP4/MN3 drains) + MPOUT/MPAMP gates + "
        "MCC's gate -- one node in the schematic and, since the "
        "gate-contact gap closed, one drawn node in the layout too",
    },
    {
        "net": "TAIL",
        "blocks": ["core_mirror", "amp_input_pair"],
        "hops": ["TAIL"],
        "schematic": "MPAMP drain + MP1/MP2 common source",
    },
    {
        "net": "D1",
        "blocks": ["amp_input_pair", "amp_nload", "amp_nmirr"],
        "hops": ["D1"],
        "schematic": "MP1 drain + MN1 diode + MN3 gate",
    },
    {
        "net": "D2",
        "blocks": ["amp_input_pair", "amp_nload", "amp_nmirr"],
        "hops": ["D2"],
        "schematic": "MP2 drain + MN2 diode + MN4 gate",
    },
    {
        "net": "PN",
        "blocks": ["amp_nmirr", "amp_pmirr"],
        "hops": ["PN"],
        "schematic": "MN4 drain + MP3 diode + MP4 gate",
    },
    {
        "net": "VDD",
        "blocks": ["core_mirror", "amp_input_pair", "amp_pmirr", "amp_cc"],
        "hops": ["VDD"],
        "schematic": "supply trunk: MPOUT/MPAMP sources + MP1/MP2 well side "
        "+ MP3/MP4 sources + MCC drain/source",
    },
    {
        "net": "VSS",
        "blocks": ["amp_nload", "amp_nmirr", "pnp_ctat", "pnp_ptat"],
        "hops": ["VSS"],
        "schematic": "ground trunk: MN1-MN4 sources + both PNPs' base ties. "
        "The three resistor blocks' res_high_po bulk terminals "
        "(design/bandgap_core.sch r2ab/r2bb/r1b) are on this node in the "
        "schematic too, and now resolve to the same real drawn `VSS` net "
        "the rest of this row does (SUBSTRATE_NET_NOTE) -- but not through "
        "a pad this router can target: `res_array` draws no bulk-terminal "
        "pad inside those three blocks for metal to land on, so they stay "
        "uncounted as routing targets here even though the correspondence "
        "itself is no longer in question",
    },
]


def schematic_net_coverage(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Score each schematic inter-block node against the met1 metal actually
    drawn for it.

    `status` is "drawn" only when the drawn nets carrying that node touch
    every block the schematic says the node reaches; "partial" when some but
    not all are joined; "labelled only" when no metal is drawn for it at all
    (the node exists in the layout solely as a promoted pin label).

    Scored against design/bandgap_core.sch's own node list, never against
    this flow's own routing declaration -- a net this flow simply forgot to
    declare has to show up here as a miss.
    """
    # Credit is per *hop*, not per net, and only for blocks that end up in one
    # connected piece of metal. A net whose chain breaks in the middle leaves
    # two disjoint pieces; counting its whole block list would claim
    # connectivity that is not drawn, and counting nothing (what this function
    # did before) throws away the piece that *is*. Union-find over the routed
    # hops, then keep the largest component, states exactly what is joined.
    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(key: tuple[str, str]) -> tuple[str, str]:
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(a: tuple[str, str], b: tuple[str, str]) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    endpoint_block: dict[tuple[str, str], str] = {}
    for route in routes:
        net = route["net"]
        for hop in route.get("hops", []):
            ends = []
            for side in ("from", "to"):
                name = hop.get(side)
                if not name:
                    continue
                block = name.split(".")[0].split(":")[0]
                key = (net, name)
                endpoint_block[key] = block
                find(key)
                ends.append(key)
            if hop.get("routed") and len(ends) == 2:
                union(ends[0], ends[1])

    components: dict[tuple[str, str], set[str]] = {}
    for key, block in endpoint_block.items():
        components.setdefault(find(key), set()).add(block)
    touched: dict[str, set[str]] = {}
    for root, blocks in components.items():
        net = root[0]
        if len(blocks) > len(touched.get(net, set())):
            touched[net] = blocks
    rows = []
    for spec in SCHEMATIC_INTER_BLOCK_NETS:
        want = set(spec["blocks"])
        have: set[str] = set()
        for hop in spec["hops"]:
            have |= touched.get(hop, set())
        joined = want & have
        if joined >= want:
            status = "drawn"
        elif len(joined) >= 2:
            status = "partial"
        else:
            status = "labelled only"
        rows.append(
            {
                "net": spec["net"],
                "schematic": spec["schematic"],
                "blocks": spec["blocks"],
                "joined": sorted(joined),
                "missing": sorted(want - joined),
                "status": status,
            }
        )
    return rows


def r2_leg_length() -> dict[str, Any]:
    """Drawn vs. specified length of one R2 divider leg, in um.

    `klt lvs` can only report a resistor's *value*, and only once the two
    sides pair at all -- which took until issue #62's eighteenth increment
    (INTERNAL_NODE_LABEL_NOTE). This states the same fact in the units the
    schematic actually specifies, unconditionally and from the flow's own
    constants, so it appears in every record whether or not the comparer
    reaches these devices: a future regression in either constant shows up
    here immediately instead of hiding behind an unpaired device.

    `drawn_um` is what the layout puts in series between `VOUT` and `VA`
    (resp. `VB`) **at DR-002 code 0**: the `res_r2` coarse leg plus the whole
    `res_trim` fine leg, because code 0 is the tap at the far end of the fine
    chain (see INTER_BLOCK_MET1's `TRIM_A`/`VA` entries and
    :func:`trim_tap_port`). `spec_um` is design/bandgap_core.sch's own
    `L = r_lseg*n_r2 + r_lseg_trim*n_r2_trim` at that same code.

    The two sides are independent statements -- the drawn constants describe
    a coarse/fine decomposition, the specified one a single length -- so
    `matches` is a real comparison, not a tautology: any change to the fold,
    the unit length or either count moves `drawn_um` alone.
    """
    coarse_um = R_LSEG_UM * N_R2_COARSE
    trim_um = R_LSEG_TRIM_UM * N_R2_TRIM_UNITS
    drawn_um = coarse_um + trim_um
    spec_um = SCH_R_LSEG_UM * SCH_N_R2 + SCH_R_LSEG_TRIM_UM * SCH_N_R2_TRIM
    delta_um = drawn_um - spec_um
    return {
        "coarse_um": coarse_um,
        "trim_um": trim_um,
        "drawn_um": drawn_um,
        "spec_um": spec_um,
        "delta_um": delta_um,
        # The trim code the drawn metal option actually selects, in DR-002's
        # own units. Positive is the direction DR-002 rejects outright.
        "effective_trim_code": round(delta_um / SCH_R_LSEG_TRIM_UM),
        "matches": abs(delta_um) < 1e-9,
    }


def trim_tap_ladder(reports: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Every trim code the drawn metal option can select, per code, with the
    leg length that code yields -- read off the block's own reported ports.

    This is the whole ladder, not just its endpoints, because the ladder's
    *direction* is the thing DR-002 constrains and a two-row table cannot
    show a direction. Code 0 is the far end of the fine chain and yields the
    schematic's own `L` exactly; code -k skips the last k fine units and
    yields `L - k` um. `certified` is DR-002's own range (0..-16): the drawn
    ladder can express four codes past it (-17..-20, down to the bare coarse
    leg), and they are listed **flagged**, not silently offered, because
    spec/decision-records/DR-002-trim-network-scoping.md certifies the
    monotonic operating point only over 0..-16 (issue #46,
    sim/trim-range-monotonicity/).

    Every port index is validated against the block's own reported ports, so
    a count-constant change fails loudly here instead of silently
    mislabelling a tap.

    These are **not** emitted as `pins[]` entries -- they are reported into
    the record as documentation of where the metal option lands. See
    INTERNAL_NODE_LABEL_NOTE: every one of these taps sits on a node interior
    to the schematic's own `R2A`/`R2B` device, and promoting an interior node
    to a top-level pin is what was splitting those two devices on the layout
    side.
    """
    from bus_routing import trim_tap_port  # local: see this file's own note

    bid = "res_trim"
    available = {p["name"] for p in reports[bid]["ports"]}
    coarse_um = R_LSEG_UM * N_R2_COARSE
    rows: list[dict[str, Any]] = []
    for k in range(N_R2_TRIM_UNITS + 1):
        ports: dict[str, str] = {}
        for leg, name in ((0, "A"), (1, "B")):
            port = trim_tap_port(leg, -k)
            if port not in available:
                raise KeyError(f"block '{bid}' has no trim-tap port '{port}'")
            ports[name] = port
        rows.append(
            {
                "code": -k,
                "block": bid,
                "ports": ports,
                "leg_um": coarse_um + R_LSEG_TRIM_UM * (N_R2_TRIM_UNITS - k),
                "certified": k <= N_R2_TRIM_CODES,
            }
        )
    return rows


def routed_ports(bus_summary: dict[str, Any]) -> set[tuple[str, str]]:
    """Every `(block, port)` pad a drawn met1 net already contacts.

    A `pins[]` label is drawn *on the pad*, so a label placed on a pad some
    other node's met1 has already via'd down to does not name that label's
    node -- it renames the node that owns the pad. `klt extract` then reports
    the pad's net under both names joined by `|` (e.g. `TAIL|VOUT`), i.e. the
    layout claims one schematic node is another.

    This is not hypothetical: it is what the previous increment's composed
    layout did. `VOUT`'s label landed on `core_mirror.M2_1_D`, which is
    MPAMP's drain and the pad the drawn `TAIL` net contacts, because the pin
    selector and the router kept separate "already used" sets. They share one
    now, and :func:`assert_no_merged_pin_names` checks the extracted netlist
    for the `|` that would prove the sharing failed.
    """
    claimed: set[tuple[str, str]] = set()
    for route in bus_summary.get("_inter_block", []):
        for terminal in route.get("terminals", []):
            block, _, port = terminal.partition(".")
            if port:
                claimed.add((block, port))
    return claimed


def assert_no_merged_pin_names(netlist_path: Path) -> list[str]:
    """Fail the flow on any extracted net whose name is two pin names joined
    by `|` -- KLayout's notation for "two labels, one net".

    Returns the offending names (empty is the only acceptable result). A
    merged name always means the layout asserted an equality between two
    schematic nodes that the schematic does not contain, which is a worse
    error than an open node and is invisible to both DRC and the drawn-short
    check (the shapes involved are legal and well separated -- it is the
    *labels* that collide).
    """
    merged = sorted(
        {
            token
            for token in re.findall(r"[A-Za-z_$][\w$|\\]*", netlist_path.read_text())
            if "|" in token
        }
    )
    return merged


def split_routed_nets(
    routes: list[dict[str, Any]], components: dict[str, int]
) -> dict[str, int]:
    """Every node the router reports as fully `routed` whose drawn met1 is
    nonetheless in more than one piece, as `{net: piece count}`.

    `Met1Bus.components()` counts the connected components of each node's own
    met1. One is the only honest answer for a node this router claims it
    joined end to end -- two means the flow drew a node it *believes* is one
    conductor as two islands that never touch, which is the exact inverse of
    the drawn-short failure and is invisible to every downstream check: DRC
    sees two legal wires, `klt extract` sees two anonymous nets with nothing
    in `warnings[]`, and the coverage table -- which scores the router's own
    hop bookkeeping, not the geometry -- still reports the node as drawn.

    Restricted to `routed` nodes on purpose. A node that came up a hop short
    is *supposed* to be in more than one piece; gating on it would only
    re-report what the coverage table already says, and would make this check
    fire on every partial run instead of on the bug it exists to catch.
    """
    return {
        route["net"]: components[route["net"]]
        for route in routes
        if route.get("routed") and components.get(route["net"], 1) != 1
    }


def run_met2_drc(
    klt: str, gds_path: Path, top: str, out_dir: Path
) -> dict[str, Any]:
    """Run `layout/bin/met2_drc.py` on the composed GDS and persist its report.

    Shelled out rather than imported because this script is deliberately
    stdlib-only (it drives `klt` as a subprocess and never imports it), while
    the met2 check needs `klayout.db`. The interpreter is taken from the same
    venv the `--klt` executable lives in, which is where `layout/bin/
    setup-venv.sh` puts both.
    """
    python = Path(klt).with_name("python")
    if not python.exists():  # pragma: no cover -- non-venv klt on PATH
        python = Path(sys.executable)
    report_path = out_dir / "met2-drc.json"
    result = subprocess.run(
        [
            str(python),
            str(Path(__file__).resolve().parent / "met2_drc.py"),
            str(gds_path),
            "--top",
            top,
            "-o",
            str(report_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 3):
        raise RuntimeError(
            f"met2_drc.py failed ({result.returncode}):\n{result.stderr}"
        )
    return json.loads(report_path.read_text())


def flow_gate(
    *,
    drc_clean: bool,
    within_budget: bool,
    full_scale_ladder: bool,
    r2_leg_matches: bool,
    all_classes: bool,
    pin_count: int,
    met1_conflicts: list[Any],
    merged_pin_names: list[str],
    split_routed: dict[str, int],
    met2_drc_clean: bool = True,
) -> dict[str, bool]:
    """The flow's pass/fail gate, as a named condition per row.

    Kept a pure function of already-measured values (rather than an inline
    boolean at the end of :func:`main`) for two reasons: the composition is
    then unit-testable without a `klt` install or a PDK -- see
    `layout/tests/test_routed_flow_gates.py` -- and a failing run can name
    *which* condition failed instead of only reporting exit 1.

    What is deliberately NOT in here: `klt lvs`-clean and schematic-net
    coverage. Schematic-net coverage is recorded as a measured number in
    record.md's own scoreboard instead of gated, for the same
    hides-the-evidence reason given below. `klt lvs`-clean was historically
    blocked upstream too (MOS_GATE_NOTE, RES_FLAVOR_NOTE) -- as of the
    thirtieth increment (MCC drawn as a MOS cap, MCC_MIM_INFEASIBLE_NOTE) it
    is no longer blocked and this flow's own `lvs.combined.json` reports
    `mismatch_count: 0`, but it is still not wired into this gate: the one
    remaining blocker on a fully green flow run is `within_budget` (the
    composed cell's real, measured area once MCC is drawn -- see
    `spec/decision-records/DR-007-mcc-area-budget.md`, which is *proposed*,
    not ratified), and gating on `lvs_clean` too would not change today's
    exit status, only make a future budget-only regression harder to tell
    apart from an LVS regression at a glance. Left as a follow-up once
    DR-007 (or an amendment) is ratified and `budget_um2` below can move to
    match it -- see that record's "Consequences" section.

    The four that ARE gated and are not about the tool's own verdicts --
    `no_drawn_shorts`, `no_merged_pin_names`, `no_split_routed_nets` and
    `met2_drc_clean` -- are this flow's own honesty checks. The first two
    catch a way the layout could claim connectivity the schematic does not
    contain (through metal, and through a pin label respectively); the third
    catches the inverse, a node this flow's own bookkeeping calls routed
    while the drawn metal is still in two pieces (see
    :func:`split_routed_nets`); the fourth checks the met2 escape plane
    against sky130's own source DRC rules, because the curated deck `drc_clean`
    above reports on is missing only the met2 min-area rule (`m2.6`) for it
    (MET2_ESCAPE_NOTE) -- the width/spacing/enclosure rules landed via
    klayout-tools#513/#515 and are part of `drc_clean` itself now. None of
    the first three is visible to `klt drc` at all.

    `r2_leg_length_matches` is the fifth of that kind, and the newest (issue
    #91). `full_scale_ladder` above only checks that the ladder is drawn at
    its real unit *count*; it says nothing about the resulting *length*,
    which is what design/bandgap_core.sch actually specifies and what sets
    K = R2/R1. The 286-um-vs-270-um defect issue #91 fixed passed
    `full_scale_ladder` for nineteen increments, and `r2_leg_length()`'s
    verdict reached only record.md's table -- reported, never gated. It is
    gated here so the same class of regression fails the flow.
    """
    return {
        "drc_clean": drc_clean,
        "met2_drc_clean": met2_drc_clean,
        "within_budget": within_budget,
        "full_scale_ladder": full_scale_ladder,
        "r2_leg_length_matches": r2_leg_matches,
        "device_classes_present": all_classes,
        "pins_promoted": pin_count > 0,
        "no_drawn_shorts": not met1_conflicts,
        "no_merged_pin_names": not merged_pin_names,
        "no_split_routed_nets": not split_routed,
    }


#: The escape plane's two layers, in the (gds-label, role-layer-tuple) shape
#: `drc.json["coverage"]["layers_in_stream_without_rules"]` reports them.
ESCAPE_PLANE_LAYERS: tuple[tuple[str, tuple[int, int]], ...] = (
    ("68/44", met1_bus.VIA1_LAYER),
    ("69/20", met1_bus.MET2_LAYER),
)


def met2_drc_coverage_note(unchecked: list[str]) -> str:
    """record.md's prose for the "does `klt drc` see the escape plane"
    question, driven by `drc.json`'s own `coverage.layers_in_stream_without_rules`
    rather than a hardcoded claim.

    A pure function of that one list -- not inlined at the call site -- for
    the same reason as :func:`flow_gate`: it is unit-testable without a
    `klt` install, and it is the one place this flow used to state, as fact,
    that `klt drc`'s curated sky130 deck "carries no met2.*/via.* rule at
    all" unconditionally. That was true through issue #62's twenty-third
    increment; klayout-tools#513 (merged via #515) added the met2/via1
    width, spacing and enclosure rules, so the correct claim now depends on
    what this run's own `coverage` block says, not on a fixed increment-era
    fact -- a stale hardcoded version of this text once printed "does not
    check any of this geometry" one sentence before quoting a `coverage`
    list that named *neither* escape-plane layer as unchecked, contradicting
    itself in the same paragraph.
    """
    escape_unchecked = [
        gds for gds, layer in ESCAPE_PLANE_LAYERS
        if f"{layer[0]}/{layer[1]}" in unchecked
    ]
    if escape_unchecked:
        return (
            "**`klt drc` does not fully check this geometry, and says so.** "
            "The curated sky130 deck's `coverage` block "
            "(klayout-tools#189) lists this run's unchecked stream layers as "
            f"`{', '.join(unchecked) or '--'}`, which includes "
            f"**{', '.join(escape_unchecked)}** of the escape plane's two "
            "layers (`via.drawing` 68/44, `met2.drawing` 69/20) -- so its "
            "`violation_count` above is *silent* about at least one of them "
            "rather than clean about it. This flow checks them itself "
            "against the installed sky130A PDK's own source deck "
            "(`libs.tech/klayout/drc/sky130A_mr.drc`: `m2.1`, `m2.2`, "
            "`m2.6`, `via.1a`, `via.2`, `via.4a`/`via.5a`, `m2.4`/`m2.5`) "
            "in `layout/bin/met2_drc.py`, and gates on it -- see the met2 "
            "DRC row in Results and [`met2-drc.json`](met2-drc.json)."
        )
    return (
        "**`klt drc` now checks most of this geometry.** klayout-tools#513 "
        "(merged via #515) added met2/via1 width, spacing and enclosure "
        "rules to the curated sky130 deck, and `drc.json`'s own `coverage` "
        "block (klayout-tools#189) confirms neither escape-plane layer "
        "(`via.drawing` 68/44, `met2.drawing` 69/20) is in this run's "
        f"unchecked-layer list (`{', '.join(unchecked) or '--'}`). What "
        "`klt drc` still cannot check is the met2 min-area rule (`m2.6`) -- "
        "#515 left it out because the curated deck's rule vocabulary has no "
        "`area` check primitive. `layout/bin/met2_drc.py` re-checks the "
        "full sky130A source-deck threshold set (including `m2.6`) "
        "independently and gates on it -- see the met2 DRC row in Results "
        "and [`met2-drc.json`](met2-drc.json)."
    )


def compose_inner(
    klt: str,
    out_dir: Path,
    pdk: str,
    cell_name: str,
    block_ids: list[str],
    reports: dict[str, dict[str, Any]],
    origins: dict[str, dict[str, float]],
    bus_summary: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compose the placed blocks plus the met1 bus/route overlay into one cell.

    `connectivity[]` is deliberately **empty**. PR #64 asked `gen-compose`'s
    router to draw the inter-block nets on li1 and used the router itself as
    the routability oracle; this increment draws them on met1 instead (see
    INTER_BLOCK_MET1), for two reasons that both bite at once:

    * a met1 wire crosses a block without touching the li1 pads inside it, so
      a net between non-adjacent blocks -- `VOUT`, the third leg of the VDD
      trunk -- becomes drawable at all; and
    * with the per-matched-group guard rings switched back on (upstream
      klayout-tools#441), the li1 router rejects every route to a non-tap
      port on a ringed block except through that block's single ring opening,
      so li1 routing and per-group rings remain effectively exclusive. On
      met1 the ring is simply a layer below.

    `pins[]` is still used, and only for what it is: **naming**. A pin entry
    draws a label, never a wire, so it makes a node addressable from a
    post-layout testbench (issue #16) without claiming any connectivity. Gate
    nodes are here for exactly that reason -- a MOS gate cannot be wired at
    all (MOS_GATE_NOTE), but it can be named.

    Returns `(compose_response, pins)`.
    """
    from bus_routing import MOS_HALVES  # local: see this file's own note

    pins: list[dict[str, Any]] = []
    # Seeded with every pad the drawn met1 nets already contact, so a label can
    # never rename another node's pad (see routed_ports).
    used: set[tuple[str, str]] = routed_ports(bus_summary)
    for spec in CORE_PIN_LABELS:
        block, device = spec["device"]
        half = MOS_HALVES[block]["devices"][device]
        placed = False
        for name in select_ports(
            reports[block],
            "_G",
            DIRECTION_NORTH,
            spec["toward"],
            half=half,
        ):
            if (block, name) not in used:
                pins.append({"net": spec["net"], "block": block, "port": name})
                used.add((block, name))
                placed = True
                break
        if not placed:
            raise KeyError(
                f"pin {spec['net']}: every gate port of {block}.{device} is "
                "already claimed"
            )
    # trim_tap_ladder() is deliberately NOT folded into `pins[]` -- see
    # INTERNAL_NODE_LABEL_NOTE and the record's own trim-tap table.

    request = {
        "schema": "klt.gen_compose.request/1",
        "pdk": {"variant": pdk},
        "blocks": [
            {
                "id": bid,
                "generator_report": str((out_dir / f"{bid}.gen.json").resolve()),
            }
            for bid in block_ids
        ],
        "placement": {
            "strategy": "explicit",
            "order": block_ids,
            "origins_um": origins,
        },
        "connectivity": [],
        "pins": pins,
        "routing": {"layer_role": "metal", "width_um": ROUTE_WIDTH_UM},
        "options": {
            "cell_name": cell_name,
            "output": str((out_dir / f"{cell_name}.gds").resolve()),
        },
    }
    request_path = out_dir / "compose.inner.request.json"
    request_path.write_text(json.dumps(request, indent=2) + "\n")
    compose = run_klt_json(klt, "gen-compose", str(request_path), allow_exit=(0, 3))
    (out_dir / "compose.inner.json").write_text(json.dumps(compose, indent=2) + "\n")
    return compose, pins



# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------
def git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> int:
    from bus_routing import MOS_HALVES, build_bus_overlay  # local: see this file's own note

    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--record-id", required=True)
    ap.add_argument("--repo-root", required=True, type=Path)
    ap.add_argument("--klt", required=True)
    ap.add_argument("--pdk-variant", required=True)
    ap.add_argument("--reference", required=True, type=Path)
    args = ap.parse_args()

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    klt = args.klt
    pdk = args.pdk_variant
    cell = "bandgap_core_routed"

    # --- 1. Generate every matched-group block -------------------------------
    reports: dict[str, dict[str, Any]] = {}
    for block in BLOCKS:
        reports[block["id"]] = klt_gen(klt, pdk, out_dir, block)

    # --- 2. Place on an explicit 2D grid ------------------------------------
    # (PR #64's step 2 -- a `klt draw` PNP device-recognition overlay -- is
    # gone: 2AMLogic/klayout-tools#440 makes `klt gen bjt_array` draw sky130's
    # bipolar marker and each unit's well tap itself, so the workaround is
    # retired rather than carried. The PNP device count below now comes from
    # the generator's own geometry.)
    origins = place_blocks(BLOCKS, reports)
    all_reports: dict[str, dict[str, Any]] = dict(reports)
    all_origins: dict[str, dict[str, float]] = dict(origins)

    # --- 3. Intra-block busses on met1 (MET1_BUS_NOTE) ----------------------
    bus_report, bus_summary = build_bus_overlay(
        klt, out_dir, reports[BLOCKS[0]["id"]]["pdk"], BLOCKS, reports, origins
    )
    overlays: dict[str, dict[str, Any]] = {"bus": bus_report}
    all_reports[bus_report["cell_name"]] = bus_report
    all_origins[bus_report["cell_name"]] = {"x": 0.0, "y": 0.0}

    content_bbox = union_bbox([b["id"] for b in BLOCKS], reports, origins)

    # --- 4. Route the inner cell (blocks + overlays, no ring) ---------------
    # The cell-level guard ring is deliberately composed in a *second* pass
    # below rather than in this one. `klt gen-compose`'s obstacle check
    # treats every placed block's bbox as a routing obstacle, and a ring that
    # encloses the whole floorplan reports exactly that bbox -- so composing
    # it alongside the routed blocks vetoes every inter-block net ("backbone
    # crosses ... through unrelated block 'guard_ring_outer''s bbox"). Two
    # passes keep the ring and the routing compatible; the same two-pass
    # shape gen_bandgap_floorplan.py already used for its own inner/outer
    # composition.
    inner_cell = f"{cell}_inner"
    inner_ids = [b["id"] for b in BLOCKS] + [
        o["cell_name"] for o in overlays.values()
    ]
    inner_reports = {bid: all_reports[bid] for bid in inner_ids}
    inner_origins = {bid: all_origins[bid] for bid in inner_ids}
    inner_compose, pin_labels = compose_inner(
        klt,
        out_dir,
        pdk,
        inner_cell,
        inner_ids,
        inner_reports,
        inner_origins,
        bus_summary,
    )
    met1_routes = bus_summary["_inter_block"]
    met1_conflicts = bus_summary["_conflicts"]
    met1_components = bus_summary["_components"]
    met1_split_routed = split_routed_nets(met1_routes, met1_components)

    # A hand-written `generator_report` for the routed inner cell so the
    # second pass can place it: `gen-compose`'s own response already carries
    # everything the contract needs from a block (`cell_name`, `gds_path`,
    # `bbox_um`) except `ports[]`, which the outer pass never routes to.
    inner_report = {
        "schema_version": 1,
        "generator": "gen-compose",
        "cell_name": inner_compose["cell_name"],
        "gds_path": inner_compose["gds_path"],
        "pdk": inner_compose["pdk"],
        "bbox_um": inner_compose["bbox_um"],
        "device_count": 0,
        "ports": [],
        "drc_hints": {
            "min_spacing_um": None,
            "matched_group_id": None,
            "snapped_to_grid": False,
            "notes": [],
        },
        "warnings": [],
    }
    (out_dir / f"{inner_cell}.gen.json").write_text(
        json.dumps(inner_report, indent=2) + "\n"
    )
    content_bbox = inner_compose["bbox_um"]

    # --- 5. Guard ring, sized/centered on the composed content --------------
    content_width = content_bbox["x1"] - content_bbox["x0"]
    content_height = content_bbox["y1"] - content_bbox["y0"]
    inner_width_um = content_width + 2 * RING_MARGIN_UM
    inner_height_um = content_height + 2 * RING_MARGIN_UM
    ring_report = klt_gen(
        klt,
        pdk,
        out_dir,
        {
            "id": "guard_ring_outer",
            "generator": "guard_ring",
            "params": {
                "inner_width_um": inner_width_um,
                "inner_height_um": inner_height_um,
                "ring_width_um": RING_WIDTH_UM,
                "contacts_per_side": RING_CONTACTS_PER_SIDE,
                "add_well": False,
            },
        },
    )
    all_reports["guard_ring_outer"] = ring_report
    ring_bbox = ring_report["bbox_um"]
    all_origins["guard_ring_outer"] = {
        "x": (content_bbox["x0"] + content_bbox["x1"]) / 2.0
        - (ring_bbox["x0"] + ring_bbox["x1"]) / 2.0,
        "y": (content_bbox["y0"] + content_bbox["y1"]) / 2.0
        - (ring_bbox["y0"] + ring_bbox["y1"]) / 2.0,
    }

    order = [inner_cell, "guard_ring_outer"]
    request = {
        "schema": "klt.gen_compose.request/1",
        "pdk": {"variant": pdk},
        "blocks": [
            {
                "id": bid,
                "generator_report": str((out_dir / f"{bid}.gen.json").resolve()),
            }
            for bid in order
        ],
        "placement": {
            "strategy": "explicit",
            "order": order,
            "origins_um": {
                inner_cell: {"x": 0.0, "y": 0.0},
                "guard_ring_outer": all_origins["guard_ring_outer"],
            },
        },
        "options": {
            "cell_name": cell,
            "output": str((out_dir / f"{cell}.gds").resolve()),
        },
    }
    (out_dir / "compose.request.json").write_text(json.dumps(request, indent=2) + "\n")
    compose = run_klt_json(
        klt, "gen-compose", str(out_dir / "compose.request.json"), allow_exit=(0, 3)
    )
    (out_dir / "compose.json").write_text(json.dumps(compose, indent=2) + "\n")

    # --- 6. DRC -------------------------------------------------------------
    drc = run_klt_json(
        klt, "drc", compose["gds_path"], "--deck", "sky130", allow_exit=(0, 3)
    )
    (out_dir / "drc.json").write_text(json.dumps(drc, indent=2) + "\n")

    # --- 6b. met2 DRC, because the curated deck's own coverage is partial ---
    # `klt drc --deck sky130` above now checks met2/via1 width, spacing and
    # enclosure (klayout-tools#513, merged via #515) -- but not the met2
    # min-area rule (`m2.6`), which #515 deliberately left out. This module
    # re-checks the full sky130A source-deck threshold set (including
    # `m2.6`) so the escape plane's evidence never depends on which subset
    # the curated deck happens to cover. See MET2_ESCAPE_NOTE and
    # layout/bin/met2_drc.py.
    met2_drc = run_met2_drc(klt, Path(compose["gds_path"]), cell, out_dir)

    # --- 7. Extract ---------------------------------------------------------
    extract = run_klt_json(
        klt,
        "extract",
        compose["gds_path"],
        "--deck",
        "sky130",
        "--top",
        cell,
        "-o",
        str(out_dir / f"{cell}.extract.spice"),
    )
    (out_dir / "extract.json").write_text(json.dumps(extract, indent=2) + "\n")

    # Label-collision proof, the pin-label counterpart of the drawn-short
    # proof above. The drawn-short check reasons about met1 *rectangles*; a
    # pin label collides through the pad underneath instead, so it is invisible
    # there and to DRC. Any `A|B` net name in the extracted netlist means two
    # labels landed on one net, i.e. the layout asserted that two schematic
    # nodes are the same node. Gated, never warned.
    merged_pin_names = assert_no_merged_pin_names(
        out_dir / f"{cell}.extract.spice"
    )

    # --- 8. LVS against the xschem-derived reference ------------------------
    # Run it twice, and record both: `options.combine_devices` is what makes
    # the drawn busses above pay off (it folds the layout's series ladder
    # segments and parallel array units into the lumped devices the schematic
    # states, on both sides), but KLayout's own `Netlist.combine_devices()`
    # can abort on a bipolar array -- "Internal error: Terminal still
    # connected after removing device in device combination" -- and `klt lvs`
    # propagates that as an unhandled traceback rather than its documented
    # error envelope. Recording the uncombined run alongside it means a
    # future upstream fix changes a number in the record instead of
    # resurrecting a flow that stopped running.
    reference_name = "reference.spice"
    (out_dir / reference_name).write_text(args.reference.read_text())

    def run_lvs(tag: str, combine: bool, from_netlist: bool = False) -> dict[str, Any]:
        # The pre-extracted (`from_netlist`) shape reads the once-per-primitive
        # `{cell}.extract.spice` and deliberately does NOT name `layout.deck`.
        # Naming the deck here would make `klt lvs` apply the resistor
        # `fixed_offset_ohm` correction once per post-combine device instead
        # (klayout-tools#559/#585/#586 via #583/#587). Measured under all four
        # accounting variants by layout/bin/measure_fixed_offset_variants.py:
        # doing so is a REGRESSION here, `mismatch_count` 1 -> 4 and
        # `devices.matched` 15 -> 12, because `reference.spice` states the
        # CHAINED value this flow's own multi-primitive decomposition sums to
        # (issue #108) -- and because DR-003 ratified, with independent
        # real-SPICE evidence, that the chained array physically pays the
        # head/end resistance once per separately-contacted instance, so the
        # once-per-device value would state a resistance the fabricated cell
        # does not have. See RES_HEAD_RESISTANCE_NOTE, DR-003 and
        # layout/matching-plan.md Section 7z.
        layout_spec: dict[str, Any] = (
            {"netlist": f"{cell}.extract.spice", "top": cell}
            if from_netlist
            else {"file": f"{cell}.gds", "deck": "sky130", "top": cell}
        )
        request = {
            "schema": "klt.lvs.request/1",
            "engine": "klayout",
            "layout": layout_spec,
            "reference": {"netlist": reference_name, "top": "bandgap_core"},
            "hints": {"same_nets": SUBSTRATE_SAME_NETS},
            "options": {"combine_devices": combine},
        }
        request_path = out_dir / f"lvs{tag}.request.json"
        request_path.write_text(json.dumps(request, indent=2) + "\n")
        try:
            response = run_klt_json(klt, "lvs", str(request_path), allow_exit=(0, 3))
        except RuntimeError as exc:
            response = {
                "status": "error",
                "mismatch_count": None,
                "error": str(exc).splitlines()[-1],
                "combine_devices": combine,
            }
        response.setdefault("combine_devices", combine)
        (out_dir / f"lvs{tag}.json").write_text(json.dumps(response, indent=2) + "\n")
        return response

    # The combined run reads the *already written* extracted netlist rather
    # than re-extracting inline. Same netlist either way, but KLayout's
    # `Netlist.combine_devices()` aborts ("Internal error: Terminal still
    # connected after removing device in device combination", terminal `E`)
    # on the inline-extracted form of this cell, while the identical netlist
    # round-tripped through SPICE combines cleanly -- so the SPICE form is
    # the one that can actually be compared. Filed as friction.
    lvs_combined = run_lvs(".combined", True, from_netlist=True)
    if lvs_combined.get("status") == "error":
        lvs_combined = run_lvs(".combined", True)
    lvs_plain = run_lvs("", False)
    lvs = lvs_combined if lvs_combined.get("status") != "error" else lvs_plain

    # --- 9. Render ----------------------------------------------------------
    render = run_klt_json(
        klt,
        "render",
        compose["gds_path"],
        "-o",
        str(out_dir / "renders"),
        "--width",
        "1600",
        "--height",
        "900",
    )
    (out_dir / "render.json").write_text(json.dumps(render, indent=2) + "\n")

    # --- 10. Record ---------------------------------------------------------
    composed_bbox = compose["bbox_um"]
    composed_area_um2 = (composed_bbox["x1"] - composed_bbox["x0"]) * (
        composed_bbox["y1"] - composed_bbox["y0"]
    )
    budget_um2 = 0.08 * 1000.0 * 1000.0  # DR-007: relaxed from 0.05 to fit the drawn MCC cap (operator-ratified, #62)

    sha = git(args.repo_root, "rev-parse", "HEAD")
    branch = git(args.repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    dirty = git(args.repo_root, "status", "--porcelain") != ""
    klt_version = subprocess.run(
        [klt, "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()

    drc_clean = drc.get("status") == "clean"
    within_budget = composed_area_um2 <= budget_um2
    device_counts = extract.get("device_counts", {})
    routed_nets = [r for r in met1_routes if r["routed"]]
    unrouted = [r["net"] for r in met1_routes if not r["routed"]]
    labelled_pins = [p for p in inner_compose.get("pins", []) if p.get("labelled")]
    trim_taps = trim_tap_ladder(reports)
    r2_length = r2_leg_length()
    pin_count = extract.get("pin_count", 0)
    lvs_clean = lvs.get("status") == "match"
    classes_present = {
        "pnp": device_counts.get("pnp", 0) > 0,
        "nfet": device_counts.get("nfet", 0) > 0,
        "pfet": device_counts.get("pfet", 0) > 0,
        # `res_high_po` since 2AMLogic/klayout-tools#463 (merged via #475) --
        # the schematic's own flavour, drawable at last. The base
        # `res_generic_po` counts too: the class the layout should carry is
        # whichever flavour it drew, and neither is "plain interconnect".
        "resistor": (
            device_counts.get(RES_CLASS, 0) > 0
            or device_counts.get("res_generic_po", 0) > 0
        ),
    }
    all_classes = all(classes_present.values())
    block_params = {b["id"]: b["params"] for b in BLOCKS}
    r2_units = block_params["res_r2"]["num"]
    trim_units = block_params["res_trim"]["num"]
    full_scale_ladder = (
        r2_units == 2 * N_R2_COARSE and trim_units == 2 * N_R2_TRIM_UNITS
    )

    # Criterion 1 is scored against design/bandgap_core.sch's own inter-block
    # node list, NOT against this flow's `connectivity[]` declaration.
    coverage = schematic_net_coverage(met1_routes)
    fully_drawn = [c for c in coverage if c["status"] == "drawn"]
    full_connectivity = len(fully_drawn) == len(coverage) and not unrouted

    lines: list[str] = []
    a = lines.append
    a(f"# Bandgap-core routed layout record: {args.record_id}")
    a("")
    a(
        "Routed-and-extracted successor to the issue #15 placement-only "
        "floorplan skeleton (`layout/bandgap-core/reports/` earlier records). "
        "Read `layout/matching-plan.md` for the matching rationale this "
        "layout implements; this record is the measured evidence, not the "
        "rationale."
    )
    a("")
    a("## Acceptance-criteria scoreboard (issue #62)")
    a("")
    a("| # | Criterion | Status | Evidence |")
    a("| --- | --- | --- | --- |")
    a(
        f"| 1 | Full inter-block routing | "
        f"{'MET' if full_connectivity else 'PARTIAL'} | "
        f"{len(fully_drawn)}/{len(coverage)} **schematic** inter-block nets "
        f"fully drawn ({len(routed_nets)}/{len(met1_routes)} "
        f"declared met1 nets routed, {len(unrouted)} unrouted) -- see "
        "\"Schematic inter-block nets\" below |"
    )
    a(
        f"| 2 | Resistor ladder at real unit count | "
        f"{'MET' if full_scale_ladder and r2_length['matches'] else 'NOT MET'} | "
        f"`res_r2` num={r2_units} (= 2 legs x {N_R2_COARSE} coarse "
        f"{R_LSEG_UM:.0f}um units) + `res_trim` num={trim_units} (= 2 legs x "
        f"{N_R2_TRIM_UNITS} fine {R_LSEG_TRIM_UM:.1f}um units) = "
        f"{r2_length['drawn_um']:.0f} um/leg at DR-002 code 0, against "
        f"design/bandgap_core.sch's `r_lseg*n_r2` = "
        f"{r2_length['spec_um']:.0f} um (delta "
        f"{r2_length['delta_um']:+.0f} um); composed bbox "
        f"{composed_area_um2:,.0f} um^2 vs {budget_um2:,.0f} um^2 budget |"
    )
    a(
        f"| 3 | Extract: correct device classes + promoted pins | "
        f"{'MET' if all_classes and pin_count > 0 else 'PARTIAL'} | "
        f"device_counts={json.dumps(device_counts)}, pin_count={pin_count} |"
    )
    a(
        f"| 4 | `klt lvs` clean | {'MET' if lvs_clean else 'NOT MET'} | "
        f"status={lvs.get('status')}, mismatch_count={lvs.get('mismatch_count')} |"
    )
    a(
        "| 5 | Blocking `klt` gaps filed as friction | MET | every gap this "
        "flow ever named as *blocking* is now CLOSED upstream and this "
        "record is the re-run "
        "against them: 2AMLogic/klayout-tools#461 via #474, #462 via #471, "
        "#463 via #475, #454 via #468, #470 via #481, #490 via #495, #491 "
        "via #494, #492 via #497/#498, #504 via #505, and -- turned on by "
        "the nineteenth increment -- **#508 via #511** (sky130's curated "
        "deck gains met2 as a third connectivity level, which is what makes "
        "criterion 1's escape plane real connectivity rather than inert "
        "geometry; see ROUTING_PLANE_NOTE / MET2_ESCAPE_NOTE). "
        "2AMLogic/klayout-tools#506 (the generic arity reconciliation #505 "
        "deferred, filed by the fifteenth increment) has since closed as "
        "COMPLETED too -- this flow never needed it, because its own "
        "reference can state the bulk net directly. **Every gap this flow "
        "has ever filed as blocking is now closed upstream.** Two "
        "non-blocking gaps were filed by the nineteenth increment: "
        "**klayout-tools#513** is the flip side of #511 -- the curated "
        "sky130 **DRC** deck was not extended alongside the extraction "
        "deck, so `klt drc` returns violation_count=0 on any met2 geometry "
        "whatsoever, and this flow checks the plane itself instead "
        "(`layout/bin/met2_drc.py`, gated; see the met2 DRC row in "
        "Results). **klayout-tools#514** is the labelling gap "
        "INTERNAL_NODE_LABEL_NOTE describes: there is no way to name a net "
        "without promoting it to a pin, and a pin on a node interior to a "
        "schematic device silently blocks `combine_devices` with nothing "
        "attributing the resulting mismatches to it. The twenty-first "
        "increment filed no new gap (the PNP `ae`/`pe`/`ne` fix was a "
        "`reference.spice` transcription fix, needing no new `klt` "
        "capability). **This (twenty-third) increment picks up "
        "2AMLogic/klayout-tools#518 via #519 and #521 via #526** (the "
        "`res_high_po` fixed head/end-resistance term, and the fix that "
        "makes it reach the written netlist `klt lvs` compares) and, "
        "having measured that picking them up does not close AC4's "
        "resistor cause, files one new non-blocking gap: "
        "**klayout-tools#559** -- `ResistorDevice.fixed_offset_ohm` is "
        "charged once per drawn primitive, not once per logical device, "
        "so `combine_devices` folding a caller's own multi-primitive series "
        "decomposition (this flow's trim-tap ladder) sums it once per "
        "primitive instead of once for the schematic-level device. **This "
        "(twenty-eighth) increment bumps the klt pin past #583 (which closed "
        "#559 by deferring that correction until after `combine_devices()` "
        "folds) and #587 (which made the deferral reachable from this flow's "
        "own pre-extracted request shape, closing #585/#586 -- the real "
        "blocker was a case-sensitive device-class lookup that missed the "
        "`NetlistSpiceReader`-uppercased `RES_HIGH_PO` name, NOT "
        "`layout.deck` being ignored on that shape: `layout_deck` resolves "
        "unconditionally in `run_lvs`).** The once-per-combined-device "
        "correction is therefore reachable now, and is measured with "
        "`layout/bin/measure_fixed_offset_variants.py` across all four "
        "accounting combinations (`layout/bandgap-core/"
        "fixed-offset-variants/<record-id>/`). It is **deliberately NOT "
        "adopted**, and at this repo's current state adopting it would be a "
        "measured REGRESSION rather than a neutral choice: since issue #108 "
        "settled `reference.spice` on the CHAINED value this flow's own "
        "multi-primitive decomposition sums to, the shipped per-primitive "
        "accounting is the only variant that matches at all -- #587's own "
        "defer-plus-deck pairing takes `mismatch_count` 1 -> 4 and "
        "`devices.matched` 15 -> 12. DR-003's ratified finding points the "
        "same way: this layout physically pays the head resistance once per "
        "separately-contacted instance, so re-reporting each leg at the "
        "single-device value would state a resistance the fabricated cell "
        "does not have. See RES_HEAD_RESISTANCE_NOTE, DR-003 and "
        "layout/matching-plan.md Section 7z |"
    )
    a("")
    a(f"- [{'x' if drc_clean else ' '}] DRC on the composed, routed layout is clean")
    a(
        f"- [{'x' if within_budget else ' '}] Composed bbox area "
        f"({composed_area_um2:,.0f} um^2) is within the < 0.05 mm^2 "
        f"({budget_um2:,.0f} um^2) budget, **at the real full-length ladder "
        f"count** ({r2_units} coarse + {trim_units} fine units)"
    )
    a("")
    a("## Flow")
    a("")
    a(f"1. `klt gen` once per matched device group ({len(BLOCKS)} blocks).")
    a(
        "2. `klt draw` once, for the whole cell: every intra-block bus and "
        "every inter-block net, on met1 over mcon -- plus, for the hops met1 "
        "has no corridor for, a met2 escape over `via.drawing` "
        "(MET2_ESCAPE_NOTE) -- and one met1 net label per *schematic* node. "
        "`bandgap_core_bus.draw.json`, summarised in `bus-summary.json`."
    )
    a(
        "3. `klt gen-compose` with `placement.strategy: \"explicit\"`, an "
        "empty `connectivity[]` (routing is drawn above) and an empty "
        "`pins[]` -- every pin this cell promotes is now a net label from "
        "step 2, and the four trim-tap pin entries earlier records carried "
        "are gone (INTERNAL_NODE_LABEL_NOTE). `compose.request.json`."
    )
    a("4. `klt drc <composed> --deck sky130`.")
    a(
        "4b. `layout/bin/met2_drc.py <composed>` -- the escape plane's own "
        "DRC, because the curated deck step 4 runs is still missing the "
        "met2 min-area rule (`m2.6`; klayout-tools#513/#515 added the rest)."
    )
    a(f"5. `klt extract <composed> --deck sky130 --top {cell}`.")
    a(
        "6. `klt lvs` against the xschem-derived reference netlist (issue "
        "#8), twice -- with and without `options.combine_devices`."
    )
    a("7. `klt render` for the visual check below.")
    a("")
    a("## Device-half binding")
    a("")
    a(
        "A `klt gen diff_pair` reports its two transistors as two port "
        "families (`M1_*`/`M2_*`, or `Q1_*`/`Q2_*` when `mirror` is false). "
        "Which family is which schematic device is *this flow's* choice, not "
        "the generator's -- the halves are geometrically interchangeable. "
        "Until this increment that choice was never made: every net picked "
        "whichever candidate pad sat nearest its own centroid, independently. "
        "Two consequences were live in the previous record. `PN` took a "
        "finger of the same amp_pmirr half the `AOUT` label named, so MP3's "
        "drain and MP4's drain were the same physical transistor; and "
        "amp_nload's `D1` route and `D1_GATE` label disagreed about which "
        "half is MN1. Neither is visible to DRC or to the drawn-short check "
        "-- every terminal involved is legal, well-separated metal."
    )
    a("")
    a("| block | port family | schematic device | drain pad | source pad |")
    a("| --- | --- | --- | --- | --- |")
    for bid, entry in MOS_HALVES.items():
        for device, half in entry["devices"].items():
            a(
                f"| `{bid}` | `{half}_*` | `{device}` | "
                f"`{half}_*{entry['drain_suffix']}` | "
                f"`{half}_*{entry['source_suffix']}` |"
            )
    a("")
    a(
        "Every routed terminal and every gate pin label now resolves through "
        "that table (`mos_terminal()` / `bulk_terminal()`), so a node can "
        "only land on the transistor the schematic names."
    )
    a("")
    a("## Blocks")
    a("")
    a("| id | generator | matched group | real target |")
    a("| --- | --- | --- | --- |")
    for block in BLOCKS:
        a(
            f"| `{block['id']}` | `{block['generator']}` | "
            f"{block['matched_group_label']} | {block['real_target']} |"
        )
    a("")
    a(f"Note: {MCC_AREA_UM2_NOTE}")
    a("")
    a("## Intra-block busses drawn on met1")
    a("")
    a(
        "Each matched group's units are tied into the node the schematic "
        "says they form, on met1 over mcon -- the sky130 extraction deck's "
        "own second conductor and via (`metals = (li1, met1, met2)`, "
        "`vias = (mcon, via)` since klayout-tools#511; met2 is reserved for "
        "the inter-block escape plane above and no intra-block bus uses "
        "it). This flow draws them itself from each block's "
        "reported `ports[]` (MET1_BUS_NOTE). That is what turns a "
        "100-segment coarse ladder (and its 40-segment fine trim ladder) "
        "into two real series resistors, an 8-unit PNP "
        "array into one real m=8 device, and -- new in this increment -- "
        "each split MOS group's 4 to 32 fingers into the single m=N "
        "transistor the schematic names."
    )
    a("")
    a("| block | bus | detail |")
    a("| --- | --- | --- |")
    for bid, entry in bus_summary.items():
        if bid.startswith("_"):
            continue
        if entry["kind"] == "res_series":
            a(
                f"| `{bid}` | {entry['legs']} interdigitated series "
                f"string(s) | {len(entry['links'])} unit-to-unit met1 links |"
            )
        elif entry["kind"] == "mos_comb":
            detail = "; ".join(
                f"`{r['net']}` = {r['pads']} finger pads"
                + (f" ({r['gate_contacts']} gate contacts)"
                   if r["gate_contacts"] else "")
                + f" joined on the {r['spine_side']} spine"
                for r in entry["nets"]
            )
            a(f"| `{bid}` | split-device finger bus | {detail} |")
        else:
            detail = "; ".join(
                f"`{r['net']}` = {r['pads']} pads on {r['columns']} columns"
                for r in entry["nets"]
            )
            a(f"| `{bid}` | parallel unit bus | {detail} |")
    a("")
    a(
        f"Drawn-short / spacing proof: every met1 rectangle carries the "
        f"electrical node it belongs to, and **{len(met1_conflicts)}** pairs "
        "of rectangles belonging to *different* nodes come within the deck's "
        "0.14 um `met1.space.1` clearance. The flow fails on any nonzero "
        "count -- a drawn short the DRC deck happens not to model would "
        "otherwise read as connectivity."
    )
    a("")
    a(
        "Split-node proof (the inverse check): every node's own met1 is "
        "counted into connected components, and **"
        f"{len(met1_split_routed)}** of the nodes this router reports as "
        "fully routed are drawn in more than one piece"
        + (
            " ("
            + ", ".join(
                f"`{net}` = {n} pieces"
                for net, n in sorted(met1_split_routed.items())
            )
            + ")"
            if met1_split_routed
            else ""
        )
        + ". The flow fails on any nonzero count. A node drawn as two islands "
        "that never touch is not a connected node, and unlike a drawn short "
        "*nothing downstream reports it*: DRC sees two legal wires, `klt "
        "extract` sees two anonymous nets with nothing in `warnings[]`, and "
        "the coverage table below scores this flow's own hop bookkeeping "
        "rather than the geometry, so it would still call the node drawn. "
        "Nodes that came up a hop short are excluded on purpose -- they are "
        "*supposed* to be in more than one piece, and the coverage table "
        "already says so. Their piece counts, and every other node's, are in "
        "`bus-summary.json`'s `_components`"
        + (
            ": "
            + ", ".join(
                f"`{net}` = {n}"
                for net, n in sorted(met1_components.items())
                if n != 1
            )
            if any(n != 1 for n in met1_components.values())
            else " (every node is a single piece)"
        )
        + "."
    )
    a("")
    a(
        "Label-collision proof: **"
        f"{len(merged_pin_names)}** extracted net(s) carry more than one "
        "label"
        + (f" ({', '.join('`' + n + '`' for n in merged_pin_names)})"
           if merged_pin_names else "")
        + ". This is the pad-side counterpart of the check above and is "
        "gated the same way. A `pins[]` entry labels a *port*, i.e. a pad, so "
        "a label placed on a pad another node's metal already contacts does "
        "not name its own node -- it renames that node, and `klt extract` "
        "emits the result as a single net called `A|B` with nothing in "
        "`warnings[]` and DRC still clean. The previous increment's composed "
        "layout shipped exactly that: `VOUT`'s label sat on "
        "`core_mirror.M2_1_D`, which is MPAMP's drain and the pad the drawn "
        "`TAIL` net contacts, so its extracted netlist contained a net named "
        "`TAIL|VOUT` -- the layout asserting that the reference output and "
        "the amp tail are one node. The pin selector and the router now "
        "share one claimed-pad set, and this line is the proof. Filed "
        "upstream as 2AMLogic/klayout-tools#470 (the silence, not the "
        "collision, is the tool gap)."
    )
    a("")
    a("## Inter-block nets drawn on met1")
    a("")
    a("| net | terminals | routed | plane | schematic node |")
    a("| --- | --- | --- | --- | --- |")
    for route in met1_routes:
        met2_hops = sum(1 for h in route.get("hops", []) if h.get("met2"))
        plane = "met1" if not met2_hops else f"met1 + met2 x{met2_hops}"
        a(
            f"| `{route['net']}` | "
            f"{' + '.join(f'`{t}`' for t in route['terminals'])} | "
            f"{'yes' if route['routed'] else 'NO'} | {plane} | "
            f"{route['schematic']} |"
        )
    a("")
    met2_hop_rows = [
        (route["net"], hop)
        for route in met1_routes
        for hop in route.get("hops", [])
        if hop.get("met2")
    ]
    a("### The met2 escape plane")
    a("")
    a(
        f"**{len(met2_hop_rows)}** of this cell's inter-block hops are drawn "
        "on met2 rather than met1, each entered and left through a via1 "
        "stack (met1 pad + `via.drawing` cut + met2 pad). met1 on this "
        "floorplan carries both every block's intra-block bus and every "
        "inter-block net, and the hops below had no met1 corridor at any "
        "lane, margin, block placement or search depth this repo can set -- "
        "layout/matching-plan.md Sections 7d-7o are the exhausted list. met2 "
        "is a genuinely independent conductor, and became one for sky130's "
        "curated deck only with 2AMLogic/klayout-tools#508 (merged via "
        "#511); before that its `metal2` role resolved to the same met1 "
        "layer this flow's own bussing already occupies. The escape is tried "
        "**strictly last**, after every met1 elbow, channel path and "
        "Z-detour has been drawn and rolled back, so met1 remains the "
        "primary plane -- see MET2_ESCAPE_NOTE."
    )
    a("")
    if met2_hop_rows:
        a("| net | hop | via1 drops (um) | met2 path |")
        a("| --- | --- | --- | --- |")
        for net, hop in met2_hop_rows:
            drops = " -> ".join(
                f"({d[0]}, {d[1]})" for d in hop.get("via1_drops", [])
            )
            a(
                f"| `{net}` | `{hop['from']}` -> `{hop['to']}` | {drops} | "
                f"{len(hop.get('points', []))}-point |"
            )
        a("")
    unchecked = drc.get("coverage", {}).get("layers_in_stream_without_rules", [])
    a(met2_drc_coverage_note(unchecked))
    a("")
    a("## Schematic inter-block nets: drawn vs. labelled only")
    a("")
    a(
        "The table above counts this flow's own routing declaration. This "
        "one counts what issue #62 actually asks for: every node of "
        "design/bandgap_core.sch (+ design/error_amp.sch) that joins devices "
        "in different blocks, and whether drawn metal joins **all** the "
        "blocks the schematic says it reaches. "
        "Every one of these nodes is *expressible*: MOS gates are contactable "
        "(MOS_GATE_NOTE), the resistor blocks carry the schematic's own "
        "flavour (RES_FLAVOR_NOTE), and -- new in this increment -- a hop "
        "that met1 has no corridor for can escape onto met2 "
        "(MET2_ESCAPE_NOTE). A row that is not `drawn` would therefore be "
        "this flow's own router failing on a floorplan that can express the "
        "node, not a capability being waited on."
    )
    a("")
    a("| schematic net | reaches (blocks) | joined by drawn metal | not drawn | status |")
    a("| --- | --- | --- | --- | --- |")
    for row in coverage:
        a(
            f"| `{row['net']}` | {', '.join(f'`{b}`' for b in row['blocks'])} | "
            f"{', '.join(f'`{b}`' for b in row['joined']) or '--'} | "
            f"{', '.join(f'`{b}`' for b in row['missing']) or '--'} | "
            f"**{row['status']}** |"
        )
    a("")
    a(
        f"**{len(fully_drawn)} of {len(coverage)} schematic inter-block nets "
        "are fully drawn.** Criterion 1 is scored PARTIAL, not MET, whenever "
        "that count is short"
        + (" -- it is not short here." if full_connectivity else ".")
        + " `VSS` reaches four blocks here, not the seven "
        "an earlier record listed: the three resistor blocks' `res_high_po` "
        "bulk terminals are on this node in the schematic and now resolve "
        "to the same real, drawn `VSS` net the rest of the row does "
        "(SUBSTRATE_NET_NOTE) -- but `res_array` draws no bulk-terminal pad "
        "inside those three blocks, so there is nothing for this router to "
        "target and counting them as routing targets would be scoring "
        "against an impossible bar rather than a missed one."
    )
    a("")
    a("## Promoted top-level pins")
    a("")
    a(
        f"`klt gen-compose` labelled {len(labelled_pins)}/"
        f"{len(inner_compose.get('pins', []))} requested `pins[]` ports; "
        f"`klt extract` promoted **{pin_count}** top-level pins "
        "(the #15 skeleton promoted `pin_count: 0`)."
    )
    a("")
    a("| net | port | labelled |")
    a("| --- | --- | --- |")
    for pin in inner_compose.get("pins", []):
        a(
            f"| `{pin['net']}` | {pin['block']}.{pin['port']} | "
            f"{'yes' if pin.get('labelled') else 'no'} |"
        )
    a("")
    a(
        "Four labels the previous records carried are **gone** from this "
        "list, and their absence is one of this increment's two substantive "
        "changes: `TRIM_A`, `TRIM_B`, `TRIM_A_CODE_0` and `TRIM_B_CODE_0`. "
        f"{INTERNAL_NODE_LABEL_NOTE}"
    )
    a("")
    a("### DR-002 trim-ladder taps (documented, not pinned)")
    a("")
    a(
        "Every code the drawn metal option can select, with the divider-leg "
        "length it yields. Each tap is located and validated against the "
        "block's own reported ports every run -- a count-constant change "
        "fails the flow loudly here rather than silently mislabelling a tap "
        "-- and the lengths below are computed from the tap index, not "
        "asserted, so the table *is* the demonstration that the ladder runs "
        "downward: code -k yields exactly `spec - k` um. Taps are reported "
        "into this record instead of into `pins[]` for the reason above."
    )
    a("")
    a(
        f"Codes outside DR-002's certified 0..-{N_R2_TRIM_CODES} range are "
        "drawn (the ladder is a metal option, so its physical taps exist "
        "whether or not a code is certified) and are marked "
        "**out-of-certified-range** below. "
        "`spec/decision-records/DR-002-trim-network-scoping.md` certifies the "
        "operating point over 0..-16 only; issue #46 and "
        "`sim/trim-range-monotonicity/` are the corner evidence for the "
        "boundary. Selecting one of the flagged taps is out of spec, not a "
        "wider trim range."
    )
    a("")
    a("| DR-002 code | leg A port | leg B port | leg length | certified |")
    a("| --- | --- | --- | --- | --- |")
    for tap in trim_taps:
        a(
            f"| `{tap['code']:d}` | {tap['block']}.{tap['ports']['A']} | "
            f"{tap['block']}.{tap['ports']['B']} | {tap['leg_um']:.0f} um | "
            f"{'yes' if tap['certified'] else '**no -- out of certified range**'} |"
        )
    a("")
    a("### Drawn vs. specified R2 leg length")
    a("")
    a(
        "The divider legs are the one place where the layout's own geometry "
        "constants can disagree with design/bandgap_core.sch's `CORE_PARAMS` "
        "without anything else in this flow noticing -- `klt lvs` can only "
        "report a resistor's *value*, and only once the two sides pair at "
        "all, which they did not until the nineteenth increment. This row "
        "states the comparison in the units the schematic itself specifies, "
        "unconditionally, from this flow's own constants. **It is a gated "
        "condition** (`r2_leg_length_matches`), not merely a reported one, "
        "since issue #91."
    )
    a("")
    a("| quantity | value |")
    a("| --- | --- |")
    a(
        f"| `res_r2` coarse leg (drawn) | {r2_length['coarse_um']:.0f} um "
        f"({N_R2_COARSE} x {R_LSEG_UM:.0f} um) |"
    )
    a(
        f"| `res_trim` fine leg at code 0 (drawn) | "
        f"{r2_length['trim_um']:.0f} um ({N_R2_TRIM_UNITS} x "
        f"{R_LSEG_TRIM_UM:.1f} um) |"
    )
    a(f"| **total drawn** | **{r2_length['drawn_um']:.0f} um** |")
    a(
        f"| schematic `L = r_lseg*n_r2 + r_lseg_trim*n_r2_trim` | "
        f"{r2_length['spec_um']:.0f} um |"
    )
    a(f"| delta | {r2_length['delta_um']:+.0f} um |")
    a(
        f"| effective DR-002 trim code | "
        f"**{r2_length['effective_trim_code']:+d}** |"
    )
    a("")
    if r2_length["matches"]:
        a(f"**How this came to be a gated row.** {RES_TRIM_LENGTH_NOTE}")
    else:
        a(
            "**REGRESSION.** The drawn leg no longer reproduces the "
            "schematic's specified length, and the flow's "
            "`r2_leg_length_matches` gate has failed on it. "
            f"{RES_TRIM_LENGTH_NOTE}"
        )
    a("")
    a("## Results")
    a("")
    a("| Stage | Status | Detail |")
    a("| --- | --- | --- |")
    a(
        f"| met1 routing | {'routed' if not unrouted else 'partial'} | "
        f"nets={len(met1_routes)}, unrouted={len(unrouted)}, "
        f"drawn-short conflicts={len(met1_conflicts)}, "
        f"split routed nodes={len(met1_split_routed)} |"
    )
    a(f"| DRC | {drc.get('status')} | violation_count={drc.get('violation_count')} |")
    a(
        f"| met2 DRC (this repo's own) | {met2_drc.get('status')} | "
        f"violation_count={met2_drc.get('violation_count')}, "
        f"via1 cuts={met2_drc.get('counts', {}).get('via1_cuts')}, "
        f"met2 polygons={met2_drc.get('counts', {}).get('met2_polygons')} |"
    )
    a(
        f"| extract | ok | device_count={extract.get('device_count')}, "
        f"device_counts={json.dumps(device_counts)}, pin_count={pin_count} |"
    )
    a(
        f"| LVS | {lvs.get('status')} | mismatch_count="
        f"{lvs.get('mismatch_count')} |"
    )
    if not drc_clean:
        a("")
        a("### DRC violations")
        a("")
        for v in drc.get("violations", [])[:50]:
            a(f"- {v}")
    a("")
    a("### Extracted device classes vs. the #15 skeleton")
    a("")
    a("| class | this record | #15 skeleton |")
    a("| --- | --- | --- |")
    a(f"| `pnp` | {device_counts.get('pnp', 0)} | 0 |")
    a(f"| `nfet` | {device_counts.get('nfet', 0)} | 0 |")
    a(f"| `pfet` | {device_counts.get('pfet', 0)} | 68 |")
    a(f"| `{RES_CLASS}` | {device_counts.get(RES_CLASS, 0)} | 67 (as `res_generic_po`) |")
    a(f"| promoted pins | {pin_count} | 0 |")
    a("")
    a("### LVS mismatch analysis")
    a("")
    a("| run | `combine_devices` | status | mismatches |")
    a("| --- | --- | --- | --- |")
    for label, response in (
        ("combined", lvs_combined),
        ("uncombined", lvs_plain),
    ):
        detail = response.get("error") or response.get("mismatch_count")
        a(
            f"| {label} | {response.get('combine_devices')} | "
            f"{response.get('status')} | {detail} |"
        )
    a("")
    if lvs_combined.get("status") == "error":
        a(
            "The combined run **aborted inside KLayout**: "
            f"`{lvs_combined.get('error')}`. `klt lvs` propagates that as an "
            "unhandled traceback rather than its documented error envelope, "
            "so the scoreboard above reads the uncombined run. Filed as "
            "friction; nothing about the layout changes either way."
        )
        a("")
    lvs_counts = lvs.get("counts", {})
    lvs_nets = lvs_counts.get("nets", {})
    lvs_devices = lvs_counts.get("devices", {})
    lvs_pins = lvs_counts.get("pins", {})
    a("| | layout | reference | matched |")
    a("| --- | --- | --- | --- |")
    for label, block in (
        ("nets", lvs_nets),
        ("devices", lvs_devices),
        ("pins", lvs_pins),
    ):
        a(
            f"| {label} | {block.get('layout')} | {block.get('reference')} | "
            f"{block.get('matched')} |"
        )
    a("")
    a(
        "Device counts here are **after** `klt lvs`'s "
        "`options.combine_devices` has folded both sides (this increment "
        "turns it on): the layout's series ladder segments and parallel "
        "array units collapse into the lumped devices the schematic states, "
        "which is only possible because the busses above are actually drawn. "
        f"`klt extract` saw {extract.get('device_count')} drawn devices; the "
        f"comparison sees {lvs_devices.get('layout')}."
    )
    a("")
    a(f"Mismatch categories: `{json.dumps(lvs.get('category_counts', {}))}`.")
    a("")
    a(
        "The residual gap has exactly **one** disclosed cause left, as of "
        "this (issue #108) increment, and it is neither a topology error "
        "in either netlist, a connectivity difference, nor a layout "
        "defect: the single deliberately-undrawn device. Seven causes "
        "tracked by prior records -- the deck-synthesized substrate net, "
        "undeclarable array dummies, the resistor device-class arity "
        "mismatch, unrouted schematic nodes, the R2 divider leg length, "
        "the PNP `ae`/`pe`/`ne` transcription gap, and (as of this "
        "increment) the `res_high_po` per-instance head-resistance value "
        "gap -- are **retired**; see \"Retired since the last increment\" "
        "below."
    )
    a("")
    a(
        "1. **`MMCC`, the amp's compensation cap, is in the reference but "
        "deliberately not drawn in this layout** (see the Blocks note "
        "above), so one reference device has no layout counterpart by "
        "construction. This is the *only* mismatch on either side."
    )
    a("")
    a(
        "Not worked around by editing either netlist to match the other. "
        "`reference.spice` states design/bandgap_core.sch; rewriting it to "
        "enumerate the layout's own shortfalls would make LVS compare the "
        "layout against itself, which is not evidence. `MMCC` is a "
        "deliberate scope choice (a single-ended compensation cap this "
        "layout does not draw), not a defect either side could fix."
    )
    a("")
    a("### Retired since the last increment")
    a("")
    a(
        "- **The R2 divider legs draw the length the schematic specifies.** "
        f"{RES_TRIM_LENGTH_NOTE}"
    )
    a(
        "- **Every schematic inter-block node is now joined across every "
        "block it reaches.** Through the seventeenth increment, "
        "`D1`/`GDRV`/`VSS` were split in the layout where the reference has "
        "one node, and PRs #75-#88 are an exhaustive negative-result "
        "sequence on every met1-side lever (search depth, channel-search "
        "window, row-0 margin, row-0 re-placement, a genuine 2D row split, "
        "and klayout-tools#454/#468's `metal2` role). The cause was never "
        "any of those: it was that sky130's curated deck had only one "
        "routing plane above the device pads, and this flow's own bussing "
        "already occupied it. Retired by 2AMLogic/klayout-tools#508 (merged "
        "via #511) plus the escape router built on it -- see \"The met2 "
        "escape plane\" above. `net.split` and `net.merged` are both **0** "
        "in the categories line above; they were 10 and 3."
    )
    a(
        "- **The trim ladder's nodes no longer split R2A/R2B into unpairable "
        f"pieces.** {INTERNAL_NODE_LABEL_NOTE}"
    )
    a(
        "- **The substrate net is now real, drawn connectivity, not a "
        f"declaration.** {SUBSTRATE_NET_NOTE} No `hints.same_nets` entry is "
        "sent (`SUBSTRATE_SAME_NETS` is empty); the correspondence this "
        "flow previously had to *state* is now something `klt lvs` "
        "*discovers* from the drawn geometry on its own."
    )
    a(f"- **Array dummies are now correctly excluded from the comparison.** {DUMMY_DEVICE_NOTE}")
    a(
        "- **The resistor device-class arity mismatch is fixed, not just "
        f"diagnosed.** {RES_BULK_ARITY_NOTE}"
    )
    a(
        "- **The PNP `ae`/`pe`/`ne` transcription gap is fixed.** "
        f"{PNP_EMITTER_GEOMETRY_NOTE}"
    )
    a(
        "- **`res_high_po`'s per-instance head-resistance value gap is "
        "closed** (issue #108). RES_HEAD_RESISTANCE_NOTE's finding still "
        "holds -- this flow's own multi-primitive R2A/R2B/R1 decomposition "
        "genuinely pays the fixed per-instance offset once per drawn "
        "primitive, not once per logical device -- but `reference.spice` "
        "previously stated design/bandgap_core.sch's single-device "
        "approximation (`380 + 325*L` once per leg), which is not what "
        "`klt lvs`'s own `combine_devices` sums the layout side to. This "
        "increment settles that transcription-convention question by "
        "stating the CHAINED value instead (RES_RESIZE_NOTE and "
        "reference.spice's own RESISTOR VALUE CONVENTION note), computed "
        "from the same real `sky130_fd_pr__res_high_po` model constants "
        "RES_HEAD_RESISTANCE_NOTE cites -- exactly reproducing what "
        "`combine_devices` sums the layout side to. Measured: `R1`/`R2A`/"
        "`R2B` all move from `device.property` mismatches to full matches, "
        "`mismatch_count` moving from 4 (pre-resize) to the 1 above."
    )
    a(
        "- **The R2 leg is drawn one coarse unit longer (issue #178).** "
        f"{RES_HEAD_SIZING_NOTE}"
    )
    a("")
    a("## Visual verification")
    a("")
    a("![routed overview](renders/overview.png)")
    a("")
    a("## What this record does NOT claim")
    a("")
    a(
        f"- **Not LVS-clean.** `klt lvs` reports `{lvs.get('status')}` with "
        f"`mismatch_count={lvs.get('mismatch_count')}` against the "
        "xschem-derived reference netlist, and `devices.matched` is "
        f"{lvs_devices.get('matched')}. The one cause above (`MMCC`, "
        "deliberately not drawn) is the whole of it. The count moved "
        "18 -> 4 when reference.spice's PNP cards gained emitter geometry "
        "(a transcription fix, not a drawn-shape change), held at 4 across "
        "issue #91's R2-leg-length fix and picking up klayout-tools#518/"
        "#519/#521/#526's `res_high_po` head-resistance correction (which "
        "made the disclosed `r` delta *larger*, not smaller, because this "
        "flow's own trim-tap decomposition charges the fixed per-instance "
        "offset once per drawn primitive rather than once per logical "
        "device -- see RES_HEAD_RESISTANCE_NOTE), and now moves 4 -> 1 "
        "with issue #108's resize propagation: reference.spice now states "
        "the CHAINED value for `R1`/`R2A`/`R2B` (RES_RESIZE_NOTE, "
        "reference.spice's own RESISTOR VALUE CONVENTION note) instead of "
        "the single-device approximation, which is what `combine_devices` "
        "actually sums the layout side to -- so the three `device.property` "
        "mismatches this cause carried are gone, not just smaller."
    )
    if full_connectivity:
        a(
            "- **Fully inter-block routed, but not on one plane.** All "
            f"{len(fully_drawn)}/{len(coverage)} schematic inter-block nets "
            "are joined across every block they reach -- and "
            f"{len(met2_hop_rows)} of the hops that get them there are drawn "
            "on met2, not met1. Most of that plane's geometry is now checked "
            "by `klt drc` itself (klayout-tools#513, merged via #515); this "
            "repo's own `layout/bin/met2_drc.py` covers the one rule that "
            "isn't (`m2.6`, met2 min area) against the installed PDK's "
            "source rules. The connectivity itself is the extractor's, "
            "since klayout-tools#511 made met2 a level of the curated "
            "extraction deck's own graph."
        )
    else:
        a(
            "- **Not fully inter-block routed either.** "
            f"{len(fully_drawn)}/{len(coverage)} schematic inter-block nets "
            "are joined across every block they reach. The rest are "
            "*partial*, not absent: each is drawn between the blocks the "
            "router could reach and stops where it could not, which the "
            "coverage table names per row."
        )
    a(
        "- **MOS finger bussing is drawn, and the m=N devices it produces "
        "are this record's own claim, not the tool's.** Each `bus_mos_comb` "
        "trunk is hand-placed geometry; what makes it evidence is that "
        "`klt extract` reads the drawn shapes back and `klt lvs`'s "
        "`combine_devices` folds the fingers into a single device with the "
        "schematic's own W -- see the device table in the extracted netlist, "
        "not this sentence."
    )
    a(
        "- **The PNP devices are drawn geometry recognised by the deck, not "
        "vendor `pnp_05v5` cell instances.** `klt gen bjt_array` draws a "
        "matching-faithful floorplan from base layers by design (its own "
        "generator note says so), and since upstream klayout-tools#440 it "
        "draws sky130's bipolar marker and per-unit well tap itself -- which "
        "makes the geometry *extract* as `pnp`, not a SPICE-model-exact "
        "device. PR #64's local recognition overlay is retired here."
    )
    a(
        "- **Array dummies are excluded, and the substrate correspondence "
        "is real drawn connectivity -- both new this increment.** The "
        f"`pnp` and `{RES_CLASS}` counts above already exclude each "
        f"array's dummy edge units ({extract.get('dummy_devices_dropped', 0)} "
        "dropped this run); see \"Retired since the last increment\" above "
        "for both."
    )
    a("")
    a("## Provenance")
    a("")
    a(f"- Record ID: `{args.record_id}`")
    a(f"- `klt` version: `{klt_version}` (pinned, see `layout/requirements.txt`)")
    a(
        "- KLayout engine version: "
        f"`{drc.get('provenance', {}).get('klayout_version')}`"
    )
    a(f"- Repo state: `{sha}` on `{branch}`" + (" (dirty)" if dirty else ""))
    a("")
    a("## Links")
    a("")
    a("- [`compose.request.json`](compose.request.json), [`compose.json`](compose.json)")
    a(
        "- [`drc.json`](drc.json), [`met2-drc.json`](met2-drc.json), "
        "[`extract.json`](extract.json), "
        "[`lvs.combined.json`](lvs.combined.json), [`lvs.json`](lvs.json)"
    )
    a("- [`bus-summary.json`](bus-summary.json)")
    a(f"- [`{cell}.extract.spice`]({cell}.extract.spice), [`reference.spice`](reference.spice)")
    a(f"- [`{cell}.gds`]({cell}.gds)")
    a("- [`render.json`](render.json), [`renders/overview.png`](renders/overview.png)")
    a("")

    (out_dir / "record.md").write_text("\n".join(lines))
    print("\n".join(lines))

    # The flow's own gate: DRC must be clean, the ladder must be at full
    # scale *and* draw the leg length design/bandgap_core.sch specifies
    # (issue #91), every device class must extract, and pins must be
    # promoted.
    # LVS-clean is NOT gated here -- it is blocked upstream (MOS_GATE_NOTE)
    # and the record above states so explicitly rather than silently passing.
    # The drawn-short check IS gated: a met1 rectangle of one node touching
    # another node's is a short, and a short that reads as connectivity is
    # exactly the false evidence this flow must never produce. So is the
    # label-collision check, which catches the same failure arriving through a
    # pad rather than through metal (see assert_no_merged_pin_names). So is
    # the split-node check, the inverse of the drawn-short one: a node this
    # router reports as fully routed whose metal is still in two pieces (see
    # split_routed_nets).
    gate = flow_gate(
        drc_clean=drc_clean,
        within_budget=within_budget,
        full_scale_ladder=full_scale_ladder,
        r2_leg_matches=r2_length["matches"],
        all_classes=all_classes,
        pin_count=pin_count,
        met1_conflicts=met1_conflicts,
        merged_pin_names=merged_pin_names,
        split_routed=met1_split_routed,
        met2_drc_clean=met2_drc.get("status") == "clean",
    )
    failed = [name for name, passed in gate.items() if not passed]
    if failed:
        print(
            "gen_bandgap_routed.py: FAILED gate conditions: " + ", ".join(failed),
            file=sys.stderr,
        )
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
