#!/usr/bin/env python3
"""Monte Carlo offset/mismatch runner for the bandgap error amplifier (issue #9).

Why this is a bespoke script and not another `experiment.json` +
`sim/bin/corner-run.py` experiment: the corner runner drives exactly one
deterministic deck per PVT point and parses one scalar per measurement. An
offset *budget* is a claim about distributions -- the same deck resampled N
times at one process point -- which is a different axis than the PVT matrix.
`sim/pnp-mismatch/run_pnp_mismatch.py` established that split in this repo and
this script follows it, reusing `sim/bin/corner-run.py`'s PDK resolution, pin
enforcement, xschem netlisting, tool-version and git-provenance helpers by
import rather than re-implementing them.

What it measures, all on the same seed stream so the budget's arithmetic can be
checked instead of asserted (see `design/error-amp-offset-budget.md`):

    vos     amplifier input-referred random offset, in its own loop
    vout    total untrimmed reference spread (the number the three terms
            below have to add up to)
    dvbe8   sigma(dVBE) of the 8x PNP arrays the core actually ships
    veb8    absolute VEB of the 8x CTAT array (the unity-gain CTAT term)
    dvbe1   un-arrayed pair at 1 uA -- the ANCHOR against
            design/device-characterization-summary.md section 4
    rra/rrb R2-length and R1-length res_high_po -> the R2/R1 ratio term

Usage
-----
    sim/error-amp-offset-mc/run_amp_offset_mc.py                 # the full run
    sim/error-amp-offset-mc/run_amp_offset_mc.py --samples 20    # quick smoke
    sim/error-amp-offset-mc/run_amp_offset_mc.py --dry-run       # print the plan

Exit status: 0 every check passed, 2 a record was written but a check failed,
1 harness/setup error (no record written) -- same convention as corner-run.py.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO_ROOT = SIM_DIR.parent
SCHEMATIC = HERE / "testbench" / "tb_amp_offset_mc.sch"
SPICEINIT_FILE = SIM_DIR / "spiceinit"
BUILD_DIR = SIM_DIR / "build" / "amp-offset-mc"
LOOP_RECORDS = SIM_DIR / "error-amp-loop" / "records"

sys.path.insert(0, str(SIM_DIR / "bin"))
from sim_common import (  # noqa: E402
    load_corner_run,
    mean,
    mv,
    parse_samples,
    partition_by_window,
    render_log,
    render_pdk_tools_repo_state,
    render_record_id_experiment,
    run_ngspice,
    seed_stability_checks,
    stdev,
)

cr = load_corner_run()

# --------------------------------------------------------------------------
# experiment definition
# --------------------------------------------------------------------------

SLUG = "error-amp-offset-mc"
TITLE = "Error-amplifier offset budget by Monte Carlo: every term measured, and their sum checked"

MM_SECTION = "tt_mm"  # nominal process + MC_MM_SWITCH=1 (local mismatch on)
OFF_SECTION = "tt"  # nominal process + MC_MM_SWITCH=0 (control: sigma must be 0)
TEMPS_C = [-40.0, 27.0, 125.0]
SUPPLY_V = 3.3
N_SAMPLES = 300  # matches sim/pnp-mismatch, so the sigma figures are comparable
N_CONTROL = 30  # the control point is deterministic; N only has to be > 1
SEED_A = 20260803
SEED_B = 20260804

# Core parameters, read off design/bandgap_core.sch (n_r1=7, n_r2=54,
# r_lseg=5 um, r_w=1 um) with the res_high_po segment model R(L) = 380 + 325*L:
#   R1 = 380 + 325*35  = 11.755 kohm
#   R2 = 380 + 325*270 = 88.130 kohm
R1_OHM = 380.0 + 325.0 * 35.0
R2_OHM = 380.0 + 325.0 * 270.0
K_PTAT = R2_OHM / R1_OHM  # 7.497 -- NOT 54/7, the end resistance matters

# res_high_po local-mismatch coefficient from the PDK's own
# sw_mm_sky130_fd_pr__res_high_po_* term, as recorded in
# design/device-characterization-summary.md section 3: sigma(R)/R = 2.06 % / sqrt(W*L).
RES_MM_PCT_PER_SQRT_AREA = 2.06
R1_W_UM, R1_L_UM = 1.0, 35.0
R2_W_UM, R2_L_UM = 1.0, 270.0

# design/device-characterization-summary.md section 4, record
# 20260731-232801-ab27f82: the un-arrayed ratioed PNP pair at 1 uA / 27 degC.
# The `dvbe1` probe in this deck must reproduce both, or this harness is wrong.
ANCHOR_DVBE1_MEAN_V = 63.0e-3
ANCHOR_DVBE1_SIGMA_V = 0.480e-3
ANCHOR_MEAN_TOL_V = 1.5e-3
ANCHOR_SIGMA_BAND = (0.7, 1.4)

# A Monte Carlo sample only counts if the core actually came up. bandgap_core
# is bistable by construction (its amplifier's tail is mirrored from the same
# gate that supplies its branches) and has no startup circuit -- that is issue
# #10. A draw that converged to the other solution is not a mismatch datum, it
# is a startup datum, and folding it into sigma(VOUT) would report a hundreds-
# of-millivolts "spread" that is nothing of the kind. Samples outside this
# window are excluded from every statistic and counted in the record.
OPERATING_VOUT_V = (0.9, 1.5)
MIN_SOLVE_YIELD = 0.5  # below this the remaining samples are not a usable statistic

ARRAY_SCALING_BAND = (0.25, 0.55)  # sigma(dvbe8)/sigma(dvbe1); 1/sqrt(8) = 0.354
RES_BAND = (0.7, 1.4)  # measured / PDK-coefficient prediction
CLOSURE_BAND = (0.7, 1.4)  # measured sigma(vout) / budget prediction
SEED_SIGMA_TOL = 0.25

VECTORS = ("vos", "vout", "dvbe8", "veb8", "dvbe1", "rra", "rrb", "vgdrv")
# Derived per sample, not printed by the deck:
DERIVED = ("rratio",)
STAT_VECTORS = VECTORS + DERIVED


@dataclass(frozen=True)
class Point:
    corner_id: str
    section: str
    temp_c: float
    seed: int
    samples: int
    role: str  # "mismatch" | "control" | "seed-check"
    purpose: str


def build_points(samples: int) -> list[Point]:
    control_n = min(N_CONTROL, samples)
    points = [
        Point(
            corner_id=f"{MM_SECTION}_{t:g}c_{SUPPLY_V:.2f}v",
            section=MM_SECTION,
            temp_c=t,
            seed=SEED_A,
            samples=samples,
            role="mismatch",
            purpose="local-mismatch distribution at the nominal process point",
        )
        for t in TEMPS_C
    ]
    points.append(
        Point(
            corner_id=f"{OFF_SECTION}_27c_{SUPPLY_V:.2f}v_mm-off",
            section=OFF_SECTION,
            temp_c=27.0,
            seed=SEED_A,
            samples=control_n,
            role="control",
            purpose=(
                "control: identical deck on the plain `tt` section (MC_MM_SWITCH=0); "
                "every sigma must come back exactly 0, which is what proves the spread "
                "above is the mismatch switch and not solver noise or a re-seeded "
                "operating point"
            ),
        )
    )
    points.append(
        Point(
            corner_id=f"{MM_SECTION}_27c_{SUPPLY_V:.2f}v_seed-b",
            section=MM_SECTION,
            temp_c=27.0,
            seed=SEED_B,
            samples=samples,
            role="seed-check",
            purpose=(
                "seed-stability: same point, different setseed -- the samples must "
                "change while sigma must not, i.e. the reported spread is a property of "
                "the model, not of one lucky draw"
            ),
        )
    )
    return points


def predicted_res_ratio_sigma_rel() -> float:
    """sigma of R2/R1 relative, from the PDK's own res_high_po coefficient."""
    s1 = RES_MM_PCT_PER_SQRT_AREA / 100.0 / math.sqrt(R1_W_UM * R1_L_UM)
    s2 = RES_MM_PCT_PER_SQRT_AREA / 100.0 / math.sqrt(R2_W_UM * R2_L_UM)
    return math.sqrt(s1**2 + s2**2)


