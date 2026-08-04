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

1. **The R2A/R2B ladder is drawn at its real 108-unit count** (54 segments
   per leg), not the skeleton's reduced 16. `klt gen res_array` gained a
   `rows` fold parameter (2AMLogic/klayout-tools#415, merged upstream via
   klayout-tools#418), so a 108-unit ladder folds into 9 rows and occupies
   ~1,231 um^2 instead of the ~710 um-long single row that forced the
   skeleton's reduction. The area-budget line in layout/matching-plan.md
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

What this script does NOT claim -- read record.md's own "What this record
does NOT claim" section for the authoritative, measured version:

- **Not LVS-clean.** Four disclosed causes remain, none of them a topology
  error in either netlist: the deck-synthesized substrate net
  (SUBSTRATE_NET_NOTE), array dummies that cannot be declared as dummies on
  sky130 (DUMMY_DEVICE_NOTE), the compensation cap MCC which is in the
  reference and deliberately not drawn, and the resistor head resistance the
  schematic's unit model carries but a drawn poly body does not.
- **Not fully inter-block routed.** record.md's "Schematic inter-block nets"
  table scores every schematic inter-block node as drawn / partial /
  labelled-only against SCHEMATIC_INTER_BLOCK_NETS below -- i.e. against
  design/bandgap_core.sch's node list, not against this script's own
  declaration -- and criterion 1 is PARTIAL while any node is short. What is
  left is congestion in this flow's own hand-written router, not a tool gap:
  every remaining node *can* be expressed now.
- **Array dummies remain unmatched devices.** Neither curated deck declares
  an `ExtractionDeck.dummy` marker layer and no generator draws one, so
  klayout-tools#462's merged fix (which taught the suppression path about
  resistors and bipolars) has nothing to key off on sky130. See
  DUMMY_DEVICE_NOTE below.

Every one of those gaps is filed upstream per CLAUDE.md's friction protocol
and named in the NOTE constants below; record.md restates them with the
measured numbers from the run that produced it.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import met1_bus  # noqa: E402  -- local module, resolved from this script's dir

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
    "`metal2`/`via1` roles with via-drop bussing, so the router *can* now "
    "plan wires on a second metal. This flow has not yet moved onto it: the "
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
    "not a drawn pad, though: the deck ties it to the same synthesized "
    "`vsubs` global it ties every NMOS body to, so it is reached by "
    "declaration, not by metal -- see SUBSTRATE_NET_NOTE."
)
#: The one place this flow's layout cannot answer the reference netlist with
#: drawn geometry, and the reason a `hints.same_nets` declaration is used
#: instead of more metal.
SUBSTRATE_NET_NOTE = (
    "sky130's curated extraction deck has no NMOS-body or resistor-bulk "
    "layer to derive from drawn geometry: `extract.py` registers an *empty* "
    "`nfet_body` region, wires it into every nfet's `W` terminal, every "
    "`bulk_to_substrate` resistor's `W` terminal and every bipolar's "
    "collector, and then `connect_global`s it to the deck's synthesized "
    "`vsubs` net. No drawn shape can ever join that net -- the deck says so "
    "itself, and `klt lvs` emits a `device.body_unverified` warning for "
    "exactly this. The schematic ties all of those terminals to `VSS`, and "
    "the layout does draw a real `VSS` (both NMOS groups' substrate "
    "guard-ring taps and both PNP base ties are wired to it). The two can "
    "only be reconciled by declaring the correspondence, which is what this "
    "flow's `hints.same_nets` entry does."
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
    "2AMLogic/klayout-tools#462 (merged via #471) extended `klt extract`'s "
    "dummy-device suppression from MOS gates to resistors and bipolars, "
    "which is the half of this gap that was in the extractor. The other "
    "half is still open on sky130: the suppression keys off "
    "`ExtractionDeck.dummy`, the sky130 curated deck declares no `dummy` "
    "layer at all, no `klt gen` generator draws one, and `klt extract` "
    "exposes no override -- so there is no layer for a layout to mark its "
    "dummies with. Every matched array's dummy edge units therefore still "
    "extract as ordinary devices with no schematic counterpart. Turning "
    "dummies off to make the LVS count move would trade a real matching "
    "property for a smaller number, which this flow refuses to do."
)
#: Why no resistor can be paired by `klt lvs` at all, whatever the routing
#: does -- found while isolating issue #72's 0/0 correspondence regression and
#: filed as 2AMLogic/klayout-tools#504.
RES_BULK_ARITY_NOTE = (
    "The sky130 deck marks `res_high_po` `bulk_to_substrate`, so `klt "
    "extract` writes a **three-node** R card "
    "(`R<name> <a> <b> <bulk> <value> <model>`), which KLayout's SPICE "
    "reader turns into `DeviceClassResistorWithBulk` (terminals A/B/W). "
    "`reference.spice` states the schematic, where a poly resistor is a "
    "two-node device, so the same reader turns its R cards into "
    "`DeviceClassResistor` (terminals A/B). Same model name on both sides, "
    "different terminal count -- `NetlistComparer` cannot pair them, and it "
    "says so only as generic `device.unmatched` entries, with no "
    "`device_class_mismatch` event and nothing in `device_classes[]` "
    "distinguishing the two. `klt lvs` offers no request-side hook to "
    "reconcile the arity (`hints.same_nets` reconciles a *net*, which is "
    "enough for MOS bodies because M cards carry four nodes on both sides). "
    "The only workaround available today is to add a bulk node to the "
    "reference's R cards, i.e. to stop the reference being a transcription "
    "of the schematic -- which this flow refuses to do for the same reason "
    "it refuses every other reference edit. Filed upstream as "
    "2AMLogic/klayout-tools#504."
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
N_R1 = 7
N_R2 = 54  # per leg; R2A + R2B = 108 unit segments total
N_R2_TRIM_CODES = 16  # downward-only range 0..-16, per leg (DR-002)
M_OUT = 2
M_AMPBIAS = 2
AMP_M_IN = 16
AMP_M_NMIRR = 4
AMP_M_PMIRR = 8

# ---------------------------------------------------------------------------
# Block definitions. Each maps to one `klt gen` call. `row` groups blocks into
# stacked bands; blocks within a row are placed left-to-right in the order
# listed. Relative to gen_bandgap_floorplan.py's BLOCKS this list differs in
# exactly three ways, each of them load-bearing for this issue:
#
#   * `res_r2` is at its real 108-unit count, folded into 9 rows.
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
            "num": 2 * N_R2,
            "dummy": 2,
            "rows": 9,
        },
        "bus": {"kind": "res_series", "legs": 2},
        "matched_group_label": "R2A/R2B interdigitated ladder (K = R2/R1 divider)",
        "real_target": f"n_r2={N_R2} unit segments PER LEG x 2 legs = "
        f"{2 * N_R2} total (design/bandgap_core.sch); drawn 1:1 -- the "
        "skeleton's 16-unit reduction is closed here by `res_array`'s `rows` "
        "fold parameter (2AMLogic/klayout-tools#415, merged via #418)",
    },
    {
        "id": "res_trim",
        "row": 0,
        "align": "top",
        "generator": "res_array",
        "params": {
            "length_um": 1.0,
            "width_um": R_W_UM,
            "spacing_um": 0.5,
            "flavor": RES_FLAVOR,
            "num": 2 * N_R2_TRIM_CODES,
            "dummy": 2,
            "rows": 4,
        },
        "bus": {"kind": "res_series", "legs": 2},
        "matched_group_label": "Downward-only trim ladder taps (both legs)",
        "real_target": f"n_r2_trim range 0..-{N_R2_TRIM_CODES} codes x 2 legs "
        f"= {2 * N_R2_TRIM_CODES} 1um unit taps (design/bandgap_core.sch "
        "CORE_PARAMS, DR-002); drawn 1:1",
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
]

#: The one declaration this flow makes to `klt lvs` rather than drawing.
#: sky130's curated extraction deck synthesizes the substrate net (see
#: SUBSTRATE_NET_NOTE) and no drawn shape can join it, so the layout side
#: carries `vsubs` where the schematic carries `VSS`. Declaring the
#: correspondence is honest -- the substrate *is* the schematic's ground in
#: this design -- and it is a `hints` entry rather than an edit to either
#: netlist, so both still state what they state.
SUBSTRATE_SAME_NETS: list[list[str]] = [["vsubs", "VSS"]]

MCC_AREA_UM2_NOTE = (
    "MCC (amp compensation cap, amp_m_cc=16 x W=30 x L=20 = 9600 um^2) is "
    "single-ended and not drawn here, exactly as in the #15 skeleton; see "
    "layout/matching-plan.md's area-budget section for why"
)


