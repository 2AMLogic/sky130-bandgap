#!/usr/bin/env python3
"""layout/bin/met1_bus.py -- draw intra-block busses on sky130's *second*
conductor (met1), reached through mcon, so an array's unit devices can be tied
into one electrical node without shorting to the pads they pass over.

Why this exists
---------------
`klt gen-compose`'s router resolves `routing.layer_role` through the same
`_PDK_ROLE_LAYERS` table `klt gen` draws with, and for sky130 that table
exposes exactly **one** routing metal role (`metal` -> li1 67/20) and no via
role. Every generator draws its device pads on that same li1. A wire that
buses several units of a matched array into one node therefore has to run
across that block's other pads on the only layer available, shorting to each
one it crosses. Upstream 2AMLogic/klayout-tools#433 recorded this; its merged
fix (klayout-tools#439) made the failure *visible* -- `gen-compose` now
reports such a self-net unroutable instead of certifying a short -- but
deliberately left the two options that would make bussing *expressible*
("expose a metal2/via role", "via-drop routing") as follow-ups. So the router
still cannot draw these wires.

The same tool's sky130 **extraction** deck, however, already declares a full
two-level stack:

    metals = ((67, 20), (68, 20))   # li1.drawing, met1.drawing
    vias   = ((67, 44),)            # mcon.drawing (li1 -> met1)

and `klt extract` wires it up (`connect(metals[0], vias[0])`,
`connect(vias[0], metals[1])`). A bus drawn on met1 with an mcon under each
landing pad is therefore ordinary, fully-modelled connectivity for the
extractor -- and, being on a different layer from every device pad, it can
cross a block's interior without touching anything. That is what this module
draws, with `klt draw` (the tool's own primitive write verb), from each
block's own reported `ports[]`.

This is a *layout-side* answer to the routing-metal half of #433, not a
substitute for the upstream capability: it hand-places every wire from
geometry this repo derives itself, where a router would plan them. Its limits
are recorded in `gen_bandgap_routed.py`'s note constants and in the generated
record.

DRC budget (checked by the sky130 curated deck, see
`klayout_tools.decks.sky130.DECK`)
----------------------------------------------------------------------------
* `met1.width.1`  -- min met1 width 0.14 um    -> WIRE_WIDTH_UM = 0.24
* `met1.space.1`  -- min met1 spacing 0.14 um  -> callers keep lanes >= 0.4 apart
* `met1.enclosing.mcon.1` -- min met1 enclosure of mcon 0.03 um
                          -> LANDING_UM (0.24) around VIA_UM (0.17) = 0.035
* `mcon.space.1`  -- min mcon spacing 0.19 um  -> callers place vias on the
                     block's own port pitch, which is far coarser

sky130 has no minimum li1 enclosure of mcon (`li.5` is 0.0 in the source
deck), so a via landing flush on a narrow li1 pad -- a `bjt_array` emitter pad
is 0.22 um wide -- is legal, and the curated deck models no such rule either.

Standard library only, matching every other script under `layout/bin/`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

# --- sky130 layers, all read from the tool's own published contract --------
#: `klayout_tools.decks.sky130.EXTRACTION_DECK.metals[0]` -- local interconnect,
#: the layer every `klt gen` generator draws its device pads on.
LI1_LAYER = [67, 20]
#: `...EXTRACTION_DECK.vias[0]` -- the li1 -> met1 via.
MCON_LAYER = [67, 44]
#: `...EXTRACTION_DECK.metals[1]` -- the second conductor this module routes on.
MET1_LAYER = [68, 20]
#: `...EXTRACTION_DECK.metal_labels[1]` -- names a met1 net for `klt extract`'s
#: pin promotion.
MET1_LABEL_LAYER = [68, 5]
#: `...EXTRACTION_DECK.poly` -- the gate conductor. Drawn by this module only
#: to give a gate contact a landing area outside the channel (see
#: :meth:`Met1Bus.gate_contact`).
POLY_LAYER = [66, 20]
#: `...EXTRACTION_DECK.contact` -- the poly/active -> li1 contact.
LICON_LAYER = [66, 44]

#: mcon drawn size (um). sky130's mcon is a fixed 0.17 um square.
VIA_UM = 0.17
#: met1 landing-pad side (um) around one via: 0.24 encloses a 0.17 via by
#: 0.035 > the deck's 0.03 `met1.enclosing.mcon.1` threshold.
LANDING_UM = 0.24
#: met1 wire width (um): same as the landing pad, so a wire ending on a via
#: satisfies the enclosure rule along its own axis too.
WIRE_WIDTH_UM = 0.24

# --- gate-contact stack (the layout-side answer to klayout-tools#461) ------
#: licon side (um). sky130's licon1 is a fixed square; 0.22 is the same size
#: `klt gen`'s own source/drain contacts use, so this draws nothing the
#: generator does not already draw elsewhere in the cell.
LICON_UM = 0.22
#: Poly enclosure of the licon (um) on every side. The sky130 curated deck's
#: `poly.enclosing.licon.1` threshold is 0.05; 0.06 clears it with margin.
LICON_POLY_ENCLOSURE_UM = 0.06
#: How far the gate poly is extended past the active edge (um) so the licon
#: above has somewhere legal to land: enclosure + licon + enclosure.
GATE_POLY_EXT_UM = LICON_UM + 2 * LICON_POLY_ENCLOSURE_UM
#: Distance (um) from the active edge to the gate contact's centre.
GATE_CONTACT_OFFSET_UM = GATE_POLY_EXT_UM / 2.0
#: li1 landing pad side (um) over the gate licon. Wider than the deck's
#: `li1.width.1` (0.17) minimum and wide enough to cover the licon.
GATE_LI1_PAD_UM = 0.30


#: Side (um) of one spatial-index bucket. Comfortably larger than any wire
#: this module draws, so a rectangle lands in one or two buckets.
GRID_UM = 4.0


def _cells(x0: float, y0: float, x1: float, y1: float):
    """Every grid bucket a box touches."""
    i0, i1 = int(x0 // GRID_UM), int(x1 // GRID_UM)
    j0, j1 = int(y0 // GRID_UM), int(y1 // GRID_UM)
    for i in range(i0, i1 + 1):
        for j in range(j0, j1 + 1):
            yield (i, j)


class Met1Bus:
    """Accumulates met1/mcon shapes and met1 net labels for one `klt draw` cell.

    Coordinates are in the *composed cell's* frame: callers add each block's
    placement origin before handing a port position here, so one overlay cell
    placed at (0, 0) carries every block's bussing.
    """

    def __init__(self) -> None:
        self.shapes: list[dict[str, Any]] = []
        self.labels: list[dict[str, Any]] = []
        self.via_count = 0
        self.wire_count = 0
        #: (net_id, x0, y0, x1, y1) for every met1 rectangle drawn, used by
        #: :func:`conflicts` to prove no two *different* nets' wires touch or
        #: come closer than the deck's `met1.space.1` threshold. Nothing else
        #: in this flow can tell a drawn short from drawn connectivity, so
        #: this record is the safety net that makes hand-placed bussing
        #: honest evidence rather than a hope.
        self.met1_rects: list[tuple[str, float, float, float, float]] = []
        #: Uniform-grid index over `met1_rects`, so a proximity query costs a
        #: handful of bucket lookups instead of a scan. Without it the
        #: rip-up-and-retry router below is quadratic in the number of drawn
        #: rectangles *per attempted path*, which a fully bussed floorplan
        #: (thousands of rectangles, thousands of candidate paths) turns into
        #: minutes of wall time per pass.
        self._grid: dict[tuple[int, int], list[int]] = {}
        #: (net_id, x, y) per drawn mcon, for the `mcon.space.1` proximity
        #: half of :func:`conflicts`.
        self.via_xy: list[tuple[str, float, float]] = []
        self._vias: set[tuple[str, float, float]] = set()
        #: (net_id, x0, y0, x1, y1) per drawn poly extension, so a caller can
        #: prove no two gate nets' self-drawn poly comes within sky130's real
        #: `poly.2` minimum poly spacing -- a rule the curated DRC deck does
        #: not model, and therefore one this flow has to check itself.
        self.poly_rects: list[tuple[str, float, float, float, float]] = []
        self.gate_contact_count = 0
        self._net = "?"

    def net(self, net_id: str) -> "Met1Bus":
        """Tag every subsequent shape as belonging to electrical node `net_id`."""
        self._net = net_id
        return self

    # -- primitives --------------------------------------------------------
    def _rect(self, layer: list[int], x0: float, y0: float, x1: float, y1: float) -> None:
        self.shapes.append({"layer": layer, "rect_um": [x0, y0, x1, y1]})
        if layer == MET1_LAYER:
            index = len(self.met1_rects)
            self.met1_rects.append((self._net, x0, y0, x1, y1))
            for cell in _cells(x0, y0, x1, y1):
                self._grid.setdefault(cell, []).append(index)
        elif layer == POLY_LAYER:
            self.poly_rects.append((self._net, x0, y0, x1, y1))

    def near(
        self, x0: float, y0: float, x1: float, y1: float, pad: float = 0.0
    ) -> set[int]:
        """Indices into `met1_rects` whose grid cells touch the padded box."""
        found: set[int] = set()
        for cell in _cells(x0 - pad, y0 - pad, x1 + pad, y1 + pad):
            found.update(self._grid.get(cell, ()))
        return found

    def truncate(self, shape_mark: int, met1_mark: int) -> None:
        """Undo every shape drawn since a mark, index included.

        The router draws a candidate path optimistically and rolls it back
        when it collides; the grid has to shrink with it or a later query
        would report ghosts.
        """
        for index in range(met1_mark, len(self.met1_rects)):
            _net, x0, y0, x1, y1 = self.met1_rects[index]
            for cell in _cells(x0, y0, x1, y1):
                bucket = self._grid.get(cell)
                if bucket and bucket[-1] == index:
                    bucket.pop()
                elif bucket and index in bucket:
                    bucket.remove(index)
        del self.met1_rects[met1_mark:]
        del self.shapes[shape_mark:]

    def li1_rect(self, x0: float, y0: float, x1: float, y1: float) -> None:
        """One li1 rectangle.

        li1 is the layer every `klt gen` device pad already sits on, so a
        shape drawn here is *the same conductor* as any pad it overlaps or
        abuts -- no via, no second metal, and nothing for :func:`components`
        to reconcile. Used only where the two ends belong to the same node by
        construction (a diode-connected device's gate landing pad and that
        unit's own pad, a few tenths of a micron apart); anything longer
        belongs on met1, above the pads.
        """
        self._rect(LI1_LAYER, x0, y0, x1, y1)

    def gate_landing(
        self, x: float, edge_y: float, poly_width_um: float, outward: int
    ) -> tuple[float, float]:
        """Give one MOS gate a contactable landing area outside the channel.

        `klt gen`'s sky130 MOS generators draw the gate poly with *exactly*
        the active region's extent and report the gate port on that shared
        boundary, so there is no poly outside the channel for a contact to
        land on and a gate cannot be wired to anything at all
        (2AMLogic/klayout-tools#461). Real transistor layouts always draw a
        poly extension past the active edge for precisely this purpose, so
        this method draws the missing piece from the generator's own reported
        gate port: a poly rectangle of the port's own reported width extended
        `GATE_POLY_EXT_UM` past `edge_y` in direction `outward` (+1 = north,
        -1 = south), a licon centred in it, and an li1 pad over the licon.

        Deliberately *not* a contact on the reported port position: that
        straddles the diff edge and is DRC-illegal (`poly.enclosing.licon.1`
        and `diff.enclosing.licon.1`), and one moved inward sits on poly over
        the channel. Both are what makes the upstream gap a gap; drawing
        either to make a number move would be false evidence.

        Returns the li1 landing pad's centre. The caller decides how the node
        leaves it -- :meth:`via` up to met1, or :meth:`li1_rect` sideways to a
        pad of the same node on the same layer.
        """
        half_poly = poly_width_um / 2.0
        ext_far = edge_y + outward * GATE_POLY_EXT_UM
        self._rect(
            POLY_LAYER, x - half_poly, min(edge_y, ext_far), x + half_poly,
            max(edge_y, ext_far),
        )
        cy = edge_y + outward * GATE_CONTACT_OFFSET_UM
        half = LICON_UM / 2.0
        self._rect(LICON_LAYER, x - half, cy - half, x + half, cy + half)
        half = GATE_LI1_PAD_UM / 2.0
        self._rect(LI1_LAYER, x - half, cy - half, x + half, cy + half)
        self.gate_contact_count += 1
        return (x, cy)

    def via(self, x: float, y: float) -> None:
        """One mcon + its met1 landing pad, centred at (x, y).

        The caller is responsible for (x, y) landing on the li1 pad it means
        to contact -- every call site derives it from a generator-reported
        port position, never from a re-read of the block's GDS.

        A repeat call at a position already contacted by the *same* net is a
        no-op: two coincident mcons are one via drawn twice, and the
        duplicate would trip the deck's `mcon.space.1` rule.
        """
        key = (self._net, round(x, 4), round(y, 4))
        if key in self._vias:
            return
        self._vias.add(key)
        self.via_xy.append((self._net, x, y))
        h = VIA_UM / 2.0
        self._rect(MCON_LAYER, x - h, y - h, x + h, y + h)
        h = LANDING_UM / 2.0
        self._rect(MET1_LAYER, x - h, y - h, x + h, y + h)
        self.via_count += 1

    def hseg(self, x0: float, x1: float, y: float) -> None:
        """One horizontal met1 segment (no vias)."""
        if x0 == x1:
            return
        h = WIRE_WIDTH_UM / 2.0
        self._rect(MET1_LAYER, min(x0, x1), y - h, max(x0, x1), y + h)
        self.wire_count += 1

    def vseg(self, x: float, y0: float, y1: float) -> None:
        """One vertical met1 segment (no vias)."""
        if y0 == y1:
            return
        h = WIRE_WIDTH_UM / 2.0
        self._rect(MET1_LAYER, x - h, min(y0, y1), x + h, max(y0, y1))
        self.wire_count += 1

    def elbow(
        self, x0: float, y0: float, x1: float, y1: float, vertical_first: bool = False
    ) -> None:
        """One orthogonal two-segment met1 path between two points."""
        if vertical_first:
            self.vseg(x0, y0, y1)
            self.hseg(x0, x1, y1)
        else:
            self.hseg(x0, x1, y0)
            self.vseg(x1, y0, y1)

    def label(self, net: str, x: float, y: float) -> None:
        """Name a met1 net so `klt extract` promotes it as a top-level pin."""
        self.labels.append({"layer": MET1_LABEL_LAYER, "text": net, "at_um": [x, y]})

    # -- speculation -------------------------------------------------------
    def mark(self) -> tuple[int, ...]:
        """A restore point covering every mutable accumulator on this bus.

        Callers use it to *try* a whole multi-hop net and take it back if it
        does not route, which is what lets a router compare candidate
        terminal orderings against real drawn geometry rather than against a
        model of it.

        Every accumulator is covered, the *derived* ones included: the
        `met1_rects` spatial index (unwound by :meth:`truncate`) and the
        self-drawn poly/gate-contact tallies. A restore point that missed one
        would leave the collision checker reasoning about geometry the emitted
        cell does not contain -- the exact failure speculation exists to avoid.
        """
        return (len(self.shapes), len(self.met1_rects), len(self.via_xy),
                len(self.labels), self.via_count, self.wire_count,
                len(self.poly_rects), self.gate_contact_count)

    def restore(self, mark: tuple[int, ...]) -> None:
        """Undo every shape, rectangle, via, label and poly added since `mark`."""
        (shapes, rects, vias, labels, via_count, wire_count,
         polys, gate_contacts) = mark
        for net, x, y in self.via_xy[vias:]:
            self._vias.discard((net, round(x, 4), round(y, 4)))
        self.via_count = via_count
        self.wire_count = wire_count
        self.gate_contact_count = gate_contacts
        # Shapes and met1 rectangles go through `truncate` so the grid index
        # shrinks with them; deleting the lists directly would leave the index
        # pointing at rectangles that no longer exist.
        self.truncate(shapes, rects)
        del self.via_xy[vias:]
        del self.labels[labels:]
        del self.poly_rects[polys:]

    # -- verification ------------------------------------------------------
    def conflicts(self, clearance_um: float = 0.14) -> list[dict[str, Any]]:
        """Every pair of met1 rectangles belonging to *different* nets that
        touch, overlap, or sit closer than `clearance_um`.

        `clearance_um` defaults to the sky130 curated deck's `met1.space.1`
        threshold, so an empty result means both "no drawn short between two
        electrical nodes" and "no met1 spacing violation between them". A
        non-empty result is a flow failure, never a warning: a drawn short
        that DRC happens not to flag is exactly the class of false evidence
        this module exists to avoid producing.
        """
        found: list[dict[str, Any]] = []
        eps = clearance_um - 1e-9
        # mcon-to-mcon: sky130's `ct.2` minimum mcon spacing is 0.19 um, and
        # two vias of different nets that close are also very nearly a short.
        via_space = 0.19 - 1e-9
        via_reach = VIA_UM + via_space
        via_grid: dict[tuple[int, int], list[int]] = {}
        for i, (_net, x, y) in enumerate(self.via_xy):
            for cell in _cells(x - via_reach, y - via_reach, x + via_reach, y + via_reach):
                via_grid.setdefault(cell, []).append(i)
        seen_pairs: set[tuple[int, int]] = set()
        for bucket in via_grid.values():
            for pos, i in enumerate(bucket):
                net_a, ax, ay = self.via_xy[i]
                for j in bucket[pos + 1 :]:
                    if (i, j) in seen_pairs:
                        continue
                    seen_pairs.add((i, j))
                    net_b, bx, by = self.via_xy[j]
                    if net_a == net_b:
                        continue
                    if abs(ax - bx) < via_reach and abs(ay - by) < via_reach:
                        found.append(
                            {"nets": [net_a, net_b], "via_a": [ax, ay], "via_b": [bx, by]}
                        )
        rects = self.met1_rects
        for i, (net_a, ax0, ay0, ax1, ay1) in enumerate(rects):
            for j in self.near(ax0, ay0, ax1, ay1, clearance_um):
                if j <= i:
                    continue
                net_b, bx0, by0, bx1, by1 = rects[j]
                if net_a == net_b:
                    continue
                if ax0 - eps < bx1 and bx0 - eps < ax1 and ay0 - eps < by1 and by0 - eps < ay1:
                    found.append(
                        {
                            "nets": [net_a, net_b],
                            "a": [ax0, ay0, ax1, ay1],
                            "b": [bx0, by0, bx1, by1],
                        }
                    )
        return found

    def poly_conflicts(self, clearance_um: float = 0.21) -> list[dict[str, Any]]:
        """Every pair of *self-drawn* poly rectangles of different nets closer
        than `clearance_um`.

        The sky130 curated DRC deck models `poly.width.1` but no poly spacing
        rule, so `klt drc` cannot see a gate-extension pair drawn too close
        together. The real sky130 rule (`poly.2`, minimum poly spacing) is
        0.21 um; this check applies it to the geometry this module adds so a
        gate-contact extension can never quietly short two gate nets.
        """
        found: list[dict[str, Any]] = []
        eps = clearance_um - 1e-9
        rects = self.poly_rects
        for i, (net_a, ax0, ay0, ax1, ay1) in enumerate(rects):
            for net_b, bx0, by0, bx1, by1 in rects[i + 1 :]:
                if net_a == net_b:
                    continue
                if ax0 - eps < bx1 and bx0 - eps < ax1 and ay0 - eps < by1 and by0 - eps < ay1:
                    found.append(
                        {
                            "nets": [net_a, net_b],
                            "a": [ax0, ay0, ax1, ay1],
                            "b": [bx0, by0, bx1, by1],
                        }
                    )
        return found

    def components(self) -> dict[str, int]:
        """How many disjoint pieces of met1 each net's drawn wiring falls into.

        A net drawn as two pieces that never touch is *not* a connected node,
        however confidently the net id says otherwise -- and unlike a drawn
        short, nothing downstream reports it as an error: `klt extract` simply
        sees two anonymous nets. Counting connected components per net id is
        the matching safety net to :func:`conflicts`: 1 means the wiring this
        flow drew for that node is genuinely one conductor.

        Rectangles are joined when they touch or overlap (a shared edge is a
        connection on one metal layer). Nets that legitimately close through
        li1 rather than met1 are the caller's business to exclude.
        """
        by_net: dict[str, list[tuple[float, float, float, float]]] = {}
        for net, x0, y0, x1, y1 in self.met1_rects:
            by_net.setdefault(net, []).append((x0, y0, x1, y1))
        out: dict[str, int] = {}
        eps = 1e-9
        for net, rects in by_net.items():
            parent = list(range(len(rects)))

            def find(i: int) -> int:
                while parent[i] != i:
                    parent[i] = parent[parent[i]]
                    i = parent[i]
                return i

            local: dict[tuple[int, int], list[int]] = {}
            for i, (x0, y0, x1, y1) in enumerate(rects):
                for cell in _cells(x0 - eps, y0 - eps, x1 + eps, y1 + eps):
                    local.setdefault(cell, []).append(i)
            for bucket in local.values():
                for pos, i in enumerate(bucket):
                    ax0, ay0, ax1, ay1 = rects[i]
                    for j in bucket[pos + 1 :]:
                        bx0, by0, bx1, by1 = rects[j]
                        if (
                            ax0 - eps <= bx1
                            and bx0 - eps <= ax1
                            and ay0 - eps <= by1
                            and by0 - eps <= ay1
                        ):
                            ri, rj = find(i), find(j)
                            if ri != rj:
                                parent[ri] = rj
            out[net] = len({find(i) for i in range(len(rects))})
        return out

    # -- emit --------------------------------------------------------------
    def emit(
        self, klt: str, out_dir: Path, cell_name: str, pdk: dict[str, Any], note: str
    ) -> dict[str, Any]:
        """Write the overlay with `klt draw` and return a `klt gen`-shaped report.

        The returned report declares a **degenerate (zero-area) bbox** on
        purpose: `klt gen-compose` treats every placed block's reported bbox
        as a routing obstacle, and an overlay spanning the whole floorplan
        would otherwise veto every remaining inter-block route. The overlay's
        geometry is still copied into the composed cell in full -- the bbox is
        only consulted by the router's obstacle test. (The same technique the
        retired PNP-recognition overlay used before upstream
        klayout-tools#440 made it unnecessary.)
        """
        params = {"shapes": self.shapes, "labels": self.labels}
        params_path = out_dir / f"{cell_name}.draw.json"
        params_path.write_text(json.dumps(params, indent=2) + "\n")
        gds_path = out_dir / f"{cell_name}.gds"
        result = subprocess.run(
            [
                klt,
                "draw",
                "--params",
                str(params_path),
                "--cell-name",
                cell_name,
                "-o",
                str(gds_path),
                "--format",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"klt draw failed ({result.returncode}):\n{result.stderr}")
        draw_report = json.loads(result.stdout)
        (out_dir / f"{cell_name}.draw.report.json").write_text(
            json.dumps(draw_report, indent=2) + "\n"
        )

        gen_report = {
            "schema_version": 1,
            "generator": "draw",
            "cell_name": cell_name,
            "gds_path": str(gds_path.resolve()),
            "pdk": pdk,
            "bbox_um": {"x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 0.0},
            "device_count": 0,
            "ports": [],
            "drc_hints": {
                "min_spacing_um": None,
                "matched_group_id": None,
                "snapped_to_grid": False,
                "notes": [note],
            },
            "warnings": [],
            "met1_via_count": self.via_count,
            "met1_wire_count": self.wire_count,
            "met1_label_count": len(self.labels),
            "gate_contact_count": self.gate_contact_count,
        }
        (out_dir / f"{cell_name}.gen.json").write_text(
            json.dumps(gen_report, indent=2) + "\n"
        )
        return gen_report
