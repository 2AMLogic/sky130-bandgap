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
2. **PNP devices actually extract.** `klt gen bjt_array` draws a DRC-clean
   matching floorplan but never draws the sky130 bipolar device-recognition
   marker (`pnp.drawing` 82/44) its own `klt extract` deck keys off, nor an
   nwell tap tying each unit's base pad to the well -- so a `bjt_array`
   output extracts as *zero* devices. This script composes a small
   `klt draw`-generated recognition overlay (marker + nwell tap, one pair
   per functional unit, positioned from the generator's own reported
   `ports[]`) over each PNP array, which takes the same geometry from
   `device_count: 0` to the schematic's 8 `pnp` devices per array. See
   PNP_OVERLAY_NOTE below and the friction issue it names.
3. **Real routed metal and promoted top-level pins.** `klt gen-compose`
   grew two-pin point-to-point routing plus `connectivity[]` net labels and
   `pins[]` single-port pin promotion, so the composed cell now carries
   drawn inter-block wire and survives `klt extract`'s pin promotion with
   named pins instead of `pin_count: 0`.
4. **`klt extract` + `klt lvs` are run and recorded**, instead of being
   skipped as not-yet-meaningful.

What this script does NOT claim -- read record.md's own "What this record
does NOT claim" section for the authoritative, measured version:

- **Not LVS-clean.** Intra-block bussing (tying an array's 8 PNP emitters,
  or a ladder's 108 unit resistors, into one node) is not expressible with
  today's router: sky130's generator/router layer-role table exposes exactly
  one routing metal (`li1`), the same layer every generator draws its own
  device pads on, and the router is explicitly not aware of a block's
  internal geometry. Any wire crossing a block therefore shorts to every pad
  it passes over. See ROUTING_LAYER_NOTE below.
- Consequently the flow routes only the inter-block nets the router itself
  certifies as obstacle-free, and the extracted netlist keeps each block's
  units as separate devices.
- **Not fully inter-block routed.** `klt gen-compose` routes 2-pin nets only,
  and only between blocks adjacent across an empty channel, so a supply trunk
  can reach at most the blocks a chain of such hops can string together and a
  non-adjacent pair (MPOUT's drain and the R2 ladder's tops; the amp's output
  and the mirror gates) cannot be joined at all. record.md's "Schematic
  inter-block nets" table scores every schematic inter-block node as drawn /
  partial / labelled-only against SCHEMATIC_INTER_BLOCK_NETS below -- i.e.
  against design/bandgap_core.sch's node list, not against this script's own
  `connectivity[]` declaration -- and criterion 1 is PARTIAL while any node
  is short.

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

# ---------------------------------------------------------------------------
# Friction notes (upstream tool gaps this script works around or is limited
# by). Each is filed at 2AMLogic/klayout-tools per CLAUDE.md's protocol as a
# generic tool-gap description; the design-specific consequence lives here and
# in layout/matching-plan.md, never in that tracker.
# ---------------------------------------------------------------------------
PNP_OVERLAY_NOTE = (
    "`klt gen bjt_array` draws no bipolar device-recognition marker on "
    "sky130 (the role table's `bjt_mark` entry is None) and no well tap for "
    "the unit base pads, so its output extracts as device_count: 0 even "
    "though the same tool's sky130 extraction deck declares a `pnp` entry "
    "keyed on marker 82/44 with base = nwell. This flow composes a "
    "`klt draw` recognition overlay (82/44 marker per functional emitter "
    "pad, 65/44 nwell tap per base pad) to close that gap locally -- see "
    "2AMLogic/klayout-tools#432."
)
ROUTING_LAYER_NOTE = (
    "sky130's generator/router layer-role table exposes exactly one routing "
    "metal role (`metal` -> li1 67/20) even though the same tool's sky130 "
    "extraction deck declares a second metal (68/20) and a via (67/44). "
    "Every `klt gen` generator draws its device pads on that same li1, and "
    "`klt gen-compose`'s router is documented as unaware of a block's "
    "internal geometry, so any route crossing a block shorts to every pad it "
    "passes over. Intra-block bussing (an array's emitters, a ladder's "
    "series segments) is therefore not expressible, which is what keeps this "
    "layout from LVS-closing against the schematic -- see "
    "2AMLogic/klayout-tools#433."
)
GUARD_RING_NOTE = (
    "`klt gen-compose`'s router rejects any route to a non-tap port on a "
    "block that reports a guard/collector ring, because the route would "
    "cross the ring's own metal loop -- and offers no way in. Per-matched-"
    "group guard rings and inter-block connectivity are therefore mutually "
    "exclusive today. This flow drops the per-group rings (keeping the "
    "cell-level ring) so connectivity can be drawn at all, a matching-"
    "quality regression relative to the #15 skeleton that is recorded in "
    "layout/matching-plan.md Section 5 -- see 2AMLogic/klayout-tools#434."
)

# ---------------------------------------------------------------------------
# Floorplan geometry constants (um)
# ---------------------------------------------------------------------------
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
#   * every guard/collector ring is off (GUARD_RING_NOTE) so the router will
#     accept a route into the block at all.
#   * row order/adjacency is chosen so that the circuit's inter-block nets
#     connect *adjacent* blocks through an empty channel -- the only routes
#     `klt gen-compose`'s obstacle check will certify.
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
            "add_collector_ring": False,
        },
        "pnp_overlay": True,
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
            "add_collector_ring": False,
        },
        "pnp_overlay": True,
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
            "add_guard_ring": False,
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
            "add_guard_ring": False,
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
            "add_guard_ring": False,
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
            "add_guard_ring": False,
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
            "add_guard_ring": False,
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


