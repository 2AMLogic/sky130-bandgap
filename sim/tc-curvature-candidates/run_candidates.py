#!/usr/bin/env python3
"""Screen one TC variant with the pinned output-voltage-tc bench on batch.

Run each variant once. For survivors, repeat with --bench psrr-dc and
--bench startup-stability. --dry-run prepares requests without submitting.
Exit 0 means the selected bench passed, 2 a measured failure, 1 a run error.
"""

import argparse
import json
import math
import sys
from functools import partial
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM = HERE.parent
sys.path.insert(0, str(SIM / "bin"))

import batch_sim
import sim_common
from injector_common import new_record_id

cr = sim_common.load_corner_run()
SNAPSHOTS = {
    "output-voltage-tc": "20261112-072452-f9871d93",
    "psrr-dc": "20261112-073424-f9871d93",
    "startup-stability": "20261111-234331-ebc9a64b",
}
VARIANTS = ("unit-pair", "mixed-r1", "hot-pnp")
SMALL = "sky130_fd_pr__pnp_05v5_W0p68L0p68"
Q2 = (
    "XQ2 VSS VSS VBQ sky130_fd_pr__pnp_05v5_W3p40L3p40 m='n_pnp_ptat' mult='n_pnp_ptat'"
)
R1 = "XR1 R1_HD2 VB VSS sky130_fd_pr__res_high_po W='r_w' L='r_lseg*n_r1-n_r1_ov*r_ov_seg' mult=1 m=1"
IQ_RECORD = SIM / "quiescent-current/records/20261112-074405-f9871d93.json"
WAIT_S = 600
TIMEOUT_S = 150  # baseline worst engine times: 20.7 s TC, 26.8 s startup
submit = partial(batch_sim.run_klt, wait_for_capacity=WAIT_S)


def snapshot(bench):
    return SIM / bench / "netlist-snapshots" / (SNAPSHOTS[bench] + ".spice")


def variant_body(base, variant):
    """Edit only the exact device/parameter cards in the archived core."""
    if variant == "unit-pair":
        edits = {Q2: [f"XQ2 VSS VSS VBQ {SMALL} m=80 mult=80"]}
    elif variant == "mixed-r1":
        edits = {
            ".param n_r1=7": [".param n_r1=3"],
            R1: [
                R1.replace("R1_HD2 VB ", "R1_HD2 MIX "),
                "XTC_R1 MIX VB VSS sky130_fd_pr__res_xhigh_po W=1 L=3.77 mult=1 m=1",
            ],
        }
    elif variant == "hot-pnp":
        edits = {
            Q2: [
                Q2,
                *sim_common.chain_lines("TC_RE", "VOUT", "TC_E", [5] * 3, "VSS"),
                f"XTC_Q VSS VA TC_E {SMALL} m=1 mult=1",
            ]
        }
    else:
        raise ValueError(f"unknown variant {variant}")
    for card in edits:
        if base.count(card) != 1:
            raise ValueError(f"expected exactly one core card: {card}")
    return [line for original in base for line in edits.get(original, [original])]


def experiment(bench):
    exp = cr.load_experiment(SIM / bench)
    if bench == "output-voltage-tc":
        # The ratified upper limits are strict. The shared grader uses <=.
        upper = math.nextafter(50.0, -math.inf)
        next(m for m in exp.measurements if m.name == "tc_ppm").max = upper
        exp.raw["deck"]["analyses"].append("meas dc supply27 FIND i(v1) AT=27")
        exp.measurements += [
            cr.Measurement("iq_peak_ua", "-minimum(i(v1))*1e6", "uA", max=upper),
            cr.Measurement("iq_floor_ua", "-maximum(i(v1))*1e6", "uA", min=1),
            cr.Measurement("iq_cold_ua", "-i(v1)[0]*1e6", "uA"),
            cr.Measurement("iq_27_ua", "-supply27*1e6", "uA"),
            cr.Measurement("iq_hot_ua", "-i(v1)[15]*1e6", "uA"),
        ]
        matrix, _ = cr.build_matrix(exp, cr.parse_args([str(exp.dir)]), cr.load_pin())
    else:
        # One/two binding points cannot grade the stock full-matrix spreads.
        exp.raw["spread_checks"] = []
        if bench == "psrr-dc":
            matrix = [cr.Corner("sf", -40, 2.97)]  # lowest psrr_band_min
            for m in exp.measurements:
                if m.name in ("psrr_dc", "psrr_1k", "psrr_band_min"):
                    m.min = math.nextafter(60.0, math.inf)
        else:
            # Smallest traversal current and largest injector standing current.
            matrix = [cr.Corner("ss", 125, 2.97), cr.Corner("ff", 125, 3.63)]
    return exp, matrix


