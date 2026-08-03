v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap quiescent-current testbench (issue #11).
*
* Substantiates the DRAFT spec line "Iq < 50 uA" for the 3.3 V primary
* flavor (DR-001), over the full PVT matrix.
*
* Method: operating point, reading the total current out of the single
* supply source. Everything the block draws -- both core branches, the
* R2A/R2B legs, and the error amplifier's mirrored tail -- returns through
* V1, so -i(v1) is the whole quiescent current with nothing left out. This
* is the full 45-point PVT matrix: process x (-40/27/125 degC) x (2.97/
* 3.30/3.63 V), no subset.
*
* Degenerate-state guard, and why it is on this bench in particular: the
* core has a stable zero-current solution (no startup circuit yet -- that
* is issue #10), and in that state Iq reads near zero, which would sail
* through a "< 50 uA" check as a spectacular pass while actually meaning
* the reference is dead. So this bench also measures VREF and the mirror
* gate GDRV and fails the corner if either is outside the band that says
* "the core is up and regulating". A quiescent-current number is only
* meaningful for a circuit that is actually quiescent at its intended
* operating point.
*
* Load: none. VREF is open-circuit, so this is the block's own consumption
* and excludes any load current an output buffer would draw.
*
* Startup: the .nodeset seeds the DC solver onto the intended branch; it
* biases only the initial guess and is dropped before the final Newton
* iterations, so the reported operating point is a genuine solution.
*
* Deliberately NOT in this schematic (the corner runner injects them):
*   - the .lib model corner include, .temp
*   - the numeric supply value: V1 is 'vsup', a .param the runner sets
*   - the .control analysis/measurement block
}
G {}
K {}
V {}
S {}
E {}
T {quiescent-current testbench (issue #11)
DUT is design/bandgap_core.sym, read open-circuit at VREF.
Iq = -i(v1): the whole block's supply current, core + amplifier.
VREF/GDRV guards fail the corner if the core sat in its degenerate
zero-current state, where a near-zero Iq would otherwise "pass".
Connectivity is by net label (lab_pin on every pin), no wires.} 100 -450 0 0 0.4 0.4 {}
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
