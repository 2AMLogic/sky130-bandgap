#!/usr/bin/env python3
"""Post-layout (extracted-netlist) re-run of `sim/line-regulation`'s
untrimmed line-regulation claim, against the routed, LVS-clean bandgap-core
layout (issue #62) instead of `design/bandgap_core.sch` (issue #16).

Fourth increment of issue #16's post-layout suite, after
`sim/output-voltage-tc-post-layout/`, `sim/quiescent-current-post-layout/`
and `sim/psrr-dc-post-layout/`. This bench measures the same physical
quantity `psrr-dc-post-layout` measures (supply-to-VREF rejection), but as a
large-signal DC sweep (0.66 V of supply excursion) instead of a small-signal
AC transfer function -- `sim/psrr-dc/experiment.json`'s own notes call these
two independent, cross-checking measurements of the same underlying
mechanism, expected to differ by a few dB but not by tens of dB. Re-running
both on the extracted netlist gives that cross-check a post-layout data
point too.

`sim/line-regulation/experiment.json` sweeps the supply INSIDE the deck
(`dc v1 2.97 3.63 0.022`, an ngspice `.dc <source>` sweep that overrides the
outer `vsup` value for that source regardless of the corner loop), so the
schematic-level bench collapses the runner's outer supply axis to the
nominal 3.30 V and runs process x temperature in full (5 x 3 = 15 points) --
this script reuses that exact subset via `post_layout_common.py`'s
`supply_override` (added by this increment; symmetric to the
`temp_override` `output-voltage-tc-post-layout` already used for its own
in-deck box-TC sweep).

The measurement set -- including the two guards for the in-deck sweep really
running its full 2.97 .. 3.63 V, 31-point excursion (`sweep_start_v`,
`sweep_end_v`, `n_supply_points`) and the tightened solver tolerances the
manifest's own notes explain are load-bearing for this measurement's
resolution -- is `sim/line-regulation/experiment.json`'s, unchanged and
unedited.

Usage
-----
    sim/line-regulation-post-layout/run_post_layout_linereg.py
    sim/line-regulation-post-layout/run_post_layout_linereg.py --dry-run

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

SLUG = "line-regulation-post-layout"
WRAPPED_EXPERIMENT = "line-regulation"  # manifest (corners/measurements/deck) reused unchanged
WRAPPED_SCHEMATIC = "sim/line-regulation/testbench/tb_vref_linereg.sch"

CLAIM_TAIL = (
    "Measures the large-signal DC output shift of the ROUTED, LVS-clean bandgap-core "
    "layout (issue #62) as the supply is swept 2.97 .. 3.63 V INSIDE the deck, "
    "open-circuit at VREF, over the process x temperature subset (see 'Corner matrix "
    "run' below), via klt extract --parasitics translated to a simulatable netlist "
    "(sim/bin/post_layout_common.py) -- NOT design/bandgap_core.sch directly; see "
    "'Netlist provenance' below."
)

# The in-deck supply sweep makes the outer supply axis's other two points
# (2.97 V, 3.63 V) electrically identical reruns of the same sweep -- exactly
# what sim/line-regulation's own schematic-level records collapse via
# `--supply 3.3 --subset-reason`. Reused here.
SUPPLY_OVERRIDE = [3.3]
SUBSET_REASON = (
    "Reuses sim/line-regulation's own subset: the supply is swept 2.97 .. 3.63 V "
    "INSIDE the deck (dc v1 2.97 3.63 0.022), so the runner's outer supply axis is "
    "collapsed to one point (nominal 3.30 V) on purpose -- the other two outer-supply "
    "points would just rerun the identical in-deck sweep, since ngspice's .dc <source> "
    "form overrides the outer vsup value for that source. Process and temperature axes "
    "run in full (5 x 3 = 15 points)."
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
        supply_override=SUPPLY_OVERRIDE,
        subset_reason=SUBSET_REASON,
    )


if __name__ == "__main__":
    plc.main_wrapper(cr, run)
