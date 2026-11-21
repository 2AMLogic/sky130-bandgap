#!/usr/bin/env python3
"""layout/bin/gen_bandgap_routed.py -- issue #62: route the bandgap-core
floorplan skeleton to real inter-block connectivity, extract it, and LVS it
against the xschem-derived reference netlist.

Standard library only (matches sim/bin/corner-run.py's and
layout/bin/render-record.py's convention). Invoked by
layout/bin/run-bandgap-routed-flow.sh, which supplies
--out-dir/--record-id/--klt/--pdk-variant the same way
run-bandgap-floorplan-flow.sh used to invoke gen_bandgap_floorplan.py.

This is the routed successor to gen_bandgap_floorplan.py, the #15
placement-only DRC flow this one supersedes, removed in #217 (#215) -- its
one historical record is left in place as append-only evidence. Relative to
that skeleton, this flow draws real inter-block metal (met1, escaping to
met2 where met1 congestion forces it -- see
layout/generator-notes.md#met2-escape-note), draws and
busses each matched device group (resistor ladders, MOS combs, PNP arrays --
see MET1_BUS_NOTE / layout/generator-notes.md#mos-gate-note), promotes
gate-only and trim-tap nodes
through top-level pins, and runs `klt extract` + `klt lvs` against the
xschem-derived reference netlist, recording the result rather than skipping
it as not-yet-meaningful.

The `*_NOTE` constants below (SUBSTRATE_NET_NOTE, DUMMY_DEVICE_NOTE,
INTERNAL_NODE_LABEL_NOTE, RES_TRIM_LENGTH_NOTE, RES_BULK_ARITY_NOTE,
RES_HEAD_SIZING_NOTE, MCC_AREA_UM2_NOTE, PNP_EMITTER_GEOMETRY_NOTE, etc.)
each carry the inline rationale for one specific design or tool-capability
decision, next to the code they explain -- these are the notes the record
interpolates. The notes the record cites by name without interpolating are
anchored sections in `layout/generator-notes.md` instead (issue #552).

`layout/matching-plan.md` is the single source of truth for this flow's
design history -- every increment since issue #62 (device recognition,
metal planes, resistor/PNP LVS-model transcription fixes, trim-ladder
resizes, and the current disclosed-mismatch state) is recorded there, in
more depth and kept current, rather than duplicated here.
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
from bus_routing import MOS_HALVES, build_bus_overlay, trim_tap_port  # noqa: E402
from layout_common import (  # noqa: E402
    DIRECTION_NORTH,
    N_R1,
    N_R2_COARSE,
    N_R2_TRIM_UNITS,
    RING_MARGIN_UM,
    klt_gen,
    run_klt_json,
    union_bbox,
)

# routed_record.py reads this module's tables back (BLOCKS, the *_NOTE
# strings), so it still imports this module. When this file is run directly
# (`__name__ == "__main__"`), alias the registered name to the running
# instance so that import does not execute the file a second time.
sys.modules.setdefault("gen_bandgap_routed", sys.modules[__name__])

# ---------------------------------------------------------------------------
# Friction notes (upstream tool gaps this script works around or is limited
# by). Each is filed at 2AMLogic/klayout-tools per CLAUDE.md's protocol as a
# generic tool-gap description; the design-specific consequence lives here,
# in layout/generator-notes.md (the notes the record cites by anchor rather
# than interpolating) and in layout/matching-plan.md, never in that tracker.
# ---------------------------------------------------------------------------
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
    "devices; layout/generator-notes.md#res-trim-topology-note's "
    "structural gap is. See "
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
#: Why n_r2 moved again, 50 -> 51, and why N_R2_COARSE followed it 48 -> 49.
#: Not a layout-side finding -- transcribes issue #178's schematic-side
#: sizing decision, which is itself a consequence of finally MODELLING the
#: chained topology layout/generator-notes.md#res-head-resistance-note
#: quantifies instead of sizing around it.
RES_HEAD_SIZING_NOTE = (
    "DR-003 (layout/generator-notes.md#res-head-resistance-note) "
    "established that this flow's drawn "
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
    "layout/generator-notes.md#res-resize-note's reason (branch current, "
    "hot-corner headroom); no "
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

BLOCK_MARGIN_UM = 16.0  # clearance between blocks placed side by side in a row
ROW_MARGIN_UM = 22.0  # clearance between stacked rows
RING_WIDTH_UM = 2.0
RING_CONTACTS_PER_SIDE = 8
ROUTE_WIDTH_UM = 0.5

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
#: DR-002's chained-topology LSB comfort bound; see
#: layout/generator-notes.md#res-trim-lsb-note).
R_LSEG_TRIM_UM = 0.5
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
#: (chained-array model + DR-005 re-centring); see
#: layout/generator-notes.md#res-resize-note and RES_HEAD_SIZING_NOTE.
SCH_N_R2 = 51  # .param n_r2=51
#: 1 -> 0.5 by issue #106/PR #111 (DR-002's chained-LSB revision); see
#: layout/generator-notes.md#res-trim-lsb-note.
SCH_R_LSEG_TRIM_UM = 0.5  # .param r_lseg_trim=0.5
SCH_N_R2_TRIM = 0  # .param n_r2_trim=0 (DR-002's untrimmed code)
#: The per-leg length design/bandgap_core.sch specifies, in um (250.0 since
#: the issue #99/#108 resize -- unchanged by issue #112's r_lseg_trim
#: halving, since SCH_N_R2_TRIM=0 makes the trim term a no-op here; was
#: 270.0 before #99/#108).
R2_LEG_SPEC_UM = SCH_R_LSEG_UM * SCH_N_R2 + SCH_R_LSEG_TRIM_UM * SCH_N_R2_TRIM
M_OUT = 2
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
#: layout/generator-notes.md#mcc-mim-infeasible-note for why this is drawn
#: as the MOS cap the schematic states rather than a `cap_mim` overlay.
AMP_M_CC = 16

# ---------------------------------------------------------------------------
# Startup-injector parameters, transcribed from design/startup_injector.sch's
# own SU_PARAMS block and its six device cards (issue #285). Until this
# increment the injector was drawn only as a schematic and the composed cell
# shipped without it, which is what made row 8e of
# design/block-characterization-report.md a by-construction FAIL and what
# made every post-layout row a measurement of a circuit the schematic rows do
# not describe. See layout/generator-notes.md#startup-injector-note.
# ---------------------------------------------------------------------------
#: MPC1/MPC2, the two-high diode-connected PMOS reference fed *from* GDRV
#: (`.param m_ref=1`, W=1 L=20 each). Both are `pfet_g5v0d10v5` with their
#: bulk on VDD, so they are one matched pair in one n-well -- exactly the
#: shape `klt gen diff_pair` draws, and the only injector devices that pair
#: at all (every other one has its own W/L).
SU_W_REF_UM = 1.0
SU_L_REF_UM = 20.0
M_SU_REF = 1
#: MNS, the sense NMOS whose gate is the core's own VOUT (`.param
#: m_sense=1`, W=48 L=0.5).
SU_W_SENSE_UM = 48.0
SU_L_SENSE_UM = 0.5
M_SU_SENSE = 1
#: MNI, the injector NMOS that evicts the degenerate state by pulling GDRV
#: down (`.param m_inj=1`, W=10 L=0.5).
SU_W_INJ_UM = 10.0
SU_L_INJ_UM = 0.5
M_SU_INJ = 1
#: MNC, the railed-branch clamp (issue #52; `.param m_clamp=1`, W=4 L=1).
SU_W_CLAMP_UM = 4.0
SU_L_CLAMP_UM = 1.0
M_SU_CLAMP = 1
#: QS, the diode-connected PNP that references MNS's release threshold to a
#: VBE (`.param m_pnp=8`) -- the same `pnp_05v5_W0p68L0p68` unit device the
#: core's CTAT array uses, at the same 8-unit count, so it is drawn with the
#: identical `bjt_array` params as `pnp_ctat`.
N_PNP_SU = 8

# ---------------------------------------------------------------------------
# Thick-oxide (5 V) device flavour (issue #620). DR-005 runs the block from
# 3.3 V +/-10% and every schematic MOS card is a `*_g5v0d10v5` (5 V
# thick-oxide) device -- through the thirty-sixth increment this layout drew
# every one of them as thin-oxide 1.8 V geometry, and nothing checked the
# difference: the curated deck's extraction binds both flavours to the same
# generic `nfet`/`pfet` class, so LVS passed either way. The constants below
# drive the three halves of the correction: the generator flavour marker
# (every MOS block's `voltage_flavor` param), the legality overlay
# (:func:`build_hv_fixup_overlay` -- see HV_FIXUP_NOTE), and the PDK-bound
# flavour gate (:func:`check_mos_flavour`).
# ---------------------------------------------------------------------------
#: The `klt gen` `mos_array`/`diff_pair` thick-oxide marker name on sky130.
#: Draws the 75/20 `hvi` voltage-class marker (plus the implant/npc shapes
#: the flavour needs) over each unit device; `drc_hints.voltage_flavor`
#: echoes it back and `voltage_flavor_mark_present` confirms the marker
#: landed. Both pinned-klt PCells support it (verified against klt 0.8.0).
MOS_VOLTAGE_FLAVOUR = "hvi"
#: The wrapper cards a PDK-bound `klt extract --pdk sky130A` must emit for
#: every MOS finger once the geometry is thick-oxide, by polarity -- the
#: exact model names of design/bandgap_core.sch's own device library.
HVI_MOS_MODELS: dict[str, str] = {
    "nfet": "sky130_fd_pr__nfet_g5v0d10v5",
    "pfet": "sky130_fd_pr__pfet_g5v0d10v5",
}
#: The raw-netlist model-name field of a subckt-wrapper `X` card (`X<name>
#: d g s b <model> ...`), 0-based index 5 -- the same field the issue #620
#: baseline awk reads as `$6`.
X_CARD_MODEL_FIELD = 5
#: Margins of the legality overlay (:func:`build_hv_fixup_overlay`), all
#: derived from the pinned PDK's own source-deck thresholds -- see
#: HV_FIXUP_NOTE for why each is what it is.
#: hvi/nwell rect margin around each MOS block's own reported bbox (um):
#: puts the drawn hvi 0.35+ beyond every diff/tap edge (hvdifftap.22 needs
#: 0.18, hvdifftap.19 needs 0.33 from the tap ring once hvi covers the
#: nwell), and keeps the enlarged pfet nwell 0.4 beyond its tap ring.
HVI_FIXUP_MARGIN_UM = 0.2
#: npc square half-side margin around each `mos_array` gate-contact licon
#: (um): the generator draws a 0.36 um npc over the 0.17 um licon (0.095
#: enclosure); the deck's `licon.15` wants 0.1. A 0.11 margin (0.39 square)
#: clears it and still lands inside the 0.42 um poly landing pad.
NPC_GATE_ENCLOSURE_UM = 0.11
#: licon drawn size (um), the same fixed square met1_bus draws.
LICON_UM = 0.17

#: Rule-category prefixes of the sky130A source deck's HV group -- the
#: categories the flow's HV DRC step (:func:`run_hv_drc`) gates on. Every
#: rule that names hvi (75/20) or its well/tap/poly interactions lands in
#: one of these (`hvi.*`, `hvdifftap.*`, `hvnwell.*`/`hvnwel.*`,
#: `hvpoly.*`, `hvntm.*`); the rest of the FEOL group the run *reports*
#: but does not gate on, exactly like the curated deck's own findings.
HV_RULE_PREFIXES: tuple[str, ...] = (
    "hvi.",
    "hvdifftap.",
    "hvnwell.",
    "hvnwel.",
    "hvpoly.",
    "hvntm.",
)
#: The isolated enclosure control :func:`run_hv_drc` regenerates from
#: BLOCKS and feeds `klt drc --negative-control`: the raw generator output
#: for the injector NMOS, whose un-corrected hvi marker sits 0.15 um off its
#: diffusion -- 0.03 um short of `hvdifftap.22`. A run whose control comes
#: back clean has not executed the HV group and must not be trusted.
HV_DRC_CONTROL_BLOCK = "su_inj"
HV_DRC_CONTROL_CATEGORIES = ("hvdifftap.22",)

HV_FIXUP_NOTE = (
    "The pinned `klt`'s `voltage_flavor='hvi'` marker is necessary for a "
    "5 V device but not sufficient for a legal one, and the overlay this "
    "flow draws is what makes the geometry PDK-legal. Measured on the "
    "isolated blocks with the pinned PDK's own source deck (FEOL enabled, "
    "issue #620): the generator draws its 75/20 `hvi` marker 0.15 um past "
    "each block's diffusion -- 0.03 um short of `hvdifftap.22` (min. hvi "
    "enclosure of diff or tap, 0.18 um); on the PMOS blocks the marker "
    "additionally fails `hvdifftap.17` (0.15 < 0.33 hvnwell enclosure of "
    "diff) and `hvdifftap.20` (0.30 < 0.43 hvnwell spacing to the well "
    "tap ring), and no hvi shape alone can fix those two -- the tap ring "
    "either sits inside hvi (then `hvdifftap.19` binds and the generator's "
    "nwell, only 0.2 um beyond the ring, fails its 0.33 um enclosure) or "
    "outside it (then `.20` binds). `mos_array`'s own gate contact draws "
    "its 95/20 npc with 0.095 um enclosure where `licon.15` wants 0.1. "
    "The overlay therefore draws, per MOS block: an `hvi` rect at the "
    "block's reported bbox + 0.2 um (covering diff, poly, implant and the "
    "tap ring with margin over every threshold above), the *same* rect on "
    "64/20 `nwell` for the pfet blocks (extending the generator's well "
    "0.4 um past the ring, which is what closes `.19`/`.20` without "
    "moving a device), and a 0.39 um npc square over each `mos_array` "
    "gate licon (0.11 enclosure, still inside the 0.42 um poly landing "
    "pad). Verified per block type against the FEOL-enabled deck: zero "
    "HV-category markers on every corrected block. The generator-side "
    "half of this (markers sized to the PDK's own enclosure thresholds) "
    "is filed upstream as 2AMLogic/klayout-tools#7061."
)

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
#     reason in layout/generator-notes.md#mos-gate-note.
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
            # shrinking 0.5 um). See
            # layout/generator-notes.md#res-resize-note for why N_R2_COARSE
            # first moved (issue #99/#108) and
            # layout/generator-notes.md#res-trim-lsb-note for why it
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
            "voltage_flavor": MOS_VOLTAGE_FLAVOUR,
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
            "voltage_flavor": MOS_VOLTAGE_FLAVOUR,
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
            "voltage_flavor": MOS_VOLTAGE_FLAVOUR,
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
            "voltage_flavor": MOS_VOLTAGE_FLAVOUR,
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
            "voltage_flavor": MOS_VOLTAGE_FLAVOUR,
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
    # --- design/startup_injector.sch (issue #285) ---------------------------
    # All five injector blocks share row 3 with `amp_cc` rather than opening a
    # row of their own, and that is an AREA decision, not a routing one: row 3
    # is 63.38 um tall (amp_cc sets it) and 102 um narrower than the widest
    # row, so five blocks whose tallest is MNS's 48.82 um fit inside the
    # height the floorplan already pays for. A sixth row would have cost
    # ROW_MARGIN_UM + 48.82 um of new height across the cell's full width --
    # ~21,000 um^2, which lands the composed cell over DR-007's 80,000 um^2
    # budget. Widening one existing row costs ~4,000 um^2 instead. See
    # layout/generator-notes.md#startup-injector-note for the generator
    # choice and layout/generator-notes.md#startup-composed-note for what
    # drawing them changes about the evidence.
    {
        "id": "su_clamp",
        "row": 3,
        "align": "bottom",
        "generator": "mos_array",
        "params": {
            "w_um": SU_W_CLAMP_UM,
            "l_um": SU_L_CLAMP_UM,
            "rows": 1,
            "cols": 1,
            "dummy": 0,
            "flavor": "nfet",
            "voltage_flavor": MOS_VOLTAGE_FLAVOUR,
            "gate_contact": True,
        },
        "matched_group_label": "MNC (railed-branch clamp NMOS, issue #52)",
        "real_target": f"m_clamp={M_SU_CLAMP}, W={SU_W_CLAMP_UM:.0f} "
        f"L={SU_L_CLAMP_UM:.0f} (design/startup_injector.sch); drawn 1:1 as "
        "a single unit device -- it pairs with nothing else in the cell",
    },
    {
        "id": "su_sense",
        "row": 3,
        "generator": "mos_array",
        "params": {
            "w_um": SU_W_SENSE_UM,
            "l_um": SU_L_SENSE_UM,
            "rows": 1,
            "cols": 1,
            "dummy": 0,
            "flavor": "nfet",
            "voltage_flavor": MOS_VOLTAGE_FLAVOUR,
            "gate_contact": True,
        },
        "matched_group_label": "MNS (VBE-referenced sense NMOS)",
        "real_target": f"m_sense={M_SU_SENSE}, W={SU_W_SENSE_UM:.0f} "
        f"L={SU_L_SENSE_UM:.1f} (design/startup_injector.sch); drawn 1:1 as "
        "a single unit device, gate on the core's own VOUT (the schematic's "
        "VSENSE input)",
    },
    {
        "id": "pnp_su",
        "row": 3,
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
        "bus": {"kind": "bjt_parallel", "nets": {"_E": "NE", "_B": "VSS"}},
        "matched_group_label": "QS (startup threshold PNP, small unit "
        "W0p68L0p68)",
        "real_target": f"m_pnp={N_PNP_SU} sky130_fd_pr__pnp_05v5_W0p68L0p68 "
        "(design/startup_injector.sch); drawn 1:1 (8 real units, 2x4 "
        "common-centroid) -- the identical unit device and count as "
        "`pnp_ctat`, so it is drawn with identical params",
    },
    {
        "id": "su_ref",
        "row": 3,
        "generator": "diff_pair",
        "params": {
            "w_um": SU_W_REF_UM,
            "l_um": SU_L_REF_UM,
            "splits": M_SU_REF,
            "flavor": "pfet",
            "voltage_flavor": MOS_VOLTAGE_FLAVOUR,
            "mirror": True,
            "add_guard_ring": True,
            "ring_gap_side": "W",
            "ring_gap_um": 2.0,
        },
        "bus": {
            "kind": "mos_comb",
            "spine_side": "W",
            "nets": [
                {"net": "NC1",
                 "terminals": [("MPC1", "drain"), ("MPC1", "gate"),
                               ("MPC2", "source")]},
                {"net": "NG",
                 "terminals": [("MPC2", "drain"), ("MPC2", "gate")]},
                # GDRV last, so it is the node that also gets a spine-side
                # escape (it has the most partners off this block). At
                # `splits=1` each device is a single unit in a single device
                # row, so this block's three nodes never put more than two
                # lanes in the same 1 um row -- see the per-row dense rank in
                # bus_mos_comb and MOS_LANE_PITCH_UM.
                {"net": "GDRV", "terminals": [("MPC1", "source")]},
            ],
        },
        "matched_group_label": "MPC1/MPC2 (two-high diode-connected PMOS "
        "reference, fed from GDRV)",
        "real_target": f"m_ref={M_SU_REF}, W={SU_W_REF_UM:.0f} "
        f"L={SU_L_REF_UM:.0f} each (design/startup_injector.sch); drawn 1:1 "
        "-- the injector's only matched pair, and the only one of its six "
        "devices a `diff_pair` can express. NC1, the node between the two "
        "diodes, is entirely internal to this block and is drawn by its own "
        "intra-block comb",
    },
    {
        "id": "su_inj",
        "row": 3,
        "generator": "mos_array",
        "params": {
            "w_um": SU_W_INJ_UM,
            "l_um": SU_L_INJ_UM,
            "rows": 1,
            "cols": 1,
            "dummy": 0,
            "flavor": "nfet",
            "voltage_flavor": MOS_VOLTAGE_FLAVOUR,
            "gate_contact": True,
        },
        "matched_group_label": "MNI (degenerate-state eviction NMOS)",
        "real_target": f"m_inj={M_SU_INJ}, W={SU_W_INJ_UM:.0f} "
        f"L={SU_L_INJ_UM:.1f} (design/startup_injector.sch); drawn 1:1 as a "
        "single unit device",
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
            "voltage_flavor": MOS_VOLTAGE_FLAVOUR,
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
        "layout/generator-notes.md#mcc-mim-infeasible-note for why a "
        "`cap_mim` overlay (the "
        "operator's primary-path ruling on issue #62) cannot close this "
        "device instead",
    },
]

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
    "the `amp_cc` block above and "
    "layout/generator-notes.md#mcc-mim-infeasible-note for why it is a "
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
# Moved to bus_routing.py (issue #221); see its docstring for what moved.


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
#: because a MOS gate could not be wired at all
#: (layout/generator-notes.md#mos-gate-note), so each
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


# ---------------------------------------------------------------------------
# Thick-oxide legality overlay (issue #620) -- see HV_FIXUP_NOTE.
# ---------------------------------------------------------------------------
#: sky130 layers the overlay draws (same `[layer, datatype]` list shape
#: `klt draw` params and met1_bus use).
HVI_LAYER = [75, 20]
NWELL_LAYER = [64, 20]
NPC_LAYER = [95, 20]


def mos_hvi_blocks(
    blocks: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Every MOS block drawn at the thick-oxide flavour (issue #620)."""
    src = BLOCKS if blocks is None else blocks
    return [
        b
        for b in src
        if b["generator"] in ("mos_array", "diff_pair")
        and b["params"].get("voltage_flavor") == MOS_VOLTAGE_FLAVOUR
    ]


