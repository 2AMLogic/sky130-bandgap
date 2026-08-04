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

What this script does NOT claim -- read record.md's own "What this record
does NOT claim" section for the authoritative, measured version:

- **Not LVS-clean.** The MOS blocks are bussed now -- each matched device's
  split units share a source, a drain and a gate, so `combine_devices` folds
  them into the `m = splits` device the schematic states. What remains is
  this flow's *own* router: a handful of inter-block nodes still have a hop
  it cannot draw without a short, and those are left open rather than
  certified. record.md names them per run.
- **The gate contacts are a layout-side workaround, not a tool capability.**
  Every `klt gen` MOS generator on sky130 still draws the gate poly exactly
  coincident with the active region (2AMLogic/klayout-tools#461), so this
  flow draws the missing poly extension itself, from the generator's own
  reported gate port. See MOS_GATE_NOTE, and MOS_BAND_NOTE for the second
  half of the same gap: `diff_pair`'s fixed ring padding and row pitch leave
  room for exactly one gate contact row per side, which is what forces the
  inboard/outboard/li1-bond split `layout/bin/mos_bus.py` implements.
- **Not fully inter-block routed.** record.md's "Schematic inter-block nets"
  table scores every schematic inter-block node as drawn / partial /
  labelled-only against SCHEMATIC_INTER_BLOCK_NETS below -- i.e. against
  design/bandgap_core.sch's node list, not against this script's own
  declaration -- and criterion 1 is PARTIAL while any node is short.
- **Array dummies remain unmatched devices.** Neither curated deck declares
  an `ExtractionDeck.dummy` marker layer and no generator draws one, and the
  suppression path that exists covers MOS gates only -- never a resistor or
  bipolar unit. Every matched array's dummy edge units therefore extract as
  real devices with no schematic counterpart. See DUMMY_DEVICE_NOTE below.

Every one of those gaps is filed upstream per CLAUDE.md's friction protocol
and named in the NOTE constants below; record.md restates them with the
measured numbers from the run that produced it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import met1_bus  # noqa: E402  -- local module, resolved from this script's dir
import mos_bus  # noqa: E402  -- local module, resolved from this script's dir

# ---------------------------------------------------------------------------
# Friction notes (upstream tool gaps this script works around or is limited
# by). Each is filed at 2AMLogic/klayout-tools per CLAUDE.md's protocol as a
# generic tool-gap description; the design-specific consequence lives here and
# in layout/matching-plan.md, never in that tracker.
# ---------------------------------------------------------------------------
MET1_BUS_NOTE = (
    "sky130's generator/router layer-role table still exposes exactly one "
    "routing metal role (`metal` -> li1 67/20) -- the same layer every "
    "`klt gen` generator draws its device pads on -- so `klt gen-compose` "
    "cannot draw an intra-block bus. klayout-tools#433's merged fix (#439) "
    "made that failure visible rather than expressible: a self-net whose "
    "backbone crosses another pad on the same block is now reported "
    "unroutable instead of certified as a short, and the two options that "
    "would make bussing routable (expose a metal2/via role; via-drop "
    "routing) were deliberately left as follow-ups. The same tool's sky130 "
    "*extraction* deck, meanwhile, already declares the whole two-level "
    "stack (`metals = (li1 67/20, met1 68/20)`, `vias = (mcon 67/44)`) and "
    "`klt extract` connects it. This flow therefore draws every intra-block "
    "bus itself with `klt draw`, on met1 over mcon -- see "
    "layout/bin/met1_bus.py. Hand-placing what a router should plan is the "
    "residual gap, not a solved problem."
)
MOS_GATE_NOTE = (
    "Every `klt gen` MOS generator on sky130 (`diff_pair`, `mos_array`) "
    "draws the gate poly with exactly the active region's extent -- the "
    "poly and diff rectangles share both their top and bottom edges -- and "
    "reports the gate port on that shared boundary "
    "(2AMLogic/klayout-tools#461, still open). There is no poly landing "
    "area outside the channel on which a contact could be placed: a contact "
    "at the reported gate port straddles the diff edge (the curated deck "
    "flags it under `poly.enclosing.licon.1` and `diff.enclosing.licon.1`), "
    "and a contact moved inward sits on poly over the channel. This flow "
    "therefore draws the missing piece itself, from the generator's own "
    "reported gate port: a poly extension of the port's reported width past "
    "the active edge, then licon/li1 on it -- the same overhang every real "
    "foundry PDK draws for exactly this purpose (see "
    "met1_bus.Met1Bus.gate_landing). That is a layout-side workaround, not "
    "a substitute for the generator drawing it: the extension's size and "
    "direction are chosen here, per block, from geometry this repo derives, "
    "and the room available for it is set by two other fixed generator "
    "constants (MOS_BAND_NOTE)."
)
MOS_BAND_NOTE = (
    "2AMLogic/klayout-tools#484: `klt gen diff_pair`'s guard-ring padding "
    "(0.5 um) and inter-row "
    "spacing (0.4 um) are module constants with no parameter, and both are "
    "far too small to bring a matched block's two gate nets out: one gate "
    "contact stack (poly extension + licon + li1 pad, ~0.35 um) plus the "
    "real sky130 poly-to-poly spacing already exceeds the band, so the "
    "second gate net cannot get a second contact row on the same side. "
    "This flow works around it by giving each block at most one *inboard* "
    "routed gate net (stubbed to the innermost lane) and routing the other "
    "one *outboard*, past the guard ring, and by bonding a diode-connected "
    "device's gate straight to its own pad on li1. That covers this "
    "circuit's five matched groups but not the general case: a group whose "
    "two devices both need an independent, non-diode gate on a block with "
    "more than two rows has nowhere left to go."
)
RES_FLAVOR_NOTE = (
    "`klt gen res_array` on sky130 can only draw the base "
    "`res_generic_po` flavour: the generator's `res_implant`/`res_block` "
    "layer roles are None for the sky130 family, while the same tool's "
    "sky130 extraction deck recognises three flavours "
    "(`res_generic_po` 48.2, `res_high_po` 319.8, `res_xhigh_po` 2000 "
    "ohm/sq) distinguished by implant masks the generator never draws. A "
    "schematic built on a higher-sheet-rho flavour -- as this one is -- "
    "therefore cannot be laid out with a matching device class, and "
    "`klt lvs` has no parameter tolerance knob to absorb the difference."
)
DUMMY_DEVICE_NOTE = (
    "Neither curated extraction deck declares an `ExtractionDeck.dummy` "
    "marker layer, and no `klt gen` generator draws one, so a matched "
    "array's dummy edge units extract as ordinary devices with no "
    "schematic counterpart. The suppression path that does exist (added "
    "for klayout-tools#295) is also MOS-gate-only -- it can never drop a "
    "dummy resistor or a dummy bipolar. Turning dummies off to make LVS "
    "count would be a matching regression this flow refuses to take."
)

# ---------------------------------------------------------------------------
# Floorplan geometry constants (um)
# ---------------------------------------------------------------------------
#: Outward `direction_deg` each `klt gen` port family faces.
DIRECTION_EAST = 0
DIRECTION_NORTH = 90
DIRECTION_WEST = 180

BLOCK_MARGIN_UM = 12.0  # clearance between blocks placed side by side in a row
ROW_MARGIN_UM = 16.0  # clearance between stacked rows
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
            "kind": "mos_diff_pair",
            "devices": {
                "M1": {"S": "VDD", "D": "VOUT", "G": "GDRV"},
                "M2": {"S": "VDD", "D": "TAIL", "G": "GDRV"},
            },
            "ring_net": "VDD",
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
            "kind": "mos_diff_pair",
            "devices": {
                "Q1": {"S": "TAIL", "D": "D1", "G": "VB"},
                "Q2": {"S": "TAIL", "D": "D2", "G": "VA"},
            },
            "ring_net": "VDD",
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
            "kind": "mos_diff_pair",
            "devices": {
                "M1": {"S": "D1", "D": "VSS", "G": "D1"},
                "M2": {"S": "D2", "D": "VSS", "G": "D2"},
            },
            "ring_net": "VSS",
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
            "kind": "mos_diff_pair",
            "devices": {
                "M1": {"S": "VDD", "D": "PN", "G": "PN"},
                "M2": {"S": "VDD", "D": "GDRV", "G": "PN"},
            },
            "ring_net": "VDD",
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
            "kind": "mos_diff_pair",
            "devices": {
                "M1": {"S": "VSS", "D": "GDRV", "G": "D1"},
                "M2": {"S": "VSS", "D": "PN", "G": "D2"},
            },
            "ring_net": "VSS",
        },
        "matched_group_label": "MN3/MN4 (amp NMOS mirror outputs)",
        "real_target": f"amp_m_nmirr={AMP_M_NMIRR}, W=8 L=20 "
        "(design/error_amp.sch); drawn 1:1",
    },
]

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
#: reports whatever it has. Each pass is a full redraw from scratch, and the
#: whole flow runs in seconds, so this is cheap insurance against the greedy
#: order being wrong for some future floorplan.
ROUTE_ORDER_PASSES = 20


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
                hop = _connect_any(bus, net_id, [((ax, ay), (bx, by))])
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


