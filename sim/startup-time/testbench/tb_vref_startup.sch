v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap startup-time testbench (issue #11).
*
* Substantiates the DRAFT spec line "Startup time < 1 ms" for the 3.3 V
* primary flavor (DR-001).
*
* Relationship to issue #10 (startup circuit): #11's acceptance criteria ask
* this bench to REUSE #10's ramp-transient benches rather than re-derive
* them. At the time this bench was written #10 had no merged work in the
* tree -- no design/startup_injector.*, no sim/startup-* experiment
* directory, and no open PR against #10 -- so there was nothing to reuse.
* This bench is therefore built directly, and is deliberately structured so
* that #10 can adopt it: the DUT is instantiated by symbol, the ramp shape
* is a single deck parameter (t_ramp), and the startup criterion is a pure
* vector expression, so attaching an injector to the exposed GDRV node is
* the only edit #10 needs to make.
*
* Method: supply-ramp transient. V1 is a PULSE source that ramps the supply
* from 0 V to 'vsup' (the per-corner supply the runner sets) in t_ramp, then
* holds. The deck runs `tran 1u 2m 0 5u` and measures the first time VREF
* rises through 1.08 V -- 90% of the 1.20 V draft nominal -- as the startup
* time.
*
* Why an absolute threshold and not "90% of the final value": a
* self-referential threshold is meaningless when the core never starts (90%
* of ~0 V is crossed instantly and the bench would report a startup time of
* zero, i.e. a spectacular false pass). An absolute 1.08 V threshold cannot
* be crossed by a dead core.
*
* Why the startup criterion is a vector expression and not a `meas tran ...
* WHEN` statement: if the crossing never happens, `meas ... WHEN` leaves the
* result vector undefined, the runner's `let meas_<name> = ...` line errors,
* and every LATER measurement in the same .control block is lost -- the
* record would then be a wall of "measurement not found" with no diagnosis.
* Instead the deck builds
*     up     = (v(vref) gt 1.08)             1 where the core is up
*     tcand  = time*up + (1-up)*1            sample time, else a 1 s sentinel
* (the `gt` alias, not `>`: in the ngspice command interpreter `>` is output
* redirection, so the `>` spelling is a syntax error that silently deletes
* the vector and every measurement that depends on it)
* so `minimum(tcand)` is the first crossing time, and is a well-defined
* 1000 ms if the crossing never happens. A core that fails to start is then
* recorded as a legible 1000 ms startup time against a 1 ms limit, alongside
* the vref_final / gdrv_final guards that say *why*.
*
* Startup: NO .nodeset here, on purpose. Every other bench in this suite
* seeds the DC solver so it lands on the intended branch; doing that here
* would defeat the entire measurement -- self-starting from a cold supply is
* precisely the property under test. The transient begins from the circuit's
* own t=0 solution with the supply at 0 V and has to get itself out.
*
* Load: none. VREF is read open-circuit; an output buffer / load driver is
* not part of the core cell. A capacitive load would slow startup, so an
* open-circuit result is the optimistic case and is stated as such.
*
* Deliberately NOT in this schematic (the corner runner injects them, so one
* schematic serves the whole matrix):
*   - the .lib model corner include, .temp
*   - the numeric supply value: the PULSE top level is 'vsup', a .param the
*     runner sets, and t_ramp is a .param from the manifest's deck.params
*   - the .control analysis/measurement block
}
G {}
K {}
V {}
S {}
E {}
T {startup-time testbench (issue #11)
DUT is design/bandgap_core.sym, read open-circuit at VREF.
V1 ramps 0 -> 'vsup' in t_ramp; startup time is the first crossing of
1.08 V, computed as a vector expression so a core that never starts is
recorded as 1000 ms rather than as a missing measurement.
No .nodeset: self-starting from a cold supply is the property under test.
Connectivity is by net label (lab_pin on every pin), no wires.} 100 -450 0 0 0.4 0.4 {}
C {devices/vsource.sym} 200 -200 0 0 {name=V1 value="pulse(0 'vsup' 0 't_ramp' 1n 100 200)" savecurrent=true}
C {devices/lab_pin.sym} 200 -230 0 0 {name=v1p lab=VDD}
C {devices/lab_pin.sym} 200 -170 0 0 {name=v1m lab=0}
C {design/bandgap_core.sym} 600 -200 0 0 {name=XBG}
C {devices/lab_pin.sym} 670 -200 0 0 {name=bgout lab=VREF}
C {devices/lab_pin.sym} 530 -200 0 0 {name=bggdrv lab=GDRV}
C {devices/lab_pin.sym} 600 -270 0 0 {name=bgvdd lab=VDD}
C {devices/lab_pin.sym} 600 -130 0 0 {name=bgvss lab=0}
