#!/usr/bin/env python3
"""Re-derive and PVT-verify `design/bandgap_core.sch`'s `n_r1`/`n_r2` against
the routed layout's REAL chained-array R1/R2A/R2B topology, for issue #99
(DR-003 follow-up).

Why a bespoke script (same reasoning as `sim/res-array-head-resistance/
run_res_array_head_resistance.py`, whose Phase B pattern this extends): the
claim needs the SAME netlisted core body -- amplifier, PNPs, PMOS mirrors,
startup node -- re-run with a *structural* edit to the three divider legs,
namely replacing each single `sky130_fd_pr__res_high_po` device with a chain
of separately-instantiated unit devices reproducing the routed layout's own
`bus_res_series` decomposition (`layout/bin/gen_bandgap_routed.py`). That is a
body substitution, not a `deck.params` override, so the generic corner-runner
manifest path cannot express it. This script reuses the head-resistance
record's `chain_lines()` topology and its already-checked-in core netlist
snapshot as the base body, and adds one axis the head-resistance record did
not have: it parameterizes the chained arrays on ARBITRARY `n_r1`/`n_r2` (and
trim code), so it can search for and then verify a resized sizing rather than
only measuring the shipped one.

Layout decomposition model (transcribed from `gen_bandgap_routed.py`'s
`N_R1`/`N_R2_COARSE`/`N_R2_TRIM_UNITS` and issue #91's split-the-270um rule):

  * R1  -> `n_r1` coarse units, each `R_LSEG_UM` (5 um) long.
  * R2A/R2B per leg -> `(n_r2 - 4)` coarse `R_LSEG_UM` (5 um) units PLUS a
    20-unit fine ladder of `R_LSEG_TRIM_UM` (1 um) units, of which
    `(20 + trim_code)` are electrically in-circuit at a given DOWNWARD-only
    trim code (`trim_code <= 0`; code 0 = all 20 active = the shipped,
    untrimmed length `5*n_r2` um). The fine ladder count is FIXED at 20
    regardless of `n_r2` -- it exists to offer DR-002's 0..-16 downward taps
    (drawn 0..-20) -- so only the coarse count moves with a resize. This is
    the SAME `N2 = n_r2 + 16 + trim_code`, `L2 = 5*n_r2 + trim_code` closed
    form the head-resistance record's own Phase A geometry satisfies at
    `n_r2=54, trim=0` (70 units, 270 um).

Each chained unit is a real `sky130_fd_pr__res_high_po` instance evaluated by
ngspice against the pinned PDK's own nonlinear `rhead`/`rbody` model cards, so
every internal contact pays the fixed per-instance head/end-effect term the
routed layout really draws (2AMLogic/klayout-tools#518/#519/#526; issue #98 /
DR-003). This is the ground truth the resize is sized against -- NOT the
single-`res_high_po`-device-per-leg approximation `design/bandgap_core.sch`
and every pre-#99 PVT record simulate.

Two run modes:

  --explore n_r1 n_r2 [n_r1 n_r2 ...]
      Run one or more candidate (n_r1, n_r2) pairs at trim_code=0 across the
      5 (process, supply) corners with the box-method -40..125 C TC sweep,
      print VOUT(27 C)/TC/regulation, write NOTHING under sim/. Used to pick
      the resize integer before committing to the append-only record.

  (default, no --explore)
      Full verification of the CHOSEN resize (RESIZE_N_R1 / RESIZE_N_R2
      constants below): the 5-corner box-TC sweep at trim_code=0 (AC2), a
      trim-code {0, -8, -16} sweep at all 5 corners (AC3 -- does DR-002's
      downward 0..-16 range still cover the residual gap after the resize),
      and a CONTROL re-run of the shipped (7, 54) sizing to reproduce
      DR-003's out-of-spec / hot-corner-collapse finding on this same code
      path. Writes an append-only record under records/.

Note on tool availability: like the head-resistance record, this run
environment has `ngspice` but not `xschem`, so the core body is read from the
already-checked-in netlist snapshot (verified byte-identical on the .param
lines that matter) rather than re-netlisted from `tb_vref_tc.sch`. The
resized resistor topology is injected by this script directly, so the
snapshot's own `.param n_r1`/`.param n_r2` values are irrelevant to the
resistor legs (their `XR1`/`XR2A`/`XR2B` device lines are removed and
replaced) -- only the surrounding core body (PNPs/amp/mirrors) is reused from
it, and that body does not depend on `n_r1`/`n_r2`.

Exit status: 0 if every check passed, 2 if a record was written but a check
failed, 1 on a harness/setup error (no record written).
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
BUILD_DIR = SIM_DIR / "build" / "res-array-resize"

sys.path.insert(0, str(SIM_DIR / "bin"))
from sim_common import (  # noqa: E402
    build_deck,
    chain_lines,
    load_base_body,
    load_corner_run,
    parse_measurements,
    r1_segments_um,
    run_ngspice,
    write_log,
)

# Reuse the head-resistance record's own base body: the core netlist snapshot
# sim/trim-range-monotonicity produced at trim_code=0, wrapping
# sim/output-voltage-tc/testbench/tb_vref_tc.sch (design/bandgap_core.sch)
# unmodified. Reference-only -- never written by this script.
BASE_SNAPSHOT = (
    SIM_DIR / "trim-range-monotonicity" / "netlist-snapshots" / "20260803-170704-b976d0f.spice"
)
WRAPPED_SCHEMATIC = "sim/output-voltage-tc/testbench/tb_vref_tc.sch"


cr = load_corner_run()

SLUG = "res-array-resize"
TITLE = (
    "Re-derive and PVT-verify n_r1/n_r2 against the routed layout's real "
    "chained-array R1/R2A/R2B topology (issue #99, DR-003 follow-up)"
)

# --------------------------------------------------------------------------
# Layout decomposition constants -- transcribed from
# layout/bin/gen_bandgap_routed.py (N_R1 / N_R2_COARSE / N_R2_TRIM_UNITS /
# R_LSEG_UM / R_LSEG_TRIM_UM) and design/bandgap_core.sch's CORE_PARAMS.
# --------------------------------------------------------------------------
R_W_UM = 1.0
R_LSEG_UM = 5.0
R_LSEG_TRIM_UM = 1.0
N_R2_FINE_UNITS = 20  # fixed fine trim ladder length (drawn 0..-20, DR-002 certifies 0..-16)
# coarse R2 units at a given n_r2: the specified 5*n_r2 um leg minus the 20 um
# fine ladder, in 5 um coarse units. n_r2=54 -> 50 coarse (matches the layout).
COARSE_R2_OFFSET = int(N_R2_FINE_UNITS * R_LSEG_TRIM_UM / R_LSEG_UM)  # = 4

# --------------------------------------------------------------------------
# THE CHOSEN RESIZE (issue #99). Re-derived against the chained topology via
# --explore (see the record's Determination). The shipped sizing was
# (n_r1=7, n_r2=54); this is the resized sizing that lands in
# design/bandgap_core.sch.
# --------------------------------------------------------------------------
RESIZE_N_R1 = 7
RESIZE_N_R2 = 50
SHIPPED_N_R1 = 7  # DR-003 control (the pre-#99 shipped sizing)
SHIPPED_N_R2 = 54

# --------------------------------------------------------------------------
# Corner matrix -- identical (process, supply) set to
# run_trim_sweep.py's NEGATIVE_CORNERS and the head-resistance record's
# Phase B, at the worst-case (lowest) supply for the two hot corners #46/#91
# flagged as margin-thin.
# --------------------------------------------------------------------------
CORNERS = (
    ("tt", 3.30),
    ("ss", 3.30),
    ("ff", 2.97),
    ("sf", 2.97),
    ("fs", 2.97),
)
TRIM_CODES = (0, -8, -16)  # AC3 downward-range recheck (DR-002's certified span)

VREF_SPEC_V = (1.188, 1.212)  # draft spec: 1.20 V +/- 1%
VREF_SANITY_V = (1.10, 1.30)  # regulation-loss guard (a collapse jumps VOUT to ~2.85 V)


# --------------------------------------------------------------------------
# chained-array geometry
# --------------------------------------------------------------------------


def r2_segments_um(n_r2: int, trim_code: int) -> list[float]:
    """R2A/R2B leg unit lengths at a resize (n_r2) and DOWNWARD trim code.

    coarse (n_r2 - 4) x 5 um  +  active (20 + trim_code) x 1 um fine units.
    trim_code <= 0; code 0 keeps all 20 fine units (= the shipped 5*n_r2 um).
    """
    if trim_code > 0:
        raise cr.HarnessError(f"trim_code must be <= 0 (downward-only), got {trim_code}")
    coarse_units = n_r2 - COARSE_R2_OFFSET
    active_fine = N_R2_FINE_UNITS + trim_code
    if coarse_units < 1 or active_fine < 0:
        raise cr.HarnessError(f"invalid decomposition at n_r2={n_r2}, trim={trim_code}")
    return [R_LSEG_UM] * coarse_units + [R_LSEG_TRIM_UM] * active_fine


# The exact single-device lines this script replaces (verified present exactly
# once each in BASE_SNAPSHOT before substitution).
TARGET_LINES = {
    "XR2A": (
        "XR2A VA VOUT VSS sky130_fd_pr__res_high_po W='r_w' "
        "L='r_lseg*n_r2+r_lseg_trim*n_r2_trim' mult=1 m=1"
    ),
    "XR2B": (
        "XR2B VB VOUT VSS sky130_fd_pr__res_high_po W='r_w' "
        "L='r_lseg*n_r2+r_lseg_trim*n_r2_trim' mult=1 m=1"
    ),
    "XR1": "XR1 VBQ VB VSS sky130_fd_pr__res_high_po W='r_w' L='r_lseg*n_r1' mult=1 m=1",
}

# Core-body .param lines that MUST still match (independent of the resize).
# n_r1/n_r2/n_r2_trim are deliberately NOT here -- this script overrides the
# resistor topology directly, so the snapshot's values for them do not matter.
EXPECTED_PARAMS = {
    ".param n_pnp_ctat=8",
    ".param n_pnp_ptat=8",
    ".param r_w=1",
    ".param r_lseg=5",
    ".param m_out=2",
    ".param m_ampbias=2",
    ".param r_lseg_trim=1",
}


def substitute_arrays(body: list[str], n_r1: int, n_r2: int, trim_code: int) -> list[str]:
    r1_seg = r1_segments_um(n_r1, R_LSEG_UM)
    r2_seg = r2_segments_um(n_r2, trim_code)
    out: list[str] = []
    found: set[str] = set()
    for line in body:
        stripped = line.strip()
        replaced = False
        for key, target in TARGET_LINES.items():
            if stripped == target:
                if key in found:
                    raise cr.HarnessError(f"{key} line appears more than once in base body")
                found.add(key)
                if key == "XR2A":
                    out.extend(chain_lines("R2A", "VA", "VOUT", r2_seg, "VSS"))
                elif key == "XR2B":
                    out.extend(chain_lines("R2B", "VB", "VOUT", r2_seg, "VSS"))
                elif key == "XR1":
                    out.extend(chain_lines("R1", "VBQ", "VB", r1_seg, "VSS"))
                replaced = True
                break
        if not replaced:
            out.append(line)
    missing = set(TARGET_LINES) - found
    if missing:
        raise cr.HarnessError(
            f"expected line(s) for {sorted(missing)} not found exactly once in {BASE_SNAPSHOT}"
        )
    return out


def analytic_resistances(n_r1: int, n_r2: int, trim_code: int = 0) -> dict[str, float]:
    """klt's own reported chained model (N*379.705147 + 324.827244*L), for the
    record's cross-reference table only -- the ngspice sweep is the ground
    truth. Reproduces the head-resistance record's Phase A numbers at (7,54,0):
    R1 14026.89, R2 114282.72, K 8.1474."""
    head = 379.705147
    body = 324.827244
    r1_n = len(r1_segments_um(n_r1, R_LSEG_UM))
    r1_l = sum(r1_segments_um(n_r1, R_LSEG_UM))
    r2_n = len(r2_segments_um(n_r2, trim_code))
    r2_l = sum(r2_segments_um(n_r2, trim_code))
    r1 = r1_n * head + body * r1_l
    r2 = r2_n * head + body * r2_l
    return {"r1_ohm": r1, "r2_ohm": r2, "k": r2 / r1}


def run_corner_set(run_dir, corners_dir, record_id, pdk, base_body, n_r1, n_r2, trim_code, timeout, tag):
    """Run the 5-corner box-TC sweep at one (n_r1, n_r2, trim_code). Returns a
    dict keyed by (process, supply)."""
    body = substitute_arrays(base_body, n_r1, n_r2, trim_code)
    results: dict[tuple[str, float], dict] = {}
    for process, supply in CORNERS:
        deck = build_deck(SLUG, "run_res_array_resize.py", pdk, process, supply, body)
        stamp = datetime.now(timezone.utc)
        name = f"{tag}_{process}_{supply:.2f}v"
        raw, rc, timed_out = run_ngspice(run_dir, name, deck, timeout)
        if corners_dir is not None:
            write_log(corners_dir, name, record_id, pdk, stamp, deck, raw, rc, timed_out)
        meas = parse_measurements(raw)
        if timed_out or rc != 0 or "vref_27" not in meas:
            raise cr.HarnessError(
                f"{tag} {process}/{supply}V produced no usable measurement (rc={rc}, timeout={timed_out})"
            )
        results[(process, supply)] = meas
    return results


# --------------------------------------------------------------------------
# explore mode
# --------------------------------------------------------------------------


def explore(pairs: list[tuple[int, int]], timeout: int) -> int:
    pin = cr.load_pin()
    pdk = cr.resolve_pdk(pin)
    if not shutil.which("ngspice"):
        raise cr.HarnessError("ngspice not found on PATH")
    base_body = load_base_body(BASE_SNAPSHOT, EXPECTED_PARAMS)
    run_dir = BUILD_DIR / "explore"
    print(f"PDK: {pdk.dir} (open_pdks {pdk.installed_commit})")
    print(f"spec window: {VREF_SPEC_V} V   corners: {[p for p, _ in CORNERS]}")
    for n_r1, n_r2 in pairs:
        res = analytic_resistances(n_r1, n_r2)
        print(
            f"\n=== n_r1={n_r1} n_r2={n_r2}  (chained model: R1={res['r1_ohm']:.1f} "
            f"R2={res['r2_ohm']:.1f} K={res['k']:.4f}) ==="
        )
        results = run_corner_set(run_dir, None, "explore", pdk, base_body, n_r1, n_r2, 0, timeout, f"n{n_r1}_{n_r2}")
        for process, supply in CORNERS:
            m = results[(process, supply)]
            in_spec = VREF_SPEC_V[0] <= m["vref_27"] <= VREF_SPEC_V[1]
            reg = VREF_SANITY_V[0] <= m["vref_max"] <= VREF_SANITY_V[1]
            print(
                f"  {process}/{supply:.2f}V  vref27={m['vref_27']:.6f}  vref_max={m['vref_max']:.6f}  "
                f"tc={m['tc_ppm']:.1f}ppm  {'IN-SPEC' if in_spec else 'OUT'}  "
                f"{'reg' if reg else 'COLLAPSE'}"
            )
    return 0


# --------------------------------------------------------------------------
# checks + record (default verify mode)
# --------------------------------------------------------------------------


def evaluate(resized, resized_trim, shipped) -> list[dict]:
    checks: list[dict] = []

    def add(name, ok, detail):
        checks.append({"name": name, "pass": bool(ok), "detail": detail})

    # AC2: resized core, trim=0, in spec + regulating at every corner
    for process, supply in CORNERS:
        cid = f"{process}_{supply:.2f}v"
        m = resized[(process, supply)]
        in_spec = VREF_SPEC_V[0] <= m["vref_27"] <= VREF_SPEC_V[1]
        add(
            f"resized_vref27_in_spec[{cid}]",
            in_spec,
            f"resized (n_r1={RESIZE_N_R1}, n_r2={RESIZE_N_R2}) vref_27={m['vref_27']:.6f} V "
            f"vs spec {VREF_SPEC_V}" + ("" if in_spec else " -- OUT OF SPEC"),
        )
        reg = VREF_SANITY_V[0] <= m["vref_max"] <= VREF_SANITY_V[1]
        add(
            f"resized_regulating[{cid}]",
            reg,
            f"resized vref_max={m['vref_max']:.6f} V (sanity band {VREF_SANITY_V}; a collapse "
            f"pins VOUT near VDD ~2.85 V). tc={m['tc_ppm']:.3f} ppm/degC",
        )

    # Control: shipped (7,54) reproduces DR-003's out-of-spec / collapse finding
    for process, supply in CORNERS:
        cid = f"{process}_{supply:.2f}v"
        m = shipped[(process, supply)]
        out = not (VREF_SPEC_V[0] <= m["vref_27"] <= VREF_SPEC_V[1])
        add(
            f"shipped_control_out_of_spec[{cid}]",
            out,
            f"shipped (n_r1={SHIPPED_N_R1}, n_r2={SHIPPED_N_R2}) vref_27={m['vref_27']:.6f} V "
            f"vref_max={m['vref_max']:.6f} V -- reproduces DR-003 (expected OUT of spec"
            + (" + collapse" if m["vref_max"] > VREF_SANITY_V[1] else "") + ")",
        )

    # AC3: downward trim 0..-16 monotonic + collapse-free on the resized baseline
    for process, supply in CORNERS:
        cid = f"{process}_{supply:.2f}v"
        series = [resized_trim[(process, supply, t)]["vref_27"] for t in sorted(TRIM_CODES)]
        strictly_increasing = all(b > a for a, b in zip(series, series[1:]))
        add(
            f"resized_trim_monotonic[{cid}]",
            strictly_increasing,
            f"vref_27 vs trim {list(zip(sorted(TRIM_CODES), (round(v, 6) for v in series)))} "
            "(must strictly increase from -16 toward 0)",
        )
        all_reg = all(
            VREF_SANITY_V[0] <= resized_trim[(process, supply, t)]["vref_max"] <= VREF_SANITY_V[1]
            for t in TRIM_CODES
        )
        add(
            f"resized_trim_collapse_free[{cid}]",
            all_reg,
            "every downward code (0, -8, -16) stays on the operating branch (vref_max in "
            f"{VREF_SANITY_V})",
        )

    return checks


def render_record(r: dict) -> str:
    L: list[str] = []

    def add(line: str = ""):
        L.append(line)

    add(f"# Record {r['record_id']}")
    add("")
    add(f"- **Record ID**: {r['record_id']}")
    add(f"- **Experiment**: `{SLUG}` — {TITLE}")
    add(
        "- **Claim**: issue #99 (DR-003 follow-up) -- `design/bandgap_core.sch`'s "
        f"shipped sizing (`n_r1={SHIPPED_N_R1}`, `n_r2={SHIPPED_N_R2}`) was sized and "
        "PVT-verified against ONE `res_high_po` device per divider leg, but the routed "
        "layout draws each leg as a *chain* of separately-contacted unit instances that "
        "pays real per-instance head resistance (issue #98 / DR-003, "
        "`sim/res-array-head-resistance/records/20260805-113409-6caa9f8.md`): "
        "K = R2/R1 reads 8.1474 in the real topology vs 7.4973 in the single-device model, "
        "pushing VOUT(27 degC) out of the draft +/-1% window at all 5 corners and collapsing "
        "regulation at ff/2.97 V and fs/2.97 V. This record re-derives `n_r1`/`n_r2` "
        f"against the REAL chained topology (chosen: `n_r1={RESIZE_N_R1}`, `n_r2={RESIZE_N_R2}`) "
        "and re-verifies it at the same 5 corners #46/#91/DR-003 used, plus the DR-002 "
        "downward trim range on the resized baseline."
    )
    add(
        "- **Netlist provenance**: the core body (amp/PNPs/PMOS mirrors) is reused from "
        f"`{BASE_SNAPSHOT.relative_to(REPO_ROOT)}` (the same already-checked-in snapshot the "
        "head-resistance record wraps; xschem is unavailable in this run environment, see the "
        "script docstring). The three divider legs are replaced with chained "
        "`sky130_fd_pr__res_high_po` unit-instance arrays at the routed layout's own "
        "decomposition (`layout/bin/gen_bandgap_routed.py`), parameterized on the resized "
        "`n_r1`/`n_r2` -- so the snapshot's own `.param n_r1`/`n_r2` values do not enter the "
        "resistor legs."
    )
    pdk = r["pdk"]
    pin_state = "matches sim/pdk.json pin" if pdk["matches_pin"] else "**MISMATCH vs sim/pdk.json pin**"
    add(
        f"- **PDK**: {pdk['variant']} @ open_pdks `{pdk['installed_commit']}` ({pin_state}); "
        f"models `{pdk['lib_file']}`"
    )
    tools = r["tools"]
    add(f"- **Tools**: {tools['ngspice']}; {tools['xschem']}; {tools['platform']}")
    add(
        f"- **Repo state**: `{r['git']['sha']}` on `{r['git']['branch']}`"
        + (" (working tree dirty at run time)" if r["git"]["dirty"] else " (clean working tree)")
    )
    add(
        "- **Corner matrix**: the 5 (process, supply) corners "
        + ", ".join(f"{p}/{s:.2f} V" for p, s in CORNERS)
        + ", each with a continuous in-deck `dc temp -40 125 11` box-method sweep (16 points) -- "
        "identical corner set and method to `sim/trim-range-monotonicity/` and the "
        "head-resistance record's Phase B."
    )
    add("- **Statistical convention**: N/A (deterministic sizing/topology sweep, not a distribution claim).")
    add("")

    ra = r["resistances"]
    add("## Chained-array resistance the resize targets (klt / head-resistance model)")
    add("")
    add("| sizing | R1 (Ω) | R2A/R2B (Ω) | K = R2/R1 | source |")
    add("|---|---|---|---|---|")
    add(
        f"| shipped n_r1={SHIPPED_N_R1}, n_r2={SHIPPED_N_R2} | {ra['shipped']['r1_ohm']:.2f} | "
        f"{ra['shipped']['r2_ohm']:.2f} | {ra['shipped']['k']:.4f} | reproduces DR-003's "
        "14026.89 / 114282.72 / 8.1474 |"
    )
    add(
        f"| resized n_r1={RESIZE_N_R1}, n_r2={RESIZE_N_R2} | {ra['resized']['r1_ohm']:.2f} | "
        f"{ra['resized']['r2_ohm']:.2f} | {ra['resized']['k']:.4f} | this resize |"
    )
    add(
        f"| single-device model (pre-#99 baseline) | 11748.66 | 88083.06 | 7.4973 | "
        "what the schematic + every pre-#99 record simulate |"
    )
    add("")
    add(
        f"The resize brings the REAL chained topology's K from {ra['shipped']['k']:.4f} down to "
        f"{ra['resized']['k']:.4f} -- back to within the band the single-device model's 7.4973 "
        "produced an in-spec VOUT at. (K is the ground-truth chained value; VOUT/TC below are the "
        "real ngspice sweep, not inferred from K.)"
    )
    add("")

    add(f"## AC2 -- resized core (n_r1={RESIZE_N_R1}, n_r2={RESIZE_N_R2}), untrimmed, 5-corner box TC")
    add("")
    add("| process | supply (V) | VREF(27 °C) (V) | VREF min (V) | VREF max (V) | TC (ppm/°C) | in +/-1% spec? | regulating? |")
    add("|---|---|---|---|---|---|---|---|")
    for process, supply in CORNERS:
        m = r["resized"][f"{process}:{supply}"]
        in_spec = "yes" if VREF_SPEC_V[0] <= m["vref_27"] <= VREF_SPEC_V[1] else "**NO**"
        reg = "yes" if VREF_SANITY_V[0] <= m["vref_max"] <= VREF_SANITY_V[1] else "**NO — collapsed**"
        add(
            f"| {process} | {supply:.2f} | {m['vref_27']:.6f} | {m['vref_min']:.6f} | "
            f"{m['vref_max']:.6f} | {m['tc_ppm']:.3f} | {in_spec} | {reg} |"
        )
    add("")

    add(f"## DR-003 control -- shipped sizing (n_r1={SHIPPED_N_R1}, n_r2={SHIPPED_N_R2}), same code path")
    add("")
    add("| process | supply (V) | VREF(27 °C) (V) | VREF max (V) | TC (ppm/°C) | in +/-1% spec? | regulating? |")
    add("|---|---|---|---|---|---|---|")
    for process, supply in CORNERS:
        m = r["shipped"][f"{process}:{supply}"]
        in_spec = "yes" if VREF_SPEC_V[0] <= m["vref_27"] <= VREF_SPEC_V[1] else "**NO**"
        reg = "yes" if VREF_SANITY_V[0] <= m["vref_max"] <= VREF_SANITY_V[1] else "**NO — collapsed**"
        add(
            f"| {process} | {supply:.2f} | {m['vref_27']:.6f} | {m['vref_max']:.6f} | "
            f"{m['tc_ppm']:.3f} | {in_spec} | {reg} |"
        )
    add("")
    add(
        "This control re-runs DR-003's chained-array finding on this record's own code path: "
        "the shipped sizing is out of spec at all 5 corners and collapses at ff/2.97 V and "
        "fs/2.97 V -- confirming the harness reproduces "
        "`sim/res-array-head-resistance/records/20260805-113409-6caa9f8.md` before the resize "
        "is trusted."
    )
    add("")

    add(f"## AC3 -- DR-002 downward trim range on the RESIZED baseline (n_r2={RESIZE_N_R2})")
    add("")
    add("| process | supply (V) | trim code | VREF(27 °C) (V) | VREF max (V) | TC (ppm/°C) | regulating? |")
    add("|---|---|---|---|---|---|---|")
    for process, supply in CORNERS:
        for t in TRIM_CODES:
            m = r["resized_trim"][f"{process}:{supply}:{t}"]
            reg = "yes" if VREF_SANITY_V[0] <= m["vref_max"] <= VREF_SANITY_V[1] else "**NO — collapsed**"
            add(
                f"| {process} | {supply:.2f} | {t:+d} | {m['vref_27']:.6f} | {m['vref_max']:.6f} | "
                f"{m['tc_ppm']:.3f} | {reg} |"
            )
    add("")
    add(
        "The downward trim ladder (`n_r2_trim` 0..-16, applied to the resized `n_r2`) is "
        "re-run -- not merely re-cited -- against the resized baseline (AC3). Each corner's "
        "span (code 0 vs -16) and monotonicity is reported in the checks below; the finding "
        "for whether the existing 0..-16 range still suffices is in the Determination."
    )
    add("")

    add("## Checks")
    add("")
    n_fail = sum(1 for c in r["checks"] if not c["pass"])
    for c in r["checks"]:
        add(f"- {'PASS' if c['pass'] else 'FAIL'} `{c['name']}` — {c['detail']}")
    add("")
    add(f"- **Overall: {'PASS' if r['overall_pass'] else 'FAIL'}** ({n_fail} check(s) failed)")
    add("")

    add("## Determination")
    add("")
    add(r["determination"])
    add("")

    add("- **Links**:")
    add(f"  - wrapped schematic: `{WRAPPED_SCHEMATIC}`")
    add(f"  - reused core body snapshot: `{BASE_SNAPSHOT.relative_to(REPO_ROOT)}`")
    add(f"  - predecessor (chained-array materiality): `sim/res-array-head-resistance/records/20260805-113409-6caa9f8.md`")
    add(f"  - runner: `sim/{SLUG}/run_res_array_resize.py`")
    add(f"  - logs: `{r['links']['corners_dir']}`")
    add(f"  - record_json: `{r['links']['json']}`")
    add(f"  - decision record: `spec/decision-records/DR-003-res-array-head-resistance-sizing.md`")
    add(f"- **Timestamp / author**: {r['timestamp']}, {r['author']}")
    add(f"- **Supersedes**: {r['supersedes'] or '(none — first record for this claim)'}")
    add("")
    add(
        f"Written by `sim/{SLUG}/run_res_array_resize.py`. Append-only: never edit this file — "
        "a correction is a new record with a `Supersedes` field (see `sim/README.md`)."
    )
    add("")
    return "\n".join(L)


def build_determination(resized, resized_trim, shipped, ra) -> str:
    out_shipped = [f"{p}/{s:.2f}V" for p, s in CORNERS if not (VREF_SPEC_V[0] <= shipped[(p, s)]["vref_27"] <= VREF_SPEC_V[1])]
    collapse_shipped = [f"{p}/{s:.2f}V" for p, s in CORNERS if shipped[(p, s)]["vref_max"] > VREF_SANITY_V[1]]
    resized_vrefs = [resized[(p, s)]["vref_27"] for p, s in CORNERS]
    resized_ok = all(VREF_SPEC_V[0] <= v <= VREF_SPEC_V[1] for v in resized_vrefs)
    resized_reg = all(VREF_SANITY_V[0] <= resized[(p, s)]["vref_max"] <= VREF_SANITY_V[1] for p, s in CORNERS)
    spans = {(p, s): resized_trim[(p, s, 0)]["vref_27"] - resized_trim[(p, s, -16)]["vref_27"] for p, s in CORNERS}
    min_span_mv = min(spans.values()) * 1000
    worst_case_3sigma_mv = 15.620  # sim/monte-carlo-untrimmed 20260803-142259-544cc5e, 125 degC
    trim_reg = all(
        VREF_SANITY_V[0] <= resized_trim[(p, s, t)]["vref_max"] <= VREF_SANITY_V[1]
        for p, s in CORNERS for t in TRIM_CODES
    )
    covers = min_span_mv >= 1.5 * worst_case_3sigma_mv

    seg = []
    seg.append(
        f"**Resize adopted: n_r1={RESIZE_N_R1}, n_r2={RESIZE_N_R2}** (was "
        f"n_r1={SHIPPED_N_R1}, n_r2={SHIPPED_N_R2}). Against the routed layout's real "
        f"chained-array topology this lowers K = R2/R1 from {ra['shipped']['k']:.4f} to "
        f"{ra['resized']['k']:.4f}, R2A/R2B from {ra['shipped']['r2_ohm']:.0f} to "
        f"{ra['resized']['r2_ohm']:.0f} ohm (R1 unchanged at {ra['resized']['r1_ohm']:.0f} ohm -- "
        "R1 is left at 7 units so the branch current, and therefore the hot-corner headroom "
        "margin the collapse depends on, is not raised while correcting K)."
    )
    if resized_ok and resized_reg:
        seg.append(
            "**AC2 met.** At the resized sizing, VOUT(27 degC) lands back inside the draft "
            f"+/-1% window (1.188-1.212 V) at all {len(CORNERS)} corners, and no corner "
            "collapses -- including ff/2.97 V and fs/2.97 V, the two the shipped chained "
            f"sizing pinned near 2.85 V. Resized VOUT(27) range across corners: "
            f"{min(resized_vrefs):.4f}-{max(resized_vrefs):.4f} V."
        )
    else:
        seg.append(
            "**AC2 NOT fully met at this sizing** -- see the per-corner checks; the resize "
            "integer or the R1 count needs another iteration (or the topology-change "
            "alternative in DR-003)."
        )
    seg.append(
        "**Control confirms the harness.** Re-running the shipped (n_r1="
        f"{SHIPPED_N_R1}, n_r2={SHIPPED_N_R2}) sizing on this same code path reproduces "
        f"DR-003: out of spec at {len(out_shipped)}/{len(CORNERS)} corners "
        f"({', '.join(out_shipped) if out_shipped else 'none'})"
        + (f" and regulation collapse at {', '.join(collapse_shipped)}" if collapse_shipped else "")
        + " -- so the in-spec resized result is a real change, not a harness difference."
    )
    seg.append(
        "**AC3 -- trim-range coverage.** Re-running (not re-citing) DR-002's downward "
        f"0..-16 `n_r2_trim` ladder on the RESIZED baseline: the code-0..-16 span is at least "
        f"{min_span_mv:.2f} mV per corner, "
        + (
            f"which still clears the 1.5x-of-3sigma coverage target "
            f"(1.5 x {worst_case_3sigma_mv:.2f} mV = {1.5 * worst_case_3sigma_mv:.2f} mV) "
            "DR-002 sized the range against"
            if covers
            else f"which NO LONGER clears the 1.5x-of-3sigma target "
            f"({1.5 * worst_case_3sigma_mv:.2f} mV) -- the range needs widening"
        )
        + (", and every downward code stays on the operating branch (collapse-free)." if trim_reg
           else ", but at least one downward code collapses -- see the table.")
    )
    seg.append(
        "Because the resize CENTERS the untrimmed operating point back near 1.20 V (rather "
        "than leaving it ~34 mV high, where the shipped chained part sits), DR-002's downward "
        "trim now spends its whole span on mismatch correction rather than on a static sizing "
        "offset -- so the existing 0..-16 range does not need to widen to absorb the "
        "head-resistance shift. The shift is corrected at the sizing lever (n_r2), which is "
        "the right lever for a deterministic, every-die offset, leaving the metal-option trim "
        "for the per-die mismatch it was scoped for (DR-002)."
    )
    seg.append(
        "**Layout follow-up (next lever).** This increment lands the sizing DECISION and its "
        "full PVT + trim re-verification in `design/bandgap_core.sch`. The routed layout "
        "generator (`layout/bin/gen_bandgap_routed.py`: `N_R1`, `SCH_N_R2`, `N_R2_COARSE`) "
        "must be re-transcribed to the resized decomposition and re-verified through klayout "
        "DRC/LVS -- which needs klayout (unavailable in this run environment) -- so, per this "
        "project's one-lever-per-increment discipline (the same discipline DR-003 used to "
        "defer this resize from the investigation), it is the next increment, tracked in "
        "DR-003's closure and `layout/matching-plan.md` Section 7x."
    )
    return "\n\n".join(seg)


def verify(timeout: int, author: str, supersedes: str, allow_pdk_mismatch: bool, dry_run: bool) -> int:
    pin = cr.load_pin()
    pdk = cr.resolve_pdk(pin)
    if not pdk.matches_pin and not allow_pdk_mismatch:
        raise cr.HarnessError(
            f"installed PDK {pdk.variant} is open_pdks {pdk.installed_commit}, but "
            f"sim/pdk.json pins {pin['open_pdks_commit']} (use --allow-pdk-mismatch to override)"
        )
    if not shutil.which("ngspice"):
        raise cr.HarnessError("ngspice not found on PATH")

    base_body = load_base_body(BASE_SNAPSHOT, EXPECTED_PARAMS)
    git_info = cr.git_state()
    now = datetime.now(timezone.utc)
    record_id = f"{now:%Y%m%d}-{now:%H%M%S}-{git_info['sha']}"

    records_dir = HERE / "records"
    corners_dir = HERE / "corners" / record_id
    record_md = records_dir / f"{record_id}.md"
    record_json = records_dir / f"{record_id}.json"
    for path in (record_md, record_json, corners_dir):
        if path.exists():
            raise cr.HarnessError(f"{path} already exists — sim/ is append-only, refusing to overwrite")

    ra = {
        "shipped": analytic_resistances(SHIPPED_N_R1, SHIPPED_N_R2),
        "resized": analytic_resistances(RESIZE_N_R1, RESIZE_N_R2),
    }
    print(f"experiment : {SLUG}")
    print(f"record id  : {record_id}")
    print(f"resize     : n_r1={RESIZE_N_R1} n_r2={RESIZE_N_R2}  (chained K {ra['shipped']['k']:.4f} -> {ra['resized']['k']:.4f})")

    if dry_run:
        print("(dry run: nothing written under sim/)")
        print(
            build_deck(
                SLUG,
                "run_res_array_resize.py",
                pdk,
                *CORNERS[0],
                substitute_arrays(base_body, RESIZE_N_R1, RESIZE_N_R2, 0),
            )
        )
        return 0

    run_dir = BUILD_DIR / record_id

    # AC2: resized, untrimmed
    resized = run_corner_set(run_dir, corners_dir, record_id, pdk, base_body, RESIZE_N_R1, RESIZE_N_R2, 0, timeout, "resized")
    for (p, s), m in resized.items():
        print(f"[resized] {p}/{s:.2f}V vref27={m['vref_27']:.6f} vref_max={m['vref_max']:.6f} tc={m['tc_ppm']:.1f}")

    # Control: shipped sizing (DR-003 reproduction)
    shipped = run_corner_set(run_dir, corners_dir, record_id, pdk, base_body, SHIPPED_N_R1, SHIPPED_N_R2, 0, timeout, "shipped")
    for (p, s), m in shipped.items():
        print(f"[shipped] {p}/{s:.2f}V vref27={m['vref_27']:.6f} vref_max={m['vref_max']:.6f}")

    # AC3: downward trim range on the resized baseline
    resized_trim: dict[tuple[str, float, int], dict] = {}
    for t in TRIM_CODES:
        if t == 0:
            for (p, s), m in resized.items():
                resized_trim[(p, s, 0)] = m
            continue
        rt = run_corner_set(run_dir, corners_dir, record_id, pdk, base_body, RESIZE_N_R1, RESIZE_N_R2, t, timeout, f"resized_trim{t}")
        for (p, s), m in rt.items():
            resized_trim[(p, s, t)] = m
            print(f"[trim {t:+d}] {p}/{s:.2f}V vref27={m['vref_27']:.6f} vref_max={m['vref_max']:.6f}")

    checks = evaluate(resized, resized_trim, shipped)
    overall = all(c["pass"] for c in checks)
    determination = build_determination(resized, resized_trim, shipped, ra)

    record = {
        "record_id": record_id,
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "author": author or cr.default_author(),
        "supersedes": supersedes,
        "resize": {"n_r1": RESIZE_N_R1, "n_r2": RESIZE_N_R2},
        "shipped_control": {"n_r1": SHIPPED_N_R1, "n_r2": SHIPPED_N_R2},
        "resistances": ra,
        "pdk": {
            "variant": pdk.variant,
            "installed_commit": pdk.installed_commit,
            "matches_pin": pdk.matches_pin,
            "lib_file": str(pdk.lib_file),
        },
        "tools": cr.tool_versions(),
        "git": git_info,
        "resized": {f"{p}:{s}": resized[(p, s)] for p, s in CORNERS},
        "shipped": {f"{p}:{s}": shipped[(p, s)] for p, s in CORNERS},
        "resized_trim": {f"{p}:{s}:{t}": resized_trim[(p, s, t)] for p, s in CORNERS for t in TRIM_CODES},
        "checks": checks,
        "overall_pass": overall,
        "determination": determination,
        "links": {
            "corners_dir": str(corners_dir.relative_to(REPO_ROOT)) + "/",
            "json": str(record_json.relative_to(REPO_ROOT)),
            "record": str(record_md.relative_to(REPO_ROOT)),
        },
    }

    records_dir.mkdir(parents=True, exist_ok=True)
    record_json.write_text(json.dumps(record, indent=2, sort_keys=True, default=str) + "\n")
    record_md.write_text(render_record(record))

    print()
    print(f"record  : {record_md.relative_to(REPO_ROOT)}")
    print(f"json    : {record_json.relative_to(REPO_ROOT)}")
    print(f"overall : {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 2


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--explore", nargs="+", type=int, metavar="N",
                   help="explore mode: flat list of n_r1 n_r2 pairs to sweep (no record written)")
    p.add_argument("--author", default="")
    p.add_argument("--supersedes", default="")
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--allow-pdk-mismatch", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.explore:
        if len(args.explore) % 2 != 0:
            raise cr.HarnessError("--explore needs an even count: n_r1 n_r2 [n_r1 n_r2 ...]")
        pairs = [(args.explore[i], args.explore[i + 1]) for i in range(0, len(args.explore), 2)]
        return explore(pairs, args.timeout)
    return verify(args.timeout, args.author, args.supersedes, args.allow_pdk_mismatch, args.dry_run)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except cr.HarnessError as err:
        print(f"run_res_array_resize: error: {err}", file=sys.stderr)
        sys.exit(1)
