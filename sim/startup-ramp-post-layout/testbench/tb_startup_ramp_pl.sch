v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap POST-LAYOUT supply-ramp startup testbench (issue #299).
* Post-layout counterpart of sim/startup-ramp/testbench/tb_startup_ramp.sch,
* which it does NOT replace -- that schematic-level bench keeps its four
* copies and its bare-core control, and report row 8c keeps citing it.
*
* WHY A SEPARATE SCHEMATIC EXISTS AT ALL
* --------------------------------------
* This testbench is netlisted by
* sim/startup-ramp-post-layout/run_post_layout_startup_ramp.py, which then
* REPLACES the netlisted `.subckt bandgap_core` / `.subckt error_amp` blocks
* with the extracted, translated composed layout cell before handing the deck
* to ngspice. Since issue #285 that composed cell DRAWS
* design/startup_injector.sch -- MPC1, MPC2, MNS, MNI, MNC and QS are inside
* it. So every `design/bandgap_core.sym` instance below is, in the deck that
* actually runs, a core+injector instance.
*
* That is exactly why this schematic instantiates design/bandgap_core.sym ALONE
* and instantiates no design/startup_injector.sym at all. The schematic-level
* testbench does the opposite (core symbol + a separate injector symbol per
* copy), and re-using it here would put TWO injectors on every copy.
*
* READ THIS SCHEMATIC ONLY AS A POST-LAYOUT TESTBENCH. Netlisted on its own,
* without the substitution above, it is a bare-core bench and the measurements
* in sim/startup-ramp-post-layout/experiment.json do not describe it.
* run_post_layout_startup_ramp.py refuses to run against a layout record whose
* own reference netlist does not carry the injector's six device cards, so the
* substitution can never silently degrade into that case.
*
* NO BARE-CORE CONTROL COPY, AND WHY THAT IS NOT A WEAKENING
* ----------------------------------------------------------
* The schematic-level bench carries a fourth copy, XDEGN: the same degenerate
* initial condition and the same 1 ns supply step on a core with NO injector
* attached, graded by vref_n (<= 0.95 V) and gn_n (>= 2.5 V) -- it has to stay
* stuck. That copy is not representable here: the drawn cell has an injector,
* so there is no extracted bare core to instantiate, and a schematic-netlisted
* bare core placed alongside an extracted one would be the mixed-provenance
* construction this restructuring exists to remove.
*
* The control's falsifiability job is carried instead by:
*   - a structural precondition, not a number: the runner's
*     require_layout_draws_injector() guard, which aborts unless the layout
*     record under test states the injector's six devices in its own LVS
*     reference netlist (and that record's `klt lvs` is mismatch_count=0);
*   - t_start_g itself, which IS the control's claim inverted into a bounded
*     measurement on the DUT. XDEG below starts in the degenerate state at
*     full supply; without an injector v(VREFG) never crosses 1.05 V, the
*     `meas tran ... when` finds no crossing, the runner records the
*     measurement as missing, and the corner FAILs. A bare core cannot pass
*     this bench.
* The bare-core statement itself stays a schematic-level claim, carried by
* report rows 8c (sim/startup-ramp/) and 8e (sim/startup-time/); row 8e's
* post-layout half is the same composed cell measured from the same degenerate
* start, so the two agree by construction.
*
* Three independent copies of the composed cell, one per power-up profile, all
* simulated in a single transient so every PVT point costs one ngspice
* invocation:
*
*   XSLOW   VDDS ramps 0 -> vsup in t_slow (slow supply ramp)
*   XFAST   VDDF ramps 0 -> vsup in t_fast (fast supply ramp)
*   XDEG    VDDG steps 0 -> vsup in 1 ns AND the mirror gate GG is initialised
*           to vsup -- i.e. the circuit is *placed in* the degenerate
*           zero-current state, at full supply, and asked to leave it. This is
*           the case the claim is really about; the two ramps above start from
*           GDRV = 0, which is the over-driven side of the loop, not the stuck
*           side.
*
* The transient is run with UIC, so every node starts at 0 V except GG, set by
* the .ic below. No .nodeset, no preloaded operating point.
*
* Startup time is reported two ways per ramp:
*   t_start_*  = (VREF crosses 1.05 V) - (VDD crosses 2.90 V), i.e. measured
*                from the supply arriving, which is what the "< 1 ms,
*                self-starting" spec line means. 2.90 V is used rather than
*                the 2.97 V minimum-supply endpoint so the crossing exists
*                even at the 2.97 V corner, where the ramp only *reaches*
*                2.97 V. Negative means the reference was already up before
*                the supply finished arriving (normal on the slow ramp) --
*                a pass, and the reason there is no lower limit on it.
*   t_abs_*    = absolute time of the VREF crossing from t = 0, bounded by
*                (that ramp's duration + the 1 ms spec line).
*
* vref_spread / vref_spread_early / vref_converge additionally assert the
* three copies converge to the *same* operating point (issue #284 / DR-010).
*
* Deliberately NOT in this schematic (the corner runner injects them, so one
* schematic serves the whole PVT matrix):
*   - the .lib model corner include, .temp
*   - the numeric supply value: the sources are 'vsup', a .param the runner
*     sets, and t_slow / t_fast come from the manifest's deck.params
*   - the .control analysis/measurement block
}
G {}
K {}
V {}
S {}
E {}
T {POST-LAYOUT startup ramp testbench -- three supply profiles, one transient
Every bandgap_core instance below is replaced by the EXTRACTED composed layout
cell, which since issue #285 contains the startup injector. No startup_injector
symbol is instantiated here on purpose, and there is no bare-core control copy
-- see the header comment.
Started from the zero-current state by running the transient with UIC.
Connectivity is by net label (lab_pin on every pin), no wires.
Supply value comes from .param vsup; ramp times from .param t_slow/t_fast;
corner (.lib) and .temp are injected by sim/bin/corner-run.py.} 100 -700 0 0 0.4 0.4 {}
C {devices/code_shown.sym} 100 -900 0 0 {name=TB_DEGENERATE only_toplevel=true value="
* Put the XDEG copy in the degenerate zero-current state at t = 0: its mirror
* gate starts at the supply rail, which is where the all-off solution parks it,
* while every other node starts at 0 V (UIC). Nothing holds GG there after
* t = 0 -- .ic only sets the transient's starting point -- so whether the
* circuit leaves that state is decided by the circuit, not by the deck.
.ic v(GG)='vsup'
"}
C {devices/vsource.sym} 200 -200 0 0 {name=VSLOW value="pwl(0 0 't_slow' 'vsup')" savecurrent=true}
C {devices/lab_pin.sym} 200 -230 0 0 {name=vslowp lab=VDDS}
C {devices/lab_pin.sym} 200 -170 0 0 {name=vslowm lab=0}
C {devices/vsource.sym} 200 -400 0 0 {name=VFAST value="pwl(0 0 't_fast' 'vsup')" savecurrent=true}
C {devices/lab_pin.sym} 200 -430 0 0 {name=vfastp lab=VDDF}
C {devices/lab_pin.sym} 200 -370 0 0 {name=vfastm lab=0}
C {design/bandgap_core.sym} 600 -200 0 0 {name=XSLOW}
C {devices/lab_pin.sym} 670 -200 0 0 {name=bgsout lab=VREFS}
C {devices/lab_pin.sym} 530 -200 0 0 {name=bgsgdrv lab=GS}
C {devices/lab_pin.sym} 600 -270 0 0 {name=bgsvdd lab=VDDS}
C {devices/lab_pin.sym} 600 -130 0 0 {name=bgsvss lab=0}
C {design/bandgap_core.sym} 600 -400 0 0 {name=XFAST}
C {devices/lab_pin.sym} 670 -400 0 0 {name=bgfout lab=VREFF}
C {devices/lab_pin.sym} 530 -400 0 0 {name=bgfgdrv lab=GF}
C {devices/lab_pin.sym} 600 -470 0 0 {name=bgfvdd lab=VDDF}
C {devices/lab_pin.sym} 600 -330 0 0 {name=bgfvss lab=0}
C {devices/vsource.sym} 200 -800 0 0 {name=VDEG value="pwl(0 0 1n 'vsup')" savecurrent=true}
C {devices/lab_pin.sym} 200 -830 0 0 {name=vdegp lab=VDDG}
C {devices/lab_pin.sym} 200 -770 0 0 {name=vdegm lab=0}
C {design/bandgap_core.sym} 600 -800 0 0 {name=XDEG}
C {devices/lab_pin.sym} 670 -800 0 0 {name=bggout lab=VREFG}
C {devices/lab_pin.sym} 530 -800 0 0 {name=bgggdrv lab=GG}
C {devices/lab_pin.sym} 600 -870 0 0 {name=bggvdd lab=VDDG}
C {devices/lab_pin.sym} 600 -730 0 0 {name=bggvss lab=0}
