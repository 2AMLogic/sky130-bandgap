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
import re
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
    "once, in MOS_HALVES, and every block's bus spec resolves through it. "
    "Without that binding the centroid-nearest pick is free to hand two "
    "different schematic nodes two fingers of the same physical transistor, "
    "which is a topology error that neither DRC nor the drawn-short check "
    "can see -- both terminals are legal, well-separated metal."
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
                "MPOUT": {"S": "VDD", "D": "VOUT", "G": "GDRV"},
                "MPAMP": {"S": "VDD", "D": "TAIL", "G": "GDRV"},
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
                "MP1": {"S": "TAIL", "D": "D1", "G": "VB"},
                "MP2": {"S": "TAIL", "D": "D2", "G": "VA"},
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
                "MN1": {"S": "D1", "D": "VSS", "G": "D1"},
                "MN2": {"S": "D2", "D": "VSS", "G": "D2"},
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
                "MP3": {"S": "VDD", "D": "PN", "G": "PN"},
                "MP4": {"S": "VDD", "D": "GDRV", "G": "PN"},
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
                "MN3": {"S": "VSS", "D": "GDRV", "G": "D1"},
                "MN4": {"S": "VSS", "D": "PN", "G": "D2"},
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


#: Which `diff_pair` port family is which schematic transistor. Both halves of
#: a pair are geometrically interchangeable, so this binding is a
#: *declaration* -- but it has to be made once and obeyed everywhere, or two
#: nodes end up on one transistor (MOS_HALF_NOTE).
#:
#: PR #67 introduced this table when routes picked their pads independently by
#: centroid distance, and it also carried a `drain_suffix`/`facing` mapping
#: because a route had to name one specific pad family. Neither is needed now:
#: `layout/bin/mos_bus.py` wires *both* the source and the drain of *both*
#: halves from the generator's own `<device>_<unit>_<S|D|G>` port names, so
#: there is no free choice of which pad a node lands on left to get wrong. The
#: binding itself is still load-bearing, and is now a stronger one -- every
#: block's bus spec below states its nets per *schematic device*
#: (`MPOUT`/`MP1`/...), and :func:`resolve_bus_devices` turns that into the
#: generator's half labels through this table. A device the table does not
#: name, or a half it names twice, is a hard error rather than a silently
#: mis-bound transistor.
#:
#: Which letter goes to which device is arbitrary and stated here once; the
#: assignment below is the one the drawn evidence was measured with.
MOS_HALVES: dict[str, dict[str, str]] = {
    "core_mirror": {"MPOUT": "M1", "MPAMP": "M2"},
    "amp_input_pair": {"MP1": "Q1", "MP2": "Q2"},
    "amp_nload": {"MN1": "M1", "MN2": "M2"},
    "amp_pmirr": {"MP3": "M1", "MP4": "M2"},
    "amp_nmirr": {"MN3": "M1", "MN4": "M2"},
}


def resolve_bus_devices(block: str, spec: dict[str, Any]) -> dict[str, Any]:
    """One `mos_diff_pair` bus spec with its schematic device names replaced by
    the generator's own port-family labels, via MOS_HALVES.

    Keeping BLOCKS in schematic terms and translating here is what makes the
    binding checkable: `mos_bus.bus_diff_pair` already rejects a device set
    that does not match what the generator reported, so a typo in either table
    stops the flow instead of quietly bussing MP1's nets onto MP2.
    """
    halves = MOS_HALVES[block]
    named = spec["devices"]
    missing = set(named) - set(halves)
    if missing:
        raise KeyError(
            f"block {block}: bus spec names device(s) {sorted(missing)} that "
            "MOS_HALVES does not bind to a port family"
        )
    if len({halves[dev] for dev in named}) != len(named):
        raise ValueError(
            f"block {block}: MOS_HALVES binds two of {sorted(named)} to the "
            "same port family, which would put two schematic devices on one "
            "transistor (MOS_HALF_NOTE)"
        )
    resolved = dict(spec)
    resolved["devices"] = {halves[dev]: terms for dev, terms in named.items()}
    resolved["device_labels"] = {halves[dev]: dev for dev in named}
    return resolved


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
        "mirror's gate drive -- one node in the schematic. PR #67 drew the "
        "two drain ends only, and named the gate end `GDRV_GATE` because a "
        "gate could not be contacted; both ends are one drawn conductor now "
        "(the `core_mirror` terminal is its gate lane), so the node needs no "
        "second name",
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


