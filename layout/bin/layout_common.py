#!/usr/bin/env python3
"""Shared helpers for the `layout/bin/gen_bandgap_*.py` CLI scripts.

`gen_bandgap_routed.py` (issue #62) drives `klt` as a subprocess and composes
block placements. Mirrors `sim/bin/sim_common.py`'s role for the `sim/`
scripts (issue #169, after five prior `loom:hermit` dedupe rounds on that
module: #153, #154, #160, #162, #163):

    run_klt_json()   runs `klt <args> --format json` and parses the stdout
                     envelope, tolerating a caller-supplied set of "still
                     carries a payload" exit codes (e.g. `klt drc`'s 3)
    klt_gen()        runs `klt gen <generator>` for one BLOCKS entry and
                     writes its report alongside the generated GDS
    union_bbox()     computes the union bounding box of a set of placed
                     block ids, given each one's own reported bbox_um and
                     its placement origin

`place_blocks()` is intentionally NOT here -- it lives in
`gen_bandgap_routed.py` itself, which needs an `align` parameter
(`top`/`bottom`/`center`) for `bjt_array`'s north-facing ports (issue #169's
scope note; `gen_bandgap_floorplan.py`, the #15 flow this module used to also
serve, was removed in issue #215 as superseded by the routed flow).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def run_klt_json(klt: str, *args: str, allow_exit: tuple[int, ...] = (0,)) -> dict[str, Any]:
    """Run one `klt <args> --format json` and parse its stdout envelope.

    `allow_exit` lists the exit codes that still carry a full payload on
    stdout -- `klt drc`'s 3 ("ran clean but found violations") and
    `klt gen-compose`'s 3 ("partial success: unrouted_nets[] non-empty") both
    do, and both are results this flow records rather than crashes. The
    default `(0,)` raises on any nonzero exit, matching
    `subprocess.run(..., check=True)`'s behavior (only the exception type
    differs: `RuntimeError` with `stderr` attached, instead of
    `subprocess.CalledProcessError`).
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
