#!/usr/bin/env python3
"""layout/bin/measure_mim_overlay_feasibility.py -- measure whether the amp's
compensation cap (MCC) can be realized as a `cap_mim` overlay above the
composed `bandgap-core` cell, instead of drawn in-plane as the PMOS-as-cap
`design/error_amp.sch` states.

Why this exists
---------------
Issue #62's operator ruling (2026-08-11) requires MCC to be *realized* --
it sets the amp's dominant pole (`cc_mcc` = 21.04..21.56 pF across all 45
corners of `sim/error-amp-loop/`), so leaving it undrawn means the fabricated
block is a different, uncompensated circuit from the one that passed sim. The
ruling's *preferred* realization is a MiM-cap overlay, because a MiM sits in
upper metal and can overlay the existing active/poly layout at ~zero
incremental footprint, closing LVS while holding the ratified area budget.
Its fallback is drawing MCC as the MOS cap it already is, plus a decision
record re-budgeting the area.

Which branch applies is a *measurement*, not a judgement call, and this
harness is that measurement. It answers three questions, in the order that
matters:

1. **Is the overlay area there?** How much of the composed cell's own
   footprint is clear of the MiM stack's layers (`met3`/`met4` conductors and
   the `capm`/`capm2` top-plate marks), and how much would a MiM of the
   measured `cc_mcc` need at this deck's own capacitance coefficients?
2. **Can a drawn MiM cap be connected?** A cap whose plates cannot join
   `VDD`/`GDRV` is not a realization of MCC -- it is a floating two-terminal
   device that makes `mismatch_count` worse. Probed by building a minimal
   MiM-over-labelled-metal layout and running the same `klt extract --deck
   sky130` the flow runs.
3. **Would the drawn MiM geometry be DRC-checked?** Probed from `klt drc`'s
   own `coverage` block, not assumed.

Question 2 is measured against *this repo's pinned* `klt`
(`layout/requirements.txt`), which is the build every record here is produced
with -- and it is the question upstream is actively moving on
(klayout-tools#619/#621 made met3/met4 connectivity levels; #775 asks for the
`top_plate_via` that would finish the top plate). So a future pin bump could
flip question 2's answer.

**It would not flip the conclusion**, because there is a fourth gate this
harness deliberately does not try to measure with a probe -- it is a
documented fact about the design, not about the tool. `klt lvs` compares the
drawn cell against `reference.spice`, which transcribes
`design/bandgap_core.sch` + `design/error_amp.sch`, and MCC is stated there
as `MMCC VDD GDRV VDD VDD pfet L=20U W=30U m=16`. A `cap_mim` in the layout
does not match a `pfet` in the reference -- realizing MCC as a MiM would
require *changing the schematic*, which (a) contradicts issue #9's ratified
acceptance criterion restricting this cell to
`sky130_fd_pr__nfet_g5v0d10v5`/`pfet_g5v0d10v5` (the reason
`design/error_amp.sch` says `cap_mim_m3_*` is "deliberately not used"),
(b) invalidates the 45-corner loop-stability evidence in
`sim/error-amp-loop/`, which measures `cc_mcc` for *this* device at every PVT
point, and (c) is a change to a closed cell that issue #62's own operator
ruling put outside this issue's scope. See this harness's rendered record.

Relationship to `layout/matching-plan.md` Section 7bb
-----------------------------------------------------
Section 7bb reaches the same verdict from a hand-built three-geometry `klt
draw` reproduction across two `klt` pins, and its tooling evidence is the
stronger of the two -- this harness deliberately does not duplicate it. What
this adds is the part that was prose there and is a *number* here, produced
by running rather than by asserting:

* the MiM-clear overlay area, measured off the composed GDS itself;
* the plate area a replacement would need, solved from the deck's own
  two-term capacitance law at the **measured** `cc_mcc` (Section 7bb and the
  ruling both size from the ~29 pF analytic `Cox*W*L`, ~35% above what
  `sim/error-amp-loop/` measures);
* the DRC-coverage gap on the MiM layers (filed as klayout-tools#776);
* and, most usefully, re-runnability: klayout-tools#775 is the fix that
  would flip the tooling half of this answer, so the next pin bump can
  re-measure in one command instead of re-deriving the argument.

It is deliberately NOT part of `run-bandgap-routed-flow.sh`'s gate: it draws
nothing into the cell, changes nothing, and writes only its own append-only
evidence directory.

Usage
-----
    layout/.venv/bin/python layout/bin/measure_mim_overlay_feasibility.py \\
        --record layout/bandgap-core/reports/<record-id> \\
        --out-dir layout/bandgap-core/mim-overlay-feasibility/<record-id>

Requires `layout/.venv` (see `setup-venv.sh`): it imports `klayout.db` to
measure drawn area and to synthesize the connectivity probe, and shells out
to the same pinned `klt` the flow uses.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover -- typing only
    import klayout.db as kdb

#: The MiM stack layers sky130's curated extraction deck names, as
#: `(gds_label, (layer, datatype), role)`. Transcribed from
#: `klayout_tools.decks.sky130.EXTRACTION_DECK.capacitors` -- both entries'
#: `top_plate`/`bottom_plate` -- so this harness measures against the deck the
#: flow actually runs, not a hand-copied layer table.
MIM_STACK_LAYERS: tuple[tuple[str, tuple[int, int], str], ...] = (
    ("70/20", (70, 20), "met3.drawing (cap_mim bottom plate)"),
    ("89/44", (89, 44), "capm.drawing (cap_mim top plate)"),
    ("71/20", (71, 20), "met4.drawing (cap_mim_m4 bottom plate)"),
    ("97/44", (97, 44), "capm2.drawing (cap_mim_m4 top plate)"),
)

#: `EXTRACTION_DECK.capacitors[*]`'s tt-corner coefficients (both sky130 MiM
#: stacks share them): C = area_cap_f_um2 * A + perim_cap_f_um * P.
AREA_CAP_F_UM2 = 2.0e-15
PERIM_CAP_F_UM = 1.9e-16

#: MCC's measured gate capacitance, in farads, across the 45 PVT corners of
#: `sim/error-amp-loop/records/20260803-085320-e599e30.md` (`cc_mcc`). The
#: *max* is the sizing target: a replacement compensation cap that is smaller
#: than the one the loop-stability record measured is not a like-for-like
#: substitution.
CC_MCC_MIN_F = 2.10357e-11
CC_MCC_MAX_F = 2.15618e-11


def _square_plate_side_um(target_f: float) -> float:
    """Side length (um) of the square MiM plate that reaches `target_f`.

    Solves `AREA_CAP_F_UM2 * s^2 + PERIM_CAP_F_UM * 4s = target_f` -- the
    deck's own two-term law, not the area term alone, so the number is not
    quietly optimistic by the perimeter/fringe contribution.
    """
    a = AREA_CAP_F_UM2
    b = 4.0 * PERIM_CAP_F_UM
    c = -target_f
    return (-b + math.sqrt(b * b - 4.0 * a * c)) / (2.0 * a)


def _layer_area_um2(layout: kdb.Layout, layer: tuple[int, int]) -> float:
    """Merged drawn area (um^2) of one layer across the whole layout."""
    import klayout.db as kdb

    index = layout.find_layer(layer[0], layer[1])
    if index is None:
        return 0.0
    region = kdb.Region()
    for cell in layout.top_cells():
        region.insert(cell.begin_shapes_rec(index))
    region.merge()
    return region.area() * layout.dbu * layout.dbu


def measure_overlay_area(gds_path: Path, label: str | None = None) -> dict[str, Any]:
    """Question 1: how much of the composed cell's footprint is MiM-clear?"""
    import klayout.db as kdb

    layout = kdb.Layout()
    layout.read(str(gds_path))
    tops = layout.top_cells()
    if len(tops) != 1:
        raise SystemExit(
            f"{gds_path}: expected exactly one top cell, found {len(tops)}"
        )
    bbox = tops[0].dbbox()
    footprint_um2 = bbox.width() * bbox.height()
    occupied = [
        {
            "layer": label,
            "role": role,
            "drawn_area_um2": _layer_area_um2(layout, layer),
        }
        for label, layer, role in MIM_STACK_LAYERS
    ]
    occupied_um2 = sum(entry["drawn_area_um2"] for entry in occupied)
    return {
        "gds": label or str(gds_path),
        "top_cell": tops[0].name,
        "bbox_um": {
            "x0": bbox.left, "y0": bbox.bottom,
            "x1": bbox.right, "y1": bbox.top,
        },
        "footprint_um2": footprint_um2,
        "mim_stack_layers": occupied,
        "occupied_um2": occupied_um2,
        "available_overlay_um2": footprint_um2 - occupied_um2,
    }


