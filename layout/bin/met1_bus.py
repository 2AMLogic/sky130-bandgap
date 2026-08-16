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

The same tool's sky130 **extraction** deck, however, already declares a
multi-level stack. Since 2AMLogic/klayout-tools#508 (merged via #511) it is
three levels deep:

    metals = ((67, 20), (68, 20), (69, 20))  # li1, met1, met2 (.drawing)
    vias   = ((67, 44), (68, 44))            # mcon (li1->met1), via (met1->met2)

and `klt extract` wires it up (`connect(metals[i], vias[i])`,
`connect(vias[i], metals[i+1])`). A bus drawn on met1 with an mcon under each
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

The met2 escape plane (new, klayout-tools#511)
----------------------------------------------------------------------------
Every bus and every inter-block net above is drawn on met1, and on this
floorplan met1 saturates: three schematic inter-block hops had no met1
corridor left at all, whatever lane/margin/placement lever was pulled at them
(`layout/matching-plan.md` Sections 7d-7o). Until #511 there was no other
plane -- sky130's curated deck stopped at met1, so klayout-tools#454/#468's
`"metal2"` role resolved to the *same* met1 layer this module already fills
(ROUTING_PLANE_NOTE). #511 adds met2 as a genuine third connectivity level.

:meth:`Met1Bus.via1` and :meth:`Met1Bus.hseg2`/:meth:`Met1Bus.vseg2` draw on
it: a met1 landing pad, a `via.drawing` (68/44) cut, a met2 landing pad, and
met2 wire between two such stacks. A met2 route is a strict *escape hatch*,
tried only after every met1 form in `gen_bandgap_routed.py`'s `_connect` has
been rolled back -- met1 stays the primary plane, so this adds an unshared
corridor rather than moving the flow's routing onto a layer whose DRC the
curated deck does not model (see below).

DRC budget
----------------------------------------------------------------------------
Checked by the sky130 curated deck (`klayout_tools.decks.sky130.DECK`), i.e.
proven by this flow's own `klt drc` stage:

* `met1.width.1`  -- min met1 width 0.14 um    -> WIRE_WIDTH_UM = 0.24
* `met1.space.1`  -- min met1 spacing 0.14 um  -> callers keep lanes >= 0.4 apart
* `met1.enclosing.mcon.1` -- min met1 enclosure of mcon 0.03 um
                          -> LANDING_UM (0.24) around VIA_UM (0.17) = 0.035
* `mcon.space.1`  -- min mcon spacing 0.19 um  -> callers place vias on the
                     block's own port pitch, which is far coarser

Held by construction here and re-proved by this module's own
:meth:`Met1Bus.conflicts` regardless of what the curated deck checks:
klayout-tools#513 (merged via #515) gave the curated deck met2/via1 width,
spacing and enclosure rules, but not the met2 min-area rule (`m2.6`, left
out because the curated deck's rule vocabulary has no `area` check
primitive) and not a net-aware short check (`m2.2`'s width/space rule sees
geometry, not electrical identity, so two different nodes' met2 that
actually *touch* -- no gap between them -- is not a spacing violation for
`klt drc` to catch; :meth:`conflicts` is what does). The sizes below are
taken from the sky130A source deck the PDK install ships
(`libs.tech/klayout/drc/sky130A_mr.drc`), not from convention:

* `m2.1`   -- min met2 width 0.14 um            -> MET2_WIRE_WIDTH_UM = 0.32
* `m2.2`   -- min met2 spacing 0.14 um          -> MET2_SPACE_UM, enforced by
              :meth:`conflicts` and by the route guard, exactly as
              `met1.space.1` is for met1
* `m2.6`   -- min met2 area 0.0676 um^2         -> a 0.32 x 0.32 pad is
              0.1024 um^2
* `via.1a` -- via is exactly 0.15 x 0.15 um     -> VIA1_UM = 0.15
* `via.2`  -- min via spacing 0.17 um           -> VIA1_SPACE_UM
* `via.4a`/`via.5a` -- min met1 enclosure of via 0.055 um, 0.085 um on two
              adjacent edges -> MET1_VIA1_LANDING_UM (0.32) gives 0.085 on
              *all four*
* `m2.4`/`m2.5` -- min met2 enclosure of via 0.055 um, 0.085 um on two
              adjacent edges -> MET2_LANDING_UM (0.32) gives 0.085 on all four

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
#: `...EXTRACTION_DECK.vias[1]` -- `via.drawing`, the met1 -> met2 via. New
#: with 2AMLogic/klayout-tools#508 (merged via #511); before it the sky130
#: curated deck's connectivity graph stopped at met1.
VIA1_LAYER = [68, 44]
#: `...EXTRACTION_DECK.metals[2]` -- met2, the third conductor and the escape
#: plane this module falls back to when met1 has no corridor left.
MET2_LAYER = [69, 20]
#: `...EXTRACTION_DECK.metal_labels[2]` -- met2.pin.
MET2_LABEL_LAYER = [69, 5]

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

# --- met2 escape plane (sky130A source-deck rules, see module docstring) ---
#: sky130 `via.1a`: the met1 -> met2 via is exactly 0.15 um square.
VIA1_UM = 0.15
#: sky130 `via.2`: minimum via-to-via spacing (um).
VIA1_SPACE_UM = 0.17
#: met1 landing-pad side (um) around one via1. 0.32 encloses the 0.15 cut by
#: 0.085 on all four edges -- the stricter of `via.4a` (0.055 all round) and
#: `via.5a` (0.085 on two adjacent edges).
MET1_VIA1_LANDING_UM = 0.32
#: met2 landing-pad side (um) around one via1, sized by `m2.4`/`m2.5` the same
#: way. Also clears `m2.6` (min met2 area 0.0676 um^2) on its own.
MET2_LANDING_UM = 0.32
#: met2 wire width (um): the landing pad's side, so a wire ending on a via
#: satisfies the two-adjacent-edge enclosure along its own axis too. Well over
#: `m2.1` (0.14).
MET2_WIRE_WIDTH_UM = 0.32
#: sky130 `m2.2` minimum met2 spacing (um) -- the clearance the met2 route
#: guard and :meth:`Met1Bus.conflicts` hold between different nets.
MET2_SPACE_UM = 0.14


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
        #: Segment count for the met2 escape plane -- kept separate from
        #: `wire_count` (met1-only) so `met1_wire_count`/`met2_wire_count` in
        #: the emitted report each describe their own plane rather than one
        #: counter silently tallying both (issue #93).
        self.met2_wire_count = 0
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
        #: (net_id, x0, y0, x1, y1) for every met2 rectangle drawn -- the same
        #: drawn-short ledger `met1_rects` is, for the escape plane. It needs
        #: its own even though `klt drc`'s curated sky130 deck now carries
        #: met2 width/space/enclosure rules (klayout-tools#513/#515): those
        #: are single-layer geometric rules, not net-aware, so two different
        #: nodes' met2 touching (no gap between them) is not a spacing
        #: violation and nothing downstream but this ledger would report it.
        self.met2_rects: list[tuple[str, float, float, float, float]] = []
        #: (cell -> met2_rects indices) proximity index, see `met2_near`.
        self._grid2: dict[tuple[int, int], list[int]] = {}
        #: (net_id, x, y) per drawn via1, for the `via.2` proximity half of
        #: :meth:`conflicts` and for :meth:`components`' cross-layer joins.
        self.via1_xy: list[tuple[str, float, float]] = []
        self.via1_count = 0
        self._via1s: set[tuple[str, float, float]] = set()
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
        elif layer == MET2_LAYER:
            self._index_met2(len(self.met2_rects), x0, y0, x1, y1)
            self.met2_rects.append((self._net, x0, y0, x1, y1))
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

    # -- met2 spatial index (same shape as met1's, separate plane) ---------
    def _index_met2(self, position: int, x0: float, y0: float, x1: float, y1: float) -> None:
        for cell in self._cells(x0, y0, x1, y1):
            self._grid2.setdefault(cell, []).append(position)

    def met2_near(
        self, x0: float, y0: float, x1: float, y1: float, clearance: float
    ):
        """Every already-drawn met2 rectangle within `clearance` of the box.

        Box (Chebyshev) proximity, i.e. slightly stricter than sky130's
        Euclidean `m2.2`, for the same reason :meth:`met1_near` is stricter
        than `met1.space.1`.
        """
        seen: set[int] = set()
        for cell in self._cells(
            x0 - clearance, y0 - clearance, x1 + clearance, y1 + clearance
        ):
            for position in self._grid2.get(cell, ()):  # noqa: B007
                if position in seen:
                    continue
                seen.add(position)
                net_b, bx0, by0, bx1, by1 = self.met2_rects[position]
                if (
                    x0 - clearance < bx1
                    and bx0 - clearance < x1
                    and y0 - clearance < by1
                    and by0 - clearance < y1
                ):
                    yield (net_b, bx0, by0, bx1, by1)

    def truncate_met2(self, count: int) -> None:
        """Drop every met2 rectangle from `count` on, index included."""
        for position in range(count, len(self.met2_rects)):
            _net, x0, y0, x1, y1 = self.met2_rects[position]
            for cell in self._cells(x0, y0, x1, y1):
                bucket = self._grid2.get(cell)
                if bucket and bucket[-1] == position:
                    bucket.pop()
                elif bucket and position in bucket:
                    bucket.remove(position)
        del self.met2_rects[count:]

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

    def via1(self, x: float, y: float) -> None:
        """One met1 -> met2 via stack (met1 pad + `via.drawing` cut + met2
        pad), centred at (x, y).

        This is the primitive klayout-tools#508 (merged via #511) made
        drawable: before it the sky130 curated deck's connectivity graph
        stopped at met1, so a `via.drawing` cut and any met2 above it were
        inert geometry the extractor would not traverse -- drawing them would
        have produced a *disconnected* node that still looked routed, which is
        exactly the failure mode :meth:`components` exists to catch.

        The caller is responsible for (x, y) sitting on met1 the same net
        already owns; every call site drops it on a point the met1 router has
        just drawn to. A repeat call at a position already contacted by the
        same net is a no-op, for the same reason :meth:`via` de-duplicates:
        two coincident cuts are one via drawn twice and would trip `via.2`.
        """
        key = (self._net, round(x, 4), round(y, 4))
        if key in self._via1s:
            return
        self._via1s.add(key)
        self.via1_xy.append((self._net, x, y))
        h = MET1_VIA1_LANDING_UM / 2.0
        self._rect(MET1_LAYER, x - h, y - h, x + h, y + h)
        h = VIA1_UM / 2.0
        self._rect(VIA1_LAYER, x - h, y - h, x + h, y + h)
        h = MET2_LANDING_UM / 2.0
        self._rect(MET2_LAYER, x - h, y - h, x + h, y + h)
        self.via1_count += 1

    def hseg2(self, x0: float, x1: float, y: float) -> None:
        """One horizontal met2 segment (no vias)."""
        if x0 == x1:
            return
        h = MET2_WIRE_WIDTH_UM / 2.0
        self._rect(MET2_LAYER, min(x0, x1), y - h, max(x0, x1), y + h)
        self.met2_wire_count += 1

    def vseg2(self, x: float, y0: float, y1: float) -> None:
        """One vertical met2 segment (no vias)."""
        if y0 == y1:
            return
        h = MET2_WIRE_WIDTH_UM / 2.0
        self._rect(MET2_LAYER, x - h, min(y0, y1), x + h, max(y0, y1))
        self.met2_wire_count += 1

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
                len(self.li1_rects), self.gate_contact_count,
                len(self.met2_rects), len(self.via1_xy), self.via1_count,
                self.met2_wire_count)

    def restore(self, mark: tuple[int, ...]) -> None:
        """Undo every shape, rectangle, via, gate contact and label added
        since `mark`."""
        (shapes, rects, vias, labels, via_count, wire_count, li1_rects,
         gate_contacts, met2_rects, via1s, via1_count, met2_wire_count) = mark
        for net, x, y in self.via_xy[vias:]:
            self._vias.discard((net, round(x, 4), round(y, 4)))
        for net, x, y in self.via1_xy[via1s:]:
            self._via1s.discard((net, round(x, 4), round(y, 4)))
        self.via_count = via_count
        self.wire_count = wire_count
        self.gate_contact_count = gate_contacts
        self.via1_count = via1_count
        self.met2_wire_count = met2_wire_count
        del self.shapes[shapes:]
        self.truncate_met1(rects)
        self.truncate_met2(met2_rects)
        del self.via_xy[vias:]
        del self.via1_xy[via1s:]
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

        met2 and its via1 cuts are checked here too, and for them this is not
        a safety net but the *only* net: the curated sky130 deck declares met2
        as a connectivity level (klayout-tools#511) without declaring a single
        `met2.*`/`via.*` DRC rule, so `klt drc` reports nothing about the
        escape plane's geometry. Thresholds come from the sky130A source deck
        (`m2.2` 0.14 um, `via.2` 0.17 um).
        """
        found: list[dict[str, Any]] = []
        eps = clearance_um - 1e-9
        # mcon-to-mcon: sky130's `ct.2` minimum mcon spacing is 0.19 um, and
        # two vias of different nets that close are also very nearly a short.
        # via1-to-via1: sky130's `via.2` is 0.17 um.
        for cuts, size, space in (
            (self.via_xy, VIA_UM, 0.19 - 1e-9),
            (self.via1_xy, VIA1_UM, VIA1_SPACE_UM - 1e-9),
        ):
            for i, (net_a, ax, ay) in enumerate(cuts):
                for net_b, bx, by in cuts[i + 1 :]:
                    if net_a == net_b:
                        continue
                    if abs(ax - bx) < size + space and abs(ay - by) < size + space:
                        found.append(
                            {"nets": [net_a, net_b], "via_a": [ax, ay], "via_b": [bx, by]}
                        )
        for layer, rects, clearance in (
            ("met1", self.met1_rects, eps),
            ("met2", self.met2_rects, MET2_SPACE_UM - 1e-9),
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
        """How many disjoint pieces each net's drawn wiring falls into, across
        both routing planes.

        A net drawn as two pieces that never touch is *not* a connected node,
        however confidently the net id says otherwise -- and unlike a drawn
        short, nothing downstream reports it as an error: `klt extract` simply
        sees two anonymous nets. Counting connected components per net id is
        the matching safety net to :meth:`conflicts`: 1 means the wiring this
        flow drew for that node is genuinely one conductor.

        Rectangles are joined when they touch or overlap **on the same layer**
        (a shared edge is a connection on one metal layer, and met1 crossing
        under met2 is not). A met1 piece and a met2 piece are joined only
        where a :meth:`via1` cut of the same net sits inside both -- which is
        the whole point of counting the two planes in one graph rather than
        two: a met2 escape whose via stack missed its own met1 would otherwise
        score 1-per-plane and look connected while being two floating nets.
        Nets that legitimately close through li1 rather than met1 are the
        caller's business to exclude.
        """
        by_net: dict[str, list[tuple[int, float, float, float, float]]] = {}
        for net, x0, y0, x1, y1 in self.met1_rects:
            by_net.setdefault(net, []).append((0, x0, y0, x1, y1))
        for net, x0, y0, x1, y1 in self.met2_rects:
            by_net.setdefault(net, []).append((1, x0, y0, x1, y1))
        via1_by_net: dict[str, list[tuple[float, float]]] = {}
        for net, x, y in self.via1_xy:
            via1_by_net.setdefault(net, []).append((x, y))
        out: dict[str, int] = {}
        eps = 1e-9
        for net, rects in by_net.items():
            parent = list(range(len(rects)))

            def find(i: int) -> int:
                while parent[i] != i:
                    parent[i] = parent[parent[i]]
                    i = parent[i]
                return i

            def union(i: int, j: int) -> None:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj

            local: dict[tuple[int, int], list[int]] = {}
            for i, (_plane, x0, y0, x1, y1) in enumerate(rects):
                for cell in self._cells(x0 - eps, y0 - eps, x1 + eps, y1 + eps):
                    local.setdefault(cell, []).append(i)
            for bucket in local.values():
                for pos, i in enumerate(bucket):
                    aplane, ax0, ay0, ax1, ay1 = rects[i]
                    for j in bucket[pos + 1 :]:
                        bplane, bx0, by0, bx1, by1 = rects[j]
                        if aplane != bplane:
                            continue
                        if (
                            ax0 - eps <= bx1
                            and bx0 - eps <= ax1
                            and ay0 - eps <= by1
                            and by0 - eps <= ay1
                        ):
                            union(i, j)
            # Cross-plane joins: one via1 cut welds every met1 rectangle it
            # sits inside to every met2 rectangle it sits inside.
            for vx, vy in via1_by_net.get(net, ()):
                touching: dict[int, list[int]] = {0: [], 1: []}
                for i, (plane, x0, y0, x1, y1) in enumerate(rects):
                    if x0 - eps <= vx <= x1 + eps and y0 - eps <= vy <= y1 + eps:
                        touching[plane].append(i)
                for i in touching[0]:
                    for j in touching[1]:
                        union(i, j)
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
            "via1_count": self.via1_count,
            "met2_rect_count": len(self.met2_rects),
            "met2_wire_count": self.met2_wire_count,
        }
        (out_dir / f"{cell_name}.gen.json").write_text(
            json.dumps(gen_report, indent=2) + "\n"
        )
        return gen_report
