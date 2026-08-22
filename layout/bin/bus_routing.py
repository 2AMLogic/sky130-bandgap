#!/usr/bin/env python3
"""layout/bin/bus_routing.py -- issue #221: intra-block bussing and
inter-block routing, split out of `gen_bandgap_routed.py`'s own section of
the same name (that file's lines 1502-3631 as of the split, marked off by
its own section banners -- see that file's docstring item 5 and 13 for why
this concern exists). Pure move, verbatim (including comments); no behavior
change.

`build_bus_overlay`, `trim_tap_port` and `MOS_HALVES` are the only symbols
`gen_bandgap_routed.py` calls from outside this module (`route_inter_block_
nets`, despite being one of this span's two originally-named entry points,
turned out on re-verification after the split to be called only from within
`build_bus_overlay` and so is not re-imported there); everything else here
is a private (`_`-prefixed) helper or module constant used only by other
functions in this file.
"""

from __future__ import annotations

import itertools
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import met1_bus  # noqa: E402  -- local module, resolved from this script's dir

# gen_bandgap_routed.py's own use of this module's symbols is imported
# locally, inside each function that needs one (see that file's own note
# next to where this section used to live) -- so this is the only direction
# with a genuine top-level dependency between the two modules: this file's
# own module-level tables (MOS_HALVES, INTER_BLOCK_MET1) are built directly
# from these five names at *this* module's load time, not deferred to a
# function call, so they cannot be imported lazily the way
# `schematic_net_coverage` is below. Because gen_bandgap_routed.py carries no
# top-level reference back to this module, this import always resolves
# cleanly regardless of which of the two modules a caller happens to import
# first.
from gen_bandgap_routed import (  # noqa: E402
    DIRECTION_EAST,
    DIRECTION_WEST,
    N_R1,
    N_R2_COARSE,
    N_R2_TRIM_UNITS,
)


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
    "amp_cc": {
        # Both "devices" here are wired to the exact same nets (VDD on
        # both drain and source, GDRV on gate) -- MCC is one schematic
        # device, not two, and `combine_devices` is what folds the two
        # mult=AMP_M_CC//2 groups back into the schematic's single m=16
        # device (MCC_MIM_INFEASIBLE_NOTE). The drain/source suffix
        # choice is arbitrary here (both terminals land on VDD either
        # way) -- kept consistent with the other "W"-spine PMOS blocks.
        "drain_suffix": "_D", "drain_facing": DIRECTION_EAST,
        "source_suffix": "_S", "source_facing": DIRECTION_WEST,
        "devices": {"MCC_A": "M1", "MCC_B": "M2"},
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


def trim_tap_port(leg: int, code: int) -> str:
    """The `res_trim` port that selects DR-002 trim `code` (<= 0) on `leg`.

    The fine ladder is the last :data:`N_R2_TRIM_UNITS` um of the divider
    leg, not an addition to it (issue #91), so code 0 is the tap that puts
    *all* the fine units in circuit -- the far end of that leg's chain -- and
    code -k is the tap k units short of it. :func:`bus_res_series`
    interdigitates the two legs by segment index (even = leg 0, odd = leg 1,
    per layout/matching-plan.md Section 3), so chain position `j` of leg `l`
    is segment `2*j + l` and its `_B` terminal has `j + 1` fine units behind
    it. `code = -N_R2_TRIM_UNITS` is the chain's head, i.e. the
    `TRIM_A`/`TRIM_B` junction with `res_r2`, which bypasses the fine units
    entirely.

    Returns a port *name*; callers that need it to exist validate it against
    the block's own reported ports (:func:`trim_tap_ladder`).
    """
    if code > 0 or code < -N_R2_TRIM_UNITS:
        raise ValueError(
            f"trim code {code:+d} is outside the drawn ladder's "
            f"0..-{N_R2_TRIM_UNITS} range"
        )
    j = N_R2_TRIM_UNITS + code - 1
    return f"R{leg}_A" if j < 0 else f"R{2 * j + leg}_B"


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
            {"block": "res_trim", "port": trim_tap_port(0, 0), "leg": 0},
            {"trunk": ("pnp_ctat", "VA")},
            mos_comb("amp_input_pair", "VA"),
        ],
        "schematic": "the R2A leg's low end (at trim code 0, the far end of "
        "its fine ladder) to Q1's emitter bus and MP2's gate -- the amp's "
        "VINN node",
    },
    {
        "net": "TRIM_A",
        "internal": "R2A",
        "terminals": [
            {"block": "res_r2", "port": f"R{2 * N_R2_COARSE - 2}_B", "leg": 0},
            {"block": "res_trim", "port": "R0_A", "leg": 0},
        ],
        "schematic": "R2A's coarse 240 um into leg A of the fine trim ladder "
        "that carries the leg's last 10 um (DR-002, downward-only)",
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
        "internal": "R2B",
        "terminals": [
            {"block": "res_r2", "port": f"R{2 * N_R2_COARSE - 1}_B", "leg": 1},
            {"block": "res_trim", "port": "R1_A", "leg": 1},
        ],
        "schematic": "R2B's coarse 240 um into leg B of the same fine ladder",
    },
    {
        "net": "VB",
        "terminals": [
            {"block": "res_trim", "port": trim_tap_port(1, 0), "leg": 1},
            {"block": "res_r1", "port": "R0_A"},
            mos_comb("amp_input_pair", "VB"),
        ],
        "schematic": "the R2B leg's low end (at trim code 0, the far end of "
        "its fine ladder) to R1's head and MP1's gate -- the amp's VINP node",
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
            mos_comb("amp_cc", "VDD"),
            bulk_terminal("core_mirror"),
            bulk_terminal("amp_input_pair"),
            bulk_terminal("amp_pmirr"),
            bulk_terminal("amp_cc"),
        ],
        "schematic": "VDD trunk: MPOUT/MPAMP and MP3/MP4 sources, MCC's "
        "drain+source (it is wired D=S=B=VDD, a MOS capacitor) -- every "
        "finger of all five, not one pad per block -- plus each PMOS "
        "group's n-well guard-ring tap (the reference's pfet bulk "
        "terminal)",
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
            mos_comb("amp_cc", "GDRV"),
        ],
        "schematic": "the amp's output -- MP4's and MN3's drains -- the "
        "core mirror's gate drive, and MCC's gate (the compensation cap "
        "sits from AOUT/GDRV to VDD), one node in the schematic and now "
        "one drawn node in the layout",
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
    # Restored on rollback along with the geometry: without it `wire_count`
    # tallies every *attempted* segment, including the tens of thousands a
    # congested hop's search draws and takes straight back, so the report's
    # `met1_wire_count` describes the search rather than the layout.
    wire_mark = bus.wire_count
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
            bus.wire_count = wire_mark
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
    # Deferred import: RING_MARGIN_UM is not needed until this function is
    # actually called, unlike DIRECTION_EAST/DIRECTION_WEST/N_R1/
    # N_R2_COARSE/N_R2_TRIM_UNITS, which this module's own top-level tables
    # (MOS_HALVES, INTER_BLOCK_MET1) need immediately -- see this file's
    # top-of-file import comment.
    from gen_bandgap_routed import RING_MARGIN_UM

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
    # Last resort: lift the hop onto the met2 escape plane. Deliberately last,
    # not first -- see MET2_ESCAPE_NOTE.
    if MET2_ESCAPE_ENABLED:
        return _connect_met2(bus, net, a, b)
    return None