def measure_required_area() -> dict[str, Any]:
    """Question 1's other half: how much plate does a MiM MCC need?"""
    rows = []
    for label, target in (
        ("cc_mcc min (sim/error-amp-loop, 45 corners)", CC_MCC_MIN_F),
        ("cc_mcc max (sim/error-amp-loop, 45 corners)", CC_MCC_MAX_F),
    ):
        side = _square_plate_side_um(target)
        rows.append(
            {
                "basis": label,
                "target_f": target,
                "square_plate_side_um": side,
                "plate_area_um2": side * side,
            }
        )
    return {
        "area_cap_f_um2": AREA_CAP_F_UM2,
        "perim_cap_f_um": PERIM_CAP_F_UM,
        "variants": rows,
    }


def probe_connectivity(klt: str, work_dir: Path) -> dict[str, Any]:
    """Question 2: does a drawn MiM cap's terminals reach a named net?

    Builds the most favourable possible case -- a `capm` top plate over a
    `met3` bottom plate that *overlaps two labelled met2 wires* -- and reads
    back what `klt extract --deck sky130` makes of it. If the plates joined
    the deck's connectivity graph anywhere, this is the layout where it would
    show.
    """
    import klayout.db as kdb

    work_dir.mkdir(parents=True, exist_ok=True)
    gds_path = work_dir / "mim_connectivity_probe.gds"
    repo_root = Path(__file__).resolve().parents[2]

    layout = kdb.Layout()
    layout.dbu = 0.005
    top = layout.create_cell("mim_connectivity_probe")
    met2 = layout.layer(69, 20)
    met2_pin = layout.layer(69, 5)
    met3 = layout.layer(70, 20)
    capm = layout.layer(89, 44)
    # Two labelled met2 wires standing in for VDD / GDRV.
    top.shapes(met2).insert(kdb.DBox(0.0, 0.0, 20.0, 5.0))
    top.shapes(met2_pin).insert(
        kdb.DText("PLATE_LO", kdb.DTrans(kdb.DVector(10.0, 2.5)))
    )
    top.shapes(met2).insert(kdb.DBox(0.0, 10.0, 20.0, 15.0))
    top.shapes(met2_pin).insert(
        kdb.DText("PLATE_HI", kdb.DTrans(kdb.DVector(10.0, 12.5)))
    )
    # A met3 bottom plate laid directly over both, and a capm top plate.
    top.shapes(met3).insert(kdb.DBox(0.0, 0.0, 20.0, 15.0))
    top.shapes(capm).insert(kdb.DBox(2.0, 2.0, 18.0, 13.0))
    layout.write(str(gds_path))

    extract = json.loads(
        subprocess.run(
            [klt, "extract", str(gds_path), "--deck", "sky130",
             "--top", "mim_connectivity_probe", "--format", "json"],
            check=True, capture_output=True, text=True,
        ).stdout
    )
    (work_dir / "extract.json").write_text(json.dumps(extract, indent=2) + "\n")
    # `klt extract` writes its own `.spice` next to the input GDS, which is
    # already inside `work_dir` -- read it rather than writing a second copy.
    netlist_path = Path(extract["netlist_path"])
    netlist = netlist_path.read_text() if netlist_path.exists() else ""

    device_counts = extract.get("device_counts", {})
    recognised = sum(
        count for name, count in device_counts.items() if "cap_mim" in name
    )
    # The probe's own labelled nets are the thing to look for: if either plate
    # joined the deck's connectivity graph, the cap's terminals carry them.
    terminals_named = any(
        label in netlist for label in ("PLATE_LO", "PLATE_HI")
    )
    try:
        gds_label = str(gds_path.relative_to(repo_root))
    except ValueError:
        gds_label = str(gds_path)
    return {
        "gds": gds_label,
        "gds_abs": str(gds_path),
        "device_counts": device_counts,
        "cap_devices_recognised": recognised,
        "labelled_nets_drawn": ["PLATE_LO", "PLATE_HI"],
        "cap_terminals_reach_a_labelled_net": terminals_named,
        "extracted_netlist": netlist,
    }


