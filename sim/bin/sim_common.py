#!/usr/bin/env python3
"""Shared helpers for the bespoke `sim/*/run_*.py` experiment scripts.

`sim/bin/corner-run.py` drives exactly one deterministic deck per PVT point.
The Monte Carlo / chained-resistor-array experiments under `sim/` (issues #9,
#12, #13, #31, #98, #99, #106) are bespoke scripts instead of
`experiment.json` + `corner-run.py` entries, but they still reuse
`corner-run.py`'s PDK resolution, pin enforcement, xschem netlisting, and
tool-version/git-provenance helpers by import. Two small pieces of that
import glue were copy-pasted verbatim (or near-verbatim) across those
scripts instead of being defined once here (issue #119):

    load_corner_run()   the importlib shim that loads corner-run.py (its
                         filename has a dash, so it can't be `import`ed
                         normally)
    chain_lines()        builds N series `sky130_fd_pr__res_high_po` unit
                         instances between two SPICE nodes, reproducing the
                         routed layout's `bus_res_series` topology

Unlike `corner-run.py`, this file's name IS a valid Python identifier, so
callers import it normally (after adding `sim/bin` to `sys.path`) rather than
going through `importlib.util.spec_from_file_location`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

BIN_DIR = Path(__file__).resolve().parent


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


def mean(values: list[float]) -> float:
    return sum(values) / len(values)