#: Whether :func:`_connect` may fall back to the met2 escape plane. Always
#: True in the flow; the met1-only router tests flip it off so they can keep
#: asserting what the *met1* search does when it runs out of corridor, which
#: is a different question from what the whole router does.
MET2_ESCAPE_ENABLED = True

#: Lateral offsets (um) a met2 escape tries for its via1 drop point when the
#: hop's own endpoint has no room for the 0.32 um met1 landing pad the via
#: stack needs. Each is reached by a short guarded met1 stub from the endpoint,
#: so the drop still lands on the net's own metal.
MET2_DROP_OFFSETS_UM = (0.0, 0.4, -0.4, 0.8, -0.8, 1.6, -1.6)
#: Intermediate-lane offsets (um) a met2 Z-detour tries when neither plain
#: L-shape clears an already-drawn met2 wire of another node.
MET2_DETOUR_OFFSETS_UM = (0.0, 1.2, -1.2, 3.0, -3.0, 6.0, -6.0)


def _draw_guarded_met2(
    bus: "met1_bus.Met1Bus", net: str, points: list[tuple[float, float]]
) -> bool:
    """:func:`_draw_guarded`, on the met2 escape plane.

    Same contract, same rollback, different plane and threshold (sky130's
    `m2.2`, 0.14 um). It has to exist separately rather than be a parameter of
    the met1 version because the two planes are independent conductors: met2
    crossing over another node's met1 is ordinary routing, and that is the
    whole reason this escape hatch works.
    """
    shape_mark = len(bus.shapes)
    rect_mark = len(bus.met2_rects)
    # Restored on rollback along with the geometry, for the same reason
    # _draw_guarded's wire_mark is: without it `met2_wire_count` would tally
    # every attempted segment rather than the ones that survive.
    wire_mark = bus.met2_wire_count
    bus.net(net)
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 != x1 and y0 != y1:
            raise ValueError("path segments must be orthogonal")
        if x0 == x1:
            bus.vseg2(x0, y0, y1)
        else:
            bus.hseg2(x0, x1, y0)
    eps = met1_bus.MET2_SPACE_UM - 1e-9
    for _, ax0, ay0, ax1, ay1 in bus.met2_rects[rect_mark:]:
        for net_b, bx0, by0, bx1, by1 in bus.met2_near(ax0, ay0, ax1, ay1, eps):
            if net_b == net:
                # Same-node notch check, identical in intent to _draw_guarded's.
                if ax0 <= bx1 and bx0 <= ax1 and ay0 <= by1 and by0 <= ay1:
                    continue
            del bus.shapes[shape_mark:]
            bus.truncate_met2(rect_mark)
            bus.met2_wire_count = wire_mark
            _LAST_BLOCKER.clear()
            _LAST_BLOCKER.append(net_b)
            _BLOCKER_COUNTS[f"met2:{net_b}"] += 1
            return False
    return True