def build_pnp_overlay(
    klt: str,
    out_dir: Path,
    block_id: str,
    report: dict[str, Any],
    emitter_um: float,
) -> dict[str, Any]:
    """Draw a sky130 PNP device-recognition overlay for one `bjt_array` block.

    One 82/44 marker box per functional emitter pad (grown
    PNP_MARKER_MARGIN_UM past the pad so the extractor's `base` region
    strictly encloses its `emitter` region) and one 65/44 nwell tap box per
    base-tie pad (so the well node reaches the unit's own contact/li1 stack
    and the extracted base terminal is a named net rather than a floating
    one). Positions come from the generator's own reported `ports[]` --
    this function never re-derives geometry from the block's GDS stream,
    matching `klt gen-compose`'s own "consume the reported report" guarantee.

    The returned hand-written generator report deliberately declares a
    **degenerate (zero-area) bbox**: `klt gen-compose`'s obstacle check
    treats every placed block's reported bbox as a routing obstacle, and an
    overlay that occupies the same footprint as the block it annotates would
    otherwise veto every route into that block. A zero-area bbox contributes
    no interior for a route to cross while the overlay's geometry is still
    copied into the composed cell in full. See PNP_OVERLAY_NOTE.
    """
    shapes: list[dict[str, Any]] = []
    marker_count = 0
    tap_count = 0
    for port in report["ports"]:
        name = port["name"]
        if not name.startswith("Q"):
            continue
        x, y = float(port["x_um"]), float(port["y_um"])
        if name.endswith("_E"):
            half = emitter_um / 2.0 + PNP_MARKER_MARGIN_UM
            shapes.append(
                {
                    "layer": PNP_MARKER_LAYER,
                    "rect_um": [x - half, y - half, x + half, y + half],
                }
            )
            marker_count += 1
        elif name.endswith("_B"):
            half = float(port["width_um"]) / 2.0 + NWELL_TAP_MARGIN_UM
            shapes.append(
                {
                    "layer": NWELL_TAP_LAYER,
                    "rect_um": [x - half, y - half, x + half, y + half],
                }
            )
            tap_count += 1

    overlay_id = f"{block_id}_pnpmark"
    params_path = out_dir / f"{overlay_id}.draw.json"
    params_path.write_text(json.dumps({"shapes": shapes}, indent=2) + "\n")
    gds_path = out_dir / f"{overlay_id}.gds"
    draw_report = run_klt_json(
        klt,
        "draw",
        "--params",
        str(params_path),
        "--cell-name",
        overlay_id,
        "-o",
        str(gds_path),
    )
    (out_dir / f"{overlay_id}.draw.report.json").write_text(
        json.dumps(draw_report, indent=2) + "\n"
    )

    gen_report = {
        "schema_version": 1,
        "generator": "draw",
        "cell_name": overlay_id,
        "gds_path": str(gds_path.resolve()),
        "pdk": report["pdk"],
        # Deliberately degenerate -- see this function's docstring.
        "bbox_um": {"x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 0.0},
        "device_count": 0,
        "ports": [],
        "drc_hints": {
            "min_spacing_um": None,
            "matched_group_id": None,
            "snapped_to_grid": False,
            "notes": [PNP_OVERLAY_NOTE],
        },
        "warnings": [],
        "overlay_marker_count": marker_count,
        "overlay_tap_count": tap_count,
    }
    (out_dir / f"{overlay_id}.gen.json").write_text(
        json.dumps(gen_report, indent=2) + "\n"
    )
    return gen_report


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
DIRECTION_EAST = 0
DIRECTION_NORTH = 90
DIRECTION_WEST = 180

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
    ]
    if not ports:
        raise KeyError(
            f"no '{suffix}' ports facing {facing} deg "
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


#: The bandgap core's inter-block netlist, transcribed from
#: design/bandgap_core.sch and design/error_amp.sch. Each entry names the two
#: blocks a node connects and, per side, the port family and the block edge
#: the route arrives at. Concrete port names are resolved from each block's
#: own reported geometry (`select_ports`) and then *validated by the router
#: itself* (`resolve_connectivity`), so nothing here hardcodes a port index
#: that a count change would silently invalidate.
#:
#: Only inter-block nodes appear. Intra-block bussing (an array's 8 emitters,
#: a ladder's 108 series segments, a split pair's fingers) is deliberately
#: absent: a self-net's backbone is exempt from the router's obstacle check
#: and would be drawn straight across the block's own pads on the one
#: available routing metal, shorting every device it crossed
#: (ROUTING_LAYER_NOTE). Drawing a known short would be worse evidence than
#: leaving the node open, so this flow does not draw it.
CORE_NETS: list[dict[str, Any]] = [
    # --- core signal string: Q1 -> R2 ladder -> trim -> R1 -> Q2 -----------
    {
        "net": "VA",
        "a": ("pnp_ctat", "_E", DIRECTION_NORTH, "north"),
        "b": ("res_r2", "_A", DIRECTION_WEST, "west"),
        "schematic": "Q1 emitter to the R2A leg's low end (amp VINN node)",
    },
    {
        "net": "TRIM",
        "a": ("res_r2", "_B", DIRECTION_EAST, "east"),
        "b": ("res_trim", "_A", DIRECTION_WEST, "west"),
        "schematic": "R2 ladder tail into the downward-only trim ladder (DR-002)",
    },
    {
        "net": "VB",
        "a": ("res_trim", "_B", DIRECTION_EAST, "east"),
        "b": ("res_r1", "_A", DIRECTION_WEST, "west"),
        "schematic": "trim ladder tail to R1's head (amp VINP node)",
    },
    {
        "net": "VBQ",
        "a": ("res_r1", "_B", DIRECTION_EAST, "east"),
        "b": ("pnp_ptat", "_E", DIRECTION_NORTH, "north"),
        "schematic": "R1's tail to Q2's emitter",
    },
    # --- amp signal path ----------------------------------------------------
    {
        "net": "TAIL",
        "a": ("core_mirror", "_D", DIRECTION_EAST, "east"),
        "b": ("amp_input_pair", "_S", DIRECTION_WEST, "west"),
        "schematic": "MPAMP drain to the amp input pair's common source",
    },
    {
        "net": "D1",
        "a": ("amp_input_pair", "_D", DIRECTION_EAST, "east"),
        "b": ("amp_nload", "_S", DIRECTION_WEST, "west"),
        "schematic": "amp input-pair drain to its NMOS diode load",
    },
    {
        "net": "PN",
        "a": ("amp_nmirr", "_S", DIRECTION_WEST, "west"),
        "b": ("amp_pmirr", "_D", DIRECTION_EAST, "east"),
        "schematic": "amp NMOS mirror output to the PMOS mirror -- taken at "
        "amp_nmirr's west terminal and amp_pmirr's east terminal because "
        "`diff_pair` places amp_pmirr immediately west of amp_nmirr in row 2. "
        "`_S`/`_D` are a labelling convention on `diff_pair`'s symmetric "
        "device rows (docs/cli/gen.md), not a fixed source/drain assignment, "
        "so this names the same two devices the schematic's PN node joins",
    },
    # --- supply trunks ------------------------------------------------------
    # `klt gen-compose` routes 2-pin nets only (a >2-pin bundle is deferred
    # upstream), so a supply rail is expressed as a chain of 2-pin hops that
    # all carry the *same* net label -- extraction merges same-labelled
    # metal into one net, which is how a trunk is expressible at all today.
    {
        "net": "VDD",
        "a": ("core_mirror", "_S", DIRECTION_WEST, "west"),
        "b": ("amp_input_pair", "_S", DIRECTION_WEST, "west"),
        "schematic": "VDD trunk: core mirror sources to the amp input pair's well side",
    },
    {
        "net": "VSS",
        "a": ("amp_nload", "_D", DIRECTION_EAST, "east"),
        "b": ("amp_nmirr", "_D", DIRECTION_EAST, "east"),
        "schematic": "VSS trunk: amp NMOS load/mirror source rail -- a "
        "cross-row hop taken at both blocks' *east* terminals so the "
        "connecting jog runs in open space east of every placed block "
        "(the same same-facing-outer-edge shape the VDD hop uses on the "
        "west side); an east-to-west hop between these two rows would have "
        "to cross amp_input_pair's bbox and the router rejects it",
    },
]

#: Single-port nodes labelled without routing (`pins[]`). Every device gate is
#: a one-pin node `connectivity[]` cannot even express, and the trim ladder's
#: taps are read-only probe points, so these are label-only promotions -- the
#: mechanism that makes each node a *named* `.SUBCKT` pin instead of an
#: anonymous `$N` net, and therefore addressable from a post-layout testbench
#: (issue #16). `(block, suffix, facing, toward)` resolves the same way
#: CORE_NETS does; the first candidate not already claimed by a routed net is
#: used.
CORE_PIN_LABELS: list[dict[str, Any]] = [
    {"net": "GDRV", "port": ("core_mirror", "_G", DIRECTION_NORTH, "north"),
     "schematic": "core mirror gate drive (the amp's output node)"},
    {"net": "VOUT", "port": ("core_mirror", "_D", DIRECTION_EAST, "east"),
     "schematic": "MPOUT drain -- the reference output"},
    {"net": "VA_GATE", "port": ("amp_input_pair", "_G", DIRECTION_NORTH, "north"),
     "schematic": "amp VINN input gate"},
    {"net": "VB_GATE", "port": ("amp_input_pair", "_G", DIRECTION_NORTH, "south"),
     "schematic": "amp VINP input gate"},
    {"net": "D1_GATE", "port": ("amp_nload", "_G", DIRECTION_NORTH, "north"),
     "schematic": "amp NMOS diode-load gate (D1)"},
    {"net": "D2_GATE", "port": ("amp_nload", "_G", DIRECTION_NORTH, "south"),
     "schematic": "amp NMOS diode-load gate (D2)"},
    {"net": "D1_MIRROR_GATE", "port": ("amp_nmirr", "_G", DIRECTION_NORTH, "north"),
     "schematic": "amp NMOS mirror-output gate driven by D1"},
    {"net": "D2_MIRROR_GATE", "port": ("amp_nmirr", "_G", DIRECTION_NORTH, "south"),
     "schematic": "amp NMOS mirror-output gate driven by D2"},
    {"net": "PN_GATE", "port": ("amp_pmirr", "_G", DIRECTION_NORTH, "north"),
     "schematic": "amp PMOS mirror gate (PN)"},
    {"net": "AOUT", "port": ("amp_pmirr", "_D", DIRECTION_EAST, "east"),
     "schematic": "amp output drain (drives GDRV)"},
]


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
        "blocks": ["pnp_ctat", "res_r2", "amp_input_pair"],
        "hops": ["VA"],
        "schematic": "Q1 emitter + R2A low end + MP1 gate (amp VINN)",
    },
    {
        "net": "VB",
        "blocks": ["res_trim", "res_r1", "amp_input_pair"],
        "hops": ["VB"],
        "schematic": "R2B low end (through the trim taps) + R1 head + MP2 gate",
    },
    {
        "net": "TRIM",
        "blocks": ["res_r2", "res_trim"],
        "hops": ["TRIM"],
        "schematic": "layout-internal split of the R2 legs into ladder + "
        "DR-002 trim taps (one device in the schematic)",
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
        "hops": [],
        "schematic": "MPOUT drain + both R2A/R2B tops (the reference output)",
    },
    {
        "net": "GDRV",
        "blocks": ["core_mirror", "amp_pmirr", "amp_nmirr"],
        "hops": [],
        "schematic": "amp output (MP4/MN3 drains, labelled AOUT in the layout) "
        "+ MPOUT/MPAMP gates -- one node in the schematic",
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
        "hops": [],
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
        "schematic": "supply trunk: MPOUT/MPAMP sources, the input pair's "
        "well side, MP3/MP4 sources (and MCC, not drawn)",
    },
    {
        "net": "VSS",
        "blocks": ["amp_nload", "amp_nmirr", "pnp_ctat", "pnp_ptat"],
        "hops": ["VSS"],
        "schematic": "ground trunk: MN1-MN4 sources + both PNPs' base/collector ties",
    },
]


