v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap harness smoke testbench.
*
* NOT a bandgap. This schematic exists only to prove the harness path
* xschem -> netlist -> ngspice (with sky130 device models) -> parsed results
* round-trips, and that the process/voltage/temperature knobs the corner
* runner injects actually move the answer.
*
* Circuit: a 1 Mohm ideal resistor biases a diode-connected sky130 5 V I/O
* nFET (nfet_g5v0d10v5, the device family the 3.3 V supply implies) from the
* supply rail. The two measured quantities are strongly corner- and
* temperature-dependent, so a record that shows identical numbers across
* corners means the harness is not actually applying corners:
*   vgs  = v(vg)   -- gate-source voltage of the diode-connected device
*   isup = -i(v1)  -- current drawn from the supply
*
* Deliberately NOT in this schematic (the corner runner injects them, so one
* schematic serves the whole PVT matrix):
*   - the .lib model corner include (no sky130_fd_pr/corner.sym instance)
*   - .temp
*   - the numeric supply value: V1 is 'vsup', a .param the runner sets
*   - the .control analysis/measurement block
}
G {}
K {}
V {}
S {}
E {}
T {harness smoke testbench -- not the bandgap
connectivity is by net label (lab_pin on every device pin), no wires
supply value comes from .param vsup (corner runner)
corner (.lib) and .temp are injected by the corner runner} 0 -300 0 0 0.4 0.4 {}
C {devices/vsource.sym} 0 -100 0 0 {name=V1 value='vsup' savecurrent=true}
C {devices/lab_pin.sym} 0 -130 0 0 {name=pv1 lab=VDD}
C {devices/lab_pin.sym} 0 -70 0 0 {name=pv2 lab=0}
C {devices/res.sym} 200 -200 0 0 {name=R1 value=1meg m=1}
C {devices/lab_pin.sym} 200 -230 0 0 {name=pr1 lab=VDD}
C {devices/lab_pin.sym} 200 -170 0 0 {name=pr2 lab=VG}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 300 -100 0 0 {name=M1
L=1
W=2
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 320 -130 0 0 {name=pm1 lab=VG}
C {devices/lab_pin.sym} 280 -100 0 0 {name=pm2 lab=VG}
C {devices/lab_pin.sym} 320 -70 0 0 {name=pm3 lab=0}
C {devices/lab_pin.sym} 320 -100 0 0 {name=pm4 lab=0}