def _met2_drop(
    bus: "met1_bus.Met1Bus", net: str, x: float, y: float
) -> tuple[float, float] | None:
    """Place a via1 stack on this net's own met1 at or near `(x, y)`.

    Returns the drop point actually used, or None if no offset had room. The
    via stack's met1 landing pad (0.32 um, sized by `via.4a`/`via.5a`) is
    wider than the 0.24 um wire that reaches it, so it can foul a neighbour
    the wire itself cleared; the offsets walk the pad along a short guarded
    met1 stub until one fits, rather than declaring the hop unroutable
    because its exact endpoint was 0.04 um too tight.

    Checks the whole via1 stack against a foreign node before committing an
    offset, not just the met1 half of it: the met2 landing pad (`m2.4`/
    `m2.5`) and the via1 cut itself (`via.2`) can each foul a neighbour the
    met1 pad clears. `conflicts()` and `met2_drc.py` both still gate the
    flow, so an unchecked stack could never *ship*, but it could turn a
    backtrackable case into a hard flow failure instead of trying the next
    offset -- the same reason the met1 pad is checked here rather than left
    to those later gates.

    A landing pad is also rejected when it *notches its own node's* metal --
    the rule :func:`_draw_guarded` already applies to wires, applied here to
    the pad. It is not redundant with that check, because the pad is 0.32 um
    where the stub reaching it is 0.24: the pad overhangs its own stub by
    0.04 um on each side, and that overhang can sit inside `met1.space.1` of
    a wire of the same net that the stub itself cleared by overlapping it.
    `met1.space.1` does not care whose net the two edges belong to; only
    *touching* is exempt. Found by exactly that shape -- one 0.12 um same-net
    gap between a drop pad and its own net's wire, invisible to
    `conflicts()` (which compares different nets only) and reported by
    `klt drc` alone (issue #91's re-run).
    """
    half = met1_bus.MET1_VIA1_LANDING_UM / 2.0
    eps = 0.14 - 1e-9
    met2_half = met1_bus.MET2_LANDING_UM / 2.0
    met2_eps = met1_bus.MET2_SPACE_UM - 1e-9
    via1_gap = met1_bus.VIA1_UM + met1_bus.VIA1_SPACE_UM - 1e-9

    def _pad_fouled(
        near: Any,  # the met1_near/met2_near generators of (net, x0, y0, x1, y1)
        x0: float,
        y0: float,
        x1: float,
        y1: float,
    ) -> str | None:
        """The first neighbour this pad may not sit next to, if any: another
        node at all, or its own node *without* touching (a notch)."""
        for net_b, bx0, by0, bx1, by1 in near:
            if net_b != net:
                return net_b
            if not (x0 <= bx1 and bx0 <= x1 and y0 <= by1 and by0 <= y1):
                return f"{net_b} (same-node notch)"
        return None

    for axis in ("x", "y"):
        for offset in MET2_DROP_OFFSETS_UM:
            dx, dy = (offset, 0.0) if axis == "x" else (0.0, offset)
            if offset == 0.0 and axis == "y":
                continue  # already tried as the x-axis zero offset
            px, py = x + dx, y + dy
            mark = bus.mark()
            if offset != 0.0 and not _draw_guarded(bus, net, [(x, y), (px, py)]):
                bus.restore(mark)
                continue
            # Does the wider landing pad itself fit, on either plane -- and
            # does the via1 cut itself clear another node's cut?
            fouled = False
            blocker = _pad_fouled(
                bus.met1_near(px - half, py - half, px + half, py + half, eps),
                px - half, py - half, px + half, py + half,
            )
            if blocker is not None:
                fouled = True
                _BLOCKER_COUNTS[f"met2drop:{blocker}"] += 1
            if not fouled:
                blocker = _pad_fouled(
                    bus.met2_near(
                        px - met2_half, py - met2_half,
                        px + met2_half, py + met2_half, met2_eps,
                    ),
                    px - met2_half, py - met2_half,
                    px + met2_half, py + met2_half,
                )
                if blocker is not None:
                    fouled = True
                    _BLOCKER_COUNTS[f"met2drop:{blocker}"] += 1
            if not fouled:
                for net_b, vx, vy in bus.via1_xy:
                    if (
                        net_b != net
                        and abs(px - vx) < via1_gap
                        and abs(py - vy) < via1_gap
                    ):
                        fouled = True
                        _BLOCKER_COUNTS[f"met2drop:{net_b}"] += 1
                        break
            if fouled:
                bus.restore(mark)
                continue
            bus.net(net)
            bus.via1(px, py)
            return (px, py)
    return None


