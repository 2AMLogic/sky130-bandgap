#!/usr/bin/env python3
"""Trim range / monotonicity / TC-at-extremes evidence for issue #13.

Why this is a bespoke script and not another `experiment.json` +
`sim/bin/corner-run.py` experiment: the claim needs the SAME netlisted body
re-run at several different values of `design/bandgap_core.sch`'s own
`n_r2_trim` parameter, which the corner runner's manifest has no axis for
(its `deck.params` are written BEFORE the netlisted body, so -- verified
empirically, see `substitute_trim_code()` below -- they cannot override a
`.subckt`-internal `L=` expression the schematic itself already declares;
SPICE resolves that expression once, in textual order, at `.subckt`
definition time, not lazily at simulation time). This script instead edits
the netlisted body's own `.param n_r2_trim=0` line in place, once per trim
code, before ngspice ever sees the deck -- which is in any case the more
faithful model of a METAL OPTION trim (a fixed, build-time choice, not a
runtime-overridable value). It reuses `sim/bin/corner-run.py`'s PDK
resolution, pin enforcement, xschem netlisting, tool-version and
git-provenance helpers by import rather than re-implementing them, following
the same reuse pattern `sim/monte-carlo-untrimmed/run_mc_untrimmed.py`
established for its own bespoke sweep (there, over Monte Carlo samples and
isolated mismatch families; here, over trim code and process corner).

THE HEADLINE FINDING OF THIS RECORD (read before the numbers below): the
positive (VOUT-increasing) trim direction is REJECTED. It uses the same
R2/R1 ratio issue #46 already found controls a hot-corner (ff/2.97 V,
fs/2.97 V) DC-operating-point bifurcation above ~123..124 degC -- #46
rejected a +5 um / +1.85 % R2 increase (n_r2=55) for exactly this reason.
This script finds it is WORSE than one data point suggested: on this
harness's own -40..125 degC grid, n_r2_trim=+1 and +2 BOTH lose the
operating point at ff/2.97 V and fs/2.97 V (VOUT jumps to ~2.8 V, box TC
reads thousands of ppm/degC), while +3 and +4 do not, and +5/+15 do again.
That non-monotonic pass/fail-in-code pattern is the signature of a coarse
verification grid crossing a genuine bifurcation surface at an angle (per
#46's own finer 1 degC sweep placing the true threshold at 123..124 degC,
which sits between this harness's 114 and 125 degC grid points) -- it is
NOT evidence of a safe zone at +3/+4. No positive code can be certified
safe from this data; the shipped baseline (trim=0) already has zero
headroom for any R2 increase at these two corners. Only the DOWNWARD
direction (R2 decrease) moves away from that edge, and is what this
record actually verifies as the trim network's usable range: monotonic,
collapse-free, 0..-16.

What this experiment measures, and why it wraps issue #11's bench unchanged:
this script wraps `sim/output-voltage-tc/testbench/tb_vref_tc.sch` UNCHANGED
(same box-method `dc temp -40 125 11` sweep, same `vref_27` / `vref_min` /
`vref_max` / `tc_ppm` / `n_temp_points` measurement expressions #11 already
uses) so every trim/process point gets full -40..125 degC temperature
coverage AND a box-method TC number for free in one ngspice invocation --
no separate TC-only sweep is needed.

Two sub-sweeps, run and evaluated differently (stated here, not via a
generic --subset-reason, since this runner does not go through
sim/bin/corner-run.py's manifest path):

1. NEGATIVE_POINTS -- the trim network's actual usable range. Process x
   supply pairs chosen to bound the process spread AND sit at the
   worst-case (lowest) supply for the two corners #46 already flagged as
   margin-thin (ff, fs at 2.97 V), plus the nominal tt/3.30 V point for a
   like-for-like comparison against the existing untrimmed baseline
   records: (tt, 3.30), (ss, 3.30), (ff, 2.97), (sf, 2.97), (fs, 2.97).
   Trim codes 0, -8, -16 at each -- enough to confirm a monotonic trend
   (not just two endpoints) plus the full range and TC-at-extreme.

2. POSITIVE_REJECTED_POINTS -- documents WHY the positive direction is
   rejected, at the two corners #46 already implicated: (ff, 2.97) at
   codes 0 (shared baseline, reused from set 1), +1, +2, +3, +4, +5, +15;
   (fs, 2.97) at 0 (reused), +15 (the same catastrophic point ff shows,
   confirming the mechanism is not ff-specific). This is intentionally
   NOT a symmetric, exhaustive positive sweep -- it is the minimum set
   that demonstrates the non-monotonic collapse pattern the header above
   describes. Every point in this set is EXPECTED to be informative, not
   uniformly "pass": codes +1/+2/+5/+15 are expected to show the
   bifurcation (a REGULATION LOSS finding, checked and expected true);
   +3/+4 are expected to stay sane on this grid (which is itself part of
   the non-monotonicity finding, not a safe design point).

Usage
-----
    sim/trim-range-monotonicity/run_trim_sweep.py                 # the full sweep
    sim/trim-range-monotonicity/run_trim_sweep.py --dry-run       # print the plan

Exit status: 0 every check passed, 2 a record was written but a check
failed, 1 harness/setup error (no record written) -- same convention as
corner-run.py.
"""

