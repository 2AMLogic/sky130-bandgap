#!/usr/bin/env python3
"""layout/bin/mos_bus.py -- bus a `klt gen diff_pair` block's split unit
devices into the two matched devices the schematic actually contains.

Why this exists
---------------
`klt gen diff_pair` draws a matched pair as ``2 x splits`` unit devices in a
common-centroid checkerboard, and reports each unit's source, drain and gate
as separate ports. Nothing joins them: the composed layout therefore extracts
as ``2 * splits`` independent transistors with ``2 * splits`` floating gates,
not as two ``m = splits`` devices. Closing that gap needs two things the tool
does not provide today:

1. **A contactable gate.** Every sky130 MOS generator draws the gate poly with
   exactly the active region's extent and reports the gate port on that shared
   boundary, so there is no poly outside the channel for a contact to land on
   (2AMLogic/klayout-tools#461). :meth:`met1_bus.Met1Bus.gate_landing` draws
   the missing poly extension -- the same overhang every real foundry PDK
   draws for exactly this purpose -- plus the licon/li1 stack on top of it.
2. **A second routing conductor.** `gen-compose`'s router still exposes only
   li1, the layer the device pads themselves sit on
   (2AMLogic/klayout-tools#454), so every wire here is drawn on met1 over
   mcon, the sky130 extraction deck's own second conductor and via. See
   `met1_bus.py`.

How the bus stays planar on one metal
-------------------------------------
Two interleaved combs cannot be joined on a single routing layer without a
crossing, and a `diff_pair` is exactly that: device A owns the even columns of
row 0 and the odd columns of row 1, device B the complement. The escape is
that a unit's li1 source/drain pad is the device's full width ``w`` tall, so a
via onto it may be placed at *any* height inside the row. Every net therefore
gets its own horizontal **lane** inside each row and drops its vias at that
lane's height; a lane crossing another net's pad without a via there is simply
metal passing overhead. No jogs, no crossings, no second via level.

The gates are the constrained part, because their contacts can only live in
the thin band between the outermost active edge and the guard ring:

* the **first** gate net's contacts stub *inward* to the lowest lane in row 0
  (and the highest in row 1), which nothing else crosses;
* a gate net that is also one of its own device's source/drain nets (a
  diode-connected device) is joined *locally* on li1, gate landing pad
  straight to that unit's own pad, needing no lane at all;
* the **second** gate net stubs *outward* to a trunk drawn beyond the block's
  guard ring, where there is open space.

Row-0 and row-1 lanes are joined by vertical risers east of the block and drop
into the placement channels west of it, both bundles in strictly **nested**
order (see `bus_diff_pair`'s column-geometry comment). That nesting is what
keeps the escapes planar too, and it leaves every net a terminal in the open
channel south of the block, one north of it, and one on each side -- which is
what an inter-block router in a row-and-column floorplan actually needs.

Standard library only, matching every other script under `layout/bin/`.
"""

from __future__ import annotations

from typing import Any

import met1_bus

#: Height (um) of the first (innermost) lane above a row's lower active edge.
#: Must clear the gate stubs' met1 landing pads, which sit just outside the
#: active edge.
LANE0_UM = 0.7
#: Vertical pitch (um) between lanes inside one row. Comfortably above the
#: deck's `met1.space.1` (0.14) plus one wire width (0.24).
LANE_PITCH_UM = 0.6
#: Distance (um) from the block bbox to the innermost escape column/row.
ESCAPE_BASE_UM = 1.2
#: Pitch (um) between escape columns beside the block and between their
#: landing rows in the placement channels above and below it.
ESCAPE_PITCH_UM = 0.6
#: Minimum clearance (um) a lane must keep from its row's far active edge.
LANE_EDGE_MARGIN_UM = 0.5