#: The bandgap core's inter-block nodes that this flow draws on met1.
#:
#: Every terminal is either a named li1 device pad (`port`, contacted through
#: an mcon at the position that block's own `ports[]` reports) or one of the
#: met1 points an intra-block bus already presents that node at (`trunk`).
#: Gate-terminated nodes (`GDRV`, and the gate ends of `VA`/`VB`/`D1`/`D2`/
#: `PN`) are ordinary terminals here now that `layout/bin/mos_bus.py` gives
#: every gate a contact -- in PR #64/#65 they could not be expressed at all.
#: Ordered most-constrained-first. A net that has to cross a 100 um array to
#: reach its other end has exactly one free band to do it in; a short hop
#: between neighbouring blocks has many. Routing the long ones first is what
#: keeps a later short hop from walling off the only corridor an earlier one
#: needed -- the ordering is load-bearing, not cosmetic.
INTER_BLOCK_MET1: list[dict[str, Any]] = [
    {
        "net": "VA",
        "terminals": [
            {"block": "res_trim", "port": f"R{2 * N_R2_TRIM_CODES - 2}_B", "leg": 0},
            {"trunk": ("pnp_ctat", "VA")},
            {"trunk": ("amp_input_pair", "VA")},
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
            {"trunk": ("core_mirror", "VOUT")},
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
            {"trunk": ("amp_input_pair", "VB")},
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
        "net": "VSS",
        "terminals": [
            {"trunk": ("amp_nload", "VSS")},
            {"trunk": ("amp_nmirr", "VSS")},
            {"trunk": ("pnp_ctat", "VSS")},
            {"trunk": ("pnp_ptat", "VSS")},
        ],
        "schematic": "VSS trunk: the amp's NMOS rails and guard rings plus "
        "both PNP base ties (the diode-connected PNPs' base and collector "
        "both sit on VSS)",
    },
    {
        "net": "VDD",
        "terminals": [
            {"trunk": ("core_mirror", "VDD")},
            {"trunk": ("amp_input_pair", "VDD")},
            {"trunk": ("amp_pmirr", "VDD")},
        ],
        "schematic": "VDD trunk across all three PMOS groups -- MPOUT/MPAMP "
        "and MP3/MP4 sources, and MP1/MP2's own n-well tie (the input "
        "pair's bulk terminal, which its sources do not carry)",
    },
    {
        "net": "GDRV",
        "terminals": [
            {"trunk": ("core_mirror", "GDRV")},
            {"trunk": ("amp_nmirr", "GDRV")},
            {"trunk": ("amp_pmirr", "GDRV")},
        ],
        "schematic": "the amp's output (MP4/MN3 drains) and the core "
        "mirror's gate drive -- one node in the schematic",
    },
    {
        "net": "TAIL",
        "terminals": [
            {"trunk": ("core_mirror", "TAIL")},
            {"trunk": ("amp_input_pair", "TAIL")},
        ],
        "schematic": "MPAMP drain to the amp input pair's common source",
    },
    {
        "net": "D1",
        "terminals": [
            {"trunk": ("amp_input_pair", "D1")},
            {"trunk": ("amp_nload", "D1")},
            {"trunk": ("amp_nmirr", "D1")},
        ],
        "schematic": "MP1 drain to its NMOS diode load and on to MN3's gate",
    },
    {
        "net": "D2",
        "terminals": [
            {"trunk": ("amp_input_pair", "D2")},
            {"trunk": ("amp_nload", "D2")},
            {"trunk": ("amp_nmirr", "D2")},
        ],
        "schematic": "MP2 drain to its NMOS diode load and on to MN4's gate",
    },
    {
        "net": "PN",
        "terminals": [
            {"trunk": ("amp_pmirr", "PN")},
            {"trunk": ("amp_nmirr", "PN")},
        ],
        "schematic": "MN4 drain to the diode-connected MP3 and MP4's gate",
    },
]

#: How many (source endpoint, destination endpoint) pairs one hop will try
#: before giving up. Endpoints are tried nearest-first, so the cap only bites
#: when the near ones are all congested -- which is exactly when a far one is
#: worth the extra search.
HOP_ENDPOINT_PAIRS = 16

#: Detour lanes (um, relative to the straight elbow) the router below tries
#: when a direct elbow would collide with an already-drawn net. Small, ordered
#: outward: the first that clears wins, so a route only detours as far as it
#: must.
DETOUR_OFFSETS_UM = [0.0] + [
    sign * 0.4 * step for step in range(1, 121) for sign in (1.0, -1.0)
]


#: The node that vetoed the most recent rolled-back path, so a hop that never
#: routes can say *what* stopped it instead of only that it failed.
_LAST_BLOCKER: list[str] = []


def _path_rects(
    points: list[tuple[float, float]]
) -> list[tuple[float, float, float, float]]:
    """The met1 rectangles an orthogonal polyline would occupy."""
    half = met1_bus.WIRE_WIDTH_UM / 2.0
    rects: list[tuple[float, float, float, float]] = []
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 != x1 and y0 != y1:
            raise ValueError("path segments must be orthogonal")
        if x0 == x1:
            if y0 == y1:
                continue
            rects.append((x0 - half, min(y0, y1), x0 + half, max(y0, y1)))
        else:
            rects.append((min(x0, x1), y0 - half, max(x0, x1), y0 + half))
    return rects


def _draw_guarded(
    bus: "met1_bus.Met1Bus", net: str, points: list[tuple[float, float]]
) -> bool:
    """Draw an orthogonal met1 polyline, but only if it would not collide.

    Returns True when the path was kept. "Collide" means any new rectangle
    coming within the deck's `met1.space.1` clearance of an already-drawn
    rectangle belonging to a *different* electrical node -- i.e. a drawn short
    or a spacing violation. The check runs on the *proposed* rectangles before
    anything is committed: the router tries thousands of candidate paths per
    hop, and drawing-then-rolling-back each one costs more in index churn than
    the collision test itself.
    """
    rects = _path_rects(points)
    eps = 0.14 - 1e-9
    for ax0, ay0, ax1, ay1 in rects:
        for other in bus.near(ax0, ay0, ax1, ay1, 0.14):
            net_b, bx0, by0, bx1, by1 = bus.met1_rects[other]
            if net_b == net:
                continue
            if ax0 - eps < bx1 and bx0 - eps < ax1 and ay0 - eps < by1 and by0 - eps < ay1:
                _LAST_BLOCKER.clear()
                _LAST_BLOCKER.append(net_b)
                return False
    bus.net(net)
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 == x1:
            bus.vseg(x0, y0, y1)
        else:
            bus.hseg(x0, x1, y0)
    return True


def _connect_path(
    bus: "met1_bus.Met1Bus", net: str, points: list[tuple[float, float]]
) -> dict[str, Any] | None:
    """Try one explicit orthogonal path; return its record, or None if it
    would collide with another node."""
    if not _draw_guarded(bus, net, points):
        return None
    return {"points": [[round(x, 3), round(y, 3)] for x, y in points]}


def _candidate_paths(
    a: tuple[float, float], b: tuple[float, float], offset: float
) -> list[list[tuple[float, float]]]:
    """Every path shape the router tries at one detour depth."""
    (ax, ay), (bx, by) = a, b
    if not offset:
        return [
            [(ax, ay), (bx, ay), (bx, by)],  # horizontal first
            [(ax, ay), (ax, by), (bx, by)],  # vertical first
        ]
    # Z-detours on both an intermediate row and an intermediate column, taken
    # from either end -- a lane that is congested next to the source is often
    # free next to the destination.
    paths = [
        [(ax, ay), (ax, ay + offset), (bx, ay + offset), (bx, by)],
        [(ax, ay), (ax + offset, ay), (ax + offset, by), (bx, by)],
        [(ax, ay), (ax, by + offset), (bx, by + offset), (bx, by)],
        [(ax, ay), (bx + offset, ay), (bx + offset, by), (bx, by)],
    ]
    # Four-segment escapes: leave the source's own column, cross on a free
    # row, drop on a column shifted clear of the destination block's other
    # escape stubs, then come in. The three-segment forms above cannot
    # express "clear of both ends at once", which is what a net crossing a
    # whole 100 um array needs.
    for shift in (1.2, -1.2, 2.4, -2.4, 3.6, -3.6):
        paths = [
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
        ] + paths
    return paths


def _connect_any(
    bus: "met1_bus.Met1Bus",
    net: str,
    pairs: list[tuple[tuple[float, float], tuple[float, float]]],
) -> dict[str, Any] | None:
    """Join any one of `pairs` of met1 points, simplest path first.

    Detour depth is the *outer* loop and the endpoint pair the inner one, so
    a hop that has a straight elbow between some pair of its blocks' escape
    points finds it immediately instead of exhausting the whole detour ladder
    on the nearest pair. That ordering is also what keeps the search
    affordable: only a hop with no simple path anywhere pays for the deep
    lanes.
    """
    for offset in DETOUR_OFFSETS_UM:
        for a, b in pairs:
            for points in _candidate_paths(a, b, offset):
                if _draw_guarded(bus, net, points):
                    return {
                        "detour_um": offset,
                        "from_xy": [round(a[0], 3), round(a[1], 3)],
                        "to_xy": [round(b[0], 3), round(b[1], 3)],
                        "points": [[round(x, 3), round(y, 3)] for x, y in points],
                    }
    return None


def reserve_terminal_vias(
    bus: "met1_bus.Met1Bus",
    reports: dict[str, dict[str, Any]],
    origins: dict[str, dict[str, float]],
) -> None:
    """Contact every fixed device-pad terminal of INTER_BLOCK_MET1 up front.

    These vias sit at coordinates the *generator* chose -- a named resistor
    terminal, not something this flow can move. Every other wire in the cell
    can be re-routed around them, so they are drawn first: an intra-block
    series-chain link that would otherwise land on one now has to detour, and
    the pass ends with no drawn short instead of a rolled-back inter-block
    hop and an orphaned via. (`Met1Bus.via` is idempotent per node, so the
    router re-contacting the same pad later is a no-op.)
    """
    for spec in INTER_BLOCK_MET1:
        for terminal in spec["terminals"]:
            if "port" not in terminal:
                continue
            bid = terminal["block"]
            port = _ports_by_name(reports[bid])[terminal["port"]]
            lane = 0.0
            if "leg" in terminal:
                lane = (terminal["leg"] - 0.5) * (2 * RES_LANE_OFFSET_UM)
            bus.net(spec["net"])
            bus.via(
                float(port["x_um"]) + origins[bid]["x"],
                float(port["y_um"]) + origins[bid]["y"] + lane,
            )


def route_inter_block_nets(
    bus: "met1_bus.Met1Bus",
    reports: dict[str, dict[str, Any]],
    origins: dict[str, dict[str, float]],
    bus_summary: dict[str, Any],
    order: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Draw every INTER_BLOCK_MET1 node on met1 and report what was drawn.

    Terminals are ordered left-to-right and joined as a chain, each hop routed
    by :func:`_connect`. A hop that no candidate path can place without
    colliding is reported `routed: false` rather than drawn -- the flow gates
    on that, so an undrawn node can never be mistaken for a drawn one.
    """
    # Every point outside a block at which an intra-block bus already presents
    # one of its nodes on met1. A `{"trunk": (block, net)}` terminal resolves
    # against this: the bus decides where its own node is reachable, and the
    # router picks whichever of those points is nearest the rest of the net.
    trunks: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for bid, entry in bus_summary.items():
        if entry.get("kind") == "bjt_parallel":
            for record in entry["nets"]:
                # Both ends of the collection trunk: it runs the full width of
                # the array clear of every riser, so either end is an equally
                # valid place for a route to arrive, and offering both saves a
                # net that would otherwise have to cross the whole array to
                # reach the one arbitrarily-chosen end.
                trunks.setdefault((bid, record["net"]), []).extend(
                    [
                        (record["trunk_x1_um"], record["trunk_y_um"]),
                        (record["trunk_x0_um"], record["trunk_y_um"]),
                    ]
                )
        elif entry.get("kind") == "mos_diff_pair":
            for net, points_um in entry["endpoints"].items():
                trunks.setdefault((bid, net), []).extend(
                    (float(x), float(y)) for x, y in points_um
                )

    # A port may terminate at most one node: two nodes contacting the same
    # pad would be a short that neither DRC nor the drawn-short check can
    # see (they would be one net by construction).
    used_ports: set[tuple[str, str]] = set()
    results: list[dict[str, Any]] = []
    specs = {spec["net"]: spec for spec in INTER_BLOCK_MET1}
    sequence = order or [spec["net"] for spec in INTER_BLOCK_MET1]
    for net_name in sequence:
        spec = specs[net_name]
        net = spec["net"]
        points: list[dict[str, Any]] = []
        for terminal in spec["terminals"]:
            if "trunk" in terminal:
                bid, bus_net = terminal["trunk"]
                available = trunks[(bid, bus_net)]
                points.append(
                    {
                        "block": bid,
                        "candidates": [
                            (f"{bid}:{bus_net} trunk", x, y) for x, y in available
                        ],
                        "via": False,
                        "resolve": True,
                    }
                )
                continue
            bid = terminal["block"]
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
                points.append(
                    {
                        "block": bid,
                        "name": f"{bid}.{terminal['port']}",
                        "x": px,
                        "y": py,
                        "escape": (outward, py),
                        "via": True,
                        "fixed": True,
                    }
                )
                used_ports.add((bid, terminal["port"]))
                continue
            raise ValueError(f"net {net}: unrecognised terminal {terminal!r}")

        # Every terminal keeps *all* the points its block presents this node
        # at. They are one conductor inside the block, so a hop may leave (or
        # arrive at) whichever of them clears; committing each terminal to a
        # single point up front throws that freedom away and loses nets to
        # congestion a different escape would have missed entirely.
        resolved: list[dict[str, Any]] = []
        for point in points:
            if "candidates" in point:
                resolved.append(
                    {
                        "block": point["block"],
                        "name": point["candidates"][0][0],
                        "options": [(x, y) for _n, x, y in point["candidates"]],
                        "via": point["via"],
                    }
                )
            else:
                resolved.append(
                    {
                        "block": point["block"],
                        "name": point["name"],
                        "options": [(point["x"], point["y"])],
                        "escape": point.get("escape"),
                        "via": point["via"],
                    }
                )

        bus.net(net)
        for point in resolved:
            if point["via"]:
                for x, y in point["options"]:
                    bus.via(x, y)
        # Draw each escape stub first, so the open-channel router below works
        # from points that are already outside their block.
        for point in resolved:
            if not point.get("escape"):
                continue
            (px, py) = point["options"][0]
            ex, ey = point["escape"]
            if _draw_guarded(bus, net, [(px, py), (ex, ey)]):
                point["options"] = [(ex, ey)]
                point["escaped"] = True

        def _mean_x(point: dict[str, Any]) -> tuple[float, float]:
            return (
                sum(x for x, _y in point["options"]) / len(point["options"]),
                sum(y for _x, y in point["options"]) / len(point["options"]),
            )

        resolved.sort(key=_mean_x)
        hops: list[dict[str, Any]] = []
        routed = True
        for first, second in zip(resolved, resolved[1:]):
            pairs = sorted(
                ((a, b) for a in first["options"] for b in second["options"]),
                key=lambda ab: abs(ab[0][0] - ab[1][0]) + abs(ab[0][1] - ab[1][1]),
            )[:HOP_ENDPOINT_PAIRS]
            hop = _connect_any(bus, net, pairs)
            if hop is None:
                routed = False
                hops.append(
                    {
                        "from": first["name"],
                        "to": second["name"],
                        "routed": False,
                        "blocked_by": _LAST_BLOCKER[0] if _LAST_BLOCKER else None,
                    }
                )
                continue
            hop.update({"from": first["name"], "to": second["name"], "routed": True})
            hops.append(hop)
        # One label per net, on drawn metal, so `klt extract` promotes it as a
        # named top-level pin. Deliberately one and only one: two labels with
        # the same text on two *disconnected* pieces of metal would merge them
        # into one extracted net and manufacture connectivity that was never
        # drawn.
        bus.label(net, *resolved[0]["options"][0])
        results.append(
            {
                "net": net,
                "routed": routed,
                "schematic": spec["schematic"],
                "terminals": [p["name"] for p in resolved],
                "blocks": sorted({p["block"] for p in resolved}),
                "hops": hops,
            }
        )
    return results


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
        print(
            f"  bus pass {len(attempts) + 1}/{ROUTE_ORDER_PASSES}...",
            file=sys.stderr,
            flush=True,
        )
        bus = met1_bus.Met1Bus()
        reserve_terminal_vias(bus, reports, origins)
        summary = {}
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
            elif spec["kind"] == "mos_diff_pair":
                summary[bid] = mos_bus.bus_diff_pair(
                    bus, bid, reports[bid], origins[bid], spec
                )
            else:  # pragma: no cover -- BLOCKS is a literal table
                raise ValueError(f"unknown bus kind {spec['kind']!r} on block {bid}")

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
    summary["_inter_block"] = routes
    summary["_route_order_attempts"] = attempts
    summary["_route_order_used"] = chosen_order

    # --- drawn-short / spacing proof --------------------------------------
    # Every met1 rectangle carries the electrical node it belongs to, so two
    # nodes' wires touching is detectable *here*, not left to be discovered
    # as a mystery LVS merge. Empty is the only acceptable result, and the
    # flow's exit status gates on it.
    summary["_conflicts"] = conflicts

    # --- poly-spacing proof ------------------------------------------------
    # The curated DRC deck models `poly.width.1` but no poly *spacing* rule,
    # so `klt drc` cannot see two self-drawn gate extensions placed too close
    # together. sky130's own `poly.2` minimum is 0.21 um; applying it here to
    # the geometry this flow adds is what keeps the gate-contact workaround
    # from quietly shorting two gate nets in a deck's blind spot.
    summary["_poly_conflicts"] = bus.poly_conflicts()

    # --- per-node connectivity proof ---------------------------------------
    # A node drawn as two pieces of metal that never touch is not a connected
    # node, and nothing downstream reports it: `klt extract` just sees two
    # anonymous nets. Counting connected components per node is the matching
    # safety net to the drawn-short check above. Nodes that legitimately close
    # through li1 rather than met1 -- a diode-connected gate bonded straight
    # to its own pad, a guard ring tapped under its own lane -- are the ones
    # this count cannot see, and they are named in the record instead.
    summary["_components"] = {
        net: count for net, count in sorted(bus.components().items()) if count > 1
    }

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
#: Every schematic node this flow draws is labelled on its own drawn met1 by
#: `route_inter_block_nets`, so `klt extract` promotes it as a named
#: top-level pin without a second naming mechanism. PR #64/#65's
#: `CORE_PIN_LABELS` table -- which named *gate ports* directly, because a
#: gate could not be wired to anything -- is gone with the gap that forced
#: it: naming an already-named net a second time would hand the extractor
#: two names for one node. `pins[]` now carries only the trim-ladder taps,
#: which are genuine layout-only probe points with no schematic counterpart.


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
        "schematic": "amp output (MP4/MN3 drains, labelled AOUT in the "
        "layout) + MPOUT/MPAMP gates -- one node in the schematic",
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
        "blocks": [
            "amp_nload",
            "amp_nmirr",
            "pnp_ctat",
            "pnp_ptat",
            "res_r2",
            "res_trim",
            "res_r1",
        ],
        "hops": ["VSS"],
        "schematic": "ground trunk: MN1-MN4 sources + both PNPs' base/"
        "collector ties + all three res_high_po bulk terminals (R2A/R2B/R1 "
        "each tie their bulk to VSS -- design/bandgap_core.sch r2ab/r2bb/"
        "r1b). The layout can only draw the 2-terminal res_generic_po "
        "flavour (RES_FLAVOR_NOTE), so those three blocks have no bulk "
        "terminal to reach; this table states the schematic's requirement "
        "rather than quietly dropping it",
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
    touched: dict[str, set[str]] = {}
    for route in routes:
        if not route.get("routed"):
            continue
        touched.setdefault(route["net"], set()).update(route.get("blocks", []))
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


def compose_inner(
    klt: str,
    out_dir: Path,
    pdk: str,
    cell_name: str,
    block_ids: list[str],
    reports: dict[str, dict[str, Any]],
    origins: dict[str, dict[str, float]],
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
    post-layout testbench (issue #16) without claiming any connectivity. It
    now carries only the trim-ladder taps: every schematic node is named on
    its own drawn met1 by the router, and PR #64/#65's gate-port pin labels
    are gone with the gap that forced them.

    Returns `(compose_response, pins)`.
    """
    pins: list[dict[str, Any]] = list(trim_tap_pins(reports))

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
        klt, out_dir, pdk, inner_cell, inner_ids, inner_reports, inner_origins
    )
    met1_routes = bus_summary["_inter_block"]
    met1_conflicts = bus_summary["_conflicts"]
    poly_conflicts = bus_summary["_poly_conflicts"]
    split_nodes = bus_summary["_components"]

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
        "resistor": device_counts.get("res_generic_po", 0) > 0,
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
        "| 5 | Blocking `klt` gaps filed as friction | MET | "
        "2AMLogic/klayout-tools#461 (MOS gate poly has no contact landing "
        "area) is worked around here rather than waited on -- see "
        "MOS_GATE_NOTE -- and #484 records the second half of the same gap "
        "(`diff_pair`'s fixed ring padding / row pitch leave room for one "
        "gate contact row per side). Still open and still costing "
        "mismatches: #462 (dummy-device marker is MOS-gate-only, not "
        "bipolar/resistor), #463 (sky130 `res_array` cannot draw non-default "
        "resistor flavours), #454 (no metal2/via role, so every wire here is "
        "hand-drawn) |"
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
        "Each matched array's units are tied into the node the schematic "
        "says they form, on met1 over mcon -- the sky130 extraction deck's "
        "own second conductor and via (`metals = (li1, met1)`, "
        "`vias = (mcon,)`). The li1 router cannot express these at all "
        "(2AMLogic/klayout-tools#433 and its merged fix #439, which made the "
        "failure visible rather than expressible), so this flow draws them "
        "itself from each block's reported `ports[]`. This is what turns a "
        "108-segment ladder into two real series resistors and an 8-unit PNP "
        "array into one real m=8 device."
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
        elif entry["kind"] == "bjt_parallel":
            detail = "; ".join(
                f"`{r['net']}` = {r['pads']} pads on {r['columns']} columns"
                for r in entry["nets"]
            )
            a(f"| `{bid}` | parallel unit bus | {detail} |")
        else:
            gate_styles: dict[str, int] = {}
            for record in entry["gate_contacts"]:
                gate_styles[record["style"]] = gate_styles.get(record["style"], 0) + 1
            detail = (
                f"{entry['units']} unit devices on "
                f"{len(entry['lanes'])} lanes "
                f"({', '.join('`' + n + '`' for n in entry['lanes'])}); "
                f"{len(entry['gate_contacts'])} self-drawn gate contacts ("
                + ", ".join(f"{count} {style}" for style, count in sorted(gate_styles.items()))
                + ")"
            )
            if entry.get("ring"):
                detail += f"; guard ring tied to `{entry['ring']['net']}`"
            a(f"| `{bid}` | matched-pair lane bus | {detail} |")
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
        f"Poly-spacing proof: **{len(poly_conflicts)}** pairs of self-drawn "
        "gate-contact poly extensions belonging to different nodes come "
        "within sky130's own 0.21 um `poly.2` minimum poly spacing -- a rule "
        "the curated DRC deck does not model, so `klt drc` alone could not "
        "have caught one. The flow fails on any nonzero count."
    )
    a("")
    a(
        "Per-node connectivity proof: every node's drawn met1 is one "
        "connected conductor, except the "
        f"{len(split_nodes)} listed here, which close through li1 or are "
        f"joined by an inter-block hop that did not route: "
        f"`{json.dumps(split_nodes)}`."
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
        "blocks the schematic says it reaches. A node scored `partial` is "
        "drawn between some of its blocks and named, so it is addressable, "
        "but it is not connected -- every remaining gap is a hop this flow's "
        "own met1 router could not place without a drawn short, not a node "
        "it is unable to express."
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
        "that count is short. `VSS`'s block list includes the three resistor "
        "blocks because the *schematic* uses `res_high_po`, a 3-terminal "
        "device whose bulk ties to VSS; the layout can only draw the "
        "2-terminal `res_generic_po` (RES_FLAVOR_NOTE), so those three have "
        "no bulk terminal to reach and this table states the schematic\'s "
        "requirement rather than quietly dropping it."
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
        f"drawn-short conflicts={len(met1_conflicts)} |"
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
    a(f"| `res_generic_po` | {device_counts.get('res_generic_po', 0)} | 67 |")
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
    a("The residual gap has five disclosed causes, none of them a topology "
      "error in either netlist:")
    a("")
    a(
        f"1. **Inter-block nets still unrouted:** {', '.join('`' + n + '`' for n in unrouted) or 'none'}. "
        "Each is a schematic node whose terminals this flow's met1 router "
        "could not join without a drawn short, so it is left open rather "
        "than certified. See the inter-block table above for which hop "
        "failed and what blocked it. This is now the dominant term: unlike "
        "the previous increment's blockers it is a *routing-quality* limit "
        "of this repo's own hand-written router, not an upstream tool gap."
    )
    a(
        f"2. **Dummy devices cannot be declared.** {DUMMY_DEVICE_NOTE}"
    )
    a(
        f"3. **The resistor flavour cannot be drawn.** {RES_FLAVOR_NOTE} The "
        "reference states the schematic's device; the layout draws the only "
        "flavour the generator can."
    )
    a(
        "4. **`MMCC`, the amp's compensation cap, is in the reference but "
        "deliberately not drawn in this layout** (see the Blocks note "
        "above), so one reference device has no layout counterpart by "
        "construction."
    )
    a(
        f"5. **The gate-contact workaround is this flow's, not the tool's.** "
        f"{MOS_GATE_NOTE} {MOS_BAND_NOTE}"
    )
    a("")
    a(
        "None of the five is worked around by editing the reference netlist. "
        "`reference.spice` states design/bandgap_core.sch; rewriting it to "
        "enumerate the layout's own shortfalls would make LVS compare the "
        "layout against itself, which is not evidence."
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
        "xschem-derived reference netlist. See the five disclosed causes "
        "above; the largest is this flow's own router leaving "
        f"{len(unrouted)} declared net(s) undrawn."
    )
    a(
        f"- **Not fully inter-block routed either.** {len(fully_drawn)}/"
        f"{len(coverage)} schematic inter-block nets are "
        "joined across every block they reach. The rest are drawn in part "
        "and named, so they are addressable, but they are not connected."
    )
    a(
        "- **The gate contacts are drawn by this flow, not by `klt gen`.** "
        "Every MOS gate here is contacted through a poly extension this "
        "repo draws past the active edge from the generator's own reported "
        "gate port, because no sky130 MOS generator leaves one "
        "(2AMLogic/klayout-tools#461, still open). The extension is DRC-"
        "clean under the curated deck and is what every real PDK draws, but "
        "it is a workaround: its size, direction and the room it has to fit "
        "in are decided here, per block, not by the tool."
    )
    a(
        "- **Not every matched device's gates could be bussed the same "
        "way.** `diff_pair`'s guard-ring padding and inter-row spacing are "
        "fixed constants with no parameter, and the band they leave holds "
        "exactly one gate contact row per side. This circuit's five matched "
        "groups fit (one inboard gate net, one outboard, diode-connected "
        "gates bonded locally on li1) -- a group needing two independent "
        "non-diode gate nets on a taller stack would not."
    )
    a(
        "- **The PNP devices are drawn geometry recognised by the deck, not "
        "vendor `pnp_05v5` cell instances.** `klt gen bjt_array` draws a "
        "matching-faithful floorplan from base layers by design, and since "
        "upstream klayout-tools#440 it draws sky130's bipolar marker and "
        "per-unit well tap itself -- which makes the geometry *extract* as "
        "`pnp`, not a SPICE-model-exact device."
    )
    a(
        "- **Array dummies are counted as real devices.** The `pnp` and "
        "`res_generic_po` counts above include each array's dummy edge "
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
    # poly-spacing check, for the same reason one layer down -- the curated
    # deck has no poly spacing rule, so nothing else would catch it.
    ok = (
        drc_clean
        and within_budget
        and full_scale_ladder
        and all_classes
        and pin_count > 0
        and not met1_conflicts
        and not poly_conflicts
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
