v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap DC power-supply-rejection testbench (issue #11).
*
* Substantiates the DRAFT spec line "PSRR @ DC > 60 dB" for the 3.3 V
* primary flavor (DR-001).
*
* Method: small-signal AC. The supply source carries a 1 V AC magnitude on
* top of its DC value ('vsup', set per corner by the runner), so the
* transfer function from supply to reference IS v(vref) directly, and
*     PSRR(f) [dB] = -20*log10(|v(vref)(f)|) = -db(v(vref)(f))
* The deck sweeps `ac dec 10 0.1 100k` and reads the 0.1 Hz point as the DC
* figure. 0.1 Hz rather than a literal DC operating-point ratio because the
* spec line is a rejection *ratio* of a small perturbation about the
* nominal bias point, which is exactly what a small-signal AC analysis
* computes; the large-signal DC counterpart of the same quantity is
* measured independently in sim/line-regulation/ (its line_psrr_db
* measurement), so the two benches cross-check each other by construction.
*
* The AC magnitude of 1 V is a linearization scale factor, not a physical
* 1 V ripple -- AC analysis is linear by definition, so the result is
* independent of it.
*
* Index guards: the 0.1 Hz and 1 kHz readouts are taken by integer index
* into the AC sweep vector, so the bench also measures the frequency at
* those indices and pins it with a pass window. If the sweep spec ever
* changes, the guard fails loudly instead of silently reporting a
* rejection figure from the wrong frequency.
*
* Load: none. VREF is read open-circuit; an output buffer / load driver is
* not part of the core cell. (An open-circuit PSRR is the optimistic case
* for the core itself -- a loaded PSRR belongs with the buffer, which this
* block does not have.)
*
* Startup: bandgap_core has no startup circuit yet (issue #10), so this
* bench seeds the DC solver with a .nodeset on VREF and the mirror gate so
* the operating point the AC analysis linearizes about is the intended one
* and not the degenerate zero-current state. A .nodeset biases only the
* initial guess; it is dropped before the final Newton iterations.
*
* Deliberately NOT in this schematic (the corner runner injects them):
*   - the .lib model corner include, .temp
*   - the numeric supply DC value: V1's DC value is 'vsup', a .param the
*     runner sets. Only the AC magnitude is fixed here.
*   - the .control analysis/measurement block
}
G {}
K {}
V {}
S {}
E {}
T {DC PSRR testbench (issue #11)
DUT is design/bandgap_core.sym, read open-circuit at VREF.
V1 carries a 1 V AC magnitude, so v(vref) IS the supply-to-reference
transfer function and PSRR = -db(v(vref)).
Connectivity is by net label (lab_pin on every pin), no wires.} 100 -450 0 0 0.4 0.4 {}
C {devices/code_shown.sym} 100 -650 0 0 {name=TB_SEED only_toplevel=true value="
* DC-solver seed, not a forced solution: see the header note. Without it the
* solver can settle on the core's degenerate zero-current state, which is
* what issue #10's startup circuit exists to prevent in silicon.
.nodeset v(vref)=1.2 v(gdrv)=2.2
"}
C {devices/vsource.sym} 200 -200 0 0 {name=V1 value="'vsup' ac 1" savecurrent=true}
C {devices/lab_pin.sym} 200 -230 0 0 {name=v1p lab=VDD}
C {devices/lab_pin.sym} 200 -170 0 0 {name=v1m lab=0}
C {design/bandgap_core.sym} 600 -200 0 0 {name=XBG}
C {devices/lab_pin.sym} 670 -200 0 0 {name=bgout lab=VREF}
C {devices/lab_pin.sym} 530 -200 0 0 {name=bggdrv lab=GDRV}
C {devices/lab_pin.sym} 600 -270 0 0 {name=bgvdd lab=VDD}
C {devices/lab_pin.sym} 600 -130 0 0 {name=bgvss lab=0}