def _units(report: dict[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
    """Group a `diff_pair` report's ports into `(device, index) -> terminals`.

    Port names are `<device>_<index>_<S|D|G>` -- the generator's own
    convention, validated here rather than assumed: an unparseable name raises
    instead of being silently dropped.
    """
    units: dict[tuple[str, int], dict[str, Any]] = {}
    for port in report["ports"]:
        name = port["name"]
        if name.startswith(("TAP_", "GAP_")):
            continue
        parts = name.split("_")
        if len(parts) != 3 or parts[2] not in ("S", "D", "G"):
            raise ValueError(f"unexpected diff_pair port name {name!r}")
        units.setdefault((parts[0], int(parts[1])), {})[parts[2]] = port
    for key, terms in units.items():
        missing = {"S", "D", "G"} - set(terms)
        if missing:
            raise ValueError(f"diff_pair unit {key} is missing ports {sorted(missing)}")
    return units


def _geometry(units: dict[tuple[str, int], dict[str, Any]]) -> dict[str, float]:
    """The unit device's width and both rows' lower active edges, derived from
    the generator's own reported port positions.

    A unit's source/drain ports sit on the pad's centre line and its gate port
    on the active region's upper edge, so ``w = 2 * (gate_y - source_y)`` and
    the row's lower edge is ``gate_y - w``. Deriving both this way (rather
    than re-using the `w_um` this flow passed to `klt gen`) keeps the bus
    honest if the generator ever changes how it stacks a unit.
    """
    widths = set()
    rows = set()
    for terms in units.values():
        gy = float(terms["G"]["y_um"])
        sy = float(terms["S"]["y_um"])
        widths.add(round(2.0 * (gy - sy), 6))
        rows.add(round(gy - 2.0 * (gy - sy), 6))
    if len(widths) != 1:
        raise ValueError(f"diff_pair units disagree on device width: {sorted(widths)}")
    if len(rows) != 2:
        raise ValueError(f"expected exactly 2 unit rows, found {sorted(rows)}")
    w = widths.pop()
    lo, hi = sorted(rows)
    return {"w_um": w, "row0_y_um": lo, "row1_y_um": hi, "core_y1_um": hi + w}


def bus_diff_pair(
    bus: met1_bus.Met1Bus,
    block_id: str,
    report: dict[str, Any],
    origin: dict[str, float],
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Tie one `diff_pair` block's unit devices into the schematic's nets.

    `spec["devices"]` maps each reported device label (`M1`/`M2` for a mirror,
    `Q1`/`Q2` for a pair) to its `{"S": net, "D": net, "G": net}` schematic
    nodes; `spec.get("device_labels")` names the schematic transistor each
    label was bound to, carried through into the record so the binding is
    evidence rather than a comment; `spec.get("ring_net")` names the node the
    block's guard-ring tap belongs to (the well tie for a pfet group, the
    substrate tie for an nfet one). Returns the evidence record for
    `bus-summary.json`, including the met1 points every net is reachable at
    from outside the block.

    The device-set check below is the teeth of that binding: a spec naming a
    device family this generator did not report is a caller that thinks it is
    wiring one transistor while the geometry belongs to another, which no DRC
    or drawn-short check can see.
    """
    units = _units(report)
    geom = _geometry(units)
    w = geom["w_um"]
    core_y0 = geom["row0_y_um"] + origin["y"]
    core_y1 = geom["core_y1_um"] + origin["y"]
    row_lo = geom["row0_y_um"]
    bbox = report["bbox_um"]
    bx0 = bbox["x0"] + origin["x"]
    bx1 = bbox["x1"] + origin["x"]
    by0 = bbox["y0"] + origin["y"]
    by1 = bbox["y1"] + origin["y"]
    devices: dict[str, dict[str, str]] = spec["devices"]
    if set(devices) != {dev for dev, _ in units}:
        raise ValueError(
            f"block {block_id}: spec devices {sorted(devices)} do not match the "
            f"generator's {sorted({dev for dev, _ in units})}"
        )

    def place(port: dict[str, Any]) -> tuple[float, float]:
        return (float(port["x_um"]) + origin["x"], float(port["y_um"]) + origin["y"])

    def row_of(terms: dict[str, Any]) -> int:
        return 0 if abs(float(terms["G"]["y_um"]) - (row_lo + w)) < 1e-6 else 1

    # --- how each device's gate gets connected ------------------------------
    local_gates: dict[str, str] = {}  # device -> which of its own pads to bond to
    routed_gate_nets: list[str] = []
    for dev in sorted(devices):
        gate = devices[dev]["G"]
        if gate == devices[dev]["S"]:
            local_gates[dev] = "S"
        elif gate == devices[dev]["D"]:
            local_gates[dev] = "D"
        elif gate not in routed_gate_nets:
            routed_gate_nets.append(gate)
    if len(routed_gate_nets) > 2:
        raise ValueError(
            f"block {block_id}: {len(routed_gate_nets)} gate nets need routing; "
            "the band between the outermost active edge and the guard ring only "
            "has room for one contact row per side (see module docstring)"
        )
    in_core_gate = routed_gate_nets[0] if routed_gate_nets else None
    outer_gate = routed_gate_nets[1] if len(routed_gate_nets) > 1 else None

    # --- lane assignment ----------------------------------------------------
    lanes: list[str] = []
    if in_core_gate:
        lanes.append(in_core_gate)
    for dev in sorted(devices):
        for term in ("S", "D"):
            net = devices[dev][term]
            if net == outer_gate:
                raise ValueError(
                    f"block {block_id}: net {net!r} is both the outboard gate net "
                    "and a source/drain net; that pair cannot be joined planarly"
                )
            if net not in lanes:
                lanes.append(net)
    ring_net = spec.get("ring_net")
    if ring_net and ring_net not in lanes:
        # The guard ring's node needs a lane even when no device pad carries
        # it: a pfet group's bulk terminal is the well the ring ties, and the
        # schematic names it, so leaving the ring floating would be a real
        # missing connection, not a cosmetic one.
        lanes.append(ring_net)
    span = LANE0_UM + LANE_PITCH_UM * (len(lanes) - 1)
    if span > w - LANE_EDGE_MARGIN_UM:
        raise ValueError(
            f"block {block_id}: {len(lanes)} lanes need {span:.2f} um but the "
            f"device is only {w:.2f} um wide"
        )

    def lane_y(index: int, row: int) -> float:
        offset = LANE0_UM + LANE_PITCH_UM * index
        return core_y0 + offset if row == 0 else core_y1 - offset

    # Column geometry. Both bundles are strictly *nested*, which is the whole
    # reason the bus stays planar on one metal:
    #
    #  * the east riser that joins a lane's two rows sits further out the
    #    *lower* its index, so a lane's riser is only ever crossed by lanes
    #    whose own rows lie outside its own span -- i.e. never;
    #  * the west feed runs further out the *higher* its index, so a lane's
    #    drop into the placement channel is only ever passed by lanes whose
    #    rows sit outside the drop -- again never.
    #
    # The result is that every lane has a terminal in the open channel south
    # of the block and one north of it, without a single crossing.
    def east_x(index: int) -> float:
        return bx1 + ESCAPE_BASE_UM + ESCAPE_PITCH_UM * (len(lanes) - 1 - index)

    def west_x(index: int) -> float:
        return bx0 - (ESCAPE_BASE_UM + ESCAPE_PITCH_UM * index)

    def south_y(index: int) -> float:
        return by0 - (ESCAPE_BASE_UM + ESCAPE_PITCH_UM * index)

    def north_y(index: int) -> float:
        return by1 + (ESCAPE_BASE_UM + ESCAPE_PITCH_UM * index)

    # The outboard gate net's trunks hug the block instead of running out
    # past the lane escapes. A trunk drawn *beyond* them would put a picket
    # fence of gate stubs across the whole depth of the placement channel
    # under the block, and every inter-block route that needs to pass beneath
    # that block would have to clear the fence -- which, with a block 340 um
    # wide, is most of them. Hugging the block keeps the stubs inside a 0.6 um
    # band just outside its bbox and leaves the channel open.
    outer_west_x = bx0 - ESCAPE_BASE_UM / 2.0
    outer_east_x = bx1 + ESCAPE_BASE_UM + ESCAPE_PITCH_UM * len(lanes)
    outer_below_y = by0 - ESCAPE_BASE_UM / 2.0
    outer_above_y = by1 + ESCAPE_BASE_UM / 2.0
    endpoints: dict[str, list[list[float]]] = {}
    gate_records: list[dict[str, Any]] = []

    def export(net: str, x: float, y: float) -> None:
        endpoints.setdefault(net, []).append([round(x, 3), round(y, 3)])

    # --- lanes: source/drain vias, the inboard gate net's stubs, escapes ----
    for index, net in enumerate(lanes):
        bus.net(net)
        for row in (0, 1):
            y = lane_y(index, row)
            for (dev, _n), terms in sorted(units.items()):
                if row_of(terms) != row:
                    continue
                for term in ("S", "D"):
                    if devices[dev][term] != net:
                        continue
                    px, _py = place(terms[term])
                    bus.via(px, y)
                if net == in_core_gate and devices[dev]["G"] == net:
                    gx, _gy = place(terms["G"])
                    edge = core_y0 if row == 0 else core_y1
                    _cx, cy = bus.gate_landing(
                        gx, edge, float(terms["G"]["width_um"]), -1 if row == 0 else 1
                    )
                    bus.via(gx, cy)
                    bus.vseg(gx, cy, y)
                    gate_records.append(
                        {"unit": f"{dev}_{_n}", "net": net, "style": "inboard lane"}
                    )
            bus.hseg(west_x(index), east_x(index), y)
        bus.vseg(east_x(index), lane_y(index, 0), lane_y(index, 1))
        bus.vseg(west_x(index), south_y(index), lane_y(index, 0))
        bus.vseg(west_x(index), lane_y(index, 1), north_y(index))
        export(net, west_x(index), south_y(index))
        export(net, west_x(index), north_y(index))
        export(net, east_x(index), lane_y(index, 0))
        export(net, east_x(index), lane_y(index, 1))
        export(net, west_x(index), lane_y(index, 0))
        export(net, west_x(index), lane_y(index, 1))

    # --- diode-connected devices: gate bonded to its own pad, on li1 --------
    for dev, term in sorted(local_gates.items()):
        net = devices[dev]["G"]
        bus.net(net)
        for (this_dev, _n), terms in sorted(units.items()):
            if this_dev != dev:
                continue
            row = row_of(terms)
            gx, _gy = place(terms["G"])
            px, _py = place(terms[term])
            edge = core_y0 if row == 0 else core_y1
            _cx, cy = bus.gate_landing(
                gx, edge, float(terms["G"]["width_um"]), -1 if row == 0 else 1
            )
            # One li1 conductor from the gate landing pad to this unit's own
            # pad: no via, no met1, and therefore no second met1 component to
            # reconcile -- the two are literally the same drawn shape. Drawn
            # as a single rectangle running *up to* the active edge rather
            # than as a narrower riser, which would leave a sliver of the
            # pad's own edge a few hundredths of a micron from the link -- a
            # `li1.space.1` violation even between shapes of one node.
            half = met1_bus.GATE_LI1_PAD_UM / 2.0
            bus.li1_rect(
                min(gx, px) - half,
                min(cy - half, edge),
                max(gx, px) + half,
                max(cy + half, edge),
            )
            gate_records.append(
                {"unit": f"{dev}_{_n}", "net": net, "style": f"li1 bond to {term}"}
            )

    # --- the outboard gate net: trunks beyond every lane escape -------------
    if outer_gate:
        bus.net(outer_gate)
        row_xs: dict[int, list[float]] = {0: [], 1: []}
        for (dev, _n), terms in sorted(units.items()):
            if devices[dev]["G"] != outer_gate:
                continue
            row = row_of(terms)
            gx, _gy = place(terms["G"])
            edge = core_y0 if row == 0 else core_y1
            _cx, cy = bus.gate_landing(
                gx, edge, float(terms["G"]["width_um"]), -1 if row == 0 else 1
            )
            bus.via(gx, cy)
            bus.vseg(gx, cy, outer_below_y if row == 0 else outer_above_y)
            row_xs[row].append(gx)
            gate_records.append(
                {"unit": f"{dev}_{_n}", "net": outer_gate, "style": "outboard trunk"}
            )
        for row, trunk_y in ((0, outer_below_y), (1, outer_above_y)):
            if not row_xs[row]:
                continue
            bus.hseg(outer_west_x, outer_east_x, trunk_y)
        # Joined on the east, beyond every lane escape column: the west side
        # is fenced off by the lane drops at that height.
        bus.vseg(outer_east_x, outer_below_y, outer_above_y)
        export(outer_gate, outer_west_x, outer_below_y)
        export(outer_gate, outer_west_x, outer_above_y)
        export(outer_gate, outer_east_x, outer_below_y)
        export(outer_gate, outer_east_x, outer_above_y)

    # --- guard-ring tap -----------------------------------------------------
    ring_record: dict[str, Any] | None = None
    if ring_net:
        ports = {p["name"]: p for p in report["ports"]}
        if "TAP_S" not in ports or "TAP_E" not in ports:
            raise KeyError(f"block {block_id}: no TAP_S/TAP_E guard-ring ports to tie")
        # The ring is one rectangular band inset from the block's own reported
        # bbox by a distance its own south tap port states; its west band
        # therefore sits under every lane's west feed, and one mcon dropped
        # where the ring net's feed already crosses it ties the whole ring --
        # no reach-around wire, and nothing else to keep out of the way of.
        inset = float(ports["TAP_S"]["y_um"]) + origin["y"] - by0
        contact_x = bx0 + inset
        contact_y = lane_y(lanes.index(ring_net), 0)
        bus.net(ring_net)
        bus.via(contact_x, contact_y)
        ring_record = {
            "net": ring_net,
            "tie": "mcon onto the ring's west band, under its own lane feed",
            "at_um": [round(contact_x, 3), round(contact_y, 3)],
        }

    return {
        "kind": "mos_diff_pair",
        "units": len(units),
        "device_width_um": round(w, 3),
        "device_labels": dict(spec.get("device_labels") or {}),
        "devices_nets": {half: dict(terms) for half, terms in devices.items()},
        "lanes": lanes,
        "inboard_gate_net": in_core_gate,
        "outboard_gate_net": outer_gate,
        "local_gate_devices": local_gates,
        "gate_contacts": gate_records,
        "ring": ring_record,
        "endpoints": endpoints,
    }