def schematic_net_coverage(compose: dict[str, Any]) -> list[dict[str, Any]]:
    """Score each schematic inter-block node against what `gen-compose`
    actually routed.

    `status` is "drawn" only when the routed hops carrying that node's label
    touch every block the schematic says the node reaches; "partial" when
    some but not all are joined; "labelled only" when no metal is drawn for
    it at all (the node exists in the layout solely as promoted pin labels).
    """
    touched: dict[str, set[str]] = {}
    for net in compose.get("nets", []):
        if not net.get("routed"):
            continue
        touched.setdefault(net["net"], set()).update(
            p["block"] for p in net.get("pins", [])
        )
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


def resolve_connectivity(
    klt: str,
    out_dir: Path,
    pdk: str,
    cell_name: str,
    block_ids: list[str],
    reports: dict[str, dict[str, Any]],
    origins: dict[str, dict[str, float]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Compose the routed inner cell, using `klt gen-compose` itself as the
    routability oracle.

    `klt gen-compose` rejects a net whose Manhattan backbone would cross a
    block's interior, and reports the reason per net -- but it offers no
    "which port should I have used?" query, and a block like the 108-segment
    ladder or the 16-way-split input pair exposes hundreds of same-family
    ports of which only the few nearest the approached edge are reachable.

    This drives the tool as an oracle instead of guessing: every net gets an
    ordered candidate list from `select_ports`, round `k` proposes each
    still-unrouted net's `k`-th candidate pair, and a net that routes is
    frozen at that choice for every later round. Rounds stop when every net
    routes or every candidate is exhausted. Because one `gen-compose` call
    reports pass/fail for *all* nets at once, this costs at most
    PORT_CANDIDATE_LIMIT calls, not one per candidate pair.

    Returns `(compose_response, connectivity, pins, attempts)`.
    """
    candidates: dict[str, list[tuple[str, str]]] = {}
    for spec in CORE_NETS:
        a_block, a_suffix, a_facing, a_toward = spec["a"]
        b_block, b_suffix, b_facing, b_toward = spec["b"]
        a_names = select_ports(reports[a_block], a_suffix, a_facing, a_toward)
        b_names = select_ports(reports[b_block], b_suffix, b_facing, b_toward)
        pairs = [
            (a_names[i % len(a_names)], b_names[i % len(b_names)])
            for i in range(max(len(a_names), len(b_names)))
        ]
        candidates[spec["net"]] = pairs

    chosen: dict[str, tuple[str, str]] = {}
    routed_ok: dict[str, bool] = {spec["net"]: False for spec in CORE_NETS}
    attempts: list[dict[str, Any]] = []
    compose: dict[str, Any] = {}
    connectivity: list[dict[str, Any]] = []
    pins: list[dict[str, Any]] = []

    rounds = max(len(v) for v in candidates.values())
    for round_index in range(rounds):
        for spec in CORE_NETS:
            net = spec["net"]
            if routed_ok[net]:
                continue
            pairs = candidates[net]
            chosen[net] = pairs[min(round_index, len(pairs) - 1)]

        connectivity = []
        for spec in CORE_NETS:
            a_block = spec["a"][0]
            b_block = spec["b"][0]
            a_port, b_port = chosen[spec["net"]]
            connectivity.append(
                {
                    "net": spec["net"],
                    "pins": [
                        {"block": a_block, "port": a_port},
                        {"block": b_block, "port": b_port},
                    ],
                }
            )

        used = {(c["pins"][0]["block"], c["pins"][0]["port"]) for c in connectivity}
        used |= {(c["pins"][1]["block"], c["pins"][1]["port"]) for c in connectivity}
        pins = []
        for spec in CORE_PIN_LABELS:
            block, suffix, facing, toward = spec["port"]
            for name in select_ports(reports[block], suffix, facing, toward):
                if (block, name) not in used:
                    pins.append({"net": spec["net"], "block": block, "port": name})
                    used.add((block, name))
                    break
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
            "connectivity": connectivity,
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

        round_result = {"round": round_index, "nets": {}}
        for net in compose.get("nets", []):
            if net.get("routed"):
                routed_ok[net["net"]] = True
            round_result["nets"][net["net"]] = bool(net.get("routed"))
        attempts.append(round_result)
        if all(routed_ok.values()):
            break

    (out_dir / "compose.inner.json").write_text(json.dumps(compose, indent=2) + "\n")
    (out_dir / "route-search.json").write_text(
        json.dumps({"attempts": attempts, "chosen": {k: list(v) for k, v in chosen.items()}}, indent=2)
        + "\n"
    )
    return compose, connectivity, pins, attempts
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

    # --- 2. PNP recognition overlays (PNP_OVERLAY_NOTE) ---------------------
    overlays: dict[str, dict[str, Any]] = {}
    for block in BLOCKS:
        if block.get("pnp_overlay"):
            overlay = build_pnp_overlay(
                klt,
                out_dir,
                block["id"],
                reports[block["id"]],
                float(block["params"]["emitter_um"]),
            )
            overlays[block["id"]] = overlay

    # --- 3. Place on an explicit 2D grid ------------------------------------
    origins = place_blocks(BLOCKS, reports)
    # Each overlay rides at exactly its parent block's origin.
    all_reports: dict[str, dict[str, Any]] = dict(reports)
    all_origins: dict[str, dict[str, float]] = dict(origins)
    for parent_id, overlay in overlays.items():
        all_reports[overlay["cell_name"]] = overlay
        all_origins[overlay["cell_name"]] = dict(origins[parent_id])

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
    inner_compose, connectivity, pin_labels, route_attempts = resolve_connectivity(
        klt, out_dir, pdk, inner_cell, inner_ids, inner_reports, inner_origins
    )

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
    reference_name = "reference.spice"
    (out_dir / reference_name).write_text(args.reference.read_text())
    lvs_request = {
        "schema": "klt.lvs.request/1",
        "engine": "klayout",
        "layout": {
            "file": f"{cell}.gds",
            "deck": "sky130",
            "top": cell,
        },
        "reference": {"netlist": reference_name, "top": "bandgap_core"},
    }
    (out_dir / "lvs.request.json").write_text(json.dumps(lvs_request, indent=2) + "\n")
    lvs = run_klt_json(
        klt, "lvs", str(out_dir / "lvs.request.json"), allow_exit=(0, 3)
    )
    (out_dir / "lvs.json").write_text(json.dumps(lvs, indent=2) + "\n")

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
    routed_nets = [n for n in inner_compose.get("nets", []) if n.get("routed")]
    unrouted = inner_compose.get("unrouted_nets", [])
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
    coverage = schematic_net_coverage(inner_compose)
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
        f"fully drawn ({len(routed_nets)}/{len(inner_compose.get('nets', []))} "
        f"declared 2-pin hops routed, {len(unrouted)} unrouted) -- see "
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
        "2AMLogic/klayout-tools#432 (PNP recognition marker), #433 "
        "(single routing metal), #434 (no route into a guard-ringed block) |"
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
        "2. `klt draw` once per PNP array: a device-recognition overlay "
        "(82/44 marker per functional emitter pad, 65/44 nwell tap per base "
        "pad), positioned from that block's own reported `ports[]`."
    )
    a(
        "3. `klt gen-compose` with `placement.strategy: \"explicit\"`, "
        "`connectivity[]` (routed 2-pin nets) and `pins[]` (labelled "
        "single-port nets) -- `compose.request.json`."
    )
    a("4. `klt drc <composed> --deck sky130`.")
    a(f"5. `klt extract <composed> --deck sky130 --top {cell}`.")
    a("6. `klt lvs` against the xschem-derived reference netlist (issue #8).")
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
    a("## Routed nets")
    a("")
    a("| net | pins | routed | length (um) |")
    a("| --- | --- | --- | --- |")
    for net in inner_compose.get("nets", []):
        pins_desc = " -> ".join(
            f"{p['block']}.{p['port']}" for p in net.get("pins", [])
        )
        length = net.get("route_length_um")
        a(
            f"| `{net['net']}` | {pins_desc} | "
            f"{'yes' if net.get('routed') else 'NO'} | "
            f"{'' if length is None else f'{length:.2f}'} |"
        )
    a("")
    if unrouted:
        a("### Unrouted nets (partial success, `klt gen-compose` exit 3)")
        a("")
        for note in inner_compose.get("drc_hints", {}).get("notes", []):
            a(f"- {note}")
        a("")
    a("## Schematic inter-block nets: drawn vs. labelled only")
    a("")
    a(
        "The table above counts this flow's own `connectivity[]` declaration. "
        "This one counts what issue #62 actually asks for: every node of "
        "design/bandgap_core.sch (+ design/error_amp.sch) that joins devices "
        "in different blocks, and whether drawn metal joins **all** the "
        "blocks the schematic says it reaches. `klt gen-compose` routes 2-pin "
        "nets only, so a trunk can only be built as a chain of same-labelled "
        "hops -- and a hop is only certifiable when the two blocks are "
        "adjacent across an empty channel (2AMLogic/klayout-tools#433, #434). "
        "Everything not drawn below exists in the layout as a promoted pin "
        "label, i.e. it is addressable but electrically open."
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
        "are fully drawn.** Criterion 1 is therefore scored PARTIAL, not MET, "
        "whenever that count is short: the `VDD` trunk reaches two of its "
        "three blocks, `VSS` two of four, and `VOUT` / `GDRV` (the amp output "
        "the schematic ties straight to the mirror gates) are labelled pins "
        "with no metal between them. The same single-routing-metal limit that "
        "blocks criterion 4 caps this criterion too."
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
        f"| compose | {'routed' if not unrouted else 'partial'} | "
        f"nets={len(inner_compose.get('nets', []))}, unrouted={len(unrouted)} |"
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
    lvs_counts = lvs.get("counts", {})
    lvs_nets = lvs_counts.get("nets", {})
    lvs_devices = lvs_counts.get("devices", {})
    lvs_pins = lvs_counts.get("pins", {})
    a("| | layout | reference | matched |")
    a("| --- | --- | --- | --- |")
    a(
        f"| nets | {lvs_nets.get('layout')} | {lvs_nets.get('reference')} | "
        f"{lvs_nets.get('matched')} |"
    )
    a(
        f"| devices | {lvs_devices.get('layout')} | "
        f"{lvs_devices.get('reference')} | {lvs_devices.get('matched')} |"
    )
    a(
        f"| pins | {lvs_pins.get('layout')} | {lvs_pins.get('reference')} | "
        f"{lvs_pins.get('matched')} |"
    )
    a("")
    a(
        f"Mismatch categories: `{json.dumps(lvs.get('category_counts', {}))}`."
    )
    a("")
    a(
        "The gap has one dominant cause plus two smaller, separately "
        "disclosed deltas. The dominant cause: the reference netlist "
        "expresses each matched group the way "
        "the schematic does -- one device carrying a multiplicity (`m=8` "
        "PNPs, `m=16` input-pair PMOS) or one resistor carrying a total "
        "length (`R2A` = 54 unit segments' worth). The layout draws those as "
        "the physical instances they are, and cannot bus them into one node, "
        "because bussing an array's units requires a wire that crosses the "
        "block -- which today's router can only draw on the same single metal "
        "the device pads occupy, shorting every pad it crosses "
        "(2AMLogic/klayout-tools#433). The bulk of the unmatched devices and "
        "nets below trace back to that: the layout's device and net counts "
        "are the un-bussed expansion of the reference's, not a topology error "
        "in either. Closing the gap needs the upstream capability, not a "
        "different reference netlist -- rewriting the reference to enumerate "
        "the layout's own un-bussed devices would make LVS compare the layout "
        "against itself, which is not evidence."
    )
    a("")
    a(
        "The two smaller deltas, folded in here so this paragraph is not read "
        "as \"one cause explains everything\": (a) `MMCC`, the amp's "
        "compensation cap, is in the reference but deliberately not drawn in "
        "this layout (see the Blocks note above), so one reference device has "
        "no layout counterpart by construction; and (b) the schematic "
        "inter-block nets left as labelled-only pins in the table above "
        "(`VOUT`, `GDRV`/`AOUT`, `D2`, and the unjoined legs of `VDD`/`VSS`/"
        "`VA`/`VB`/`D1`) are single reference nodes that the layout carries as "
        "two or more open nodes. Neither is an error in the reference "
        "netlist, and neither is accommodated in it: `reference.spice` states "
        "the schematic (one `GDRV` node, no 0-ohm bridge device), and the "
        "gaps are recorded here."
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
        "xschem-derived reference netlist. The blocking reason is a tool "
        f"gap, not a layout choice: {ROUTING_LAYER_NOTE}"
    )
    a(
        "- **Not fully inter-block routed either.** "
        f"{len(fully_drawn)}/{len(coverage)} schematic inter-block nets are "
        "joined across every block they reach; the rest are promoted pin "
        "labels with no metal between them (`VOUT` never reaches the ladder, "
        "`AOUT`/`GDRV` are two pins where the schematic has one node, `D2` is "
        "undrawn, and the `VDD`/`VSS` trunks each stop short of blocks they "
        "supply). `klt gen-compose` routes 2-pin nets between blocks adjacent "
        "across an empty channel only, so a trunk is a chain of hops and a "
        "non-adjacent pair is unroutable -- the same #433/#434 limits as "
        "above. Criterion 1 is scored PARTIAL on this basis, against the "
        "schematic's node list rather than this flow's own declaration."
    )
    a(
        "- **No intra-block bussing is drawn.** Each PNP array's 8 emitters, "
        "each ladder's unit segments, and each matched pair's split fingers "
        "stay separate nodes in the extracted netlist for the reason above. "
        "This flow deliberately does not draw those wires rather than draw a "
        "known short and call it connectivity."
    )
    a(
        f"- **Per-matched-group guard rings are off.** {GUARD_RING_NOTE} The "
        "cell-level ring is still drawn and DRC-checked."
    )
    a(
        "- **The PNP devices are recognition-marked drawn geometry, not "
        "vendor `pnp_05v5` cell instances.** `klt gen bjt_array` draws a "
        "matching-faithful floorplan from base layers by design (its own "
        "generator note says so); the overlay this flow adds makes that "
        "geometry *extract* as `pnp`, it does not make it a SPICE-model-"
        "exact device."
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
    a("- [`drc.json`](drc.json), [`extract.json`](extract.json), [`lvs.json`](lvs.json)")
    a(f"- [`{cell}.extract.spice`]({cell}.extract.spice), [`reference.spice`](reference.spice)")
    a(f"- [`{cell}.gds`]({cell}.gds)")
    a("- [`render.json`](render.json), [`renders/overview.png`](renders/overview.png)")
    a("")

    (out_dir / "record.md").write_text("\n".join(lines))
    print("\n".join(lines))

    # The flow's own gate: DRC must be clean, the ladder must be at full
    # scale, every device class must extract, and pins must be promoted.
    # LVS-clean is NOT gated here -- it is blocked upstream (ROUTING_LAYER_NOTE)
    # and the record above states so explicitly rather than silently passing.
    ok = drc_clean and within_budget and full_scale_ladder and all_classes and pin_count > 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
