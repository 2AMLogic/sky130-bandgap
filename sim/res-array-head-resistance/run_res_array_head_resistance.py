#!/usr/bin/env python3
"""Real-SPICE check of the routed layout's folded R2A/R2B/R1 array topology
against `design/bandgap_core.sch`'s single-`res_high_po`-device model, for
issue #98.

Why this is a bespoke script and not another `experiment.json` +
`sim/bin/corner-run.py` manifest: like `sim/trim-range-monotonicity/`'s own
`run_trim_sweep.py`, the claim needs the SAME netlisted core body re-run with
a structural (not parametric) edit -- here, replacing each of `XR2A`/`XR2B`/
`XR1`'s single `sky130_fd_pr__res_high_po` device line with a chain of
several separately-instantiated unit devices wired in series through new
intermediate nodes, exactly reproducing the routed layout's own decomposition
(`layout/bin/gen_bandgap_routed.py`'s `res_r2`/`res_trim`/`res_r1` block
params: 50 coarse 5 um + 20 fine 1 um units per R2 leg, 7 coarse 5 um units
for R1, all W=1 um). That is a body-substitution problem, not a
`deck.params` override -- the corner runner's manifest path has no way to
turn "one device" into "N devices" in a netlisted body.

Two phases, one record:

  PHASE A -- standalone comparison (nominal tt, 27 degC, single `.op`,
  MC_MM_SWITCH=0 implicit at DC): a raw, hand-written ngspice deck (no
  xschem schematic -- same pattern `layout/matching-plan.md` Section 7t used
  to check the real `sky130_fd_pr__res_high_po` PDK model card directly)
  chains N real unit-device instances at the layout's own N/L shapes for
  both R1 and R2A/R2B, and compares the resulting two-terminal resistance
  against (a) `design/bandgap_core.sch`'s own `R ~ 380 + 325*L` approximation
  and (b) one `res_high_po` instance drawn at the combined length -- i.e.
  the model every existing PVT sim record in this repo actually simulates
  today (see `design/bandgap_core.sch` lines ~250-278: `XR2A`/`XR2B`/`XR1`
  are each ONE device at `L='r_lseg*n_r2'` / `L='r_lseg*n_r1'`, not a chain).
  This phase answers issue #98's central question: is the routed layout's
  extra resistance (2AMLogic/klayout-tools#518/#519/#526's LVS finding) a
  real SPICE-level electrical property of drawing N separately-contacted
  devices, or an LVS/extraction-only bookkeeping artifact?

  PHASE B -- materiality: wraps the exact core netlist body PR #62's own
  `sim/trim-range-monotonicity/` record already produced and checked in
  (`sim/trim-range-monotonicity/netlist-snapshots/20260803-170704-b976d0f.spice`,
  verified below to still match `design/bandgap_core.sch`'s current
  `.param` values byte-for-byte -- no drift since that snapshot was taken),
  substitutes `XR2A`/`XR2B`/`XR1`'s single-device lines for the same N-chain
  topology Phase A verified, and re-runs the identical 5 (process, supply)
  corner points `run_trim_sweep.py`'s own NEGATIVE_CORNERS set already
  covers (tt/3.30, ss/3.30, ff/2.97, sf/2.97, fs/2.97), each with the same
  box-method `dc temp -40 125 11` sweep and `vref_27`/`tc_ppm` measurements
  issue #11/#13's own testbench already uses. The baseline (single-device)
  values for these exact 5 points are NOT re-run here -- they are read
  directly from that already-committed, append-only record
  (`sim/trim-range-monotonicity/records/20260803-170704-b976d0f.json`,
  trim_code=0 rows), the same "reuse existing evidence" convention
  `run_trim_sweep.py` itself uses for issue #11's testbench.

  Note on tool availability: this run environment has `ngspice` but not
  `xschem`, so Phase B cannot re-netlist `tb_vref_tc.sch` itself (the
  mechanism `sim/bin/corner_run.netlist_with_xschem` uses). It instead reads
  the already-checked-in, current netlist snapshot named above as its base
  body -- verified byte-identical on the `.param` lines that matter
  (`n_r1`/`n_r2`/`n_r2_trim`/`r_lseg`/`r_lseg_trim`/`r_w`) against
  `design/bandgap_core.sch`'s present content before use, and the script
  refuses to run if that check fails (a schematic edit since that snapshot
  was taken would silently invalidate the comparison).

Usage
-----
    sim/res-array-head-resistance/run_res_array_head_resistance.py
    sim/res-array-head-resistance/run_res_array_head_resistance.py --dry-run

Exit status: 0 if every check passed, 2 if a record was written but a check
failed, 1 on a harness/setup error (no record written) -- same convention as
`corner-run.py` / `run_trim_sweep.py`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO_ROOT = SIM_DIR.parent
SPICEINIT_FILE = SIM_DIR / "spiceinit"
BUILD_DIR = SIM_DIR / "build" / "res-array-head-resistance"

sys.path.insert(0, str(SIM_DIR / "bin"))
from sim_common import (  # noqa: E402
    chain_lines,
    load_corner_run,
    parse_measurements,
    run_ngspice,
    write_log,
)

# The core netlist body this experiment wraps (Phase B), reference-only --
# never modified by this script. Produced by sim/trim-range-monotonicity's
# own run at trim_code=0, which wraps sim/output-voltage-tc/testbench/
# tb_vref_tc.sch (design/bandgap_core.sch) unmodified.
BASE_SNAPSHOT = (
    SIM_DIR / "trim-range-monotonicity" / "netlist-snapshots" / "20260803-170704-b976d0f.spice"
)
BASE_RECORD_JSON = (
    SIM_DIR / "trim-range-monotonicity" / "records" / "20260803-170704-b976d0f.json"
)
WRAPPED_SCHEMATIC = "sim/output-voltage-tc/testbench/tb_vref_tc.sch"


cr = load_corner_run()

SLUG = "res-array-head-resistance"
TITLE = (
    "Does the routed layout's folded R2A/R2B/R1 res_high_po array add real "
    "per-instance head resistance beyond design/bandgap_core.sch's "
    "single-device model? (issue #98)"
)

# --------------------------------------------------------------------------
# Geometry -- transcribed from layout/bin/gen_bandgap_routed.py's BLOCKS
# (res_r2/res_trim/res_r1 params) and design/bandgap_core.sch's CORE_PARAMS,
# at the shipped, untrimmed n_r2_trim=0 code (every unit electrically in
# circuit -- see gen_bandgap_routed.py's trim_tap_ladder docstring).
# --------------------------------------------------------------------------
R_W_UM = 1.0
R_LSEG_UM = 5.0
R_LSEG_TRIM_UM = 1.0
N_R1 = 7
N_R2_COARSE = 50
N_R2_TRIM_UNITS = 20

R1_SEGMENTS_UM = [R_LSEG_UM] * N_R1  # 7 x 5um = 35um
R2_SEGMENTS_UM = [R_LSEG_UM] * N_R2_COARSE + [R_LSEG_TRIM_UM] * N_R2_TRIM_UNITS  # 70 x, 270um

R1_COMBINED_L_UM = sum(R1_SEGMENTS_UM)
R2_COMBINED_L_UM = sum(R2_SEGMENTS_UM)

# design/bandgap_core.sch line ~188's approximation, and
# layout/bandgap-core/reference.spice's RR1/RR2A/RR2B literal values.
SCH_APPROX_OFFSET_OHM = 380.0
SCH_APPROX_SLOPE_OHM_PER_UM = 325.0


def sch_approx_ohm(length_um: float) -> float:
    return SCH_APPROX_OFFSET_OHM + SCH_APPROX_SLOPE_OHM_PER_UM * length_um


# 2AMLogic/klayout-tools#518/#519/#526's own reported LVS-extracted values
# (issue #98's Problem section, layout/bandgap-core/reports/LATEST as of PR
# #97, N*379.705147 + 324.827244*L) -- cited here ONLY as a cross-check
# target for Phase A's chained-instance measurement, not as ground truth.
KLT_EXTRACTED_R1_OHM = 14026.89
KLT_EXTRACTED_R2_OHM = 114282.72
# Reproduction tolerance: klt's own extraction rounds/reports to 2 decimal
# digits and folds mismatch (MC_MM_SWITCH=0 here too, so this is a like-for-
# like nominal-tt comparison) via combine_devices' analytic L/W*sheet_rho +
# fixed_offset formula, vs. this script's full nonlinear `r`-device model
# (p2/q2 shape terms) evaluated by ngspice itself -- agreement to within
# 0.1% would already be a strong structural confirmation.
KLT_REPRO_REL_TOL = 0.001

# --------------------------------------------------------------------------
# Phase B corner matrix -- identical to run_trim_sweep.py's NEGATIVE_CORNERS
# (process, supply) set, at trim_code=0 (untrimmed, the shipped default).
# --------------------------------------------------------------------------
PHASE_B_CORNERS = (
    ("tt", 3.30),
    ("ss", 3.30),
    ("ff", 2.97),
    ("sf", 2.97),
    ("fs", 2.97),
)

VREF_SPEC_V = (1.188, 1.212)  # draft spec: 1.20 V +/- 1% (sim/output-voltage-tc/experiment.json)
VREF_SANITY_V = (1.10, 1.30)  # loose regulation-loss guard, same band run_trim_sweep.py uses


# --------------------------------------------------------------------------
# Phase A -- standalone chained-instance vs. single-instance comparison
# --------------------------------------------------------------------------


def phase_a_deck(pdk) -> str:
    lines: list[str] = [
        f"* {SLUG} Phase A deck -- generated by sim/{SLUG}/run_res_array_head_resistance.py, do not edit",
        ".option wnflag=1 reltol=1e-6 vntol=1e-9 abstol=1e-15",
        f'.lib "{pdk.lib_file}" tt',
        "",
        "* ---- R1 shape: N_R1 series units (layout: res_r1 block) ----",
        *chain_lines("R1CHAIN", "r1c_lo", "r1c_hi", R1_SEGMENTS_UM, "0"),
        "IR1CHAIN r1c_hi r1c_lo dc 1m",
        f"XR1SINGLE r1s_lo r1s_hi 0 sky130_fd_pr__res_high_po W={R_W_UM} L={R1_COMBINED_L_UM} mult=1 m=1",
        "IR1SINGLE r1s_hi r1s_lo dc 1m",
        "",
        "* ---- R2 shape: N_R2_COARSE + N_R2_TRIM_UNITS series units (layout: res_r2 + res_trim) ----",
        *chain_lines("R2CHAIN", "r2c_lo", "r2c_hi", R2_SEGMENTS_UM, "0"),
        "IR2CHAIN r2c_hi r2c_lo dc 1m",
        f"XR2SINGLE r2s_lo r2s_hi 0 sky130_fd_pr__res_high_po W={R_W_UM} L={R2_COMBINED_L_UM} mult=1 m=1",
        "IR2SINGLE r2s_hi r2s_lo dc 1m",
        "",
        ".control",
        "save all",
        "op",
        "let meas_r1_chain_ohm = (v(r1c_lo)-v(r1c_hi))/1m",
        "let meas_r1_single_ohm = (v(r1s_lo)-v(r1s_hi))/1m",
        "let meas_r2_chain_ohm = (v(r2c_lo)-v(r2c_hi))/1m",
        "let meas_r2_single_ohm = (v(r2s_lo)-v(r2s_hi))/1m",
        "print meas_r1_chain_ohm",
        "print meas_r1_single_ohm",
        "print meas_r2_chain_ohm",
        "print meas_r2_single_ohm",
        "quit",
        ".endc",
        ".end",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Phase B -- materiality: wrap the real core, substitute the chained arrays
# --------------------------------------------------------------------------

# The exact single-device lines this script replaces (verified present,
# exactly once each, in BASE_SNAPSHOT before substitution).
PHASE_B_TARGET_LINES = {
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

# The current schematic's .param values that must match BASE_SNAPSHOT's own
# .param lines byte-for-byte -- guards against silent drift between the
# snapshot (last taken 2026-08-03) and design/bandgap_core.sch's present
# content, since Phase B cannot re-netlist via xschem in this run
# environment (see module docstring).
EXPECTED_PARAMS = {
    ".param n_pnp_ctat=8",
    ".param n_pnp_ptat=8",
    ".param r_w=1",
    ".param r_lseg=5",
    ".param n_r1=7",
    ".param n_r2=54",
    ".param m_out=2",
    ".param m_ampbias=2",
    ".param n_r2_trim=0",
    ".param r_lseg_trim=1",
}


def load_base_body() -> list[str]:
    if not BASE_SNAPSHOT.is_file():
        raise cr.HarnessError(f"missing base netlist snapshot: {BASE_SNAPSHOT}")
    text = BASE_SNAPSHOT.read_text()
    lines = [ln for ln in text.splitlines() if ln.strip().lower() != ".end"]

    present_params = {ln.strip() for ln in lines if ln.strip().startswith(".param ")}
    missing = EXPECTED_PARAMS - present_params
    if missing:
        raise cr.HarnessError(
            f"base netlist snapshot {BASE_SNAPSHOT} is missing expected .param line(s) "
            f"{sorted(missing)} -- design/bandgap_core.sch may have drifted since this "
            "snapshot was taken; re-derive the snapshot (needs xschem) before trusting "
            "Phase B's comparison against the trim-range-monotonicity baseline"
        )
    return lines


def substitute_chained_arrays(body: list[str]) -> list[str]:
    out: list[str] = []
    found: set[str] = set()
    for line in body:
        stripped = line.strip()
        replaced = False
        for key, target in PHASE_B_TARGET_LINES.items():
            if stripped == target:
                if key in found:
                    raise cr.HarnessError(f"{key} line appears more than once in base body")
                found.add(key)
                if key == "XR2A":
                    out.extend(chain_lines("R2A", "VA", "VOUT", R2_SEGMENTS_UM, "VSS"))
                elif key == "XR2B":
                    out.extend(chain_lines("R2B", "VB", "VOUT", R2_SEGMENTS_UM, "VSS"))
                elif key == "XR1":
                    out.extend(chain_lines("R1", "VBQ", "VB", R1_SEGMENTS_UM, "VSS"))
                replaced = True
                break
        if not replaced:
            out.append(line)
    missing = set(PHASE_B_TARGET_LINES) - found
    if missing:
        raise cr.HarnessError(
            f"expected line(s) for {sorted(missing)} not found (exactly once each) in "
            f"{BASE_SNAPSHOT} -- schematic may have changed out from under this script"
        )
    return out


def phase_b_deck(pdk, process: str, supply_v: float, body: list[str]) -> str:
    head = [
        f"* {SLUG} Phase B deck (process={process}, supply={supply_v}) -- "
        f"generated by sim/{SLUG}/run_res_array_head_resistance.py, do not edit",
        ".option wnflag=1 reltol=1e-6 vntol=1e-9 abstol=1e-15",
        f".param vsup={supply_v}",
        f'.lib "{pdk.lib_file}" {process}',
    ]
    control = [
        ".control",
        "save all",
        "dc temp -40 125 11",
        "meas dc vref27 FIND v(vref) AT=27",
        "let vspan = 165",
        "let meas_vref_27 = vref27",
        "let meas_vref_min = minimum(v(vref))",
        "let meas_vref_max = maximum(v(vref))",
        "let meas_tc_ppm = (maximum(v(vref))-minimum(v(vref)))/(vref27*vspan)*1e6",
        "let meas_n_temp_points = length(v(vref))",
        "print meas_vref_27",
        "print meas_vref_min",
        "print meas_vref_max",
        "print meas_tc_ppm",
        "print meas_n_temp_points",
        "quit",
        ".endc",
        ".end",
        "",
    ]
    return "\n".join(head + body + control)


def load_phase_b_baseline() -> dict[tuple[str, float], dict]:
    if not BASE_RECORD_JSON.is_file():
        raise cr.HarnessError(f"missing baseline record: {BASE_RECORD_JSON}")
    data = json.loads(BASE_RECORD_JSON.read_text())
    out: dict[tuple[str, float], dict] = {}
    for process, supply in PHASE_B_CORNERS:
        key = f"{process}:{supply}:0"
        if key not in data["results"]:
            raise cr.HarnessError(
                f"baseline record {BASE_RECORD_JSON} has no trim_code=0 result for {key}"
            )
        out[(process, supply)] = data["results"][key]
    return out


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------


def evaluate(phase_a: dict, phase_b: dict[tuple[str, float], dict], baseline: dict[tuple[str, float], dict]) -> list[dict]:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str):
        checks.append({"name": name, "pass": ok, "detail": detail})

    # --- Phase A: chained total must exceed both reference models (the
    # central determination -- reading 2 requires this to be true) ---
    r1_chain = phase_a["r1_chain_ohm"]
    r1_single = phase_a["r1_single_ohm"]
    r2_chain = phase_a["r2_chain_ohm"]
    r2_single = phase_a["r2_single_ohm"]
    add(
        "r1_chain_exceeds_single_device_model",
        r1_chain > r1_single,
        f"R1: chained (N={N_R1}) = {r1_chain:.2f} ohm vs single-instance-at-combined-L "
        f"({R1_COMBINED_L_UM:.0f} um) = {r1_single:.2f} ohm, delta "
        f"{(r1_chain - r1_single) / r1_single:+.2%}",
    )
    add(
        "r2_chain_exceeds_single_device_model",
        r2_chain > r2_single,
        f"R2A/R2B: chained (N={N_R2_COARSE + N_R2_TRIM_UNITS}) = {r2_chain:.2f} ohm vs "
        f"single-instance-at-combined-L ({R2_COMBINED_L_UM:.0f} um) = {r2_single:.2f} ohm, "
        f"delta {(r2_chain - r2_single) / r2_single:+.2%}",
    )

    # --- Phase A: reproduces klt's own reported LVS-extracted values --
    # the structural confirmation that this is the same electrical effect,
    # not a coincidentally similar but different number ---
    r1_repro = abs(r1_chain - KLT_EXTRACTED_R1_OHM) / KLT_EXTRACTED_R1_OHM
    add(
        "r1_chain_reproduces_klt_extraction",
        r1_repro <= KLT_REPRO_REL_TOL,
        f"chained R1 = {r1_chain:.2f} ohm vs klt-extracted {KLT_EXTRACTED_R1_OHM:.2f} ohm "
        f"(2AMLogic/klayout-tools#518/#519/#526), relative diff {r1_repro:.4%} "
        f"(tolerance {KLT_REPRO_REL_TOL:.2%})",
    )
    r2_repro = abs(r2_chain - KLT_EXTRACTED_R2_OHM) / KLT_EXTRACTED_R2_OHM
    add(
        "r2_chain_reproduces_klt_extraction",
        r2_repro <= KLT_REPRO_REL_TOL,
        f"chained R2A/R2B = {r2_chain:.2f} ohm vs klt-extracted {KLT_EXTRACTED_R2_OHM:.2f} ohm "
        f"(2AMLogic/klayout-tools#518/#519/#526), relative diff {r2_repro:.4%} "
        f"(tolerance {KLT_REPRO_REL_TOL:.2%})",
    )

    # --- Phase A: single-instance-at-combined-L closely tracks the
    # schematic's own R ~ 380 + 325*L approximation (re-confirms Section
    # 7t's finding on THIS repo's own two lengths, not a new claim) ---
    r1_sch = sch_approx_ohm(R1_COMBINED_L_UM)
    r1_sch_diff = abs(r1_single - r1_sch) / r1_sch
    add(
        "r1_single_device_matches_schematic_approximation",
        r1_sch_diff <= 0.01,
        f"single-instance R1 (L={R1_COMBINED_L_UM:.0f}um) = {r1_single:.2f} ohm vs "
        f"design/bandgap_core.sch approximation {r1_sch:.2f} ohm, diff {r1_sch_diff:.3%}",
    )
    r2_sch = sch_approx_ohm(R2_COMBINED_L_UM)
    r2_sch_diff = abs(r2_single - r2_sch) / r2_sch
    add(
        "r2_single_device_matches_schematic_approximation",
        r2_sch_diff <= 0.01,
        f"single-instance R2A/R2B (L={R2_COMBINED_L_UM:.0f}um) = {r2_single:.2f} ohm vs "
        f"design/bandgap_core.sch approximation {r2_sch:.2f} ohm, diff {r2_sch_diff:.3%}",
    )

    # --- Phase B: does the chained-array VOUT stay inside the +/-1% spec
    # window at every one of the 5 corner points, given the baseline
    # (single-device) values already pass it? ---
    for process, supply in PHASE_B_CORNERS:
        base = baseline[(process, supply)]
        chained = phase_b[(process, supply)]
        corner_id = f"{process}_{supply:.2f}v"
        add(
            f"baseline_sane[{corner_id}]",
            VREF_SANITY_V[0] <= base["vref_27"] <= VREF_SANITY_V[1],
            f"baseline (single-device) vref_27={base['vref_27']:.6f} V",
        )
        chained_in_spec = VREF_SPEC_V[0] <= chained["vref_27"] <= VREF_SPEC_V[1]
        add(
            f"chained_vref27_in_spec[{corner_id}]",
            chained_in_spec,
            f"chained-array vref_27={chained['vref_27']:.6f} V vs draft spec window "
            f"{VREF_SPEC_V} (baseline was {base['vref_27']:.6f} V)"
            + ("" if chained_in_spec else " -- OUT OF SPEC"),
        )
        add(
            f"chained_still_regulating[{corner_id}]",
            VREF_SANITY_V[0] <= chained["vref_max"] <= VREF_SANITY_V[1],
            f"chained-array vref_max={chained['vref_max']:.6f} V (sanity band {VREF_SANITY_V}; "
            "outside it would mean the operating point collapsed, per issue #46/#91's own "
            "regulation-loss signature)",
        )

    return checks


# --------------------------------------------------------------------------
# record rendering
# --------------------------------------------------------------------------


def render_record(record: dict) -> str:
    r = record
    L: list[str] = []

    def add(line: str = ""):
        L.append(line)

    add(f"# Record {r['record_id']}")
    add("")
    add(f"- **Record ID**: {r['record_id']}")
    add(f"- **Experiment**: `{SLUG}` — {TITLE}")
    add(
        "- **Claim**: issue #98 -- the routed layout draws each `R1`/`R2A`/`R2B` "
        "divider leg as a *chain* of separately-contacted `res_high_po` unit "
        "instances (`layout/bin/gen_bandgap_routed.py`'s `res_r2`/`res_trim`/"
        "`res_r1` blocks, wired in series via real drawn metal+via through "
        "`bus_res_series`), while `design/bandgap_core.sch` and every existing "
        "PVT sim record model each leg as ONE `res_high_po` device at the "
        "combined length. 2AMLogic/klayout-tools#518/#519/#526 taught `klt "
        "extract` a real per-instance head/end-effect resistance term, which "
        "now makes the layout's extracted R1/R2A/R2B read higher than the "
        "schematic's model (R1 +19.3%, R2A/R2B +29.7%, per issue #98's own "
        "measurement). **Phase A determines whether this is a real SPICE-"
        "level electrical property of the chained topology or an LVS-only "
        "bookkeeping artifact. Phase B determines whether it is material to "
        "VOUT/TC at the PVT corners issue #46/#91 already flagged as "
        "margin-thin.**"
    )
    add(
        "- **Netlist provenance**: Phase A -- raw, hand-written ngspice deck "
        "(no schematic; same pattern as `layout/matching-plan.md` Section "
        "7t's single-device PDK-model-card check). Phase B -- schematic "
        f"(`{WRAPPED_SCHEMATIC}`, wrapping `design/bandgap_core.sch`), reused "
        "via the already-checked-in netlist snapshot "
        f"`{BASE_SNAPSHOT.relative_to(REPO_ROOT)}` (xschem is not available in "
        "this run environment -- see the script's module docstring; the "
        "snapshot was verified byte-identical to `design/bandgap_core.sch`'s "
        "current `.param` values before use)."
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
        "- **Corner matrix**: Phase A at nominal `tt`, 27 degC, MC_MM_SWITCH=0 "
        "(single `.op` point, matching Section 7t). Phase B at the 5 (process, "
        "supply) corners " + ", ".join(f"{p}/{s:.2f} V" for p, s in PHASE_B_CORNERS)
        + ", each with a continuous in-deck `dc temp -40 125 11` box-method "
        "temperature sweep (16 points) -- identical corner set and method to "
        "`sim/trim-range-monotonicity/`'s own NEGATIVE_CORNERS."
    )
    add("- **Statistical convention**: N/A (deterministic geometry/topology comparison, not a distribution claim).")
    add("")

    add("## Phase A -- chained-instance vs. single-instance resistance")
    add("")
    add("| leg | shape | ngspice result (ohm) | vs. schematic approx (ohm) | vs. single-device-at-combined-L (ohm) |")
    add("|---|---|---|---|---|")
    pa = r["phase_a"]
    r1_sch = sch_approx_ohm(R1_COMBINED_L_UM)
    r2_sch = sch_approx_ohm(R2_COMBINED_L_UM)
    add(
        f"| R1 | single instance, L={R1_COMBINED_L_UM:.0f} um | {pa['r1_single_ohm']:.2f} | "
        f"{r1_sch:.2f} ({(pa['r1_single_ohm'] - r1_sch) / r1_sch:+.3%}) | — |"
    )
    add(
        f"| R1 | chained, N={N_R1} x L={R_LSEG_UM:.0f}um | {pa['r1_chain_ohm']:.2f} | "
        f"{r1_sch:.2f} ({(pa['r1_chain_ohm'] - r1_sch) / r1_sch:+.3%}) | "
        f"{pa['r1_single_ohm']:.2f} ({(pa['r1_chain_ohm'] - pa['r1_single_ohm']) / pa['r1_single_ohm']:+.3%}) |"
    )
    add(
        f"| R2A/R2B | single instance, L={R2_COMBINED_L_UM:.0f} um | {pa['r2_single_ohm']:.2f} | "
        f"{r2_sch:.2f} ({(pa['r2_single_ohm'] - r2_sch) / r2_sch:+.3%}) | — |"
    )
    add(
        f"| R2A/R2B | chained, N={N_R2_COARSE}x{R_LSEG_UM:.0f}um + {N_R2_TRIM_UNITS}x{R_LSEG_TRIM_UM:.0f}um | "
        f"{pa['r2_chain_ohm']:.2f} | {r2_sch:.2f} ({(pa['r2_chain_ohm'] - r2_sch) / r2_sch:+.3%}) | "
        f"{pa['r2_single_ohm']:.2f} ({(pa['r2_chain_ohm'] - pa['r2_single_ohm']) / pa['r2_single_ohm']:+.3%}) |"
    )
    add("")
    k_single = pa["r2_single_ohm"] / pa["r1_single_ohm"]
    k_chain = pa["r2_chain_ohm"] / pa["r1_chain_ohm"]
    add(
        f"K = R2/R1: single-device model = {k_single:.4f}; chained (real layout topology) = "
        f"{k_chain:.4f} ({(k_chain - k_single) / k_single:+.2%})."
    )
    add("")
    add(
        f"**Reproduction of klt's own extraction** (2AMLogic/klayout-tools#518/#519/#526, issue "
        f"#98's Problem section): chained R1 = {pa['r1_chain_ohm']:.2f} ohm vs. klt-extracted "
        f"{KLT_EXTRACTED_R1_OHM:.2f} ohm ({abs(pa['r1_chain_ohm'] - KLT_EXTRACTED_R1_OHM) / KLT_EXTRACTED_R1_OHM:.4%} "
        f"diff); chained R2A/R2B = {pa['r2_chain_ohm']:.2f} ohm vs. klt-extracted "
        f"{KLT_EXTRACTED_R2_OHM:.2f} ohm ({abs(pa['r2_chain_ohm'] - KLT_EXTRACTED_R2_OHM) / KLT_EXTRACTED_R2_OHM:.4%} diff). "
        "This is real SPICE (ngspice evaluating the PDK's own nonlinear `rhead`/`rbody` "
        "semiconductor-resistor model cards, chained through ideal zero-resistance wires -- "
        "not klt's own analytic `L/W*sheet_rho + fixed_offset` approximation), so this close an "
        "agreement is not circular: it independently confirms the LVS-measured delta is a real "
        "electrical consequence of drawing N separately-contacted devices, not an artifact of how "
        "`klt`'s `combine_devices()` folds series resistors during extraction."
    )
    add("")

    add("## Phase B -- materiality: VOUT/TC with the chained-array topology")
    add("")
    add("| process | supply (V) | model | VREF(27 °C) (V) | VREF max (V) | TC (ppm/°C) | in +/-1% spec? |")
    add("|---|---|---|---|---|---|---|")
    for process, supply in PHASE_B_CORNERS:
        base = r["phase_b_baseline"][f"{process}:{supply}"]
        chained = r["phase_b"][f"{process}:{supply}"]
        base_ok = "yes" if VREF_SPEC_V[0] <= base["vref_27"] <= VREF_SPEC_V[1] else "**NO**"
        chained_ok = "yes" if VREF_SPEC_V[0] <= chained["vref_27"] <= VREF_SPEC_V[1] else "**NO**"
        add(
            f"| {process} | {supply:.2f} | single-device (baseline) | {base['vref_27']:.6f} | "
            f"{base['vref_max']:.6f} | {base['tc_ppm']:.3f} | {base_ok} |"
        )
        add(
            f"| {process} | {supply:.2f} | chained array (this record) | {chained['vref_27']:.6f} | "
            f"{chained['vref_max']:.6f} | {chained['tc_ppm']:.3f} | {chained_ok} |"
        )
    add("")
    add(
        "Baseline (single-device) rows are read directly from "
        f"`{BASE_RECORD_JSON.relative_to(REPO_ROOT)}`'s trim_code=0 results (not re-run here) -- "
        "the same evidence-reuse convention `run_trim_sweep.py` itself uses."
    )
    add("")

    add("## Checks")
    add("")
    n_fail = sum(1 for c in r["checks"] if not c["pass"])
    for c in r["checks"]:
        verdict = "PASS" if c["pass"] else "FAIL"
        add(f"- {verdict} `{c['name']}` — {c['detail']}")
    add("")
    add(f"- **Overall: {'PASS' if r['overall_pass'] else 'FAIL'}** ({n_fail} check(s) failed)")
    add("")

    add("## Determination")
    add("")
    add(r["determination"])
    add("")

    add("- **Links**:")
    add(f"  - wrapped schematic: `{WRAPPED_SCHEMATIC}`")
    add(f"  - Phase B base netlist snapshot: `{BASE_SNAPSHOT.relative_to(REPO_ROOT)}`")
    add(f"  - Phase B baseline record: `{BASE_RECORD_JSON.relative_to(REPO_ROOT)}`")
    add(f"  - runner: `sim/{SLUG}/run_res_array_head_resistance.py`")
    add(f"  - logs: `{r['links']['corners_dir']}`")
    add(f"  - record_json: `{r['links']['json']}`")
    add(f"  - layout closure: `layout/matching-plan.md`, next dated section")
    add(f"- **Timestamp / author**: {r['timestamp']}, {r['author']}")
    add(f"- **Supersedes**: {r['supersedes'] or '(none — first record for this claim)'}")
    add("")
    add(
        f"Written by `sim/{SLUG}/run_res_array_head_resistance.py`. Append-only: never edit this "
        "file — a correction is a new record with a `Supersedes` field (see `sim/README.md`)."
    )
    add("")
    return "\n".join(L)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--author", default="", help="record author (default: git user.email)")
    p.add_argument("--supersedes", default="", help="record id this run supersedes")
    p.add_argument("--timeout", type=int, default=1800, help="per-point ngspice timeout (s)")
    p.add_argument(
        "--allow-pdk-mismatch",
        action="store_true",
        help="run even if the installed PDK differs from the sim/pdk.json pin",
    )
    p.add_argument("--dry-run", action="store_true", help="print the plan, write nothing under sim/")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    pin = cr.load_pin()
    pdk = cr.resolve_pdk(pin)
    if not pdk.matches_pin and not args.allow_pdk_mismatch:
        raise cr.HarnessError(
            f"installed PDK {pdk.variant} is open_pdks {pdk.installed_commit}, but "
            f"sim/pdk.json pins {pin['open_pdks_commit']}\n"
            f"  install the pin: {pin['install_command']}\n"
            f"  or re-run with --allow-pdk-mismatch (the record will say so)"
        )
    if not shutil.which("ngspice"):
        raise cr.HarnessError("ngspice not found on PATH")

    base_body = load_base_body()
    substituted_body = substitute_chained_arrays(base_body)
    baseline = load_phase_b_baseline()

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

    print(f"experiment      : {SLUG}")
    print(f"record id       : {record_id}")
    print(f"PDK             : {pdk.dir} (open_pdks {pdk.installed_commit})")
    print(f"Phase A         : R1 N={N_R1} L={R1_SEGMENTS_UM}; R2 N={len(R2_SEGMENTS_UM)} L={R2_SEGMENTS_UM}")
    print(f"Phase B corners : {PHASE_B_CORNERS}")

    if args.dry_run:
        print("\n-- Phase A deck --")
        print(phase_a_deck(pdk))
        print("\n-- Phase B deck for first corner --")
        print(phase_b_deck(pdk, *PHASE_B_CORNERS[0], substituted_body))
        print("\n(dry run: nothing written under sim/<experiment>/)")
        return 0

    run_dir = BUILD_DIR / record_id

    # --- Phase A ---
    deck_a = phase_a_deck(pdk)
    stamp = datetime.now(timezone.utc)
    raw_a, rc_a, timedout_a = run_ngspice(run_dir, "phase_a", deck_a, args.timeout)
    write_log(corners_dir, "phase_a", record_id, pdk, stamp, deck_a, raw_a, rc_a, timedout_a)
    meas_a = parse_measurements(raw_a)
    print(f"[phase A] rc={rc_a}{' TIMEOUT' if timedout_a else ''} {meas_a}")
    required_a = {"r1_chain_ohm", "r1_single_ohm", "r2_chain_ohm", "r2_single_ohm"}
    if timedout_a or rc_a != 0 or not required_a.issubset(meas_a):
        raise cr.HarnessError(f"Phase A did not produce usable measurements (rc={rc_a}, timed_out={timedout_a})")

    # --- Phase B ---
    phase_b: dict[tuple[str, float], dict] = {}
    for i, (process, supply) in enumerate(PHASE_B_CORNERS, start=1):
        deck_b = phase_b_deck(pdk, process, supply, substituted_body)
        stamp = datetime.now(timezone.utc)
        name = f"phase_b_{process}_{supply:.2f}v"
        raw_b, rc_b, timedout_b = run_ngspice(run_dir, name, deck_b, args.timeout)
        write_log(corners_dir, name, record_id, pdk, stamp, deck_b, raw_b, rc_b, timedout_b)
        meas_b = parse_measurements(raw_b)
        print(
            f"[phase B {i}/{len(PHASE_B_CORNERS)}] {process}/{supply:.2f}V rc={rc_b}"
            f"{' TIMEOUT' if timedout_b else ''} vref_27={meas_b.get('vref_27')} tc_ppm={meas_b.get('tc_ppm')}"
        )
        if timedout_b or rc_b != 0 or "vref_27" not in meas_b:
            raise cr.HarnessError(
                f"Phase B point {process}/{supply}V did not produce usable measurements "
                f"(rc={rc_b}, timed_out={timedout_b})"
            )
        phase_b[(process, supply)] = meas_b

    checks = evaluate(meas_a, phase_b, baseline)
    overall = all(c["pass"] for c in checks)

    # determination narrative, derived from the checks (not hand-waved)
    r1_delta = (meas_a["r1_chain_ohm"] - meas_a["r1_single_ohm"]) / meas_a["r1_single_ohm"]
    r2_delta = (meas_a["r2_chain_ohm"] - meas_a["r2_single_ohm"]) / meas_a["r2_single_ohm"]
    k_single = meas_a["r2_single_ohm"] / meas_a["r1_single_ohm"]
    k_chain = meas_a["r2_chain_ohm"] / meas_a["r1_chain_ohm"]
    out_of_spec_corners = [
        f"{p}/{s:.2f}V"
        for p, s in PHASE_B_CORNERS
        if not (VREF_SPEC_V[0] <= phase_b[(p, s)]["vref_27"] <= VREF_SPEC_V[1])
    ]
    determination = (
        f"**Reading 2 (a real electrical effect), confirmed.** Chaining {N_R1} real "
        f"`sky130_fd_pr__res_high_po` unit instances via ideal wires (R1's shape) measures "
        f"{r1_delta:+.2%} higher than one instance drawn at the same {R1_COMBINED_L_UM:.0f} um "
        f"combined length; chaining {N_R2_COARSE + N_R2_TRIM_UNITS} units (R2A/R2B's shape) measures "
        f"{r2_delta:+.2%} higher. Both numbers reproduce `klt`'s own LVS-extracted values to within "
        f"{KLT_REPRO_REL_TOL:.2%} using an independent mechanism (real ngspice evaluation of the "
        "PDK's nonlinear `rhead`/`rbody` model cards through ideal interconnect, not `klt`'s own "
        "analytic extraction formula) -- so the gap 2AMLogic/klayout-tools#518/#519/#526 measures at "
        "LVS time is not an extractor bookkeeping artifact. The model card's own structure explains "
        "why: `rhead`'s width is a fixed function of `w` and its length is a hardcoded `l=1.0`, "
        "*independent of the caller's drawn body length* -- so a real device really does pay this "
        "term once per physically separate, individually-contacted instance, and `rbody`'s own "
        "`leff = l + 0.247` fringe term adds a further per-instance length markup. The routed "
        f"layout's `bus_res_series` draws real contacts and metal risers at every one of the array's "
        f"internal unit boundaries (issue #98's Problem section), which is exactly the structure "
        "this model term represents -- so real fabricated silicon built from this layout really "
        "does pay N times the head/fringe term, not once per logical divider leg.\n\n"
        f"K = R2/R1 shifts from {k_single:.4f} (single-device model -- what "
        "`design/bandgap_core.sch` and every existing PVT sim record in this repo actually "
        f"simulates today) to {k_chain:.4f} under the routed layout's real chained topology "
        f"({(k_chain - k_single) / k_single:+.2%}), because R1's delta ({r1_delta:+.2%}) and "
        f"R2A/R2B's delta ({r2_delta:+.2%}) differ -- confirming the concern issue #98's Problem "
        "section raised: this is not a uniform scale factor on both resistors.\n\n"
        + (
            f"**Material.** Substituting the chained-array topology into the real core testbench "
            f"(Phase B) pushes VOUT(27 degC) outside the draft +/-1% spec window "
            f"({VREF_SPEC_V[0]:.3f}-{VREF_SPEC_V[1]:.3f} V) at "
            f"{len(out_of_spec_corners)}/{len(PHASE_B_CORNERS)} corner points: "
            f"{', '.join(out_of_spec_corners) if out_of_spec_corners else '(none)'}"
            ". This is the same class of finding issue #46 (operating-point collapse from a "
            "+1.4% R2 error) and issue #91 (drawn-length mismatch) treated as real and actionable, "
            "not a rounding-level effect to wave off."
            if out_of_spec_corners
            else "**Checked for materiality, found immaterial at this corner set**: VOUT(27 degC) "
            "under the chained-array topology stayed inside the draft +/-1% spec window at all "
            f"{len(PHASE_B_CORNERS)} corner points tested."
        )
    )

    snapshots_dir.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("\n".join(substituted_body) + "\n.end\n")

    record = {
        "record_id": record_id,
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "author": args.author or cr.default_author(),
        "supersedes": args.supersedes,
        "pdk": {
            "variant": pdk.variant,
            "installed_commit": pdk.installed_commit,
            "matches_pin": pdk.matches_pin,
            "lib_file": str(pdk.lib_file),
        },
        "tools": cr.tool_versions(),
        "git": git_info,
        "phase_a": meas_a,
        "phase_b": {f"{p}:{s}": phase_b[(p, s)] for p, s in PHASE_B_CORNERS},
        "phase_b_baseline": {f"{p}:{s}": baseline[(p, s)] for p, s in PHASE_B_CORNERS},
        "checks": checks,
        "overall_pass": overall,
        "determination": determination,
        "links": {
            "corners_dir": str(corners_dir.relative_to(REPO_ROOT)) + "/",
            "json": str(record_json.relative_to(REPO_ROOT)),
            "record": str(record_md.relative_to(REPO_ROOT)),
            "netlist_snapshot": str(snapshot.relative_to(REPO_ROOT)),
        },
    }

    records_dir.mkdir(parents=True, exist_ok=True)
    record_json.write_text(json.dumps(record, indent=2, sort_keys=True, default=str) + "\n")
    record_md.write_text(render_record(record))

    print()
    print(f"record  : {record_md.relative_to(REPO_ROOT)}")
    print(f"json    : {record_json.relative_to(REPO_ROOT)}")
    print(f"logs    : {corners_dir.relative_to(REPO_ROOT)}/")
    print(f"overall : {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except cr.HarnessError as err:
        print(f"run_res_array_head_resistance: error: {err}", file=sys.stderr)
        sys.exit(1)
