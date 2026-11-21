#!/usr/bin/env python3
"""layout/bin/gds_layer_boxes.py -- list the merged shapes of one GDS layer.

Reads `<layer>/<datatype>` from a GDS with `klayout.db`, merges the region,
and reports one bbox per merged polygon as JSON. Exists for the routed
flow's supply-ERC step (issue #620): the committed `erc-supply-spec.json`
ties carry *absolute* well boxes of an older GDS, so the flow re-derives
them from the composed GDS's merged 64/20 region every run and classifies
each box by the block whose centre sits inside it
(`gen_bandgap_routed.classify_well_boxes`).

Shelled out from `gen_bandgap_routed.py` with the layout venv's interpreter
for the same reason `met2_drc.py` is: the flow scripts are stdlib-only by
convention and only the venv has `klayout.db`. Not a `klt` verb because
`klt layers` reports whole-layer bboxes, not per-shape -- and the tie
declaration needs one box per well or the negative-control count is wrong.

Run standalone:

    layout/.venv/bin/python layout/bin/gds_layer_boxes.py <gds> \
        --layer 64 --datatype 20 [-o out.json]

Exits 0 on success, 1 on error. Requires `klayout` -- i.e. the layout venv,
not the bare system interpreter the rest of the flow runs under.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import klayout.db as db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("gds", type=Path)
    parser.add_argument("--layer", type=int, required=True)
    parser.add_argument("--datatype", type=int, required=True)
    parser.add_argument(
        "--top",
        help="read this cell's subtree only (default: the single top cell)",
    )
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args(argv)

    layout = db.Layout()
    layout.read(str(args.gds))
    if args.top:
        cell_index = layout.cell_by_name(args.top)
        if cell_index < 0:
            print(f"gds_layer_boxes.py: no cell '{args.top}'", file=sys.stderr)
            return 1
        cell = layout.cell(cell_index)
    else:
        tops = layout.top_cells()
        if len(tops) != 1:
            names = ", ".join(c.name for c in tops)
            print(
                f"gds_layer_boxes.py: {args.gds} has {len(tops)} top cells"
                f" ({names}); pass --top",
                file=sys.stderr,
            )
            return 1
        cell = tops[0]

    layer_index = layout.find_layer(args.layer, args.datatype)
    shapes: list[dict[str, object]] = []
    if layer_index is not None:
        region = db.Region(layout.begin_shapes(cell, layer_index)).merged()
        dbu = layout.dbu
        for polygon in region.each():
            box = polygon.bbox()
            shapes.append(
                {
                    "bbox_um": [
                        box.left * dbu,
                        box.bottom * dbu,
                        box.right * dbu,
                        box.top * dbu,
                    ],
                    "area_um2": polygon.area() * dbu * dbu,
                }
            )
    shapes.sort(key=lambda s: s["bbox_um"])  # type: ignore[arg-type,return-value]

    payload = {
        "schema_version": 1,
        "file": str(args.gds),
        "top": cell.name,
        "layer": f"{args.layer}/{args.datatype}",
        "shape_count": len(shapes),
        "shapes": shapes,
    }
    text = json.dumps(payload, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
