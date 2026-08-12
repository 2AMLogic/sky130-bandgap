#!/usr/bin/env python3
"""Post-layout (extracted-netlist) re-run of `sim/output-voltage-tc`'s output
voltage + box-method TC claim, against the routed, LVS-clean bandgap-core
layout (issue #62) instead of `design/bandgap_core.sch` (issue #16).

Schematic-level evidence assumes ideal parasitics; this record substantiates
the SAME claim -- README.md 'Target specification' rows 'Output reference'
and 'Temp coefficient' -- against a netlist genuinely derived from the routed
GDS: `klt extract --parasitics` (real per-net star RC parasitics from the
drawn routing) with its generic LVS device-class placeholders translated to
simulatable sky130 vendor models. See `sim/bin/post_layout_common.py`'s
module docstring for the full translation methodology, the two-PNP-unit-size
keying, the dropped resistor bulk terminal, and the ngspice BSIM-binning
unit-suffix quirk this discovered and works around.

Why a bespoke script, not a `corner-run.py` experiment.json entry (same
reasoning as `sim/trim-lsb-chained/run_trim_lsb_chained.py` and
`sim/res-array-resize/run_res_array_resize.py`): the DUT netlist body is not
something `corner-run.py`'s xschem-driven netlisting can produce on its own
-- it is `sim/output-voltage-tc/testbench/tb_vref_tc.sch`'s OWN netlisted
body with its `.subckt bandgap_core ... .ends` / `.subckt error_amp ...
.ends` blocks replaced by the translated, extracted layout. The run itself
still reuses `corner-run.py`'s PDK resolution, corner matrix, per-corner
ngspice runner, spread checks and record rendering by import (same
convention), so this record is directly comparable to the schematic-level
ones structurally -- the entries differ only in provenance and in the DUT
body.

Everything above the per-bench declarations below is
`sim/bin/post_layout_common.run_post_layout_experiment`, shared with every
other `sim/*-post-layout/run_*.py`.

Usage
-----
    sim/output-voltage-tc-post-layout/run_post_layout_vref_tc.py
    sim/output-voltage-tc-post-layout/run_post_layout_vref_tc.py --dry-run

Exit status: 0 all checks passed, 2 a record was written but something
failed, 1 harness/setup error (no record written) -- same convention as
`corner-run.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent

sys.path.insert(0, str(SIM_DIR / "bin"))
from sim_common import load_corner_run  # noqa: E402
import post_layout_common as plc  # noqa: E402

cr = load_corner_run()

SLUG = "output-voltage-tc-post-layout"
WRAPPED_EXPERIMENT = "output-voltage-tc"  # manifest (corners/measurements/deck) reused unchanged
WRAPPED_SCHEMATIC = "sim/output-voltage-tc/testbench/tb_vref_tc.sch"

CLAIM_TAIL = (
    "Measures the ROUTED, LVS-clean bandgap-core layout (issue #62) open-circuit, "
    "untrimmed, via klt extract --parasitics translated to a simulatable netlist "
    "(sim/bin/post_layout_common.py) -- NOT design/bandgap_core.sch directly; see "
    "'Netlist provenance' below."
)

# The box-method TC needs the -40..125 degC excursion swept continuously
# INSIDE the deck (dc temp), so the runner's outer temperature axis is
# collapsed to one point on purpose -- exactly as sim/output-voltage-tc's own
# schematic-level records do.
TEMP_OVERRIDE = [27.0]
SUBSET_REASON = (
    "Reuses sim/output-voltage-tc's own subset: the box-method TC needs the "
    "-40..125 degC excursion swept continuously INSIDE the deck (dc temp), so "
    "the runner's outer temperature axis is collapsed to one point on purpose. "
    "Process and supply axes run in full (5 x 3 = 15 points)."
)


def run(argv: list[str]) -> int:
    return plc.run_post_layout_experiment(
        cr,
        here=HERE,
        slug=SLUG,
        wrapped_experiment=WRAPPED_EXPERIMENT,
        wrapped_schematic=WRAPPED_SCHEMATIC,
        claim_tail=CLAIM_TAIL,
        argv=argv,
        temp_override=TEMP_OVERRIDE,
        subset_reason=SUBSET_REASON,
    )


if __name__ == "__main__":
    plc.main_wrapper(cr, run)