def free_channels(
    reports: dict[str, dict[str, Any]],
    origins: dict[str, dict[str, float]],
) -> dict[str, list[float]]:
    """The mid-lines of the floorplan's empty vertical and horizontal channels.

    met1 sits above every block's li1, so a *block* is not an obstacle to this
    router -- only another node's already-drawn met1 is. The gaps between
    blocks are still the right lanes to prefer, though, because that is where
    the previously-drawn nets are sparsest: BLOCK_MARGIN_UM/ROW_MARGIN_UM
    exist precisely to leave them empty.

    Returning mid-lines (rather than a grid) keeps the candidate set small
    enough to try exhaustively per hop: this floorplan has four vertical
    channels and two horizontal ones, so a hop gets a handful of "go out to a
    channel, along a band, and back in" paths instead of the thousands a
    blind offset sweep would need to stumble onto the same route.
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
        intervals.sort()
        merged: list[list[float]] = []
        for lo, hi in intervals:
            if merged and lo <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi])
        mids = [
            round((merged[i][1] + merged[i + 1][0]) / 2.0, 3)
            for i in range(len(merged) - 1)
        ]
        # The margins outside the content are lanes too, and are the only way
        # out for a terminal boxed in at a corner of the floorplan.
        margin = RING_MARGIN_UM / 2.0
        mids.append(round(merged[0][0] - margin, 3))
        mids.append(round(merged[-1][1] + margin, 3))
        lanes[axis] = mids
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
    paths: list[list[tuple[float, float]]] = []
    for cx in channels.get("x", []):
        for cy in channels.get("y", []):
            paths.append([(ax, ay), (cx, ay), (cx, cy), (bx, cy), (bx, by)])
            paths.append([(ax, ay), (ax, cy), (cx, cy), (cx, by), (bx, by)])
    # Sort by length: a channel pair that happens to sit near both ends is a
    # short detour and should be preferred over one that crosses the cell.
    paths.sort(
        key=lambda p: sum(
            abs(q[0] - r[0]) + abs(q[1] - r[1]) for q, r in zip(p, p[1:])
        )
    )
    return paths


def _connect_any(
    bus: "met1_bus.Met1Bus",
    net: str,
    pairs: list[tuple[tuple[float, float], tuple[float, float]]],
    channels: dict[str, list[float]] | None = None,
) -> dict[str, Any] | None:
    """Join any one of `pairs` of met1 points, simplest path first.

    Search order is by path *shape*, not by endpoint pair, and strictly
    cheapest-shape-first:

    1. a plain elbow, for every endpoint pair -- so a hop that has one
       anywhere finds it immediately instead of exhausting the whole detour
       ladder on the nearest pair;
    2. the Z and four-segment detours, offset by offset, pair inside offset;
    3. and only if all of that fails, a corridor through the floorplan's free
       channels.

    The channel stage is deliberately last even though PR #67 (which had one
    escape point per terminal, so stage 1 was a single attempt) put it
    second. A channel path crosses the whole cell; taking one in preference
    to a 0.4 um jog spends a corridor several later nets need. Measured: with
    the channel stage second, `VDD` lost its route entirely and the run
    scored 7/12 schematic nets against 8/12 with it last.

    The two ingredients are what PR #67 and this branch each contributed:
    multiple endpoints per terminal (a bussed block presents its node at four
    or six points, so "which end do I leave from" is a real choice) and the
    channel lanes (a route across a 100 um array needs a corridor no elbow or
    single-jog Z can express).
    """
    for a, b in pairs:
        for points in _candidate_paths(a, b, 0.0):
            if _draw_guarded(bus, net, points):
                return _hop_record(a, b, points, detour_um=0.0)
    for offset in DETOUR_OFFSETS_UM:
        if not offset:
            continue  # already tried, for every pair, above
        for a, b in pairs:
            for points in _candidate_paths(a, b, offset):
                if _draw_guarded(bus, net, points):
                    return _hop_record(a, b, points, detour_um=offset)
    for a, b in pairs:
        for points in _channel_paths(a, b, channels or {}):
            if _draw_guarded(bus, net, points):
                return _hop_record(a, b, points, detour_um=None, via_channel=True)
    return None


def _hop_record(
    a: tuple[float, float],
    b: tuple[float, float],
    points: list[tuple[float, float]],
    *,
    detour_um: float | None,
    via_channel: bool = False,
) -> dict[str, Any]:
    """One drawn hop, as it appears in `bus-summary.json`.

    Records which endpoint of each terminal the hop actually left from and
    arrived at: with several escape points per terminal, "the net is drawn"
    is only checkable evidence if the record says *where*.
    """
    record: dict[str, Any] = {
        "detour_um": detour_um,
        "from_xy": [round(a[0], 3), round(a[1], 3)],
        "to_xy": [round(b[0], 3), round(b[1], 3)],
        "points": [[round(x, 3), round(y, 3)] for x, y in points],
    }
    if via_channel:
        record["via_channel"] = True
    return record


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

    Terminals are joined as an open chain, each hop routed by
    :func:`_connect_any`. A hop that no candidate path can place without
    colliding is reported `routed: false` rather than drawn -- the flow gates
    on that, so an undrawn node can never be mistaken for a drawn one.

    Two independent degrees of freedom are searched, because a supply trunk
    that has to visit three rows needs both: the *order* the terminals are
    visited in (:func:`_chain_orders`) and, per hop, which of each terminal's
    escape points to leave from and arrive at.
    """
    channels = free_channels(reports, origins)
    # Every point outside a block at which an intra-block bus already presents
    # one of its nodes on met1. A `{"trunk": (block, net)}` terminal resolves
    # against this: the bus decides where its own node is reachable, and the
    # router picks whichever of those points clears.
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
            raise ValueError(f"net {net}: unrecognised terminal {terminal!r}")

        # Every terminal keeps *all* the points its block presents this node
        # at. They are one conductor inside the block, so a hop may leave (or
        # arrive at) whichever of them clears; committing each terminal to a
        # single point up front throws that freedom away and loses nets to
        # congestion a different escape would have missed entirely.
        #
        # `pads` is the *unrouted* truth and never changes; `options` is the
        # working copy a drawing attempt may narrow (an escape stub moves a
        # fixed pad outside its block). Keeping them apart is what lets a
        # retried chain order start from the pads again rather than from
        # wherever the previous attempt left the terminal.
        resolved: list[dict[str, Any]] = []
        for point in points:
            if "candidates" in point:
                resolved.append(
                    {
                        "block": point["block"],
                        "name": point["candidates"][0][0],
                        "pads": [(x, y) for _n, x, y in point["candidates"]],
                        "escape": None,
                        "via": point["via"],
                    }
                )
            else:
                resolved.append(
                    {
                        "block": point["block"],
                        "name": point["name"],
                        "pads": [(point["x"], point["y"])],
                        "escape": point.get("escape"),
                        "via": point["via"],
                    }
                )

        # The terminals of one node are joined as an open chain, so the order
        # they are visited in *is* the wire plan: a chain that zig-zags across
        # the floorplan asks the open-channel router for corridors that a
        # chain visiting the same terminals in a friendlier order never needs.
        # Sorting by x is a good default and was the only plan this router had;
        # it is also what left the four-terminal `VSS` trunk permanently one
        # hop short, because it made the chain start at the bottom-left PNP and
        # jump straight to the top-right NMOS mirror. Try a few orders and keep
        # the first that routes completely, falling back to the best partial.
        # Only a net whose default order fails pays for the extra attempts.
        best_score: tuple[int, int] | None = None
        best_plan = resolved
        hops: list[dict[str, Any]] = []
        routed = False
        for plan in _chain_orders(resolved):
            mark = bus.mark()
            hops, routed = _draw_chain(bus, net, plan, channels)
            score = (0 if routed else 1, sum(1 for h in hops if not h["routed"]))
            if routed:
                best_plan, best_score = plan, score
                break  # geometry for the winning plan stays on the bus
            bus.restore(mark)
            if best_score is None or score < best_score:
                best_plan, best_score = plan, score
        if not routed:
            # Every plan was rolled back. Redraw the best one so the geometry
            # on the bus is the geometry the report below describes.
            hops, routed = _draw_chain(bus, net, best_plan, channels)
        resolved = best_plan
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


