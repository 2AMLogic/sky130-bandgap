#!/usr/bin/env python3
"""Post-layout (extracted-netlist) re-run of `sim/quiescent-current`'s total
quiescent supply current claim, against the routed, LVS-clean bandgap-core
layout (issue #62) instead of `design/bandgap_core.sch` (issue #16).

Second increment of issue #16's post-layout suite, after
`sim/output-voltage-tc-post-layout/`. Iq is the spec line most directly
exposed to extraction: the drawn VDD/VSS routing carries the real branch
current, so its series resistance is in the loop that sets every branch's
operating point -- an effect no schematic-level record can see. This record
substantiates the SAME claim (README.md 'Target specification' row 'Iq',
`< 50 uA`) against a netlist genuinely derived from the routed GDS via
`klt extract --parasitics`, with the extraction's generic LVS device-class
placeholders translated to simulatable sky130 vendor models -- see
`sim/bin/post_layout_common.py`'s module docstring for that methodology.

Unlike the box-TC bench, this one runs the FULL 45-point PVT matrix with no
collapsed axis: `sim/quiescent-current/experiment.json` sweeps nothing
internally (a single `op` per point), and its own notes make the same
argument ("an operating point is cheap and Iq is meaningful at every
individual corner").

The measurement set is `sim/quiescent-current/experiment.json`'s, unchanged
and unedited -- including its two degenerate-state guards (`vref` in a wide
1.0-1.4 V band and `vgdrv` <= 2.9 V), which are what stop an all-off
solution from passing the Iq upper limit trivially. On the extracted netlist
those guards do a second job: a translation that silently dropped devices, or
a parasitic network that opened a supply rail, would show up as a
degenerate/dead operating point rather than as a plausible-looking small
current.

Usage
-----
    sim/quiescent-current-post-layout/run_post_layout_iq.py
    sim/quiescent-current-post-layout/run_post_layout_iq.py --dry-run

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

SLUG = "quiescent-current-post-layout"
WRAPPED_EXPERIMENT = "quiescent-current"  # manifest (corners/measurements/deck) reused unchanged
WRAPPED_SCHEMATIC = "sim/quiescent-current/testbench/tb_vref_iq.sch"

CLAIM_TAIL = (
    "Measures the total current out of the single supply source feeding the ROUTED, "
    "LVS-clean bandgap-core layout (issue #62) -- both core branches, the R2A/R2B legs "
    "and the error amplifier's mirrored tail, now including the drawn VDD/VSS routing's "
    "own series resistance -- open-circuit at VREF, over the full 45-point PVT matrix, "
    "via klt extract --parasitics translated to a simulatable netlist "
    "(sim/bin/post_layout_common.py) -- NOT design/bandgap_core.sch directly; see "
    "'Netlist provenance' below."
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
        # No axis collapsed: the full 45-point matrix, same as the
        # schematic-level bench this wraps.
        temp_override=None,
        subset_reason="",
    )


if __name__ == "__main__":
    plc.main_wrapper(cr, run)
