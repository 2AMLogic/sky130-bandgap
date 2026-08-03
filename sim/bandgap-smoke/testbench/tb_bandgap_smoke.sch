v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap core smoke testbench (issue #8).
*
* Instantiates design/bandgap_core.sch (the Kuijk-style core) on a supply and
* reads its untrimmed nominal operating point. This is a *schematic-entry*
* smoke check, not a spec claim: it substantiates that the core netlists
* headlessly, biases up, and lands in the vicinity of 1.20 V at tt / 27 degC
* / 3.3 V. Full-PVT accuracy verification (the +/-1% line) is issue #11.
*
* Load: none. The reference output is read open-circuit; an output buffer /
* load driver is not part of this cell.
*
* Startup: bandgap_core has a stable zero-current state by construction (its
* amplifier tail is mirrored from the same gate that supplies the core), and
* the startup circuit that breaks it is issue #10. This testbench therefore
* seeds the DC solver with a .nodeset on the reference node and the mirror
* gate so the operating-point solver lands on the intended branch. A
* .nodeset only biases the *initial guess* -- it is removed before the final
* Newton iterations, so the reported operating point is a genuine solution
* of the circuit, not an imposed one. Once #10 lands, the nodeset can be
* dropped and startup verified as a transient instead.
*
* Deliberately NOT in this schematic (the corner runner injects them, so one
* schematic serves the whole PVT matrix):
*   - the .lib model corner include, .temp
*   - the numeric supply value: V1 is 'vsup', a .param the runner sets
*   - the .control analysis/measurement block
}
G {}
K {}
V {}
S {}
E {}
T {bandgap core smoke testbench -- nominal operating point only
DUT is design/bandgap_core.sym (Kuijk core + error_amp subcircuit).
Connectivity is by net label (lab_pin on every pin), no wires.
Supply value comes from .param vsup; corner (.lib) and .temp are injected
by sim/bin/corner-run.py.} 100 -450 0 0 0.4 0.4 {}
C {devices/code_shown.sym} 100 -650 0 0 {name=TB_SEED only_toplevel=true value="
* DC-solver seed, not a forced solution: see the header note. Without it the
* solver can settle on the core's degenerate zero-current state, which is
* what issue #10's startup circuit exists to prevent in silicon.
.nodeset v(vref)=1.2 v(gdrv)=2.2
"}
C {devices/vsource.sym} 200 -200 0 0 {name=V1 value='vsup' savecurrent=true}
C {devices/lab_pin.sym} 200 -230 0 0 {name=v1p lab=VDD}
C {devices/lab_pin.sym} 200 -170 0 0 {name=v1m lab=0}
C {design/bandgap_core.sym} 600 -200 0 0 {name=XBG}
C {devices/lab_pin.sym} 670 -200 0 0 {name=bgout lab=VREF}
C {devices/lab_pin.sym} 530 -200 0 0 {name=bggdrv lab=GDRV}
C {devices/lab_pin.sym} 600 -270 0 0 {name=bgvdd lab=VDD}
C {devices/lab_pin.sym} 600 -130 0 0 {name=bgvss lab=0}
