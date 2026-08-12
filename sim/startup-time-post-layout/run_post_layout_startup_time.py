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
bench). The routed layout this bench now measures is that same bare core:
`layout/bandgap-core/` composes the core + amplifier and promotes GDRV as a
pin; the injector (`design/startup_injector.sch`, issue #10) has no layout
at all yet. So the schematic-level and post-layout DUTs are the same
circuit, and the comparison is apples to apples -- unlike the two sibling
startup benches, whose injector half necessarily stays schematic-level.

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
    "see 'Netlist provenance' below. NOTE: the same no-injector caveat the schematic-"
    "level manifest carries applies unchanged here, and for the same reason -- the "
    "composed layout is the core cell with GDRV promoted as a pin, and "
    "design/startup_injector.sch has no layout yet -- so this bench measures the "
    "extracted core AS DRAWN. A failure here is a statement about the missing "
    "injector, not about the bench or the extraction; the injector-equipped "
    "post-layout benches are sim/startup-ramp-post-layout/ and "
    "sim/startup-stability-post-layout/."
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
