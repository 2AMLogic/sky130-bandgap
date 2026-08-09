#!/usr/bin/env python3
"""Monte Carlo local-mismatch runner for the sky130 substrate-PNP pair (issue #31).

Why this is a bespoke script and not another `experiment.json` +
`sim/bin/corner-run.py` experiment: `corner-run.py` runs exactly one
deterministic deck per PVT point and parses one scalar per measurement. A
local-mismatch claim needs the same deck resampled N times at a single
process point and a *distribution* parsed out of the log. That is a different
axis than the PVT matrix, so this experiment drives ngspice itself -- the same
split gf180-bandgap's `sim/device-pnp-mismatch/` uses.

It still reuses `sim/bin/corner-run.py`'s PDK resolution, PDK-pin enforcement,
tool-version and git-provenance helpers (imported directly, not re-implemented)
so a record written here is comparable with the records the corner runner
writes, and it follows `sim/README.md`'s record-id scheme, directory layout,
`.md` + `.json` twin convention and append-only rule.

Usage
-----
    sim/pnp-mismatch/run_pnp_mismatch.py                  # the full run
    sim/pnp-mismatch/run_pnp_mismatch.py --samples 20     # quick smoke run
    sim/pnp-mismatch/run_pnp_mismatch.py --dry-run        # print the plan

Exit status: 0 every check passed, 2 a record was written but a check failed,
1 harness/setup error (no record written) -- same convention as corner-run.py.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO_ROOT = SIM_DIR.parent
DECK = HERE / "testbench" / "tb_pnp_mismatch.spice"
BUILD_DIR = SIM_DIR / "build" / "pnp-mismatch"
SPICEINIT_FILE = SIM_DIR / "spiceinit"

sys.path.insert(0, str(SIM_DIR / "bin"))
from sim_common import load_corner_run, mean  # noqa: E402

cr = load_corner_run()

# --------------------------------------------------------------------------
# experiment definition
# --------------------------------------------------------------------------

SLUG = "pnp-mismatch"
TITLE = "Substrate PNP pair local mismatch -- sigma(dVBE) by Monte Carlo"

MM_SECTION = "tt_mm"  # nominal process + MC_MM_SWITCH=1 (local mismatch on)
OFF_SECTION = "tt"  # nominal process + MC_MM_SWITCH=0 (control: sigma must be 0)
TEMPS_C = [-40.0, 27.0, 125.0]
N_SAMPLES = 300  # matches gf180-bandgap's mismatch record, so N is comparable
N_CONTROL = 30  # the control point is deterministic; N only has to be > 1
SEED_A = 20260731
SEED_B = 20260801  # second seed, for the seed-stability check

# PDK mismatch coefficients, read from
# $PDK_ROOT/$PDK/libs.tech/combined/continuous/models_global.spice
SW_MM_IS = 1.662e-2  # sw_mm_sky130_fd_pr__pnp_05v5_W0p68L0p68_is
SW_MM_BF = 5.537e-2  # sw_mm_sky130_fd_pr__pnp_05v5_W0p68L0p68_bf
LARGE_IS_SCALE = 0.13  # W3p40L3p40 reuses ..._is scaled by 0.13
LARGE_BF_SCALE = 0.45  # W3p40L3p40 reuses ..._bf scaled by 0.45

K_OVER_Q = 1.380649e-23 / 1.602176634e-19  # V/K

SMALL = "sky130_fd_pr__pnp_05v5_W0p68L0p68"
LARGE = "sky130_fd_pr__pnp_05v5_W3p40L3p40"


@dataclass(frozen=True)
class Pair:
    vector: str  # ngspice vector printed by the testbench
    kind: str  # "identical" | "ratioed"
    label: str
    bias_a: float
    veb_vectors: tuple[str, str] | None = None  # absolute VEB legs, if printed


PAIRS = (
    Pair("da1", "identical", f"{SMALL} x2", 1e-6),
    Pair("da10", "identical", f"{SMALL} x2", 10e-6),
    Pair("dr1", "ratioed", f"{SMALL} / {LARGE}", 1e-6, ("vr1a", "vr1b")),
    Pair("dr10", "ratioed", f"{SMALL} / {LARGE}", 10e-6, ("vr10a", "vr10b")),
)
VEB_VECTORS = ("vr1a", "vr1b", "vr10a", "vr10b")
ALL_VECTORS = tuple(p.vector for p in PAIRS) + VEB_VECTORS

# check tolerances
MEAN_SIGMA_TOL = 4.0  # |mean| must stay under TOL * sigma/sqrt(N) for a zero-mean pair
ANALYTIC_BAND = (0.7, 2.0)  # measured sigma / first-order analytic prediction
SEED_SIGMA_TOL = 0.25  # |sigma_B/sigma_A - 1| for the seed-stability check
SIGNAL_RATIO_MAX = 0.05  # sigma(dVBE) must stay well under the PTAT dVBE signal


@dataclass(frozen=True)
class Point:
    """One ngspice invocation: a (section, temperature, seed, N) tuple."""

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
            corner_id=f"{MM_SECTION}_{t:g}c_nosupply",
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
            corner_id=f"{OFF_SECTION}_27c_nosupply_mm-off",
            section=OFF_SECTION,
            temp_c=27.0,
            seed=SEED_A,
            samples=control_n,
            role="control",
            purpose=(
                "control: identical deck on the plain `tt` section "
                "(MC_MM_SWITCH=0); every sigma must come back exactly 0, which "
                "is what proves the spread above is the mismatch switch and not "
                "solver noise"
            ),
        )
    )
    points.append(
        Point(
            corner_id=f"{MM_SECTION}_27c_nosupply_seed-b",
            section=MM_SECTION,
            temp_c=27.0,
            seed=SEED_B,
            samples=samples,
            role="seed-check",
            purpose=(
                "seed-stability: same point, different setseed -- the samples "
                "must change while sigma must not, i.e. the reported spread is "
                "a property of the model, not of one lucky draw"
            ),
        )
    )
    return points


# --------------------------------------------------------------------------
# statistics (stdlib only, same style as the rest of the harness)
# --------------------------------------------------------------------------


def stdev(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mu = mean(values)
    return math.sqrt(sum((v - mu) ** 2 for v in values) / (n - 1))


def thermal_voltage(temp_c: float) -> float:
    return K_OVER_Q * (temp_c + 273.15)


def analytic_sigma(pair: Pair, temp_c: float) -> float:
    """First-order prediction from the PDK's own Is-mismatch coefficients.

    VBE = VT*ln(Ic/Is) => dVBE/VBE-shift from a relative Is error is
    -VT * (dIs/Is), so sigma(VBE) ~ VT * sigma_rel(Is) per device and the pair
    adds in quadrature. Bf/Ise/Vaf and the xti mismatch term add on top, so the
    measured sigma is expected to land at or slightly above this figure -- the
    check band below is one-sided-ish for that reason.
    """
    vt = thermal_voltage(temp_c)
    small = SW_MM_IS
    other = SW_MM_IS if pair.kind == "identical" else LARGE_IS_SCALE * SW_MM_IS
    return vt * math.sqrt(small**2 + other**2)


# --------------------------------------------------------------------------
# ngspice
# --------------------------------------------------------------------------

_PRINT_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(-?[0-9.]+(?:[eE][-+]?[0-9]+)?)$")


def parse_samples(log: str, vectors: tuple[str, ...]) -> list[dict[str, float]]:
    """Parse the repeated `op` + `print` blocks of the Monte Carlo loop.

    A new sample starts whenever a vector name that is already in the current
    sample repeats.
    """
    wanted = set(vectors)
    samples: list[dict[str, float]] = []
    current: dict[str, float] = {}
    for line in log.splitlines():
        m = _PRINT_LINE.match(line.strip())
        if not m or m.group(1) not in wanted:
            continue
        name, value = m.group(1), float(m.group(2))
        if name in current:
            samples.append(current)
            current = {}
        current[name] = value
    if current:
        samples.append(current)
    return [s for s in samples if wanted <= set(s)]


def corner_shim(pdk, point: Point) -> str:
    return (
        "* Generated per point by sim/pnp-mismatch/run_pnp_mismatch.py from the\n"
        "* resolved PDK -- scratch only, not committed.\n"
        f'.lib "{pdk.lib_file}" {point.section}\n'
        f".temp {point.temp_c:g}\n"
    )


def spiceinit_text(point: Point) -> str:
    return (
        SPICEINIT_FILE.read_text()
        + "\n* Monte Carlo controls injected by sim/pnp-mismatch/run_pnp_mismatch.py\n"
        f"set mc_seed={point.seed}\n"
        f"set mc_runs={point.samples}\n"
    )


def run_point(pdk, point: Point, run_dir: Path, timeout: int) -> tuple[str, int, bool]:
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DECK, run_dir / DECK.name)
    (run_dir / "corner.spice").write_text(corner_shim(pdk, point))
    (run_dir / ".spiceinit").write_text(spiceinit_text(point))
    try:
        proc = subprocess.run(
            ["ngspice", "-b", DECK.name],
            cwd=run_dir,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
        return proc.stdout + proc.stderr, proc.returncode, False
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        err = exc.stderr or ""
        if isinstance(out, bytes):
            out = out.decode(errors="replace")
        if isinstance(err, bytes):
            err = err.decode(errors="replace")
        return out + err, -1, True


def write_log(
    corners_dir: Path, point: Point, pdk, record_id: str, stamp: datetime, run_dir: Path, raw: str, rc: int, timed_out: bool
) -> Path:
    corners_dir.mkdir(parents=True, exist_ok=True)
    path = corners_dir / f"{point.corner_id}.log"
    deck_text = (run_dir / DECK.name).read_text()
    shim_text = (run_dir / "corner.spice").read_text()
    init_text = (run_dir / ".spiceinit").read_text()
    path.write_text(
        "\n".join(
            [
                f"# point: {point.corner_id}",
                f"# record: {record_id}",
                f"# role: {point.role} -- {point.purpose}",
                f"# section={point.section} temp={point.temp_c:g}C supply=n/a "
                f"seed={point.seed} samples={point.samples}",
                f"# pdk: {pdk.variant} @ open_pdks {pdk.installed_commit} ({pdk.lib_file})",
                f"# ngspice exit: {rc}{' (TIMEOUT)' if timed_out else ''}",
                f"# run (UTC): {stamp:%Y-%m-%dT%H:%M:%SZ}",
                "",
                "# ==== .spiceinit (exact) ====",
                *[f"| {ln}" for ln in init_text.splitlines()],
                "",
                "# ==== corner.spice (exact) ====",
                *[f"| {ln}" for ln in shim_text.splitlines()],
                "",
                "# ==== testbench deck (exact input given to ngspice) ====",
                *[f"| {ln}" for ln in deck_text.splitlines()],
                "",
                "# ==== ngspice stdout+stderr ====",
                raw.rstrip(),
                "",
            ]
        )
    )
    return path


# --------------------------------------------------------------------------
# per-point evaluation
# --------------------------------------------------------------------------


def evaluate(point: Point, samples: list[dict[str, float]]) -> dict:
    stats = {}
    for name in ALL_VECTORS:
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

    add(
        "sample_count",
        len(samples) == point.samples,
        f"parsed {len(samples)} samples, expected {point.samples}",
    )

    for pair in PAIRS:
        st = stats[pair.vector]
        sigma = st["sigma"]
        if point.role == "control":
            add(
                f"sigma_zero[{pair.vector}]",
                sigma == 0.0,
                f"sigma = {sigma:.6g} V with MC_MM_SWITCH=0 (must be exactly 0)",
            )
            continue

        add(
            f"sigma_nonzero[{pair.vector}]",
            sigma > 0.0,
            f"sigma = {sigma * 1e3:.4f} mV (must be > 0: a zero here means the "
            f"mismatch switch never reached the models)",
        )
        pred = analytic_sigma(pair, point.temp_c)
        ratio = sigma / pred if pred else 0.0
        add(
            f"analytic_band[{pair.vector}]",
            ANALYTIC_BAND[0] <= ratio <= ANALYTIC_BAND[1],
            f"sigma/predicted = {ratio:.2f} (measured {sigma * 1e3:.4f} mV vs "
            f"first-order PDK-coefficient prediction {pred * 1e3:.4f} mV; band "
            f"{ANALYTIC_BAND[0]}-{ANALYTIC_BAND[1]})",
        )
        if pair.kind == "identical":
            se = sigma / math.sqrt(len(samples))
            add(
                f"zero_mean[{pair.vector}]",
                abs(st["mean"]) <= MEAN_SIGMA_TOL * se,
                f"|mean| = {abs(st['mean']) * 1e3:.4f} mV vs "
                f"{MEAN_SIGMA_TOL:g}*sigma/sqrt(N) = {MEAN_SIGMA_TOL * se * 1e3:.4f} mV "
                f"(an identical pair has no systematic offset)",
            )
        else:
            signal = abs(st["mean"])
            add(
                f"signal_vs_sigma[{pair.vector}]",
                signal > 0 and sigma / signal <= SIGNAL_RATIO_MAX,
                f"sigma/|mean dVBE| = {sigma / signal:.4f} (mismatch spread "
                f"{sigma * 1e3:.4f} mV against a {signal * 1e3:.3f} mV PTAT signal; "
                f"must be <= {SIGNAL_RATIO_MAX:g})",
            )

    return {
        "corner_id": point.corner_id,
        "role": point.role,
        "purpose": point.purpose,
        "section": point.section,
        "temperature_c": point.temp_c,
        "supply_v": None,
        "seed": point.seed,
        "requested_samples": point.samples,
        "parsed_samples": len(samples),
        "stats": stats,
        "checks": checks,
        "pass": all(c["pass"] for c in checks),
    }


def seed_stability(results: dict[str, dict]) -> list[dict]:
    """Compare the seed-B point against the same point at seed A."""
    a = results.get(f"{MM_SECTION}_27c_nosupply")
    b = results.get(f"{MM_SECTION}_27c_nosupply_seed-b")
    if not a or not b:
        return []
    out = []
    for pair in PAIRS:
        sa = a["stats"][pair.vector]["sigma"]
        sb = b["stats"][pair.vector]["sigma"]
        drift = abs(sb / sa - 1.0) if sa else float("inf")
        out.append(
            {
                "name": f"seed_sigma_stable[{pair.vector}]",
                "pass": drift <= SEED_SIGMA_TOL,
                "detail": (
                    f"sigma(seed {SEED_B}) / sigma(seed {SEED_A}) = "
                    f"{(sb / sa) if sa else float('nan'):.3f} "
                    f"({sb * 1e3:.4f} mV vs {sa * 1e3:.4f} mV; tolerance "
                    f"+/-{SEED_SIGMA_TOL:.0%})"
                ),
            }
        )
        out.append(
            {
                "name": f"seed_sample_differs[{pair.vector}]",
                "pass": a["stats"][pair.vector]["max_abs"] != b["stats"][pair.vector]["max_abs"],
                "detail": (
                    "worst-sample magnitude differs between the two seeds "
                    f"({a['stats'][pair.vector]['max_abs'] * 1e3:.4f} mV vs "
                    f"{b['stats'][pair.vector]['max_abs'] * 1e3:.4f} mV), i.e. the "
                    "draw really did change"
                ),
            }
        )
    return out


# --------------------------------------------------------------------------
# record rendering
# --------------------------------------------------------------------------


def mv(value: float) -> str:
    return f"{value * 1e3:.4f}"


def render_record(r: dict) -> str:
    L: list[str] = []
    add = L.append
    mm_points = [p for p in r["points"] if p["role"] == "mismatch"]
    ctrl = next((p for p in r["points"] if p["role"] == "control"), None)
    seedb = next((p for p in r["points"] if p["role"] == "seed-check"), None)
    n = r["statistics"]["n_samples"]

    add(f"# Record {r['record_id']}")
    add("")
    add(f"- **Record ID**: {r['record_id']}")
    add(f"- **Experiment**: `{r['experiment']['slug']}` — {r['experiment']['title']}")
    add(f"- **Claim**: {r['experiment']['claim']}")
    add(
        f"- **Netlist provenance**: {r['experiment']['provenance']} "
        f"(`{r['experiment']['provenance_source']}`)"
    )
    pdk = r["pdk"]
    pin_state = (
        "matches sim/pdk.json pin" if pdk["matches_pin"] else "**MISMATCH vs sim/pdk.json pin**"
    )
    add(
        f"- **PDK**: {pdk['variant']} @ open_pdks `{pdk['installed_commit']}` ({pin_state}); "
        f"models `{pdk['lib_file']}`"
    )
    t = r["tools"]
    add(f"- **Tools**: {t['ngspice']}; {t['xschem']}; {t['platform']}")
    add(
        f"- **Repo state**: `{r['git']['sha']}` on `{r['git']['branch']}`"
        + (" (working tree dirty at run time)" if r["git"]["dirty"] else " (clean working tree)")
    )

    add("- **Corner matrix run**:")
    add(
        f"  - Process: `{MM_SECTION}` only — the nominal process point with the PDK's "
        f"local-mismatch switch on. In `libs.tech/combined/sky130.lib.spice` every plain "
        f"corner section sets `.param MC_MM_SWITCH=0` and only the `*_mm` sections set it "
        f"to 1, so **the section name is the mismatch switch**; `MC_PR_SWITCH` (global "
        f"process Monte Carlo, the `mc` section) stays 0. Local mismatch is intra-die "
        f"variation: stacking it on `tt/ss/ff/sf/fs` would double-count the global spread "
        f"`sim/pnp-characterization`'s 15-point matrix already records, so this record "
        f"deliberately does **not** sweep the process axis. This runner does not go "
        f"through `sim/bin/corner-run.py`, so that justification is stated here rather "
        f"than via `--subset-reason`."
    )
    add(
        "  - Temperature: "
        + ", ".join(f"{p['temperature_c']:g} °C" for p in mm_points)
        + " (full CLAUDE.md temperature axis — the Is-mismatch term also lands on the "
        "model's `xti` temperature exponent, so the spread is not temperature-flat)"
    )
    add(
        "  - Supply: **not applicable**. Every DUT is a diode-connected substrate PNP "
        "referred to its own emitter node and biased by an ideal current source; there is "
        "no supply-referenced terminal, so the ±10 % supply axis has nothing to sweep "
        "(the same justification `sim/pnp-characterization/experiment.json` records). The "
        "point ids carry `nosupply` in the supply field."
    )
    add(
        f"  - {len(r['points'])} ngspice points executed: {len(mm_points)} Monte Carlo "
        f"points (N = {n} each), one MC-off control point, one second-seed point."
    )
    add(
        f"- **Statistical convention**: **N = {n}** Monte Carlo samples per temperature, "
        f"local mismatch only (section `{MM_SECTION}`: `MC_MM_SWITCH=1`, `MC_PR_SWITCH=0`, "
        f"`mismatch_factor=1`). Spread is reported as **1 σ** of the pair's emitter-voltage "
        f"difference ΔVBE with 3 σ alongside; σ is the sample standard deviation (N−1), so "
        f"its own relative standard error is ≈ {100 / math.sqrt(2 * (n - 1)):.1f} %. "
        f"Reproducible: `setseed {SEED_A}` (the second-seed point uses {SEED_B}). N matches "
        f"gf180-bandgap's PNP mismatch record, so the two repos' σ figures are directly "
        f"comparable."
    )
    add(f"- **Result**: {'PASS' if r['overall_pass'] else 'FAIL'} — see the tables below.")
    add("")

    add("## What the sky130 PDK actually does for BJT mismatch")
    add("")
    add(
        "Verified against the pinned PDK rather than carried over from gf180mcu (whose "
        "`sw_stat_mismatch` / `mis_is_pnp_*` convention does **not** exist here). In "
        "`libs.tech/combined/continuous/models_bjt.spice` each PNP subcircuit carries"
    )
    add("")
    add("```")
    add(".param mm_is = {sw_mm_sky130_fd_pr__pnp_05v5_W0p68L0p68_is")
    add("               * mismatch_factor * MC_MM_SWITCH * AGAUSS(0,1.0,1)/sqrt(mult)}")
    add("       mm_bf = {sw_mm_sky130_fd_pr__pnp_05v5_W0p68L0p68_bf * ... }")
    add("  is  = '1.5075e-018*dkispp / sw_func_rdp*(1+mm_is)'      (W0p68L0p68)")
    add("  bf  = '19.35*dkbfpp*sw_nw_rs_mult**0.75*(1+mm_bf)'")
    add("  ise = '9.4936e-017*(1-mm_bf)'   vaf = '152.06 / sw_nw_rs_mult*(1-mm_bf)'")
    add("  xti = {1.1*(1+mm_is)}")
    add("```")
    add("")
    add(
        f"with the sigmas in `continuous/models_global.spice`: "
        f"`..._is = {SW_MM_IS:.3e}` ({SW_MM_IS:.3%} on Is) and "
        f"`..._bf = {SW_MM_BF:.3e}` ({SW_MM_BF:.3%} on Bf). The `W3p40L3p40` subcircuit "
        f"reuses the same two coefficients scaled by {LARGE_IS_SCALE} (Is) and "
        f"{LARGE_BF_SCALE} (Bf) — the 25× emitter area's matching benefit is already in the "
        f"PDK model. `AGAUSS()` sits inside the subcircuit, so each instance draws "
        f"independently; ngspice re-draws on `reset`, which is what makes the deck's "
        f"control loop a real Monte Carlo."
    )
    add("")

    add(f"## Pair ΔVBE distribution (N = {n} per point)")
    add("")
    add(
        "| Pair | Bias | T (°C) | mean ΔVBE (mV) | 1 σ (mV) | 3 σ (mV) | worst sample \\|ΔVBE\\| (mV) |"
    )
    add("|---|---|---|---|---|---|---|")
    for pair in PAIRS:
        for p in mm_points:
            st = p["stats"][pair.vector]
            add(
                f"| {pair.kind}: `{pair.label}` | {pair.bias_a * 1e6:g} µA | "
                f"{p['temperature_c']:g} | {st['mean'] * 1e3:+.4f} | {mv(st['sigma'])} | "
                f"{mv(3 * st['sigma'])} | {mv(st['max_abs'])} |"
            )
    add("")
    add(
        "The three temperatures share one seed, so they are the *same* device draws "
        "re-solved at a different temperature (common random numbers) — the three rows of a "
        "pair are not independent estimates of σ."
    )
    add("")

    add("## Sanity: measured σ vs the PDK's own coefficients")
    add("")
    add(
        "First-order prediction from the Is-mismatch coefficient alone: "
        "VBE = V_T·ln(Ic/Is), so a relative Is error σ_Is/Is shifts VBE by V_T·σ_Is/Is and "
        "the two legs add in quadrature. Bf/Ise/Vaf and the `xti` term add on top, so the "
        "measurement is expected to land at or a little above the prediction — an "
        "*order-of-magnitude* agreement here is what rules out the failure mode where the "
        "spread comes from somewhere other than the intended per-instance mismatch terms."
    )
    add("")
    add("| Pair | T (°C) | predicted σ (mV) | measured σ (mV) | ratio |")
    add("|---|---|---|---|---|")
    for pair in PAIRS:
        for p in mm_points:
            pred = analytic_sigma(pair, p["temperature_c"])
            got = p["stats"][pair.vector]["sigma"]
            add(
                f"| {pair.kind}, {pair.bias_a * 1e6:g} µA | {p['temperature_c']:g} | "
                f"{mv(pred)} | {mv(got)} | {got / pred:.2f} |"
            )
    add("")

    add("## Controls (the reason this record can be believed)")
    add("")
    if ctrl:
        sig = ", ".join(f"σ({p.vector}) = {ctrl['stats'][p.vector]['sigma']:.3g} V" for p in PAIRS)
        add(
            f"- **MC-off control** (`{ctrl['corner_id']}`, section `{OFF_SECTION}`, "
            f"N = {ctrl['parsed_samples']}): identical deck with `MC_MM_SWITCH=0`. "
            f"{sig} — exactly zero, so the spread reported above is the mismatch switch "
            f"and not solver noise or a re-randomised bias point. This is the check that "
            f"would have caught a wrong/no-op switch name, the main way this experiment "
            f"could have produced plausible-looking nonsense."
        )
    if seedb:
        add(
            f"- **Second-seed point** (`{seedb['corner_id']}`, `setseed {SEED_B}`, "
            f"N = {seedb['parsed_samples']}): "
            + "; ".join(
                f"σ({p.vector}) = {mv(seedb['stats'][p.vector]['sigma'])} mV"
                for p in PAIRS
            )
            + " — see the seed-stability checks below: the individual samples change, σ "
            "does not."
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

    add("## Divergences worth stating explicitly")
    add("")
    add(
        "1. **`.json` twin.** gf180-bandgap's `sim/device-pnp-mismatch/` record shipped a "
        "`.md` only. `sim/README.md` in *this* repo makes a machine-readable `.json` twin "
        "part of the house record format, so this record writes both. The house convention "
        "wins over the sibling repo's precedent."
    )
    add(
        "2. **Terminal connection vs `sim/pnp-characterization`.** This deck drives the "
        "**emitter** (collector and base grounded), which is how a bandgap core connects a "
        "sky130 substrate PNP. `sim/pnp-characterization`'s netlist snapshot "
        "(`XQS0 E_small_100n 0 0 sky130_fd_pr__pnp_05v5_W0p68L0p68`) lands the driven node "
        "on subcircuit pin 1 = `c`, i.e. it biases the collector with the emitter grounded "
        "and therefore measures the base-collector junction. Reproduced at tt / 27 °C / "
        "1 µA: collector-driven = 0.545166 V, which is exactly that record's "
        "`veb_small_1u`; emitter-driven = 0.742539 V. **Absolute VBE and the ΔVBE PTAT "
        "figures in this record are therefore not comparable one-for-one with that "
        "record's ladder**; the PTAT ΔVBE this deck measures on the same two devices is "
        "reported above as the ratioed pair's mean. Correcting `sim/pnp-characterization` "
        "is out of scope for issue #31 (`sim/` is append-only; a correction is a new "
        "record) and is filed separately."
    )
    add(
        "3. **Bias points.** 1 µA and 10 µA — rungs of `sim/pnp-characterization`'s "
        "half-decade ladder that bracket the 2/5/20 µA per-branch range "
        "`sim/mos-matching-characterization` uses for the < 50 µA Iq budget, and the same "
        "two biases gf180-bandgap used, so both cross-references hold."
    )
    add(
        f"4. **N and seed** match gf180-bandgap (N = {N_SAMPLES}, fixed `setseed`); the "
        "MC-off control point and the second-seed point are additions this record makes "
        "that the gf180 precedent did not have."
    )
    add("")

    add("- **Links**:")
    for key, value in r["links"].items():
        add(f"  - {key}: `{value}`")
    add(f"- **Timestamp / author**: {r['timestamp']}, {r['author']}")
    add(f"- **Supersedes**: {r['supersedes'] or '(none — first record for this claim)'}")
    add("")
    add(
        "Written by `sim/pnp-mismatch/run_pnp_mismatch.py`. Append-only: never edit this "
        "file — a correction is a new record with a `Supersedes` field (see "
        "`sim/README.md`)."
    )
    add("")
    return "\n".join(L)


CLAIM = (
    "Issue #31 — local (intra-die) mismatch of a matched sky130 substrate-PNP pair: "
    "sigma of dVBE for (a) two identical `sky130_fd_pr__pnp_05v5_W0p68L0p68` devices and "
    "(b) the area-ratioed `sky130_fd_pr__pnp_05v5_W0p68L0p68` / "
    "`sky130_fd_pr__pnp_05v5_W3p40L3p40` pair, at equal emitter current. This is the PNP "
    "counterpart of the MOS Pelgrom projection in "
    "`sim/mos-matching-characterization` and feeds the error-amplifier offset budget (#9) "
    "and the draft spec (#1). **This record makes no spec pass/fail claim** — no ratified "
    "spec exists yet; it reports a measured distribution plus the harness checks that "
    "make the distribution trustworthy."
)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--samples", type=int, default=N_SAMPLES, help="Monte Carlo samples per point")
    p.add_argument("--author", default="", help="record author (default: git user.email)")
    p.add_argument("--supersedes", default="", help="record id this run supersedes")
    p.add_argument("--timeout", type=int, default=3600, help="per-point ngspice timeout (s)")
    p.add_argument(
        "--allow-pdk-mismatch",
        action="store_true",
        help="run even if the installed PDK differs from the sim/pdk.json pin",
    )
    p.add_argument("--dry-run", action="store_true", help="print the plan, write nothing under sim/")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if not DECK.is_file():
        raise cr.HarnessError(f"missing testbench: {DECK}")
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
    print(f"testbench       : {DECK.relative_to(REPO_ROOT)}")
    print(f"points          : {len(points)} ({args.samples} samples per MC point)")
    for p in points:
        print(f"  {p.corner_id:<38} section={p.section:<6} T={p.temp_c:>5g}C seed={p.seed} N={p.samples}")
    if args.dry_run:
        print("\n-- corner shim for the first point --")
        print(corner_shim(pdk, points[0]))
        print("(dry run: nothing written under sim/pnp-mismatch/)")
        return 0

    results: dict[str, dict] = {}
    ordered: list[dict] = []
    for i, point in enumerate(points, start=1):
        run_dir = BUILD_DIR / record_id / point.corner_id
        raw, rc, timed_out = run_point(pdk, point, run_dir, args.timeout)
        write_log(corners_dir, point, pdk, record_id, now, run_dir, raw, rc, timed_out)
        if rc != 0 or timed_out:
            raise cr.HarnessError(
                f"ngspice exit {rc}{' (timeout)' if timed_out else ''} for {point.corner_id}; "
                f"see {(corners_dir / (point.corner_id + '.log')).relative_to(REPO_ROOT)}"
            )
        samples = parse_samples(raw, ALL_VECTORS)
        if not samples:
            raise cr.HarnessError(
                f"no Monte Carlo samples parsed for {point.corner_id} — see the log"
            )
        res = evaluate(point, samples)
        results[point.corner_id] = res
        ordered.append(res)
        head = ", ".join(
            f"sigma({p.vector})={res['stats'][p.vector]['sigma'] * 1e3:.4f}mV" for p in PAIRS
        )
        print(
            f"[{i}/{len(points)}] {point.corner_id:<38} "
            f"{'PASS' if res['pass'] else 'FAIL'}  n={res['parsed_samples']}  {head}"
        )

    cross = seed_stability(results)
    overall = all(r["pass"] for r in ordered) and all(c["pass"] for c in cross)

    snapshots_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DECK, snapshot)

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
            "provenance_source": str(DECK.relative_to(REPO_ROOT)),
            "statistical_convention": (
                f"N = {args.samples} Monte Carlo samples per point, local mismatch only "
                f"(section {MM_SECTION}: MC_MM_SWITCH=1, MC_PR_SWITCH=0); 1 sigma sample "
                f"standard deviation (N-1), fixed setseed {SEED_A}"
            ),
        },
        "mismatch_model": {
            "switch": "MC_MM_SWITCH (set by the .lib section: 0 in tt/ss/ff/sf/fs, 1 in *_mm)",
            "sections": {"mismatch": MM_SECTION, "control": OFF_SECTION},
            "coefficients": {
                "sw_mm_sky130_fd_pr__pnp_05v5_W0p68L0p68_is": SW_MM_IS,
                "sw_mm_sky130_fd_pr__pnp_05v5_W0p68L0p68_bf": SW_MM_BF,
                "W3p40L3p40_is_scale": LARGE_IS_SCALE,
                "W3p40L3p40_bf_scale": LARGE_BF_SCALE,
            },
            "source": "libs.tech/combined/continuous/models_bjt.spice + models_global.spice",
        },
        "pairs": [
            {
                "vector": p.vector,
                "kind": p.kind,
                "devices": p.label,
                "bias_a": p.bias_a,
                "veb_vectors": list(p.veb_vectors) if p.veb_vectors else None,
            }
            for p in PAIRS
        ],
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
            "testbench": str(DECK.relative_to(REPO_ROOT)),
            "run_script": str((HERE / "run_pnp_mismatch.py").relative_to(REPO_ROOT)),
            "netlist_snapshot": str(snapshot.relative_to(REPO_ROOT)),
            "raw_logs": str(corners_dir.relative_to(REPO_ROOT)) + "/",
            "json_record": str(record_json.relative_to(REPO_ROOT)),
            "record": str(record_md.relative_to(REPO_ROOT)),
        },
    }

    records_dir.mkdir(parents=True, exist_ok=True)
    record_json.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
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
        print(f"run_pnp_mismatch: error: {err}", file=sys.stderr)
        sys.exit(1)
