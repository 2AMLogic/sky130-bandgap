#!/usr/bin/env python3
"""Shared helpers for the bespoke `sim/*/run_*.py` experiment scripts.

`sim/bin/corner-run.py` drives exactly one deterministic deck per PVT point.
The Monte Carlo / chained-resistor-array experiments under `sim/` (issues #9,
#12, #13, #31, #98, #99, #106) are bespoke scripts instead of
`experiment.json` + `corner-run.py` entries, but they still reuse
`corner-run.py`'s PDK resolution, pin enforcement, xschem netlisting, and
tool-version/git-provenance helpers by import. Several small pieces of that
import glue were copy-pasted verbatim (or near-verbatim) across those
scripts instead of being defined once here (issues #119, #130, #135):

    load_corner_run()    the importlib shim that loads corner-run.py (its
                          filename has a dash, so it can't be `import`ed
                          normally)
    chain_lines()         builds N series `sky130_fd_pr__res_high_po` unit
                          instances between two SPICE nodes, reproducing the
                          routed layout's `bus_res_series` topology
    run_ngspice()          runs one ngspice deck in a scratch dir, capturing
                          stdout+stderr and timeout status
    parse_measurements()   extracts `.meas`-style `let`/`print` results from
                          an ngspice log via `corner-run.py`'s `MEAS_RE`
    parse_samples()        parses the repeated `op`+`print` blocks of a
                          Monte Carlo loop's ngspice log into per-sample
                          dicts (issue #153)
    write_log()            writes the append-only per-point `.log` file
                          (header + .spiceinit + deck + ngspice output),
                          `name`-keyed (issue #138)
    render_log()            the shared tail-formatting skeleton underneath
                          every `write_log()` in this repo (issue #146)

Unlike `corner-run.py`, this file's name IS a valid Python identifier, so
callers import it normally (after adding `sim/bin` to `sys.path`) rather than
going through `importlib.util.spec_from_file_location`.

    r1_segments_um()      the coarse-unit R1 leg decomposition
                          (`n_r1` units of `r_lseg_um` length each)
    load_base_body()       reads + validates the shared core-body netlist
                          snapshot (`sim/trim-range-monotonicity/
                          netlist-snapshots/20260803-170704-b976d0f.spice`)
                          against a caller-supplied set of required
                          `.param` lines
    build_deck()            assembles the DC-temperature-sweep-and-vref-TC
                          measurement deck skeleton shared by every bespoke
                          chained-array script
    dc_temp_sweep_control() the `.control` block literal underneath
                          `build_deck()`, also reused directly by
                          `trim-range-monotonicity/run_trim_sweep.py`'s own
                          `build_deck()` (issue #152)

(issue #143 -- `sim/res-array-resize/run_res_array_resize.py` and
`sim/trim-lsb-chained/run_trim_lsb_chained.py` both reuse these three
verbatim, differing only in which module-level constants they closed the
functions over.)
"""

from __future__ import annotations

import importlib.util
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

BIN_DIR = Path(__file__).resolve().parent
SIM_DIR = BIN_DIR.parent
SPICEINIT_FILE = SIM_DIR / "spiceinit"