def load_offset_gain() -> tuple[float, str]:
    """Read the MEASURED Kuijk offset gain out of the newest error-amp-loop record.

    The budget-closure check multiplies sigma(VOS) by dVOUT/dVOS, and that
    multiplier is a measurement (sim/error-amp-loop/), not algebra. Reading it
    out of the record instead of hard-coding it means this script cannot drift
    away from the evidence it cites.
    """
    if not LOOP_RECORDS.is_dir():
        raise cr.HarnessError(
            f"no {LOOP_RECORDS.relative_to(REPO_ROOT)} -- run sim/error-amp-loop first; "
            "the budget-closure check needs its measured offset gain"
        )
    candidates = sorted(LOOP_RECORDS.glob("*.json"))
    if not candidates:
        raise cr.HarnessError(
            f"no records under {LOOP_RECORDS.relative_to(REPO_ROOT)} -- run "
            "sim/error-amp-loop first"
        )
    latest = candidates[-1]
    record = json.loads(latest.read_text())
    for corner in record.get("corners", []):
        if corner.get("corner_id") != "tt_27c_3.30v":
            continue
        for m in corner.get("measurements", []):
            if m.get("name") == "offset_gain" and m.get("value") is not None:
                return float(m["value"]), latest.stem
    raise cr.HarnessError(
        f"{latest.relative_to(REPO_ROOT)} has no offset_gain at tt_27c_3.30v"
    )


# --------------------------------------------------------------------------
# deck generation and ngspice
# --------------------------------------------------------------------------


