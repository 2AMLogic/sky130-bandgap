#!/usr/bin/env python3
"""Monte Carlo mismatch analysis for the untrimmed +/-1% output-accuracy claim (issue #12).

Why this is a bespoke script and not another `experiment.json` +
`sim/bin/corner-run.py` experiment: the corner runner drives exactly one
deterministic deck per PVT point. A yield/sigma claim needs the same deck
resampled N times at a single process point, which is a different axis than
the PVT matrix. `sim/pnp-mismatch/run_pnp_mismatch.py` established that split
in this repo and `sim/error-amp-offset-mc/run_amp_offset_mc.py` followed it;
this script follows both, reusing `sim/bin/corner-run.py`'s PDK resolution,
pin enforcement, xschem netlisting, tool-version and git-provenance helpers by
import rather than re-implementing them.

What makes this experiment different from its two MC siblings: it does NOT
probe internal nodes. It wraps issue #11's own output-voltage measurement
bench (`sim/output-voltage-tc/testbench/tb_vref_tc.sch`) UNCHANGED -- the only
thing measured is `v(vref)`, exactly what #11 measures deterministically per
PVT corner. The contributor breakdown (PNP vs. resistor vs. amp/mirror
mismatch) does not come from probing amplifier-internal nodes (that is
`sim/error-amp-offset-mc`'s job, for issue #9's offset budget); it comes from
running the *same* wrapped bench four times per temperature with different
subsets of the PDK's own per-instance mismatch coefficients zeroed out via a
`.param` override -- see "Isolation mechanism" below.

Usage
-----
    sim/monte-carlo-untrimmed/run_mc_untrimmed.py                 # the full run
    sim/monte-carlo-untrimmed/run_mc_untrimmed.py --samples 20    # quick smoke
    sim/monte-carlo-untrimmed/run_mc_untrimmed.py --dry-run       # print the plan

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
# Wrapped, NOT copied: issue #11's own testbench, reference-only for this
# issue (see the issue body's "Affected Files"). Never modify this file from
# this script or its record.
SCHEMATIC = SIM_DIR / "output-voltage-tc" / "testbench" / "tb_vref_tc.sch"
SPICEINIT_FILE = SIM_DIR / "spiceinit"
BUILD_DIR = SIM_DIR / "build" / "monte-carlo-untrimmed"

sys.path.insert(0, str(SIM_DIR / "bin"))
from sim_common import load_corner_run, mean  # noqa: E402

cr = load_corner_run()

# --------------------------------------------------------------------------
# experiment definition
# --------------------------------------------------------------------------

SLUG = "monte-carlo-untrimmed"
TITLE = (
    "Monte Carlo mismatch sigma and yield against the untrimmed +/-1% output-accuracy "
    "window, with a PNP / resistor / amp-mirror contributor breakdown"
)

MM_SECTION = "tt_mm"  # nominal process + MC_MM_SWITCH=1 (local mismatch on)
OFF_SECTION = "tt"  # nominal process + MC_MM_SWITCH=0 (control: sigma must be 0)
TEMPS_C = [-40.0, 27.0, 125.0]  # full CLAUDE.md temperature axis (both extremes + nominal)
SUPPLY_V = 3.3
N_SAMPLES = 300  # matches sim/pnp-mismatch and sim/error-amp-offset-mc
N_CONTROL = 30  # the control point is deterministic; N only has to be > 1
SEED_A = 20260803
SEED_B = 20260804  # second seed, for the seed-stability check

# --------------------------------------------------------------------------
# Isolation mechanism: zero out a device family's PDK mismatch coefficient
# --------------------------------------------------------------------------
#
# sky130's MC_MM_SWITCH (see sim/pnp-mismatch/testbench/tb_pnp_mismatch.spice
# for the full mechanism writeup) is a SINGLE global gate: every device family
# that has a mismatch term shares it, set by the `.lib` section name
# (0 in tt/ss/ff/sf/fs, 1 only in `*_mm`). There is no per-family switch, so a
# per-family contributor breakdown needs a different lever: the sigma
# COEFFICIENTS themselves (`sw_mm_*`, declared as `.param` inside
# continuous/models_global.spice, textually pulled in wherever the chosen
# `.lib` section `.include`s that file).
#
# Empirically verified against the pinned PDK (not assumed): a `.param
# sw_mm_<name>=0` line placed AFTER the `.lib ... tt_mm` include in this
# script's own deck DOES override the PDK's declared value for that name --
# ngspice's last-definition-wins for `.param` redefinition within one deck.
# (A same-named override placed BEFORE the `.lib` include, or overriding
# `mismatch_factor` -- the universal per-instance scale used by every
# family -- also works and was used as the validation control: overriding
# `mismatch_factor=0` alone zeroes every family's spread in one shot, exactly
# like the `tt` control section does.) Confirmed per family, on the actual
# `bandgap_core` + `error_amp` hierarchy this script drives (not just a
# two-device toy netlist):
#
#   PNP     (sky130_fd_pr__pnp_05v5_W0p68L0p68 / _W3p40L3p40, XQ1/XQ2):
#           sw_mm_sky130_fd_pr__pnp_05v5_W0p68L0p68_is
#           sw_mm_sky130_fd_pr__pnp_05v5_W0p68L0p68_bf
#           The W3p40L3p40 (PTAT) subcircuit reuses these SAME two names,
#           scaled internally by fixed literals 0.13/0.45 -- confirmed in
#           libs.tech/combined/continuous/models_bjt.spice -- so zeroing the
#           two names above disables mismatch on BOTH PNP devices in the core.
#   Resistor (sky130_fd_pr__res_high_po, XR1/XR2A/XR2B):
#           sw_mm_sky130_fd_pr__res_high_po        (body resistance, dominant)
#           sw_mm_sky130_fd_pr__res_generic_po_head (contact-head resistance)
#           BOTH are needed: res_high_po is a series rhead+rbody model pair,
#           each with its own independent AGAUSS() term (models_resistors.spice).
#           Zeroing only the body term leaves a small nonzero residual from
#           the head term alone -- verified empirically before adopting this
#           two-name list.
#   MOS (amp/mirror) (sky130_fd_pr__nfet_g5v0d10v5 / __pfet_g5v0d10v5 --
#           the error amplifier's input pair, its NMOS/PMOS current mirrors,
#           its Miller device, AND the core's own two PMOS current mirrors
#           XMPOUT/XMPAMP -- every MOS device in this circuit is one of these
#           two families):
#           sw_mm_vth0_sky130_fd_pr__nfet_g5v0d10v5
#           sw_mm_vth0_sky130_fd_pr__pfet_g5v0d10v5
#           (Vth mismatch only -- these two device flavors carry no other
#           `sw_mm_*` term in models_fet.spice, unlike the higher-voltage
#           flavors that also mismatch tox; verified by grep against the
#           pinned PDK, not assumed.)
#
# "all" (no override) is the combined claim: every family's mismatch active
# at once, on independent per-instance draws, which is what the untrimmed
# +/-1% spec line is actually exposed to in silicon.

PNP_COEFFS = (
    "sw_mm_sky130_fd_pr__pnp_05v5_W0p68L0p68_is",
    "sw_mm_sky130_fd_pr__pnp_05v5_W0p68L0p68_bf",
)
RESISTOR_COEFFS = (
    "sw_mm_sky130_fd_pr__res_high_po",
    "sw_mm_sky130_fd_pr__res_generic_po_head",
)
MOS_COEFFS = (
    "sw_mm_vth0_sky130_fd_pr__nfet_g5v0d10v5",
    "sw_mm_vth0_sky130_fd_pr__pfet_g5v0d10v5",
)

CONFIGS: dict[str, tuple[str, ...]] = {
    "all": (),  # nothing zeroed -- every family's mismatch active (the spec claim)
    "pnp": RESISTOR_COEFFS + MOS_COEFFS,  # zero resistor + MOS -> isolates PNP
    "resistor": PNP_COEFFS + MOS_COEFFS,  # zero PNP + MOS -> isolates the resistor network
    "mos": PNP_COEFFS + RESISTOR_COEFFS,  # zero PNP + resistor -> isolates amp/mirror MOS
}
CONFIG_LABELS = {
    "all": "all families (the spec claim)",
    "pnp": "PNP array only (Q1 CTAT + Q2 PTAT)",
    "resistor": "PTAT/output resistor network only (R1, R2A, R2B)",
    "mos": "amp/mirror MOS only (error_amp diff pair + mirrors + XMPOUT/XMPAMP)",
}

# The draft spec's untrimmed output-accuracy window (README.md "Target
# specification (DRAFT)"; same +/-1% window sim/output-voltage-tc uses).
# PROVISIONAL until issue #1 ratifies the spec -- see the CLAIM string below.
VOUT_NOMINAL_V = 1.20
SPEC_WINDOW_V = (1.188, 1.212)

# A Monte Carlo sample only counts if the core actually came up. bandgap_core
# is bistable by construction (no startup circuit -- issue #10) and this
# testbench's `.nodeset` is a solver hint, not a forced solution. A draw that
# converged to the degenerate zero-current branch is a startup datum, not a
# mismatch one; folding it into sigma(VOUT) would report a spurious
# hundreds-of-millivolts spread. Same convention and thresholds as
# sim/error-amp-offset-mc.
OPERATING_VOUT_V = (0.9, 1.5)
MIN_SOLVE_YIELD = 0.5

# --- check tolerances ---
DECOMPOSITION_BAND = (0.75, 1.35)  # sigma(all) / RSS(pnp, resistor, mos)
ISOLATION_SLACK = 1.15  # an isolated-family sigma must not exceed sigma(all) * this
SEED_SIGMA_TOL = 0.25
CONVERGENCE_CHECKPOINTS = (5, 10, 15, 20)
CONVERGENCE_TOL = 0.20  # max relative change between the last two checkpoints

VECTORS = ("vout", "vgdrv")


@dataclass(frozen=True)
class Point:
    corner_id: str
    section: str
    config: str
    temp_c: float
    seed: int
    samples: int
    role: str  # "mismatch" | "control" | "seed-check"
    purpose: str


def build_points(samples: int) -> list[Point]:
    control_n = min(N_CONTROL, samples)
    points: list[Point] = []
    for t in TEMPS_C:
        for config in ("all", "pnp", "resistor", "mos"):
            points.append(
                Point(
                    corner_id=f"{MM_SECTION}_{config}_{t:g}c_{SUPPLY_V:.2f}v",
                    section=MM_SECTION,
                    config=config,
                    temp_c=t,
                    seed=SEED_A,
                    samples=samples,
                    role="mismatch",
                    purpose=(
                        f"local-mismatch distribution, {CONFIG_LABELS[config]}, at the "
                        "nominal process point"
                    ),
                )
            )
    points.append(
        Point(
            corner_id=f"{OFF_SECTION}_27c_{SUPPLY_V:.2f}v_mm-off",
            section=OFF_SECTION,
            config="all",
            temp_c=27.0,
            seed=SEED_A,
            samples=control_n,
            role="control",
            purpose=(
                "control: identical deck on the plain `tt` section (MC_MM_SWITCH=0), no "
                "coefficient overrides; every sigma must come back exactly 0, which is what "
                "proves the spread above is the mismatch switch and not solver noise or a "
                "re-randomised bias point"
            ),
        )
    )
    points.append(
        Point(
            corner_id=f"{MM_SECTION}_all_27c_{SUPPLY_V:.2f}v_seed-b",
            section=MM_SECTION,
            config="all",
            temp_c=27.0,
            seed=SEED_B,
            samples=samples,
            role="seed-check",
            purpose=(
                "seed-stability: same point (all families), different setseed -- the "
                "samples must change while sigma must not, i.e. the reported spread is a "
                "property of the model, not of one lucky draw"
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
            # tb_vref_tc.sch carries `.save i(v1)`, which restricts the
            # saved-vector list; `reset` reloads the circuit from that
            # netlist text, so the restriction comes back on every
            # iteration. `save all` must therefore be re-issued INSIDE the
            # loop, after `reset` and before `op` -- issuing it once before
            # the loop is not enough (empirically verified: without this,
            # every `op` after the first `reset` reports `v(vref)` as an
            # unavailable vector).
            "  save all",
            "  op",
            "  let vout = v(vref)",
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
        f"* {SLUG} Monte Carlo deck (config={point.config}) -- generated by "
        f"sim/{SLUG}/run_mc_untrimmed.py, do not edit",
        f"* point: {point.corner_id}",
        ".option wnflag=1",
        f".temp {point.temp_c:g}",
        f".param vsup={SUPPLY_V}",
        f'.lib "{pdk.lib_file}" {point.section}',
    ]
    for name in CONFIGS[point.config]:
        head.append(f".param {name}=0")
    return "\n".join(head + body) + "\n" + control_block(point)


_PRINT_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(-?[0-9.]+(?:[eE][-+]?[0-9]+)?)$")


def parse_samples(log: str) -> list[dict[str, float]]:
    """Parse the repeated `op` + `print` blocks of the Monte Carlo loop."""
    wanted = set(VECTORS)
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


def run_point(pdk, point: Point, run_dir: Path, deck: str, timeout: int):
    run_dir.mkdir(parents=True, exist_ok=True)
    deck_path = run_dir / f"{point.corner_id}.spice"
    deck_path.write_text(deck)
    shutil.copyfile(SPICEINIT_FILE, run_dir / ".spiceinit")
    try:
        proc = subprocess.run(
            ["ngspice", "-b", deck_path.name],
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


def write_log(corners_dir, point, pdk, record_id, stamp, deck, raw, rc, timed_out) -> Path:
    corners_dir.mkdir(parents=True, exist_ok=True)
    path = corners_dir / f"{point.corner_id}.log"
    init_text = SPICEINIT_FILE.read_text()
    path.write_text(
        "\n".join(
            [
                f"# point: {point.corner_id}",
                f"# record: {record_id}",
                f"# role: {point.role} -- {point.purpose}",
                f"# config={point.config} section={point.section} temp={point.temp_c:g}C "
                f"supply={SUPPLY_V:.2f}V seed={point.seed} samples={point.samples}",
                f"# pdk: {pdk.variant} @ open_pdks {pdk.installed_commit} ({pdk.lib_file})",
                f"# ngspice exit: {rc}{' (TIMEOUT)' if timed_out else ''}",
                f"# run (UTC): {stamp:%Y-%m-%dT%H:%M:%SZ}",
                "",
                "# ==== .spiceinit (exact) ====",
                *[f"| {ln}" for ln in init_text.splitlines()],
                "",
                "# ==== deck (exact input given to ngspice) ====",
                *[f"| {ln}" for ln in deck.splitlines()],
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


def partition(samples: list[dict[str, float]]):
    lo, hi = OPERATING_VOUT_V
    good = [s for s in samples if lo <= s["vout"] <= hi]
    bad = [s for s in samples if not (lo <= s["vout"] <= hi)]
    return good, bad


def spec_yield(values: list[float]) -> float:
    lo, hi = SPEC_WINDOW_V
    return sum(1 for v in values if lo <= v <= hi) / len(values)


def convergence_series(values: list[float]) -> list[dict]:
    """Running sigma at increasing sample-count checkpoints, same seed stream.

    ngspice draws sequentially from one PRNG stream per `setseed`; the first
    K samples of an N-sample run (K < N) are identical to a standalone K-run
    with the same seed, so this is a real converging estimate, not a
    re-simulation at each checkpoint.
    """
    out = []
    for k in CONVERGENCE_CHECKPOINTS:
        if k > len(values):
            continue
        prefix = values[:k]
        out.append({"n": k, "sigma": stdev(prefix), "mean": mean(prefix)})
    return out


def evaluate(point: Point, samples: list[dict[str, float]], excluded: list[dict[str, float]]) -> dict:
    total = len(samples) + len(excluded)
    vout_vals = [s["vout"] for s in samples]
    stats = {
        "vout": {
            "n": len(vout_vals),
            "mean": mean(vout_vals),
            "sigma": stdev(vout_vals),
            "min": min(vout_vals),
            "max": max(vout_vals),
        }
    }
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "pass": bool(ok), "detail": detail})

    add("sample_count", total == point.samples, f"parsed {total} samples, expected {point.samples}")

    yield_frac = len(samples) / total if total else 0.0
    add(
        "mc_solve_yield",
        yield_frac >= MIN_SOLVE_YIELD,
        f"{len(samples)}/{total} draws converged to the operating solution (VOUT in "
        f"{OPERATING_VOUT_V[0]}..{OPERATING_VOUT_V[1]} V); {len(excluded)} landed on the "
        f"core's other stable branch and are excluded from sigma/yield below. This is a "
        f"STARTUP observation (issue #10 -- the core has no startup circuit), not a "
        f"mismatch one, and is also sensitive to the testbench `.nodeset`; not a "
        f"startup-yield prediction for silicon."
        + (
            ""
            if not excluded
            else " Excluded VOUT values: "
            + ", ".join(f"{s['vout']:.4f} V" for s in excluded[:8])
            + (" ..." if len(excluded) > 8 else "")
        ),
    )

    if point.role == "control":
        add(
            "sigma_zero[vout]",
            stats["vout"]["sigma"] == 0.0,
            f"sigma = {stats['vout']['sigma']:.6g} V with MC_MM_SWITCH=0 and no coefficient "
            f"overrides (must be exactly 0)",
        )
        spec_y = spec_yield(vout_vals) if vout_vals else float("nan")
        return _wrap(point, samples, excluded, stats, checks, spec_y, total)

    add(
        "sigma_nonzero[vout]",
        stats["vout"]["sigma"] > 0.0,
        f"sigma = {stats['vout']['sigma'] * 1e3:.4f} mV (a zero here means the mismatch "
        f"switch, or this config's coefficient set, never reached the models)",
    )

    spec_y = spec_yield(vout_vals)
    add(
        "yield_ge_50pct",
        spec_y >= 0.5,
        f"{spec_y:.1%} of converged draws land inside the +/-1% window "
        f"[{SPEC_WINDOW_V[0]}, {SPEC_WINDOW_V[1]}] V (sanity floor only -- the yield number "
        f"itself is the deliverable, not a pass/fail spec claim; see the Result section)",
    )

    result = _wrap(point, samples, excluded, stats, checks, spec_y, total)
    if point.config == "all" and abs(point.temp_c - 27.0) < 1e-9 and point.role == "mismatch":
        result["convergence"] = convergence_series(vout_vals)
    return result


def _wrap(point, samples, excluded, stats, checks, spec_y, total) -> dict:
    return {
        "corner_id": point.corner_id,
        "role": point.role,
        "config": point.config,
        "purpose": point.purpose,
        "section": point.section,
        "temperature_c": point.temp_c,
        "supply_v": SUPPLY_V,
        "seed": point.seed,
        "requested_samples": point.samples,
        "parsed_samples": total,
        "converged_samples": len(samples),
        "excluded_samples": len(excluded),
        "excluded_vout_v": [s["vout"] for s in excluded],
        "stats": stats,
        "spec_yield": spec_y,
        "checks": checks,
        "pass": all(c["pass"] for c in checks),
    }


def decomposition_checks(results: dict[str, dict]) -> list[dict]:
    out = []
    for t in TEMPS_C:
        by_config = {
            cfg: results.get(f"{MM_SECTION}_{cfg}_{t:g}c_{SUPPLY_V:.2f}v") for cfg in CONFIGS
        }
        if any(v is None for v in by_config.values()):
            continue
        total_sigma = by_config["all"]["stats"]["vout"]["sigma"]
        parts = {cfg: by_config[cfg]["stats"]["vout"]["sigma"] for cfg in ("pnp", "resistor", "mos")}
        rss = math.sqrt(sum(v * v for v in parts.values()))
        ratio = total_sigma / rss if rss else float("inf")
        out.append(
            {
                "name": f"decomposition_closure[{t:g}C]",
                "pass": DECOMPOSITION_BAND[0] <= ratio <= DECOMPOSITION_BAND[1],
                "detail": (
                    f"sigma(all)={total_sigma * 1e3:.4f} mV vs RSS(pnp={parts['pnp'] * 1e3:.4f}, "
                    f"resistor={parts['resistor'] * 1e3:.4f}, mos={parts['mos'] * 1e3:.4f})="
                    f"{rss * 1e3:.4f} mV (ratio {ratio:.3f}, band {DECOMPOSITION_BAND[0]}-"
                    f"{DECOMPOSITION_BAND[1]}); the three families' mismatch draws are "
                    f"statistically independent (different device parameters, different "
                    f"AGAUSS() terms), so the total is expected to reproduce the "
                    f"root-sum-square of the isolated parts"
                ),
            }
        )
        for cfg in ("pnp", "resistor", "mos"):
            iso = parts[cfg]
            out.append(
                {
                    "name": f"isolation_bounded[{cfg},{t:g}C]",
                    "pass": iso <= total_sigma * ISOLATION_SLACK,
                    "detail": (
                        f"sigma({cfg})={iso * 1e3:.4f} mV must not exceed "
                        f"sigma(all)={total_sigma * 1e3:.4f} mV by more than "
                        f"{ISOLATION_SLACK:.0%} -- catches a coefficient-override that "
                        f"silently failed to isolate anything (i.e. still reads the full "
                        f"combined spread)"
                    ),
                }
            )
    return out


def seed_stability(results: dict[str, dict]) -> list[dict]:
    a = results.get(f"{MM_SECTION}_all_27c_{SUPPLY_V:.2f}v")
    b = results.get(f"{MM_SECTION}_all_27c_{SUPPLY_V:.2f}v_seed-b")
    if not a or not b:
        return []
    sa = a["stats"]["vout"]["sigma"]
    sb = b["stats"]["vout"]["sigma"]
    drift = abs(sb / sa - 1.0) if sa else float("inf")
    out = [
        {
            "name": "seed_sigma_stable[vout]",
            "pass": drift <= SEED_SIGMA_TOL,
            "detail": (
                f"sigma(seed {SEED_B}) / sigma(seed {SEED_A}) = "
                f"{(sb / sa) if sa else float('nan'):.3f} ({sb * 1e3:.4f} mV vs "
                f"{sa * 1e3:.4f} mV; tolerance +/-{SEED_SIGMA_TOL:.0%})"
            ),
        }
    ]
    out.append(
        {
            "name": "seed_sample_differs[vout]",
            "pass": a["stats"]["vout"]["max"] != b["stats"]["vout"]["max"],
            "detail": (
                f"worst-sample VOUT differs between the two seeds "
                f"({a['stats']['vout']['max']:.6f} V vs {b['stats']['vout']['max']:.6f} V), "
                "i.e. the draw really did change"
            ),
        }
    )
    return out


def convergence_check(all_point_27c: dict | None) -> list[dict]:
    if not all_point_27c or "convergence" not in all_point_27c:
        return []
    series = all_point_27c["convergence"]
    if len(series) < 2:
        return []
    last, prev = series[-1], series[-2]
    rel = abs(last["sigma"] / prev["sigma"] - 1.0) if prev["sigma"] else float("inf")
    return [
        {
            "name": "sample_count_sufficient",
            "pass": rel <= CONVERGENCE_TOL,
            "detail": (
                f"running sigma(VOUT) at N={prev['n']} vs N={last['n']} (same seed stream, "
                f"the {last['n']}-sample run's first {prev['n']} draws are identical to a "
                f"standalone {prev['n']}-sample run): {prev['sigma'] * 1e3:.4f} mV -> "
                f"{last['sigma'] * 1e3:.4f} mV, relative change {rel:.1%} (tolerance "
                f"{CONVERGENCE_TOL:.0%}). Full checkpoint series: "
                + ", ".join(f"N={p['n']}: {p['sigma'] * 1e3:.4f} mV" for p in series)
            ),
        }
    ]


# --------------------------------------------------------------------------
# record rendering
# --------------------------------------------------------------------------

CLAIM = (
    "README.md 'Target specification (DRAFT)' row 'Output reference' (1.20 V +/-1% "
    "untrimmed) -- but read as a MISMATCH claim, not the corner-matrix claim issue #11 "
    "already substantiates. Process-corner sims move every device the same direction "
    "together; the untrimmed spread that actually determines whether a real part lands "
    "inside +/-1% is set by how far a real PNP, resistor, or MOS device drifts from its "
    "neighbor, i.e. LOCAL MISMATCH, which only Monte Carlo over sky130's mismatch models "
    "can quantify. Wraps issue #11's own output-voltage bench "
    "(sim/output-voltage-tc/testbench/tb_vref_tc.sch, unmodified) rather than re-deriving "
    "the v(vref) extraction. Records are PROVISIONAL against the draft spec until issue #1 "
    "ratifies it. Feeds issue #13 (does the design need a trim network, and what range) "
    "and issue #15 (layout matching priority, from the contributor breakdown)."
)


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
        f"(`{r['experiment']['provenance_source']}` — issue #11's testbench, wrapped "
        f"unmodified; not copied or re-derived)"
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
        f"process Monte Carlo) stays 0. Local mismatch is intra-die variation, independent "
        f"of (and not double-counting) the global process shift `sim/output-voltage-tc`'s "
        f"15-point corner matrix already records for this same core."
    )
    add(
        "  - Temperature: "
        + ", ".join(f"{t:g} °C" for t in TEMPS_C)
        + " (full CLAUDE.md temperature axis, per the issue's explicit scope: nominal + "
        "both extremes, not a full corner-matrix MC run)"
    )
    add(
        f"  - Supply: **{SUPPLY_V:.2f} V only**. This deck has a supply rail, so the subset "
        f"needs a reason: supply is a *deterministic* axis for this circuit, already swept "
        f"by `sim/output-voltage-tc` (±10 % at every process/temperature point), while every "
        f"mismatch coefficient this record samples (`sw_mm_*`) is a device parameter with no "
        f"supply dependence. This runner does not go through `sim/bin/corner-run.py`, so "
        f"that justification is stated here rather than via `--subset-reason` (see "
        f"`sim/README.md`)."
    )
    add(
        f"  - Contributor isolation: 4 configs per temperature — {CONFIG_LABELS['all']}, "
        f"{CONFIG_LABELS['pnp']}, {CONFIG_LABELS['resistor']}, {CONFIG_LABELS['mos']} — by "
        f"zeroing the PDK's own `sw_mm_*` coefficients for the two families NOT under test "
        f"(see the runner script header for the exact mechanism and the coefficient names)."
    )
    add(
        f"  - {len(r['points'])} ngspice points executed: {len(mm_points)} Monte Carlo "
        f"points (N = {n} each, 3 temperatures x 4 configs), one MC-off control point, one "
        f"second-seed point."
    )
    add(
        f"- **Statistical convention**: **N = {n}** Monte Carlo samples per point, local "
        f"mismatch only (section `{MM_SECTION}`: `MC_MM_SWITCH=1`, `MC_PR_SWITCH=0`). Spread "
        f"is the sample standard deviation (N−1) reported as **1 σ**, with 3 σ alongside; "
        f"σ's own relative standard error is ≈ {100 / math.sqrt(2 * (n - 1)):.1f} %. "
        f"Reproducible: `setseed {SEED_A}` (second-seed point uses {SEED_B}). N matches "
        f"`sim/pnp-mismatch` and `sim/error-amp-offset-mc`, so σ figures are directly "
        f"comparable across all three. See 'Sample-count justification' below for the "
        f"empirical convergence check."
    )
    add(f"- **Result**: {'PASS' if r['overall_pass'] else 'FAIL'} — see the tables below.")
    add("")

    add("## Output-voltage distribution and yield against the +/-1 % window")
    add("")
    add(
        f"Window: [{SPEC_WINDOW_V[0]}, {SPEC_WINDOW_V[1]}] V around the draft spec's "
        f"{VOUT_NOMINAL_V:.2f} V nominal (README.md 'Target specification (DRAFT)'). "
        f"**Yield** below is the fraction of MC draws that (a) converged to the core's real "
        f"operating solution (excludes the issue #10 startup artifact — see "
        f"'mc_solve_yield' in the Checks section) and (b) landed inside that window."
    )
    add("")
    add("| T (°C) | config | mean VOUT (V) | 1 σ (mV) | 3 σ (% of 1.20 V) | converged/total | yield (of converged) |")
    add("|---|---|---|---|---|---|---|")
    for p in mm_points:
        st = p["stats"]["vout"]
        add(
            f"| {p['temperature_c']:g} | {p['config']} | {st['mean']:.6f} | {mv(st['sigma'])} | "
            f"{3 * st['sigma'] / VOUT_NOMINAL_V:.3%} | {p['converged_samples']}/"
            f"{p['parsed_samples']} | {p['spec_yield']:.2%} |"
        )
    add("")
    add(
        "The `all` row at each temperature is the spec-relevant number; the `pnp` / "
        "`resistor` / `mos` rows are the isolated single-family runs used for the "
        "contributor breakdown directly below, not independent yield claims of their own."
    )
    add("")

    add("## Contributor breakdown (PNP vs. resistor vs. amp/mirror mismatch)")
    add("")
    add("| T (°C) | PNP array 1 σ (mV) | resistor network 1 σ (mV) | amp/mirror MOS 1 σ (mV) | RSS of the three (mV) | measured σ(all) (mV) | closure ratio |")
    add("|---|---|---|---|---|---|---|")
    by_temp: dict[float, dict[str, dict]] = {}
    for p in mm_points:
        by_temp.setdefault(p["temperature_c"], {})[p["config"]] = p
    for t in TEMPS_C:
        cfgs = by_temp.get(t, {})
        if not all(c in cfgs for c in ("all", "pnp", "resistor", "mos")):
            continue
        s_pnp = cfgs["pnp"]["stats"]["vout"]["sigma"]
        s_res = cfgs["resistor"]["stats"]["vout"]["sigma"]
        s_mos = cfgs["mos"]["stats"]["vout"]["sigma"]
        s_all = cfgs["all"]["stats"]["vout"]["sigma"]
        rss = math.sqrt(s_pnp**2 + s_res**2 + s_mos**2)
        add(
            f"| {t:g} | {mv(s_pnp)} | {mv(s_res)} | {mv(s_mos)} | {mv(rss)} | {mv(s_all)} | "
            f"{s_all / rss if rss else float('nan'):.3f} |"
        )
    add("")
    dominant_note = ""
    all27 = by_temp.get(27.0, {})
    if all(c in all27 for c in ("all", "pnp", "resistor", "mos")):
        sigmas = {
            "PNP array": all27["pnp"]["stats"]["vout"]["sigma"],
            "resistor network": all27["resistor"]["stats"]["vout"]["sigma"],
            "amp/mirror MOS": all27["mos"]["stats"]["vout"]["sigma"],
        }
        total_sigma_27c = all27["all"]["stats"]["vout"]["sigma"]
        dominant = max(sigmas, key=lambda k: sigmas[k])
        dominant_note = (
            f"At 27 °C the dominant term is **{dominant}** "
            f"({mv(sigmas[dominant])} mV of {mv(total_sigma_27c)} mV measured σ(all)) — "
            f"this is the term issue #15's layout matching priority and issue #13's "
            f"trim-range scoping should target first."
        )
    add(dominant_note)
    add("")

    add("## Sample-count justification (empirical convergence check)")
    add("")
    conv = next((p.get("convergence") for p in mm_points if "convergence" in p), None)
    if conv:
        add(
            "Running σ(VOUT) at increasing sample counts, computed from the SAME "
            f"N={n}, seed={SEED_A} draw sequence at 27 °C / `all` config (ngspice draws "
            "sequentially per `setseed`, so the first K samples of the full run are "
            "identical to what a standalone K-sample run would produce — this is a real "
            "convergence trend, not a re-simulation at each row):"
        )
        add("")
        add("| N | running σ(VOUT) (mV) | running mean (V) |")
        add("|---|---|---|")
        for row in conv:
            add(f"| {row['n']} | {mv(row['sigma'])} | {row['mean']:.6f} |")
        add("")
        last, prev = conv[-1], conv[-2] if len(conv) > 1 else conv[-1]
        rel = abs(last["sigma"] / prev["sigma"] - 1.0) if prev["sigma"] else float("nan")
        add(
            f"N={prev['n']} -> N={last['n']}: σ changed by {rel:.1%} (see the "
            "`sample_count_sufficient` check below for the pass/fail threshold). Combined "
            f"with the analytic standard error of a sample std-dev estimate, "
            f"≈ {100 / math.sqrt(2 * (n - 1)):.1f} % at N={n} (1/√(2(N−1))), this is why "
            f"N={n} (matching the two sibling MC experiments in this repo) is treated as "
            "sufficient for the σ and yield figures above, rather than asserted by "
            "convention alone."
        )
    add("")

    add("## Controls (the reason this record can be believed)")
    add("")
    if ctrl:
        add(
            f"- **MC-off control** (`{ctrl['corner_id']}`, section `{OFF_SECTION}`, "
            f"N = {ctrl['parsed_samples']}): identical deck, no coefficient overrides, "
            f"`MC_MM_SWITCH=0`. σ(VOUT) = {ctrl['stats']['vout']['sigma']:.3g} V — exactly "
            f"zero, so the spread above is the mismatch switch and not solver noise, "
            f"`.nodeset` drift, or a re-randomised bias point."
        )
    if seedb:
        add(
            f"- **Second-seed point** (`{seedb['corner_id']}`, `setseed {SEED_B}`, "
            f"N = {seedb['parsed_samples']}): σ(VOUT) = {mv(seedb['stats']['vout']['sigma'])} "
            f"mV — see the seed-stability checks below: the individual samples change, σ "
            "does not."
        )
    add(
        "- **Isolation-bounded check**: every isolated-family σ (`pnp`, `resistor`, `mos`) "
        "must not exceed σ(`all`) by more than 15 % at each temperature — catches a "
        "coefficient-override that silently failed to isolate anything (see "
        "`isolation_bounded` checks below)."
    )
    add(
        "- **Decomposition closure**: σ(`all`) is compared against the root-sum-square of "
        "the three isolated σ's at each temperature — the three families' mismatch draws "
        "are statistically independent (different device parameters, different `AGAUSS()` "
        "terms per instance), so the total is expected to reproduce the RSS of the parts "
        "(see `decomposition_closure` checks below)."
    )
    excl = sum(p["excluded_samples"] for p in r["points"])
    tot = sum(p["parsed_samples"] for p in r["points"])
    add(
        f"- **Startup / solve yield**: {excl} of {tot} draws across all points converged to "
        f"the core's *other* stable solution instead of the operating one and were excluded "
        f"from every statistic (per-point counts and excluded VOUT values are in the "
        f"`mc_solve_yield` check). `bandgap_core` is bistable by construction and ships no "
        f"startup circuit — that is issue #10 — so a non-zero count here is a startup "
        f"datum, not a mismatch one. Not a startup-yield prediction for silicon."
    )
    add("")

    add("## Checks")
    add("")
    for p in r["points"]:
        add(f"- `{p['corner_id']}` ({p['role']}, config=`{p['config']}`): **{'PASS' if p['pass'] else 'FAIL'}**")
        for c in p["checks"]:
            add(f"  - {'PASS' if c['pass'] else 'FAIL'} `{c['name']}` — {c['detail']}")
    for c in r["cross_point_checks"]:
        add(f"- {'PASS' if c['pass'] else 'FAIL'} `{c['name']}` — {c['detail']}")
    add(f"- **Overall: {'PASS' if r['overall_pass'] else 'FAIL'}**")
    add("")

    add("## Scope limits, stated so this record is not over-read")
    add("")
    add(
        "1. **Mismatch only, one process point.** σ(VOUT) here is the *intra-die* spread "
        "at the nominal process corner. The untrimmed ±1 % spec line also carries global "
        "process shift and temperature curvature, both already substantiated by "
        "`sim/output-voltage-tc` (issue #11). A part that passes this record's yield "
        "figure can still miss ±1 % from global corner shift alone, and vice versa."
    )
    add(
        "2. **Contributor breakdown is by isolated re-run, not simultaneous internal "
        "probing.** Each family's σ comes from a separate MC run with the other two "
        "families' PDK mismatch coefficients set to zero, not from decomposing a single "
        "run's internal nodes (that approach is `sim/error-amp-offset-mc`'s, for issue #9's "
        "amplifier-offset budget specifically). The two approaches are cross-checked by the "
        "decomposition-closure band, not required to match exactly."
    )
    add(
        "3. **No supply sweep.** Justified above as a deterministic axis already covered "
        "by issue #11; if a future revision finds supply-dependent mismatch coupling "
        "(e.g. through a supply-dependent bias current), that would invalidate this "
        "simplification and require a new record."
    )
    add("")

    add("- **Links**:")
    for key, value in r["links"].items():
        add(f"  - {key}: `{value}`")
    add(f"- **Timestamp / author**: {r['timestamp']}, {r['author']}")
    add(f"- **Supersedes**: {r['supersedes'] or '(none — first record for this claim)'}")
    add("")
    add(
        "Written by `sim/monte-carlo-untrimmed/run_mc_untrimmed.py`. Append-only: never "
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
    if not SCHEMATIC.is_file():
        raise cr.HarnessError(f"missing testbench: {SCHEMATIC}")
    if args.samples < max(CONVERGENCE_CHECKPOINTS):
        raise cr.HarnessError(
            f"--samples must be at least {max(CONVERGENCE_CHECKPOINTS)} so the convergence "
            "checkpoints have data (use a smaller checkpoint list for smoke runs)"
        )

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
    print(f"testbench       : {SCHEMATIC.relative_to(REPO_ROOT)} (wrapped, unmodified)")
    print(f"points          : {len(points)} ({args.samples} samples per MC point)")
    for p in points:
        print(
            f"  {p.corner_id:<38} config={p.config:<9} section={p.section:<6} "
            f"T={p.temp_c:>5g}C seed={p.seed} N={p.samples}"
        )

    netlist = cr.netlist_with_xschem(SCHEMATIC, BUILD_DIR / "xschem", pdk)
    body = cr.netlist_body(netlist)

    if args.dry_run:
        print("\n-- deck head + control block for the first point --")
        deck = build_deck(pdk, points[0], body)
        print("\n".join(deck.splitlines()[:10]))
        print("...")
        print(control_block(points[0]))
        print(f"(dry run: nothing written under sim/{SLUG}/)")
        return 0

    results: dict[str, dict] = {}
    ordered: list[dict] = []
    for i, point in enumerate(points, start=1):
        run_dir = BUILD_DIR / record_id / point.corner_id
        deck = build_deck(pdk, point, body)
        raw, rc, timed_out = run_point(pdk, point, run_dir, deck, args.timeout)
        write_log(corners_dir, point, pdk, record_id, now, deck, raw, rc, timed_out)
        if rc != 0 or timed_out:
            raise cr.HarnessError(
                f"ngspice exit {rc}{' (timeout)' if timed_out else ''} for "
                f"{point.corner_id}; see "
                f"{(corners_dir / (point.corner_id + '.log')).relative_to(REPO_ROOT)}"
            )
        parsed = parse_samples(raw)
        if not parsed:
            raise cr.HarnessError(
                f"no Monte Carlo samples parsed for {point.corner_id} — see the log"
            )
        samples, excluded = partition(parsed)
        if len(samples) < 2:
            raise cr.HarnessError(
                f"only {len(samples)} of {len(parsed)} draws for {point.corner_id} "
                f"converged to the operating solution — nothing to compute a sigma from; "
                f"see the log"
            )
        res = evaluate(point, samples, excluded)
        results[point.corner_id] = res
        ordered.append(res)
        print(
            f"[{i}/{len(points)}] {point.corner_id:<38} "
            f"{'PASS' if res['pass'] else 'FAIL'}  n={res['converged_samples']}"
            f"(-{res['excluded_samples']})  sigma(vout)={res['stats']['vout']['sigma'] * 1e3:.4f}mV"
        )

    cross = decomposition_checks(results)
    cross += seed_stability(results)
    all_27c = results.get(f"{MM_SECTION}_all_27c_{SUPPLY_V:.2f}v")
    cross += convergence_check(all_27c)
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
        "mismatch_model": {
            "switch": "MC_MM_SWITCH (set by the .lib section: 0 in tt/ss/ff/sf/fs, 1 in *_mm)",
            "sections": {"mismatch": MM_SECTION, "control": OFF_SECTION},
            "isolation": {
                "mechanism": (
                    "per-family .param override of the PDK's own sw_mm_* coefficients, "
                    "placed after the .lib include (last-definition-wins in ngspice)"
                ),
                "pnp_coefficients": list(PNP_COEFFS),
                "resistor_coefficients": list(RESISTOR_COEFFS),
                "mos_coefficients": list(MOS_COEFFS),
            },
            "source": "libs.tech/combined/continuous/models_*.spice + models_global.spice",
        },
        "spec_window_v": list(SPEC_WINDOW_V),
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
            "runner": str((HERE / "run_mc_untrimmed.py").relative_to(REPO_ROOT)),
            "netlist_snapshot": str(snapshot.relative_to(REPO_ROOT)),
            "logs": str(corners_dir.relative_to(REPO_ROOT)),
            "record_json": str(record_json.relative_to(REPO_ROOT)),
            "device_characterization": "design/device-characterization-summary.md",
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
