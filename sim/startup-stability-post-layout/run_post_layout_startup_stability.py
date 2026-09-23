#!/usr/bin/env python3
"""Post-layout (extracted-netlist) re-run of `sim/startup-stability`'s
degenerate-state / single-equilibrium claim, against the routed, LVS-clean
bandgap-core layout (issue #62) instead of `design/bandgap_core.sch` --
issue #16, the first of the two remaining "#10 startup/degenerate-state
checks" increments (the other is `sim/startup-ramp-post-layout/`).

**SUPERSEDED PREMISE (issue #285) -- this bench REFUSES to run against the
current layout.** Everything below was true until `design/startup_injector.sch`
was drawn into the composed cell. It no longer is: the extracted
`bandgap_core` body now contains the injector's six devices, so wiring a
separately netlisted schematic injector onto it would double-count the
injector on the DUT instances (XDUT/XSW) and would silently turn this bench's
bare-core CONTROL instances (XREF/XSWN) into injector-equipped ones -- with
no sign of either in the output. `run()` therefore calls
`plc.refuse_if_layout_draws_injector()` and exits 1 rather than appending a
wrong record to `sim/`. Restructuring this bench -- its own post-layout
testbench, and a decision about what the control instance should be now that
the drawn cell cannot express one -- is **issue #299**. The newest valid
record in this directory is the one taken against a pre-#285 layout record,
which is what `design/block-characterization-report.md` row 8b cites, with
that disclosure.

MIXED-PROVENANCE DUT, not all-extracted like the five earlier post-layout
benches (`output-voltage-tc`, `quiescent-current`, `psrr-dc`, `line-regulation`,
`startup-time`): `layout/bandgap-core/` composes the core + amplifier only --
`design/startup_injector.sch` (issue #10) has no layout yet. So this bench
needs the EXTRACTED core wired to the SCHEMATIC-netlisted injector.

That composition turns out to need no new body-assembly code, only this
declaration -- `sim/bin/post_layout_common.py`'s `build_extracted_body()`
already operates at `.subckt` scope: `strip_schematic_subckts()` removes only
the NAMED `bandgap_core`/`error_amp` blocks xschem emits for
`design/bandgap_core.sym`, and every `design/startup_injector.sym` instance
in `sim/startup-stability/testbench/tb_startup_stability.sch` is netlisted as
a `startup_injector` `X`-line/`.subckt` pair that name never touches. Because
xschem emits exactly ONE `.subckt bandgap_core ... .ends` definition no
matter how many `X` instances call it (four in this testbench: XDUT/XSW free-
running or forced with the injector attached, XREF/XSWN the same but WITHOUT
it, the required sim/README.md control), swapping that one definition for the
extracted, translated layout swaps EVERY instance at once -- injector-equipped
and bare-core-control alike -- which is exactly the same-DUT-everywhere shape
the schematic-level bench itself already relies on. The injector only ever
touches the core's 4 exposed pins (GDRV, VOUT as VSENSE, VDD, VSS -- verified
against `design/startup_injector.sym`'s own pin-order comment), which is
exactly `build_core_wrapper()`'s default `exposed` set, so no internal core
node the injector needs is hidden by the extraction wrapper.

Worst-corner SUBSET, not the full 45-point matrix (issue #16's Acceptance
Criteria phrase this bullet as "at worst corners", unlike the full-matrix
"#11 testbench suite" bullet the five earlier benches satisfy): process in
{ff, ss} x temperature in {-40, 125} x supply in {2.97, 3.63} = 8 corners,
the two process corners and the temperature/supply extremes
`sim/startup-stability/experiment.json`'s own `notes` field and
`sim/startup-ramp/experiment.json`'s `vref_spread` note identify as where
this design's degenerate-state margin is thinnest (ff/125 C/3.63 V is the
worst recorded `dvref`; ff/-40 C is where `sim/startup-ramp`'s sibling bench's
only two FAILs live) or where the amplifier is slowest (ss). See
`subset_reason` below for the full citation.

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
WRAPPED_EXPERIMENT = "startup-stability"  # manifest (corners/measurements/deck) reused unchanged
WRAPPED_SCHEMATIC = "sim/startup-stability/testbench/tb_startup_stability.sch"

# sim/startup-stability's claim has no "Measures " marker (unlike most other
# wrapped manifests), so an explicit split point is required. Everything from
# "Substantiates that " onward describes the schematic DUT and is replaced.
CLAIM_SPLIT = "Substantiates that "

CLAIM_TAIL = (
    "Substantiates that the ROUTED, LVS-clean bandgap-core layout (issue #62) "
    "wired to the SCHEMATIC-netlisted design/startup_injector.sch (issue #10 has "
    "no layout yet for the injector) has exactly ONE DC operating point over the "
    "whole 0..VDD range of its startup node GDRV, that the zero-current state the "
    "bare extracted core does have (reproduced here as the control instance) is "
    "actively driven away from by microamps rather than merely being unlikely, "
    "and that the loop is pulled downhill by a bounded-below current everywhere "
    "in the degenerate region rather than merely somewhere in it. Also bounds "
    "what attaching the injector costs the running extracted-core circuit: the "
    "residual current it draws out of GDRV and the shift that puts on the "
    "reference. The extracted core comes from klt extract --parasitics "
    "translated to a simulatable netlist (sim/bin/post_layout_common.py), NOT "
    "design/bandgap_core.sch directly -- see 'Netlist provenance' below; the "
    "injector is netlisted from design/startup_injector.sch UNMODIFIED, since "
    "it has no layout to extract. The startup TIME claim on this same mixed DUT "
    "is the sibling post-layout bench sim/startup-ramp-post-layout/; the "
    "+/-1% output-accuracy claim is issue #11."
)

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
    "startup-ramp bench's only two documented FAILs are both at ff/-40 C "
    "(2.97 V and 3.63 V, on vref_spread); ss is the slow-amplifier corner "
    "the same startup-ramp notes cite as the worst t_start_s "
    "(ss/125 C/2.97 V, +146 us against the 1 ms bound). tt/sf/fs and the "
    "27 C / nominal-supply interior points are intentionally omitted -- they "
    "are not where the design's own prior evidence puts the degenerate-state "
    "margin at risk, and every one of them is already covered by "
    "sim/startup-time-post-layout's full 45-point matrix on the SAME extracted "
    "core (bare, no injector), which found no NEW divergence from the "
    "schematic-level bare-core numbers at any of those points."
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
        claim_split=CLAIM_SPLIT,
        process_override=PROCESS_SUBSET,
        temp_override=TEMP_SUBSET,
        supply_override=SUPPLY_SUBSET,
        subset_reason=SUBSET_REASON,
    )


if __name__ == "__main__":
    plc.main_wrapper(cr, run)
