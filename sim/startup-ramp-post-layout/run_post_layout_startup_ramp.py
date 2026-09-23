#!/usr/bin/env python3
"""Post-layout (extracted-netlist) supply-ramp startup-TIME claim for the
COMPOSED bandgap-core layout cell -- the routed, LVS-clean layout of issue #62
as it stands since issue #285 drew `design/startup_injector.sch` into it.
Sibling of `sim/startup-stability-post-layout/`; schematic-level counterpart
is `sim/startup-ramp/` (report row 8c).

ALL-EXTRACTED DUT, no longer mixed-provenance (issue #299)
----------------------------------------------------------
Until issue #285 the composed cell was core + amplifier only, so this bench
was built as a MIXED-provenance wrapper: it netlisted
`sim/startup-ramp/testbench/tb_startup_ramp.sch` unmodified -- extracted core
swapped in for every `design/bandgap_core.sym` instance, that testbench's own
`design/startup_injector.sym` instances left netlisted at SCHEMATIC level --
and reused its `experiment.json` unchanged. That construction is false now, in
two ways at once, neither visible in the output: XSLOW/XFAST/XDEG would carry
TWO injectors, and the bare-core control copy XDEGN would silently become
injector-equipped, so `vref_n` and `gn_n` would be measuring something other
than what their notes say.

So this bench now has its OWN testbench and OWN manifest:

  * `testbench/tb_startup_ramp_pl.sch` instantiates `design/bandgap_core.sym`
    ALONE (three copies: XSLOW, XFAST, XDEG) and instantiates no
    `design/startup_injector.sym` at all -- the extracted body supplies the
    injector;
  * `experiment.json` drops `vref_n` and `gn_n`, the two bare-core control
    measurements, with a stated reason and a pointer to where that claim still
    lives (report row 8c at schematic level; report row 8e,
    `sim/startup-time-post-layout/`, for the post-layout counterpart of
    `gn_n`, which measures `gdrv_final` on this same composed cell from the
    same degenerate start).

The control's falsifiability job is carried by two things instead.
Structurally, `plc.require_layout_draws_injector()` below aborts unless the
layout record under test states the injector's six device cards in its own LVS
reference netlist -- the mirror image of the `refuse_if_layout_draws_
injector()` guard this bench used to call, since the dangerous direction is
now "core-only layout silently measured as the composed cell". Numerically,
`t_start_g` IS the control inverted into a bound: the degenerate-start copy
begins at full supply with its mirror gate at the rail, and a DUT with no
working injector never produces the `v(VREFG) = 1.05 V` crossing that
measurement is the difference of -- the `meas tran ... when` writes no vector
and the corner is recorded as a failure.

FULL 45-point PVT matrix by default: a single transient corner completes in
roughly a minute on the extracted netlist on a fast, idle machine, so the full
matrix is not a burden and gives strictly stronger evidence than a subset.

"Roughly a minute" is a property of the HOST, not of the deck, and issue #284
found the difference matters: the same corner that took ~105 s on the Darwin
arm64 machine `20260910-004925-e8e2e46` was minted on took well over half an
hour on the shared Linux x86_64 fleet host, where a 45-point serial re-run is
not practical. Nothing below pins an axis, so the DEFAULT is still the full
matrix -- but the shared runner accepts `--process/--temp/--supply/
--subset-reason` (issue #284, `sim/bin/post_layout_common.parse_post_layout_args`)
so a capacity-limited re-run states its reason in the record instead of being
done by editing this file. `sim/startup-ramp-post-layout/README.md` indexes
which records are subsets and why.

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
# This bench owns its manifest and testbench (see the module docstring): the
# schematic-level bench's measurement set cannot be reused, because two of its
# measurements are readings on a bare-core control copy the drawn cell cannot
# express.
EXPERIMENT = SLUG
SCHEMATIC = "sim/startup-ramp-post-layout/testbench/tb_startup_ramp_pl.sch"


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
    )


if __name__ == "__main__":
    plc.main_wrapper(cr, run)