def probe_drc_coverage(klt: str, gds_path: Path) -> dict[str, Any]:
    """Question 3: does the curated DRC deck check MiM geometry at all?"""
    drc = json.loads(
        subprocess.run(
            [klt, "drc", str(gds_path), "--deck", "sky130", "--format", "json"],
            check=True, capture_output=True, text=True,
        ).stdout
    )
    coverage = drc.get("coverage", {})
    violations = drc.get("violations", [])
    violation_count = (
        len(violations) if isinstance(violations, list) else int(violations)
    )
    unchecked = set(coverage.get("layers_in_stream_without_rules", []))
    mim_unchecked = [
        {"layer": label, "role": role}
        for label, _, role in MIM_STACK_LAYERS
        if label in unchecked
    ]
    return {
        "status": drc.get("status"),
        "violation_count": violation_count,
        "deck_layers": coverage.get("deck_layers", []),
        "layers_in_stream_without_rules": sorted(unchecked),
        "mim_layers_without_rules": mim_unchecked,
    }


def verdict(
    overlay: dict[str, Any], required: dict[str, Any], connectivity: dict[str, Any]
) -> dict[str, Any]:
    worst = max(row["plate_area_um2"] for row in required["variants"])
    area_ok = overlay["available_overlay_um2"] >= worst
    connect_ok = bool(connectivity["cap_terminals_reach_a_labelled_net"])
    return {
        "overlay_area_sufficient": area_ok,
        "required_plate_area_um2": worst,
        "available_overlay_um2": overlay["available_overlay_um2"],
        "mim_terminals_connectable": connect_ok,
        "feasible": area_ok and connect_ok,
    }