def requests(exp, matrix, body, path):
    return batch_sim.build_groups(
        exp,
        cr.load_pin(),
        matrix,
        body,
        cr.SPICEINIT_FILE.read_text(),
        path,
        TIMEOUT_S,
        capacity_wait_s=WAIT_S,
        runner_version_check="enforce",
        poll_interval_s=30,
        enforce_job_ceiling=True,
    )


def add_current_delta(results, baseline_ua):
    """Compare cold, room (interpolated), or hot supply current at the same PVT."""
    names = {-40: "iq_cold_ua", 27: "iq_27_ua", 125: "iq_hot_ua"}
    for row in results:
        name = names[row["temperature_c"]]
        current = next(m["value"] for m in row["measurements"] if m["name"] == name)
        stock = baseline_ua[row["corner_id"]]
        row["measurements"].append(
            {
                "name": "iq_delta_ua",
                "unit": "uA",
                "expr": f"{name} - {stock:g} uA (archived stock operating point)",
                "value": None if current is None else current - stock,
                "min": None,
                "max": None,
                "pass": current is not None,
                "reason": "" if current is not None else "missing candidate current",
            }
        )


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variant", choices=VARIANTS)
    parser.add_argument("--bench", choices=SNAPSHOTS, default="output-voltage-tc")
    parser.add_argument("--backend", choices=["batch"], default="batch")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    exp, matrix = experiment(args.bench)
    base = snapshot(args.bench)
    body = variant_body(cr.netlist_body(base), args.variant)
    stamp, git, now = new_record_id()
    record_id = f"{stamp}-{args.variant}-{args.bench}"
    work = (
        cr.BUILD_DIR / HERE.name / ("preview" if args.dry_run else "runs") / record_id
    )
    if args.dry_run:
        for group in requests(exp, matrix, body, work):
            print(f"{group.request_path} ({len(group.corners)} corners)")
        return 0

    pin = cr.load_pin()
    pdk = sim_common.check_pdk_and_ngspice(pin, False, require_ngspice=False)
    records, _, corners, md, js, net = sim_common.setup_record_paths(HERE, record_id)
    work.mkdir(parents=True, exist_ok=False)
    local_tools = cr.tool_versions() | {"klt": cr.first_line(["klt", "--version"])}

    def execute(points, logs):
        results, blockers, extra = batch_sim.execute(
            exp,
            pin,
            pdk,
            points,
            body,
            cr.SPICEINIT_FILE.read_text(),
            work,
            logs,
            cr.REPO_ROOT,
            TIMEOUT_S,
            cr.evaluate_measurements,
            local_tools,
            capacity_wait_s=WAIT_S,
            enforce_job_ceiling=True,
            runner=submit,
        )

        if args.bench == "output-voltage-tc":
            base_iq = json.loads(IQ_RECORD.read_text())
            baseline = {
                row["corner_id"]: m["value"] * 1e6
                for row in base_iq["corners"]
                for m in row["measurements"]
                if m["name"] == "iq" and m["pass"]
            }
            add_current_delta(results, baseline)
            extra["iq_baseline_record"] = str(IQ_RECORD.relative_to(cr.REPO_ROOT))
        return results, blockers, extra

    subset = args.bench != "output-voltage-tc"
    source = str(base.relative_to(cr.REPO_ROOT))
    _, passed = sim_common.run_matrix_and_write_record(
        cr,
        exp=exp,
        matrix=matrix,
        is_subset=subset,
        subset_reason="Binding baseline corners for the survivor regression."
        if subset
        else "",
        pdk=pdk,
        pin=pin,
        body=body,
        run_dir=work,
        corners_dir=corners,
        records_dir=records,
        record_md=md,
        record_json=js,
        snapshot=net,
        record_id=record_id,
        git_info=git,
        now=now,
        args=argparse.Namespace(author=None, supersedes=None, timeout=TIMEOUT_S),
        experiment_fields={
            "slug": HERE.name,
            "title": f"{args.variant} on {args.bench}",
            "claim": f"Candidate {args.variant} measured on the {args.bench} bench",
            "provenance": "schematic-level SPICE variant of the archived netlist",
            "provenance_source": source,
            "statistical_convention": exp.raw["statistical_convention"],
        },
        links={
            "testbench": source,
            "manifest": str((exp.dir / "experiment.json").relative_to(cr.REPO_ROOT)),
        },
        record_extra={"variant": args.variant, "bench": args.bench},
        execute_matrix=execute,
    )
    return 0 if passed else 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (cr.HarnessError, batch_sim.BatchError, ValueError) as err:
        sys.exit(f"TC screen: {err}")
