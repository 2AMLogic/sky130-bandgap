v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap POST-LAYOUT degenerate-state / stable-state sweep testbench
* (issue #299). Post-layout counterpart of
* sim/startup-stability/testbench/tb_startup_stability.sch, which it does NOT
* replace -- that schematic-level bench keeps its four instances and its
* bare-core control, and rows 8a/8e of design/block-characterization-report.md
* keep citing it.
*
* WHY A SEPARATE SCHEMATIC EXISTS AT ALL
* --------------------------------------
* This testbench is netlisted by
* sim/startup-stability-post-layout/run_post_layout_startup_stability.py, which
* then REPLACES the netlisted `.subckt bandgap_core` / `.subckt error_amp`
* blocks with the extracted, translated composed layout cell before handing the
* deck to ngspice. Since issue #285 that composed cell DRAWS
* design/startup_injector.sch -- MPC1, MPC2, MNS, MNI, MNC and QS are inside
* it. So every `design/bandgap_core.sym` instance below is, in the deck that
* actually runs, a core+injector instance.
*
* That is exactly why this schematic instantiates design/bandgap_core.sym ALONE
* and instantiates no design/startup_injector.sym at all. The schematic-level
* testbench does the opposite (core symbol + a separate injector symbol per
* DUT), and re-using it here would put TWO injectors on every DUT instance.
*
* READ THIS SCHEMATIC ONLY AS A POST-LAYOUT TESTBENCH. Netlisted on its own,
* without the substitution above, it is a bare-core bench and the measurements
* in sim/startup-stability-post-layout/experiment.json do not describe it.
* run_post_layout_startup_stability.py refuses to run against a layout record
* whose own reference netlist does not carry the injector's six device cards,
* so the substitution can never silently degrade into that case.
*
* NO BARE-CORE CONTROL INSTANCE, AND WHY THAT IS NOT A WEAKENING
* -------------------------------------------------------------
* The schematic-level bench carries two bare-core instances (XREF free-running,
* XSWN forced) so that imin_off_bare / i_off_bare / ncross_bare can show the
* degenerate state really is an equilibrium of the UNPROTECTED core, and so
* dvref / i_standing can price what attaching the injector costs. None of that
* is representable here: the drawn cell has an injector, so there is no
* extracted bare core to instantiate, and a schematic-netlisted bare core
* placed alongside an extracted one would make every difference a mixture of
* "what the injector costs" and "what the extraction costs" -- which is the
* mixed-provenance mistake this whole restructuring exists to remove.
*
* The control's falsifiability job is carried instead by:
*   - a structural precondition, not a number: the runner's
*     require_layout_draws_injector() guard, which aborts unless the layout
*     record under test states the injector's six devices in its own LVS
*     reference netlist (and that record's `klt lvs` is mismatch_count=0);
*   - the surviving injector-side bounds, which a missing injector cannot
*     pass. imin_off_su >= 1e-8 A and i_off_su >= 1e-6 A ARE the bare core's
*     failure mode stated as a bound: without an injector both collapse to
*     the leakage level that imin_off_bare / i_off_bare used to report, and
*     this bench FAILs instead of quietly reporting a plausible crossing.
* The bare-core statements themselves stay a schematic-level claim, carried by
* report rows 8a (sim/startup-stability/) and 8e (sim/startup-time/).
*
* Method (unchanged from the schematic-level bench)
* ------------------------------------------------
* GDRV is the one high-impedance state node of the loop (the error-amplifier
* output and the PMOS mirror gate; with the injector drawn in, also MPC1's
* source, MNI's drain and MNC's source). Force it to a known voltage with an
* ideal source and measure the current that source has to deliver to hold it
* there:
*
*     iforce(V) = current the forcing source pushes into GDRV
*               = -(net current the circuit itself pushes into GDRV)
*
* iforce(V) = 0 exactly at the circuit's own equilibria, and the sign of
* iforce tells which way the node moves when released: iforce > 0 means the
* circuit is pulling GDRV down, iforce < 0 means it is pushing GDRV up. So
*   - every zero crossing of iforce is an operating point, and
*   - a crossing from negative to positive is a *stable* one.
* Counting sign changes over the whole 0..VDD range therefore enumerates the
* operating points; "exactly one" is the claim this experiment substantiates.
*
* The forcing voltage is 'vsup' * v(ALPHA) rather than a plain swept source,
* so the sweep covers exactly 0..VDD at every supply corner on a fixed
* 251-point grid (`dc valpha 0 1 0.004` in the manifest -- the sign-change
* count and the degenerate-region windows ifsu[188,250] / ifsu[225,250] index
* that grid by literal position). It never runs GDRV above VDD, which would
* forward-bias the injector PMOS source-to-nwell junction and manufacture a
* meaningless equilibrium.
*
* Two independent instances, each on its own supply, both solved at every
* sweep point:
*
*   XSW   composed cell, GDRV forced       -> the claim
*   XDUT  composed cell, free-running      -> the operating point it settles at
*
* XDUT needs no .nodeset seed -- the drawn injector places the loop on the
* intended branch by itself, which is itself part of the evidence (contrast
* the schematic-level bench, whose bare-core XREF instance does need one).
*
* Deliberately NOT in this schematic (the corner runner injects them, so one
* schematic serves the whole PVT matrix):
*   - the .lib model corner include, .temp
*   - the numeric supply value: sources are 'vsup', a .param the runner sets
*   - the .control analysis/measurement block (the dc sweep of VALPHA and the
*     sign-change arithmetic live in
*     sim/startup-stability-post-layout/experiment.json)
}
G {}
K {}
V {}
S {}
E {}
T {POST-LAYOUT startup stable-state sweep -- enumerate the equilibria of GDRV
Every bandgap_core instance below is replaced by the EXTRACTED composed layout
cell, which since issue #285 contains the startup injector. No startup_injector
symbol is instantiated here on purpose, and there is no bare-core control --
see the header comment.
Connectivity is by net label (lab_pin on every pin), no wires.} 100 -700 0 0 0.4 0.4 {}
C {devices/code_shown.sym} 100 -900 0 0 {name=TB_FORCE only_toplevel=true value="
* ALPHA is the normalized sweep variable: the runner's dc analysis sweeps
* VALPHA from 0 to 1, and the B-source turns that into 0 .. vsup on the forced
* GDRV node. VPSW is a 0 V current probe in series with that forcing source --
* i(vpsw) is the current the forcing source has to deliver, i.e. the negated
* self-current of the circuit.
VALPHA ALPHA 0 0
BSW NSW 0 V='vsup*v(ALPHA)'
VPSW GSW NSW 0
.save i(vpsw)
"}
C {devices/vsource.sym} 200 -200 0 0 {name=V1 value='vsup' savecurrent=true}
C {devices/lab_pin.sym} 200 -230 0 0 {name=v1p lab=VDDA}
C {devices/lab_pin.sym} 200 -170 0 0 {name=v1m lab=0}
C {devices/vsource.sym} 200 -600 0 0 {name=V3 value='vsup' savecurrent=true}
C {devices/lab_pin.sym} 200 -630 0 0 {name=v3p lab=VDDC}
C {devices/lab_pin.sym} 200 -570 0 0 {name=v3m lab=0}
C {design/bandgap_core.sym} 600 -200 0 0 {name=XDUT}
C {devices/lab_pin.sym} 670 -200 0 0 {name=bgdout lab=VREFD}
C {devices/lab_pin.sym} 530 -200 0 0 {name=bgdgdrv lab=GD}
C {devices/lab_pin.sym} 600 -270 0 0 {name=bgdvdd lab=VDDA}
C {devices/lab_pin.sym} 600 -130 0 0 {name=bgdvss lab=0}
C {design/bandgap_core.sym} 600 -600 0 0 {name=XSW}
C {devices/lab_pin.sym} 670 -600 0 0 {name=bgwout lab=VREFW}
C {devices/lab_pin.sym} 530 -600 0 0 {name=bgwgdrv lab=GSW}
C {devices/lab_pin.sym} 600 -670 0 0 {name=bgwvdd lab=VDDC}
C {devices/lab_pin.sym} 600 -530 0 0 {name=bgwvss lab=0}