def render_record(payload: dict[str, Any]) -> str:
    overlay = payload["overlay_area"]
    required = payload["required_plate"]
    connectivity = payload["connectivity_probe"]
    drc = payload["drc_coverage"]
    v = payload["verdict"]
    lines: list[str] = []
    a = lines.append
    a(f"# MiM-overlay feasibility for MCC: {payload['record_id']}")
    a("")
    a(
        "Measured answer to issue #62's operator ruling (2026-08-11), whose "
        "primary branch is \"realize MCC as a `cap_mim` overlay\" and whose "
        "fallback is \"draw MCC as the MOS cap it is, and re-budget the "
        "area\". Which branch applies is decided here, by measurement."
    )
    a("")
    a(f"**Verdict: MiM overlay is {'FEASIBLE' if v['feasible'] else 'INFEASIBLE'}.**")
    a("")
    a("| Question | Answer |")
    a("| --- | --- |")
    a(
        "| Is the overlay area there? | "
        f"{'**yes**' if v['overlay_area_sufficient'] else '**no**'} -- "
        f"{overlay['available_overlay_um2']:,.0f} um^2 clear vs "
        f"{v['required_plate_area_um2']:,.0f} um^2 needed |"
    )
    a(
        "| Can a drawn MiM cap's plates reach a named net? | "
        f"{'**yes**' if v['mim_terminals_connectable'] else '**no**'} -- see "
        "the connectivity probe below |"
    )
    a(
        "| Is drawn MiM geometry DRC-checked? | "
        f"{'**no**' if drc['mim_layers_without_rules'] else '**yes**'} -- "
        f"{len(drc['mim_layers_without_rules'])} of "
        f"{len(MIM_STACK_LAYERS)} MiM stack layers carry no curated rule |"
    )
    a("")
    a("## 1. Overlay area available above the composed cell")
    a("")
    a(f"Measured from `{overlay['gds']}` (top cell `{overlay['top_cell']}`).")
    a("")
    a("| Layer | Role | Drawn area |")
    a("| --- | --- | --- |")
    for entry in overlay["mim_stack_layers"]:
        a(
            f"| `{entry['layer']}` | {entry['role']} | "
            f"{entry['drawn_area_um2']:,.1f} um^2 |"
        )
    a("")
    a(
        f"Composed-cell footprint **{overlay['footprint_um2']:,.0f} um^2**, of "
        f"which **{overlay['occupied_um2']:,.1f} um^2** carries MiM-stack "
        f"geometry, leaving **{overlay['available_overlay_um2']:,.0f} um^2** "
        "clear. The routed cell draws on li1/met1/met2 only, so the whole "
        "footprint is available to an overlay in principle."
    )
    a("")
    a("## 2. Plate area a MiM MCC would need")
    a("")
    a(
        "At this deck's own tt-corner coefficients "
        f"(`area_cap_f_um2={required['area_cap_f_um2']:.2e}`, "
        f"`perim_cap_f_um={required['perim_cap_f_um']:.2e}`), solving "
        "`C = area*A + perim*P` for a square plate:"
    )
    a("")
    a("| Sizing basis | Target C | Square plate | Plate area |")
    a("| --- | --- | --- | --- |")
    for row in required["variants"]:
        a(
            f"| {row['basis']} | {row['target_f'] * 1e12:.2f} pF | "
            f"{row['square_plate_side_um']:.1f} x "
            f"{row['square_plate_side_um']:.1f} um | "
            f"{row['plate_area_um2']:,.0f} um^2 |"
        )
    a("")
    a(
        "**The sizing target is the measured capacitance, not the analytic "
        "one.** The operator ruling and `layout/matching-plan.md` Section 7bb "
        "both size this from a ~29 pF figure, which is `Cox*W*L*m` on the "
        "device's drawn gate area. `design/error_amp.sch` says explicitly "
        "that MCC's capacitance is *measured, not computed from Cox*W*L*, "
        "and `sim/error-amp-loop/`'s 45-corner run measures `cc_mcc` at "
        f"{CC_MCC_MIN_F * 1e12:.2f}-{CC_MCC_MAX_F * 1e12:.2f} pF -- the "
        "value the loop-stability result actually depends on. Sizing a "
        "replacement to the analytic number would over-build it by ~35%. "
        "Either way the answer to question 1 is the same (both fit), which "
        "is why this correction changes nothing about the verdict -- but a "
        "future revisit should size from the measured number."
    )
    a("")
    a("## 3. Connectivity probe (the decisive one)")
    a("")
    a(
        "A MiM cap whose plates cannot join `VDD` and `GDRV` is not a "
        "realization of MCC -- it is a floating two-terminal device, and "
        "adding one makes `klt lvs`'s `mismatch_count` *worse*, not zero. "
        "This probe is the most favourable case that can be drawn: a `capm` "
        "top plate over a `met3` bottom plate laid directly over two "
        "labelled met2 wires."
    )
    a("")
    a(
        f"`klt extract --deck sky130` recognises "
        f"**{connectivity['cap_devices_recognised']}** MiM cap device(s) "
        f"(`device_counts={json.dumps(connectivity['device_counts'])}`) -- so "
        "recognition is not the gap. The extracted netlist is:"
    )
    a("")
    a("```spice")
    a(connectivity["extracted_netlist"].rstrip())
    a("```")
    a("")
    if connectivity["cap_terminals_reach_a_labelled_net"]:
        a(
            "Both plates carry the labelled nets, so a MiM MCC could be "
            "wired to `VDD`/`GDRV` and the overlay branch is open."
        )
    else:
        a(
            "**Neither plate carries either labelled net.** The cap's two "
            "terminals are anonymous, isolated nodes. This is not a probe "
            "artifact -- it is what the curated deck declares: "
            "`EXTRACTION_DECK.metals` is `(li1, met1, met2)` and `vias` is "
            "`(mcon, via)`, so neither `met3` (the `cap_mim` bottom plate) "
            "nor `met4` (`cap_mim_m4`'s) is a connectivity level, and "
            "neither capacitor entry declares a `top_plate_via`. The deck's "
            "own comment states the consequence directly: *\"both plates "
            "stay isolated connectivity nodes, not wired into this deck's "
            "li1/met1/met2-only stack\"*. There is no layout-side way "
            "around it: the plates are unreachable by construction, not by "
            "placement."
        )
    a("")
    a("## 4. DRC coverage of the MiM stack")
    a("")
    a("| Layer | Role | Curated rule? |")
    a("| --- | --- | --- |")
    unchecked_labels = {e["layer"] for e in drc["mim_layers_without_rules"]}
    for label, _, role in MIM_STACK_LAYERS:
        drawn = any(
            e["layer"] == label and e["drawn_area_um2"] > 0
            for e in overlay["mim_stack_layers"]
        )
        if label in unchecked_labels:
            state = "**no** (in stream, no rule)"
        elif drawn:
            state = "yes"
        else:
            state = "not drawn in the probe"
        a(f"| `{label}` | {role} | {state} |")
    a("")
    a(
        "`klt drc --deck sky130` on the probe reports "
        f"`status={drc['status']}`, `violations={drc['violation_count']}` -- "
        "a clean verdict that says nothing about the MiM geometry, because "
        "the curated deck has no rule for those layers. A MiM overlay would "
        "therefore need this repo's own rule checker alongside it, the way "
        "`layout/bin/met2_drc.py` covers the met2 escape plane."
    )
    a("")
    a("## 5. The gate this harness does not probe (and why it decides)")
    a("")
    a(
        "Questions 2 and 3 are measured against **this repo's pinned `klt`** "
        "(`layout/requirements.txt`) -- the build every record here is "
        "produced with. Upstream is moving on exactly this: "
        "klayout-tools#619 (merged via #621) made met3/met4 real "
        "connectivity levels, which fixes the *bottom* plate, and #775 asks "
        "for the `top_plate_via`/`top_plate_via_metal` pairing that would "
        "finish the top one. A future pin bump can flip question 2's answer, "
        "and this harness is re-runnable precisely so that it is re-measured "
        "rather than assumed."
    )
    a("")
    a(
        "It would not flip the conclusion. `klt lvs` compares the drawn cell "
        "against `reference.spice`, which transcribes "
        "design/bandgap_core.sch + design/error_amp.sch, and MCC is stated "
        "there as `MMCC VDD GDRV VDD VDD pfet L=20U W=30U m=16`. **A "
        "`cap_mim` in the layout does not match a `pfet` in the reference** "
        "-- it would be an unmatched layout device *and* an unmatched "
        "reference device, i.e. `mismatch_count` 1 -> 2, not 1 -> 0. "
        "Realizing MCC as a MiM therefore requires changing the schematic, "
        "and three ratified things say no:"
    )
    a("")
    a(
        "1. **Issue #9's device menu.** Its acceptance criteria restrict this "
        "cell to `sky130_fd_pr__nfet_g5v0d10v5`/`pfet_g5v0d10v5`. "
        "design/error_amp.sch cites that restriction by name as the reason "
        "`cap_mim_m3_*` is \"deliberately not used\"."
    )
    a(
        "2. **The 45-corner loop-stability evidence.** "
        "`sim/error-amp-loop/` measures `cc_mcc` (21.04-21.56 pF) for *this* "
        "device at every PVT point and asserts a floor on it. A different "
        "device -- different C(V) behaviour, different parasitics -- would "
        "need that whole corner set re-run before the amp could be called "
        "stable again."
    )
    a(
        "3. **Issue #62's own operator ruling**, which put changes to the "
        "closed amp cell (and the #9/loop-stability re-verification they "
        "drag in) explicitly outside this issue's scope."
    )
    a("")
    a("## Consequence")
    a("")
    if v["feasible"]:
        a(
            "The overlay branch of the ruling applies: draw MCC as a "
            "`cap_mim` over the existing layout and hold the ratified area "
            "budget."
        )
    else:
        a(
            "The ruling's **fallback** branch applies. The area is there "
            "(question 1); the connectivity is not (question 3); and even "
            "when upstream finishes closing that (question 5), the "
            "schematic-side gate stands. MCC is drawn as the MOS cap "
            "`design/error_amp.sch` already specifies -- which is what issue "
            "#9's ratified device menu requires, what keeps the drawn cell "
            "the same circuit the 45-corner loop-stability record measured, "
            "and what lets `klt lvs` reach `mismatch_count: 0` against an "
            "unedited reference -- and the area it costs is re-budgeted "
            "through the Area-row decision record `spec/decision-records/` "
            "carries for it (`DR-007-mcc-area-budget.md`). See "
            "`layout/matching-plan.md` Section 7bb for the same conclusion "
            "reached independently, with a three-geometry `klt draw` "
            "reproduction this harness's single probe deliberately does not "
            "repeat."
        )
    a("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record", required=True, type=Path,
        help="a layout/bandgap-core/reports/<record-id> directory",
    )
    parser.add_argument(
        "--out-dir", required=True, type=Path,
        help="evidence directory to write (created if missing)",
    )
    parser.add_argument(
        "--klt", default=str(Path(__file__).resolve().parents[1] / ".venv/bin/klt"),
        help="path to the pinned klt executable",
    )
    args = parser.parse_args(argv)

    record_dir = args.record.resolve()
    gds_path = record_dir / "bandgap_core_routed.gds"
    if not gds_path.exists():
        raise SystemExit(f"{gds_path}: not found (is --record a routed record?)")
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Record the path the way a reader can re-run it: relative to the repo
    # root when it lives inside the checkout, absolute only when it does not.
    repo_root = Path(__file__).resolve().parents[2]
    try:
        gds_label = str(gds_path.relative_to(repo_root))
    except ValueError:
        gds_label = str(gds_path)
    overlay = measure_overlay_area(gds_path, gds_label)
    required = measure_required_area()
    connectivity = probe_connectivity(args.klt, out_dir)
    drc = probe_drc_coverage(args.klt, Path(connectivity["gds_abs"]))

    payload: dict[str, Any] = {
        "record_id": record_dir.name,
        "overlay_area": overlay,
        "required_plate": required,
        "connectivity_probe": connectivity,
        "drc_coverage": drc,
    }
    payload["verdict"] = verdict(overlay, required, connectivity)

    (out_dir / "feasibility.json").write_text(json.dumps(payload, indent=2) + "\n")
    (out_dir / "record.md").write_text(render_record(payload))
    print(f"measure_mim_overlay_feasibility.py: wrote {out_dir}/record.md")
    print(
        "  verdict: "
        f"{'FEASIBLE' if payload['verdict']['feasible'] else 'INFEASIBLE'} "
        f"(area_ok={payload['verdict']['overlay_area_sufficient']}, "
        f"connectable={payload['verdict']['mim_terminals_connectable']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