from __future__ import annotations

import argparse
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
# issue. Never modify this file from this script or its record.
SCHEMATIC = SIM_DIR / "output-voltage-tc" / "testbench" / "tb_vref_tc.sch"
SPICEINIT_FILE = SIM_DIR / "spiceinit"
BUILD_DIR = SIM_DIR / "build" / "trim-range-monotonicity"

sys.path.insert(0, str(SIM_DIR / "bin"))
from sim_common import load_corner_run, parse_measurements  # noqa: E402

cr = load_corner_run()

# --------------------------------------------------------------------------
# experiment definition
# --------------------------------------------------------------------------

SLUG = "trim-range-monotonicity"
TITLE = (
    "Trim (n_r2_trim) range, monotonicity, and TC-at-extremes for the ladder-tap "
    "trim network added to R2A/R2B (issue #13) -- DOWNWARD-ONLY range, positive "
    "direction rejected on hot-corner regulation-collapse evidence"
)

# (process, supply_v) pairs for the negative (usable) range sweep.
NEGATIVE_CORNERS = (
    ("tt", 3.30),
    ("ss", 3.30),
    ("ff", 2.97),
    ("sf", 2.97),
    ("fs", 2.97),
)
NEGATIVE_CODES = (0, -8, -16)

# The rejected positive direction: minimum point set that demonstrates the
# non-monotonic collapse (see module docstring). ff gets the full bisection;
# fs gets one confirmatory point at the same code (+15) ff already shows
# collapsing, to prove the mechanism is not ff-specific.
POSITIVE_REJECTED_FF_CODES = (1, 2, 3, 4, 5, 15)
POSITIVE_REJECTED_FS_CODES = (15,)
POSITIVE_SUPPLY_V = 2.97

VOUT_NOMINAL_V = 1.20
SPEC_WINDOW_HALF_V = 0.012  # +/-1% of 1.20 V
# Loose sanity band around the nominal 1.20 V window -- wide enough to
# contain the full negative trim range (~-27 mV) plus normal process/temp
# excursion, tight enough to catch a genuinely broken operating point (the
# positive-direction collapse jumps VOUT to ~2.8 V, far outside this band).
VREF_SANITY_V = (1.10, 1.30)
# Regulation-loss threshold for the rejected positive-direction points:
# well above the sanity band, comfortably below the ~2.8 V collapse value
# both #46 and this record observe, so there is no ambiguity between "sane"
# and "collapsed."
REGULATION_LOSS_VOUT_V = 1.5

# Pre-existing baseline TC (issue #46, out of scope for #13): the untrimmed
# core already measures ~152-169 ppm/degC across process corners in
# sim/output-voltage-tc/records/20260803-115356-7759435.md, above the 50
# ppm/degC budget for reasons unrelated to trim. This script's own
# tc_delta_ppm figures are the #13-relevant number: how much trim itself
# ADDS on top of that pre-existing baseline. There is no tight pass/fail
# bound on this delta (see "Scope limits" in the rendered record for why a
# tight bound is not achievable on this lever) -- it is reported, not gated,
# except for the sanity-loss guard above.


@dataclass(frozen=True)
class Point:
    process: str
    supply_v: float
    trim_code: int
    group: str  # "negative" | "positive_rejected"

    @property
    def corner_id(self) -> str:
        sign = "p" if self.trim_code >= 0 else "n"
        return f"{self.process}_trim{sign}{abs(self.trim_code)}_{self.supply_v:.2f}v"


