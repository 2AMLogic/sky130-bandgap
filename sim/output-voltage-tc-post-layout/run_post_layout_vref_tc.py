#!/usr/bin/env python3
"""Post-layout (extracted-netlist) re-run of `sim/output-voltage-tc`'s output
voltage + box-method TC claim, against the routed, LVS-clean bandgap-core
layout (issue #62) instead of `design/bandgap_core.sch` (issue #16).

Schematic-level evidence assumes ideal parasitics; this record substantiates
the SAME claim -- README.md 'Target specification' rows 'Output reference'
and 'Temp coefficient' -- against a netlist genuinely derived from the routed
GDS: `klt extract --parasitics` (real per-net star RC parasitics from the
drawn routing) with its generic LVS device-class placeholders translated to
simulatable sky130 vendor models. See `sim/bin/post_layout_common.py`'s
module docstring for the full translation methodology, the two-PNP-unit-size
keying, the dropped resistor bulk terminal, and the ngspice BSIM-binning
unit-suffix quirk this discovered and works around.

Why a bespoke script, not a `corner-run.py` experiment.json entry (same
reasoning as `sim/trim-lsb-chained/run_trim_lsb_chained.py` and
`sim/res-array-resize/run_res_array_resize.py`): the DUT netlist body is not
something `corner-run.py`'s xschem-driven netlisting can produce on its own
-- it is `sim/output-voltage-tc/testbench/tb_vref_tc.sch`'s OWN netlisted
body with its `.subckt bandgap_core ... .ends` / `.subckt error_amp ...
.ends` blocks replaced by the translated, extracted layout. This script
reuses `corner-run.py`'s PDK resolution, corner matrix, per-corner ngspice
runner, spread checks and record rendering by import (same convention), so
this record is directly comparable to the schematic-level ones structurally
-- the entries differ only in provenance and in the DUT body.

Reusable pattern for the follow-on #16 increments (`psrr-dc`,
`line-regulation`, `quiescent-current`, `startup-time`, `startup-stability`,
`startup-ramp` all instantiate `design/bandgap_core.sym` the same way --
`grep -l design/bandgap_core.sym sim/*/testbench/*.sch`): swap
`WRAPPED_SCHEMATIC` and the manifest/slug below; everything else in this
file's `main()` is generic (see `sim/bin/post_layout_common.py`).

Usage
-----
    sim/output-voltage-tc-post-layout/run_post_layout_vref_tc.py
    sim/output-voltage-tc-post-layout/run_post_layout_vref_tc.py --dry-run

Exit status: 0 all checks passed, 2 a record was written but something
failed, 1 harness/setup error (no record written) -- same convention as
`corner-run.py`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO_ROOT = SIM_DIR.parent
LAYOUT_BANDGAP_CORE_DIR = REPO_ROOT / "layout" / "bandgap-core"

sys.path.insert(0, str(SIM_DIR / "bin"))
from sim_common import load_corner_run  # noqa: E402
import post_layout_common as plc  # noqa: E402

cr = load_corner_run()

SLUG = "output-voltage-tc-post-layout"
WRAPPED_EXPERIMENT = "output-voltage-tc"  # manifest (corners/measurements/deck) reused unchanged
WRAPPED_SCHEMATIC = "sim/output-voltage-tc/testbench/tb_vref_tc.sch"
SCHEMATIC_SUBCKTS_TO_REPLACE = ("bandgap_core", "error_amp")


def build_extracted_body(pdk, run_dir: Path, corners_dir: Path | None) -> tuple[list[str], dict]:
    """Netlist the (unmodified) schematic testbench, then swap its
    `bandgap_core`/`error_amp` subckt definitions for the translated,
    extracted, parasitics-included routed layout. Returns (body, provenance).
    """
    layout_record_id, layout_record_dir, gds = plc.resolve_latest_layout(LAYOUT_BANDGAP_CORE_DIR)

    pex_dir = HERE / "parasitics-snapshot" / layout_record_id
    if not pex_dir.exists():
        spice_path, pex_summary = plc.run_klt_extract_parasitics(gds, pex_dir)
    else:
        # Already extracted for this layout record in a prior run of this
        # script (append-only sim/ evidence -- don't re-extract/overwrite).
        spice_path = pex_dir / "bandgap_core_routed.pex.spice"
        pex_summary = json.loads((pex_dir / "bandgap_core_routed.pex.json").read_text())

    raw_text = spice_path.read_text()
    translated, counts = plc.translate_extracted_netlist(raw_text)

    expected = pex_summary.get("device_counts", {})
    expected_mos = expected.get("nfet", 0) + expected.get("pfet", 0)
    expected_pnp = expected.get("pnp", 0)
    expected_res = expected.get("res_high_po", 0)
    if (counts["mos"], counts["pnp"], counts["res"]) != (expected_mos, expected_pnp, expected_res):
        raise plc.PostLayoutError(
            "translation coverage mismatch against the extraction's own device_counts: "
            f"translated mos={counts['mos']} pnp={counts['pnp']} res={counts['res']}, "
            f"extraction reports nfet+pfet={expected_mos} pnp={expected_pnp} res_high_po={expected_res} "
            "-- a device class this translator doesn't recognize may have been silently skipped"
        )

    core_block = plc.extract_subckt_block(translated, "bandgap_core_routed")
    wrapper = plc.build_core_wrapper(core_subckt="bandgap_core_routed")

    testbench = REPO_ROOT / WRAPPED_SCHEMATIC
    netlist = cr.netlist_with_xschem(testbench, run_dir, pdk)
    tb_body_text = "\n".join(cr.netlist_body(netlist))
    tb_body_text = plc.strip_schematic_subckts(tb_body_text, SCHEMATIC_SUBCKTS_TO_REPLACE)

    full_text = tb_body_text + "\n\n" + wrapper + "\n" + core_block + "\n"
    body = full_text.splitlines()

    provenance = {
        "layout_record_id": layout_record_id,
        "layout_record": str((layout_record_dir / "record.md").relative_to(REPO_ROOT)),
        "layout_gds": str(gds.relative_to(REPO_ROOT)),
        "parasitics_snapshot": {
            "spice": str(spice_path.relative_to(REPO_ROOT)) if spice_path.is_relative_to(REPO_ROOT) else str(spice_path),
            "json": str((pex_dir / "bandgap_core_routed.pex.json").relative_to(REPO_ROOT)),
            "r_count": pex_summary.get("parasitics", {}).get("r_count"),
            "c_count": pex_summary.get("parasitics", {}).get("c_count"),
            "total_resistance_ohm": pex_summary.get("parasitics", {}).get("total_resistance_ohm"),
            "total_capacitance_ff": pex_summary.get("parasitics", {}).get("total_capacitance_ff"),
        },
        "device_translation_counts": counts,
        "lvs_mismatch_count_at_extraction": None,  # cross-referenced in the record body, not re-derived here
    }
    return body, provenance


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--supersedes", default="")
    p.add_argument("--author", default="")
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--allow-pdk-mismatch", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    pin = cr.load_pin()
    pdk = cr.resolve_pdk(pin)
    if not pdk.matches_pin and not args.allow_pdk_mismatch:
        raise cr.HarnessError(
            f"installed PDK {pdk.variant} is open_pdks {pdk.installed_commit}, but "
            f"sim/pdk.json pins {pin['open_pdks_commit']} (use --allow-pdk-mismatch to override)"
        )
    if not shutil.which("ngspice"):
        raise cr.HarnessError("ngspice not found on PATH")
    if not shutil.which("klt"):
        raise cr.HarnessError("klt (klayout-tools) not found on PATH")

    exp = cr.load_experiment(SIM_DIR / WRAPPED_EXPERIMENT)
    # exp.raw["claim"]'s trailing sentence describes the SCHEMATIC bench this
    # record wraps ("Measures design/bandgap_core.sch open-circuit...") --
    # accurate for the manifest's own schematic-level records, misleading for
    # this one. Keep the spec-line identification, replace the provenance tail.
    claim_head = exp.raw["claim"].split("Measures ")[0].rstrip()
    claim_text = (
        claim_head
        + " Measures the ROUTED, LVS-clean bandgap-core layout (issue #62) open-circuit, "
        "untrimmed, via klt extract --parasitics translated to a simulatable netlist "
        "(sim/bin/post_layout_common.py) -- NOT design/bandgap_core.sch directly; see "
        "'Netlist provenance' below."
    )

    class _Args:
        quick = False
        process = None
        temp = [27.0]  # dc temp swept INSIDE the deck -- same subset as the schematic bench
        supply = None

    matrix, is_subset = cr.build_matrix(exp, _Args(), pin)
    subset_reason = (
        "Reuses sim/output-voltage-tc's own subset: the box-method TC needs the "
        "-40..125 degC excursion swept continuously INSIDE the deck (dc temp), so "
        "the runner's outer temperature axis is collapsed to one point on purpose. "
        "Process and supply axes run in full (5 x 3 = 15 points)."
        if is_subset
        else ""
    )

    git_info = cr.git_state()
    now = datetime.now(timezone.utc)
    record_id = f"{now:%Y%m%d}-{now:%H%M%S}-{git_info['sha']}"

    records_dir = HERE / "records"
    snapshots_dir = HERE / "netlist-snapshots"
    corners_dir = HERE / "corners" / record_id
    record_md = records_dir / f"{record_id}.md"
    record_json = records_dir / f"{record_id}.json"
    snapshot = snapshots_dir / f"{record_id}.spice"
    for path in (record_md, record_json, snapshot, corners_dir):
        if path.exists():
            raise cr.HarnessError(f"{path} already exists — sim/ is append-only, refusing to overwrite")

    run_dir = SIM_DIR / "build" / SLUG / record_id
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SIM_DIR / "spiceinit", run_dir / ".spiceinit")

    body, layout_provenance = build_extracted_body(pdk, run_dir, corners_dir)

    print(f"experiment      : {SLUG}")
    print(f"record id       : {record_id}")
    print(f"layout record   : {layout_provenance['layout_record_id']}")
    print(f"corner points   : {len(matrix)}" + (" (SUBSET)" if is_subset else " (full matrix)"))

    if args.dry_run:
        print("\n-- corner list --")
        for corner in matrix:
            print(f"  {corner.id}")
        print(f"\n-- deck for {matrix[0].id} --")
        print(cr.build_deck(exp, pdk, matrix[0], body))
        print("\n(dry run: nothing written under sim/)")
        return 0

    results = []
    for i, corner in enumerate(matrix, start=1):
        log_path = corners_dir / f"{corner.id}.log"
        res = cr.run_corner(exp, pdk, corner, body, run_dir, log_path, args.timeout)
        results.append(res)
        summary = ", ".join(
            f"{c['name']}={'n/a' if c['value'] is None else format(c['value'], '.6g')}"
            for c in res["measurements"]
        )
        print(f"[{i:>3}/{len(matrix)}] {corner.id:<20} " f"{'PASS' if res['pass'] else 'FAIL'}  {summary}")

    spreads = cr.spread_checks(exp, results)
    overall = all(r["pass"] for r in results) and all(s["pass"] for s in spreads)

    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("\n".join(body) + "\n.end\n")

    record = {
        "record_id": record_id,
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "author": args.author or cr.default_author(),
        "supersedes": args.supersedes,
        "experiment": {
            "slug": SLUG,
            "title": exp.raw.get("title", exp.slug) + " -- POST-LAYOUT (extracted netlist)",
            "claim": claim_text,
            "provenance": "extracted",
            "provenance_source": (
                f"{layout_provenance['layout_gds']} via `klt extract --parasitics` "
                f"(layout record {layout_provenance['layout_record_id']}), translated by "
                "sim/bin/post_layout_common.py, wrapped over the unmodified "
                f"{WRAPPED_SCHEMATIC}"
            ),
            "statistical_convention": exp.raw.get("statistical_convention", "N/A"),
        },
        "layout_provenance": layout_provenance,
        "pdk": {
            "root": str(pdk.root),
            "variant": pdk.variant,
            "installed_commit": pdk.installed_commit,
            "pinned_commit": pin["open_pdks_commit"],
            "matches_pin": pdk.matches_pin,
            "lib_file": str(pdk.lib_file),
        },
        "tools": cr.tool_versions(),
        "git": git_info,
        "matrix": {
            "process": cr.unique_in_order(c.process for c in matrix),
            "temperature_c": sorted({c.temp_c for c in matrix}),
            "supply_v": sorted({c.supply_v for c in matrix}),
            "n_points": len(matrix),
            "is_subset": is_subset,
            "subset_reason": subset_reason,
            "points": [[c.process, c.temp_c, c.supply_v] for c in matrix],
            "point_ids": [c.id for c in matrix],
        },
        "corners": results,
        "spread_checks": spreads,
        "overall_pass": overall,
        "links": {
            "testbench": WRAPPED_SCHEMATIC,
            "manifest": str((SIM_DIR / WRAPPED_EXPERIMENT / "experiment.json").relative_to(REPO_ROOT)),
            "netlist_snapshot": str(snapshot.relative_to(REPO_ROOT)),
            "corners_dir": str(corners_dir.relative_to(REPO_ROOT)) + "/",
            "json": str(record_json.relative_to(REPO_ROOT)),
            "record": str(record_md.relative_to(REPO_ROOT)),
        },
    }

    records_dir.mkdir(parents=True, exist_ok=True)
    record_json.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    record_md.write_text(cr.render_record(record))

    print()
    print(f"record  : {record_md.relative_to(REPO_ROOT)}")
    print(f"json    : {record_json.relative_to(REPO_ROOT)}")
    print(f"logs    : {corners_dir.relative_to(REPO_ROOT)}/")
    print(f"overall : {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (cr.HarnessError, plc.PostLayoutError) as err:
        print(f"run_post_layout_vref_tc: error: {err}", file=sys.stderr)
        sys.exit(1)