def _pad_centroid(point: dict[str, Any]) -> tuple[float, float]:
    """The mean of one terminal's escape points, for ordering purposes only."""
    pads = point["pads"]
    return (
        sum(x for x, _y in pads) / len(pads),
        sum(y for _x, y in pads) / len(pads),
    )


def _chain_orders(points: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Candidate visit orders for one node's terminals, best-guess first.

    Column-major and row-major sorts cover the two trunk shapes this floorplan
    actually has; the nearest-neighbour chains (one per possible starting
    terminal) cover the rest, and are what turns a supply trunk that has to
    visit three rows into a sequence of short hops. Duplicates are dropped so
    a two-terminal net still costs exactly one attempt.

    A terminal is a *set* of escape points, not one point, so every ordering
    key below is taken at the centroid of its pads. That is only a heuristic
    for the ordering; which individual endpoint each hop actually uses is
    decided later, per hop, by :func:`_connect_any`.
    """
    orders: list[list[dict[str, Any]]] = [
        sorted(points, key=lambda p: _pad_centroid(p)),
        sorted(points, key=lambda p: _pad_centroid(p)[::-1]),
    ]
    for start in range(len(points)):
        remaining = list(points)
        chain = [remaining.pop(start)]
        while remaining:
            hx, hy = _pad_centroid(chain[-1])
            nxt = min(
                remaining,
                key=lambda p: abs(_pad_centroid(p)[0] - hx)
                + abs(_pad_centroid(p)[1] - hy),
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

    Every point's `options` is reset from its immutable `pads` before drawing,
    so a plan can be retried after an earlier one narrowed a terminal onto its
    escape stub.
    """
    bus.net(net)
    for point in plan:
        point["options"] = list(point["pads"])
        if point["via"]:
            for x, y in point["options"]:
                bus.via(x, y)
    # Draw each escape stub first, so the open-channel router below works
    # from points that are already outside their block.
    for point in plan:
        point.pop("escaped", None)
        if not point.get("escape"):
            continue
        px, py = point["options"][0]
        ex, ey = point["escape"]
        if _draw_guarded(bus, net, [(px, py), (ex, ey)]):
            point["options"] = [(ex, ey)]
            point["escaped"] = True

    hops: list[dict[str, Any]] = []
    routed = True
    for first, second in zip(plan, plan[1:]):
        # Nearest endpoint pairs first, capped: the cap only bites when the
        # near ones are all congested, which is exactly when a far one is
        # worth the extra search.
        pairs = sorted(
            ((a, b) for a in first["options"] for b in second["options"]),
            key=lambda ab: abs(ab[0][0] - ab[1][0]) + abs(ab[0][1] - ab[1][1]),
        )[:HOP_ENDPOINT_PAIRS]
        hop = _connect_any(bus, net, pairs, channels)
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
    return hops, routed


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
                    bus, bid, reports[bid], origins[bid],
                    resolve_bus_devices(bid, spec),
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
#: Retiring it is also what keeps `assert_no_merged_pin_names` honest:
#: with `GDRV` now one drawn conductor from MP4/MN3's drains to MPOUT and
#: MPAMP's gates, a `GDRV_GATE` pin label on that same conductor would be a
#: *second* name for one net -- the very `A|B` collision PR #67's gate was
#: added to catch. The gate stays; what it guards is now unreachable by
#: construction rather than merely avoided.


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
        "node in the schematic, and one drawn conductor here: the gate end is "
        "reached through the self-drawn gate contacts (MOS_GATE_NOTE), not "
        "left as a separate `GDRV_GATE` label as in PR #67",
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


def flow_gate(
    *,
    drc_clean: bool,
    within_budget: bool,
    full_scale_ladder: bool,
    all_classes: bool,
    pin_count: int,
    met1_conflicts: list[Any],
    merged_pin_names: list[str],
    poly_conflicts: list[Any],
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
    `no_drawn_shorts`, `no_merged_pin_names` and `no_poly_shorts` -- are this
    flow's own honesty checks: each catches a way the layout could claim
    connectivity the schematic does not contain (through met1, through a pin
    label, and through the poly extensions this flow draws itself for the
    gate contacts), and none of the three is visible to DRC. The last is the
    newest and the least obvious: the curated sky130 deck models
    `poly.width.1` but no poly *spacing* rule, so two self-drawn gate
    extensions of different nodes could sit on top of each other and `klt drc`
    would still report clean.
    """
    return {
        "drc_clean": drc_clean,
        "within_budget": within_budget,
        "full_scale_ladder": full_scale_ladder,
        "device_classes_present": all_classes,
        "pins_promoted": pin_count > 0,
        "no_drawn_shorts": not met1_conflicts,
        "no_merged_pin_names": not merged_pin_names,
        "no_poly_shorts": not poly_conflicts,
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
    post-layout testbench (issue #16) without claiming any connectivity. It
    now carries only the trim-ladder taps: every schematic node is named on
    its own drawn met1 by the router, and PR #64/#65's gate-port pin labels
    are gone with the gap that forced them.

    The taps that remain are still filtered through :func:`routed_ports`,
    PR #67's prevention half of the label-collision gate. A `pins[]` entry
    labels a *pad*, so a tap label landing on a pad some node's met1 already
    contacts would rename that node rather than name the tap -- which is how
    the `TRIM_A_CODE_MINUS16|VA` collisions in record `20260804-012421-1a97bf5`
    were drawn. Fewer labels makes that less likely, not impossible, so the
    claimed-pad set stays.

    Returns `(compose_response, pins)`.
    """
    claimed = routed_ports(bus_summary)
    pins: list[dict[str, Any]] = [
        pin
        for pin in trim_tap_pins(reports)
        if (pin["block"], pin["port"]) not in claimed
    ]

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
        "hand-drawn), and #470 (a net carrying two different labels is "
        "emitted as `A|B` with no diagnostic from either `klt extract` or "
        "`klt lvs`) -- the last of which this flow still gates on itself, "
        "see assert_no_merged_pin_names |"
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
        "Record `20260804-012421-1a97bf5` shows what happens when the choice "
        "is never made: every net picked whichever candidate pad sat nearest "
        "its own centroid, independently, so `PN` took a finger of the same "
        "amp_pmirr half the `AOUT` label named (MP3's drain and MP4's drain "
        "were one physical transistor), and amp_nload's `D1` route and "
        "`D1_GATE` label disagreed about which half is MN1. Neither is "
        "visible to DRC or to the drawn-short check -- every terminal "
        "involved is legal, well-separated metal."
    )
    a("")
    a("")
    a(MOS_HALF_NOTE)
    a("")
    a(
        "The binding is made once, in `MOS_HALVES`; the half-to-device column "
        "below is read back out of `bus-summary.json`'s `device_labels`, i.e. "
        "out of the binding the bus actually drew with, and the net columns "
        "are that block's bus spec. Every source, drain and gate of both "
        "halves is bussed from the generator's own reported ports, so there "
        "is no per-net pad choice left to get wrong."
    )
    a("")
    a("| block | port family | schematic device | source net | drain net | gate net |")
    a("| --- | --- | --- | --- | --- | --- |")
    for bid, entry in bus_summary.items():
        if not isinstance(entry, dict) or entry.get("kind") != "mos_diff_pair":
            continue
        for half, device in sorted(entry["device_labels"].items()):
            terms = entry["devices_nets"][half]
            a(
                f"| `{bid}` | `{half}_*` | `{device}` | `{terms['S']}` | "
                f"`{terms['D']}` | `{terms['G']}` |"
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
        "the amp tail are one node. PR #67 fixed that by making the pin "
        "selector and the router share one claimed-pad set; this increment "
        "goes further and retires the gate-port pin labels entirely, because "
        "every schematic node is now named on its own drawn met1. The set is "
        "still shared (the trim taps still go through it) and this line is "
        "still the proof. Filed upstream as 2AMLogic/klayout-tools#470 (the "
        "silence, not the collision, is the tool gap)."
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
        "but it is not connected. The gaps have two causes, stated per row "
        "below rather than collapsed into one sentence: a hop this flow's own "
        "met1 router could not place without a drawn short, and -- for "
        "`VSS`'s three resistor blocks only -- the resistor-flavour gap "
        "(RES_FLAVOR_NOTE), where the drawn `res_generic_po` has no bulk "
        "terminal to reach at all. The MOS-gate cause that dominated PR "
        "#64/#65/#67 is gone: every gate is contacted here (MOS_GATE_NOTE)."
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
        f"{len(unrouted)} declared net(s) undrawn. It is no longer the "
        "gate-contact gap: PR #67's record could say `devices.matched` was 0 "
        "and would stay 0 however much more metal was drawn, because no split "
        "group could collapse into the m=N device the schematic states. Every "
        "gate is contacted here, so that ceiling is lifted and what remains "
        "is measured, not structural."
    )
    a(
        f"- **Not fully inter-block routed either.** {len(fully_drawn)}/"
        f"{len(coverage)} schematic inter-block nets are "
        "joined across every block they reach. The rest are *partial*, not "
        "absent: each is drawn between the blocks whose terminals are "
        "reachable and stops at the one that is not, which the coverage table "
        "names per row. `VSS` stops at the resistor blocks' missing bulk "
        "terminal (RES_FLAVOR_NOTE); the others stop at a hop this flow's own "
        "router could not place without a drawn short."
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
    # exactly the false evidence this flow must never produce. So are the
    # other two honesty checks: the label-collision check, which catches the
    # same failure arriving through a pad rather than through metal (see
    # assert_no_merged_pin_names), and the poly-spacing check, which catches
    # it one layer down -- the curated deck models no poly spacing rule, so
    # nothing else would see two self-drawn gate extensions shorting.
    gate = flow_gate(
        drc_clean=drc_clean,
        within_budget=within_budget,
        full_scale_ladder=full_scale_ladder,
        all_classes=all_classes,
        pin_count=pin_count,
        met1_conflicts=met1_conflicts,
        merged_pin_names=merged_pin_names,
        poly_conflicts=poly_conflicts,
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