# ---------------------------------------------------------------------------
# klt drivers
# ---------------------------------------------------------------------------
def run_klt_json(klt: str, *args: str, allow_exit: tuple[int, ...] = (0,)) -> dict[str, Any]:
    """Run one `klt <args> --format json` and parse its stdout envelope.

    `allow_exit` lists the exit codes that still carry a full payload on
    stdout -- `klt drc`'s 3 ("ran clean but found violations") and
    `klt gen-compose`'s 3 ("partial success: unrouted_nets[] non-empty") both
    do, and both are results this flow records rather than crashes.
    """
    result = subprocess.run(
        [klt, *args, "--format", "json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode not in allow_exit:
        raise RuntimeError(
            f"klt {' '.join(args)} exited {result.returncode}:\n{result.stderr}"
        )
    return json.loads(result.stdout)


def klt_gen(klt: str, pdk: str, out_dir: Path, block: dict[str, Any]) -> dict[str, Any]:
    cell_name = block["id"]
    gds_path = out_dir / f"{cell_name}.gds"
    report = run_klt_json(
        klt,
        "gen",
        block["generator"],
        "--pdk",
        pdk,
        "--cell-name",
        cell_name,
        "--params",
        json.dumps(block["params"]),
        "-o",
        str(gds_path),
    )
    (out_dir / f"{cell_name}.gen.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


# ---------------------------------------------------------------------------
# Intra-block bussing (met1 over mcon -- see met1_bus.py and MET1_BUS_NOTE)
# ---------------------------------------------------------------------------
#: Vertical offset (um) between the two interdigitated legs' met1 lanes inside
#: a shared resistor array. A `res_array` terminal pad is `width_um` tall, so
#: +-RES_LANE_OFFSET_UM must stay inside +-width_um/2 while leaving the two
#: lanes more than the deck's 0.14 um `met1.space.1` apart (0.5 - 0.24 = 0.26).
RES_LANE_OFFSET_UM = 0.25
#: Clearance (um) between a `bjt_array`'s outermost unit row and the emitter /
#: base collection trunk drawn beyond it. Any value > 0 keeps the two trunks
#: outside every riser's span, which is what makes the bus crossing-free.
BJT_TRUNK_CLEARANCE_UM = 1.0
#: How far outside a block's own bbox (um) an inter-block route's escape stub
#: lands. Must clear the fold-turn lanes `bus_res_series` draws just outside a
#: folded array, and stay well inside the BLOCK_MARGIN_UM placement channel.
BLOCK_ESCAPE_UM = 4.0
#: How many rip-up-and-reorder passes the inter-block router gets before it
#: reports whatever it has. Each pass is a full redraw from scratch. Lower
#: than the 40 an earlier increment used: each pass now searches candidate
#: assignments and chain orders as well as paths, so a pass is much more
#: thorough and far fewer of them are worth paying for.
ROUTE_ORDER_PASSES = 14


def _ports_by_name(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p["name"]: p for p in report["ports"]}


def bus_res_series(
    bus: "met1_bus.Met1Bus",
    block_id: str,
    report: dict[str, Any],
    origin: dict[str, float],
    legs: int,
) -> list[dict[str, Any]]:
    """Chain a `res_array`'s unit segments into `legs` interdigitated series
    strings, one met1 lane per leg.

    Leg `l` owns unit indices `l, l + legs, l + 2*legs, ...` -- i.e. the two
    divider legs are interdigitated unit-by-unit across the array, which is
    the arrangement layout/matching-plan.md asks for and which the #15/#64
    layouts declared but never made electrically real (nothing joined the
    units at all). Each consecutive pair in a leg is joined `R<i>_B` ->
    `R<j>_A` on that leg's own lane, offset from the pads' centre line so the
    two legs' wires never share a track. Every coordinate comes from the
    generator's own reported `ports[]`.

    Returns one record per drawn link, for the evidence record.
    """
    ports = _ports_by_name(report)
    count = sum(1 for name in ports if name.endswith("_A"))
    bbox = {
        "x0": report["bbox_um"]["x0"] + origin["x"],
        "x1": report["bbox_um"]["x1"] + origin["x"],
    }
    links: list[dict[str, Any]] = []
    for leg in range(legs):
        indices = list(range(leg, count, legs))
        lane = (leg - (legs - 1) / 2.0) * (2 * RES_LANE_OFFSET_UM)
        for src, dst in zip(indices, indices[1:]):
            # Each series link is its own electrical node (the two unit
            # resistors it joins are in series, not shorted), so it is tagged
            # separately for the drawn-short check.
            bus.net(f"{block_id}:leg{leg}:{src}-{dst}")
            a = ports[f"R{src}_B"]
            b = ports[f"R{dst}_A"]
            ax = float(a["x_um"]) + origin["x"]
            ay = float(a["y_um"]) + origin["y"] + lane
            bx = float(b["x_um"]) + origin["x"]
            by = float(b["y_um"]) + origin["y"] + lane
            net_id = f"{block_id}:leg{leg}:{src}-{dst}"
            bus.net(net_id)
            bus.via(ax, ay)
            bus.via(bx, by)
            # Routed, not hardcoded: a same-row link is one straight segment
            # on the leg's own lane, but a fold turn puts both legs' links in
            # the same corner, so the router has to be free to pick a
            # different jog lane for the second one.
            hop = None
            if abs(ay - by) > 1e-6:
                # A boustrophedon fold turn: both legs' links land in the same
                # corner of the array, and the row band between them is full
                # of the other leg's lane wires. Take the turn *outside* the
                # array instead, on a per-leg vertical lane in the placement
                # channel the floorplan already leaves there.
                side = 1.0 if (ax + bx) / 2.0 > (bbox["x0"] + bbox["x1"]) / 2.0 else -1.0
                for step in (1.0, 1.8, 2.6):
                    turn_x = (
                        (bbox["x1"] if side > 0 else bbox["x0"])
                        + side * (step + leg * 0.6)
                    )
                    hop = _connect_path(
                        bus,
                        net_id,
                        [(ax, ay), (turn_x, ay), (turn_x, by), (bx, by)],
                    )
                    if hop:
                        break
            if hop is None:
                hop = _connect(bus, net_id, (ax, ay), (bx, by))
            links.append(
                {
                    "leg": leg,
                    "from": f"R{src}_B",
                    "to": f"R{dst}_A",
                    "routed": hop is not None,
                }
            )
    return links


def bus_bjt_parallel(
    bus: "met1_bus.Met1Bus",
    nets: dict[str, str],
    report: dict[str, Any],
    origin: dict[str, float],
) -> list[dict[str, Any]]:
    """Tie a `bjt_array`'s unit emitters into one node and its unit base ties
    into another.

    `bjt_array` reports every unit's emitter pad on one set of x columns and
    every unit's base tie on a second, interleaved set, with the units stacked
    in rows. So each column gets a riser joining its own pads, the emitter
    risers collect on a trunk drawn *above* the top row and the base risers on
    a trunk *below* the bottom row. Because every emitter riser stops below
    the base trunk and every base riser stops above the emitter trunk, no two
    wires of the two nets ever cross -- the bus needs no jogs and no second
    via level.

    Returns one record per net, for the evidence record.
    """
    ports = _ports_by_name(report)

    def collect(suffix: str) -> dict[float, list[float]]:
        columns: dict[float, list[float]] = {}
        for name, port in ports.items():
            if not name.startswith("Q") or not name.endswith(suffix):
                continue
            columns.setdefault(
                round(float(port["x_um"]) + origin["x"], 4), []
            ).append(float(port["y_um"]) + origin["y"])
        return columns

    records: list[dict[str, Any]] = []
    emitters = collect("_E")
    bases = collect("_B")
    all_ys = [y for ys in emitters.values() for y in ys] + [
        y for ys in bases.values() for y in ys
    ]
    top_trunk = max(all_ys) + BJT_TRUNK_CLEARANCE_UM
    bottom_trunk = min(all_ys) - BJT_TRUNK_CLEARANCE_UM

    for suffix, columns, trunk_y in (
        ("_E", emitters, top_trunk),
        ("_B", bases, bottom_trunk),
    ):
        if not columns:
            continue
        bus.net(nets[suffix])
        for x, ys in sorted(columns.items()):
            for y in ys:
                bus.via(x, y)
            bus.vseg(x, min(ys + [trunk_y]), max(ys + [trunk_y]))
        xs = sorted(columns)
        bus.hseg(min(xs), max(xs), trunk_y)
        records.append(
            {
                "terminal": suffix.lstrip("_"),
                "net": nets[suffix],
                "columns": len(columns),
                "pads": sum(len(v) for v in columns.values()),
                "trunk_y_um": round(trunk_y, 3),
                "trunk_x0_um": round(min(xs), 3),
                "trunk_x1_um": round(max(xs), 3),
            }
        )
    return records


#: Which `diff_pair` port family is which schematic transistor, and how that
#: generator's S/D naming maps onto the schematic's. Both halves of a pair are
#: geometrically interchangeable, so this binding is a *declaration* -- but it
#: has to be made once and obeyed everywhere, or two nodes end up on one
#: transistor (MOS_HALF_NOTE).
#:
#: `drain_suffix` records the second half of the mapping. `klt gen`'s
#: `diff_pair` reports `_S` on the west edge and `_D` on the east edge of each
#: finger; a MOSFET's source and drain are physically the same construction,
#: so which one the schematic calls the drain is again this flow's choice.
#: The pfet blocks sit above their loads and the nfet blocks below theirs, so
#: taking the pfet drain on the east pad and the nfet drain on the west pad is
#: what makes each inter-block hop a short one. Every net below states the
#: schematic terminal it wants; these two tables turn that into a port name.
MOS_HALVES: dict[str, dict[str, Any]] = {
    "core_mirror": {
        "drain_suffix": "_D", "drain_facing": DIRECTION_EAST,
        "source_suffix": "_S", "source_facing": DIRECTION_WEST,
        "devices": {"MPOUT": "M1", "MPAMP": "M2"},
    },
    "amp_input_pair": {
        "drain_suffix": "_D", "drain_facing": DIRECTION_EAST,
        "source_suffix": "_S", "source_facing": DIRECTION_WEST,
        "devices": {"MP1": "Q2", "MP2": "Q1"},
    },
    "amp_nload": {
        "drain_suffix": "_S", "drain_facing": DIRECTION_WEST,
        "source_suffix": "_D", "source_facing": DIRECTION_EAST,
        "devices": {"MN1": "M1", "MN2": "M2"},
    },
    "amp_pmirr": {
        "drain_suffix": "_D", "drain_facing": DIRECTION_EAST,
        "source_suffix": "_S", "source_facing": DIRECTION_WEST,
        "devices": {"MP3": "M1", "MP4": "M2"},
    },
    "amp_nmirr": {
        "drain_suffix": "_S", "drain_facing": DIRECTION_WEST,
        "source_suffix": "_D", "source_facing": DIRECTION_EAST,
        "devices": {"MN4": "M1", "MN3": "M2"},
    },
}


# ---------------------------------------------------------------------------
# MOS finger bussing (the payoff of 2AMLogic/klayout-tools#461 / #474)
# ---------------------------------------------------------------------------
#: Clearance (um) between a MOS block's own bbox and the innermost of the
#: vertical spines `bus_mos_comb` runs beside it.
MOS_SPINE_CLEARANCE_UM = 0.6
#: Centre-to-centre pitch (um) between adjacent spines. A met1 wire is
#: `met1_bus.WIRE_WIDTH_UM` (0.24) wide and the deck's `met1.space.1` is 0.14,
#: so 0.4 is the tightest legal pitch.
MOS_SPINE_PITCH_UM = 0.4
#: Distances (um) past the block edge a comb's escape stub is tried at, nearest
#: first. Several, because two neighbouring blocks' escape stubs share the
#: placement channel between them and can land on the same track.
#:
#: Deliberately **short**. A block's escape stubs fan out at every one of its
#: lane heights, so together they are a wall across the channel for anything
#: trying to pass vertically. At 4 um into a 12 um channel, two facing blocks'
#: fans met in the middle and sealed it -- which is what left `GDRV` and the
#: `D1`/`D2` pair unroutable with every ordering the search tried. Keeping the
#: fans hugging their own block leaves the middle of each placement channel
#: open, which is what those channels are for.
MOS_ESCAPE_UM = (1.2, 1.6, 2.0, 0.8, 2.4)

MOS_COMB_NOTE = (
    "Every split MOS group's fingers are bussed into the one m=N device the "
    "schematic states, on met1, with the trunk of each node running *inside* "
    "the device row rather than around it. That is deliberate and is what "
    "makes the bus crossing-free on a single routing metal: a source/drain "
    "pad is a full-height li1 strip, so a trunk may drop its via anywhere "
    "along the pad's height, and a gate reaches the same track through the "
    "li1 riser met1_bus.gate_contact draws down its own column gap. With "
    "every node's via on its own horizontal track, no node ever needs a stub "
    "that would cross another node's trunk. Each node then leaves the block "
    "on its own vertical spine, and the spines are ordered so that the "
    "further out a spine sits, the further from the row's edge its trunk is "
    "-- which is what keeps a trunk from crossing an outer spine on its way "
    "past."
)


def _mos_rows(
    report: dict[str, Any], origin: dict[str, float]
) -> list[tuple[float, float]]:
    """The `diff_pair`'s device rows, bottom-first, as (y0, y1) diffusion
    bands in composed-cell coordinates.

    Derived from the generator's own reported source/drain ports -- each is
    reported at its pad's centre with `width_um` equal to the device width,
    i.e. the pad's full height -- never from a re-read of the block's GDS or
    from re-deriving the generator's placement arithmetic here.
    """
    bands: dict[float, tuple[float, float]] = {}
    for port in report["ports"]:
        layer = port.get("layer") or {}
        if [layer.get("layer"), layer.get("datatype")] != met1_bus.LI1_LAYER:
            continue
        # `TAP_S` is a guard-ring tap, not a device pad, and would otherwise
        # look like a third (zero-height) device row.
        if not re.fullmatch(r"[MQ]\d+_\d+_[SD]", port["name"]):
            continue
        centre = float(port["y_um"]) + origin["y"]
        half = float(port["width_um"]) / 2.0
        bands[round(centre, 4)] = (centre - half, centre + half)
    return [bands[key] for key in sorted(bands)]


def _band_index(bands: list[tuple[float, float]], y: float) -> int:
    """Which device row a port at `y` belongs to.

    A source/drain port sits at its band's centre; a gate port sits on the
    landing pad just above its band's top edge, and below the next band's
    bottom edge -- so "the last band whose bottom edge is at or below y" is
    the right rule for both, and needs no per-port-kind special case.
    """
    index = 0
    for i, (y0, _) in enumerate(bands):
        if y >= y0 - 1e-6:
            index = i
    return index


def mos_group_pads(
    block_id: str,
    report: dict[str, Any],
    origin: dict[str, float],
    device: str,
    terminal: str,
) -> list[tuple[str, float, float, bool]]:
    """Every finger pad of one schematic device's one terminal, as
    `(port_name, x, y, is_gate)` in composed-cell coordinates.

    Unlike the previous increment's centroid-nearest single-pad pick, this
    returns *all* of them: bussing every finger of a split group into one
    node is what lets `klt lvs`'s `combine_devices` collapse them into the
    `m=N` device the schematic states. The half binding still goes through
    MOS_HALVES, so a node can only land on the transistor the schematic
    names (MOS_HALF_NOTE).
    """
    entry = MOS_HALVES[block_id]
    half = entry["devices"][device]
    if terminal == "gate":
        suffix = "_G"
        want_layer = [66, 20]  # poly.drawing -- where a gate port is reported
    elif terminal in ("drain", "source"):
        suffix = entry[f"{terminal}_suffix"]
        want_layer = met1_bus.LI1_LAYER
    else:
        raise ValueError(
            f"{block_id}.{device}: unknown terminal {terminal!r} "
            "(want 'drain', 'source' or 'gate')"
        )
    pads: list[tuple[str, float, float, bool]] = []
    for port in report["ports"]:
        name = port["name"]
        if not name.startswith(f"{half}_") or not name.endswith(suffix):
            continue
        layer = port.get("layer") or {}
        if [layer.get("layer"), layer.get("datatype")] != want_layer:
            continue
        pads.append(
            (
                name,
                float(port["x_um"]) + origin["x"],
                float(port["y_um"]) + origin["y"],
                terminal == "gate",
            )
        )
    if not pads:
        raise KeyError(
            f"{block_id}.{device}: no '{suffix}' ports on half {half}"
        )
    return pads


def bus_mos_comb(
    bus: "met1_bus.Met1Bus",
    block_id: str,
    report: dict[str, Any],
    origin: dict[str, float],
    spine_side: str,
    groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Bus every finger of every schematic device in one MOS block, one comb
    per electrical node, and return each node's off-block escape points.

    See MOS_COMB_NOTE for why the trunks run inside the device rows. The rest
    of the structure exists to make the whole comb set **planar on one metal
    layer**, which is the only way it can be drawn at all without a second
    routing metal the extraction deck would model:

    * a node's lane index is its position in `groups`;
    * in the **bottom** row lanes descend with that index and in the **top**
      row they ascend, so node `k`'s row-to-row span is strictly inside node
      `k+1`'s;
    * every spine sits on `spine_side`, ordered outward by the same index, so
      an outer node's trunk always passes an inner node's spine strictly
      above or below that spine -- never through it;
    * every escape leaves on the **opposite** side, as a straight
      continuation of the node's own trunk. That side carries no spines at
      all, so the escapes are parallel horizontal lines at distinct y and
      cannot cross each other either.

    The last point is what a first cut of this function got wrong: with the
    connection point taken on the spine itself, an inner node was walled in
    by every outer node's spine and six of the twelve schematic nets could
    not be routed out of their own block. Mixing spine sides within one block
    does not fix it -- the nesting order that keeps a west escape clear is
    exactly the one that blocks an east escape -- so the side is a per-block
    choice, made where the block's neighbours are.

    The drawn-short check in `met1_bus.Met1Bus.conflicts` is the proof of all
    of the above, not this docstring.
    """
    bands = _mos_rows(report, origin)
    if len(bands) != 2:
        raise ValueError(
            f"block '{block_id}': bus_mos_comb needs exactly two device rows "
            f"(the lane nesting above assumes it); found {len(bands)}"
        )
    if spine_side not in ("W", "E"):
        raise ValueError(f"block '{block_id}': spine_side must be 'W' or 'E'")
    bbox = report["bbox_um"]
    west = bbox["x0"] + origin["x"]
    east = bbox["x1"] + origin["x"]
    lanes = len(groups)
    #: Escape side: the block edge the trunks continue past, and the sign of
    #: "outward" there.
    edge_x = east if spine_side == "W" else west
    outward = 1.0 if spine_side == "W" else -1.0

    records: list[dict[str, Any]] = []
    for index, spec in enumerate(groups):
        net = spec["net"]
        offset = MOS_SPINE_CLEARANCE_UM + index * MOS_SPINE_PITCH_UM
        spine_x = west - offset if spine_side == "W" else east + offset

        pads: list[tuple[str, float, float, bool]] = []
        for device, terminal in spec["terminals"]:
            pads.extend(
                mos_group_pads(block_id, report, origin, device, terminal)
            )

        bus.net(net)
        lane_ys: list[float] = []
        escapes: list[tuple[str, float, float]] = []
        gates = 0
        for band_index, (y0, y1) in enumerate(bands):
            in_band = [p for p in pads if _band_index(bands, p[2]) == band_index]
            if not in_band:
                continue
            step = (y1 - y0) / (lanes + 1)
            lane_y = (
                y1 - (index + 1) * step
                if band_index == 0
                else y0 + (index + 1) * step
            )
            lane_ys.append(lane_y)
            xs = [spine_x, edge_x]
            for _name, px, py, is_gate in in_band:
                if is_gate:
                    bus.gate_contact(px, py, lane_y)
                    gates += 1
                bus.via(px, lane_y)
                xs.append(px)
            bus.hseg(min(xs), max(xs), lane_y)
            # The escape stub is the only part of a comb that leaves the
            # block's own footprint on the escape side, so it is the only part
            # that can meet a *neighbouring* block's comb. Drawn guarded, and
            # tried at a few lengths: a stub that cannot be placed at all
            # leaves the terminal at the block edge rather than failing the
            # whole comb.
            # The outermost node -- and only it -- can also escape on the
            # spine side: nothing of this block's is drawn beyond its own
            # spine, so extending its trunk past it crosses nothing. Every
            # inner node is walled in by the outer spines, which is why the
            # `groups` order is load-bearing: put the node whose partner
            # blocks lie on the spine side last.
            sides = [(edge_x, outward, "far")]
            if index == lanes - 1:
                sides.append((spine_x, -outward, "spine"))
            for from_x, direction, tag in sides:
                reach = from_x
                for distance in MOS_ESCAPE_UM:
                    target = from_x + direction * distance
                    if _draw_guarded(
                        bus, net, [(from_x, lane_y), (target, lane_y)]
                    ):
                        reach = target
                        break
                escapes.append(
                    (f"{block_id}:{net}:{tag}{band_index}", reach, lane_y)
                )
        if not lane_ys:  # pragma: no cover -- every device has pads in both rows
            raise ValueError(f"block '{block_id}' net {net}: no pads found")
        if len(lane_ys) > 1:
            bus.vseg(spine_x, min(lane_ys), max(lane_ys))
        records.append(
            {
                "net": net,
                "spine_side": spine_side,
                "terminals": [f"{d}.{t}" for d, t in spec["terminals"]],
                "pads": len(pads),
                "gate_contacts": gates,
                "spine_x_um": round(spine_x, 3),
                "escapes": [
                    [name, round(x, 3), round(y, 3)] for name, x, y in escapes
                ],
            }
        )
    return records


#: A `diff_pair`'s guard ring carries the block's bulk tie -- an n-well tap on
#: a pfet group (klayout-tools#421's fix gates the well tie on
#: `flavor == "pfet"`) and a p-substrate tap on an nfet group -- and reports it
#: as `TAP_N`/`TAP_S`/`TAP_E` on li1. The reference netlist puts every MOS
#: bulk terminal on a supply (`... VDD VDD pfet` / `... VSS VSS nfet`), so
#: leaving these unconnected is not a neutral omission: it leaves each group's
#: bulk as an anonymous floating net in the extracted netlist. They are
#: contactable ordinary li1 pads -- nothing about MOS_GATE_NOTE applies -- and
#: are drawn from this increment on.
#:
#: All three taps are offered as *candidates*, not just `TAP_S`. Pinning every
#: block to its south tap was the previous increment's choice ("it faces the
#: free band below each row"), and it is what left `VDD` two hops short: from
#: `core_mirror.TAP_S`, at the bottom edge of a 8 x 19 um block, the only ways
#: out cross that block's own comb escape stubs, and from `amp_pmirr.TAP_S` the
#: south tap of `amp_input_pair` is on the far side of the whole input pair.
#: Both blocks have taps that are *not* boxed in -- their north taps face the
#: free band the amp PMOS mirror already routes along, and `core_mirror.TAP_E`
#: sits 1.6 um clear of that block's own VDD comb escape row -- so which tap
#: to take is a routing choice like any other and belongs to the candidate
#: search, not to this table. The search takes `TAP_N` on both, and `VDD`
#: routes end to end; every PMOS bulk then extracts onto `VDD` instead of onto
#: an anonymous floating net, which is what `klt lvs` needs before it can seed
#: any correspondence at all (issue #72). Cost: `bulk` terminals lose their
#: fixed position and join the `_candidate_assignments` enumeration.
BULK_TAP_PORTS = ("TAP_S", "TAP_N", "TAP_E")


def bulk_terminal(block: str) -> dict[str, Any]:
    """The guard-ring bulk tap of one MOS group, as a supply-net terminal.

    No escape stub: unlike a resistor row-end, a ring tap already sits on the
    block's outer edge facing open floorplan, so the general router can leave
    from the pad itself.
    """
    return {"block": block, "ports": list(BULK_TAP_PORTS), "escape": False}


def mos_comb(block: str, net: str) -> dict[str, Any]:
    """One INTER_BLOCK_MET1 terminal naming the off-block connection point of
    a MOS block's already-drawn comb for `net` (see :func:`bus_mos_comb`).

    A MOS terminal is no longer a single pad. Every finger of the schematic
    device is bussed inside its own block, so what the inter-block router has
    to reach is that comb's spine -- one point per node per block, already on
    met1, with no via and no pad claim of its own.
    """
    return {"block": block, "comb": (block, net)}


#: The bandgap core's inter-block nodes that this flow draws on met1.
#:
#: This is now the *complete* node list of design/bandgap_core.sch (with
#: design/error_amp.sch expanded): with MOS gates contactable (MOS_GATE_NOTE)
#: every schematic node is expressible, so nothing is omitted here and scored
#: as "labelled only" in the coverage table below.
#:
#: Every terminal is one of three things: a `comb` point, i.e. the spine of a
#: MOS block's already-drawn finger bus (:func:`bus_mos_comb`); the met1 trunk
#: an intra-block bus already drew for the same node (`trunk`, the PNP
#: arrays); or a named li1 pad on a resistor block, contacted through an mcon.
#: Ordered most-constrained-first. A net that has to cross a 100 um array to
#: reach its other end has exactly one free band to do it in; a short hop
#: between neighbouring blocks has many. Routing the long ones first is what
#: keeps a later short hop from walling off the only corridor an earlier one
#: needed -- the ordering is load-bearing, not cosmetic (and the order search
#: in :func:`build_bus_overlay` rotates it anyway).
INTER_BLOCK_MET1: list[dict[str, Any]] = [
    {
        "net": "VA",
        "terminals": [
            {"block": "res_trim", "port": f"R{2 * N_R2_TRIM_CODES - 2}_B", "leg": 0},
            {"trunk": ("pnp_ctat", "VA")},
            mos_comb("amp_input_pair", "VA"),
        ],
        "schematic": "the R2A leg's low end (through its trim taps) to Q1's "
        "emitter bus and MP2's gate -- the amp's VINN node",
    },
    {
        "net": "TRIM_A",
        "terminals": [
            {"block": "res_r2", "port": f"R{2 * N_R2 - 2}_B", "leg": 0},
            {"block": "res_trim", "port": "R0_A", "leg": 0},
        ],
        "schematic": "R2A's low end into leg A of the downward-only trim "
        "ladder (DR-002)",
    },
    {
        "net": "VOUT",
        "terminals": [
            mos_comb("core_mirror", "VOUT"),
            {"block": "res_r2", "port": "R0_A", "leg": 0},
            {"block": "res_r2", "port": "R1_A", "leg": 1},
        ],
        "schematic": "MPOUT's drain and the high ends of both divider legs "
        "-- the reference output",
    },
    {
        "net": "TRIM_B",
        "terminals": [
            {"block": "res_r2", "port": f"R{2 * N_R2 - 1}_B", "leg": 1},
            {"block": "res_trim", "port": "R1_A", "leg": 1},
        ],
        "schematic": "R2B's low end into leg B of the trim ladder",
    },
    {
        "net": "VB",
        "terminals": [
            {"block": "res_trim", "port": f"R{2 * N_R2_TRIM_CODES - 1}_B", "leg": 1},
            {"block": "res_r1", "port": "R0_A"},
            mos_comb("amp_input_pair", "VB"),
        ],
        "schematic": "the R2B leg's low end (through its trim taps) to R1's "
        "head and MP1's gate -- the amp's VINP node",
    },
    {
        "net": "VBQ",
        "terminals": [
            {"block": "res_r1", "port": f"R{N_R1 - 1}_B"},
            {"trunk": ("pnp_ptat", "VBQ")},
        ],
        "schematic": "R1's tail to Q2's emitter bus",
    },
    {
        "net": "VDD",
        "terminals": [
            mos_comb("core_mirror", "VDD"),
            mos_comb("amp_pmirr", "VDD"),
            bulk_terminal("core_mirror"),
            bulk_terminal("amp_input_pair"),
            bulk_terminal("amp_pmirr"),
        ],
        "schematic": "VDD trunk: MPOUT/MPAMP and MP3/MP4 sources -- every "
        "finger of all four, not one pad per block -- plus each PMOS group's "
        "n-well guard-ring tap (the reference's pfet bulk terminal)",
    },
    {
        "net": "VSS",
        "terminals": [
            mos_comb("amp_nload", "VSS"),
            mos_comb("amp_nmirr", "VSS"),
            bulk_terminal("amp_nload"),
            bulk_terminal("amp_nmirr"),
            {"trunk": ("pnp_ctat", "VSS")},
            {"trunk": ("pnp_ptat", "VSS")},
        ],
        "schematic": "VSS trunk: every finger of all four amp NMOS sources "
        "(MN1-MN4), both NMOS groups' substrate guard-ring taps, and both "
        "PNP base ties (the diode-connected PNPs' base sits on VSS)",
    },
    {
        "net": "TAIL",
        "terminals": [
            mos_comb("core_mirror", "TAIL"),
            mos_comb("amp_input_pair", "TAIL"),
        ],
        "schematic": "MPAMP drain to the amp input pair's common source",
    },
    {
        "net": "GDRV",
        "terminals": [
            mos_comb("amp_pmirr", "GDRV"),
            mos_comb("amp_nmirr", "GDRV"),
            mos_comb("core_mirror", "GDRV"),
        ],
        "schematic": "the amp's output -- MP4's and MN3's drains -- and the "
        "core mirror's gate drive, one node in the schematic and now one "
        "drawn node in the layout",
    },
    {
        "net": "D1",
        "terminals": [
            mos_comb("amp_input_pair", "D1"),
            mos_comb("amp_nload", "D1"),
            mos_comb("amp_nmirr", "D1"),
        ],
        "schematic": "MP1's drain, MN1's diode-connected drain/gate, and "
        "MN3's gate",
    },
    {
        "net": "D2",
        "terminals": [
            mos_comb("amp_input_pair", "D2"),
            mos_comb("amp_nload", "D2"),
            mos_comb("amp_nmirr", "D2"),
        ],
        "schematic": "MP2's drain, MN2's diode-connected drain/gate, and "
        "MN4's gate",
    },
    {
        "net": "PN",
        "terminals": [
            mos_comb("amp_pmirr", "PN"),
            mos_comb("amp_nmirr", "PN"),
        ],
        "schematic": "MN4's drain, MP3's diode-connected drain/gate, and "
        "MP4's gate",
    },
]

#: How many parallel tracks :func:`free_channels` offers per placement channel,
#: and their pitch (um). One track per channel is what the previous increment
#: had, and it meant a channel could carry exactly one node.
CHANNEL_TRACKS = 4
CHANNEL_TRACK_PITCH_UM = 1.2
#: How far (um) the first track sits from the block edge it is derived from.
#: Must clear that block's own comb escape stubs (MOS_ESCAPE_UM), or the
#: nearest track lands exactly on the stub ends and every path through it is
#: rejected -- which is precisely what a first cut did, with the track offset
#: and the stub length both 1.2 um.
CHANNEL_TRACK_OFFSET_UM = 3.0
#: How many tracks near each endpoint :func:`_channel_paths` draws from. Every
#: block edge contributes tracks, so the full set is ~90 per axis and using all
#: of it would mean tens of thousands of candidate paths per hop; a route's
#: useful turn is near one of its own ends.
#:
#: A first cut instead kept a global "best 26" ordered by how many block bboxes
#: each track crosses. That silently threw away every usable track: the only
#: tracks crossing *no* block on this floorplan are the ones outside the whole
#: cell, so the 26 survivors were all at x < 0 or x > 300 and the placement
#: channels between neighbours -- the entire point of the exercise -- never
#: appeared in a candidate path.
CHANNEL_NEAR_TRACKS = 8
#: How many tracks near each endpoint the double-dogleg path family draws from.
#: Squared into the candidate count, so smaller still.
CHANNEL_DOGLEG_TRACKS = 5

#: Detour lanes (um, relative to the straight elbow) the router below tries
#: when a direct elbow would collide with an already-drawn net. Small, ordered
#: outward: the first that clears wins, so a route only detours as far as it
#: must.
DETOUR_OFFSETS_UM = [0.0] + [
    sign * 0.4 * step for step in range(1, 121) for sign in (1.0, -1.0)
]


def _li1_ports(
    report: dict[str, Any],
    origin: dict[str, float],
    suffix: str,
    facing: int,
    half: str | None = None,
) -> list[tuple[str, float, float]]:
    """Every li1 port of one family on a block, in composed-cell coordinates.

    Poly ports are filtered out here rather than at the call site: a gate port
    is reported on `poly` (66/20), and there is no contactable poly landing
    area outside the channel to place a via on (MOS_GATE_NOTE), so a gate can
    never be a met1 terminal.

    `half` restricts the result to one of a `diff_pair`'s two devices (`"M1"` /
    `"M2"`, the generator's own port-name prefix). Without it the caller gets
    both, and the centroid-nearest pick below can hand a node a finger of the
    *wrong* transistor -- geometrically plausible, electrically a different
    device than the schematic names. See MOS_HALF_NOTE.
    """
    out: list[tuple[str, float, float]] = []
    for port in report["ports"]:
        layer = port.get("layer") or {}
        if [layer.get("layer"), layer.get("datatype")] != met1_bus.LI1_LAYER:
            continue
        if not port["name"].endswith(suffix):
            continue
        if half is not None and not port["name"].startswith(f"{half}_"):
            continue
        if int(port.get("direction_deg", 0)) % 360 != facing:
            continue
        out.append(
            (
                port["name"],
                float(port["x_um"]) + origin["x"],
                float(port["y_um"]) + origin["y"],
            )
        )
    return out


#: The node that vetoed the most recent rolled-back path, so a hop that never
#: routes can say *what* stopped it instead of only that it failed.
_LAST_BLOCKER: list[str] = []

#: How many times each net vetoed a candidate path during the *current*
#: :func:`_connect` call (reset there, tallied by :func:`_draw_guarded`).
#: `_LAST_BLOCKER` alone is order-dependent -- it is whichever candidate
#: happened to be tried last, not the net actually responsible for most of
#: the congestion -- which made a hop's own "blocked_by" attribution
#: misleading on a floorplan where *several* nets contest the same corridor
#: (issue #62's `matching-plan.md` Section 7g: the three still-unrouted
#: schematic hops are each rejected by 3 to 20 distinct already-drawn nets --
#: including, for `VSS`, thirteen segments of the resistor ladder's own
#: intra-block bus -- not by the single net their old `blocked_by` value
#: named, which in two of the three cases is not even the largest
#: contributor). `_connect`'s caller surfaces this as
#: `blocked_by_counts` on a failed hop, ordered most-frequent first, so a
#: future increment reading the record does not have to re-run a standalone
#: diagnostic to see that.
_BLOCKER_COUNTS: "Counter[str]" = Counter()


def _draw_guarded(
    bus: "met1_bus.Met1Bus", net: str, points: list[tuple[float, float]]
) -> bool:
    """Draw an orthogonal met1 polyline, rolling it back if it would collide.

    Returns True when the path was kept. "Collide" means any new rectangle
    coming within the deck's `met1.space.1` clearance of an already-drawn
    rectangle belonging to a *different* electrical node -- i.e. a drawn short
    or a spacing violation. Rolling back rather than drawing-and-reporting is
    what lets the caller try the next detour lane.
    """
    shape_mark = len(bus.shapes)
    rect_mark = len(bus.met1_rects)
    bus.net(net)
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 != x1 and y0 != y1:
            raise ValueError("path segments must be orthogonal")
        if x0 == x1:
            bus.vseg(x0, y0, y1)
        else:
            bus.hseg(x0, x1, y0)
    eps = 0.14 - 1e-9
    for _, ax0, ay0, ax1, ay1 in bus.met1_rects[rect_mark:]:
        for net_b, bx0, by0, bx1, by1 in bus.met1_near(ax0, ay0, ax1, ay1, eps):
            if net_b == net:
                # Same node: touching or overlapping is the normal case (every
                # elbow shares a corner with its own next segment, every via
                # pad sits under its own wire). *Near but not touching* is
                # different -- it is a notch, and `met1.space.1` applies to two
                # edges of one net exactly as it does to two nets. This is what
                # a first cut of the multi-track channel search shipped: DRC
                # caught one 0.12 um same-net gap that this check, looking only
                # at other nodes, had waved through.
                if ax0 <= bx1 and bx0 <= ax1 and ay0 <= by1 and by0 <= ay1:
                    continue
            del bus.shapes[shape_mark:]
            bus.truncate_met1(rect_mark)
            _LAST_BLOCKER.clear()
            _LAST_BLOCKER.append(net_b)
            _BLOCKER_COUNTS[net_b] += 1
            return False
    return True


def _connect_path(
    bus: "met1_bus.Met1Bus", net: str, points: list[tuple[float, float]]
) -> dict[str, Any] | None:
    """Try one explicit orthogonal path; return its record, or None if it
    would collide with another node."""
    if not _draw_guarded(bus, net, points):
        return None
    return {"points": [[round(x, 3), round(y, 3)] for x, y in points]}


def free_channels(
    reports: dict[str, dict[str, Any]],
    origins: dict[str, dict[str, float]],
) -> dict[str, list[float]]:
    """Candidate vertical and horizontal tracks the open-channel router may
    cross the floorplan on.

    met1 sits above every block's li1, so a *block* is not an obstacle to this
    router -- only another node's already-drawn met1 is. The placement gaps are
    still the right lanes to prefer, because that is where the previously-drawn
    nets are sparsest: BLOCK_MARGIN_UM/ROW_MARGIN_UM exist precisely to leave
    them empty.

    Derived **per block edge**, not from the union of every block's span. The
    union is what a first cut used, and on this floorplan it is nearly useless:
    the row-1 and row-2 blocks overlap in x with the row-0 blocks, so merging
    every span collapses ten blocks into two x intervals and leaves exactly two
    usable vertical tracks -- both outside the whole cell. The 12 um channels
    the placement deliberately leaves *between* neighbours in a row disappear
    from the candidate set entirely, and six schematic nets were reported
    unroutable as a direct result. Each block edge contributes its own tracks
    here, so those channels are back.

    Duplicates are dropped and the result is ordered by how many blocks a track
    passes over, fewest first, so a hop tries the genuinely free lanes before
    the ones that only look free.
    """
    spans: dict[str, list[tuple[float, float]]] = {"x": [], "y": []}
    for bid, report in reports.items():
        bbox = report["bbox_um"]
        if bbox["x1"] - bbox["x0"] <= 0 or bbox["y1"] - bbox["y0"] <= 0:
            continue  # the zero-area bus overlay is not a block
        spans["x"].append((bbox["x0"] + origins[bid]["x"], bbox["x1"] + origins[bid]["x"]))
        spans["y"].append((bbox["y0"] + origins[bid]["y"], bbox["y1"] + origins[bid]["y"]))

    lanes: dict[str, list[float]] = {}
    for axis, intervals in spans.items():
        candidates: list[float] = []
        for lo, hi in intervals:
            for step in range(CHANNEL_TRACKS):
                out = CHANNEL_TRACK_OFFSET_UM + step * CHANNEL_TRACK_PITCH_UM
                candidates.append(round(lo - out, 3))
                candidates.append(round(hi + out, 3))
        # The margins outside the content are lanes too, and are the only way
        # out for a terminal boxed in at a corner of the floorplan.
        margin = RING_MARGIN_UM / 2.0
        outer_lo = min(lo for lo, _ in intervals) - margin
        outer_hi = max(hi for _, hi in intervals) + margin
        for step in range(CHANNEL_TRACKS):
            candidates.append(round(outer_lo + step * CHANNEL_TRACK_PITCH_UM, 3))
            candidates.append(round(outer_hi - step * CHANNEL_TRACK_PITCH_UM, 3))

        seen: set[float] = set()
        unique = [t for t in candidates if not (t in seen or seen.add(t))]
        unique.sort()
        lanes[axis] = unique
    return lanes


def _channel_paths(
    a: tuple[float, float],
    b: tuple[float, float],
    channels: dict[str, list[float]],
) -> list[list[tuple[float, float]]]:
    """Paths that leave the source into a free channel, cross on a free band,
    and drop into the destination -- the shape a route across the whole
    floorplan actually needs, which no elbow or single-jog Z can express."""
    (ax, ay), (bx, by) = a, b
    all_xs = channels.get("x", [])
    all_ys = channels.get("y", [])

    def near(tracks: list[float], *values: float, limit: int) -> list[float]:
        chosen: list[float] = []
        for value in values:
            for track in sorted(tracks, key=lambda t: abs(t - value))[:limit]:
                if track not in chosen:
                    chosen.append(track)
        return chosen

    xs = near(all_xs, ax, bx, limit=CHANNEL_NEAR_TRACKS)
    ys = near(all_ys, ay, by, limit=CHANNEL_NEAR_TRACKS)
    paths: list[list[tuple[float, float]]] = []
    for cx in xs:
        for cy in ys:
            paths.append([(ax, ay), (cx, ay), (cx, cy), (bx, cy), (bx, by)])
            paths.append([(ax, ay), (ax, cy), (cx, cy), (cx, by), (bx, by)])
    # Double-dogleg: leave the source on one track, cross on a band, and come
    # in to the destination on a *different* track. The single-track forms
    # above cannot express "the lane that gets me out is not the lane that
    # gets me in", which is exactly what a hop between two blocks whose
    # escapes face opposite ways needs -- `D1` and `D2` (amp_nmirr's west fan
    # to amp_input_pair's east fan) have no other shape available at all.
    # Bounded by only offering the tracks nearest each end.
    near_a = near(all_xs, ax, limit=CHANNEL_DOGLEG_TRACKS)
    near_b = near(all_xs, bx, limit=CHANNEL_DOGLEG_TRACKS)
    for cy in ys:
        for cx1 in near_a:
            for cx2 in near_b:
                if cx1 == cx2:
                    continue
                paths.append(
                    [(ax, ay), (cx1, ay), (cx1, cy), (cx2, cy), (cx2, by), (bx, by)]
                )
    near_a_y = near(all_ys, ay, limit=CHANNEL_DOGLEG_TRACKS)
    near_b_y = near(all_ys, by, limit=CHANNEL_DOGLEG_TRACKS)
    for cx in xs:
        for cy1 in near_a_y:
            for cy2 in near_b_y:
                if cy1 == cy2:
                    continue
                paths.append(
                    [(ax, ay), (ax, cy1), (cx, cy1), (cx, cy2), (bx, cy2), (bx, by)]
                )
    # Sort by length: a channel pair that happens to sit near both ends is a
    # short detour and should be preferred over one that crosses the cell.
    paths.sort(
        key=lambda p: sum(
            abs(q[0] - r[0]) + abs(q[1] - r[1]) for q, r in zip(p, p[1:])
        )
    )
    return paths


def _connect(
    bus: "met1_bus.Met1Bus",
    net: str,
    a: tuple[float, float],
    b: tuple[float, float],
    channels: dict[str, list[float]] | None = None,
) -> dict[str, Any] | None:
    """Join two met1 points, trying elbows, then floorplan channels, then
    Z-detours, until one clears."""
    _BLOCKER_COUNTS.clear()
    (ax, ay), (bx, by) = a, b
    for points in (
        [(ax, ay), (bx, ay), (bx, by)],
        [(ax, ay), (ax, by), (bx, by)],
    ):
        if _draw_guarded(bus, net, points):
            return {
                "detour_um": 0.0,
                "points": [[round(x, 3), round(y, 3)] for x, y in points],
            }
    for points in _channel_paths(a, b, channels or {}):
        if _draw_guarded(bus, net, points):
            return {
                "detour_um": None,
                "via_channel": True,
                "points": [[round(x, 3), round(y, 3)] for x, y in points],
            }
    for offset in DETOUR_OFFSETS_UM:
        candidates = [
            [(ax, ay), (bx, ay), (bx, by)],  # horizontal first
            [(ax, ay), (ax, by), (bx, by)],  # vertical first
        ]
        if offset:
            # Z-detours on both an intermediate row (mid_y) and an
            # intermediate column (mid_x), taken from either end -- a lane
            # that is congested next to the source is often free next to the
            # destination.
            candidates = [
                [(ax, ay), (ax, ay + offset), (bx, ay + offset), (bx, by)],
                [(ax, ay), (ax + offset, ay), (ax + offset, by), (bx, by)],
                [(ax, ay), (ax, by + offset), (bx, by + offset), (bx, by)],
                [(ax, ay), (bx + offset, ay), (bx + offset, by), (bx, by)],
            ] + candidates
            # Four-segment escapes: leave the source's own column, cross on a
            # free row, drop on a column shifted clear of the destination
            # block's other escape stubs, then come in. The three-segment
            # forms above cannot express "clear of both ends at once", which
            # is what a net crossing a whole 100 um array needs.
            for shift in (1.2, -1.2, 2.4, -2.4, 3.6, -3.6):
                candidates = [
                    [
                        (ax, ay),
                        (ax, ay + offset),
                        (bx + shift, ay + offset),
                        (bx + shift, by),
                        (bx, by),
                    ],
                    [
                        (ax, ay),
                        (ax + shift, ay),
                        (ax + shift, by + offset),
                        (bx, by + offset),
                        (bx, by),
                    ],
                ] + candidates
        for points in candidates:
            if _draw_guarded(bus, net, points):
                return {
                    "detour_um": offset,
                    "points": [[round(x, 3), round(y, 3)] for x, y in points],
                }
    return None


#: How many candidate assignments (which escape / which pad each terminal
#: takes) the router tries per node before settling for the best partial.
CANDIDATE_ASSIGNMENTS = 3
#: How many candidates per terminal feed that enumeration.
CANDIDATES_PER_TERMINAL = 3


def _candidate_assignments(
    points: list[dict[str, Any]], cx: float, cy: float
) -> list[tuple[list[dict[str, Any]], list[tuple[str, str]]]]:
    """Candidate `(resolved terminals, pad claims)` pairs for one node,
    best-guess first.

    Each terminal that offers a choice contributes its
    CANDIDATES_PER_TERMINAL nearest options (nearest to the node's own
    centroid); the assignments are then enumerated in increasing total
    "rank", so the all-nearest assignment is first and the search degrades
    gracefully from there. Pad claims are returned rather than applied,
    because only the assignment that is finally kept may claim a pad.
    """
    options: list[list[dict[str, Any] | None]] = []
    for point in points:
        if "candidates" not in point:
            options.append([None])
            continue
        ordered = sorted(
            point["candidates"], key=lambda c: abs(c[1] - cx) + abs(c[2] - cy)
        )[:CANDIDATES_PER_TERMINAL]
        options.append(list(ordered))

    indices = [range(len(o)) for o in options]
    combos = sorted(
        itertools.product(*indices), key=lambda combo: (sum(combo), combo)
    )[:CANDIDATE_ASSIGNMENTS]

    assignments: list[tuple[list[dict[str, Any]], list[tuple[str, str]]]] = []
    for combo in combos:
        resolved: list[dict[str, Any]] = []
        claims: list[tuple[str, str]] = []
        for point, choice, option in zip(points, combo, options):
            if "candidates" not in point:
                resolved.append(dict(point))
                continue
            name, x, y = option[choice]
            if point.get("claims_pad", True):
                claims.append((point["block"], name))
                name = f"{point['block']}.{name}"
            resolved.append(
                {
                    "block": point["block"],
                    "name": name,
                    "x": x,
                    "y": y,
                    "via": point["via"],
                }
            )
        assignments.append((resolved, claims))
    return assignments


#: How many of a blocking net's own "next-best" fully-routed solutions the
#: rip-up-and-reroute repair pass (:func:`_repair_unrouted_hops`) will force
#: before giving up on freeing one specific hop through it.
REPAIR_MAX_SKIPS_PER_NET = 3
#: Hard ceiling on repair attempts per :func:`route_inter_block_nets` call
#: (`repair=True`), so a genuine capacity deadlock -- no alternative routing
#: of the blocker exists at all -- costs a bounded number of tail replays
#: rather than looping. Each attempt redraws at most `len(sequence)` nets, the
#: same cost as one more :data:`ROUTE_ORDER_PASSES` pass, so this bounds the
#: repair pass to a small, fixed multiple of one order-search pass.
REPAIR_MAX_ATTEMPTS = 8


def _route_one_net(
    bus: "met1_bus.Met1Bus",
    net_name: str,
    specs: dict[str, dict[str, Any]],
    reports: dict[str, dict[str, Any]],
    origins: dict[str, dict[str, float]],
    trunks: dict[tuple[str, str], tuple[float, float]],
    combs: dict[tuple[str, str], list[tuple[str, float, float]]],
    used_ports: set[tuple[str, str]],
    channels: dict[str, list[float]],
    skip_first: int = 0,
) -> dict[str, Any]:
    """Draw one INTER_BLOCK_MET1 node into `bus` and report what was drawn.

    This is :func:`route_inter_block_nets`'s original per-net loop body,
    split out so :func:`_repair_unrouted_hops` can redraw a single net in
    isolation. `skip_first` forces the search past this net's own first
    `skip_first` fully-routed candidate assignment/chain-order solutions --
    i.e. asks "what is this net's *next*-best routing against the same
    already-drawn geometry?" instead of its greedy first pick.
    `skip_first=0` (the default, used by every call in the plain forward
    pass below) reproduces the original loop body exactly.
    """
    spec = specs[net_name]
    net = spec["net"]
    points: list[dict[str, Any]] = []
    for terminal in spec["terminals"]:
        if "trunk" in terminal:
            x, y = trunks[tuple(terminal["trunk"])]
            points.append(
                {
                    "block": terminal["trunk"][0],
                    "name": f"{terminal['trunk'][0]}:{net} trunk",
                    "x": x,
                    "y": y,
                    "via": False,
                }
            )
            continue
        if "comb" in terminal:
            # Already met1, already contacted: the comb drew every finger's
            # via itself, so this terminal is a point on drawn metal and
            # claims no pad the pin selector could collide with. Both of
            # the comb's row escapes are offered; the resolver below takes
            # whichever sits nearer the rest of the node.
            points.append(
                {
                    "block": terminal["comb"][0],
                    "candidates": combs[tuple(terminal["comb"])],
                    "via": False,
                    "claims_pad": False,
                }
            )
            continue
        bid = terminal["block"]
        if "ports" in terminal:
            # Several *named* pads of one block, any one of which satisfies
            # this terminal -- the guard-ring bulk taps (BULK_TAP_PORTS).
            # Unlike the `suffix`/`facing` form below, the names are given
            # explicitly, because the taps of one ring do not share a facing
            # (`TAP_S` faces 270 deg, `TAP_N` 90, `TAP_E` 0) and picking one
            # facing is exactly the pinning this shape exists to undo.
            by_name = _ports_by_name(reports[bid])
            candidates = [
                (
                    pname,
                    float(by_name[pname]["x_um"]) + origins[bid]["x"],
                    float(by_name[pname]["y_um"]) + origins[bid]["y"],
                )
                for pname in terminal["ports"]
                if pname in by_name and (bid, pname) not in used_ports
            ]
            if not candidates:
                raise KeyError(
                    f"net {net}: block {bid} has none of the ports "
                    f"{terminal['ports']} free"
                )
            points.append({"block": bid, "candidates": candidates, "via": True})
            continue
        if "port" in terminal:
            port = _ports_by_name(reports[bid])[terminal["port"]]
            lane = 0.0
            if "leg" in terminal:
                lane = (terminal["leg"] - 0.5) * (2 * RES_LANE_OFFSET_UM)
            px = float(port["x_um"]) + origins[bid]["x"]
            py = float(port["y_um"]) + origins[bid]["y"] + lane
            # Escape hatch: a multi-row resistor array's rows are packed
            # end to end with its own series-chain lanes, so any path
            # that tries to cross the block collides with them. A
            # chain-end terminal sits at a row end, though, and the track
            # straight out of that row end is free by construction -- so
            # every route to one of these starts by leaving the block
            # sideways at the terminal's own y, and the general router
            # only has to solve the open-channel part.
            bbox = reports[bid]["bbox_um"]
            west = bbox["x0"] + origins[bid]["x"]
            east = bbox["x1"] + origins[bid]["x"]
            outward = east + BLOCK_ESCAPE_UM if px > (west + east) / 2.0 else west - BLOCK_ESCAPE_UM
            point = {
                "block": bid,
                "name": f"{bid}.{terminal['port']}",
                "x": px,
                "y": py,
                "via": True,
                "fixed": True,
            }
            if terminal.get("escape", True):
                point["escape"] = (outward, py)
            points.append(point)
            used_ports.add((bid, terminal["port"]))
            continue
        candidates = [
            c
            for c in _li1_ports(
                reports[bid],
                origins[bid],
                terminal["suffix"],
                terminal["facing"],
                terminal.get("half"),
            )
            if (bid, c[0]) not in used_ports
        ]
        if not candidates:
            raise KeyError(
                f"net {net}: no li1 '{terminal['suffix']}' port facing "
                f"{terminal['facing']} deg on block {bid}"
                + (f" half {terminal['half']}" if terminal.get("half") else "")
            )
        points.append({"block": bid, "candidates": candidates, "via": True})

    # Resolve each block terminal to the candidate port nearest the net's
    # other terminals -- shortest wire, from the block's own geometry.
    anchors = [
        (p["x"], p["y"]) for p in points if "x" in p
    ] or [
        (sum(c[1] for c in p["candidates"]) / len(p["candidates"]),
         sum(c[2] for c in p["candidates"]) / len(p["candidates"]))
        for p in points if "candidates" in p
    ]
    cx = sum(a[0] for a in anchors) / len(anchors)
    cy = sum(a[1] for a in anchors) / len(anchors)

    # Which candidate each terminal takes is a *choice*, and the nearest
    # one is only a first guess. A comb offers two or four escapes (one
    # per device row, plus the spine side for the outermost node) and a
    # split MOS group offers several pads; picking centroid-nearest once
    # and never revisiting it is what left `D1`/`TAIL`/`VOUT` reported
    # unroutable while a perfectly good path existed off the *other*
    # escape of the same comb. So the assignments are enumerated too,
    # nearest-first, and the first that routes completely wins (unless
    # `skip_first` asks for it to be passed over).
    best_score: tuple[int, int] | None = None
    best_plan: list[dict[str, Any]] = []
    best_claims: list[tuple[str, str]] = []
    hops: list[dict[str, Any]] = []
    routed = False
    skipped = 0
    resolved: list[dict[str, Any]] = []
    for assignment in _candidate_assignments(points, cx, cy):
        resolved, claims = assignment
        for point in resolved:
            # The pad each terminal contacts, kept separate from `x`/`y`
            # because drawing an escape stub moves the latter. A retried
            # chain order has to start from the pad again, not from
            # wherever the previous attempt left the terminal.
            point["pad"] = (point["x"], point["y"])
        # The terminals of one node are joined as an open chain, so the
        # order they are visited in *is* the wire plan: a chain that
        # zig-zags across the floorplan asks the open-channel router for
        # corridors that a chain visiting the same terminals in a
        # friendlier order never needs.
        for plan in _chain_orders(resolved):
            mark = bus.mark()
            hops, routed = _draw_chain(bus, net, plan, channels)
            score = (0 if routed else 1, sum(1 for h in hops if not h["routed"]))
            if routed and skipped < skip_first:
                # A fully-routed candidate, but the repair pass asked for
                # this net's *next* solution past its greedy first pick --
                # keep it as the fallback (in case nothing survives past
                # skip_first, see the "not routed" tail below) and keep
                # looking rather than accepting it.
                skipped += 1
                routed = False
                bus.restore(mark)
                if best_score is None or score < best_score:
                    best_plan, best_score, best_claims = plan, score, claims
                continue
            if routed:
                best_plan, best_score, best_claims = plan, score, claims
                break  # geometry for the winning plan stays on the bus
            bus.restore(mark)
            if best_score is None or score < best_score:
                best_plan, best_score, best_claims = plan, score, claims
        if routed:
            break
    if not routed:
        # Every plan was rolled back (or, with `skip_first` set and nothing
        # surviving past it, only ever scored and rolled back). Redraw the
        # best one so the geometry on the bus is the geometry the report
        # below describes.
        hops, routed = _draw_chain(bus, net, best_plan, channels)
    used_ports.update(best_claims)
    # One label per net, on drawn metal, so `klt extract` promotes it as a
    # named top-level pin. Deliberately one and only one: two labels with
    # the same text on two *disconnected* pieces of metal would merge them
    # into one extracted net and manufacture connectivity that was never
    # drawn.
    bus.label(net, resolved[0]["x"], resolved[0]["y"])
    return {
        "net": net,
        "routed": routed,
        "schematic": spec["schematic"],
        "terminals": [p["name"] for p in best_plan],
        "blocks": sorted({p["block"] for p in best_plan}),
        "hops": hops,
    }


def _replay_tail(
    bus: "met1_bus.Met1Bus",
    sequence: list[str],
    from_index: int,
    specs: dict[str, dict[str, Any]],
    reports: dict[str, dict[str, Any]],
    origins: dict[str, dict[str, float]],
    trunks: dict[tuple[str, str], tuple[float, float]],
    combs: dict[tuple[str, str], list[tuple[str, float, float]]],
    used_ports: set[tuple[str, str]],
    channels: dict[str, list[float]],
    marks: list[tuple[int, ...]],
    port_snapshots: list[set[tuple[str, str]]],
    results: list[dict[str, Any]],
    skip_counts: dict[str, int],
) -> None:
    """Roll `bus` back to just before `sequence[from_index]` and redraw every
    net from there to the end of `sequence`, each with its current
    `skip_counts` entry.

    Every net at or after `from_index` sees the *replayed* geometry of every
    net before it, so the forward pass's own invariant -- a net only ever
    sees already-final geometry -- holds after a repair exactly as it does
    on the first pass. `marks`/`port_snapshots`/`results` are updated in
    place so a further repair attempt (or a revert back to this same point)
    can build on the new state.
    """
    bus.restore(marks[from_index])
    used_ports.clear()
    used_ports.update(port_snapshots[from_index])
    for j in range(from_index, len(sequence)):
        marks[j] = bus.mark()
        port_snapshots[j] = set(used_ports)
        results[j] = _route_one_net(
            bus, sequence[j], specs, reports, origins, trunks, combs,
            used_ports, channels, skip_first=skip_counts.get(sequence[j], 0),
        )


def _repair_unrouted_hops(
    bus: "met1_bus.Met1Bus",
    sequence: list[str],
    specs: dict[str, dict[str, Any]],
    reports: dict[str, dict[str, Any]],
    origins: dict[str, dict[str, float]],
    trunks: dict[tuple[str, str], tuple[float, float]],
    combs: dict[tuple[str, str], list[tuple[str, float, float]]],
    used_ports: set[tuple[str, str]],
    channels: dict[str, list[float]],
    marks: list[tuple[int, ...]],
    port_snapshots: list[set[tuple[str, str]]],
    results: list[dict[str, Any]],
) -> None:
    """Rip up and reroute the net that blocked a still-unrouted hop, in
    place, when doing so frees it without costing more than it buys.

    The order-search in :func:`build_bus_overlay` already retries a *whole*
    redraw with a different net order when something fails -- a coarse,
    whole-cell form of rip-up. What that cannot express is "net J's own
    greedy first solution happens to sit exactly where net K's one remaining
    hop needs to go, and no reordering changes that, because J is drawn
    before K in every order that still satisfies J's own prerequisites" --
    which is exactly the pattern issue #62's last increment measured: the
    same net, on every one of :data:`ROUTE_ORDER_PASSES` orderings, comes up
    one hop short.

    This targets exactly that case: it finds a still-unrouted hop, reads
    which net's already-drawn geometry blocked it
    (:data:`_LAST_BLOCKER`, recorded per hop by :func:`_draw_chain`), and --
    when that net is itself one of this call's own already-routed nets and
    is drawn earlier in `sequence` -- rolls `bus` back to just before it and
    replays the rest of `sequence` (:func:`_replay_tail`) with it forced
    past its first `skip_first` solutions (:func:`_route_one_net`). Kept
    only if the total number of unrouted hops drops and no new drawn-short
    conflict appears; reverted and blacklisted otherwise, so a genuine
    capacity deadlock -- no alternative routing of the blocker exists at all
    -- costs :data:`REPAIR_MAX_SKIPS_PER_NET` bounded attempts, not an
    unbounded search.
    """
    skip_counts: dict[str, int] = {}
    # (blocker, failing net) pairs already tried past their skip budget with
    # no improvement -- never retried, so a genuine deadlock cannot loop.
    exhausted: set[tuple[str, str]] = set()
    net_index = {name: i for i, name in enumerate(sequence)}

    def score() -> tuple[int, int]:
        conflicts = len(bus.conflicts())
        unrouted = sum(1 for r in results for h in r["hops"] if not h["routed"])
        return (conflicts, unrouted)

    for _ in range(REPAIR_MAX_ATTEMPTS):
        target: tuple[str, str] | None = None
        for r in results:
            if r["routed"]:
                continue
            for h in r["hops"]:
                if h["routed"]:
                    continue
                blocker = h.get("blocked_by")
                if (
                    blocker is None
                    or blocker not in net_index
                    or net_index[blocker] >= net_index[r["net"]]
                    or (blocker, r["net"]) in exhausted
                ):
                    continue
                target = (r["net"], blocker)
                break
            if target:
                break
        if target is None:
            return  # nothing left this pass can attribute to a rippable net

        failing_net, blocker = target
        blocker_i = net_index[blocker]
        skip_counts[blocker] = skip_counts.get(blocker, 0) + 1
        if skip_counts[blocker] > REPAIR_MAX_SKIPS_PER_NET:
            skip_counts[blocker] -= 1
            exhausted.add((blocker, failing_net))
            continue

        before = score()
        _replay_tail(
            bus, sequence, blocker_i, specs, reports, origins, trunks, combs,
            used_ports, channels, marks, port_snapshots, results, skip_counts,
        )
        if score() < before:
            continue  # improvement kept; look for the next repairable failure
        # No better (or worse, e.g. a new drawn-short conflict): put the
        # blocker back to its previous choice and never retry this pair.
        skip_counts[blocker] -= 1
        _replay_tail(
            bus, sequence, blocker_i, specs, reports, origins, trunks, combs,
            used_ports, channels, marks, port_snapshots, results, skip_counts,
        )
        exhausted.add((blocker, failing_net))


def route_inter_block_nets(
    bus: "met1_bus.Met1Bus",
    reports: dict[str, dict[str, Any]],
    origins: dict[str, dict[str, float]],
    bus_summary: dict[str, Any],
    order: list[str] | None = None,
    repair: bool = False,
) -> list[dict[str, Any]]:
    """Draw every INTER_BLOCK_MET1 node on met1 and report what was drawn.

    Terminals are ordered left-to-right and joined as a chain, each hop routed
    by :func:`_connect`. A hop that no candidate path can place without
    colliding is reported `routed: false` rather than drawn -- the flow gates
    on that, so an undrawn node can never be mistaken for a drawn one.

    `repair=True` runs :func:`_repair_unrouted_hops` after the forward pass
    below (unused by :func:`build_bus_overlay`'s order-search loop, which
    calls this `ROUTE_ORDER_PASSES` times and would multiply the repair cost
    by as many; used once, after that loop picks its winning order, on a
    fresh redraw of just that order -- see build_bus_overlay's own comment).
    `repair=False` (the default) makes this function behave exactly as it
    did before the repair pass existed.
    """
    channels = free_channels(reports, origins)
    trunks: dict[tuple[str, str], tuple[float, float]] = {}
    combs: dict[tuple[str, str], list[tuple[str, float, float]]] = {}
    for bid, entry in bus_summary.items():
        if entry.get("kind") == "bjt_parallel":
            for record in entry["nets"]:
                trunks[(bid, record["net"])] = (
                    record["trunk_x1_um"],
                    record["trunk_y_um"],
                )
        elif entry.get("kind") == "mos_comb":
            for record in entry["nets"]:
                combs[(bid, record["net"])] = [
                    (name, x, y) for name, x, y in record["escapes"]
                ]

    # A port may terminate at most one node: two nodes contacting the same
    # pad would be a short that neither DRC nor the drawn-short check can
    # see (they would be one net by construction).
    used_ports: set[tuple[str, str]] = set()
    specs = {spec["net"]: spec for spec in INTER_BLOCK_MET1}
    sequence = order or [spec["net"] for spec in INTER_BLOCK_MET1]

    # A restore point and the port-claim state captured *before* each net is
    # drawn, so a repair attempt can roll back to exactly one net's start and
    # replay forward -- see _repair_unrouted_hops / _replay_tail. Cheap to
    # keep even when `repair` is False: each entry is a handful of ints and a
    # small set.
    marks: list[tuple[int, ...]] = []
    port_snapshots: list[set[tuple[str, str]]] = []
    results: list[dict[str, Any]] = []
    for net_name in sequence:
        marks.append(bus.mark())
        port_snapshots.append(set(used_ports))
        results.append(
            _route_one_net(
                bus, net_name, specs, reports, origins, trunks, combs,
                used_ports, channels,
            )
        )

    if repair and any(not r["routed"] for r in results):
        _repair_unrouted_hops(
            bus, sequence, specs, reports, origins, trunks, combs,
            used_ports, channels, marks, port_snapshots, results,
        )

    return results


def _chain_orders(points: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Candidate visit orders for one node's terminals, best-guess first.

    Column-major and row-major sorts cover the two trunk shapes this floorplan
    actually has; the nearest-neighbour chains (one per possible starting
    terminal) cover the rest, and are what turns a supply trunk that has to
    visit three rows into a sequence of short hops. Duplicates are dropped so
    a two-terminal net still costs exactly one attempt.
    """
    orders: list[list[dict[str, Any]]] = [
        sorted(points, key=lambda p: (p["x"], p["y"])),
        sorted(points, key=lambda p: (p["y"], p["x"])),
    ]
    for start in range(len(points)):
        remaining = list(points)
        chain = [remaining.pop(start)]
        while remaining:
            here = chain[-1]
            nxt = min(
                remaining,
                key=lambda p: abs(p["x"] - here["x"]) + abs(p["y"] - here["y"]),
            )
            remaining.remove(nxt)
            chain.append(nxt)
        orders.append(chain)
    seen: set[tuple[int, ...]] = set()
    unique: list[list[dict[str, Any]]] = []
    for order in orders:
        key = tuple(id(p) for p in order)
        if key in seen:
            continue
        seen.add(key)
        unique.append(order)
    return unique


def _draw_chain(
    bus: "met1_bus.Met1Bus",
    net: str,
    plan: list[dict[str, Any]],
    channels: dict[str, list[float]] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Draw one node's vias, escape stubs and chain hops in `plan` order.

    Every point's `x`/`y` is reset from its `pad` before drawing, so a plan
    can be retried after an earlier one moved a terminal onto its escape stub.
    """
    bus.net(net)
    for point in plan:
        point["x"], point["y"] = point["pad"]
        if point["via"]:
            bus.via(point["x"], point["y"])
    # Draw each escape stub first, so the open-channel router below works
    # from points that are already outside their block.
    for point in plan:
        point.pop("escaped", None)
        if "escape" not in point:
            continue
        ex, ey = point["escape"]
        if _draw_guarded(bus, net, [(point["x"], point["y"]), (ex, ey)]):
            point["x"], point["y"] = ex, ey
            point["escaped"] = True

    hops: list[dict[str, Any]] = []
    routed = True
    for first, second in zip(plan, plan[1:]):
        hop = _connect(
            bus, net, (first["x"], first["y"]), (second["x"], second["y"]),
            channels,
        )
        if hop is None:
            routed = False
            hops.append(
                {
                    "from": first["name"],
                    "to": second["name"],
                    "routed": False,
                    "blocked_by": _LAST_BLOCKER[0] if _LAST_BLOCKER else None,
                    # Every net that vetoed at least one candidate path this
                    # hop tried, most-frequent first -- see _BLOCKER_COUNTS.
                    # `blocked_by` above is kept unchanged (the last-tried
                    # veto, not necessarily the dominant one) for backward
                    # compatibility with existing readers/tests.
                    "blocked_by_counts": dict(_BLOCKER_COUNTS.most_common()),
                }
            )
            continue
        hop.update({"from": first["name"], "to": second["name"], "routed": True})
        hops.append(hop)
    return hops, routed


def _draw_intra_block_busses(
    bus: "met1_bus.Met1Bus",
    blocks: list[dict[str, Any]],
    reports: dict[str, dict[str, Any]],
    origins: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """Draw every block's own intra-block bus into `bus` and return the
    per-block summary :func:`route_inter_block_nets` reads trunk/comb escape
    points from.

    Split out of :func:`build_bus_overlay` so both the order-search loop and
    the one-shot repair redraw after it (see that function's own comment) can
    build a fresh `(bus, summary)` pair from the same block list without
    duplicating this dispatch table.
    """
    summary: dict[str, Any] = {}
    for block in blocks:
        spec = block.get("bus")
        if not spec:
            continue
        bid = block["id"]
        if spec["kind"] == "res_series":
            summary[bid] = {
                "kind": "res_series",
                "legs": spec["legs"],
                "links": bus_res_series(
                    bus, bid, reports[bid], origins[bid], spec["legs"]
                ),
            }
        elif spec["kind"] == "bjt_parallel":
            summary[bid] = {
                "kind": "bjt_parallel",
                "nets": bus_bjt_parallel(
                    bus, spec["nets"], reports[bid], origins[bid]
                ),
            }
        elif spec["kind"] == "mos_comb":
            summary[bid] = {
                "kind": "mos_comb",
                "nets": bus_mos_comb(
                    bus, bid, reports[bid], origins[bid],
                    spec["spine_side"], spec["nets"],
                ),
            }
        else:  # pragma: no cover -- BLOCKS is a literal table
            raise ValueError(f"unknown bus kind {spec['kind']!r} on block {bid}")
    return summary


def build_bus_overlay(
    klt: str,
    out_dir: Path,
    pdk_info: dict[str, Any],
    blocks: list[dict[str, Any]],
    reports: dict[str, dict[str, Any]],
    origins: dict[str, dict[str, float]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Draw every declared intra-block bus into one `klt draw` overlay cell.

    Returns `(generator_report, summary)`.
    """
    base = [spec["net"] for spec in INTER_BLOCK_MET1]
    # Seed the search with every rotation of the declared order, so no single
    # net is permanently first (or permanently last) just because of where it
    # sits in a table written for readability.
    pending = [base[k:] + base[:k] for k in range(len(base))]
    seen: set[tuple[str, ...]] = set()
    attempts: list[dict[str, Any]] = []
    best: tuple[Any, ...] | None = None
    for _ in range(ROUTE_ORDER_PASSES):
        if not pending:
            break
        order = pending.pop(0)
        if tuple(order) in seen:
            continue
        seen.add(tuple(order))
        bus = met1_bus.Met1Bus()
        summary = _draw_intra_block_busses(bus, blocks, reports, origins)

        routes = route_inter_block_nets(bus, reports, origins, summary, order)
        failed = [r["net"] for r in routes if not r["routed"]]
        conflicts = bus.conflicts()
        # Score by what issue #62 actually asks for -- schematic nodes joined
        # across every block they reach -- not by this flow's own net count.
        # Two orderings can route the same number of nets and be worth very
        # different amounts: a node that is one block short of complete
        # coverage buys nothing, a node that completes one buys a criterion-1
        # row.
        drawn = sum(
            1
            for row in schematic_net_coverage(routes)
            if row["status"] == "drawn"
        )
        hops_routed = sum(
            1 for r in routes for h in r["hops"] if h.get("routed")
        )
        attempts.append(
            {
                "order": list(order),
                "failed": failed,
                "conflicts": len(conflicts),
                "schematic_nets_drawn": drawn,
                "hops_routed": hops_routed,
            }
        )
        # No drawn shorts first, then schematic coverage, then raw drawn
        # connectivity -- losing a four-terminal supply trunk is worse than
        # losing a two-terminal signal net even when both leave the coverage
        # table unchanged.
        score = (len(conflicts), -drawn, -hops_routed, len(failed))
        if best is None or score < best[0]:
            best = (score, bus, summary, routes, conflicts, list(order))
        if not failed and not conflicts:
            break
        # Rip up and retry with the nets that lost moved to the front. This
        # router is greedy, so which net claims a corridor first decides
        # whether a later one has anywhere to go; retrying with the losers
        # promoted is the cheapest correct answer to that, and it keeps the
        # ordering out of the hands of a hand-tuned constant that a future
        # parameter change would silently invalidate.
        pending.append(failed + [net for net in order if net not in failed])

    # Keep the *best* pass, not the last: the reorder heuristic can cycle,
    # and a later pass is not automatically an improvement.
    assert best is not None
    _, bus, summary, routes, conflicts, chosen_order = best

    # --- rip-up-and-reroute repair pass ------------------------------------
    # The order-search above is a coarse, whole-cell form of rip-up: retry
    # everything with a different net order. It cannot express "net J's own
    # greedy solution sits exactly where net K's one remaining hop needs to
    # go, and no order changes that because J must still be drawn before K"
    # -- which is what issue #62's own record showed: the same net, on every
    # one of ROUTE_ORDER_PASSES orderings, came up exactly one hop short (see
    # _repair_unrouted_hops). Rebuild the winning order on a fresh bus once
    # more, this time with `repair=True`, so route_inter_block_nets can rip
    # up and retry the specific net named as each remaining hop's blocker.
    # Every input here is deterministic (no randomness anywhere in this
    # module), so this reproduces `bus`/`routes` byte-for-byte before repair
    # does anything -- this can only match or improve the order-search's own
    # winner, never regress it.
    if any(not r["routed"] for r in routes):
        repaired_bus = met1_bus.Met1Bus()
        repaired_summary = _draw_intra_block_busses(repaired_bus, blocks, reports, origins)
        repaired_routes = route_inter_block_nets(
            repaired_bus, reports, origins, repaired_summary, chosen_order,
            repair=True,
        )
        repaired_conflicts = repaired_bus.conflicts()
        repaired_drawn = sum(
            1
            for row in schematic_net_coverage(repaired_routes)
            if row["status"] == "drawn"
        )
        repaired_hops_routed = sum(
            1 for r in repaired_routes for h in r["hops"] if h.get("routed")
        )
        repaired_failed = [r["net"] for r in repaired_routes if not r["routed"]]
        repaired_score = (
            len(repaired_conflicts), -repaired_drawn, -repaired_hops_routed,
            len(repaired_failed),
        )
        if repaired_score < best[0]:
            bus, summary, routes, conflicts = (
                repaired_bus, repaired_summary, repaired_routes, repaired_conflicts,
            )
        attempts.append(
            {
                "order": list(chosen_order),
                "failed": repaired_failed,
                "conflicts": len(repaired_conflicts),
                "schematic_nets_drawn": repaired_drawn,
                "hops_routed": repaired_hops_routed,
                "repair_pass": True,
                "kept": repaired_score < best[0],
            }
        )

    summary["_inter_block"] = routes
    summary["_route_order_attempts"] = attempts
    summary["_route_order_used"] = chosen_order

    # --- drawn-short / spacing proof --------------------------------------
    # Every met1 rectangle carries the electrical node it belongs to, so two
    # nodes' wires touching is detectable *here*, not left to be discovered
    # as a mystery LVS merge. Empty is the only acceptable result, and the
    # flow's exit status gates on it.
    summary["_conflicts"] = conflicts

    # --- split-node proof (the opposite failure) ---------------------------
    # `conflicts()` catches two *different* nodes' metal touching. This
    # catches one node's own metal NOT touching: a net drawn as two pieces
    # that never meet is not a connected node, and nothing downstream reports
    # it -- `klt extract` simply sees two anonymous nets and DRC sees two
    # legal wires. Recorded per net, and gated only for the nets this router
    # claims it fully routed (see :func:`split_routed_nets`): a net that came
    # up a hop short is *expected* to be in more than one piece, and is
    # already scored as such in the coverage table.
    summary["_components"] = bus.components()

    report = bus.emit(klt, out_dir, "bandgap_core_bus", pdk_info, MET1_BUS_NOTE)
    (out_dir / "bus-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return report, summary


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


def union_bbox(
    block_ids: list[str],
    reports: dict[str, dict[str, Any]],
    origins: dict[str, dict[str, float]],
) -> dict[str, float]:
    x0s, y0s, x1s, y1s = [], [], [], []
    for bid in block_ids:
        bbox = reports[bid]["bbox_um"]
        origin = origins[bid]
        x0s.append(bbox["x0"] + origin["x"])
        y0s.append(bbox["y0"] + origin["y"])
        x1s.append(bbox["x1"] + origin["x"])
        y1s.append(bbox["y1"] + origin["y"])
    return {"x0": min(x0s), "y0": min(y0s), "x1": max(x1s), "y1": max(y1s)}


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
    a 108-segment ladder or a 16-way split pair is chosen therefore decides
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
#: single-port nodes no schematic net reaches (see :func:`trim_tap_pins`).
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
        "blocks": ["core_mirror", "amp_pmirr", "amp_nmirr"],
        "hops": ["GDRV"],
        "schematic": "amp output (MP4/MN3 drains) + MPOUT/MPAMP gates -- one "
        "node in the schematic and, since the gate-contact gap closed, one "
        "drawn node in the layout too",
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
        "blocks": ["core_mirror", "amp_input_pair", "amp_pmirr"],
        "hops": ["VDD"],
        "schematic": "supply trunk: MPOUT/MPAMP sources + MP1/MP2 well side "
        "+ MP3/MP4 sources",
    },
    {
        "net": "VSS",
        "blocks": ["amp_nload", "amp_nmirr", "pnp_ctat", "pnp_ptat"],
        "hops": ["VSS"],
        "schematic": "ground trunk: MN1-MN4 sources + both PNPs' base ties. "
        "The three resistor blocks' res_high_po bulk terminals "
        "(design/bandgap_core.sch r2ab/r2bb/r1b) are on this node in the "
        "schematic too, but the extraction deck ties every resistor bulk to "
        "its synthesized `vsubs` global rather than to drawn geometry "
        "(SUBSTRATE_NET_NOTE), so there is no pad in those blocks for metal "
        "to reach and they are not counted as routing targets here",
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


def trim_tap_pins(reports: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Label the downward-only trim ladder's taps at **both ends** of the
    DR-002 code range (0 and -N_R2_TRIM_CODES), per leg.

    The ladder interdigitates the two legs by segment index (even = leg A,
    odd = leg B, per layout/matching-plan.md Section 3), so leg A's code-0
    tap is segment 0's far terminal and its code-N tap is the last even
    segment's; leg B is the odd-index mirror image. Indices are validated
    against the block's own reported ports, so a count-constant change fails
    loudly here instead of silently mislabelling a tap.
    """
    bid = "res_trim"
    available = {p["name"] for p in reports[bid]["ports"]}
    last_a = 2 * N_R2_TRIM_CODES - 2
    last_b = 2 * N_R2_TRIM_CODES - 1
    wanted = [
        ("TRIM_A_CODE_0", f"R0_B"),
        (f"TRIM_A_CODE_MINUS{N_R2_TRIM_CODES}", f"R{last_a}_B"),
        ("TRIM_B_CODE_0", f"R1_B"),
        (f"TRIM_B_CODE_MINUS{N_R2_TRIM_CODES}", f"R{last_b}_B"),
    ]
    pins = []
    for net, port in wanted:
        if port not in available:
            raise KeyError(f"block '{bid}' has no trim-tap port '{port}'")
        pins.append({"net": net, "block": bid, "port": port})
    return pins


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


def flow_gate(
    *,
    drc_clean: bool,
    within_budget: bool,
    full_scale_ladder: bool,
    all_classes: bool,
    pin_count: int,
    met1_conflicts: list[Any],
    merged_pin_names: list[str],
    split_routed: dict[str, int],
) -> dict[str, bool]:
    """The flow's pass/fail gate, as a named condition per row.

    Kept a pure function of already-measured values (rather than an inline
    boolean at the end of :func:`main`) for two reasons: the composition is
    then unit-testable without a `klt` install or a PDK -- see
    `layout/tests/test_routed_flow_gates.py` -- and a failing run can name
    *which* condition failed instead of only reporting exit 1.

    What is deliberately NOT in here: `klt lvs`-clean and schematic-net
    coverage. Both are blocked upstream (MOS_GATE_NOTE, RES_FLAVOR_NOTE) and
    are recorded as measured numbers in record.md's own scoreboard instead;
    gating on them would only mean the flow never runs to completion, which
    hides the evidence rather than producing it.

    The three that ARE gated and are not about the tool's own verdicts --
    `no_drawn_shorts`, `no_merged_pin_names` and `no_split_routed_nets` --
    are this flow's own honesty checks. The first two catch a way the layout
    could claim connectivity the schematic does not contain (through metal,
    and through a pin label respectively); the third catches the inverse, a
    node this flow's own bookkeeping calls routed while the drawn metal is
    still in two pieces (see :func:`split_routed_nets`). None of the three is
    visible to DRC.
    """
    return {
        "drc_clean": drc_clean,
        "within_budget": within_budget,
        "full_scale_ladder": full_scale_ladder,
        "device_classes_present": all_classes,
        "pins_promoted": pin_count > 0,
        "no_drawn_shorts": not met1_conflicts,
        "no_merged_pin_names": not merged_pin_names,
        "no_split_routed_nets": not split_routed,
    }


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
    for pin in trim_tap_pins(reports):
        if (pin["block"], pin["port"]) not in used:
            pins.append(pin)
            used.add((pin["block"], pin["port"]))

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
    budget_um2 = 0.05 * 1000.0 * 1000.0

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
    r2_units = BLOCKS[[b["id"] for b in BLOCKS].index("res_r2")]["params"]["num"]
    full_scale_ladder = r2_units == 2 * N_R2

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
        f"| 2 | Resistor ladder at real unit count | {'MET' if full_scale_ladder else 'NOT MET'} | "
        f"`res_r2` num={r2_units} (= 2 x n_r2={N_R2}); composed bbox "
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
        "| 5 | Blocking `klt` gaps filed as friction | MET | every gap the "
        "previous three records named is now CLOSED upstream and this "
        "record is the re-run against them (2AMLogic/klayout-tools#461 via "
        "#474, #462 via #471, #463 via #475, #454 via #468, #470 via #481). "
        "New this increment: #490 (the sky130 extraction deck synthesizes "
        "the substrate/bulk net from an empty region, so no drawn shape can "
        "join it -- the dominant remaining LVS term), #491 (#462's "
        "suppression path is unreachable on sky130: no deck `dummy` layer, "
        "no generator draws one, no CLI override), #492 (`gen-compose` "
        "still cannot route to a poly gate port, so #461's landing pad has "
        "to be contacted by hand), #504 (a `bulk_to_substrate` resistor "
        "extracts with one more terminal than the same device read from a "
        "plain-element reference, so no resistor can ever be paired and the "
        "compare says so only as generic `device.unmatched`) |"
    )
    a("")
    a(f"- [{'x' if drc_clean else ' '}] DRC on the composed, routed layout is clean")
    a(
        f"- [{'x' if within_budget else ' '}] Composed bbox area "
        f"({composed_area_um2:,.0f} um^2) is within the < 0.05 mm^2 "
        f"({budget_um2:,.0f} um^2) budget, **at the real 108-unit ladder count**"
    )
    a("")
    a("## Flow")
    a("")
    a(f"1. `klt gen` once per matched device group ({len(BLOCKS)} blocks).")
    a(
        "2. `klt draw` once, for the whole cell: every intra-block bus and "
        "every inter-block net, on met1 over mcon, plus one met1 net label "
        "each -- `bandgap_core_bus.draw.json`, summarised in "
        "`bus-summary.json`."
    )
    a(
        "3. `klt gen-compose` with `placement.strategy: \"explicit\"`, an "
        "empty `connectivity[]` (routing is on met1, above) and `pins[]` for "
        "the label-only nodes -- `compose.request.json`."
    )
    a("4. `klt drc <composed> --deck sky130`.")
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
        "own second conductor and via (`metals = (li1, met1)`, "
        "`vias = (mcon,)`). This flow draws them itself from each block's "
        "reported `ports[]` (MET1_BUS_NOTE). That is what turns a "
        "108-segment ladder into two real series resistors, an 8-unit PNP "
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
    a("| net | terminals | routed | schematic node |")
    a("| --- | --- | --- | --- |")
    for route in met1_routes:
        a(
            f"| `{route['net']}` | "
            f"{' + '.join(f'`{t}`' for t in route['terminals'])} | "
            f"{'yes' if route['routed'] else 'NO'} | {route['schematic']} |"
        )
    a("")
    a("## Schematic inter-block nets: drawn vs. labelled only")
    a("")
    a(
        "The table above counts this flow's own routing declaration. This "
        "one counts what issue #62 actually asks for: every node of "
        "design/bandgap_core.sch (+ design/error_amp.sch) that joins devices "
        "in different blocks, and whether drawn metal joins **all** the "
        "blocks the schematic says it reaches. "
        "The cause of a short row has changed with this increment, and the "
        "change is the point of it: it is no longer a tool gap. Every one of "
        "these nodes is now *expressible* -- MOS gates are contactable "
        "(MOS_GATE_NOTE) and the resistor blocks carry the schematic's own "
        "flavour (RES_FLAVOR_NOTE) -- so a row that is not `drawn` is this "
        "flow's own router failing to find a corridor through its own "
        "congestion, and nothing upstream is being waited on for it."
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
        "that count is short. `VSS` reaches four blocks here, not the seven "
        "an earlier record listed: the three resistor blocks' `res_high_po` "
        "bulk terminals are on this node in the schematic, but the "
        "extraction deck puts every resistor bulk on its synthesized `vsubs` "
        "global rather than on drawn geometry (SUBSTRATE_NET_NOTE), so there "
        "is no pad in those blocks for metal to reach and counting them as "
        "routing targets would be scoring against an impossible bar rather "
        "than a missed one. The correspondence itself is declared to `klt "
        "lvs` instead."
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
    a("The residual gap has six disclosed causes, none of them a topology "
      "error in either netlist:")
    a("")
    a(
        "1. **Unrouted nodes.** "
        f"{len(coverage) - len(fully_drawn)} of {len(coverage)} schematic "
        "inter-block nodes are not joined across every block they reach (see "
        "the coverage table above), so the corresponding layout nets are "
        "split where the reference has one. Unlike every previous "
        "increment's headline cause, this one is not a tool gap: it is this "
        "flow's own hand-written router running out of corridors in its own "
        "congestion, and it is the first thing a further increment should "
        "attack."
    )
    a(
        "2. **The substrate net is synthesized, not drawn.** "
        f"{SUBSTRATE_NET_NOTE} Declared through "
        f"`hints.same_nets={json.dumps(SUBSTRATE_SAME_NETS)}` rather than "
        "worked around in either netlist. The layout's own drawn `VSS` -- "
        "the NMOS sources, the substrate guard-ring taps and both PNP base "
        "ties -- is then a second layout net with no reference counterpart, "
        "because the reference (correctly) has only one ground node."
    )
    a(
        f"3. **Dummy devices cannot be declared on sky130.** "
        f"{DUMMY_DEVICE_NOTE}"
    )
    a(
        "4. **`MMCC`, the amp's compensation cap, is in the reference but "
        "deliberately not drawn in this layout** (see the Blocks note "
        "above), so one reference device has no layout counterpart by "
        "construction."
    )
    a(
        "5. **Resistor values differ by the schematic's head resistance.** "
        "design/bandgap_core.sch line 188 models a res_high_po segment as "
        "`R ~ 380 + 325*L` ohm, with the 380 ohm head charged once per "
        "*device*; the extractor derives R from drawn body squares alone "
        "(319.8 ohm/sq), so a 270 um leg reads 86,346 ohm against the "
        "reference's 88,130. The layout also puts the DR-002 trim taps in "
        "series in each leg, which the schematic carries as a length term on "
        "the same device (`L='r_lseg*n_r2+r_lseg_trim*n_r2_trim'`) rather "
        "than as separate devices."
    )
    a(
        "6. **No resistor can be paired at all: the two sides' resistor "
        f"device class has a different terminal count.** {RES_BULK_ARITY_NOTE} "
        "This is why cause 5's value difference has never actually been "
        "reached -- the comparer stops one step earlier, at the arity."
    )
    a("")
    a(
        "None of the six is worked around by editing either netlist. "
        "`reference.spice` states design/bandgap_core.sch; rewriting it to "
        "enumerate the layout's own shortfalls would make LVS compare the "
        "layout against itself, which is not evidence. The one declaration "
        "made -- the substrate correspondence in cause 2 -- is a `hints` "
        "entry, and it states something that is true of the design rather "
        "than something convenient about the layout."
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
        f"{lvs_devices.get('matched')}. The six causes above are the whole "
        "of it; none is hidden behind a number that moved."
    )
    a(
        "- **Not fully inter-block routed either.** "
        f"{len(fully_drawn)}/{len(coverage)} schematic inter-block nets are "
        "joined across every block they reach. The rest are *partial*, not "
        "absent: each is drawn between the blocks the router could reach and "
        "stops where it could not, which the coverage table names per row. "
        "Every one of them is now expressible -- what is missing is corridor, "
        "not capability."
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
        "- **Array dummies are counted as real devices.** The `pnp` and "
        f"`{RES_CLASS}` counts above include each array's dummy edge "
        "units, which have no schematic counterpart and cannot be marked as "
        "dummies (cause 2 above). Turning dummies off would trade a real "
        "matching property for a smaller mismatch number; this flow keeps "
        "them."
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
        "- [`drc.json`](drc.json), [`extract.json`](extract.json), "
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
    # scale, every device class must extract, and pins must be promoted.
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
        all_classes=all_classes,
        pin_count=pin_count,
        met1_conflicts=met1_conflicts,
        merged_pin_names=merged_pin_names,
        split_routed=met1_split_routed,
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
