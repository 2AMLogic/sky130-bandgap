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
    write_log()            writes the append-only per-point `.log` file
                          (header + .spiceinit + deck + ngspice output),
                          `name`-keyed (issue #138)

Unlike `corner-run.py`, this file's name IS a valid Python identifier, so
callers import it normally (after adding `sim/bin` to `sys.path`) rather than
going through `importlib.util.spec_from_file_location`.
"""

from __future__ import annotations

import importlib.util
import math
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
    this consolidation, see the issue's Hermit-suggestion comment).
    """
    corners_dir.mkdir(parents=True, exist_ok=True)
    path = corners_dir / f"{name}.log"
    init_text = SPICEINIT_FILE.read_text()
    path.write_text(
        "\n".join(
            [
                f"# point: {name}",
                f"# record: {record_id}",
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


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def stdev(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mu = mean(values)
    return math.sqrt(sum((v - mu) ** 2 for v in values) / (n - 1))