def _connect_met2(
    bus: "met1_bus.Met1Bus",
    net: str,
    a: tuple[float, float],
    b: tuple[float, float],
) -> dict[str, Any] | None:
    """Join two met1 points by going *up*: via1 at each end, met2 in between.

    met1 on this floorplan is one shared plane carrying both every block's
    intra-block bus and every inter-block net, and three schematic hops have
    no corridor left on it at any lane, margin or placement this repo can set
    (`layout/matching-plan.md` Sections 7d-7o). met2 is a genuinely separate
    conductor -- new to sky130's curated deck with klayout-tools#511 -- so a
    hop lifted onto it crosses the congestion instead of competing with it.

    Returns a hop record with `met2: True`, or None if even the escape plane
    could not be reached (no room for a via1 landing pad at an endpoint) or
    could not be crossed (another node's met2 escape already in the way).
    """
    mark = bus.mark()
    (ax, ay), (bx, by) = a, b
    drop_a = _met2_drop(bus, net, ax, ay)
    if drop_a is None:
        bus.restore(mark)
        return None
    drop_b = _met2_drop(bus, net, bx, by)
    if drop_b is None:
        bus.restore(mark)
        return None
    (px, py), (qx, qy) = drop_a, drop_b
    met2_mark = bus.mark()
    for offset in MET2_DETOUR_OFFSETS_UM:
        if offset == 0.0:
            candidates = [
                [(px, py), (qx, py), (qx, qy)],
                [(px, py), (px, qy), (qx, qy)],
            ]
        else:
            candidates = [
                [(px, py), (px, py + offset), (qx, py + offset), (qx, qy)],
                [(px, py), (px + offset, py), (px + offset, qy), (qx, qy)],
            ]
        for points in candidates:
            if _draw_guarded_met2(bus, net, points):
                return {
                    "detour_um": offset,
                    "met2": True,
                    "via1_drops": [
                        [round(px, 3), round(py, 3)],
                        [round(qx, 3), round(qy, 3)],
                    ],
                    "points": [[round(x, 3), round(y, 3)] for x, y in points],
                }
        bus.restore(met2_mark)
    bus.restore(mark)
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
    #
    # ... and deliberately *none* for a node the schematic does not have.
    # A labelled met1 net is promoted to a top-level pin, and a pin is a
    # node the comparer must preserve, so labelling an internal node of a
    # schematic device splits that device in two on the layout side and
    # nothing can pair either half. See INTERNAL_NODE_LABEL_NOTE.
    if not spec.get("internal"):
        bus.label(net, resolved[0]["x"], resolved[0]["y"])
    return {
        "net": net,
        "routed": routed,
        "internal_to": spec.get("internal"),
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
    # Deferred import: MET1_BUS_NOTE is not needed until this function is
    # actually called (see this file's top-of-file import comment for why
    # DIRECTION_EAST/DIRECTION_WEST/N_R1/N_R2_COARSE/N_R2_TRIM_UNITS cannot
    # be deferred the same way). schematic_net_coverage is defined in
    # gen_bandgap_routed.py itself, so this stays a plain call-time import
    # either way.
    from gen_bandgap_routed import MET1_BUS_NOTE, schematic_net_coverage

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