def control_block(point: Point) -> str:
    prints = " ".join(VECTORS)
    return "\n".join(
        [
            ".control",
            f"setseed {point.seed}",
            "set width = 512",
            "set height = 100000",
            f"let nruns = {point.samples}",
            "let run = 0",
            "dowhile run < nruns",
            "  reset",
            "  op",
            "  let vos   = v(xbg.va)-v(xbg.vb)",
            "  let vout  = v(vref)",
            "  let dvbe8 = v(e8s)-v(e8l)",
            "  let veb8  = v(e8s)",
            "  let dvbe1 = v(e1s)-v(e1l)",
            "  let rra   = v(nra)",
            "  let rrb   = v(nrb)",
            "  let vgdrv = v(gdrv)",
            f"  print {prints}",
            "  let run = run + 1",
            "end",
            "quit",
            ".endc",
            ".end",
            "",
        ]
    )


def build_deck(pdk, point: Point, body: list[str]) -> str:
    head = [
        f"* {SLUG} Monte Carlo deck -- generated by sim/{SLUG}/run_amp_offset_mc.py, do not edit",
        f"* point: {point.corner_id}",
        f".param vsup={SUPPLY_V}",
        ".option wnflag=1",
        f".temp {point.temp_c:g}",
        f'.lib "{pdk.lib_file}" {point.section}',
    ]
    return "\n".join(head + body) + "\n" + control_block(point)


def write_log(corners_dir, point, pdk, record_id, stamp, deck, raw, rc, timed_out) -> Path:
    corners_dir.mkdir(parents=True, exist_ok=True)
    path = corners_dir / f"{point.corner_id}.log"
    init_text = SPICEINIT_FILE.read_text()
    header = [
        f"# point: {point.corner_id}",
        f"# record: {record_id}",
        f"# role: {point.role} -- {point.purpose}",
        f"# section={point.section} temp={point.temp_c:g}C supply={SUPPLY_V:.2f}V "
        f"seed={point.seed} samples={point.samples}",
    ]
    sections = [(".spiceinit (exact)", init_text), ("deck (exact input given to ngspice)", deck)]
    path.write_text(render_log(header, pdk, rc, timed_out, stamp, sections, raw))
    return path


# --------------------------------------------------------------------------
# per-point evaluation
# --------------------------------------------------------------------------


