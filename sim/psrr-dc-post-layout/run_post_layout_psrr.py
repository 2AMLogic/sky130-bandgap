#!/usr/bin/env python3
"""Post-layout (extracted-netlist) re-run of `sim/psrr-dc`'s power-supply
rejection ratio claim, against the routed, LVS-clean bandgap-core layout
(issue #62) instead of `design/bandgap_core.sch` (issue #16).

Third increment of issue #16's post-layout suite, after
`sim/output-voltage-tc-post-layout/` and
`sim/quiescent-current-post-layout/`. PSRR is the spec line most directly
exposed to the drawn VDD/VSS routing's own series impedance: the whole
measurement IS the supply-to-VREF small-signal transfer function
(`-db(v(vref))` under a 1 V AC magnitude on the supply), so any extracted
routing resistance/capacitance the schematic cannot see sits directly in the
signal path this bench characterizes -- unlike Iq, where the routing
resistance is a second-order effect on the DC operating point.

This record substantiates the SAME claim
(`sim/psrr-dc/experiment.json`'s `psrr_dc`/`psrr_1k`/`psrr_band_min`/`psrr_1m`
measurements, README.md 'Target specification' row 'PSRR', DR-005 amended by
DR-006) against a netlist genuinely derived from the routed GDS via
`klt extract --parasitics`, with the extraction's generic LVS device-class
placeholders translated to simulatable sky130 vendor models -- see
`sim/bin/post_layout_common.py`'s module docstring for that methodology.

The measurement set, corner matrix, AC sweep (0.1 Hz .. 1 MHz, 10 pts/decade,
71 points) and the tightened solver tolerances (reltol=1e-6, vntol=1e-9,
abstol=1e-15 -- see `sim/psrr-dc/experiment.json`'s own notes on why the
defaults are not enough to resolve this measurement) all come from
`sim/psrr-dc/experiment.json`, unchanged and unedited. The band-interior
guard `psrr_band_min` (issue #127) and the two index guards on `psrr_dc`/
`psrr_1k` (`f_dc`/`f_1k`) do a second job here beyond their schematic-level
one: on the extracted netlist they also rule out a translation that silently
dropped a device or a parasitic network that opened a signal path from
showing up as a plausible-looking but wrong number instead of a visibly
broken sweep.

Usage
-----
    sim/psrr-dc-post-layout/run_post_layout_psrr.py
    sim/psrr-dc-post-layout/run_post_layout_psrr.py --dry-run

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

SLUG = "psrr-dc-post-layout"
WRAPPED_EXPERIMENT = "psrr-dc"  # manifest (corners/measurements/deck) reused unchanged
WRAPPED_SCHEMATIC = "sim/psrr-dc/testbench/tb_vref_psrr.sch"

CLAIM_TAIL = (
    "Measures the AC supply-to-VREF transfer function (1 V AC magnitude on the supply, "
    "PSRR = -db(v(vref))) of the ROUTED, LVS-clean bandgap-core layout (issue #62) -- now "
    "including the drawn VDD/VSS routing's own series R/C parasitics directly in the signal "
    "path under test -- open-circuit at VREF, over the full 45-point PVT matrix, via "
    "klt extract --parasitics translated to a simulatable netlist "
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
        # No axis collapsed: the AC sweep lives entirely inside the deck's
        # own "ac dec 10 0.1 1meg" analysis, so the outer PVT matrix runs in
        # full, same as the schematic-level bench this wraps.
        temp_override=None,
        subset_reason="",
    )


if __name__ == "__main__":
    plc.main_wrapper(cr, run)
