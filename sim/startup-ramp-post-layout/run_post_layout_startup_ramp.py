#!/usr/bin/env python3
"""Post-layout (extracted-netlist) re-run of `sim/startup-ramp`'s supply-ramp
startup-TIME claim, against the routed, LVS-clean bandgap-core layout
(issue #62) instead of `design/bandgap_core.sch` -- issue #16, the second of
the two remaining "#10 startup/degenerate-state checks" increments (the
sibling is `sim/startup-stability-post-layout/`).

**SUPERSEDED PREMISE (issue #285) -- this bench REFUSES to run against the
current layout**, for exactly the reason its sibling does: the composed cell
now draws `design/startup_injector.sch` itself, so the separately netlisted
schematic injector below would be a SECOND one on XSLOW/XFAST/XDEGN, and the
bare-core control XNOSU would stop being bare. `run()` calls
`plc.refuse_if_layout_draws_injector()` and exits 1 instead of appending a
wrong record. Restructuring is **issue #299**; the newest valid record here is
the one taken against a pre-#285 layout record, which
`design/block-characterization-report.md` row 8d cites with that disclosure.

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

"Roughly a minute" is a property of the HOST, not of the deck, and issue #284
found the difference matters: the same corner that took ~105 s on the Darwin
arm64 machine `20260910-004925-e8e2e46` was minted on took well over half an
hour on the shared Linux x86_64 fleet host, where a 45-point serial re-run is
not practical. This script's DEFAULT is still the full matrix -- nothing below
pins an axis -- but the shared runner now accepts
`--process/--temp/--supply/--subset-reason` (issue #284,
`sim/bin/post_layout_common.parse_post_layout_args`) so a capacity-limited
re-run states its reason in the record instead of being done by editing this
file. `sim/startup-ramp-post-layout/README.md` indexes which records are
subsets and why. Note the ORDER of the two gates: the #285 refusal above fires
first, so those flags are only reachable once #299 restructures this bench --
they are recorded here because #284's own 2-point subset record
(`20260923-093126-079a778`, taken against the pre-#285 layout record while that
was still the freshest one) was produced with them, and whatever #299 builds
will have the same host-capacity problem to state in its records.

Usage
-----
    sim/startup-ramp-post-layout/run_post_layout_startup_ramp.py
    sim/startup-ramp-post-layout/run_post_layout_startup_ramp.py --dry-run
    # capacity-limited subset (reason is REQUIRED and is written into the record):
    sim/startup-ramp-post-layout/run_post_layout_startup_ramp.py \
        --process tt,sf --temp=-40,125 --supply=3.63 --subset-reason "..."

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
    # The MIXED-PROVENANCE premise above is only true while the composed cell
    # has no injector of its own. Issue #285 drew one in, so this refuses
    # rather than minting a double-injector record (issue #299).
    plc.refuse_if_layout_draws_injector(SLUG)
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
