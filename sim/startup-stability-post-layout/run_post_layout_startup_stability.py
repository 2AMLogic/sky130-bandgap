#!/usr/bin/env python3
"""Post-layout (extracted-netlist) degenerate-state / single-equilibrium claim
for the COMPOSED bandgap-core layout cell -- the routed, LVS-clean layout of
issue #62 as it stands since issue #285 drew `design/startup_injector.sch`
into it. Sibling of `sim/startup-ramp-post-layout/`; schematic-level
counterpart is `sim/startup-stability/` (report row 8a).

ALL-EXTRACTED DUT, no longer mixed-provenance (issue #299)
----------------------------------------------------------
Until issue #285 the composed cell was core + amplifier only, so this bench
was built as a MIXED-provenance wrapper: it netlisted
`sim/startup-stability/testbench/tb_startup_stability.sch` unmodified --
extracted core swapped in for every `design/bandgap_core.sym` instance, the
testbench's own `design/startup_injector.sym` instances left netlisted at
SCHEMATIC level -- and reused that bench's `experiment.json` unchanged.

That construction is false now, in two ways at once, neither of them visible
in the output:

  * the injector-equipped instances (XDUT/XSW) would carry TWO injectors, the
    drawn one plus the separately netlisted one; and
  * the bare-core CONTROL instances (XREF/XSWN) would silently become
    injector-equipped, so `imin_off_bare`, `i_off_bare`, `ncross_bare`,
    `dvref`, `i_standing` and `i_su_standing` would all be measuring something
    other than what their notes say -- for reasons having nothing to do with
    the design.

So this bench now has its OWN testbench and OWN manifest:

  * `testbench/tb_startup_stability_pl.sch` instantiates
    `design/bandgap_core.sym` ALONE (two instances: XSW with GDRV forced,
    XDUT free-running) and instantiates no `design/startup_injector.sym` at
    all -- the extracted body supplies the injector;
  * `experiment.json` drops the six control-dependent measurements above,
    each with a stated reason and a pointer to where that claim still lives
    (see its "DROPPED MEASUREMENTS" note; the short version is: the bare-core
    statements are a SCHEMATIC-level claim, report row 8a, and the
    injector-attach cost is not representable against a monolithic drawn
    cell at all).

The bare-core control's falsifiability job is carried by two things instead.
Structurally, `plc.require_layout_draws_injector()` below aborts unless the
layout record under test states the injector's six device cards in its own
LVS reference netlist -- the mirror image of the `refuse_if_layout_draws_
injector()` guard this bench used to call, since the dangerous direction is
now "core-only layout silently measured as the composed cell". Numerically,
`imin_off_su` (>= 1e-8 A) and `i_off_su` (>= 1e-6 A) ARE the bare core's
failure mode stated as a bound: an absent injector collapses both onto the
leakage level `imin_off_bare`/`i_off_bare` used to report, three orders of
magnitude under the floor.

Worst-corner SUBSET, not the full 45-point matrix (issue #16's Acceptance
Criteria phrase this bullet as "at worst corners", unlike the full-matrix
"#11 testbench suite" bullet the five earlier benches satisfy): process in
{ff, ss} x temperature in {-40, 125} x supply in {2.97, 3.63} = 8 corners.
See `SUBSET_REASON` below for the full citation.

Usage
-----
    sim/startup-stability-post-layout/run_post_layout_startup_stability.py
    sim/startup-stability-post-layout/run_post_layout_startup_stability.py --dry-run

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

SLUG = "startup-stability-post-layout"
# This bench owns its manifest and testbench (see the module docstring): the
# schematic-level bench's measurement set cannot be reused, because six of its
# measurements are differences against a bare-core control instance the drawn
# cell cannot express.
EXPERIMENT = SLUG
SCHEMATIC = "sim/startup-stability-post-layout/testbench/tb_startup_stability_pl.sch"

# Worst-corner subset (see module docstring): ff/ss process x -40/125 C x
# 2.97/3.63 V supply extremes.
PROCESS_SUBSET = ["ff", "ss"]
TEMP_SUBSET = [-40, 125]
SUPPLY_SUBSET = [2.97, 3.63]

SUBSET_REASON = (
    "issue #16's Acceptance Criteria ask for issue #10's degenerate-state "
    "checks re-run 'at worst corners', not the full 45-point matrix "
    "sim/startup-stability's own schematic-level records use. This 8-point "
    "subset (process in {ff, ss} x temperature in {-40, 125} C x supply in "
    "{2.97, 3.63} V) is the temperature/supply extremes crossed with the two "
    "process corners sim/startup-stability/experiment.json's own notes field "
    "and sim/startup-ramp/experiment.json's vref_spread note identify as "
    "where this design's margin is thinnest: ff/125 C/3.63 V is the worst "
    "recorded dvref (+8.70 mV, record 20260803-204236-f41373d); the sibling "
    "startup-ramp bench's only two documented FAILs in its early records are "
    "both at ff/-40 C (2.97 V and 3.63 V, on vref_spread); ss is the "
    "slow-amplifier corner the same startup-ramp notes cite as the worst "
    "t_start_s (ss/125 C/2.97 V, +146 us against the 1 ms bound). tt/sf/fs "
    "and the 27 C / nominal-supply interior points are intentionally "
    "omitted -- they are not where the design's own prior evidence puts the "
    "degenerate-state margin at risk, and every one of them is already "
    "covered by sim/startup-time-post-layout's full 45-point matrix on the "
    "SAME extracted composed cell, whose 45/45 PASS (record "
    "20260923-070906-dbd57a9, t_start 0.0678-0.1818 ms, gdrv_final "
    "1.598-2.611 V) is the same 'the drawn injector evicts the degenerate "
    "state' statement measured transiently at every one of them. It also "
    "keeps this bench's cost bounded: each corner is four forced 251-point "
    "non-continuation DC sweeps over a parasitic-laden extracted netlist."
)


def run(argv: list[str]) -> int:
    # The DUT this bench claims to measure is the COMPOSED cell. Refuse rather
    # than silently measure an unprotected core against these bounds (#299).
    plc.require_layout_draws_injector(SLUG)
    return plc.run_post_layout_experiment(
        cr,
        here=HERE,
        slug=SLUG,
        wrapped_experiment=EXPERIMENT,
        wrapped_schematic=SCHEMATIC,
        claim_tail=None,  # this bench's manifest claim is already post-layout
        argv=argv,
        process_override=PROCESS_SUBSET,
        temp_override=TEMP_SUBSET,
        supply_override=SUPPLY_SUBSET,
        subset_reason=SUBSET_REASON,
    )


if __name__ == "__main__":
    plc.main_wrapper(cr, run)