def evaluate(
    point: Point,
    samples: list[dict[str, float]],
    excluded: list[dict[str, float]],
    offset_gain: float,
) -> dict:
    stats = {}
    for name in STAT_VECTORS:
        values = [s[name] for s in samples]
        stats[name] = {
            "n": len(values),
            "mean": mean(values),
            "sigma": stdev(values),
            "max_abs": max(abs(v) for v in values),
            "min": min(values),
            "max": max(values),
        }
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "pass": bool(ok), "detail": detail})

    total = len(samples) + len(excluded)
    add(
        "sample_count",
        total == point.samples,
        f"parsed {total} samples, expected {point.samples}",
    )
    yield_frac = len(samples) / total if total else 0.0
    add(
        "mc_solve_yield",
        yield_frac >= MIN_SOLVE_YIELD,
        f"{len(samples)}/{total} draws converged to the operating solution "
        f"(VOUT in {OPERATING_VOUT_V[0]}..{OPERATING_VOUT_V[1]} V); "
        f"{len(excluded)} landed on the core's other stable branch and are excluded from "
        f"every statistic below. This is a STARTUP observation (issue #10 -- the core has "
        f"no startup circuit), not a mismatch one, and it is also sensitive to the "
        f"testbench .nodeset; the threshold here only asserts that enough draws remain "
        f"for the distribution to mean anything (>= {MIN_SOLVE_YIELD:.0%})."
        + (
            ""
            if not excluded
            else " Excluded VOUT values: "
            + ", ".join(f"{s['vout']:.4f} V" for s in excluded[:8])
            + (" ..." if len(excluded) > 8 else "")
        ),
    )

    spread_vectors = ("vos", "vout", "dvbe8", "veb8", "dvbe1", "rratio")
    if point.role == "control":
        for name in spread_vectors:
            add(
                f"sigma_zero[{name}]",
                stats[name]["sigma"] == 0.0,
                f"sigma = {stats[name]['sigma']:.6g} with MC_MM_SWITCH=0 (must be exactly 0)",
            )
        return _wrap(point, samples, excluded, stats, checks)

    for name in spread_vectors:
        add(
            f"sigma_nonzero[{name}]",
            stats[name]["sigma"] > 0.0,
            f"sigma = {stats[name]['sigma']:.6g} (a zero here means the mismatch switch "
            f"never reached the models)",
        )

    # --- anchor against the published section-4 numbers (27 degC point only) ---
    if abs(point.temp_c - 27.0) < 1e-9:
        got_mean = stats["dvbe1"]["mean"]
        add(
            "anchor_mean[dvbe1]",
            abs(got_mean - ANCHOR_DVBE1_MEAN_V) <= ANCHOR_MEAN_TOL_V,
            f"mean dVBE of the un-arrayed pair at 1 uA = {got_mean * 1e3:.3f} mV vs "
            f"{ANCHOR_DVBE1_MEAN_V * 1e3:.1f} mV published in "
            f"design/device-characterization-summary.md section 4 "
            f"(tolerance +/-{ANCHOR_MEAN_TOL_V * 1e3:.1f} mV)",
        )
        got_sigma = stats["dvbe1"]["sigma"]
        ratio = got_sigma / ANCHOR_DVBE1_SIGMA_V
        add(
            "anchor_sigma[dvbe1]",
            ANCHOR_SIGMA_BAND[0] <= ratio <= ANCHOR_SIGMA_BAND[1],
            f"sigma = {got_sigma * 1e3:.4f} mV vs {ANCHOR_DVBE1_SIGMA_V * 1e3:.3f} mV "
            f"published (ratio {ratio:.2f}, band {ANCHOR_SIGMA_BAND[0]}-{ANCHOR_SIGMA_BAND[1]})",
        )

    # --- the 8x array really does buy 1/sqrt(mult) ---
    s1, s8 = stats["dvbe1"]["sigma"], stats["dvbe8"]["sigma"]
    scale = s8 / s1 if s1 else float("inf")
    add(
        "array_scaling[dvbe8/dvbe1]",
        ARRAY_SCALING_BAND[0] <= scale <= ARRAY_SCALING_BAND[1],
        f"sigma(8x)/sigma(1x) = {scale:.3f} ({s8 * 1e3:.4f} / {s1 * 1e3:.4f} mV); the "
        f"model's 1/sqrt(mult) term predicts {1 / math.sqrt(8):.3f}, band "
        f"{ARRAY_SCALING_BAND[0]}-{ARRAY_SCALING_BAND[1]}",
    )

    # --- resistor ratio against the PDK's own coefficient ---
    pred_res = predicted_res_ratio_sigma_rel()
    got_res = stats["rratio"]["sigma"] / stats["rratio"]["mean"]
    ratio = got_res / pred_res
    add(
        "res_ratio_vs_pdk_coefficient",
        RES_BAND[0] <= ratio <= RES_BAND[1],
        f"sigma(R2/R1)/mean = {got_res:.4%} vs {pred_res:.4%} predicted from the PDK's "
        f"{RES_MM_PCT_PER_SQRT_AREA}%/sqrt(W*L) res_high_po coefficient on L = "
        f"{R2_L_UM:g}/{R1_L_UM:g} um (ratio {ratio:.2f}, band {RES_BAND[0]}-{RES_BAND[1]})",
    )

    # --- does the budget's arithmetic reproduce the measured total? ---
    amp = offset_gain * stats["vos"]["sigma"]
    ptat = K_PTAT * stats["dvbe8"]["sigma"]
    ctat = stats["veb8"]["sigma"]
    res = K_PTAT * abs(stats["dvbe8"]["mean"]) * got_res
    predicted = math.sqrt(amp**2 + ptat**2 + ctat**2 + res**2)
    measured = stats["vout"]["sigma"]
    closure = measured / predicted if predicted else float("inf")
    add(
        "budget_closure",
        CLOSURE_BAND[0] <= closure <= CLOSURE_BAND[1],
        f"measured sigma(VOUT) = {measured * 1e3:.4f} mV vs {predicted * 1e3:.4f} mV from "
        f"the four measured terms in quadrature (amp {amp * 1e3:.4f} + PTAT "
        f"{ptat * 1e3:.4f} + CTAT {ctat * 1e3:.4f} + resistor {res * 1e3:.4f} mV; "
        f"ratio {closure:.2f}, band {CLOSURE_BAND[0]}-{CLOSURE_BAND[1]})",
    )

    res_wrapped = _wrap(point, samples, excluded, stats, checks)
    res_wrapped["budget"] = {
        "offset_gain": offset_gain,
        "k_ptat": K_PTAT,
        "terms_v": {"amp": amp, "ptat": ptat, "ctat": ctat, "resistor": res},
        "predicted_sigma_vout_v": predicted,
        "measured_sigma_vout_v": measured,
        "closure_ratio": closure,
    }
    return res_wrapped


def _wrap(point, samples, excluded, stats, checks) -> dict:
    return {
        "corner_id": point.corner_id,
        "role": point.role,
        "purpose": point.purpose,
        "section": point.section,
        "temperature_c": point.temp_c,
        "supply_v": SUPPLY_V,
        "seed": point.seed,
        "requested_samples": point.samples,
        "parsed_samples": len(samples),
        "excluded_samples": len(excluded),
        "excluded_vout_v": [s["vout"] for s in excluded],
        "stats": stats,
        "checks": checks,
        "pass": all(c["pass"] for c in checks),
    }


def seed_stability(results: dict[str, dict]) -> list[dict]:
    a = results.get(f"{MM_SECTION}_27c_{SUPPLY_V:.2f}v")
    b = results.get(f"{MM_SECTION}_27c_{SUPPLY_V:.2f}v_seed-b")
    if not a or not b:
        return []
    out = []
    for name in ("vos", "vout", "dvbe8"):
        out += seed_stability_checks(a, b, name, SEED_A, SEED_B, SEED_SIGMA_TOL)
    return out


# --------------------------------------------------------------------------
# record rendering
# --------------------------------------------------------------------------

