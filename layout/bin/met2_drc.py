#!/usr/bin/env python3
"""layout/bin/met2_drc.py -- check the met2/via escape plane against sky130's
own source DRC rules, because the curated `klt drc` deck does not.

Why this exists
---------------
2AMLogic/klayout-tools#508 (merged via #511) added met2 to sky130's curated
**extraction** deck as a third connectivity level, which is what makes
`layout/bin/met1_bus.py`'s escape plane real connectivity rather than inert
geometry (see `gen_bandgap_routed.py`'s MET2_ESCAPE_NOTE). The curated **DRC**
deck (`klayout_tools.decks.sky130.DECK`) was not extended alongside it: it
carries `met1.width.1`, `met1.space.1` and `met1.enclosing.mcon.1`, and no
`met2.*` or `via.*` rule at all. So `klt drc --deck sky130` returns
`violation_count: 0` on a layout whose met2 could be 10 nm wide, and this
flow's evidence discipline ("no claim without a testbench") does not allow a
silent rule to stand in for a checked one.

This module checks the new plane directly, on the composed GDS, with the same
`klayout.db.Region` primitives a DRC deck uses, against the thresholds the
installed sky130A PDK's own source deck states
(`libs.tech/klayout/drc/sky130A_mr.drc`):

    m2.1    min met2 width               0.14 um
    m2.2    min met2 spacing             0.14 um
    m2.6    min met2 area                0.0676 um^2
    via.1a  via is exactly 0.15 um square
    via.2   min via spacing              0.17 um
    via.4a  min met1 enclosure of via    0.055 um
    via.5a  ... 0.085 um on two adjacent edges
    m2.4    min met2 enclosure of via    0.055 um
    m2.5    ... 0.085 um on two adjacent edges

`via.5a`/`m2.5`'s two-adjacent-edge form is checked here in its stricter
all-round shape (0.085 on every edge), which every landing pad this flow draws
satisfies by construction -- a check that passes the stricter bar has also
passed the real one, and the converse failure mode (passing a laxer proxy) is
what this module exists to avoid.

Run standalone or via `gen_bandgap_routed.py`:

    layout/.venv/bin/python layout/bin/met2_drc.py <gds> --top <cell> [-o out.json]

Exits 0 when clean, 3 when any rule is violated (mirroring `klt drc`'s own
convention), 1 on an error. Requires `klayout` -- i.e. the layout venv, not
the bare system interpreter the rest of the flow runs under.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# --- layers, from klayout_tools.decks.sky130.EXTRACTION_DECK ---------------
MET1 = (68, 20)
VIA1 = (68, 44)
MET2 = (69, 20)

# --- thresholds (um), from the installed sky130A source DRC deck ----------
M2_WIDTH_UM = 0.14  # m2.1
M2_SPACE_UM = 0.14  # m2.2
M2_AREA_UM2 = 0.0676  # m2.6
VIA_SIDE_UM = 0.15  # via.1a
VIA_SPACE_UM = 0.17  # via.2
MET1_ENC_VIA_UM = 0.085  # via.4a (0.055) tightened to via.5a's 0.085
MET2_ENC_VIA_UM = 0.085  # m2.4 (0.055) tightened to m2.5's 0.085


def check(gds_path: Path, top: str | None = None) -> dict[str, Any]:
    """Every met2/via1 rule violation in `gds_path`, as a `klt drc`-shaped
    report. An empty `violations` list is the only clean result."""
    import klayout.db as db  # imported here so --help works without klayout

    layout = db.Layout()
    layout.read(str(gds_path))
    if top is not None:
        cell = layout.cell(top)
        if cell is None:
            raise SystemExit(f"met2_drc.py: no cell '{top}' in {gds_path}")
    else:
        tops = layout.top_cells()
        if len(tops) != 1:
            raise SystemExit(
                f"met2_drc.py: {len(tops)} top cells in {gds_path}; pass --top"
            )
        cell = tops[0]

    def region(layer: tuple[int, int]) -> "db.Region":
        index = layout.layer(layer[0], layer[1])
        return db.Region(cell.begin_shapes_rec(index))

    met1 = region(MET1).merged()
    via1 = region(VIA1).merged()
    met2 = region(MET2).merged()

    violations: list[dict[str, Any]] = []

    def record(rule: str, description: str, edges: Any) -> None:
        count = edges.count() if hasattr(edges, "count") else len(edges)
        if not count:
            return
        violations.append(
            {"rule": rule, "description": description, "count": int(count)}
        )

    def dbu(value_um: float) -> int:
        return int(round(value_um / layout.dbu))

    record("m2.1", f"min met2 width {M2_WIDTH_UM} um",
           met2.width_check(dbu(M2_WIDTH_UM)))
    record("m2.2", f"min met2 spacing {M2_SPACE_UM} um",
           met2.space_check(dbu(M2_SPACE_UM)))
    # `with_area` MUST be called in its three-argument `(min, max, inverse)`
    # form. KLayout's Python binding also has a two-argument
    # `(area, inverse)` overload, and a two-argument call silently resolves
    # to *that* one -- `with_area(0, threshold)` reads as "area exactly 0,
    # inverted", i.e. it returns every polygon and reports every met2 shape
    # as an area violation. Found by this module's own negative control, in
    # square dbu (hence the dbu**2 divisor, not a second call to `dbu()`).
    record("m2.6", f"min met2 area {M2_AREA_UM2} um^2",
           met2.with_area(0, int(round(M2_AREA_UM2 / (layout.dbu ** 2))), False))
    record("via.2", f"min via spacing {VIA_SPACE_UM} um",
           via1.space_check(dbu(VIA_SPACE_UM)))

    # via.1a -- every via cut is exactly VIA_SIDE_UM square. Checked on the
    # unmerged polygons' bounding boxes rather than with a width/space rule,
    # because "exactly" is a two-sided constraint no single DRC check states.
    side_dbu = dbu(VIA_SIDE_UM)
    bad_cuts = 0
    for polygon in region(VIA1).each():
        box = polygon.bbox()
        if box.width() != side_dbu or box.height() != side_dbu:
            bad_cuts += 1
    if bad_cuts:
        violations.append({
            "rule": "via.1a",
            "description": f"via must be exactly {VIA_SIDE_UM} um square",
            "count": bad_cuts,
        })

    record("via.4a/via.5a",
           f"min met1 enclosure of via {MET1_ENC_VIA_UM} um (all round)",
           met1.enclosing_check(via1, dbu(MET1_ENC_VIA_UM)))
    record("m2.4/m2.5",
           f"min met2 enclosure of via {MET2_ENC_VIA_UM} um (all round)",
           met2.enclosing_check(via1, dbu(MET2_ENC_VIA_UM)))

    # A via with no metal above or below it is not a violation of a *spacing*
    # rule but is a hard connectivity error, and nothing else in this flow
    # would report it: `klt extract` simply produces one fewer connection.
    orphan_below = (via1 - met1).count()
    orphan_above = (via1 - met2).count()
    if orphan_below:
        violations.append({
            "rule": "via.4a_a",
            "description": "via must be enclosed by met1",
            "count": int(orphan_below),
        })
    if orphan_above:
        violations.append({
            "rule": "m2.4_a",
            "description": "via must be enclosed by met2",
            "count": int(orphan_above),
        })

    return {
        "schema_version": 1,
        "checker": "layout/bin/met2_drc.py",
        "gds": str(gds_path),
        "top": cell.name,
        "source": "sky130A_mr.drc (installed PDK), see module docstring",
        "reason": (
            "the curated klt sky130 DRC deck declares met2 as a connectivity "
            "level but carries no met2.*/via.* rule, so `klt drc` is silent "
            "about this plane"
        ),
        "counts": {
            "met1_polygons": int(met1.count()),
            "via1_cuts": int(region(VIA1).count()),
            "met2_polygons": int(met2.count()),
        },
        "violation_count": sum(v["count"] for v in violations),
        "violations": violations,
        "status": "clean" if not violations else "violations",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gds", type=Path)
    parser.add_argument("--top", default=None)
    parser.add_argument("-o", "--output", type=Path, default=None)
    args = parser.parse_args()

    report = check(args.gds, args.top)
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
    sys.stdout.write(text)
    return 0 if report["status"] == "clean" else 3


if __name__ == "__main__":
    raise SystemExit(main())
