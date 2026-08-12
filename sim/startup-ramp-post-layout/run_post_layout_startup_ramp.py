#!/usr/bin/env python3
"""Post-layout (extracted-netlist) re-run of `sim/startup-ramp`'s supply-ramp
startup-TIME claim, against the routed, LVS-clean bandgap-core layout
(issue #62) instead of `design/bandgap_core.sch` -- issue #16, the second of
the two remaining "#10 startup/degenerate-state checks" increments (the
sibling is `sim/startup-stability-post-layout/`).

MIXED-PROVENANCE DUT, same shape as `sim/startup-stability-post-layout/`
(see that script's module docstring for the full mechanism and the
`strip_schematic_subckts()` bug this pair of benches found and fixed in
`sim/bin/post_layout_common.py`): the extracted, translated `bandgap_core`
subckt definition swaps in for EVERY `design/bandgap_core.sym` instance this
testbench netlists (XSLOW/XFAST/XDEGN, injector-equipped, and XNOSU, the
required bare-core control) at once, while `design/startup_injector.sch`
stays netlisted unmodified -- it has no layout to extract.

FULL 45-point PVT matrix, not a worst-corner subset: unlike the DC-sweep
`sim/startup-stability` bench (heavy enough per corner -- ~7 minutes,
4 forced 251-point sweeps over the parasitic-laden extracted netlist -- that
issue #16's "at worst corners" wording is used to scope it down), a single
transient corner of this bench completes in roughly a minute even on the
extracted netlist (adaptive-timestep `tran`, not a non-continuation forced
DC sweep), so the full matrix is not a burden and gives strictly stronger
evidence than a subset would.

Usage
-----
    sim/startup-ramp-post-layout/run_post_layout_startup_ramp.py
    sim/startup-ramp-post-layout/run_post_layout_startup_ramp.py --dry-run

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

SLUG = "startup-ramp-post-layout"
WRAPPED_EXPERIMENT = "startup-ramp"  # manifest (corners/measurements/deck) reused unchanged
WRAPPED_SCHEMATIC = "sim/startup-ramp/testbench/tb_startup_ramp.sch"

# sim/startup-ramp's claim has "Measures ", the default marker: everything
# from there describes the schematic DUT and is replaced below.
CLAIM_TAIL = (
    "Measures, in a single transient per PVT point, how long the ROUTED, "
    "LVS-clean bandgap-core layout (issue #62) wired to the SCHEMATIC-"
    "netlisted design/startup_injector.sch (issue #10 has no layout yet for "
    "the injector) takes to bring VOUT up after the supply arrives, on a "
    "slow ramp, on a fast ramp, and from the worst case of all: placed *in* "
    "the degenerate zero-current state at full supply and asked to leave "
    "it. The extracted core comes from klt extract --parasitics translated "
    "to a simulatable netlist (sim/bin/post_layout_common.py), NOT "
    "design/bandgap_core.sch directly -- see 'Netlist provenance' below; "
    "the injector is netlisted from design/startup_injector.sch UNMODIFIED, "
    "since it has no layout to extract. The no-other-stable-state half of "
    "the same spec line on this same mixed DUT is the sibling post-layout "
    "bench sim/startup-stability-post-layout/; the +/-1% output-accuracy "
    "claim is issue #11."
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
    )


if __name__ == "__main__":
    plc.main_wrapper(cr, run)
