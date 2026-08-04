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

#: mcon drawn size (um). sky130's mcon is a fixed 0.17 um square.
VIA_UM = 0.17
#: met1 landing-pad side (um) around one via: 0.24 encloses a 0.17 via by
#: 0.035 > the deck's 0.03 `met1.enclosing.mcon.1` threshold.
LANDING_UM = 0.24
#: met1 wire width (um): same as the landing pad, so a wire ending on a via
#: satisfies the enclosure rule along its own axis too.
WIRE_WIDTH_UM = 0.24


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
            self.met1_rects.append((self._net, x0, y0, x1, y1))

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
        rects = self.met1_rects
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
