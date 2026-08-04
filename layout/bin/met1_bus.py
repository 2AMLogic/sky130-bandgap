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
#: `...EXTRACTION_DECK.contact` -- the poly/diff -> li1 contact. Drawn by this
#: module only on a MOS **gate landing pad** (see :meth:`Met1Bus.gate_contact`).
LICON_LAYER = [66, 44]

#: mcon drawn size (um). sky130's mcon is a fixed 0.17 um square.
VIA_UM = 0.17
#: licon drawn size (um). Same fixed 0.17 um square as mcon in sky130.
LICON_UM = 0.17
#: met1 landing-pad side (um) around one via: 0.24 encloses a 0.17 via by
#: 0.035 > the deck's 0.03 `met1.enclosing.mcon.1` threshold.
LANDING_UM = 0.24
#: met1 wire width (um): same as the landing pad, so a wire ending on a via
#: satisfies the enclosure rule along its own axis too.
WIRE_WIDTH_UM = 0.24
#: li1 width (um) of the gate riser :meth:`Met1Bus.gate_contact` draws. Above
#: the deck's 0.17 um `li1.width.1` minimum, and wide enough to enclose both
#: the licon under it and the mcon on top of it.
GATE_LI1_UM = 0.24
#: Cell size (um) of the met1 proximity index below. Large enough that a
#: typical wire touches only a few cells, small enough that a cell holds only
#: a few wires.
GRID_UM = 8.0
#: sky130 `li1.space.1` (um) -- the clearance :meth:`Met1Bus.conflicts` holds
#: every pair of *different*-net li1 shapes this module draws to.
LI1_SPACE_UM = 0.17


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
        #: (net_id, x, y) per drawn mcon, for the `mcon.space.1` proximity
        #: half of :func:`conflicts`.
        self.via_xy: list[tuple[str, float, float]] = []
        #: (net_id, x0, y0, x1, y1) for every li1 rectangle *this module*
        #: draws -- only the gate risers of :meth:`gate_contact`. Checked to
        #: the deck's `li1.space.1` for the same reason `met1_rects` is: a
        #: hand-placed conductor that touches another node's conductor is a
        #: short, and li1 is the layer every device pad already lives on.
        self.li1_rects: list[tuple[str, float, float, float, float]] = []
        #: (cell -> met1_rects indices) proximity index, see `met1_near`.
        self._grid: dict[tuple[int, int], list[int]] = {}
        self.gate_contact_count = 0
        self._vias: set[tuple[str, float, float]] = set()
        self._net = "?"

    def net(self, net_id: str) -> "Met1Bus":
        """Tag every subsequent shape as belonging to electrical node `net_id`."""
        self._net = net_id
        return self

    # -- primitives --------------------------------------------------------
    def _rect(self, layer: list[int], x0: float, y0: float, x1: float, y1: float) -> None:
        self.shapes.append({"layer": layer, "rect_um": [x0, y0, x1, y1]})
        if layer == MET1_LAYER:
            self._index_met1(len(self.met1_rects), x0, y0, x1, y1)
            self.met1_rects.append((self._net, x0, y0, x1, y1))
        elif layer == LI1_LAYER:
            self.li1_rects.append((self._net, x0, y0, x1, y1))

    # -- met1 spatial index -----------------------------------------------
    # A route search asks "does this rectangle come within met1.space.1 of
    # anything already drawn?" tens of thousands of times per run, and a full
    # scan of every drawn rectangle makes the answer O(n) each. The index
    # buckets rectangles into GRID_UM cells so the scan only touches the
    # handful that could possibly be near -- which is what makes it affordable
    # to try a large candidate-path set per hop rather than giving up early
    # and reporting a node unroutable.
    def _cells(self, x0: float, y0: float, x1: float, y1: float):
        for ix in range(int(x0 // GRID_UM), int(x1 // GRID_UM) + 1):
            for iy in range(int(y0 // GRID_UM), int(y1 // GRID_UM) + 1):
                yield (ix, iy)

    def _index_met1(self, position: int, x0: float, y0: float, x1: float, y1: float) -> None:
        for cell in self._cells(x0, y0, x1, y1):
            self._grid.setdefault(cell, []).append(position)

    def met1_near(
        self, x0: float, y0: float, x1: float, y1: float, clearance: float
    ):
        """Every already-drawn met1 rectangle within `clearance` of the box,
        as `(net, x0, y0, x1, y1)`. Box (Chebyshev) proximity, i.e. slightly
        stricter than the deck's Euclidean `met1.space.1` -- deliberately, so
        a route this accepts can never be one DRC rejects."""
        seen: set[int] = set()
        for cell in self._cells(
            x0 - clearance, y0 - clearance, x1 + clearance, y1 + clearance
        ):
            for position in self._grid.get(cell, ()):  # noqa: B007
                if position in seen:
                    continue
                seen.add(position)
                net_b, bx0, by0, bx1, by1 = self.met1_rects[position]
                if (
                    x0 - clearance < bx1
                    and bx0 - clearance < x1
                    and y0 - clearance < by1
                    and by0 - clearance < y1
                ):
                    yield (net_b, bx0, by0, bx1, by1)

    def truncate_met1(self, count: int) -> None:
        """Drop every met1 rectangle from `count` on, index included."""
        for position in range(count, len(self.met1_rects)):
            _net, x0, y0, x1, y1 = self.met1_rects[position]
            for cell in self._cells(x0, y0, x1, y1):
                bucket = self._grid.get(cell)
                if bucket and bucket[-1] == position:
                    bucket.pop()
                elif bucket and position in bucket:
                    bucket.remove(position)
        del self.met1_rects[count:]

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

    def gate_contact(self, x: float, gate_y: float, to_y: float) -> None:
        """Contact one MOS gate at its reported poly landing pad `(x, gate_y)`
        and run an li1 riser from it to `to_y`, so an ordinary
        :meth:`via` at `(x, to_y)` can lift the gate onto met1.

        This is what upstream 2AMLogic/klayout-tools#461 (merged via #474)
        made drawable at all. Before it, `klt gen`'s MOS generators drew the
        gate poly with exactly the active region's extent and reported the
        gate port on the shared poly/diff boundary, so no contact could be
        placed legally: one at the port straddled the diff edge and one moved
        inward sat on poly over the channel. The generators now extend the
        first finger's poly past the diffusion into a
        contact-region-sized landing pad and report the port at its centre.

        Three shapes, all sized from the deck's own thresholds:

        * a `LICON_UM` licon centred on the pad -- the pad is a
          contact-region square, so the poly encloses this by well over the
          deck's 0.05 um `poly.enclosing.licon.1`, and it sits entirely
          outside the diffusion;
        * an `GATE_LI1_UM`-wide li1 riser spanning `gate_y` .. `to_y`, which
          both covers the licon and reaches down into the device row where
          the bus trunk runs. It passes *over* the gate poly and the channel,
          which is ordinary routing -- it carries the gate's own node, and
          without a licon under it it connects to nothing else;
        * nothing on met1: the caller places the mcon with :meth:`via`.

        `to_y` deliberately lands inside the device row rather than outside
        it. A MOS row's source/drain pads are full-height li1 strips, so a
        bus trunk can drop its via anywhere along them -- and putting the
        gate's via on the same horizontal track removes the only stub that
        would have had to cross another node's trunk.
        """
        h = LICON_UM / 2.0
        self._rect(LICON_LAYER, x - h, gate_y - h, x + h, gate_y + h)
        w = GATE_LI1_UM / 2.0
        y0, y1 = min(gate_y, to_y), max(gate_y, to_y)
        self._rect(LI1_LAYER, x - w, y0 - w, x + w, y1 + w)
        self.gate_contact_count += 1

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
        """
        return (len(self.shapes), len(self.met1_rects), len(self.via_xy),
                len(self.labels), self.via_count, self.wire_count,
                len(self.li1_rects), self.gate_contact_count)

    def restore(self, mark: tuple[int, ...]) -> None:
        """Undo every shape, rectangle, via, gate contact and label added
        since `mark`."""
        (shapes, rects, vias, labels, via_count, wire_count, li1_rects,
         gate_contacts) = mark
        for net, x, y in self.via_xy[vias:]:
            self._vias.discard((net, round(x, 4), round(y, 4)))
        self.via_count = via_count
        self.wire_count = wire_count
        self.gate_contact_count = gate_contacts
        del self.shapes[shapes:]
        self.truncate_met1(rects)
        del self.via_xy[vias:]
        del self.labels[labels:]
        del self.li1_rects[li1_rects:]

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
        for i, (net_a, ax, ay) in enumerate(self.via_xy):
            for net_b, bx, by in self.via_xy[i + 1 :]:
                if net_a == net_b:
                    continue
                if abs(ax - bx) < VIA_UM + via_space and abs(ay - by) < VIA_UM + via_space:
                    found.append(
                        {"nets": [net_a, net_b], "via_a": [ax, ay], "via_b": [bx, by]}
                    )
        for layer, rects, clearance in (
            ("met1", self.met1_rects, eps),
            # The gate risers of `gate_contact` are the only li1 this module
            # draws, and they are checked against each other to sky130's
            # `li1.space.1`. Their clearance to the *generators'* own li1 pads
            # is not checked here (this module never sees that geometry) --
            # that one is held by construction, since a riser runs down the
            # gate's own column gap, and it is `klt drc` on the composed cell
            # that has the whole picture and proves it.
            ("li1", self.li1_rects, LI1_SPACE_UM - 1e-9),
        ):
            for i, (net_a, ax0, ay0, ax1, ay1) in enumerate(rects):
                for net_b, bx0, by0, bx1, by1 in rects[i + 1 :]:
                    if net_a == net_b:
                        continue
                    if (
                        ax0 - clearance < bx1
                        and bx0 - clearance < ax1
                        and ay0 - clearance < by1
                        and by0 - clearance < ay1
                    ):
                        found.append(
                            {
                                "layer": layer,
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
        the matching safety net to :meth:`conflicts`: 1 means the wiring this
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
                for cell in self._cells(x0 - eps, y0 - eps, x1 + eps, y1 + eps):
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
        }
        (out_dir / f"{cell_name}.gen.json").write_text(
            json.dumps(gen_report, indent=2) + "\n"
        )
        return gen_report
