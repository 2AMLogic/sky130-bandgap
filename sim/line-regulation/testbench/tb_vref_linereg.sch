v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap line-regulation testbench (issue #11).
*
* Substantiates the DRAFT spec's supply row -- "Supply 3.3 V +/-10%" -- by
* measuring how far the untrimmed reference moves across that whole supply
* range, at every process corner and temperature.
*
* Method: large-signal DC sweep of the supply source, `dc v1 2.97 3.63
* 0.022` (31 points, 22 mV resolution, with the nominal 3.30 V landing
* exactly on grid index 15), reading the peak-to-peak excursion of VREF
* over the sweep. Peak-to-peak rather than endpoint-to-endpoint because a
* bandgap's line sensitivity is not monotonic in general -- the mirror can
* leave saturation at the low end -- and an endpoint difference would
* under-report exactly the case that matters. 22 mV is fine resolution for
* a peak-to-peak on this curve: a bring-up run of the same deck at 6.6 mV
* resolution (101 points) at tt / 27 degC / 3.30 V gave a 0.311 mV shift on
* a smooth characteristic, and the coarser grid is what makes the full
* 15-corner matrix affordable.
*
* Why the supply sweep lives INSIDE this bench instead of on the runner's
* supply axis: the claim is about the *shift across* the supply range, which
* is a property of a curve, not of any single supply point. Three discrete
* outer supply points cannot express it. So the deck sweeps the supply, and
* the runner is invoked with `--supply 3.3 --subset-reason ...` so the
* record says plainly that the outer supply axis was collapsed to one point
* because the bench sweeps supply itself. The process and temperature axes
* run in full (5 x 3 = 15 points), so every recorded line-regulation number
* is a full 2.97..3.63 V sweep at its own process corner and temperature.
*
* On the pass limit: the draft spec table has no dedicated line-regulation
* number -- it states the supply range and, separately, a +/-1% output
* accuracy target. The bench therefore checks the only bound that follows
* without inventing a spec: the supply-induced shift alone must fit inside
* the entire +/-1% output window (24 mV peak-to-peak on a 1.20 V nominal).
* That is a NECESSARY condition, not a sufficient one -- in a real budget,
* line regulation gets a fraction of the window, not all of it. Setting a
* real line-regulation line item is issue #1's (spec ratification) call, and
* this bench's recorded numbers are the input to that decision.
*
* Cross-check: line_psrr_db below is the large-signal DC counterpart of
* sim/psrr-dc/'s small-signal 0.1 Hz figure. They are related but not the
* same quantity -- this one is an average slope over 0.66 V of supply,
* that one is the local slope at a single bias point -- so on a
* characteristic with a shallow interior minimum a few dB of difference is
* expected, with this one the conservative figure. Tens of dB is not
* expected, and means one of the two benches is not resolving the circuit.
*
* Solver resolution (learned the hard way, record 20260803-100723-77b96e3):
* this bench measures a shift of tens of microvolts on a ~1.2 V node, which
* is BELOW ngspice's default convergence tolerance. At the default
* reltol=1e-3 the solver need only settle a 1.175 V node to ~1.2 mV, and
* the first run of this bench duly reported 0.11 .. 1.27 mV of "shift"
* that, on inspection of the raw sweep, was non-monotonic point-to-point
* jitter at exactly that amplitude -- the noise floor, not the circuit.
* That run also disagreed with sim/psrr-dc/ by ~39 dB, which is what
* exposed it. The deck therefore runs at reltol=1e-6 / vntol=1e-9 /
* abstol=1e-15 (set in experiment.json deck.options, shared by every
* DC-based bench in this suite), at which the sweep is smooth and monotone
* with a shallow minimum near 3.45 V. Do not loosen these back to the
* defaults: the measurement stops being a measurement.
*
* Load: none. VREF is read open-circuit; an output buffer / load driver is
* not part of the core cell.
*
* Startup: bandgap_core has no startup circuit yet (issue #10), so this
* bench seeds the DC solver with a .nodeset on VREF and the mirror gate so
* the first sweep point lands on the intended branch; the sweep then
* continues from that solution point to point. A .nodeset biases only the
* initial guess and is dropped before the final Newton iterations.
*
* Deliberately NOT in this schematic (the corner runner injects them):
*   - the .lib model corner include, .temp
*   - the numeric supply value: V1 is 'vsup', a .param the runner sets (and
*     which the in-deck sweep then overrides across 2.97..3.63 V)
*   - the .control analysis/measurement block
}
G {}
K {}
V {}
S {}
E {}
T {line-regulation testbench (issue #11)
DUT is design/bandgap_core.sym, read open-circuit at VREF.
Supply is swept 2.97..3.63 V inside the deck, so the runner's outer supply
axis is collapsed to a single point on purpose.
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