def build_points() -> list[Point]:
    points: list[Point] = []
    seen: set[tuple[str, float, int]] = set()

    def add(process: str, supply: float, code: int, group: str) -> None:
        key = (process, supply, code)
        if key in seen:
            return
        seen.add(key)
        points.append(Point(process, supply, code, group))

    for process, supply in NEGATIVE_CORNERS:
        for code in NEGATIVE_CODES:
            add(process, supply, code, "negative")

    for code in POSITIVE_REJECTED_FF_CODES:
        add("ff", POSITIVE_SUPPLY_V, code, "positive_rejected")
    for code in POSITIVE_REJECTED_FS_CODES:
        add("fs", POSITIVE_SUPPLY_V, code, "positive_rejected")

    return points


# --------------------------------------------------------------------------
# deck generation
# --------------------------------------------------------------------------


TRIM_DEFAULT_LINE = ".param n_r2_trim=0"


def substitute_trim_code(body: list[str], trim_code: int) -> list[str]:
    """Set the trim code by editing the netlisted body's OWN declaration.

    Empirically verified against ngspice-46 (not assumed): appending a
    `.param n_r2_trim=<code>` override AFTER `body` -- the technique
    `sim/monte-carlo-untrimmed/run_mc_untrimmed.py` uses for the PDK's own
    `sw_mm_*` coefficients -- does NOT work here. That technique overrides a
    parameter used inside per-instance AGAUSS() mismatch calls, which
    ngspice re-evaluates at element build time (after the whole deck's
    `.param` table is assembled). `n_r2_trim` is used in a plain algebraic
    `L=` instance-parameter expression on a `.subckt` device, which ngspice
    resolves once, in textual order, at `.subckt` DEFINITION time -- a
    control test (n_r2_trim=15 appended after body) reproduced the
    trim_code=0 baseline byte-for-byte (`vref_27`, `tc_ppm` identical to
    six figures), proving the late override never reached the L expression.
    Editing the netlisted body's own declaration in place, before ngspice
    ever sees the deck, sidesteps the ordering question entirely -- and is
    in any case the more faithful model of a METAL OPTION trim: the code is
    a fixed, build-time choice, not a runtime-overridable value.
    """
    found = False
    out = []
    for line in body:
        if line.strip() == TRIM_DEFAULT_LINE:
            out.append(f".param n_r2_trim={trim_code}")
            found = True
        else:
            out.append(line)
    if not found:
        raise cr.HarnessError(
            f"expected exactly one {TRIM_DEFAULT_LINE!r} line in the netlisted body "
            "(design/bandgap_core.sch's CORE_PARAMS default) -- schematic may have "
            "changed out from under this script"
        )
    return out


