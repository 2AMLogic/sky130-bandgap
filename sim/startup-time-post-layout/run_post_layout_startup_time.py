#!/usr/bin/env python3
"""Post-layout (extracted-netlist) re-run of `sim/startup-time`'s supply-ramp
startup-time claim, against the routed, LVS-clean bandgap-core layout
(issue #62) instead of `design/bandgap_core.sch` (issue #16).

Fifth increment of issue #16's post-layout suite, and the LAST of the five
spec lines the Acceptance Criteria's "full #11 testbench suite" bullet
enumerates (output V + TC box, PSRR at DC, line regulation, Iq, startup
time) -- the other four landed as PR #134, #137, #139 and #142.

`sim/startup-time`'s DUT is the BARE core: `design/bandgap_core.sym` alone,
with GDRV exposed and no startup injector attached (its own manifest claim
says so explicitly -- the core cell as merged by issue #8 has no injector,
and a failure here is a statement about the missing injector, not about the
bench).

**The post-layout DUT is no longer that same circuit (issue #285).** Until
issue #285 the routed layout WAS the bare core -- `layout/bandgap-core/`
composed the core + amplifier and promoted GDRV as a pin, and
`design/startup_injector.sch` had no layout at all -- so the schematic-level
and post-layout DUTs matched and the comparison was apples to apples. The
injector is now drawn into the composed cell, so the extracted netlist this
bench runs is core + injector while the wrapped schematic bench stays the
bare core. That asymmetry is deliberate and is the WHOLE POINT of the row
this bench feeds (`design/block-characterization-report.md` row 8e): the
schematic side records what the unprotected core does (park in the
degenerate all-off state), the post-layout side records what the cell that
would actually be fabricated does. A verdict flip between the two halves of
row 8e is therefore the expected outcome of drawing the injector, not a
provenance error -- and the numbers that name it are `gdrv_final` (parks at
VDD without an injector, pulled down with one) and `t_start_ms`.

Full 45-point PVT matrix: nothing in this bench's deck sweeps a PVT axis
internally (the supply ramp is a `pulse()` shaped by `t_ramp` on the corner's
own `vsup`, not a `.dc` sweep), so no axis is collapsed.

Usage
-----
    sim/startup-time-post-layout/run_post_layout_startup_time.py
    sim/startup-time-post-layout/run_post_layout_startup_time.py --dry-run

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

SLUG = "startup-time-post-layout"
WRAPPED_EXPERIMENT = "startup-time"  # manifest (corners/measurements/deck) reused unchanged
WRAPPED_SCHEMATIC = "sim/startup-time/testbench/tb_vref_startup.sch"

# sim/startup-time's claim turns to provenance at "Ramps the supply feeding
# design/bandgap_core.sch ..."; everything from there describes the schematic
# DUT and is replaced below (including its no-injector NOTE, restated for the
# layout).
CLAIM_SPLIT = "Ramps the supply feeding "

CLAIM_TAIL = (
    "Ramps the supply feeding the ROUTED, LVS-clean bandgap-core layout (issue #62) "
    "from 0 V to the corner supply in t_ramp and measures the first time VREF rises "
    "through 1.08 V (90% of the 1.20 V draft nominal), open-circuit, over the full "
    "45-point PVT matrix, via klt extract --parasitics translated to a simulatable "
    "netlist (sim/bin/post_layout_common.py) -- NOT design/bandgap_core.sch directly; "
    "see 'Netlist provenance' below. NOTE: the no-injector caveat the schematic-level "
    "manifest carries does NOT apply to this record any more (issue #285). The "
    "composed cell now DRAWS design/startup_injector.sch -- six devices (MPC1, MPC2, "
    "MNS, MNI, MNC, QS), LVS-matched against a reference netlist that carries them "
    "too -- so this bench measures the extracted core AS DRAWN, injector included, "
    "while the wrapped schematic bench stays the bare core. The two halves of this "
    "spec line therefore measure DIFFERENT circuits on purpose: schematic = the "
    "unprotected core (parks in the all-off degenerate state), post-layout = the "
    "cell that would be fabricated. Read this record against the layout record named "
    "under 'Netlist provenance', not against the schematic-level record."
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
        claim_split=CLAIM_SPLIT,
    )


if __name__ == "__main__":
    plc.main_wrapper(cr, run)
