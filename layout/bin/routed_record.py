#!/usr/bin/env python3
"""layout/bin/routed_record.py -- issue #227: the record.md scoreboard
renderer split out of `gen_bandgap_routed.py`'s own Step 10 ("Record"), the
same shape of move #223 already made for that file's bus/routing logic
(`bus_routing.py`). Pure move, verbatim (including comments); no behavior
change -- `render_record()`'s inputs are exactly the values `main()`'s Step
10 already had fully computed in hand, and its output is byte-identical
`record.md` content for the same inputs.

`render_record` is the only symbol `gen_bandgap_routed.py` calls from
outside this module; `RecordResult` is its return type, carrying both the
rendered markdown text and the handful of scoreboard booleans/counts that
`main()`'s own `flow_gate()` call still needs (the other `flow_gate` inputs
-- `met1_conflicts`, `merged_pin_names`, `met1_split_routed`, `met2_drc`'s
own status -- are already in `main()`'s hands before Step 10 runs, so they
are not round-tripped through here).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

# gen_bandgap_routed.py's own use of this module's symbols is imported
# locally, inside main() (see that file's own note next to where this
# section used to live) -- so this is the only direction with a genuine
# top-level dependency between the two modules, the same shape bus_routing.py
# already uses for its own back-import from gen_bandgap_routed.py.
from gen_bandgap_routed import (  # noqa: E402
    BLOCKS,
    DUMMY_DEVICE_NOTE,
    INTERNAL_NODE_LABEL_NOTE,
    MCC_AREA_UM2_NOTE,
    N_R2_COARSE,
    N_R2_TRIM_CODES,
    N_R2_TRIM_UNITS,
    PNP_EMITTER_GEOMETRY_NOTE,
    RES_BULK_ARITY_NOTE,
    RES_CLASS,
    RES_HEAD_SIZING_NOTE,
    RES_TRIM_LENGTH_NOTE,
    R_LSEG_TRIM_UM,
    R_LSEG_UM,
    SUBSTRATE_NET_NOTE,
    git,
    met2_drc_coverage_note,
    r2_leg_length,
    schematic_net_coverage,
    trim_tap_ladder,
)
from bus_routing import MOS_HALVES  # noqa: E402


@dataclass(frozen=True)
class RecordResult:
    """`render_record()`'s return value.

    `text` is the full rendered `record.md` content (already written to
    disk by `render_record` itself); the rest are the scoreboard values
    `main()`'s own `flow_gate()` call needs and that this function is the
    one place that computes.
    """

    text: str
    drc_clean: bool
    within_budget: bool
    full_scale_ladder: bool
    r2_leg_matches: bool
    all_classes: bool
    pin_count: int


def render_record(
    *,
    args: argparse.Namespace,
    cell: str,
    klt: str,
    out_dir: Path,
    compose: dict[str, Any],
    drc: dict[str, Any],
    met2_drc: dict[str, Any],
    extract: dict[str, Any],
    lvs: dict[str, Any],
    lvs_combined: dict[str, Any],
    lvs_plain: dict[str, Any],
    inner_compose: dict[str, Any],
    met1_routes: list[dict[str, Any]],
    met1_conflicts: list[Any],
    met1_components: dict[str, int],
    met1_split_routed: dict[str, int],
    merged_pin_names: list[str],
    reports: dict[str, dict[str, Any]],
    bus_summary: dict[str, Any],
) -> RecordResult:
    """Render the acceptance-criteria scoreboard + prose record.md.

    Extracted verbatim from `gen_bandgap_routed.main()`'s own Step 10
    ("Record") -- see that function's docstring history and issue #227.
    Every parameter here is a value `main()` already has fully computed by
    the time it reaches Step 10; this function adds no new computation over
    devices/nets/etc. beyond what the record text itself states.
    """
    composed_bbox = compose["bbox_um"]
    composed_area_um2 = (composed_bbox["x1"] - composed_bbox["x0"]) * (
        composed_bbox["y1"] - composed_bbox["y0"]
    )
    budget_um2 = 0.08 * 1000.0 * 1000.0  # DR-007: relaxed from 0.05 to fit the drawn MCC cap (operator-ratified, #62)

    sha = git(args.repo_root, "rev-parse", "HEAD")
    branch = git(args.repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    dirty = git(args.repo_root, "status", "--porcelain") != ""
    klt_version = subprocess.run(
        [klt, "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()

    drc_clean = drc.get("status") == "clean"
    within_budget = composed_area_um2 <= budget_um2
    device_counts = extract.get("device_counts", {})
    routed_nets = [r for r in met1_routes if r["routed"]]
    unrouted = [r["net"] for r in met1_routes if not r["routed"]]
    labelled_pins = [p for p in inner_compose.get("pins", []) if p.get("labelled")]
    trim_taps = trim_tap_ladder(reports)
    r2_length = r2_leg_length()
    pin_count = extract.get("pin_count", 0)
    lvs_clean = lvs.get("status") == "match"
    classes_present = {
        "pnp": device_counts.get("pnp", 0) > 0,
        "nfet": device_counts.get("nfet", 0) > 0,
        "pfet": device_counts.get("pfet", 0) > 0,
        # `res_high_po` since 2AMLogic/klayout-tools#463 (merged via #475) --
        # the schematic's own flavour, drawable at last. The base
        # `res_generic_po` counts too: the class the layout should carry is
        # whichever flavour it drew, and neither is "plain interconnect".
        "resistor": (
            device_counts.get(RES_CLASS, 0) > 0
            or device_counts.get("res_generic_po", 0) > 0
        ),
    }
    all_classes = all(classes_present.values())
    block_params = {b["id"]: b["params"] for b in BLOCKS}
    r2_units = block_params["res_r2"]["num"]
    trim_units = block_params["res_trim"]["num"]
    full_scale_ladder = (
        r2_units == 2 * N_R2_COARSE and trim_units == 2 * N_R2_TRIM_UNITS
    )

    # Criterion 1 is scored against design/bandgap_core.sch's own inter-block
    # node list, NOT against this flow's `connectivity[]` declaration.
    coverage = schematic_net_coverage(met1_routes)
    fully_drawn = [c for c in coverage if c["status"] == "drawn"]
    full_connectivity = len(fully_drawn) == len(coverage) and not unrouted

    lines: list[str] = []
    a = lines.append
    a(f"# Bandgap-core routed layout record: {args.record_id}")
    a("")
    a(
        "Routed-and-extracted successor to the issue #15 placement-only "
        "floorplan skeleton (`layout/bandgap-core/reports/` earlier records). "
        "Read `layout/matching-plan.md` for the matching rationale this "
        "layout implements; this record is the measured evidence, not the "
        "rationale."
    )
    a("")
    a("## Acceptance-criteria scoreboard (issue #62)")
    a("")
    a("| # | Criterion | Status | Evidence |")
    a("| --- | --- | --- | --- |")
    a(
        f"| 1 | Full inter-block routing | "
        f"{'MET' if full_connectivity else 'PARTIAL'} | "
        f"{len(fully_drawn)}/{len(coverage)} **schematic** inter-block nets "
        f"fully drawn ({len(routed_nets)}/{len(met1_routes)} "
        f"declared met1 nets routed, {len(unrouted)} unrouted) -- see "
        "\"Schematic inter-block nets\" below |"
    )
    a(
        f"| 2 | Resistor ladder at real unit count | "
        f"{'MET' if full_scale_ladder and r2_length['matches'] else 'NOT MET'} | "
        f"`res_r2` num={r2_units} (= 2 legs x {N_R2_COARSE} coarse "
        f"{R_LSEG_UM:.0f}um units) + `res_trim` num={trim_units} (= 2 legs x "
        f"{N_R2_TRIM_UNITS} fine {R_LSEG_TRIM_UM:.1f}um units) = "
        f"{r2_length['drawn_um']:.0f} um/leg at DR-002 code 0, against "
        f"design/bandgap_core.sch's `r_lseg*n_r2` = "
        f"{r2_length['spec_um']:.0f} um (delta "
        f"{r2_length['delta_um']:+.0f} um); composed bbox "
        f"{composed_area_um2:,.0f} um^2 vs {budget_um2:,.0f} um^2 budget |"
    )
    a(
        f"| 3 | Extract: correct device classes + promoted pins | "
        f"{'MET' if all_classes and pin_count > 0 else 'PARTIAL'} | "
        f"device_counts={json.dumps(device_counts)}, pin_count={pin_count} |"
    )
    a(
        f"| 4 | `klt lvs` clean | {'MET' if lvs_clean else 'NOT MET'} | "
        f"status={lvs.get('status')}, mismatch_count={lvs.get('mismatch_count')} |"
    )
    a(
        "| 5 | Blocking `klt` gaps filed as friction | MET | every gap this "
        "flow ever named as *blocking* is now CLOSED upstream and this "
        "record is the re-run "
        "against them: 2AMLogic/klayout-tools#461 via #474, #462 via #471, "
        "#463 via #475, #454 via #468, #470 via #481, #490 via #495, #491 "
        "via #494, #492 via #497/#498, #504 via #505, and -- turned on by "
        "the nineteenth increment -- **#508 via #511** (sky130's curated "
        "deck gains met2 as a third connectivity level, which is what makes "
        "criterion 1's escape plane real connectivity rather than inert "
        "geometry; see ROUTING_PLANE_NOTE / MET2_ESCAPE_NOTE). "
        "2AMLogic/klayout-tools#506 (the generic arity reconciliation #505 "
        "deferred, filed by the fifteenth increment) has since closed as "
        "COMPLETED too -- this flow never needed it, because its own "
        "reference can state the bulk net directly. **Every gap this flow "
        "has ever filed as blocking is now closed upstream.** Two "
        "non-blocking gaps were filed by the nineteenth increment: "
        "**klayout-tools#513** is the flip side of #511 -- the curated "
        "sky130 **DRC** deck was not extended alongside the extraction "
        "deck, so `klt drc` returns violation_count=0 on any met2 geometry "
        "whatsoever, and this flow checks the plane itself instead "
        "(`layout/bin/met2_drc.py`, gated; see the met2 DRC row in "
        "Results). **klayout-tools#514** is the labelling gap "
        "INTERNAL_NODE_LABEL_NOTE describes: there is no way to name a net "
        "without promoting it to a pin, and a pin on a node interior to a "
        "schematic device silently blocks `combine_devices` with nothing "
        "attributing the resulting mismatches to it. The twenty-first "
        "increment filed no new gap (the PNP `ae`/`pe`/`ne` fix was a "
        "`reference.spice` transcription fix, needing no new `klt` "
        "capability). **This (twenty-third) increment picks up "
        "2AMLogic/klayout-tools#518 via #519 and #521 via #526** (the "
        "`res_high_po` fixed head/end-resistance term, and the fix that "
        "makes it reach the written netlist `klt lvs` compares) and, "
        "having measured that picking them up does not close AC4's "
        "resistor cause, files one new non-blocking gap: "
        "**klayout-tools#559** -- `ResistorDevice.fixed_offset_ohm` is "
        "charged once per drawn primitive, not once per logical device, "
        "so `combine_devices` folding a caller's own multi-primitive series "
        "decomposition (this flow's trim-tap ladder) sums it once per "
        "primitive instead of once for the schematic-level device. **This "
        "(twenty-eighth) increment bumps the klt pin past #583 (which closed "
        "#559 by deferring that correction until after `combine_devices()` "
        "folds) and #587 (which made the deferral reachable from this flow's "
        "own pre-extracted request shape, closing #585/#586 -- the real "
        "blocker was a case-sensitive device-class lookup that missed the "
        "`NetlistSpiceReader`-uppercased `RES_HIGH_PO` name, NOT "
        "`layout.deck` being ignored on that shape: `layout_deck` resolves "
        "unconditionally in `run_lvs`).** The once-per-combined-device "
        "correction is therefore reachable now, and is measured with "
        "`layout/bin/measure_fixed_offset_variants.py` across all four "
        "accounting combinations (`layout/bandgap-core/"
        "fixed-offset-variants/<record-id>/`). It is **deliberately NOT "
        "adopted**, and at this repo's current state adopting it would be a "
        "measured REGRESSION rather than a neutral choice: since issue #108 "
        "settled `reference.spice` on the CHAINED value this flow's own "
        "multi-primitive decomposition sums to, the shipped per-primitive "
        "accounting is the only variant that matches at all -- #587's own "
        "defer-plus-deck pairing takes `mismatch_count` 1 -> 4 and "
        "`devices.matched` 15 -> 12. DR-003's ratified finding points the "
        "same way: this layout physically pays the head resistance once per "
        "separately-contacted instance, so re-reporting each leg at the "
        "single-device value would state a resistance the fabricated cell "
        "does not have. See RES_HEAD_RESISTANCE_NOTE, DR-003 and "
        "layout/matching-plan.md Section 7z |"
    )
    a("")
    a(f"- [{'x' if drc_clean else ' '}] DRC on the composed, routed layout is clean")
    a(
        f"- [{'x' if within_budget else ' '}] Composed bbox area "
        f"({composed_area_um2:,.0f} um^2) is within the < 0.05 mm^2 "
        f"({budget_um2:,.0f} um^2) budget, **at the real full-length ladder "
        f"count** ({r2_units} coarse + {trim_units} fine units)"
    )
    a("")
    a("## Flow")
    a("")
    a(f"1. `klt gen` once per matched device group ({len(BLOCKS)} blocks).")
    a(
        "2. `klt draw` once, for the whole cell: every intra-block bus and "
        "every inter-block net, on met1 over mcon -- plus, for the hops met1 "
        "has no corridor for, a met2 escape over `via.drawing` "
        "(MET2_ESCAPE_NOTE) -- and one met1 net label per *schematic* node. "
        "`bandgap_core_bus.draw.json`, summarised in `bus-summary.json`."
    )
    a(
        "3. `klt gen-compose` with `placement.strategy: \"explicit\"`, an "
        "empty `connectivity[]` (routing is drawn above) and an empty "
        "`pins[]` -- every pin this cell promotes is now a net label from "
        "step 2, and the four trim-tap pin entries earlier records carried "
        "are gone (INTERNAL_NODE_LABEL_NOTE). `compose.request.json`."
    )
    a("4. `klt drc <composed> --deck sky130`.")
    a(
        "4b. `layout/bin/met2_drc.py <composed>` -- the escape plane's own "
        "DRC, because the curated deck step 4 runs is still missing the "
        "met2 min-area rule (`m2.6`; klayout-tools#513/#515 added the rest)."
    )
    a(f"5. `klt extract <composed> --deck sky130 --top {cell}`.")
    a(
        "6. `klt lvs` against the xschem-derived reference netlist (issue "
        "#8), twice -- with and without `options.combine_devices`."
    )
    a("7. `klt render` for the visual check below.")
    a("")
    a("## Device-half binding")
    a("")
    a(
        "A `klt gen diff_pair` reports its two transistors as two port "
        "families (`M1_*`/`M2_*`, or `Q1_*`/`Q2_*` when `mirror` is false). "
        "Which family is which schematic device is *this flow's* choice, not "
        "the generator's -- the halves are geometrically interchangeable. "
        "Until this increment that choice was never made: every net picked "
        "whichever candidate pad sat nearest its own centroid, independently. "
        "Two consequences were live in the previous record. `PN` took a "
        "finger of the same amp_pmirr half the `AOUT` label named, so MP3's "
        "drain and MP4's drain were the same physical transistor; and "
        "amp_nload's `D1` route and `D1_GATE` label disagreed about which "
        "half is MN1. Neither is visible to DRC or to the drawn-short check "
        "-- every terminal involved is legal, well-separated metal."
    )
    a("")
    a("| block | port family | schematic device | drain pad | source pad |")
    a("| --- | --- | --- | --- | --- |")
    for bid, entry in MOS_HALVES.items():
        for device, half in entry["devices"].items():
            a(
                f"| `{bid}` | `{half}_*` | `{device}` | "
                f"`{half}_*{entry['drain_suffix']}` | "
                f"`{half}_*{entry['source_suffix']}` |"
            )
    a("")
    a(
        "Every routed terminal and every gate pin label now resolves through "
        "that table (`mos_terminal()` / `bulk_terminal()`), so a node can "
        "only land on the transistor the schematic names."
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
    a("## Intra-block busses drawn on met1")
    a("")
    a(
        "Each matched group's units are tied into the node the schematic "
        "says they form, on met1 over mcon -- the sky130 extraction deck's "
        "own second conductor and via (`metals = (li1, met1, met2)`, "
        "`vias = (mcon, via)` since klayout-tools#511; met2 is reserved for "
        "the inter-block escape plane above and no intra-block bus uses "
        "it). This flow draws them itself from each block's "
        "reported `ports[]` (MET1_BUS_NOTE). That is what turns a "
        "100-segment coarse ladder (and its 40-segment fine trim ladder) "
        "into two real series resistors, an 8-unit PNP "
        "array into one real m=8 device, and -- new in this increment -- "
        "each split MOS group's 4 to 32 fingers into the single m=N "
        "transistor the schematic names."
    )
    a("")
    a("| block | bus | detail |")
    a("| --- | --- | --- |")
    for bid, entry in bus_summary.items():
        if bid.startswith("_"):
            continue
        if entry["kind"] == "res_series":
            a(
                f"| `{bid}` | {entry['legs']} interdigitated series "
                f"string(s) | {len(entry['links'])} unit-to-unit met1 links |"
            )
        elif entry["kind"] == "mos_comb":
            detail = "; ".join(
                f"`{r['net']}` = {r['pads']} finger pads"
                + (f" ({r['gate_contacts']} gate contacts)"
                   if r["gate_contacts"] else "")
                + f" joined on the {r['spine_side']} spine"
                for r in entry["nets"]
            )
            a(f"| `{bid}` | split-device finger bus | {detail} |")
        else:
            detail = "; ".join(
                f"`{r['net']}` = {r['pads']} pads on {r['columns']} columns"
                for r in entry["nets"]
            )
            a(f"| `{bid}` | parallel unit bus | {detail} |")
    a("")
    a(
        f"Drawn-short / spacing proof: every met1 rectangle carries the "
        f"electrical node it belongs to, and **{len(met1_conflicts)}** pairs "
        "of rectangles belonging to *different* nodes come within the deck's "
        "0.14 um `met1.space.1` clearance. The flow fails on any nonzero "
        "count -- a drawn short the DRC deck happens not to model would "
        "otherwise read as connectivity."
    )
    a("")
    a(
        "Split-node proof (the inverse check): every node's own met1 is "
        "counted into connected components, and **"
        f"{len(met1_split_routed)}** of the nodes this router reports as "
        "fully routed are drawn in more than one piece"
        + (
            " ("
            + ", ".join(
                f"`{net}` = {n} pieces"
                for net, n in sorted(met1_split_routed.items())
            )
            + ")"
            if met1_split_routed
            else ""
        )
        + ". The flow fails on any nonzero count. A node drawn as two islands "
        "that never touch is not a connected node, and unlike a drawn short "
        "*nothing downstream reports it*: DRC sees two legal wires, `klt "
        "extract` sees two anonymous nets with nothing in `warnings[]`, and "
        "the coverage table below scores this flow's own hop bookkeeping "
        "rather than the geometry, so it would still call the node drawn. "
        "Nodes that came up a hop short are excluded on purpose -- they are "
        "*supposed* to be in more than one piece, and the coverage table "
        "already says so. Their piece counts, and every other node's, are in "
        "`bus-summary.json`'s `_components`"
        + (
            ": "
            + ", ".join(
                f"`{net}` = {n}"
                for net, n in sorted(met1_components.items())
                if n != 1
            )
            if any(n != 1 for n in met1_components.values())
            else " (every node is a single piece)"
        )
        + "."
    )
    a("")
    a(
        "Label-collision proof: **"
        f"{len(merged_pin_names)}** extracted net(s) carry more than one "
        "label"
        + (f" ({', '.join('`' + n + '`' for n in merged_pin_names)})"
           if merged_pin_names else "")
        + ". This is the pad-side counterpart of the check above and is "
        "gated the same way. A `pins[]` entry labels a *port*, i.e. a pad, so "
        "a label placed on a pad another node's metal already contacts does "
        "not name its own node -- it renames that node, and `klt extract` "
        "emits the result as a single net called `A|B` with nothing in "
        "`warnings[]` and DRC still clean. The previous increment's composed "
        "layout shipped exactly that: `VOUT`'s label sat on "
        "`core_mirror.M2_1_D`, which is MPAMP's drain and the pad the drawn "
        "`TAIL` net contacts, so its extracted netlist contained a net named "
        "`TAIL|VOUT` -- the layout asserting that the reference output and "
        "the amp tail are one node. The pin selector and the router now "
        "share one claimed-pad set, and this line is the proof. Filed "
        "upstream as 2AMLogic/klayout-tools#470 (the silence, not the "
        "collision, is the tool gap)."
    )
    a("")
    a("## Inter-block nets drawn on met1")
    a("")
    a("| net | terminals | routed | plane | schematic node |")
    a("| --- | --- | --- | --- | --- |")
    for route in met1_routes:
        met2_hops = sum(1 for h in route.get("hops", []) if h.get("met2"))
        plane = "met1" if not met2_hops else f"met1 + met2 x{met2_hops}"
        a(
            f"| `{route['net']}` | "
            f"{' + '.join(f'`{t}`' for t in route['terminals'])} | "
            f"{'yes' if route['routed'] else 'NO'} | {plane} | "
            f"{route['schematic']} |"
        )
    a("")
    met2_hop_rows = [
        (route["net"], hop)
        for route in met1_routes
        for hop in route.get("hops", [])
        if hop.get("met2")
    ]
    a("### The met2 escape plane")
    a("")
    a(
        f"**{len(met2_hop_rows)}** of this cell's inter-block hops are drawn "
        "on met2 rather than met1, each entered and left through a via1 "
        "stack (met1 pad + `via.drawing` cut + met2 pad). met1 on this "
        "floorplan carries both every block's intra-block bus and every "
        "inter-block net, and the hops below had no met1 corridor at any "
        "lane, margin, block placement or search depth this repo can set -- "
        "layout/matching-plan.md Sections 7d-7o are the exhausted list. met2 "
        "is a genuinely independent conductor, and became one for sky130's "
        "curated deck only with 2AMLogic/klayout-tools#508 (merged via "
        "#511); before that its `metal2` role resolved to the same met1 "
        "layer this flow's own bussing already occupies. The escape is tried "
        "**strictly last**, after every met1 elbow, channel path and "
        "Z-detour has been drawn and rolled back, so met1 remains the "
        "primary plane -- see MET2_ESCAPE_NOTE."
    )
    a("")
    if met2_hop_rows:
        a("| net | hop | via1 drops (um) | met2 path |")
        a("| --- | --- | --- | --- |")
        for net, hop in met2_hop_rows:
            drops = " -> ".join(
                f"({d[0]}, {d[1]})" for d in hop.get("via1_drops", [])
            )
            a(
                f"| `{net}` | `{hop['from']}` -> `{hop['to']}` | {drops} | "
                f"{len(hop.get('points', []))}-point |"
            )
        a("")
    unchecked = drc.get("coverage", {}).get("layers_in_stream_without_rules", [])
    a(met2_drc_coverage_note(unchecked))
    a("")
    a("## Schematic inter-block nets: drawn vs. labelled only")
    a("")
    a(
        "The table above counts this flow's own routing declaration. This "
        "one counts what issue #62 actually asks for: every node of "
        "design/bandgap_core.sch (+ design/error_amp.sch) that joins devices "
        "in different blocks, and whether drawn metal joins **all** the "
        "blocks the schematic says it reaches. "
        "Every one of these nodes is *expressible*: MOS gates are contactable "
        "(MOS_GATE_NOTE), the resistor blocks carry the schematic's own "
        "flavour (RES_FLAVOR_NOTE), and -- new in this increment -- a hop "
        "that met1 has no corridor for can escape onto met2 "
        "(MET2_ESCAPE_NOTE). A row that is not `drawn` would therefore be "
        "this flow's own router failing on a floorplan that can express the "
        "node, not a capability being waited on."
    )
    a("")
    a("| schematic net | reaches (blocks) | joined by drawn metal | not drawn | status |")
    a("| --- | --- | --- | --- | --- |")
    for row in coverage:
        a(
            f"| `{row['net']}` | {', '.join(f'`{b}`' for b in row['blocks'])} | "
            f"{', '.join(f'`{b}`' for b in row['joined']) or '--'} | "
            f"{', '.join(f'`{b}`' for b in row['missing']) or '--'} | "
            f"**{row['status']}** |"
        )
    a("")
    a(
        f"**{len(fully_drawn)} of {len(coverage)} schematic inter-block nets "
        "are fully drawn.** Criterion 1 is scored PARTIAL, not MET, whenever "
        "that count is short"
        + (" -- it is not short here." if full_connectivity else ".")
        + " `VSS` reaches four blocks here, not the seven "
        "an earlier record listed: the three resistor blocks' `res_high_po` "
        "bulk terminals are on this node in the schematic and now resolve "
        "to the same real, drawn `VSS` net the rest of the row does "
        "(SUBSTRATE_NET_NOTE) -- but `res_array` draws no bulk-terminal pad "
        "inside those three blocks, so there is nothing for this router to "
        "target and counting them as routing targets would be scoring "
        "against an impossible bar rather than a missed one."
    )
    a("")
    a("## Promoted top-level pins")
    a("")
    a(
        f"`klt gen-compose` labelled {len(labelled_pins)}/"
        f"{len(inner_compose.get('pins', []))} requested `pins[]` ports; "
        f"`klt extract` promoted **{pin_count}** top-level pins "
        "(the #15 skeleton promoted `pin_count: 0`)."
    )
    a("")
    a("| net | port | labelled |")
    a("| --- | --- | --- |")
    for pin in inner_compose.get("pins", []):
        a(
            f"| `{pin['net']}` | {pin['block']}.{pin['port']} | "
            f"{'yes' if pin.get('labelled') else 'no'} |"
        )
    a("")
    a(
        "Four labels the previous records carried are **gone** from this "
        "list, and their absence is one of this increment's two substantive "
        "changes: `TRIM_A`, `TRIM_B`, `TRIM_A_CODE_0` and `TRIM_B_CODE_0`. "
        f"{INTERNAL_NODE_LABEL_NOTE}"
    )
    a("")
    a("### DR-002 trim-ladder taps (documented, not pinned)")
    a("")
    a(
        "Every code the drawn metal option can select, with the divider-leg "
        "length it yields. Each tap is located and validated against the "
        "block's own reported ports every run -- a count-constant change "
        "fails the flow loudly here rather than silently mislabelling a tap "
        "-- and the lengths below are computed from the tap index, not "
        "asserted, so the table *is* the demonstration that the ladder runs "
        "downward: code -k yields exactly `spec - k` um. Taps are reported "
        "into this record instead of into `pins[]` for the reason above."
    )
    a("")
    a(
        f"Codes outside DR-002's certified 0..-{N_R2_TRIM_CODES} range are "
        "drawn (the ladder is a metal option, so its physical taps exist "
        "whether or not a code is certified) and are marked "
        "**out-of-certified-range** below. "
        "`spec/decision-records/DR-002-trim-network-scoping.md` certifies the "
        "operating point over 0..-16 only; issue #46 and "
        "`sim/trim-range-monotonicity/` are the corner evidence for the "
        "boundary. Selecting one of the flagged taps is out of spec, not a "
        "wider trim range."
    )
    a("")
    a("| DR-002 code | leg A port | leg B port | leg length | certified |")
    a("| --- | --- | --- | --- | --- |")
    for tap in trim_taps:
        a(
            f"| `{tap['code']:d}` | {tap['block']}.{tap['ports']['A']} | "
            f"{tap['block']}.{tap['ports']['B']} | {tap['leg_um']:.0f} um | "
            f"{'yes' if tap['certified'] else '**no -- out of certified range**'} |"
        )
    a("")
    a("### Drawn vs. specified R2 leg length")
    a("")
    a(
        "The divider legs are the one place where the layout's own geometry "
        "constants can disagree with design/bandgap_core.sch's `CORE_PARAMS` "
        "without anything else in this flow noticing -- `klt lvs` can only "
        "report a resistor's *value*, and only once the two sides pair at "
        "all, which they did not until the nineteenth increment. This row "
        "states the comparison in the units the schematic itself specifies, "
        "unconditionally, from this flow's own constants. **It is a gated "
        "condition** (`r2_leg_length_matches`), not merely a reported one, "
        "since issue #91."
    )
    a("")
    a("| quantity | value |")
    a("| --- | --- |")
    a(
        f"| `res_r2` coarse leg (drawn) | {r2_length['coarse_um']:.0f} um "
        f"({N_R2_COARSE} x {R_LSEG_UM:.0f} um) |"
    )
    a(
        f"| `res_trim` fine leg at code 0 (drawn) | "
        f"{r2_length['trim_um']:.0f} um ({N_R2_TRIM_UNITS} x "
        f"{R_LSEG_TRIM_UM:.1f} um) |"
    )
    a(f"| **total drawn** | **{r2_length['drawn_um']:.0f} um** |")
    a(
        f"| schematic `L = r_lseg*n_r2 + r_lseg_trim*n_r2_trim` | "
        f"{r2_length['spec_um']:.0f} um |"
    )
    a(f"| delta | {r2_length['delta_um']:+.0f} um |")
    a(
        f"| effective DR-002 trim code | "
        f"**{r2_length['effective_trim_code']:+d}** |"
    )
    a("")
    if r2_length["matches"]:
        a(f"**How this came to be a gated row.** {RES_TRIM_LENGTH_NOTE}")
    else:
        a(
            "**REGRESSION.** The drawn leg no longer reproduces the "
            "schematic's specified length, and the flow's "
            "`r2_leg_length_matches` gate has failed on it. "
            f"{RES_TRIM_LENGTH_NOTE}"
        )
    a("")
    a("## Results")
    a("")
    a("| Stage | Status | Detail |")
    a("| --- | --- | --- |")
    a(
        f"| met1 routing | {'routed' if not unrouted else 'partial'} | "
        f"nets={len(met1_routes)}, unrouted={len(unrouted)}, "
        f"drawn-short conflicts={len(met1_conflicts)}, "
        f"split routed nodes={len(met1_split_routed)} |"
    )
    a(f"| DRC | {drc.get('status')} | violation_count={drc.get('violation_count')} |")
    a(
        f"| met2 DRC (this repo's own) | {met2_drc.get('status')} | "
        f"violation_count={met2_drc.get('violation_count')}, "
        f"via1 cuts={met2_drc.get('counts', {}).get('via1_cuts')}, "
        f"met2 polygons={met2_drc.get('counts', {}).get('met2_polygons')} |"
    )
    a(
        f"| extract | ok | device_count={extract.get('device_count')}, "
        f"device_counts={json.dumps(device_counts)}, pin_count={pin_count} |"
    )
    a(
        f"| LVS | {lvs.get('status')} | mismatch_count="
        f"{lvs.get('mismatch_count')} |"
    )
    if not drc_clean:
        a("")
        a("### DRC violations")
        a("")
        for v in drc.get("violations", [])[:50]:
            a(f"- {v}")
    a("")
    a("### Extracted device classes vs. the #15 skeleton")
    a("")
    a("| class | this record | #15 skeleton |")
    a("| --- | --- | --- |")
    a(f"| `pnp` | {device_counts.get('pnp', 0)} | 0 |")
    a(f"| `nfet` | {device_counts.get('nfet', 0)} | 0 |")
    a(f"| `pfet` | {device_counts.get('pfet', 0)} | 68 |")
    a(f"| `{RES_CLASS}` | {device_counts.get(RES_CLASS, 0)} | 67 (as `res_generic_po`) |")
    a(f"| promoted pins | {pin_count} | 0 |")
    a("")
    a("### LVS mismatch analysis")
    a("")
    a("| run | `combine_devices` | status | mismatches |")
    a("| --- | --- | --- | --- |")
    for label, response in (
        ("combined", lvs_combined),
        ("uncombined", lvs_plain),
    ):
        detail = response.get("error") or response.get("mismatch_count")
        a(
            f"| {label} | {response.get('combine_devices')} | "
            f"{response.get('status')} | {detail} |"
        )
    a("")
    if lvs_combined.get("status") == "error":
        a(
            "The combined run **aborted inside KLayout**: "
            f"`{lvs_combined.get('error')}`. `klt lvs` propagates that as an "
            "unhandled traceback rather than its documented error envelope, "
            "so the scoreboard above reads the uncombined run. Filed as "
            "friction; nothing about the layout changes either way."
        )
        a("")
    lvs_counts = lvs.get("counts", {})
    lvs_nets = lvs_counts.get("nets", {})
    lvs_devices = lvs_counts.get("devices", {})
    lvs_pins = lvs_counts.get("pins", {})
    a("| | layout | reference | matched |")
    a("| --- | --- | --- | --- |")
    for label, block in (
        ("nets", lvs_nets),
        ("devices", lvs_devices),
        ("pins", lvs_pins),
    ):
        a(
            f"| {label} | {block.get('layout')} | {block.get('reference')} | "
            f"{block.get('matched')} |"
        )
    a("")
    a(
        "Device counts here are **after** `klt lvs`'s "
        "`options.combine_devices` has folded both sides (this increment "
        "turns it on): the layout's series ladder segments and parallel "
        "array units collapse into the lumped devices the schematic states, "
        "which is only possible because the busses above are actually drawn. "
        f"`klt extract` saw {extract.get('device_count')} drawn devices; the "
        f"comparison sees {lvs_devices.get('layout')}."
    )
    a("")
    a(f"Mismatch categories: `{json.dumps(lvs.get('category_counts', {}))}`.")
    a("")
    a(
        "The residual gap has exactly **one** disclosed cause left, as of "
        "this (issue #108) increment, and it is neither a topology error "
        "in either netlist, a connectivity difference, nor a layout "
        "defect: the single deliberately-undrawn device. Seven causes "
        "tracked by prior records -- the deck-synthesized substrate net, "
        "undeclarable array dummies, the resistor device-class arity "
        "mismatch, unrouted schematic nodes, the R2 divider leg length, "
        "the PNP `ae`/`pe`/`ne` transcription gap, and (as of this "
        "increment) the `res_high_po` per-instance head-resistance value "
        "gap -- are **retired**; see \"Retired since the last increment\" "
        "below."
    )
    a("")
    a(
        "1. **`MMCC`, the amp's compensation cap, is in the reference but "
        "deliberately not drawn in this layout** (see the Blocks note "
        "above), so one reference device has no layout counterpart by "
        "construction. This is the *only* mismatch on either side."
    )
    a("")
    a(
        "Not worked around by editing either netlist to match the other. "
        "`reference.spice` states design/bandgap_core.sch; rewriting it to "
        "enumerate the layout's own shortfalls would make LVS compare the "
        "layout against itself, which is not evidence. `MMCC` is a "
        "deliberate scope choice (a single-ended compensation cap this "
        "layout does not draw), not a defect either side could fix."
    )
    a("")
    a("### Retired since the last increment")
    a("")
    a(
        "- **The R2 divider legs draw the length the schematic specifies.** "
        f"{RES_TRIM_LENGTH_NOTE}"
    )
    a(
        "- **Every schematic inter-block node is now joined across every "
        "block it reaches.** Through the seventeenth increment, "
        "`D1`/`GDRV`/`VSS` were split in the layout where the reference has "
        "one node, and PRs #75-#88 are an exhaustive negative-result "
        "sequence on every met1-side lever (search depth, channel-search "
        "window, row-0 margin, row-0 re-placement, a genuine 2D row split, "
        "and klayout-tools#454/#468's `metal2` role). The cause was never "
        "any of those: it was that sky130's curated deck had only one "
        "routing plane above the device pads, and this flow's own bussing "
        "already occupied it. Retired by 2AMLogic/klayout-tools#508 (merged "
        "via #511) plus the escape router built on it -- see \"The met2 "
        "escape plane\" above. `net.split` and `net.merged` are both **0** "
        "in the categories line above; they were 10 and 3."
    )
    a(
        "- **The trim ladder's nodes no longer split R2A/R2B into unpairable "
        f"pieces.** {INTERNAL_NODE_LABEL_NOTE}"
    )
    a(
        "- **The substrate net is now real, drawn connectivity, not a "
        f"declaration.** {SUBSTRATE_NET_NOTE} No `hints.same_nets` entry is "
        "sent (`SUBSTRATE_SAME_NETS` is empty); the correspondence this "
        "flow previously had to *state* is now something `klt lvs` "
        "*discovers* from the drawn geometry on its own."
    )
    a(f"- **Array dummies are now correctly excluded from the comparison.** {DUMMY_DEVICE_NOTE}")
    a(
        "- **The resistor device-class arity mismatch is fixed, not just "
        f"diagnosed.** {RES_BULK_ARITY_NOTE}"
    )
    a(
        "- **The PNP `ae`/`pe`/`ne` transcription gap is fixed.** "
        f"{PNP_EMITTER_GEOMETRY_NOTE}"
    )
    a(
        "- **`res_high_po`'s per-instance head-resistance value gap is "
        "closed** (issue #108). RES_HEAD_RESISTANCE_NOTE's finding still "
        "holds -- this flow's own multi-primitive R2A/R2B/R1 decomposition "
        "genuinely pays the fixed per-instance offset once per drawn "
        "primitive, not once per logical device -- but `reference.spice` "
        "previously stated design/bandgap_core.sch's single-device "
        "approximation (`380 + 325*L` once per leg), which is not what "
        "`klt lvs`'s own `combine_devices` sums the layout side to. This "
        "increment settles that transcription-convention question by "
        "stating the CHAINED value instead (RES_RESIZE_NOTE and "
        "reference.spice's own RESISTOR VALUE CONVENTION note), computed "
        "from the same real `sky130_fd_pr__res_high_po` model constants "
        "RES_HEAD_RESISTANCE_NOTE cites -- exactly reproducing what "
        "`combine_devices` sums the layout side to. Measured: `R1`/`R2A`/"
        "`R2B` all move from `device.property` mismatches to full matches, "
        "`mismatch_count` moving from 4 (pre-resize) to the 1 above."
    )
    a(
        "- **The R2 leg is drawn one coarse unit longer (issue #178).** "
        f"{RES_HEAD_SIZING_NOTE}"
    )
    a("")
    a("## Visual verification")
    a("")
    a("![routed overview](renders/overview.png)")
    a("")
    a("## What this record does NOT claim")
    a("")
    a(
        f"- **Not LVS-clean.** `klt lvs` reports `{lvs.get('status')}` with "
        f"`mismatch_count={lvs.get('mismatch_count')}` against the "
        "xschem-derived reference netlist, and `devices.matched` is "
        f"{lvs_devices.get('matched')}. The one cause above (`MMCC`, "
        "deliberately not drawn) is the whole of it. The count moved "
        "18 -> 4 when reference.spice's PNP cards gained emitter geometry "
        "(a transcription fix, not a drawn-shape change), held at 4 across "
        "issue #91's R2-leg-length fix and picking up klayout-tools#518/"
        "#519/#521/#526's `res_high_po` head-resistance correction (which "
        "made the disclosed `r` delta *larger*, not smaller, because this "
        "flow's own trim-tap decomposition charges the fixed per-instance "
        "offset once per drawn primitive rather than once per logical "
        "device -- see RES_HEAD_RESISTANCE_NOTE), and now moves 4 -> 1 "
        "with issue #108's resize propagation: reference.spice now states "
        "the CHAINED value for `R1`/`R2A`/`R2B` (RES_RESIZE_NOTE, "
        "reference.spice's own RESISTOR VALUE CONVENTION note) instead of "
        "the single-device approximation, which is what `combine_devices` "
        "actually sums the layout side to -- so the three `device.property` "
        "mismatches this cause carried are gone, not just smaller."
    )
    if full_connectivity:
        a(
            "- **Fully inter-block routed, but not on one plane.** All "
            f"{len(fully_drawn)}/{len(coverage)} schematic inter-block nets "
            "are joined across every block they reach -- and "
            f"{len(met2_hop_rows)} of the hops that get them there are drawn "
            "on met2, not met1. Most of that plane's geometry is now checked "
            "by `klt drc` itself (klayout-tools#513, merged via #515); this "
            "repo's own `layout/bin/met2_drc.py` covers the one rule that "
            "isn't (`m2.6`, met2 min area) against the installed PDK's "
            "source rules. The connectivity itself is the extractor's, "
            "since klayout-tools#511 made met2 a level of the curated "
            "extraction deck's own graph."
        )
    else:
        a(
            "- **Not fully inter-block routed either.** "
            f"{len(fully_drawn)}/{len(coverage)} schematic inter-block nets "
            "are joined across every block they reach. The rest are "
            "*partial*, not absent: each is drawn between the blocks the "
            "router could reach and stops where it could not, which the "
            "coverage table names per row."
        )
    a(
        "- **MOS finger bussing is drawn, and the m=N devices it produces "
        "are this record's own claim, not the tool's.** Each `bus_mos_comb` "
        "trunk is hand-placed geometry; what makes it evidence is that "
        "`klt extract` reads the drawn shapes back and `klt lvs`'s "
        "`combine_devices` folds the fingers into a single device with the "
        "schematic's own W -- see the device table in the extracted netlist, "
        "not this sentence."
    )
    a(
        "- **The PNP devices are drawn geometry recognised by the deck, not "
        "vendor `pnp_05v5` cell instances.** `klt gen bjt_array` draws a "
        "matching-faithful floorplan from base layers by design (its own "
        "generator note says so), and since upstream klayout-tools#440 it "
        "draws sky130's bipolar marker and per-unit well tap itself -- which "
        "makes the geometry *extract* as `pnp`, not a SPICE-model-exact "
        "device. PR #64's local recognition overlay is retired here."
    )
    a(
        "- **Array dummies are excluded, and the substrate correspondence "
        "is real drawn connectivity -- both new this increment.** The "
        f"`pnp` and `{RES_CLASS}` counts above already exclude each "
        f"array's dummy edge units ({extract.get('dummy_devices_dropped', 0)} "
        "dropped this run); see \"Retired since the last increment\" above "
        "for both."
    )
    a("")
    a("## Provenance")
    a("")
    a(f"- Record ID: `{args.record_id}`")
    a(f"- `klt` version: `{klt_version}` (pinned, see `layout/requirements.txt`)")
    a(
        "- KLayout engine version: "
        f"`{drc.get('provenance', {}).get('klayout_version')}`"
    )
    a(f"- Repo state: `{sha}` on `{branch}`" + (" (dirty)" if dirty else ""))
    a("")
    a("## Links")
    a("")
    a("- [`compose.request.json`](compose.request.json), [`compose.json`](compose.json)")
    a(
        "- [`drc.json`](drc.json), [`met2-drc.json`](met2-drc.json), "
        "[`extract.json`](extract.json), "
        "[`lvs.combined.json`](lvs.combined.json), [`lvs.json`](lvs.json)"
    )
    a("- [`bus-summary.json`](bus-summary.json)")
    a(f"- [`{cell}.extract.spice`]({cell}.extract.spice), [`reference.spice`](reference.spice)")
    a(f"- [`{cell}.gds`]({cell}.gds)")
    a("- [`render.json`](render.json), [`renders/overview.png`](renders/overview.png)")
    a("")

    text = "\n".join(lines)
    (out_dir / "record.md").write_text(text)
    return RecordResult(
        text=text,
        drc_clean=drc_clean,
        within_budget=within_budget,
        full_scale_ladder=full_scale_ladder,
        r2_leg_matches=r2_length["matches"],
        all_classes=all_classes,
        pin_count=pin_count,
    )