CLAIM = (
    "Issue #9 -- the DISTRIBUTION half of the error amplifier's offset/mismatch budget. "
    "Measures, on one seed stream at the nominal process point: the amplifier's random "
    "input-referred offset in its own loop, the 8x PNP array pair's sigma(dVBE) and "
    "absolute VEB, the res_high_po R2/R1 ratio spread, and the resulting total spread of "
    "the untrimmed reference -- then checks that the first four reproduce the fifth. This "
    "is what design/error-amp-offset-budget.md's allocation is built on. It is NOT the "
    "+/-1% untrimmed output-accuracy spec claim: this is mismatch only, at one process "
    "point, with no global process shift or temperature curvature. That claim is issue "
    "#11's experiment. The deterministic half (stability, offset gain, PSRR, Iq) is "
    "sim/error-amp-loop/."
)


def render_record(r: dict) -> str:
    L: list[str] = []
    add = L.append
    mm_points = [p for p in r["points"] if p["role"] == "mismatch"]
    ctrl = next((p for p in r["points"] if p["role"] == "control"), None)
    seedb = next((p for p in r["points"] if p["role"] == "seed-check"), None)
    n = r["statistics"]["n_samples"]

    add(f"# Record {r['record_id']}")
    add("")
    L.extend(
        render_record_id_experiment(
            r["record_id"], r["experiment"]["slug"], r["experiment"]["title"]
        )
    )
    add(f"- **Claim**: {r['experiment']['claim']}")
    add(
        f"- **Netlist provenance**: {r['experiment']['provenance']} "
        f"(`{r['experiment']['provenance_source']}`)"
    )
    L.extend(render_pdk_tools_repo_state(r))
    add("- **Corner matrix run**:")
    add(
        f"  - Process: `{MM_SECTION}` only — the nominal process point with the PDK's "
        f"local-mismatch switch on. In `libs.tech/combined/sky130.lib.spice` every plain "
        f"corner section sets `.param MC_MM_SWITCH=0` and only the `*_mm` sections set it "
        f"to 1, so **the section name is the mismatch switch**; `MC_PR_SWITCH` (global "
        f"process Monte Carlo) stays 0. Local mismatch is intra-die variation — running it "
        f"on top of `tt/ss/ff/sf/fs` would double-count the global spread that "
        f"`sim/error-amp-loop`'s 45-point matrix already records for exactly this circuit."
    )
    add(
        "  - Temperature: "
        + ", ".join(f"{p['temperature_c']:g} °C" for p in mm_points)
        + " (the full CLAUDE.md temperature axis: the PNP Is-mismatch term lands on the "
        "model's `xti` exponent and the MOS terms move with V_ov, so the spread is not "
        "temperature-flat)"
    )
    add(
        f"  - Supply: **{SUPPLY_V:.2f} V only**. Unlike `sim/pnp-mismatch`, this deck does "
        f"have a supply rail — so the subset needs a reason rather than a "
        f"not-applicable. The reason is that supply is a *deterministic* axis for this "
        f"circuit and is already swept: `sim/error-amp-loop` runs the same cell over "
        f"±10 % supply at every process/temperature point and shows the offset gain and "
        f"systematic offset move by only a few percent across it, while the mismatch "
        f"coefficients this record samples (`sw_mm_*`) are device parameters with no "
        f"supply dependence at all. Stacking N = {n} Monte Carlo samples on the supply "
        f"axis would triple the runtime to re-measure a number that does not move. This "
        f"runner does not go through `sim/bin/corner-run.py`, so that justification is "
        f"stated here rather than via `--subset-reason` (see `sim/README.md`)."
    )
    add(
        f"  - {len(r['points'])} ngspice points executed: {len(mm_points)} Monte Carlo "
        f"points (N = {n} each), one MC-off control point, one second-seed point."
    )
    add(
        f"- **Statistical convention**: **N = {n}** Monte Carlo samples per temperature, "
        f"local mismatch only (section `{MM_SECTION}`). Spread is the sample standard "
        f"deviation (N−1) reported as **1 σ**, with 3 σ alongside; σ's own relative "
        f"standard error is ≈ {100 / math.sqrt(2 * (n - 1)):.1f} %. Reproducible: "
        f"`setseed {SEED_A}` (second-seed point uses {SEED_B}). N matches "
        f"`sim/pnp-mismatch`, so the σ figures are directly comparable."
    )
    add(f"- **Result**: {'PASS' if r['overall_pass'] else 'FAIL'} — see the tables below.")
    add("")

    add("## The measured budget")
    add("")
    add(
        "Every row is a measurement from this run. The output-referred column applies the "
        "gain each term reaches the reference through: the amplifier's offset through the "
        f"**measured** Kuijk offset gain dVOUT/dVOS = {r['budget_inputs']['offset_gain']:.3f} "
        f"(from `sim/error-amp-loop` record `{r['budget_inputs']['offset_gain_record']}`, "
        f"tt/27 °C/3.30 V), the PTAT ΔVBE and the resistor-ratio error through "
        f"K = R2/R1 = {K_PTAT:.3f}, and the CTAT V_EB at unity."
    )
    add("")
    add("| T (°C) | term | measured 1 σ | output-referred 1 σ (mV) | output-referred 3 σ (% of 1.2 V) |")
    add("|---|---|---|---|---|")
    for p in mm_points:
        b = p["budget"]
        st = p["stats"]
        rows = [
            ("amplifier VOS", f"{mv(st['vos']['sigma'])} mV", b["terms_v"]["amp"]),
            ("PNP ΔVBE (8× arrays)", f"{mv(st['dvbe8']['sigma'])} mV", b["terms_v"]["ptat"]),
            ("PNP V_EB (CTAT, 8×)", f"{mv(st['veb8']['sigma'])} mV", b["terms_v"]["ctat"]),
            (
                "res_high_po R2/R1 ratio",
                f"{st['rratio']['sigma'] / st['rratio']['mean']:.4%}",
                b["terms_v"]["resistor"],
            ),
        ]
        for label, measured, out_v in rows:
            add(
                f"| {p['temperature_c']:g} | {label} | {measured} | {out_v * 1e3:.4f} | "
                f"{3 * out_v / 1.2:.3%} |"
            )
        add(
            f"| {p['temperature_c']:g} | **RSS of the four** | — | "
            f"**{b['predicted_sigma_vout_v'] * 1e3:.4f}** | "
            f"**{3 * b['predicted_sigma_vout_v'] / 1.2:.3%}** |"
        )
        add(
            f"| {p['temperature_c']:g} | **measured σ(VOUT)** | "
            f"{mv(st['vout']['sigma'])} mV | **{b['measured_sigma_vout_v'] * 1e3:.4f}** | "
            f"**{3 * b['measured_sigma_vout_v'] / 1.2:.3%}** |"
        )
    add("")
    add(
        "The last two rows of each temperature block are the point of the experiment: the "
        "budget is not an assertion, it is checked against an independently measured total "
        "on the same draws (`budget_closure` below)."
    )
    add("")

    add("## Raw distributions")
    add("")
    add("| T (°C) | vector | mean | 1 σ | 3 σ | min | max |")
    add("|---|---|---|---|---|---|---|")
    for p in mm_points:
        for name in ("vos", "vout", "dvbe8", "veb8", "dvbe1", "rratio", "vgdrv"):
            st = p["stats"][name]
            add(
                f"| {p['temperature_c']:g} | `{name}` | {st['mean']:.6g} | "
                f"{st['sigma']:.4g} | {3 * st['sigma']:.4g} | {st['min']:.6g} | "
                f"{st['max']:.6g} |"
            )
    add("")
    add(
        "The three temperatures share one seed, so they are the *same* device draws "
        "re-solved at a different temperature (common random numbers) — the three rows of "
        "a vector are not independent estimates of σ."
    )
    add("")

    add("## Controls (the reason this record can be believed)")
    add("")
    if ctrl:
        sig = ", ".join(
            f"σ({name}) = {ctrl['stats'][name]['sigma']:.3g}"
            for name in ("vos", "vout", "dvbe8", "rratio")
        )
        add(
            f"- **MC-off control** (`{ctrl['corner_id']}`, section `{OFF_SECTION}`, "
            f"N = {ctrl['parsed_samples']}): identical deck with `MC_MM_SWITCH=0`. {sig} — "
            f"exactly zero, so the spread above is the mismatch switch and not solver "
            f"noise, `.nodeset` drift or a re-randomised bias point. This is the check "
            f"that would have caught a silently no-op mismatch setup."
        )
    if seedb:
        add(
            f"- **Second-seed point** (`{seedb['corner_id']}`, `setseed {SEED_B}`, "
            f"N = {seedb['parsed_samples']}): "
            + "; ".join(
                f"σ({name}) = {mv(seedb['stats'][name]['sigma'])} mV"
                for name in ("vos", "vout", "dvbe8")
            )
            + " — the individual samples change, σ does not (see the seed-stability checks)."
        )
    add(
        "- **Published anchor**: the un-arrayed 1 µA PNP pair (`dvbe1`) in this same deck "
        "has to reproduce `design/device-characterization-summary.md` section 4's "
        f"{ANCHOR_DVBE1_MEAN_V * 1e3:.1f} mV mean and "
        f"{ANCHOR_DVBE1_SIGMA_V * 1e3:.3f} mV σ at 27 °C, which were measured by a "
        "different testbench (`sim/pnp-mismatch/`) on a different run. It is the "
        "cross-harness check that this deck's Monte Carlo really is the same mechanism."
    )
    excl = sum(p["excluded_samples"] for p in r["points"])
    add(
        f"- **Startup / solve yield**: {excl} of "
        f"{sum(p['parsed_samples'] + p['excluded_samples'] for p in r['points'])} draws "
        f"across all points converged to the core's *other* stable solution instead of "
        f"the operating one and were excluded from every statistic (per-point counts and "
        f"the excluded VOUT values are in the `mc_solve_yield` check). `bandgap_core` is "
        f"bistable by construction and ships no startup circuit — that is issue #10 — so "
        f"a non-zero count here is a startup datum, not a mismatch one, and folding it "
        f"into σ(VOUT) would report a hundreds-of-millivolts spread that is nothing of "
        f"the kind. It is also sensitive to the testbench `.nodeset` (see the testbench "
        f"header), so it is **not** a startup-yield prediction for silicon; quantifying "
        f"startup properly is a transient, and it is #10's job."
    )
    add(
        "- **PDK-coefficient cross-check**: the measured res_high_po ratio spread is "
        "compared against the PDK's own 2.06 %/√(W·L) coefficient applied to the two "
        "lengths the core uses, so the resistor term is not taken on trust either."
    )
    add("")

    add("## Checks")
    add("")
    for p in r["points"]:
        add(f"- `{p['corner_id']}` ({p['role']}): **{'PASS' if p['pass'] else 'FAIL'}**")
        for c in p["checks"]:
            add(f"  - {'PASS' if c['pass'] else 'FAIL'} `{c['name']}` — {c['detail']}")
    for c in r["cross_point_checks"]:
        add(f"- {'PASS' if c['pass'] else 'FAIL'} `{c['name']}` — {c['detail']}")
    add(f"- **Overall: {'PASS' if r['overall_pass'] else 'FAIL'}**")
    add("")

    add("## Scope limits, stated so this record is not over-read")
    add("")
    add(
        "1. **Mismatch only, one process point.** σ(VOUT) here is the *intra-die* spread. "
        "The untrimmed ±1 % spec line also carries global process shift of V_BE and of "
        "the resistor sheet, plus temperature curvature — all of which are issue #11's "
        "experiment. A part that passes this record can still miss ±1 %."
    )
    add(
        "2. **`vos` is measured in the loop, not in a servo rig.** It is the residual "
        "across the amplifier's own sense inputs in the settled loop, which equals the "
        "amplifier's input-referred offset plus (its required output) ÷ (its own voltage "
        "gain). The second term contributes microvolts here — the amplifier's gain is "
        "~50 dB and mismatch moves GDRV by millivolts (see the `vgdrv` row) — so it does "
        "not materially inflate σ(vos). It is not exactly zero either, which is one "
        "reason `budget_closure` is a band and not an equality."
    )
    add(
        "3. **Correlation between terms is neglected in the RSS.** Q1's I_s draw enters "
        "both the CTAT V_EB term and the PTAT ΔVBE term, so those two are not strictly "
        "independent. The CTAT term is ~2 % of the total, so the error this introduces is "
        "far inside the closure band; the measured σ(VOUT) row is the one to trust when "
        "the two disagree."
    )
    add("")

    add("- **Links**:")
    for key, value in r["links"].items():
        add(f"  - {key}: `{value}`")
    add(f"- **Timestamp / author**: {r['timestamp']}, {r['author']}")
    add(f"- **Supersedes**: {r['supersedes'] or '(none — first record for this claim)'}")
    add("")
    add(
        "Written by `sim/error-amp-offset-mc/run_amp_offset_mc.py`. Append-only: never "
        "edit this file — a correction is a new record with a `Supersedes` field (see "
        "`sim/README.md`)."
    )
    add("")
    return "\n".join(L)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--samples", type=int, default=N_SAMPLES, help="Monte Carlo samples per point")
    p.add_argument("--author", default="", help="record author (default: git user.email)")
    p.add_argument("--supersedes", default="", help="record id this run supersedes")
    p.add_argument("--timeout", type=int, default=7200, help="per-point ngspice timeout (s)")
    p.add_argument(
        "--allow-pdk-mismatch",
        action="store_true",
        help="run even if the installed PDK differs from the sim/pdk.json pin",
    )
    p.add_argument("--dry-run", action="store_true", help="print the plan, write nothing under sim/")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if not SCHEMATIC.is_file():
        raise cr.HarnessError(f"missing testbench: {SCHEMATIC}")
    if args.samples < 2:
        raise cr.HarnessError("--samples must be at least 2 (sigma needs N-1 > 0)")

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

    offset_gain, offset_gain_record = load_offset_gain()
    points = build_points(args.samples)
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
            raise cr.HarnessError(
                f"{path} already exists — sim/ is append-only, refusing to overwrite"
            )

    print(f"experiment      : {SLUG}")
    print(f"record id       : {record_id}")
    print(f"PDK             : {pdk.dir} (open_pdks {pdk.installed_commit})")
    print(f"testbench       : {SCHEMATIC.relative_to(REPO_ROOT)}")
    print(f"offset gain     : {offset_gain:.4f} V/V (from {offset_gain_record})")
    print(f"points          : {len(points)} ({args.samples} samples per MC point)")
    for p in points:
        print(
            f"  {p.corner_id:<32} section={p.section:<6} T={p.temp_c:>5g}C "
            f"seed={p.seed} N={p.samples}"
        )

    netlist = cr.netlist_with_xschem(SCHEMATIC, BUILD_DIR / "xschem", pdk)
    body = cr.netlist_body(netlist)

    if args.dry_run:
        print("\n-- deck head + control block for the first point --")
        deck = build_deck(pdk, points[0], body)
        print("\n".join(deck.splitlines()[:8]))
        print("...")
        print(control_block(points[0]))
        print(f"(dry run: nothing written under sim/{SLUG}/)")
        return 0

    results: dict[str, dict] = {}
    ordered: list[dict] = []
    for i, point in enumerate(points, start=1):
        run_dir = BUILD_DIR / record_id / point.corner_id
        deck = build_deck(pdk, point, body)
        raw, rc, timed_out = run_ngspice(run_dir, point.corner_id, deck, args.timeout)
        write_log(corners_dir, point, pdk, record_id, now, deck, raw, rc, timed_out)
        if rc != 0 or timed_out:
            raise cr.HarnessError(
                f"ngspice exit {rc}{' (timeout)' if timed_out else ''} for "
                f"{point.corner_id}; see "
                f"{(corners_dir / (point.corner_id + '.log')).relative_to(REPO_ROOT)}"
            )
        parsed = parse_samples(raw, VECTORS)
        for s in parsed:
            s["rratio"] = s["rra"] / s["rrb"] if s["rrb"] else float("nan")
        if not parsed:
            raise cr.HarnessError(
                f"no Monte Carlo samples parsed for {point.corner_id} — see the log"
            )
        samples, excluded = partition_by_window(parsed, "vout", OPERATING_VOUT_V)
        if len(samples) < 2:
            raise cr.HarnessError(
                f"only {len(samples)} of {len(parsed)} draws for {point.corner_id} "
                f"converged to the operating solution — nothing to compute a sigma from; "
                f"see the log"
            )
        res = evaluate(point, samples, excluded, offset_gain)
        results[point.corner_id] = res
        ordered.append(res)
        print(
            f"[{i}/{len(points)}] {point.corner_id:<32} "
            f"{'PASS' if res['pass'] else 'FAIL'}  n={res['parsed_samples']}"
            f"(-{res['excluded_samples']})  "
            f"sigma(vos)={res['stats']['vos']['sigma'] * 1e3:.4f}mV  "
            f"sigma(vout)={res['stats']['vout']['sigma'] * 1e3:.4f}mV"
        )

    cross = seed_stability(results)
    overall = all(r["pass"] for r in ordered) and all(c["pass"] for c in cross)

    snapshots_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(netlist, snapshot)

    record = {
        "record_id": record_id,
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "author": args.author or cr.default_author(),
        "supersedes": args.supersedes,
        "experiment": {
            "slug": SLUG,
            "title": TITLE,
            "claim": CLAIM,
            "provenance": "schematic",
            "provenance_source": str(SCHEMATIC.relative_to(REPO_ROOT)),
            "statistical_convention": (
                f"N = {args.samples} Monte Carlo samples per point, local mismatch only "
                f"(section {MM_SECTION}: MC_MM_SWITCH=1, MC_PR_SWITCH=0); 1 sigma sample "
                f"standard deviation (N-1), fixed setseed {SEED_A}"
            ),
        },
        "budget_inputs": {
            "offset_gain": offset_gain,
            "offset_gain_record": offset_gain_record,
            "offset_gain_source": "sim/error-amp-loop (measured, tt/27C/3.30V)",
            "k_ptat": K_PTAT,
            "r1_ohm": R1_OHM,
            "r2_ohm": R2_OHM,
            "res_mm_pct_per_sqrt_area": RES_MM_PCT_PER_SQRT_AREA,
            "predicted_res_ratio_sigma_rel": predicted_res_ratio_sigma_rel(),
            "anchor_dvbe1_mean_v": ANCHOR_DVBE1_MEAN_V,
            "anchor_dvbe1_sigma_v": ANCHOR_DVBE1_SIGMA_V,
        },
        "mismatch_model": {
            "switch": "MC_MM_SWITCH (set by the .lib section: 0 in tt/ss/ff/sf/fs, 1 in *_mm)",
            "sections": {"mismatch": MM_SECTION, "control": OFF_SECTION},
            "source": "libs.tech/combined/continuous/models_*.spice + models_global.spice",
        },
        "statistics": {"n_samples": args.samples, "seed_a": SEED_A, "seed_b": SEED_B},
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
        "points": ordered,
        "cross_point_checks": cross,
        "overall_pass": overall,
        "links": {
            "testbench": str(SCHEMATIC.relative_to(REPO_ROOT)),
            "runner": str((HERE / "run_amp_offset_mc.py").relative_to(REPO_ROOT)),
            "netlist_snapshot": str(snapshot.relative_to(REPO_ROOT)),
            "logs": str(corners_dir.relative_to(REPO_ROOT)),
            "record_json": str(record_json.relative_to(REPO_ROOT)),
            "budget_doc": "design/error-amp-offset-budget.md",
        },
    }

    records_dir.mkdir(parents=True, exist_ok=True)
    record_json.write_text(json.dumps(record, indent=2) + "\n")
    record_md.write_text(render_record(record))
    print(f"\nrecord: {record_md.relative_to(REPO_ROOT)}")
    print(f"        {record_json.relative_to(REPO_ROOT)}")
    return 0 if overall else 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except cr.HarnessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