def build_hv_fixup_overlay(
    klt: str,
    out_dir: Path,
    pdk_info: dict[str, Any],
    reports: dict[str, dict[str, Any]],
    origins: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """Draw the thick-oxide legality overlay for every `hvi` MOS block.

    One `klt draw` cell (`bandgap_core_hv_fixup`), composed into the inner
    cell alongside the bus overlay at origin (0,0) with shapes in absolute
    floorplan coordinates. Three shape families only, all derived from the
    blocks' own reported bboxes/ports (never a hand-placed coordinate), all
    snapped to the 5 nm grid -- see HV_FIXUP_NOTE for the threshold each
    one closes:

    * `hvi` (75/20) at each block's placed bbox + HVI_FIXUP_MARGIN_UM;
    * the same rect on `nwell` (64/20) for the pfet blocks, whose tap
      rings the hvi covers;
    * `npc` (95/20) at 2*NPC_GATE_ENCLOSURE_UM + LICON_UM around each
      `mos_array` gate-contact licon (the `U<i>_G` ports).

    Returns a `klt gen`-shaped report with a degenerate bbox, for the same
    reason :meth:`met1_bus.Met1Bus.emit` declares one: a real bbox would
    make `gen-compose`'s router treat the whole floorplan as an obstacle.
    """
    cell_name = "bandgap_core_hv_fixup"
    shapes: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []
    for block in mos_hvi_blocks():
        bid = block["id"]
        bbox = reports[bid]["bbox_um"]
        ox, oy = origins[bid]["x"], origins[bid]["y"]
        x0, y0 = met1_bus.snap_to_grid(
            bbox["x0"] + ox - HVI_FIXUP_MARGIN_UM
        ), met1_bus.snap_to_grid(bbox["y0"] + oy - HVI_FIXUP_MARGIN_UM)
        x1, y1 = met1_bus.snap_to_grid(
            bbox["x1"] + ox + HVI_FIXUP_MARGIN_UM
        ), met1_bus.snap_to_grid(bbox["y1"] + oy + HVI_FIXUP_MARGIN_UM)
        entry: dict[str, Any] = {
            "block": bid,
            "hvi_rect_um": [x0, y0, x1, y1],
            "nwell_rect_um": None,
            "npc_squares_um": [],
        }
        shapes.append({"layer": HVI_LAYER, "rect_um": [x0, y0, x1, y1]})
        if block["params"]["flavor"] == "pfet":
            # The pfet tap ring must end up inside hvi AND inside an nwell
            # that encloses it by 0.33 (hvdifftap.19/.20) -- the generator's
            # own nwell is 0.2 short, so the overlay extends it by the same
            # rect. The generator's nwell merges with this on 64/20.
            shapes.append({"layer": NWELL_LAYER, "rect_um": [x0, y0, x1, y1]})
            entry["nwell_rect_um"] = [x0, y0, x1, y1]
        if block["generator"] == "mos_array":
            half = LICON_UM / 2.0 + NPC_GATE_ENCLOSURE_UM
            for port in reports[bid]["ports"]:
                if not port["name"].endswith("_G"):
                    continue
                px = met1_bus.snap_to_grid(port["x_um"] + ox)
                py = met1_bus.snap_to_grid(port["y_um"] + oy)
                entry["npc_squares_um"].append(
                    [px - half, py - half, px + half, py + half]
                )
                shapes.append(
                    {
                        "layer": NPC_LAYER,
                        "rect_um": [px - half, py - half, px + half, py + half],
                    }
                )
        summary.append(entry)

    params_path = out_dir / f"{cell_name}.draw.json"
    params_path.write_text(
        json.dumps({"shapes": shapes, "labels": []}, indent=2) + "\n"
    )
    gds_path = out_dir / f"{cell_name}.gds"
    run_klt_json(
        klt,
        "draw",
        "--params",
        str(params_path),
        "--cell-name",
        cell_name,
        "-o",
        str(gds_path),
    )
    report = {
        "schema_version": 1,
        "generator": "draw",
        "cell_name": cell_name,
        "gds_path": str(gds_path.resolve()),
        "pdk": pdk_info,
        "bbox_um": {"x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 0.0},
        "device_count": 0,
        "ports": [],
        "drc_hints": {
            "min_spacing_um": None,
            "matched_group_id": None,
            "snapped_to_grid": False,
            "notes": ["thick-oxide legality overlay (issue #620)"],
        },
        "warnings": [],
        "shape_count": len(shapes),
        "blocks": summary,
    }
    (out_dir / f"{cell_name}.gen.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    (out_dir / f"{cell_name}.summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    return report


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
    mos_flavour_clean: bool = True,
    hv_drc_clean: bool = True,
    erc_supply_clean: bool = True,
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
    blocked upstream too (layout/generator-notes.md#mos-gate-note,
    layout/generator-notes.md#res-flavor-note) -- as of the
    thirtieth increment (MCC drawn as a MOS cap,
    layout/generator-notes.md#mcc-mim-infeasible-note) it
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
    (layout/generator-notes.md#met2-escape-note) -- the
    width/spacing/enclosure rules landed via
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
        # Issue #620: the schematic's MOS cards are all 5 V thick-oxide
        # devices, so the layout must bind every finger to the matching
        # `*_g5v0d10v5` wrapper in a PDK-bound extraction -- one thin-oxide
        # card among 73 correct ones fails this row (see check_mos_flavour).
        "mos_flavour_bound": mos_flavour_clean,
        # The HV rule group of the pinned PDK's own source deck (FEOL on),
        # run with a failing enclosure control: zero applicable HV
        # violations on the composed GDS (see run_hv_drc).
        "hv_drc_clean": hv_drc_clean,
        # Supply/n-well-tie ERC on this exact GDS, gated exactly like
        # run-erc-supply-flow.sh gates it, negative control included (see
        # run_supply_erc).
        "erc_supply_clean": erc_supply_clean,
    }


# ---------------------------------------------------------------------------
# Thick-oxide flavour gate (issue #620): the raw, pre-translation output of
# a PDK-bound extraction must bind every schematic MOS finger to the 5 V
# wrapper card of its polarity.
# ---------------------------------------------------------------------------
#: `M<name> d g s b <model> [param=val ...]` -- the model field of a
#: reference M card, 0-based index 5.
M_CARD_MODEL_FIELD = 5


def expected_mos_fingers(reference_text: str) -> dict[str, int]:
    """Sum the parallel multiplier `m` of every MOS card, per polarity.

    The reference netlist is the schematic-side truth: each `M` card states
    one device's polarity (its model name) and its finger count (`m=`,
    default 1). Summing per polarity gives exactly the number of unit
    devices the layout must draw -- for this reference, 19 NFET and 54 PFET
    fingers (16 of the PFET fingers are MMCC, the compensation cap). A
    layout that binds a different number of raw wrapper cards is a layout
    that changed multiplicity, whatever its schematic transcription says.
    """
    counts = {"nfet": 0, "pfet": 0}
    for line in reference_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("*") or stripped[0] not in "Mm":
            continue
        tokens = stripped.split()
        if len(tokens) <= M_CARD_MODEL_FIELD:
            continue
        model = tokens[M_CARD_MODEL_FIELD]
        if model not in counts:
            continue
        m = 1
        for token in tokens[M_CARD_MODEL_FIELD + 1 :]:
            key, _, value = token.partition("=")
            if key.lower() == "m" and value:
                try:
                    m = int(float(value))
                except ValueError:
                    m = 1
        counts[model] += m
    return counts


def raw_mos_card_counts(netlist_text: str) -> dict[str, int]:
    """Count subckt-wrapper `X` cards per `sky130_fd_pr__*fet*` model name.

    A PDK-bound `klt extract --pdk sky130A` writes every extracted device
    as an `X` card naming the PDK wrapper it bound (`X$1 d g s b
    sky130_fd_pr__nfet_g5v0d10v5 L=... W=...`), *before* any translation to
    the generic classes the curated deck/LVS path compares -- this is the
    raw binding, which is exactly why it can see the oxide flavour the
    curated netlist cannot. Resistors and PNPs never match `*fet*`, so the
    count is a MOS-only census by construction (verified on this cell's own
    extraction: 73 fet cards, 0 other matches).
    """
    counts: dict[str, int] = {}
    for line in netlist_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped[0] not in "Xx":
            continue  # '+' continuation lines never carry another card
        tokens = stripped.split()
        if len(tokens) <= X_CARD_MODEL_FIELD:
            continue
        model = tokens[X_CARD_MODEL_FIELD]
        if "sky130_fd_pr__" in model and "fet" in model:
            counts[model] = counts.get(model, 0) + 1
    return counts


def check_mos_flavour(
    netlist_text: str, expected: dict[str, int]
) -> dict[str, Any]:
    """Score the raw PDK-bound netlist against the schematic's fingers.

    Passes only when every polarity's finger count binds to the 5 V
    thick-oxide wrapper exactly and no MOS card binds anywhere else. Both
    halves are needed to catch a *single* wrong card: one thin-oxide card
    among otherwise-correct devices leaves the HVI count one short (caught
    by the exact-count comparison) and adds one unexpected model (caught by
    the census), so the failure names both.
    """
    census = raw_mos_card_counts(netlist_text)
    observed = {
        polarity: census.get(model, 0)
        for polarity, model in HVI_MOS_MODELS.items()
    }
    unexpected = {
        model: n
        for model, n in sorted(census.items())
        if model not in HVI_MOS_MODELS.values()
    }
    mismatches = {
        polarity: {
            "expected": expected[polarity],
            "observed": observed[polarity],
        }
        for polarity in HVI_MOS_MODELS
        if observed[polarity] != expected[polarity]
    }
    return {
        "clean": not mismatches and not unexpected,
        "expected": dict(expected),
        "observed": observed,
        "unexpected_mos_models": unexpected,
        "mismatches": mismatches,
    }


def run_pdk_bound_extract(
    klt: str, gds_path: str, top: str, out_dir: Path, cell: str
) -> tuple[str, dict[str, Any]]:
    """Run the PDK-bound extraction whose raw netlist the flavour gate reads.

    A separate run from the curated-deck extraction the flow's LVS uses:
    `--pdk` is what makes `klt extract` bind devices to the PDK's own
    wrapper cards (the curated run's generic `nfet`/`pfet` M cards carry no
    flavour and never could). The generic extract stays the LVS input;
    nothing about it changes.
    """
    netlist_path = out_dir / f"{cell}.pdk.spice"
    extract = run_klt_json(
        klt,
        "extract",
        gds_path,
        "--deck",
        "sky130",
        "--pdk",
        "sky130A",
        "--top",
        top,
        "-o",
        str(netlist_path),
    )
    (out_dir / "extract.pdk.json").write_text(
        json.dumps(extract, indent=2) + "\n"
    )
    return netlist_path.read_text(), extract


def sha256_of(path: str | Path) -> str:
    """Bare sha256 of a file, via the repo's one implementation.

    `scripts/ci/content_hash.py` owns every SHA-256 call site (issue #538
    consolidated ten drifting copies into it), so this delegates rather
    than re-implementing -- the digest convention (bare hex here, the
    `sha256:`-tagged form where a contract needs it) stays visible in the
    helper's name at the call site. Imported lazily so unit tests that
    import this module never touch the path dance.
    """
    ci_dir = str(Path(__file__).resolve().parents[2] / "scripts" / "ci")
    if ci_dir not in sys.path:
        sys.path.insert(0, ci_dir)
    from content_hash import sha256_file  # noqa: E402  -- repo-owned helper

    return sha256_file(str(path))


# ---------------------------------------------------------------------------
# HV DRC (issue #620): the pinned PDK's own source deck with FEOL enabled,
# the HV rule group gated, the raw generator output as the failing control.
# ---------------------------------------------------------------------------
def pdk_klayout_dir(klt: str, pdk: str) -> Path:
    """`libs.tech/klayout` of the PDK install `klt pdk find` resolves."""
    info = run_klt_json(klt, "pdk", "find", "--pdk", pdk)
    klayout = Path(info["assets"]["klayout"])
    if not klayout.is_dir():
        raise RuntimeError(
            f"pdk find resolved no klayout assets for {pdk} "
            f"(got {klayout})"
        )
    return klayout


def score_hv_rule_counts(rule_counts: dict[str, int]) -> dict[str, Any]:
    """Split one DRC run's per-category counts into HV vs rest (issue #620).

    Pure function of the report's own `rule_counts` so the gate is
    unit-testable without a PDK: `hv_violations` is the HV-prefixed subset
    (only categories with markers), `non_hv_violation_count` sums the rest,
    and `clean` means zero HV markers -- the non-HV FEOL/BEOL findings are
    reported exactly like the curated deck's, never gated here.
    """
    hv = {
        cat: n
        for cat, n in sorted(rule_counts.items())
        if cat.startswith(HV_RULE_PREFIXES)
    }
    non_hv = sum(
        n
        for cat, n in rule_counts.items()
        if not cat.startswith(HV_RULE_PREFIXES)
    )
    return {
        "hv_violations": hv,
        "hv_violation_count": sum(hv.values()),
        "non_hv_violation_count": non_hv,
        "clean": not hv,
    }


def run_hv_drc(
    klt: str,
    gds_path: str,
    out_dir: Path,
    pdk: str,
) -> dict[str, Any]:
    """Run the HV rule group on the composed GDS, with a failing control.

    The curated deck `klt drc --deck sky130` runs carries no hvi/npc/nwell
    rule at all (its coverage block lists 75/20 among the stream layers it
    has no rules for), so thick-oxide legality is invisible to step 6. This
    step runs the *pinned PDK's own source deck* with its FEOL group
    enabled -- the HVI/HVDIFFTAP/HVPOLY/HVNTM checks the stock deck gates
    behind `FEOL = false` -- and gates on the HV subset. Two things make a
    zero-marker verdict evidence rather than an absence:

    * `--negative-control`: the raw generator output for the injector NMOS
      (regenerated from BLOCKS every run, before any overlay is composed)
      must produce `hvdifftap.22` markers -- the enclosure failure the
      legality overlay exists to fix. A deck run that cannot fail has not
      run.
    * the report's own `coverage.rule_categories` must declare the HV
      categories, so a deck revision that silently dropped the group fails
      the gate instead of passing it.

    ``--top`` is deliberately not passed: `--negative-control` reruns the
    deck on the control with identical options, and the control's top cell
    is not the composed cell's name. Both streams have exactly one top
    cell (the flow composes one; `klt gen` emits one), so omitting it
    checks the same thing.
    """
    deck_src = pdk_klayout_dir(klt, pdk) / "drc" / f"{pdk}.lydrc"
    if not deck_src.is_file():
        raise RuntimeError(f"no PDK DRC deck at {deck_src}")
    deck_text = deck_src.read_text()
    # FEOL    = false -> true: only the value of the deck's own switch
    # changes, so the copy stays the pinned deck in every other respect.
    feol_deck_text, n = re.subn(
        r"(?m)^(FEOL\s*=\s*)false", r"\g<1>true", deck_text, count=1
    )
    if n != 1:
        raise RuntimeError(
            f"{deck_src} carries no 'FEOL = false' assignment to enable"
        )
    deck_copy = out_dir / "sky130A.feol.lydrc"
    deck_copy.write_text(feol_deck_text)

    control_block = next(b for b in BLOCKS if b["id"] == HV_DRC_CONTROL_BLOCK)
    control_id = f"{HV_DRC_CONTROL_BLOCK}_hvi_control"
    klt_gen(
        klt,
        pdk,
        out_dir,
        {
            "id": control_id,
            "generator": control_block["generator"],
            "params": dict(control_block["params"]),
        },
    )
    control_gds = str((out_dir / f"{control_id}.gds").resolve())

    report = run_klt_json(
        klt,
        "drc",
        gds_path,
        "--engine",
        "klayout",
        "--deck-file",
        str(deck_copy),
        "--pdk",
        pdk,
        "--min-klayout-version",
        "0.30.12",
        "--negative-control",
        control_gds,
        "--negative-control-categories",
        ",".join(HV_DRC_CONTROL_CATEGORIES),
        allow_exit=(0, 3),
    )
    declared = set(report.get("coverage", {}).get("rule_categories", []))
    hv_declared = sorted(c for c in declared if c.startswith(HV_RULE_PREFIXES))
    control = report.get("negative_control", {})
    control_ok = control.get("status") == "passed" and all(
        cat in (control.get("rules_found") or [])
        for cat in HV_DRC_CONTROL_CATEGORIES
    )
    scores = score_hv_rule_counts(report.get("rule_counts", {}))
    verdict = {
        "deck": {
            "source": str(deck_src),
            "source_sha256": sha256_of(deck_src),
            "feol_enabled_copy": str(deck_copy),
            "feol_copy_sha256": sha256_of(deck_copy),
        },
        "control": {
            "block": HV_DRC_CONTROL_BLOCK,
            "gds": control_gds,
            "required_categories": list(HV_DRC_CONTROL_CATEGORIES),
            "report": control,
            "passed": control_ok,
        },
        "hv_categories_declared": hv_declared,
        "hv_categories_declared_count": len(hv_declared),
        "rule_counts": report.get("rule_counts", {}),
        "provenance": report.get("provenance", {}),
        **scores,
        "status": "clean" if scores["clean"] else "violations",
        "clean": scores["clean"] and control_ok and bool(hv_declared),
    }
    (out_dir / "hv-drc.json").write_text(json.dumps(verdict, indent=2) + "\n")
    return verdict


# ---------------------------------------------------------------------------
# Supply/tie ERC on the exact composed GDS (issue #620) -- the two specs
# run-erc-supply-flow.sh invokes, with the well boxes this GDS actually has.
# ---------------------------------------------------------------------------
def classify_well_boxes(
    boxes: list[dict[str, Any]],
    vdd_points: list[tuple[float, float]],
    vss_points: list[tuple[float, float]],
) -> dict[str, list[list[float]]]:
    """Assign each merged n-well box to the tie net owning its block.

    A box is a VDD well iff it contains the centre of one of the pfet MOS
    blocks (their drawn wells, which the legality overlay extends), and a
    VSS well iff it contains the centre of one of the PNP arrays' bboxes
    (their base tubs) -- the same five + three split the committed supply
    spec encodes for the pre-HVI GDS. A well matched by neither or by both
    is an error, not a guess: the tie declaration must account for every
    well the GDS draws.
    """
    assigned: dict[str, list[list[float]]] = {"VDD": [], "VSS": []}
    for box in boxes:
        x0, y0, x1, y1 = box["bbox_um"]
        vdd = any(
            x0 <= px <= x1 and y0 <= py <= y1 for px, py in vdd_points
        )
        vss = any(
            x0 <= px <= x1 and y0 <= py <= y1 for px, py in vss_points
        )
        if vdd and not vss:
            assigned["VDD"].append(box["bbox_um"])
        elif vss and not vdd:
            assigned["VSS"].append(box["bbox_um"])
        else:
            raise RuntimeError(
                f"n-well box [{x0}, {y0}, {x1}, {y1}] matched "
                f"{'both' if vdd and vss else 'neither'} tie nets"
            )
    return assigned


def run_supply_erc(
    klt: str,
    gds_path: str,
    out_dir: Path,
    repo_root: Path,
    reports: dict[str, dict[str, Any]],
    origins: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """Run the two supply specs on the exact composed GDS and gate them.

    `layout/bin/run-erc-supply-flow.sh` runs `klt erc` with
    `erc-supply-spec.json` and the swapped-net
    `erc-nwell-tie-spec.negative-control.json` -- but their `ties[]` carry
    the *previous* GDS's absolute well boxes, and this flow's HVI overlay
    enlarges the five PMOS wells, so those boxes would mis-describe this
    GDS. Both specs are therefore re-derived into the record: same
    stackup/nets/ties, with `well_requires_boxes` read back from this
    GDS's merged 64/20 region (via `gds_layer_boxes.py`, the same
    venv-klayout shell-out pattern `met2_drc.py` uses) and classified per
    tie net. Gating is erc_supply_record's own -- the same gate the
    committed item-11 evidence passes, negative control included.
    """
    from erc_supply_record import (  # local: shares layout/bin
        gate_negative_control,
        gate_supply_report,
        gate_tie_report,
    )

    python = Path(klt).with_name("python")
    if not python.exists():  # pragma: no cover -- non-venv klt on PATH
        python = Path(sys.executable)
    boxes_path = out_dir / "nwell-boxes.json"
    result = subprocess.run(
        [
            str(python),
            str(Path(__file__).resolve().parent / "gds_layer_boxes.py"),
            gds_path,
            "--layer",
            "64",
            "--datatype",
            "20",
            "-o",
            str(boxes_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"gds_layer_boxes.py failed ({result.returncode}):\n"
            f"{result.stderr[-2000:]}"
        )
    boxes = json.loads(boxes_path.read_text())["shapes"]

    def block_centre(bid: str) -> tuple[float, float]:
        bbox = reports[bid]["bbox_um"]
        return (
            (bbox["x0"] + bbox["x1"]) / 2.0 + origins[bid]["x"],
            (bbox["y0"] + bbox["y1"]) / 2.0 + origins[bid]["y"],
        )

    vdd_points = [
        block_centre(b["id"])
        for b in mos_hvi_blocks()
        if b["params"]["flavor"] == "pfet"
    ]
    vss_points = [
        block_centre(b["id"]) for b in BLOCKS if b["generator"] == "bjt_array"
    ]
    assigned = classify_well_boxes(boxes, vdd_points, vss_points)

    cell_dir = repo_root / "layout" / "bandgap-core"
    specs: dict[str, dict[str, Any]] = {}
    for kind, src_name, out_name in (
        ("supply", "erc-supply-spec.json", "erc-supply-spec.this-gds.json"),
        (
            "negative_control",
            "erc-nwell-tie-spec.negative-control.json",
            "erc-nwell-tie-spec.negative-control.this-gds.json",
        ),
    ):
        spec = json.loads((cell_dir / src_name).read_text())
        for tie in spec.get("ties", []):
            # Key the boxes by the net the tie's NAME declares, never its
            # `net` field: the negative-control spec is the supply spec
            # with the `net` fields swapped on the SAME boxes (its ties
            # are named `swapped_<net>_boxes_to_<other>`), so keying by
            # `net` there would hand each tie the other net's real boxes
            # and the control would pass instead of flag every well. The
            # first VDD/VSS token of the name is the box class in both
            # specs' naming convention.
            name_net = next(
                (
                    token.upper()
                    for token in tie["name"].split("_")
                    if token.upper() in assigned
                ),
                None,
            )
            if name_net is None:
                raise RuntimeError(
                    f"tie '{tie['name']}' names no VDD/VSS box class"
                )
            tie["well_requires_boxes"] = assigned[name_net]
        spec_path = out_dir / out_name
        spec_path.write_text(json.dumps(spec, indent=2) + "\n")
        specs[kind] = {"spec": spec, "path": spec_path, "source": src_name}

    verdict: dict[str, Any] = {
        "gds": str(gds_path),
        "gds_sha256": sha256_of(gds_path),
        "well_boxes": assigned,
        "well_box_count": {net: len(v) for net, v in assigned.items()},
    }
    overall_ok = True
    for kind in ("supply", "negative_control"):
        payload_path = out_dir / (
            "erc.json" if kind == "supply" else "erc.negative-control.json"
        )
        proc = subprocess.run(
            [
                klt,
                "erc",
                gds_path,
                str(specs[kind]["path"]),
                "--deck",
                "sky130",
                "--pdk",
                "sky130",
                "--format",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode not in (0, 3, 4):
            raise RuntimeError(
                f"klt erc ({kind}) exited {proc.returncode}:\n"
                f"{proc.stderr[-2000:]}"
            )
        payload_path.write_text(proc.stdout)
        report = json.loads(proc.stdout)
        if kind == "supply":
            ok, reasons = gate_supply_report(report, Path(gds_path))
            tie_ok, tie_reasons = gate_tie_report(report)
            ok = ok and tie_ok
            reasons = reasons + tie_reasons
        else:
            well_shapes = sum(len(v) for v in assigned.values())
            ok, reasons = gate_negative_control(report, well_shapes)
        verdict[kind] = {
            "spec_source": specs[kind]["source"],
            "spec_derived": str(specs[kind]["path"]),
            "report": payload_path.name,
            "exit": proc.returncode,
            "passed": ok,
            "reasons": reasons,
            "erc_status": report.get("erc_status"),
            "finding_count": report.get("erc_finding_count"),
        }
        overall_ok = overall_ok and ok
    verdict["clean"] = overall_ok
    (out_dir / "erc-verdict.json").write_text(
        json.dumps(verdict, indent=2) + "\n"
    )
    return verdict


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
    all (layout/generator-notes.md#mos-gate-note), but it can be named.

    Returns `(compose_response, pins)`.
    """

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
def main() -> int:
    from routed_record import render_record  # local: routed_record imports this module

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

    # --- 3b. Thick-oxide legality overlay (issue #620) ---------------------
    # Drawn after the bus overlay so both sit at absolute floorplan
    # coordinates and are composed into the inner cell together. Not part
    # of the bus: these shapes carry no electrical node -- they are the
    # hvi/nwell/npc markers that make the generators' thick-oxide geometry
    # PDK-legal (HV_FIXUP_NOTE).
    hv_fixup_report = build_hv_fixup_overlay(
        klt, out_dir, reports[BLOCKS[0]["id"]]["pdk"], reports, origins
    )
    overlays["hv_fixup"] = hv_fixup_report
    all_reports[hv_fixup_report["cell_name"]] = hv_fixup_report
    all_origins[hv_fixup_report["cell_name"]] = {"x": 0.0, "y": 0.0}

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
    # the curated deck happens to cover. See
    # layout/generator-notes.md#met2-escape-note and layout/bin/met2_drc.py.
    met2_drc = run_met2_drc(klt, Path(compose["gds_path"]), cell, out_dir)

    # --- 6c. HV DRC on the pinned PDK's own source deck (issue #620) --------
    # The curated deck above carries no hvi/npc/nwell rule, so it is silent
    # about the one thing thick-oxide geometry must satisfy. This runs the
    # PDK's source deck with FEOL enabled and gates on the HV rule group,
    # with the raw injector NMOS as the failing enclosure control. Gated:
    # a 5 V device that violates its own oxide rules is not a 5 V device.
    hv_drc = run_hv_drc(klt, compose["gds_path"], out_dir, pdk)

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

    # --- 7b. PDK-bound extraction + flavour gate (issue #620) ---------------
    # A second, separate extraction (`--pdk`), whose raw X cards name the
    # PDK wrapper each device bound -- the one place the oxide flavour is
    # observable. Every schematic MOS finger must bind to the 5 V wrapper
    # of its polarity; a single thin-oxide card among correct ones fails.
    # The curated extraction above stays the LVS input, unchanged.
    pdk_netlist_text, pdk_extract = run_pdk_bound_extract(
        klt, compose["gds_path"], cell, out_dir, cell
    )
    expected_fingers = expected_mos_fingers(args.reference.read_text())
    flavour = check_mos_flavour(pdk_netlist_text, expected_fingers)
    flavour["expected_source"] = str(args.reference)
    flavour["extract"] = {
        "device_count": pdk_extract.get("device_count"),
        "device_counts": pdk_extract.get("device_counts"),
    }
    (out_dir / "flavour.json").write_text(json.dumps(flavour, indent=2) + "\n")

    # --- 7c. Supply/tie ERC on this exact GDS (issue #620) ------------------
    # The two specs run-erc-supply-flow.sh invokes, with the well boxes
    # this GDS draws (the committed spec's boxes describe the pre-HVI
    # GDS). Gated with erc_supply_record's own item-11 gate, negative
    # control included.
    erc = run_supply_erc(
        klt, compose["gds_path"], out_dir, args.repo_root, reports, origins
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
        # does not have. See
        # layout/generator-notes.md#res-head-resistance-note, DR-003 and
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
    record = render_record(
        args=args,
        cell=cell,
        klt=klt,
        out_dir=out_dir,
        compose=compose,
        drc=drc,
        met2_drc=met2_drc,
        extract=extract,
        lvs=lvs,
        lvs_combined=lvs_combined,
        lvs_plain=lvs_plain,
        inner_compose=inner_compose,
        met1_routes=met1_routes,
        met1_conflicts=met1_conflicts,
        met1_components=met1_components,
        met1_split_routed=met1_split_routed,
        merged_pin_names=merged_pin_names,
        reports=reports,
        bus_summary=bus_summary,
        gds_digest=sha256_of(compose["gds_path"]),
        flavour=flavour,
        hv_drc=hv_drc,
        erc=erc,
    )
    print(record.text)

    # The flow's own gate: DRC must be clean, the ladder must be at full
    # scale *and* draw the leg length design/bandgap_core.sch specifies
    # (issue #91), every device class must extract, and pins must be
    # promoted.
    # LVS-clean is NOT gated here -- it is blocked upstream
    # (layout/generator-notes.md#mos-gate-note) and the record above states
    # so explicitly rather than silently passing.
    # The drawn-short check IS gated: a met1 rectangle of one node touching
    # another node's is a short, and a short that reads as connectivity is
    # exactly the false evidence this flow must never produce. So is the
    # label-collision check, which catches the same failure arriving through a
    # pad rather than through metal (see assert_no_merged_pin_names). So is
    # the split-node check, the inverse of the drawn-short one: a node this
    # router reports as fully routed whose metal is still in two pieces (see
    # split_routed_nets).
    # Issue #620 adds three gates: every MOS finger must bind its 5 V
    # wrapper (flavour), the HV rule group must be clean on the composed
    # GDS with a failing control (hv_drc), and the supply/tie ERC must
    # pass on this exact GDS (erc).
    gate = flow_gate(
        drc_clean=record.drc_clean,
        within_budget=record.within_budget,
        full_scale_ladder=record.full_scale_ladder,
        r2_leg_matches=record.r2_leg_matches,
        all_classes=record.all_classes,
        pin_count=record.pin_count,
        met1_conflicts=met1_conflicts,
        merged_pin_names=merged_pin_names,
        split_routed=met1_split_routed,
        met2_drc_clean=met2_drc.get("status") == "clean",
        mos_flavour_clean=flavour["clean"],
        hv_drc_clean=hv_drc["clean"],
        erc_supply_clean=erc["clean"],
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