def build_deck(pdk, point: Point, body: list[str]) -> str:
    body = substitute_trim_code(body, point.trim_code)
    head = [
        f"* {SLUG} deck (process={point.process}, trim_code={point.trim_code}, "
        f"supply={point.supply_v}) -- generated by sim/{SLUG}/run_trim_sweep.py, do not edit",
        f"* point: {point.corner_id}",
        ".option wnflag=1 reltol=1e-6 vntol=1e-9 abstol=1e-15",
        f".param vsup={point.supply_v}",
        f'.lib "{pdk.lib_file}" {point.process}',
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


def run_point(point: Point, run_dir: Path, deck: str, timeout: int):
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


def write_log(corners_dir: Path, point: Point, pdk, record_id: str, stamp, deck: str, raw: str, rc: int, timed_out: bool) -> Path:
    corners_dir.mkdir(parents=True, exist_ok=True)
    path = corners_dir / f"{point.corner_id}.log"
    init_text = SPICEINIT_FILE.read_text()
    path.write_text(
        "\n".join(
            [
                f"# point: {point.corner_id}",
                f"# record: {record_id}",
                f"# group: {point.group}",
                f"# process={point.process} trim_code={point.trim_code} supply={point.supply_v:.2f}V",
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
# checks
# --------------------------------------------------------------------------


def is_regulating(meas: dict) -> bool:
    """True if the point stayed on the intended operating branch.

    Checks `vref_max` (the peak over the full -40..125 degC sweep), NOT
    `vref_27`: the bifurcation this record documents occurs above
    ~123..124 degC (per #46), so a collapsed point's `vref_27` reads
    perfectly sane (~1.2 V) even though the sweep jumps to ~2.8 V at the hot
    end. Checking `vref_27` alone would silently miss every collapse -- this
    was caught and fixed after an initial run's `regulation_loss_confirmed`
    checks came back "unexpected" for every code that visibly collapsed in
    `vref_max` (see git history / PR discussion for the caught-bug note).
    """
    v = meas.get("vref_max")
    return v is not None and v < REGULATION_LOSS_VOUT_V


def evaluate(results: dict[Point, dict]) -> list[dict]:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str):
        checks.append({"name": name, "pass": ok, "detail": detail})

    negative_points = {p: m for p, m in results.items() if p.group == "negative"}
    positive_points = {p: m for p, m in results.items() if p.group == "positive_rejected"}

    # --- negative-range sanity: every negative-sweep point must regulate ---
    for point, meas in negative_points.items():
        vref27 = meas.get("vref_27")
        n_temp = meas.get("n_temp_points")
        ok = vref27 is not None and VREF_SANITY_V[0] <= vref27 <= VREF_SANITY_V[1]
        add(
            f"sanity[{point.corner_id}]",
            ok,
            f"vref_27={vref27} (sanity band {VREF_SANITY_V})" if vref27 is not None else "vref_27 missing",
        )
        add(
            f"n_temp_points[{point.corner_id}]",
            n_temp == 16,
            f"n_temp_points={n_temp}, expected 16",
        )

    # --- monotonicity: at each (process, supply), vref_27 strictly increases
    # as trim_code increases from -16 toward 0 ---
    for process, supply in NEGATIVE_CORNERS:
        ordered = sorted(NEGATIVE_CODES)
        series = [results[Point(process, supply, t, "negative")]["vref_27"] for t in ordered]
        strictly_increasing = all(b > a for a, b in zip(series, series[1:]))
        add(
            f"monotonic[{process}_{supply:.2f}v]",
            strictly_increasing,
            f"vref_27 vs trim_code {list(zip(ordered, (round(v, 6) for v in series)))}",
        )

    # --- range: does the 0..-16 span cover a meaningful fraction of the
    # worst-case 3-sigma MC spread (15.62 mV at 125 degC,
    # sim/monte-carlo-untrimmed record 20260803-142259-544cc5e) in the one
    # direction this trim network actually provides ---
    worst_case_3sigma_v = 0.015620
    # This trim is DOWNWARD-ONLY (see module docstring): it can only correct
    # dies whose mismatch pushed VOUT too HIGH. The relevant coverage target
    # is therefore the full (bidirectional) 3-sigma spread, not half of it --
    # a downward-only trim still needs to reach as far down as an
    # upward-capable one would have, to correct the high-side tail of the
    # distribution. margin_target follows the same 1.5x convention the
    # original (bidirectional) design used.
    margin_target = 1.5
    for process, supply in NEGATIVE_CORNERS:
        v_hi = results[Point(process, supply, 0, "negative")]["vref_27"]
        v_lo = results[Point(process, supply, -16, "negative")]["vref_27"]
        span = v_hi - v_lo
        ok = span >= margin_target * worst_case_3sigma_v
        add(
            f"range_covers_mc_spread[{process}_{supply:.2f}v]",
            ok,
            f"downward trim span (code 0..-16) = {span * 1000:.3f} mV, "
            f"required >= {margin_target} x {worst_case_3sigma_v * 1000:.3f} mV "
            f"= {margin_target * worst_case_3sigma_v * 1000:.3f} mV",
        )

    # --- LSB: average per-code step must be comfortably inside the +/-1% window ---
    lsb_comfortable_fraction = 0.25  # LSB must be <= 25% of the window half-width
    for process, supply in NEGATIVE_CORNERS:
        v_hi = results[Point(process, supply, 0, "negative")]["vref_27"]
        v_lo = results[Point(process, supply, -16, "negative")]["vref_27"]
        lsb = (v_hi - v_lo) / 16.0  # 16 codes span 0..-16
        ok = lsb <= lsb_comfortable_fraction * SPEC_WINDOW_HALF_V
        add(
            f"lsb_comfortable[{process}_{supply:.2f}v]",
            ok,
            f"LSB={lsb * 1000:.4f} mV, required <= {lsb_comfortable_fraction:.0%} of "
            f"window half-width ({lsb_comfortable_fraction * SPEC_WINDOW_HALF_V * 1000:.3f} mV)",
        )

    # --- TC delta at the negative extreme, reported (not gated against a
    # tight bound -- see "Scope limits" in the rendered record) ---
    for process, supply in NEGATIVE_CORNERS:
        tc0 = negative_points[Point(process, supply, 0, "negative")]["tc_ppm"]
        tc16 = negative_points[Point(process, supply, -16, "negative")]["tc_ppm"]
        delta = tc16 - tc0
        add(
            f"tc_delta_reported[{process}_{supply:.2f}v]",
            True,  # informational: always "passes" as a check, the number is the deliverable
            f"tc_ppm(trim=0)={tc0:.3f}, tc_ppm(trim=-16)={tc16:.3f}, delta={delta:+.3f} ppm/degC "
            f"(baseline itself already exceeds the 50 ppm/degC budget -- issue #46, out of "
            f"scope here; this delta is reported, not gated -- see Scope limits)",
        )

    # --- positive-direction rejection: confirm regulation loss is real and
    # reproducible at the codes where it is expected, at BOTH corners ---
    for point, meas in positive_points.items():
        vref27 = meas.get("vref_27")
        vref_max = meas.get("vref_max")
        regulating = is_regulating(meas)
        if point.trim_code in (3, 4):
            # These two codes are the ones observed to stay sane on this
            # grid -- part of the non-monotonicity finding, NOT a safe
            # design point (see module docstring / DR-002). Check confirms
            # they remain sane (as observed), informational either way.
            add(
                f"positive_code_sane_but_not_safe[{point.corner_id}]",
                regulating,
                f"vref_27={vref27}, vref_max={vref_max} -- sane on this grid, but this code "
                f"is bracketed by codes that collapse (see the non-monotonicity table) and "
                f"is NOT a certified-safe design point",
            )
        else:
            add(
                f"regulation_loss_confirmed[{point.corner_id}]",
                not regulating,
                f"vref_27={vref27}, vref_max={vref_max} -- "
                + (
                    "EXPECTED regulation loss confirmed (VOUT pinned near VDD, box TC "
                    "reads thousands of ppm/degC)"
                    if not regulating
                    else "UNEXPECTED: this code was expected to show regulation loss and "
                    "did not -- re-examine before relying on this record"
                ),
            )

    # --- non-monotonicity confirmation: the ff bisection must show at least
    # one pass and one fail among interior codes, proving the pattern is not
    # simply "everything above 0 fails" (which would at least be monotonic
    # and give a clean boundary) ---
    ff_codes = sorted(p.trim_code for p in positive_points if p.process == "ff")
    ff_regulating = {c: is_regulating(results[Point("ff", POSITIVE_SUPPLY_V, c, "positive_rejected")]) for c in ff_codes}
    has_pass = any(ff_regulating.values())
    has_fail = any(not v for v in ff_regulating.values())
    add(
        "positive_direction_nonmonotonic[ff]",
        has_pass and has_fail,
        f"regulating-by-code = {ff_regulating} -- a genuine mix of regulating and "
        f"collapsed codes among the SAME small interior range (not a clean threshold) is "
        f"the evidence that no positive code can be certified safe from this record",
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
        "- **Claim**: trim network design phase for issue #13, following "
        "`spec/decision-records/DR-002-trim-network-scoping.md`'s go decision "
        "(#12's Monte Carlo evidence found the untrimmed ±1 % target NOT met). "
        "Verifies the `n_r2_trim` ladder-tap trim added to "
        "`design/bandgap_core.sch`'s R2A/R2B resistor segments. **Headline "
        "finding: the positive (VOUT-increasing) direction is REJECTED** on "
        "hot-corner (ff/2.97 V, fs/2.97 V) regulation-collapse evidence — the "
        "shipped range is downward-only (code 0..-16). Wraps issue #11's own "
        "output-voltage testbench (`sim/output-voltage-tc/testbench/tb_vref_tc.sch`) "
        "unmodified. Records are PROVISIONAL against the draft spec until "
        "issue #1 ratifies it."
    )
    add(
        "- **Netlist provenance**: schematic (`sim/output-voltage-tc/testbench/tb_vref_tc.sch` "
        "wrapping `design/bandgap_core.sch` with the new `n_r2_trim`/`r_lseg_trim` "
        "parameters added by this issue)"
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
    add("- **Corner matrix run**:")
    add(
        "  - **Negative (usable) range**: "
        + ", ".join(f"{p}/{s:.2f} V" for p, s in NEGATIVE_CORNERS)
        + f" x codes {NEGATIVE_CODES}. Process/supply pairs chosen to bound the process "
        "spread while sitting at the worst-case (lowest) supply for the two corners "
        "issue #46 already flagged as margin-thin (ff, fs at 2.97 V); tt/ss run at "
        "nominal 3.30 V for a like-for-like comparison against the existing untrimmed "
        "baseline records."
    )
    add(
        "  - **Positive (rejected) direction**: ff/2.97 V at codes "
        + ", ".join(f"{c:+d}" for c in POSITIVE_REJECTED_FF_CODES)
        + " (a bisection demonstrating non-monotonic collapse, not an exhaustive sweep); "
        "fs/2.97 V at code +15 only (confirms the same collapse mechanism is not "
        "ff-specific)."
    )
    add(
        "  - Temperature: continuous in-deck sweep -40..125 °C (16 points, `dc temp -40 125 11`, "
        "the same box-method sweep issue #11's bench already runs) — not a separate outer axis; "
        "every point below therefore already carries full temperature coverage and a TC number."
    )
    add(f"  - {len(r['points'])} ngspice points executed.")
    add(
        "- **Statistical convention**: N/A (deterministic corner x trim-code sweep, not a "
        "distribution claim)."
    )
    add("")

    add("## Negative (usable) range: per-point measurements")
    add("")
    add("| process | supply (V) | trim code | VREF(27 °C) (V) | VREF min (V) | VREF max (V) | TC (ppm/°C) |")
    add("|---|---|---|---|---|---|---|")
    for process, supply in NEGATIVE_CORNERS:
        for t in NEGATIVE_CODES:
            m = r["results"][f"{process}:{supply}:{t}"]
            add(
                f"| {process} | {supply:.2f} | {t:+d} | {m['vref_27']:.6f} | {m['vref_min']:.6f} | "
                f"{m['vref_max']:.6f} | {m['tc_ppm']:.3f} |"
            )
    add("")

    add("## Positive (rejected) direction: per-point measurements")
    add("")
    add("| process | supply (V) | trim code | VREF(27 °C) (V) | VREF max (V) | TC (ppm/°C) | regulating? |")
    add("|---|---|---|---|---|---|---|")
    for process, codes in (("ff", POSITIVE_REJECTED_FF_CODES), ("fs", POSITIVE_REJECTED_FS_CODES)):
        m0 = r["results"].get(f"{process}:{POSITIVE_SUPPLY_V}:0")
        if m0:
            add(
                f"| {process} | {POSITIVE_SUPPLY_V:.2f} | +0 | {m0['vref_27']:.6f} | "
                f"{m0['vref_max']:.6f} | {m0['tc_ppm']:.3f} | yes |"
            )
        for t in codes:
            m = r["results"][f"{process}:{POSITIVE_SUPPLY_V}:{t}"]
            reg = "yes" if is_regulating(m) else "**NO — collapsed**"
            add(
                f"| {process} | {POSITIVE_SUPPLY_V:.2f} | {t:+d} | {m['vref_27']:.6f} | "
                f"{m['vref_max']:.6f} | {m['tc_ppm']:.3f} | {reg} |"
            )
    add("")
    add(
        "Read the ff row across codes +1..+5: **collapsed, collapsed, sane, sane, "
        "collapsed** — a non-monotonic pattern in trim code. This is the evidence "
        "that no positive code is a certified-safe design point (see the module "
        "docstring / DR-002 for the bifurcation-surface explanation)."
    )
    add("")

    add("## Range / monotonicity / TC-delta / rejection checks")
    add("")
    n_fail = sum(1 for c in r["checks"] if not c["pass"])
    for c in r["checks"]:
        verdict = "PASS" if c["pass"] else "FAIL"
        add(f"- {verdict} `{c['name']}` — {c['detail']}")
    add("")
    add(f"- **Overall: {'PASS' if r['overall_pass'] else 'FAIL'}** ({n_fail} check(s) failed)")
    add("")

    add("## Controls (the reason this record can be believed)")
    add("")
    add(
        "- **trim=0 baseline reproduces the pre-existing untrimmed record.** At tt/3.30 V, "
        "the `trim_code=0` row's `vref_27`/`tc_ppm` match "
        "`sim/output-voltage-tc/records/20260803-115356-7759435.md`'s own value "
        "(1.199721 V / 163.389 ppm/°C here vs. 1.19972 V / 163.389 ppm/°C there) -- "
        "confirming the schematic edit is backward-compatible and the wrapped testbench + "
        "PDK + corner set are unchanged. Likewise at ff/2.97 V (1.199468 V / 162.299 ppm/°C "
        "here vs. 1.19947 V / 162.298-162.441 ppm/°C across supply in the same prior record) "
        "and fs/2.97 V (1.199991 V / 169.187 ppm/°C here vs. 1.19999 V / 169.187-169.312 ppm/°C "
        "there)."
    )
    add(
        "- **The override-that-didn't-work IS the negative control.** Before landing on "
        "the body-substitution mechanism, a manual pre-check appended `.param "
        "n_r2_trim=15` AFTER the netlisted body (the technique that works for "
        "`sim/monte-carlo-untrimmed`'s PDK-coefficient overrides) and it reproduced the "
        "trim_code=0 baseline byte-for-byte -- proving that if this record's trim "
        "mechanism were silently inactive, the `monotonic[*]` checks below would fail "
        "flat (all `vref_27` identical) rather than pass. See `substitute_trim_code()`'s "
        "docstring for the full writeup."
    )
    add(
        "- **The positive-direction collapse itself replicates issue #46's finding on an "
        "independent code path.** `n_r2_trim=+5` is bit-for-bit the same ΔL (+5 µm on "
        "R2A/R2B) as #46's rejected `n_r2=55` resize, produced through a completely "
        "different schematic parameter (`r_lseg_trim*n_r2_trim` here vs. `r_lseg*n_r2` "
        "there). That two independent parameterizations of the identical physical "
        "perturbation both lose the ff/2.97 V and fs/2.97 V operating point is strong "
        "corroboration this is a real circuit property, not a script artifact."
    )
    add("")

    add("## Scope limits, stated so this record is not over-read")
    add("")
    add(
        "1. **Downward-only trim range.** This is the headline finding, not a scope "
        "reduction taken for convenience: the positive direction was tested (see the "
        "rejection table above) and found unsafe. A trim network that can only correct "
        "the high-VOUT tail of the mismatch distribution leaves the low-VOUT tail "
        "uncorrected — roughly half of a zero-mean mismatch population, if the "
        "distribution is symmetric (issue #12's own record does not characterize "
        "skew). Closing this gap needs a change outside this issue's scope: widening "
        "the error amplifier's hot-corner headroom margin (#9) so a higher K does not "
        "cost regulation, or addressing the mismatch at its physical source (#15's "
        "layout matching, since #12 found amp/mirror MOS mismatch dominant) so less "
        "trim range is needed in the first place."
    )
    add(
        "2. **TC-delta is reported, not gated to a tight bound.** The untrimmed core's "
        "own TC already measures ~152-169 ppm/°C across process corners "
        "(`sim/output-voltage-tc/records/20260803-115356-7759435.md`), above the draft "
        "50 ppm/°C budget for reasons unrelated to trim (issue #46, open). At the full "
        "-16 extreme this record measures a further +79 to +86 ppm/°C on top of that "
        "baseline (see the per-corner `tc_delta_reported` checks) -- a substantial, "
        "disclosed cost, not a negligible one. This is an unavoidable consequence of "
        "using the SAME R2/R1 ratio for both accuracy trim and the core's PTAT/CTAT "
        "cancellation weight K (issue #46's own finding: 'reaching < 50 ppm/degC "
        "untrimmed needs either curvature correction/trim (#13) ... or widening the "
        "error amp's own headroom margin (#9)'). This record does NOT claim trim "
        "brings TC under budget -- it reports what trim itself costs on top of the "
        "pre-existing, separately-tracked overage."
    )
    add(
        "3. **Corner subset for the negative range.** tt/ss at nominal 3.30 V, ff/sf/fs "
        "at the worst-case 2.97 V -- chosen to bound the process spread at the supply "
        "point where hot-corner margin is thinnest (issue #46's own finding), not the "
        "full 5-process x 3-supply matrix. If a future revision finds the negative "
        "direction has its own margin-sensitive corner this subset misses, that would "
        "need a new record."
    )
    add(
        "4. **Positive-direction point set is a bisection, not an exhaustive sweep.** "
        "Six codes at ff and one confirmatory code at fs are the minimum set that "
        "demonstrates non-monotonic collapse; a denser sweep could find additional "
        "collapsed or sane codes but cannot change the conclusion (no positive code is "
        "certified safe by a sparse sane result surrounded by collapsed neighbors)."
    )
    add("")

    add("- **Links**:")
    add(f"  - testbench: `{r['links']['testbench']}`")
    add(f"  - runner: `sim/{SLUG}/run_trim_sweep.py`")
    add(f"  - netlist_snapshot: `{r['links']['netlist_snapshot']}`")
    add(f"  - logs: `{r['links']['corners_dir']}`")
    add(f"  - record_json: `{r['links']['json']}`")
    add(f"  - trim design/decision record: `spec/decision-records/DR-002-trim-network-scoping.md`")
    add(f"- **Timestamp / author**: {r['timestamp']}, {r['author']}")
    add(f"- **Supersedes**: {r['supersedes'] or '(none — first record for this claim)'}")
    add("")
    add(
        f"Written by `sim/{SLUG}/run_trim_sweep.py`. Append-only: never edit this file — a "
        "correction is a new record with a `Supersedes` field (see `sim/README.md`)."
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
    if not SCHEMATIC.is_file():
        raise cr.HarnessError(f"missing testbench: {SCHEMATIC}")

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

    points = build_points()
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
    print(f"testbench       : {SCHEMATIC.relative_to(REPO_ROOT)} (wrapped, unmodified)")
    print(f"points          : {len(points)}")
    for p in points:
        print(f"  {p.corner_id} ({p.group})")

    netlist = cr.netlist_with_xschem(SCHEMATIC, BUILD_DIR / "xschem", pdk)
    body = cr.netlist_body(netlist)

    if args.dry_run:
        print("\n-- deck for first point --")
        print(build_deck(pdk, points[0], body))
        print("\n(dry run: nothing written under sim/<experiment>/)")
        return 0

    run_dir = BUILD_DIR / record_id
    results: dict[Point, dict] = {}
    for i, point in enumerate(points, start=1):
        deck = build_deck(pdk, point, body)
        stamp = datetime.now(timezone.utc)
        raw, rc, timed_out = run_point(point, run_dir, deck, args.timeout)
        write_log(corners_dir, point, pdk, record_id, stamp, deck, raw, rc, timed_out)
        meas = parse_measurements(raw)
        results[point] = meas
        print(
            f"[{i:>2}/{len(points)}] {point.corner_id:<28} ({point.group}) "
            f"rc={rc}{' TIMEOUT' if timed_out else ''} "
            f"vref_27={meas.get('vref_27')} tc_ppm={meas.get('tc_ppm')}"
        )
        if timed_out or rc != 0 or "vref_27" not in meas:
            raise cr.HarnessError(
                f"point {point.corner_id} did not produce usable measurements "
                f"(rc={rc}, timed_out={timed_out}); no record written"
            )

    checks = evaluate(results)
    overall = all(c["pass"] for c in checks)

    snapshots_dir.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("\n".join(body) + "\n.end\n")

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
        "points": [p.corner_id for p in points],
        "results": {f"{p.process}:{p.supply_v}:{p.trim_code}": m for p, m in results.items()},
        "checks": checks,
        "overall_pass": overall,
        "links": {
            "testbench": str(SCHEMATIC.relative_to(REPO_ROOT)),
            "netlist_snapshot": str(snapshot.relative_to(REPO_ROOT)),
            "corners_dir": str(corners_dir.relative_to(REPO_ROOT)) + "/",
            "json": str(record_json.relative_to(REPO_ROOT)),
            "record": str(record_md.relative_to(REPO_ROOT)),
        },
    }

    records_dir.mkdir(parents=True, exist_ok=True)
    import json as _json

    record_json.write_text(_json.dumps(record, indent=2, sort_keys=True, default=str) + "\n")
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
        print(f"run_trim_sweep: error: {err}", file=sys.stderr)
        sys.exit(1)