def load_corner_run() -> ModuleType:
    """Import sim/bin/corner-run.py (the dash makes it non-importable normally).

    Registers the loaded module in `sys.modules` under its spec name
    ("corner_run") *before* `exec_module` runs -- required because
    `@dataclass`-decorated classes inside corner-run.py resolve type
    annotations through `sys.modules[cls.__module__]`, which fails on an
    unregistered module.
    """
    path = BIN_DIR / "corner-run.py"
    spec = importlib.util.spec_from_file_location("corner_run", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def chain_lines(
    prefix: str,
    node_lo: str,
    node_hi: str,
    segments_um: list[float],
    bulk: str,
    r_w_um: float = 1.0,
) -> list[str]:
    """N series `sky130_fd_pr__res_high_po` unit instances between two nodes.

    Reproduces the routed layout's own `bus_res_series` topology: each unit
    is a separately-contacted two-terminal device (real drawn metal+via
    between adjacent units), not a single device's internal length
    subdivision -- so this emits N distinct `X` lines, each paying the model
    card's own `rhead`/`leff` terms once, not one device with an
    N-times-longer `L`.
    """
    lines = []
    prev = node_lo
    for i, length_um in enumerate(segments_um):
        nxt = node_hi if i == len(segments_um) - 1 else f"{prefix}_n{i + 1}"
        lines.append(
            f"X{prefix}_{i} {prev} {nxt} {bulk} sky130_fd_pr__res_high_po "
            f"W={r_w_um} L={length_um} mult=1 m=1"
        )
        prev = nxt
    return lines


def r1_segments_um(n_r1: int, r_lseg_um: float) -> list[float]:
    """R1 leg unit lengths: `n_r1` coarse units of `r_lseg_um` length each."""
    return [r_lseg_um] * n_r1


_cr_module: ModuleType | None = None


def _cr() -> ModuleType:
    """Lazily load+cache corner-run.py, for `parse_measurements()`'s `MEAS_RE`.

    Cached at module scope so repeated `parse_measurements()` calls (e.g. once
    per PVT corner in a sweep) don't re-exec corner-run.py's module body each
    time.
    """
    global _cr_module
    if _cr_module is None:
        _cr_module = load_corner_run()
    return _cr_module


def load_base_body(base_snapshot: Path, expected_params: set[str]) -> list[str]:
    """Read + validate a shared core-body netlist snapshot.

    Strips the trailing `.end` line and checks that every line in
    `expected_params` (a set of exact `.param ...` line strings) is present
    -- raising `cr.HarnessError` if the reused core body has drifted.
    """
    cr = _cr()
    if not base_snapshot.is_file():
        raise cr.HarnessError(f"missing base netlist snapshot: {base_snapshot}")
    text = base_snapshot.read_text()
    lines = [ln for ln in text.splitlines() if ln.strip().lower() != ".end"]
    present = {ln.strip() for ln in lines if ln.strip().startswith(".param ")}
    missing = expected_params - present
    if missing:
        raise cr.HarnessError(
            f"base snapshot {base_snapshot} is missing expected core .param line(s) "
            f"{sorted(missing)} -- the reused core body may have drifted"
        )
    return lines


def dc_temp_sweep_control() -> list[str]:
    """The DC-temperature-sweep-and-vref-TC-measurement `.control` block
    shared by every bespoke chained-array script (`dc temp -40 125 11`,
    `meas dc vref27`, and the five `let`/`print meas_*` lines) -- extracted
    out of `build_deck()` so `trim-range-monotonicity/run_trim_sweep.py`'s
    otherwise-private `build_deck()` can reuse it too (issue #152)."""
    return [
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


def build_deck(
    slug: str, script_name: str, pdk, process: str, supply_v: float, body: list[str]
) -> str:
    """Assemble the DC-temperature-sweep-and-vref-TC-measurement deck skeleton
    shared by the bespoke chained-array scripts (`dc temp -40 125 11`,
    `meas dc vref27`, and the five `let`/`print meas_*` lines)."""
    head = [
        f"* {slug} deck (process={process}, supply={supply_v}) -- "
        f"generated by sim/{slug}/{script_name}, do not edit",
        ".option wnflag=1 reltol=1e-6 vntol=1e-9 abstol=1e-15",
        f".param vsup={supply_v}",
        f'.lib "{pdk.lib_file}" {process}',
    ]
    return "\n".join(head + body + dc_temp_sweep_control())


def run_ngspice(run_dir: Path, name: str, deck: str, timeout: int) -> tuple[str, int, bool]:
    """Run one ngspice deck in `run_dir`, returning (log, returncode, timed_out)."""
    run_dir.mkdir(parents=True, exist_ok=True)
    deck_path = run_dir / f"{name}.spice"
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


def parse_measurements(log: str) -> dict[str, float]:
    """Extract `meas_<name> = <value>` results from an ngspice log."""
    cr = _cr()
    values: dict[str, float] = {}
    for line in log.splitlines():
        m = cr.MEAS_RE.match(line.strip())
        if m:
            values[m.group(1)] = float(m.group(2))
    return values


_PRINT_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(-?[0-9.]+(?:[eE][-+]?[0-9]+)?)$")


def parse_samples(log: str, vectors) -> list[dict[str, float]]:
    """Parse the repeated `op` + `print` blocks of a Monte Carlo loop.

    A new sample starts whenever a vector name that is already in the current
    sample repeats. Shared by the bespoke Monte Carlo run scripts (issue
    #153) -- lifted to `pnp-mismatch/run_pnp_mismatch.py`'s already-
    parameterized `(log, vectors)` signature rather than reading a
    module-level `VECTORS` constant.
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


def render_log(header_lines, pdk, rc, timed_out, stamp, sections, raw) -> str:
    """Shared `.log` tail skeleton: caller's `header_lines` + pdk/exit/
    timestamp + `(label, text)` `sections` + raw ngspice output (#146)."""
    lines = [
        *header_lines,
        f"# pdk: {pdk.variant} @ open_pdks {pdk.installed_commit} ({pdk.lib_file})",
        f"# ngspice exit: {rc}{' (TIMEOUT)' if timed_out else ''}",
        f"# run (UTC): {stamp:%Y-%m-%dT%H:%M:%SZ}",
        "",
    ]
    for label, text in sections:
        lines += [f"# ==== {label} ====", *[f"| {ln}" for ln in text.splitlines()], ""]
    lines += ["# ==== ngspice stdout+stderr ====", raw.rstrip(), ""]
    return "\n".join(lines)


def write_log(
    corners_dir: Path,
    name: str,
    record_id: str,
    pdk,
    stamp,
    deck: str,
    raw: str,
    rc: int,
    timed_out: bool,
) -> Path:
    """Write the append-only per-point `.log` file, return its `Path`.

    Header + exact `.spiceinit` + exact deck + raw ngspice stdout/stderr --
    `name`-keyed (issue #138; not the 4 `point`-keyed variants excluded from
    this consolidation, see the issue's Hermit-suggestion comment), now
    built on the shared `render_log()` tail skeleton (issue #146).
    """
    corners_dir.mkdir(parents=True, exist_ok=True)
    path = corners_dir / f"{name}.log"
    init_text = SPICEINIT_FILE.read_text()
    sections = [(".spiceinit (exact)", init_text), ("deck (exact input given to ngspice)", deck)]
    header = [f"# point: {name}", f"# record: {record_id}"]
    path.write_text(render_log(header, pdk, rc, timed_out, stamp, sections, raw))
    return path


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def stdev(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mu = mean(values)
    return math.sqrt(sum((v - mu) ** 2 for v in values) / (n - 1))


def mv(value: float) -> str:
    """Format a volt-scale value as a millivolt string with 4 decimal places."""
    return f"{value * 1e3:.4f}"


def seed_stability_checks(
    a: dict,
    b: dict,
    vector: str,
    seed_a: int,
    seed_b: int,
    tol: float,
    *,
    sample_field: str = "max_abs",
    sample_label: str = "magnitude",
    sample_unit: str = "mV",
    sample_scale: float = 1e3,
    sample_precision: int = 4,
) -> list[dict]:
    """Two-check seed-stability block for one Monte Carlo vector (issue #154).

    Compares a run seeded with `seed_a` against a second run seeded with
    `seed_b`: `seed_sigma_stable[vector]` checks the sigma drift stays within
    `tol`, `seed_sample_differs[vector]` checks the worst-sample value
    (`stats[vector][sample_field]`) actually changed between seeds -- i.e.
    the second draw wasn't a no-op. `SEED_A`/`SEED_B`/`SEED_SIGMA_TOL` are
    per-script module constants with different *values* across the three
    callers (`error-amp-offset-mc`, `pnp-mismatch`, `monte-carlo-untrimmed`),
    so they are passed in rather than imported. `sample_field` defaults to
    `"max_abs"` (error-amp-offset-mc, pnp-mismatch); `monte-carlo-untrimmed`
    passes `sample_field="max", sample_label="VOUT", sample_unit="V",
    sample_scale=1.0, sample_precision=6` to preserve its pre-existing
    (differently-formatted, absolute-VOUT rather than mV-magnitude) detail
    text.
    """
    sa = a["stats"][vector]["sigma"]
    sb = b["stats"][vector]["sigma"]
    drift = abs(sb / sa - 1.0) if sa else float("inf")
    sample_a = a["stats"][vector][sample_field]
    sample_b = b["stats"][vector][sample_field]
    return [
        {
            "name": f"seed_sigma_stable[{vector}]",
            "pass": drift <= tol,
            "detail": (
                f"sigma(seed {seed_b}) / sigma(seed {seed_a}) = "
                f"{(sb / sa) if sa else float('nan'):.3f} "
                f"({mv(sb)} mV vs {mv(sa)} mV; tolerance +/-{tol:.0%})"
            ),
        },
        {
            "name": f"seed_sample_differs[{vector}]",
            "pass": sample_a != sample_b,
            "detail": (
                f"worst-sample {sample_label} differs between the two seeds "
                f"({sample_a * sample_scale:.{sample_precision}f} {sample_unit} vs "
                f"{sample_b * sample_scale:.{sample_precision}f} {sample_unit}), i.e. the "
                "draw really did change"
            ),
        },
    ]
