#!/usr/bin/env python3
"""layout/bin/gen_bandgap_floorplan.py -- issue #15: generate, place, and
DRC-check the bandgap core's initial floorplan skeleton.

Standard library only (matches sim/bin/corner-run.py's and
layout/bin/render-record.py's convention). Invoked by
layout/bin/run-bandgap-floorplan-flow.sh, which supplies --out-dir/
--record-id/--klt/--pdk-variant the same way run-trivial-cell-flow.sh's
render-record.py is invoked.

What this script does, end to end:

1. Runs `klt gen` once per matched device group named in
   layout/matching-plan.md (PNP CTAT/PTAT arrays, R2A/R2B interdigitated
   ladder, R1, the downward trim-tap ladder, the amp input pair, the two
   NMOS load/mirror pairs, the PMOS mirror pair, and the core's own
   MPOUT/MPAMP mirror pair), each with the real schematic W/L/mult/rows/
   cols/splits from design/bandgap_core.sch and design/error_amp.sch where
   the generator's own output stays tractable for an initial skeleton, and
   a documented reduced count where it does not (see BLOCKS below and
   layout/matching-plan.md's "Skeleton vs. real target counts" table).
2. Places every block on an explicit 2D grid (four stacked, horizontally
   centered rows -- PNP arrays, resistor ladders, amp input/load pair, amp
   mirror pairs) using
   `klt gen-compose`'s `placement.strategy: "explicit"`
   (2AMLogic/klayout-tools#330, picked up by this issue's requirements.txt
   pin bump -- see that file's own comment for why).
3. Wraps the placed union bbox in one overall guard ring (`klt gen
   guard_ring`), sized and centered from the composed bbox reported by step
   2 -- not a placeholder size.
4. Runs `klt drc` on the final composed-plus-ring GDS and writes a
   record.md verdict, mirroring layout/trivial-cell/'s evidence-record
   convention (append-only, timestamped record id).

This flow does NOT run `klt extract`/`klt lvs` on the composed output: two
of the matched groups (the PNP arrays via `bjt_array`, the resistor ladders
via `res_array`) are known not to round-trip through `klt extract` today
(2AMLogic/klayout-tools#176's own design note for the former; #369 for the
latter), so an LVS claim over the whole composed cell would not be
meaningful evidence yet. DRC-clean is this issue's acceptance bar
(see layout/matching-plan.md); LVS-clean bandgap-core layout is later work.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from layout_common import klt_gen, run_klt_json, union_bbox  # noqa: E402

# ---------------------------------------------------------------------------
# Floorplan geometry constants (um)
# ---------------------------------------------------------------------------
BLOCK_MARGIN_UM = 5.0  # clearance between blocks placed side by side in a row
ROW_MARGIN_UM = 8.0  # clearance between stacked rows
RING_MARGIN_UM = 8.0  # clearance between the composed content and the outer ring
RING_WIDTH_UM = 2.0
RING_CONTACTS_PER_SIDE = 8

# ---------------------------------------------------------------------------
# Block definitions. Each maps directly to one `klt gen` call. `row` groups
# blocks into the four stacked floorplan bands (0 = top: PNP arrays,
# 1 = resistor ladders, 2 = amp input pair + NMOS loads,
# 3 = bottom: amp mirror pairs + core mirror); blocks within a row are
# placed left-to-right in the order listed, centered as a group once every
# row's width is known (see place_blocks()).
#
# `real_target` documents the actual design/bandgap_core.sch or
# design/error_amp.sch parameter this block's generator params approximate,
# for cross-reference against layout/matching-plan.md -- this script's own
# comments are not a substitute for that document's fuller rationale.
# ---------------------------------------------------------------------------
BLOCKS: list[dict[str, Any]] = [
    {
        "id": "pnp_ctat",
        "row": 0,
        "generator": "bjt_array",
        "params": {
            "emitter_um": 0.68,
            "rows": 2,
            "cols": 4,
            "dummy": 1,
            "ratio": 8,
            "topology": "common_centroid",
            "add_collector_ring": True,
        },
        "matched_group_label": "Q1 (CTAT PNP, small unit W0p68L0p68)",
        "real_target": "m=8 sky130_fd_pr__pnp_05v5_W0p68L0p68 (design/bandgap_core.sch); "
        "drawn 1:1 with the schematic count (8 real units, 2x4 common-centroid)",
    },
    {
        "id": "pnp_ptat",
        "row": 0,
        "generator": "bjt_array",
        "params": {
            "emitter_um": 3.40,
            "rows": 2,
            "cols": 4,
            "dummy": 1,
            "ratio": 8,
            "topology": "common_centroid",
            "add_collector_ring": True,
        },
        "matched_group_label": "Q2 (PTAT PNP, large unit W3p40L3p40)",
        "real_target": "m=8 sky130_fd_pr__pnp_05v5_W3p40L3p40 (design/bandgap_core.sch); "
        "drawn 1:1 with the schematic count (8 real units, 2x4 common-centroid)",
    },
    {
        "id": "res_r2",
        "row": 1,
        "generator": "res_array",
        "params": {
            "length_um": 5.0,
            "width_um": 1.0,
            "spacing_um": 0.5,
            "num": 16,
            "dummy": 2,
        },
        "matched_group_label": "R2A/R2B interdigitated ladder (K = R2/R1 divider)",
        "real_target": "n_r2=54 unit segments PER LEG x 2 legs = 108 total "
        "(design/bandgap_core.sch); skeleton uses 16 (8 per leg, alternating "
        "A/B by index) -- 108 does not fit a single-row res_array within the "
        "< 0.05 mm^2 budget without folding, a real klt gap "
        "(2AMLogic/klayout-tools#415); see layout/matching-plan.md",
    },
    {
        "id": "res_r1",
        "row": 1,
        "generator": "res_array",
        "params": {
            "length_um": 5.0,
            "width_um": 1.0,
            "spacing_um": 0.5,
            "num": 7,
            "dummy": 2,
        },
        "matched_group_label": "R1 (dVBE-to-current leg)",
        "real_target": "n_r1=7 unit segments (design/bandgap_core.sch); drawn 1:1",
    },
    {
        "id": "res_trim",
        "row": 1,
        "generator": "res_array",
        "params": {
            "length_um": 1.0,
            "width_um": 1.0,
            "spacing_um": 0.5,
            "num": 32,
            "dummy": 2,
        },
        "matched_group_label": "Downward-only trim ladder taps (both legs)",
        "real_target": "n_r2_trim range 0..-16 codes x 2 legs (R2A, R2B) = 32 "
        "1um unit taps (design/bandgap_core.sch CORE_PARAMS, DR-002); drawn 1:1",
    },
    {
        "id": "amp_input_pair",
        "row": 2,
        "generator": "diff_pair",
        "params": {
            "w_um": 20.0,
            "l_um": 10.0,
            "splits": 16,
            "flavor": "pfet",
            "mirror": False,
            "add_guard_ring": True,
        },
        "matched_group_label": "MP1/MP2 (amp PMOS input pair)",
        "real_target": "amp_m_in=16, W=20 L=10 (design/error_amp.sch); drawn 1:1; "
        "the dominant contributor per sim/monte-carlo-untrimmed and "
        "design/error-amp-offset-budget.md -- see layout/matching-plan.md",
    },
    {
        "id": "amp_nload",
        "row": 2,
        "generator": "diff_pair",
        "params": {
            "w_um": 8.0,
            "l_um": 20.0,
            "splits": 4,
            "flavor": "nfet",
            "mirror": True,
            "add_guard_ring": True,
        },
        "matched_group_label": "MN1/MN2 (amp NMOS diode loads)",
        "real_target": "amp_m_nmirr=4, W=8 L=20 (design/error_amp.sch); drawn 1:1. "
        "MN1..MN4 are one 4-device matched group in the offset budget; "
        "gen-compose's diff_pair generator only matches 2 devices at a time, "
        "so this is split into two matched pairs (MN1/MN2 here, MN3/MN4 in "
        "amp_nmirr below) -- see layout/matching-plan.md",
    },
    {
        "id": "amp_nmirr",
        "row": 3,
        "generator": "diff_pair",
        "params": {
            "w_um": 8.0,
            "l_um": 20.0,
            "splits": 4,
            "flavor": "nfet",
            "mirror": True,
            "add_guard_ring": True,
        },
        "matched_group_label": "MN3/MN4 (amp NMOS mirror outputs)",
        "real_target": "amp_m_nmirr=4, W=8 L=20 (design/error_amp.sch); drawn 1:1",
    },
    {
        "id": "amp_pmirr",
        "row": 3,
        "generator": "diff_pair",
        "params": {
            "w_um": 6.0,
            "l_um": 20.0,
            "splits": 8,
            "flavor": "pfet",
            "mirror": True,
            "add_guard_ring": True,
        },
        "matched_group_label": "MP3/MP4 (amp PMOS mirror)",
        "real_target": "amp_m_pmirr=8, W=6 L=20 (design/error_amp.sch); drawn 1:1",
    },
    {
        "id": "core_mirror",
        "row": 3,
        "generator": "diff_pair",
        "params": {
            "w_um": 8.0,
            "l_um": 2.0,
            "splits": 2,
            "flavor": "pfet",
            "mirror": True,
            "add_guard_ring": True,
        },
        "matched_group_label": "MPOUT/MPAMP (core PMOS output/bias mirror)",
        "real_target": "m_out=m_ampbias=2, W=8 L=2 (design/bandgap_core.sch); drawn 1:1",
    },
]

# MCC (the amp's compensation device, amp_m_cc=16 x W=30 L=20 = 9600 um^2) is
# a single-ended MOS capacitor, not a matched pair -- there is nothing for it
# to common-centroid against, so it is not one of the placed blocks above.
# Its area is carried in layout/matching-plan.md's area budget table as an
# analytic allocation (not drawn in this skeleton) -- see that document's
# "Area budget" section for why and for the exact figure.
MCC_AREA_UM2_NOTE = (
    "MCC (amp compensation cap, amp_m_cc=16 x W=30 x L=20 = 9600 um^2) is "
    "single-ended and not drawn in this skeleton; see layout/matching-plan.md"
)


# run_klt_json() and klt_gen() live in layout_common.py (issue #169) --
# imported above.


def place_blocks(
    blocks: list[dict[str, Any]], reports: dict[str, dict[str, Any]]
) -> dict[str, dict[str, float]]:
    """Compute an origins_um dict for `gen-compose`'s "explicit" strategy:
    four horizontally-centered rows stacked bottom-to-top in `row` order,
    each row's blocks placed left-to-right with BLOCK_MARGIN_UM between
    them, rows separated by ROW_MARGIN_UM. Every number here is derived from
    the blocks' own reported bbox_um (never hardcoded pixel coordinates), so
    this recomputes correctly if a BLOCKS entry's params change.
    """
    rows: dict[int, list[str]] = {}
    for block in blocks:
        rows.setdefault(block["row"], []).append(block["id"])

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
            # Translate so the block's own bbox.x0/.y0 lands at (x_cursor, y_cursor).
            origins[bid] = {"x": x_cursor - bbox["x0"], "y": y_cursor - bbox["y0"]}
            x_cursor += block_width + BLOCK_MARGIN_UM
        y_cursor += row_height + ROW_MARGIN_UM

    return origins


# union_bbox() lives in layout_common.py (issue #169) -- imported above.


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--record-id", required=True)
    ap.add_argument("--repo-root", required=True, type=Path)
    ap.add_argument("--klt", required=True)
    ap.add_argument("--pdk-variant", required=True)
    args = ap.parse_args()

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    klt = args.klt
    pdk = args.pdk_variant

    # --- 1. Generate every matched-group block -------------------------------
    reports: dict[str, dict[str, Any]] = {}
    for block in BLOCKS:
        reports[block["id"]] = klt_gen(klt, pdk, out_dir, block)

    # --- 2. Place on an explicit 2D grid (four centered, stacked rows) ------
    origins = place_blocks(BLOCKS, reports)
    content_bbox = union_bbox([b["id"] for b in BLOCKS], reports, origins)

    inner_blocks_request = {
        "schema": "klt.gen_compose.request/1",
        "pdk": {"variant": pdk},
        "blocks": [
            {
                "id": block["id"],
                "generator_report": str(
                    (out_dir / f"{block['id']}.gen.json").resolve()
                ),
            }
            for block in BLOCKS
        ],
        "placement": {
            "strategy": "explicit",
            "order": [block["id"] for block in BLOCKS],
            "origins_um": origins,
        },
        "options": {
            "cell_name": "bandgap_core_floorplan_inner",
            "output": str((out_dir / "bandgap_core_floorplan_inner.gds").resolve()),
        },
    }
    (out_dir / "compose.inner.request.json").write_text(
        json.dumps(inner_blocks_request, indent=2) + "\n"
    )
    inner_compose = run_klt_json(
        klt, "gen-compose", str(out_dir / "compose.inner.request.json")
    )
    (out_dir / "compose.inner.json").write_text(
        json.dumps(inner_compose, indent=2) + "\n"
    )

    # --- 3. Size and place the overall guard ring around the composed content
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
                "add_well": True,
            },
        },
    )
    reports["guard_ring_outer"] = ring_report

    # Center the ring's own reported bbox on the content bbox's center: a
    # guard ring's protected inner cavity is horizontally/vertically centered
    # within its own reported bbox_um by construction (ring_width_um is one
    # scalar applied uniformly on all four sides), so aligning bbox centers
    # aligns the cavity with the content with RING_MARGIN_UM clearance on
    # every side -- confirmed empirically against `klt gen guard_ring`'s own
    # reported bbox_um for a representative inner_width_um/inner_height_um
    # pair while building this script (see layout/matching-plan.md).
    ring_bbox = ring_report["bbox_um"]
    ring_center_x = (ring_bbox["x0"] + ring_bbox["x1"]) / 2.0
    ring_center_y = (ring_bbox["y0"] + ring_bbox["y1"]) / 2.0
    content_center_x = (content_bbox["x0"] + content_bbox["x1"]) / 2.0
    content_center_y = (content_bbox["y0"] + content_bbox["y1"]) / 2.0
    ring_origin = {
        "x": content_center_x - ring_center_x,
        "y": content_center_y - ring_center_y,
    }

    full_order = [block["id"] for block in BLOCKS] + ["guard_ring_outer"]
    full_origins = dict(origins)
    full_origins["guard_ring_outer"] = ring_origin

    full_request = {
        "schema": "klt.gen_compose.request/1",
        "pdk": {"variant": pdk},
        "blocks": [
            {
                "id": block["id"],
                "generator_report": str(
                    (out_dir / f"{block['id']}.gen.json").resolve()
                ),
            }
            for block in BLOCKS
        ]
        + [
            {
                "id": "guard_ring_outer",
                "generator_report": str(
                    (out_dir / "guard_ring_outer.gen.json").resolve()
                ),
            }
        ],
        "placement": {
            "strategy": "explicit",
            "order": full_order,
            "origins_um": full_origins,
        },
        "options": {
            "cell_name": "bandgap_core_floorplan",
            "output": str((out_dir / "bandgap_core_floorplan.gds").resolve()),
        },
    }
    (out_dir / "compose.request.json").write_text(
        json.dumps(full_request, indent=2) + "\n"
    )
    compose = run_klt_json(klt, "gen-compose", str(out_dir / "compose.request.json"))
    (out_dir / "compose.json").write_text(json.dumps(compose, indent=2) + "\n")

    # --- 4. DRC the composed floorplan ---------------------------------------
    drc = run_klt_json(klt, "drc", compose["gds_path"], "--deck", "sky130")
    (out_dir / "drc.json").write_text(json.dumps(drc, indent=2) + "\n")

    # --- 5. Render a per-layer overview PNG for visual verification ---------
    # (common-centroid symmetry / dummy-ring coverage -- issue #15's test
    # plan asks for this to be checked visually, not just DRC pass/fail.)
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

    # --- Record -----------------------------------------------------------
    composed_bbox = compose["bbox_um"]
    composed_area_um2 = (composed_bbox["x1"] - composed_bbox["x0"]) * (
        composed_bbox["y1"] - composed_bbox["y0"]
    )
    budget_um2 = 0.05 * 1000.0 * 1000.0  # 0.05 mm^2 in um^2

    sha = subprocess.run(
        ["git", "-C", str(args.repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    branch = subprocess.run(
        ["git", "-C", str(args.repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = (
        subprocess.run(
            ["git", "-C", str(args.repo_root), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        != ""
    )
    klt_version = subprocess.run(
        [klt, "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()

    drc_clean = drc.get("status") == "clean"

    lines: list[str] = []
    a = lines.append
    a(f"# Bandgap-core floorplan skeleton DRC record: {args.record_id}")
    a("")
    a(
        "Initial placed layout skeleton for issue #15 (floorplan + matching "
        "plan). See `layout/matching-plan.md` for the full matching-effort "
        "rationale this floorplan implements -- this record is the DRC "
        "evidence for the skeleton that document describes, not a "
        "substitute for it."
    )
    a("")
    a("## Overall verdict: " + ("PASS" if drc_clean else "FAIL"))
    a("")
    a(f"- [{'x' if drc_clean else ' '}] DRC on the composed floorplan is clean")
    a(
        f"- [{'x' if composed_area_um2 <= budget_um2 else ' '}] Composed bbox "
        f"area ({composed_area_um2:,.0f} um^2) is within the < 0.05 mm^2 "
        f"({budget_um2:,.0f} um^2) budget"
    )
    a("")
    a("## Flow")
    a("")
    a(
        "1. `klt gen` once per matched device group (10 blocks -- see "
        "`compose.inner.request.json` and each `<id>.gen.json`)."
    )
    a(
        "2. `klt gen-compose` with `placement.strategy: \"explicit\"` "
        "(2AMLogic/klayout-tools#330) places all 10 on a computed, "
        "horizontally-centered four-row grid (PNP arrays / resistor "
        "ladders / amp input+load pair / amp mirror pairs) -- `compose.inner.request.json`."
    )
    a(
        "3. `klt gen guard_ring`, sized and centered from the composed "
        "content's own reported bbox, wraps the whole floorplan."
    )
    a(
        "4. A second `klt gen-compose` places all 10 blocks plus the ring "
        "-- `compose.request.json` -> `bandgap_core_floorplan.gds`."
    )
    a("5. `klt drc bandgap_core_floorplan.gds --deck sky130`.")
    a(
        "6. `klt render bandgap_core_floorplan.gds` -- per-layer + combined "
        "overview PNGs, for the visual common-centroid/dummy-ring check "
        "below (not itself DRC/LVS evidence)."
    )
    a("")
    a("## Visual verification")
    a("")
    a(
        "![floorplan overview](renders/overview.png)\n\n"
        "Read left-to-right, bottom-to-top by `origin_um` (see "
        "`compose.request.json`): row 0 (lowest y) is the PNP CTAT/PTAT "
        "pair, row 1 the resistor ladders, row 2 the amp input pair + NMOS "
        "loads, row 3 (highest y) the amp mirror pairs + core mirror, all "
        "enclosed by the outer guard ring. Each matched group's own inner "
        "ring and interdigitated/cross-quad striping (from `bjt_array`'s "
        "`topology=common_centroid` and `diff_pair`'s cross-quad `splits`) "
        "is visible at this render scale; per-layer PNGs are under "
        "`renders/` for a closer look at any one layer."
    )
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
    a("## Composed floorplan")
    a("")
    a(f"- Composed bbox (um): `{composed_bbox}`")
    a(f"- Composed bbox area: {composed_area_um2:,.0f} um^2 (budget: {budget_um2:,.0f} um^2)")
    a(f"- Outer guard ring: inner {inner_width_um:.2f} x {inner_height_um:.2f} um, "
      f"ring width {RING_WIDTH_UM} um, {RING_CONTACTS_PER_SIDE} contacts/side")
    a("")
    a("## Results")
    a("")
    a("| Stage | Status | Detail |")
    a("| --- | --- | --- |")
    a(
        "| DRC | "
        f"{drc.get('status')} | violation_count={drc.get('violation_count')} |"
    )
    if not drc_clean:
        a("")
        a("### DRC violations")
        a("")
        for v in drc.get("violations", [])[:50]:
            a(f"- {v}")
    a("")
    a("## What this record does NOT claim")
    a("")
    a(
        "- **No LVS.** `klt extract`/`klt lvs` are not run on the composed "
        "output -- `bjt_array` and `res_array` output are both known not to "
        "round-trip through `klt extract` as recognized `pnp`/`resistor` "
        "devices today (2AMLogic/klayout-tools#176, #369), so an LVS claim "
        "here would not be meaningful evidence. DRC-clean is this issue's "
        "acceptance bar; LVS-clean bandgap-core layout is later work."
    )
    a(
        "- **Not to scale on the resistor ladder.** `res_r2` uses a reduced "
        "representative segment count (16, not the real 108) -- see the "
        "Blocks table above and `layout/matching-plan.md`; "
        "2AMLogic/klayout-tools#415 tracks the folding gap that blocks a "
        "full-scale single-row layout from fitting the area budget."
    )
    a(
        "- **Row placement within the amp/resistor groups is illustrative, "
        "not final.** The four-row grid establishes the relative "
        "floorplan (PNP arrays / resistor ladders / amp input+load pair / "
        "amp mirror pairs) and "
        "proves the composition + DRC-clean mechanism; exact spacing, "
        "routing, and the amp-quad simplification (MN1..MN4 split into two "
        "matched pairs -- see the Blocks table) are documented open items "
        "in `layout/matching-plan.md`, not finished tape-out geometry."
    )
    a("")
    a("## Provenance")
    a("")
    a(f"- Record ID: `{args.record_id}`")
    a(f"- `klt` version: `{klt_version}` (pinned commit, see `layout/requirements.txt`)")
    a(
        "- KLayout engine version: "
        f"`{drc.get('provenance', {}).get('klayout_version')}`"
    )
    a(f"- Repo state: `{sha}` on `{branch}`" + (" (dirty)" if dirty else ""))
    a("")
    a("## Links")
    a("")
    a("- [`compose.inner.request.json`](compose.inner.request.json), "
      "[`compose.inner.json`](compose.inner.json)")
    a("- [`compose.request.json`](compose.request.json), [`compose.json`](compose.json)")
    a("- [`drc.json`](drc.json)")
    a("- [`render.json`](render.json), [`renders/overview.png`](renders/overview.png)")
    a("- [`bandgap_core_floorplan.gds`](bandgap_core_floorplan.gds)")
    a("")

    (out_dir / "record.md").write_text("\n".join(lines))
    print("\n".join(lines))
    return 0 if drc_clean else 1


if __name__ == "__main__":
    sys.exit(main())
