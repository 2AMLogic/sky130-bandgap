v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap degenerate-state / stable-state sweep testbench (issue #10).
*
* Enumerates *every* DC equilibrium of the startup node instead of probing a
* few initial conditions, and does it in a single dc sweep so all of it fits
* one corner-runner deck.
*
* Method
* ------
* GDRV is the one high-impedance state node of the core+injector loop (the
* error-amplifier output and the PMOS mirror gate). Force it to a known
* voltage with an ideal source and measure the current that source has to
* deliver to hold it there:
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
* so the sweep covers exactly 0..VDD at every supply corner with a fixed
* 1001-point grid (the sign-change count indexes that grid by literal
* position, and a supply-dependent point count would break it). It never
* runs GDRV above VDD, which would forward-bias the injector PMOS source-
* to-nwell junction and manufacture a meaningless equilibrium.
*
* Four independent instances, each on its own supply, all solved at every
* sweep point:
*
*   XSW  + XSUW  core + startup injector, GDRV forced  -> the claim
*   XSWN         core ALONE, GDRV forced               -> the CONTROL
*   XDUT + XSU   core + startup injector, free-running -> disengage checks
*   XREF         core ALONE, free-running, nodeset-seeded onto the intended
*                branch (the same seed sim/bandgap-smoke/ needed)
*                                                      -> disengage baseline
*
* The control instance is the point sim/README.md insists on: a measurement
* that must fail if the mechanism under test is not actually active. Without
* the injector, GDRV = VDD *is* a genuine equilibrium, so i_off_bare must
* come back at leakage level; with the injector, i_off_su must come back
* orders of magnitude larger. If the harness ever stopped exercising the
* injector, i_off_su would collapse onto i_off_bare and the record would say
* so instead of quietly reporting a plausible single crossing.
*
* XDUT vs XREF isolates what attaching the injector costs the running
* circuit: dvref_disturb is the output shift and i_standing is the supply
* current the disengaged injector steals (both must be ~0, which is the
* "cleanly disengages" half of the acceptance criteria). They are read out
* of sweep point 0 -- ALPHA drives only the two forced instances, so XDUT
* and XREF hold the same operating point at every point of the sweep.
*
* This sweep is also the arbitrarily-slow-ramp limit: a supply ramp slower
* than every time constant in the loop is by definition quasi-static, and a
* quasi-static trajectory can only stall at a DC equilibrium. Showing the
* only equilibrium is the intended one is therefore a stronger statement
* than any finite ramp in sim/startup-ramp/ can make.
*
* Deliberately NOT in this schematic (the corner runner injects them, so one
* schematic serves the whole PVT matrix):
*   - the .lib model corner include, .temp
*   - the numeric supply value: sources are 'vsup', a .param the runner sets
*   - the .control analysis/measurement block (the dc sweep of VALPHA and the
*     sign-change arithmetic live in sim/startup-stability/experiment.json)
}
G {}
K {}
V {}
S {}
E {}
T {startup stable-state sweep -- enumerate the equilibria of the GDRV node
Force GDRV over 0..VDD, measure the current the forcing source must deliver;
zero crossings are the operating points. Injector-equipped instance must show
exactly one; the bare-core control instance must show the degenerate state is
a real equilibrium when the injector is absent.
Connectivity is by net label (lab_pin on every pin), no wires.} 100 -900 0 0 0.4 0.4 {}
C {devices/code_shown.sym} 100 -1150 0 0 {name=TB_FORCE only_toplevel=true value="
* ALPHA is the normalized sweep variable: the runner's dc analysis sweeps
* VALPHA from 0 to 1, and the two B-sources turn that into 0 .. vsup on the
* forced GDRV nodes. VPSW / VPSN are 0 V current probes in series with those
* forcing sources -- i(vpsw) / i(vpsn) are the currents the forcing sources
* have to deliver, i.e. the negated self-currents of the circuits.
VALPHA ALPHA 0 0
BSW NSW 0 V='vsup*v(ALPHA)'
VPSW GSW NSW 0
BSN NSN 0 V='vsup*v(ALPHA)'
VPSN GSN NSN 0
* VPSU is a 0 V probe in XSU's ground return. The injector's VDD pin only
* feeds the two PMOS bulks and its GDRV/VSENSE pins are gates, so every amp
* the disengaged injector draws leaves through this probe: i(vpsu) IS the
* standing current the injector steals from the Iq budget, measured directly
* rather than inferred from the difference of two ~31 uA supply currents
* (which the solver's own tolerance would swamp at the nA level).
VPSU VSSI 0 0
.save i(vpsw) i(vpsn) i(vpsu)
* XREF is the bare core with no startup circuit, so its DC solution has to be
* seeded onto the intended branch exactly the way sim/bandgap-smoke/ does --
* that is the whole point of this issue. A .nodeset biases only the initial
* guess and is released before the final Newton iterations, so the reported
* operating point is still a genuine solution. XDUT (core + injector) needs
* no such help, which is itself part of the evidence.
.nodeset v(VREFR)=1.2 v(GR)=2.2
"}
C {devices/vsource.sym} 200 -200 0 0 {name=V1 value='vsup' savecurrent=true}
C {devices/lab_pin.sym} 200 -230 0 0 {name=v1p lab=VDDA}
C {devices/lab_pin.sym} 200 -170 0 0 {name=v1m lab=0}
C {devices/vsource.sym} 200 -400 0 0 {name=V2 value='vsup' savecurrent=true}
C {devices/lab_pin.sym} 200 -430 0 0 {name=v2p lab=VDDB}
C {devices/lab_pin.sym} 200 -370 0 0 {name=v2m lab=0}
C {devices/vsource.sym} 200 -600 0 0 {name=V3 value='vsup' savecurrent=true}
C {devices/lab_pin.sym} 200 -630 0 0 {name=v3p lab=VDDC}
C {devices/lab_pin.sym} 200 -570 0 0 {name=v3m lab=0}
C {devices/vsource.sym} 200 -800 0 0 {name=V4 value='vsup' savecurrent=true}
C {devices/lab_pin.sym} 200 -830 0 0 {name=v4p lab=VDDD}
C {devices/lab_pin.sym} 200 -770 0 0 {name=v4m lab=0}
C {design/bandgap_core.sym} 600 -200 0 0 {name=XDUT}
C {devices/lab_pin.sym} 670 -200 0 0 {name=bgdout lab=VREFD}
C {devices/lab_pin.sym} 530 -200 0 0 {name=bgdgdrv lab=GD}
C {devices/lab_pin.sym} 600 -270 0 0 {name=bgdvdd lab=VDDA}
C {devices/lab_pin.sym} 600 -130 0 0 {name=bgdvss lab=0}
C {design/startup_injector.sym} 900 -200 0 0 {name=XSU}
C {devices/lab_pin.sym} 830 -220 0 0 {name=sug lab=GD}
C {devices/lab_pin.sym} 830 -180 0 0 {name=sus lab=VREFD}
C {devices/lab_pin.sym} 900 -250 0 0 {name=suvdd lab=VDDA}
C {devices/lab_pin.sym} 900 -150 0 0 {name=suvss lab=VSSI}
C {design/bandgap_core.sym} 600 -400 0 0 {name=XREF}
C {devices/lab_pin.sym} 670 -400 0 0 {name=bgrout lab=VREFR}
C {devices/lab_pin.sym} 530 -400 0 0 {name=bgrgdrv lab=GR}
C {devices/lab_pin.sym} 600 -470 0 0 {name=bgrvdd lab=VDDB}
C {devices/lab_pin.sym} 600 -330 0 0 {name=bgrvss lab=0}
C {design/bandgap_core.sym} 600 -600 0 0 {name=XSW}
C {devices/lab_pin.sym} 670 -600 0 0 {name=bgwout lab=VREFW}
C {devices/lab_pin.sym} 530 -600 0 0 {name=bgwgdrv lab=GSW}
C {devices/lab_pin.sym} 600 -670 0 0 {name=bgwvdd lab=VDDC}
C {devices/lab_pin.sym} 600 -530 0 0 {name=bgwvss lab=0}
C {design/startup_injector.sym} 900 -600 0 0 {name=XSUW}
C {devices/lab_pin.sym} 830 -620 0 0 {name=suwg lab=GSW}
C {devices/lab_pin.sym} 830 -580 0 0 {name=suws lab=VREFW}
C {devices/lab_pin.sym} 900 -650 0 0 {name=suwvdd lab=VDDC}
C {devices/lab_pin.sym} 900 -550 0 0 {name=suwvss lab=0}
C {design/bandgap_core.sym} 600 -800 0 0 {name=XSWN}
C {devices/lab_pin.sym} 670 -800 0 0 {name=bgnout lab=VREFN}
C {devices/lab_pin.sym} 530 -800 0 0 {name=bgngdrv lab=GSN}
C {devices/lab_pin.sym} 600 -870 0 0 {name=bgnvdd lab=VDDD}
C {devices/lab_pin.sym} 600 -730 0 0 {name=bgnvss lab=0}
