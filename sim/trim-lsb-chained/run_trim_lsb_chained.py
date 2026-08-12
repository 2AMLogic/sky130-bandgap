#!/usr/bin/env python3
"""Re-derive DR-002's three trim criteria (monotonic-in-code, downward span,
LSB) against the routed layout's REAL chained fine-trim topology, at the
ADOPTED `n_r1=7`/`n_r2=50` sizing (issue #99 / PR #105) -- issue #106.

Why this is needed (and why it is a fresh derivation, not a re-citation):
issue #99's own AC3 re-check of DR-002's downward trim range
(`sim/res-array-resize/records/20260805-204809-2c83c7a.md`) spot-checked only
codes 0/-8/-16 and reported the SPAN and MONOTONICITY criteria explicitly,
but never computed the third DR-002 criterion -- the per-code LSB, gated at
`<= 3.000 mV/code` (25% of the +/-1% window's 12 mV half-width, the exact
bound `sim/trim-range-monotonicity/run_trim_sweep.py`'s own
`lsb_comfortable[*]` check uses) -- against the CHAINED topology. A prior
issue (#106's own now-corrected original text) computed a 3.655-3.682 mV/code
LSB and flagged a DR-002 violation, but did so against an ABANDONED
`n_r1=6`/`n_r2=42` sizing that never merged (losing side of a concurrent-
Builder race on #99; see #106's Curator correction). This script re-derives
the same three criteria against the topology that DOES matter -- the
ADOPTED `n_r1=7`/`n_r2=50` sizing PR #105 shipped -- using the identical
per-code LSB formula `run_trim_sweep.py` established:
`lsb = (vref_27(code=0) - vref_27(code=-16)) / 16`.

Why a bespoke script (same reasoning as `sim/res-array-resize/
run_res_array_resize.py`, whose chained-array substitution this script
reuses conceptually): the claim needs the SAME netlisted core body -- amp,
PNPs, PMOS mirrors, startup node -- re-run with a structural edit to the
R2A/R2B fine-trim ladder, namely chaining separately-contacted unit
instances (the routed layout's own `bus_res_series` decomposition) rather
than one lumped `res_high_po` device. That is a body substitution, not a
`deck.params` override, so the generic corner-runner manifest path cannot
express it (the same finding `sim/trim-range-monotonicity/
run_trim_sweep.py`'s own module docstring documents for the single-device
case).

THIS SCRIPT ADDS ONE AXIS `sim/res-array-resize/run_res_array_resize.py`
did not have: the fine-trim UNIT LENGTH (`r_lseg_trim`, drawn today as
`R_LSEG_TRIM_UM=1.0` um in `layout/bin/gen_bandgap_routed.py` and
`design/bandgap_core.sch`'s `.param r_lseg_trim=1`). It runs TWO configs at
the same adopted sizing and corner/code matrix:

  * `shipped`  -- `r_lseg_trim=1.0` um, the topology drawn today. Expected
    (per the prior issue's now-corrected-baseline prior, and per DR-003's
    finding that the fine chain's per-instance head-resistance term is
    unchanged between the two competing #99 resizes) to still show a real,
    if smaller, LSB violation.
  * `revised`  -- `r_lseg_trim=0.5` um, the fix this record proposes (a DR-002
    revision, see the module-level `FIX_RATIONALE` below): halving the fine
    unit's drawn length halves its `rbody` fringe contribution while the
    per-instance `rhead` term (the dominant piece, ~379.7 of the ~704.5
    ohm/code total -- see DR-003 / `sim/res-array-head-resistance/`) is
    UNCHANGED, since `rhead`'s length is a hardcoded PDK-model constant
    independent of the caller's drawn body length. The fine ladder's unit
    COUNT (`N_R2_FINE_UNITS=20`, and therefore DR-002's certified 0..-16 code
    range) is left unchanged -- only the per-unit length shrinks, so the
    fine ladder's own drawn extent halves (20 um -> 10 um) and the coarse
    portion lengthens by the same amount to hold the untrimmed leg length
    (`5*n_r2` um) fixed. This is a pure re-partition of the SAME total R2A/R2B
    length between coarse and fine segments, not a resize of `n_r1`/`n_r2`
    (issue #99's lever) or of the certified code range (DR-002's other
    lever) -- see `r2_segments_um()` below for the exact closed form.

Chained-array electrical model (same klt/PDK-model-card constants
`sim/res-array-resize/run_res_array_resize.py`'s `analytic_resistances()`
reproduces to 0.0000% against real ngspice and against `klt`'s own LVS
extraction -- see `sim/res-array-head-resistance/`): each unit instance
contributes `HEAD_OHM` (fixed, per-instance, independent of drawn length)
plus `BODY_OHM_PER_UM * length_um` (the `rbody` fringe/sheet term).

Note on tool availability: like the two records this one extends, this run
environment has `ngspice` but not `xschem`, so the core body is read from
the already-checked-in netlist snapshot `sim/trim-range-monotonicity/
netlist-snapshots/20260803-170704-b976d0f.spice` (verified byte-identical on
the `.param` lines that matter) rather than re-netlisted from
`tb_vref_tc.sch`. The chained resistor topology is injected by this script
directly, so the snapshot's own `.param n_r1`/`n_r2`/`n_r2_trim`/
`r_lseg_trim` values never enter the resistor legs -- only the surrounding
core body (PNPs/amp/mirrors) is reused from it.

Layout-propagation scope note: this record verifies the FIX at the sim
(chained-topology) level only, per this issue's acceptance criteria and the
one-lever-per-increment discipline DR-003/#99 already established (schematic
+ sim first, `layout/bin/gen_bandgap_routed.py` re-transcription + klayout
DRC/LVS re-verification as a separate follow-up issue -- the same split #99
used for #107/#108). `klayout`'s python extraction/DRC backend is not
importable in this run environment (`python3 -c "import klayout"` fails),
so this record does not attempt to regenerate or re-verify the drawn GDS.

Usage
-----
    sim/trim-lsb-chained/run_trim_lsb_chained.py                 # full run
    sim/trim-lsb-chained/run_trim_lsb_chained.py --dry-run        # print plan

Exit status: 0 if every check passed, 2 if a record was written but a check
failed, 1 on a harness/setup error (no record written) -- same convention as
`corner-run.py` and the two records this one extends.
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
BUILD_DIR = SIM_DIR / "build" / "trim-lsb-chained"

sys.path.insert(0, str(SIM_DIR / "bin"))
from sim_common import (  # noqa: E402
    chain_lines,
    load_corner_run,
    parse_measurements,
    run_ngspice,
    write_log,
)

# Reuse the same already-checked-in core-body snapshot the head-resistance
# and res-array-resize records reuse (xschem unavailable in this run
# environment). Reference-only -- never written by this script.
BASE_SNAPSHOT = (
    SIM_DIR / "trim-range-monotonicity" / "netlist-snapshots" / "20260803-170704-b976d0f.spice"
)
WRAPPED_SCHEMATIC = "sim/output-voltage-tc/testbench/tb_vref_tc.sch"


cr = load_corner_run()

SLUG = "trim-lsb-chained"
TITLE = (
    "Re-derive DR-002's monotonic/span/LSB trim criteria against the chained "
    "fine-trim topology at the adopted n_r1=7/n_r2=50 sizing, and verify a "
    "fine-unit-length fix if the LSB comfort bound fails (issue #106)"
)

# --------------------------------------------------------------------------
# Layout decomposition constants -- transcribed from
# layout/bin/gen_bandgap_routed.py (N_R1 / N_R2_COARSE / N_R2_TRIM_UNITS /
# R_LSEG_UM / R_LSEG_TRIM_UM) and design/bandgap_core.sch's CORE_PARAMS, same
# source `sim/res-array-resize/run_res_array_resize.py` transcribes from.
# --------------------------------------------------------------------------
R_W_UM = 1.0
R_LSEG_UM = 5.0  # coarse unit length (unchanged by this issue)
N_R2_FINE_UNITS = 20  # fixed fine-ladder unit COUNT (unchanged by this issue;
# drawn 0..-20, DR-002 certifies 0..-16)

# klt / PDK-model-card chained-array constants (reproduced to 0.0000% against
# real ngspice and klt's own LVS extraction -- sim/res-array-head-resistance/,
# sim/res-array-resize/run_res_array_resize.py's analytic_resistances()).
HEAD_OHM = 379.705147  # rhead: fixed per-instance term, independent of drawn L
BODY_OHM_PER_UM = 324.827244  # rbody: sheet + fringe term, scales with drawn L

# --------------------------------------------------------------------------
# THE ADOPTED SIZING (issue #99 / PR #105 / DR-003 closure) -- NOT the
# abandoned n_r1=6/n_r2=42 alternative the original #106 text cited (see
# #106's Curator correction). This is fixed for both configs below; this
# issue's lever is the fine unit LENGTH, not n_r1/n_r2.
# --------------------------------------------------------------------------
N_R1 = 7
N_R2 = 50

# --------------------------------------------------------------------------
# Configs: the fine-trim unit length (r_lseg_trim) axis this script adds.
# Both keep N_R2_FINE_UNITS=20 fine units and the SAME untrimmed leg length
# (5*n_r2 um) -- only the coarse/fine split of that fixed length moves, via
# r2_segments_um()'s closed form below.
# --------------------------------------------------------------------------
CONFIGS = (
    ("shipped", 1.0),  # design/bandgap_core.sch's r_lseg_trim=1 as of PR #110
    ("revised", 0.5),  # this record's proposed DR-002 revision
)

FIX_RATIONALE = (
    "Halving the fine unit's drawn length from 1.0 to 0.5 um roughly halves "
    "its `rbody` (sheet+fringe) contribution per code while leaving the "
    "per-instance `rhead` term -- the DOMINANT piece of the per-code step, "
    "379.705147 of the shipped config's 704.532391 ohm/code total -- "
    "UNCHANGED (the PDK model card's own rhead length is a hardcoded "
    "constant, independent of the caller's drawn body length; see DR-003 / "
    "sim/res-array-head-resistance/). The fine ladder's unit COUNT (20) and "
    "therefore DR-002's certified 0..-16 code range are unchanged -- only "
    "the coarse/fine split of the fixed 5*n_r2 um leg length moves."
)

# --------------------------------------------------------------------------
# Corner matrix -- identical (process, supply) set and codes to
# sim/trim-range-monotonicity's NEGATIVE_CORNERS / NEGATIVE_CODES and issue
# #99's AC3 re-check.
# --------------------------------------------------------------------------
CORNERS = (
    ("tt", 3.30),
    ("ss", 3.30),
    ("ff", 2.97),
    ("sf", 2.97),
    ("fs", 2.97),
)
CODES = (0, -8, -16)

VREF_SANITY_V = (1.10, 1.30)  # regulation-loss guard (collapse jumps VOUT ~2.85 V)
SPEC_WINDOW_HALF_V = 0.012  # +/-1% of 1.20 V -- same bound DR-002/run_trim_sweep.py use
LSB_COMFORTABLE_FRACTION = 0.25  # DR-002: LSB must be <= 25% of the window half-width
WORST_CASE_3SIGMA_V = 0.015620  # sim/monte-carlo-untrimmed 20260803-142259-544cc5e, 125 degC
SPAN_MARGIN_TARGET = 1.5  # DR-002 / run_trim_sweep.py's own downward-span margin


# --------------------------------------------------------------------------
# chained-array geometry
# --------------------------------------------------------------------------


def r2_segments_um(n_r2: int, trim_code: int, trim_unit_um: float) -> list[float]:
    """R2A/R2B leg unit lengths at the adopted sizing, a DOWNWARD trim code,
    and a candidate fine-unit length.

    coarse_units * R_LSEG_UM  +  N_R2_FINE_UNITS * trim_unit_um  ==  5*n_r2
    (the untrimmed leg length stays fixed; only the coarse/fine split of it
    moves with trim_unit_um). trim_code <= 0; code 0 keeps all
    N_R2_FINE_UNITS fine units in circuit (= the untrimmed length).
    """
    if trim_code > 0:
        raise cr.HarnessError(f"trim_code must be <= 0 (downward-only), got {trim_code}")
    fine_um_at_code0 = N_R2_FINE_UNITS * trim_unit_um
    coarse_um = R_LSEG_UM * n_r2 - fine_um_at_code0
    if coarse_um <= 0 or (coarse_um % R_LSEG_UM) != 0:
        raise cr.HarnessError(
            f"trim_unit_um={trim_unit_um} does not divide the fixed {R_LSEG_UM * n_r2:.1f} um "
            f"leg length into an integer number of {R_LSEG_UM} um coarse units (coarse_um="
            f"{coarse_um})"
        )
    coarse_units = int(round(coarse_um / R_LSEG_UM))
    active_fine = N_R2_FINE_UNITS + trim_code
    if active_fine < 0:
        raise cr.HarnessError(f"invalid decomposition at n_r2={n_r2}, trim={trim_code}")
    return [R_LSEG_UM] * coarse_units + [trim_unit_um] * active_fine


def r1_segments_um(n_r1: int) -> list[float]:
    return [R_LSEG_UM] * n_r1


def analytic_step_ohm(trim_unit_um: float) -> float:
    """The chained model's per-code resistance step (removing one active fine
    unit): HEAD_OHM (fixed) + BODY_OHM_PER_UM * trim_unit_um. Cross-reference
    only -- the ngspice sweep below is the ground truth."""
    return HEAD_OHM + BODY_OHM_PER_UM * trim_unit_um


# The exact single-device lines this script replaces (verified present exactly
# once each in BASE_SNAPSHOT before substitution) -- identical target lines to
# sim/res-array-resize/run_res_array_resize.py's TARGET_LINES.
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

# Core-body .param lines that MUST still match (independent of this issue's
# fine-unit-length axis).
EXPECTED_PARAMS = {
    ".param n_pnp_ctat=8",
    ".param n_pnp_ptat=8",
    ".param r_w=1",
    ".param r_lseg=5",
    ".param m_out=2",
    ".param m_ampbias=2",
}


def load_base_body() -> list[str]:
    if not BASE_SNAPSHOT.is_file():
        raise cr.HarnessError(f"missing base netlist snapshot: {BASE_SNAPSHOT}")
    text = BASE_SNAPSHOT.read_text()
    lines = [ln for ln in text.splitlines() if ln.strip().lower() != ".end"]
    present = {ln.strip() for ln in lines if ln.strip().startswith(".param ")}
    missing = EXPECTED_PARAMS - present
    if missing:
        raise cr.HarnessError(
            f"base snapshot {BASE_SNAPSHOT} is missing expected core .param line(s) "
            f"{sorted(missing)} -- the reused core body may have drifted"
        )
    return lines


def substitute_arrays(body: list[str], n_r1: int, n_r2: int, trim_code: int, trim_unit_um: float) -> list[str]:
    r1_seg = r1_segments_um(n_r1)
    r2_seg = r2_segments_um(n_r2, trim_code, trim_unit_um)
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


def build_deck(pdk, process: str, supply_v: float, body: list[str]) -> str:
    head = [
        f"* {SLUG} deck (process={process}, supply={supply_v}) -- "
        f"generated by sim/{SLUG}/run_trim_lsb_chained.py, do not edit",
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


@dataclass(frozen=True)
class Point:
    config: str
    trim_unit_um: float
    process: str
    supply_v: float
    trim_code: int

    @property
    def name(self) -> str:
        sign = "p" if self.trim_code >= 0 else "n"
        return f"{self.config}_{self.process}_trim{sign}{abs(self.trim_code)}_{self.supply_v:.2f}v"


def build_points() -> list[Point]:
    points = []
    for config, trim_unit_um in CONFIGS:
        for process, supply in CORNERS:
            for code in CODES:
                points.append(Point(config, trim_unit_um, process, supply, code))
    return points


def run_all(base_body, pdk, run_dir, corners_dir, record_id, timeout) -> dict[Point, dict]:
    results: dict[Point, dict] = {}
    points = build_points()
    for i, point in enumerate(points, start=1):
        body = substitute_arrays(base_body, N_R1, N_R2, point.trim_code, point.trim_unit_um)
        deck = build_deck(pdk, point.process, point.supply_v, body)
        stamp = datetime.now(timezone.utc)
        raw, rc, timed_out = run_ngspice(run_dir, point.name, deck, timeout)
        if corners_dir is not None:
            write_log(corners_dir, point.name, record_id, pdk, stamp, deck, raw, rc, timed_out)
        meas = parse_measurements(raw)
        print(
            f"[{i:>2}/{len(points)}] {point.name:<32} rc={rc}{' TIMEOUT' if timed_out else ''} "
            f"vref_27={meas.get('vref_27')} tc_ppm={meas.get('tc_ppm')}"
        )
        if timed_out or rc != 0 or "vref_27" not in meas:
            raise cr.HarnessError(
                f"point {point.name} did not produce usable measurements "
                f"(rc={rc}, timed_out={timed_out}); no record written"
            )
        results[point] = meas
    return results


# --------------------------------------------------------------------------
# checks (DR-002's three criteria, exact formulas from
# sim/trim-range-monotonicity/run_trim_sweep.py's evaluate())
# --------------------------------------------------------------------------


def evaluate(results: dict[Point, dict]) -> list[dict]:
    checks: list[dict] = []

    def add(name, ok, detail):
        checks.append({"name": name, "pass": bool(ok), "detail": detail})

    def get(config, process, supply, code):
        return results[Point(config, dict(CONFIGS)[config], process, supply, code)]

    for config, trim_unit_um in CONFIGS:
        for process, supply in CORNERS:
            cid = f"{config}_{process}_{supply:.2f}v"

            # sanity / collapse-free at every sampled code
            all_reg = all(
                VREF_SANITY_V[0] <= get(config, process, supply, t)["vref_max"] <= VREF_SANITY_V[1]
                for t in CODES
            )
            add(
                f"collapse_free[{cid}]",
                all_reg,
                f"every downward code {CODES} stays on the operating branch (vref_max in "
                f"{VREF_SANITY_V}) at r_lseg_trim={trim_unit_um} um",
            )

            # monotonic in code (0, -8, -16 strictly increasing toward 0)
            ordered = sorted(CODES)
            series = [get(config, process, supply, t)["vref_27"] for t in ordered]
            strictly_increasing = all(b > a for a, b in zip(series, series[1:]))
            add(
                f"monotonic[{cid}]",
                strictly_increasing,
                f"vref_27 vs trim_code {list(zip(ordered, (round(v, 6) for v in series)))} "
                "(must strictly increase from -16 toward 0)",
            )

            # downward span >= 1.5x worst-case 3sigma MC spread
            v_hi = get(config, process, supply, 0)["vref_27"]
            v_lo = get(config, process, supply, -16)["vref_27"]
            span_v = v_hi - v_lo
            span_ok = span_v >= SPAN_MARGIN_TARGET * WORST_CASE_3SIGMA_V
            add(
                f"range_covers_mc_spread[{cid}]",
                span_ok,
                f"downward trim span (code 0..-16) = {span_v * 1000:.3f} mV, required >= "
                f"{SPAN_MARGIN_TARGET} x {WORST_CASE_3SIGMA_V * 1000:.3f} mV = "
                f"{SPAN_MARGIN_TARGET * WORST_CASE_3SIGMA_V * 1000:.3f} mV",
            )

            # LSB (average per-code step over 0..-16) <= 25% of window half-width
            lsb_v = span_v / 16.0
            lsb_ok = lsb_v <= LSB_COMFORTABLE_FRACTION * SPEC_WINDOW_HALF_V
            add(
                f"lsb_comfortable[{cid}]",
                lsb_ok,
                f"LSB={lsb_v * 1000:.4f} mV/code, required <= "
                f"{LSB_COMFORTABLE_FRACTION:.0%} of window half-width "
                f"({LSB_COMFORTABLE_FRACTION * SPEC_WINDOW_HALF_V * 1000:.3f} mV) "
                f"at r_lseg_trim={trim_unit_um} um",
            )

    return checks


# --------------------------------------------------------------------------
# record rendering
# --------------------------------------------------------------------------


def render_record(r: dict) -> str:
    L: list[str] = []

    def add(line: str = ""):
        L.append(line)

    add(f"# Record {r['record_id']}")
    add("")
    add(f"- **Record ID**: {r['record_id']}")
    add(f"- **Experiment**: `{SLUG}` — {TITLE}")
    add(
        "- **Claim**: issue #106 -- re-derive (not re-cite) DR-002's three trim "
        "criteria (monotonic-in-code, downward span, LSB) against the routed "
        "layout's real chained fine-trim topology, at the ADOPTED "
        f"`n_r1={N_R1}`/`n_r2={N_R2}` sizing (issue #99 / PR #105 -- NOT the "
        "abandoned `n_r1=6`/`n_r2=42` alternative the original issue text cited, "
        "see #106's Curator correction). Runs two `r_lseg_trim` (fine-unit-length) "
        "configs at the same sizing/corner/code matrix: `shipped` (1.0 um, the "
        "topology `design/bandgap_core.sch` and the routed layout drew before "
        "this record) and `revised` (0.5 um, this record's proposed DR-002 fix)."
    )
    add(
        "- **Netlist provenance**: the core body (amp/PNPs/PMOS mirrors) is reused "
        f"from `{BASE_SNAPSHOT.relative_to(REPO_ROOT)}` (the same already-checked-in "
        "snapshot the head-resistance and res-array-resize records reuse; xschem is "
        "unavailable in this run environment). The R2A/R2B fine-trim ladder is "
        "replaced with chained `sky130_fd_pr__res_high_po` unit-instance arrays at "
        "the routed layout's own decomposition (`layout/bin/gen_bandgap_routed.py`), "
        "parameterized on the candidate fine-unit length -- so the snapshot's own "
        "`.param n_r1`/`n_r2`/`n_r2_trim`/`r_lseg_trim` values do not enter the "
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
        + f" x trim codes {CODES} x 2 fine-unit-length configs, each with a continuous "
        "in-deck `dc temp -40 125 11` box-method sweep (16 points) -- identical corner "
        "set and code sampling to `sim/trim-range-monotonicity/` and issue #99's AC3."
    )
    add("- **Statistical convention**: N/A (deterministic sizing/topology sweep, not a distribution claim).")
    add("")

    add("## Per-code resistance step (analytic cross-reference)")
    add("")
    add("| config | r_lseg_trim (um) | rhead (ohm, fixed) | rbody (ohm) | step (ohm/code) |")
    add("|---|---|---|---|---|")
    for config, trim_unit_um in CONFIGS:
        body_ohm = BODY_OHM_PER_UM * trim_unit_um
        add(
            f"| {config} | {trim_unit_um:.2f} | {HEAD_OHM:.3f} | {body_ohm:.3f} | "
            f"{HEAD_OHM + body_ohm:.3f} |"
        )
    add("")
    add(
        "The `rhead` term is fixed per removed unit instance regardless of `r_lseg_trim` "
        "(PDK model card, DR-003); only `rbody` scales with the drawn fine-unit length. "
        "This is the analytic model only -- the ngspice sweep below is the ground truth "
        "the checks are gated on."
    )
    add("")

    for config, trim_unit_um in CONFIGS:
        add(f"## Config `{config}` (r_lseg_trim={trim_unit_um} um) -- per-corner, per-code VREF")
        add("")
        add("| process | supply (V) | trim code | VREF(27 °C) (V) | VREF max (V) | TC (ppm/°C) | regulating? |")
        add("|---|---|---|---|---|---|---|")
        for process, supply in CORNERS:
            for t in CODES:
                m = r["results"][f"{config}:{process}:{supply}:{t}"]
                reg = "yes" if VREF_SANITY_V[0] <= m["vref_max"] <= VREF_SANITY_V[1] else "**NO — collapsed**"
                add(
                    f"| {process} | {supply:.2f} | {t:+d} | {m['vref_27']:.6f} | {m['vref_max']:.6f} | "
                    f"{m['tc_ppm']:.3f} | {reg} |"
                )
        add("")
        add(f"### Config `{config}` -- DR-002 criteria per corner")
        add("")
        add("| process | supply (V) | span 0..-16 (mV) | monotonic? | span >= 1.5x3sigma? | LSB (mV/code) | LSB <= 3.000? |")
        add("|---|---|---|---|---|---|---|")
        for process, supply in CORNERS:
            v_hi = r["results"][f"{config}:{process}:{supply}:0"]["vref_27"]
            v_lo = r["results"][f"{config}:{process}:{supply}:-16"]["vref_27"]
            span_mv = (v_hi - v_lo) * 1000
            lsb_mv = span_mv / 16.0
            cid = f"{config}_{process}_{supply:.2f}v"
            mono = "yes" if next(c for c in r["checks"] if c["name"] == f"monotonic[{cid}]")["pass"] else "**NO**"
            span_ok = "yes" if next(c for c in r["checks"] if c["name"] == f"range_covers_mc_spread[{cid}]")["pass"] else "**NO**"
            lsb_ok = "yes" if next(c for c in r["checks"] if c["name"] == f"lsb_comfortable[{cid}]")["pass"] else "**NO**"
            add(
                f"| {process} | {supply:.2f} | {span_mv:.3f} | {mono} | {span_ok} | {lsb_mv:.4f} | {lsb_ok} |"
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

    add("## Fix rationale")
    add("")
    add(FIX_RATIONALE)
    add("")

    add("## Determination")
    add("")
    add(r["determination"])
    add("")

    add("- **Links**:")
    add(f"  - wrapped schematic: `{WRAPPED_SCHEMATIC}`")
    add(f"  - reused core body snapshot: `{BASE_SNAPSHOT.relative_to(REPO_ROOT)}`")
    add(
        "  - predecessor (chained-array materiality): "
        "`sim/res-array-head-resistance/records/20260805-113409-6caa9f8.md`"
    )
    add(
        "  - predecessor (adopted sizing / AC3 span+monotonic spot-check): "
        "`sim/res-array-resize/records/20260805-204809-2c83c7a.md`"
    )
    add(
        "  - predecessor (DR-002's own LSB formula / criteria): "
        "`sim/trim-range-monotonicity/records/20260803-170704-b976d0f.md`"
    )
    add(f"  - runner: `sim/{SLUG}/run_trim_lsb_chained.py`")
    add(f"  - logs: `{r['links']['corners_dir']}`")
    add(f"  - record_json: `{r['links']['json']}`")
    add("  - decision record: `spec/decision-records/DR-002-trim-network-scoping.md`")
    add(f"- **Timestamp / author**: {r['timestamp']}, {r['author']}")
    add(f"- **Supersedes**: {r['supersedes'] or '(none — first record for this claim)'}")
    add("")
    add(
        f"Written by `sim/{SLUG}/run_trim_lsb_chained.py`. Append-only: never edit this file — "
        "a correction is a new record with a `Supersedes` field (see `sim/README.md`)."
    )
    add("")
    return "\n".join(L)


def build_determination(results: dict[Point, dict], checks: list[dict]) -> str:
    def fails_for(config: str) -> list[str]:
        return [
            c["name"]
            for c in checks
            if not c["pass"] and c["name"].split("[", 1)[1].startswith(f"{config}_")
        ]

    seg = []
    seg.append(
        f"**Re-derived (not re-cited) against the ADOPTED sizing.** All three DR-002 "
        f"criteria are re-measured against the routed layout's real chained fine-trim "
        f"topology at `n_r1={N_R1}`, `n_r2={N_R2}` (issue #99 / PR #105) -- the sizing "
        "that actually merged, not the abandoned `n_r1=6`/`n_r2=42` alternative the "
        "original issue text (before Curator correction) cited."
    )

    shipped_fails = fails_for("shipped")
    revised_fails = fails_for("revised")

    if shipped_fails:
        lsb_fails = [n for n in shipped_fails if n.startswith("lsb_comfortable")]
        other_fails = [n for n in shipped_fails if not n.startswith("lsb_comfortable")]
        seg.append(
            "**`shipped` config (r_lseg_trim=1.0 um, what is drawn today): DR-002's "
            f"LSB comfort bound FAILS at {len(lsb_fails)}/{len(CORNERS)} corners"
            + (f" ({', '.join(n.split('[')[1].rstrip(']') for n in lsb_fails)})" if lsb_fails else "")
            + ". Monotonic-in-code and downward-span PASS at every corner (matching "
            "issue #99's own AC3 spot-check), confirming the third DR-002 criterion -- "
            "not previously derived against this adopted sizing -- is the one that does "
            "not hold. This is a smaller violation than the abandoned baseline's "
            "3.655-3.682 mV/code (the resized sizing's own trim span is smaller because "
            "the untrimmed operating point sits closer to spec center), but it is a real, "
            "measured violation of the same <=3.000 mV/code comfort bound, not merely a "
            "prior's untested assumption."
            + (f" Unexpected additional failures: {other_fails}." if other_fails else "")
        )
    else:
        seg.append(
            "**`shipped` config (r_lseg_trim=1.0 um, what is drawn today): all three "
            "DR-002 criteria PASS at every corner** -- contrary to the prior (abandoned-"
            "baseline-derived) expectation of an LSB violation."
        )

    if revised_fails:
        seg.append(
            f"**`revised` config (r_lseg_trim=0.5 um) does NOT resolve every check: "
            f"{revised_fails}.** This candidate fix needs another iteration before it "
            "can be adopted."
        )
    else:
        seg.append(
            "**`revised` config (r_lseg_trim=0.5 um, this record's proposed fix): all "
            "three DR-002 criteria PASS at every corner**, including the LSB comfort "
            "bound the shipped config fails. Halving the fine unit's drawn length shifts "
            "the per-code step from the shipped config's fixed-`rhead`-plus-1.0um-`rbody` "
            "total down to fixed-`rhead`-plus-0.5um-`rbody` (see the analytic "
            "cross-reference table), which is enough margin at every corner (worst "
            "corner's LSB stays comfortably under the 3.000 mV/code bound -- see the "
            "per-corner checks)."
        )

    if not shipped_fails and not revised_fails:
        seg.append(
            "**No DR-002 revision is needed.** The adopted `n_r1=7`/`n_r2=50` sizing's "
            "trim network already meets all three criteria against the real chained "
            "topology; this record's `revised` config is reported for completeness "
            "(a candidate the project can adopt for additional margin) but is not "
            "required by this issue's acceptance criteria."
        )
    elif shipped_fails and not revised_fails:
        seg.append(
            "**Recommendation: adopt r_lseg_trim=0.5 um as a DR-002 revision.** "
            "`design/bandgap_core.sch`'s `.param r_lseg_trim=1` should move to `0.5`, "
            "and DR-002's own 'Range and resolution' section should be revised to record "
            "the new per-code LSB against the chained topology. This changes the fine "
            "unit's DRAWN length, so `layout/bin/gen_bandgap_routed.py`'s "
            "`R_LSEG_TRIM_UM`/`SCH_R_LSEG_TRIM_UM` (and the coarse-count constant that "
            "holds the leg length fixed) need re-transcribing and the routed cell needs "
            "re-verification through klayout DRC/LVS before the fabricated part matches "
            "this decision -- klayout's extraction backend is not importable in this run "
            "environment (`python3 -c \"import klayout\"` fails), so that step is a "
            "follow-up issue, per the same one-lever-per-increment split issue #99 used "
            "for #107/#108 (schematic+sim first, layout regen+DRC/LVS as the next "
            "increment)."
        )

    return "\n\n".join(seg)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


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

    base_body = load_base_body()
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

    print(f"experiment : {SLUG}")
    print(f"record id  : {record_id}")
    print(f"sizing     : n_r1={N_R1} n_r2={N_R2} (adopted, issue #99 / PR #105)")
    print(f"configs    : {CONFIGS}")

    if dry_run:
        print("(dry run: nothing written under sim/)")
        sample = substitute_arrays(base_body, N_R1, N_R2, 0, CONFIGS[0][1])
        print(build_deck(pdk, *CORNERS[0], sample))
        return 0

    run_dir = BUILD_DIR / record_id
    results = run_all(base_body, pdk, run_dir, corners_dir, record_id, timeout)
    checks = evaluate(results)
    overall = all(c["pass"] for c in checks)
    determination = build_determination(results, checks)

    record = {
        "record_id": record_id,
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "author": author or cr.default_author(),
        "supersedes": supersedes,
        "sizing": {"n_r1": N_R1, "n_r2": N_R2},
        "configs": {c: u for c, u in CONFIGS},
        "pdk": {
            "variant": pdk.variant,
            "installed_commit": pdk.installed_commit,
            "matches_pin": pdk.matches_pin,
            "lib_file": str(pdk.lib_file),
        },
        "tools": cr.tool_versions(),
        "git": git_info,
        "results": {
            f"{p.config}:{p.process}:{p.supply_v}:{p.trim_code}": m for p, m in results.items()
        },
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
    p.add_argument("--author", default="")
    p.add_argument("--supersedes", default="")
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--allow-pdk-mismatch", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    return verify(args.timeout, args.author, args.supersedes, args.allow_pdk_mismatch, args.dry_run)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except cr.HarnessError as err:
        print(f"run_trim_lsb_chained: error: {err}", file=sys.stderr)
        sys.exit(1)
