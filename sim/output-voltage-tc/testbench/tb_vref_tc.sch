v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap output-voltage + temperature-coefficient testbench (issue #11).
*
* Substantiates two DRAFT spec lines at once, because both are read off the
* same VREF-vs-temperature curve:
*   - Output reference: 1.20 V +/-1% untrimmed  (measured at 27 degC)
*   - Temp coefficient: < 50 ppm/degC over -40..125 degC (box method)
*
* Box method, spelled out so the record is unambiguous:
*     TC[ppm/degC] = (max(VREF) - min(VREF)) / (VREF(27 degC) * (125 - -40))
*                    * 1e6
* i.e. the peak-to-peak excursion of the curve over the full military range,
* normalized to the room-temperature output and to the 165 degC span. This
* is the conservative "box" definition -- it charges the full curvature of
* the characteristic against the number, unlike an endpoint or a local
* dVREF/dT slope, either of which would flatter the result.
*
* Why the temperature sweep lives INSIDE this bench instead of on the
* runner's temperature axis: the box method needs max/min over a dense,
* continuous temperature range, and the runner's outer axis only offers
* three discrete points (-40/27/125). A three-point box would miss the
* curvature maximum entirely -- for a bandgap the extremum of the
* characteristic generally sits between the endpoints, not on them. So the
* deck sweeps `dc temp -40 125 11` (16 points, 11 degC resolution). The
* step is chosen so the grid lands exactly on BOTH endpoints
* (-40 + 15*11 = 125): the endpoints are where a bandgap characteristic
* sits furthest from its extremum, so a grid that missed 125 degC would
* systematically under-report the box excursion. The interior resolution
* is deliberately coarse -- the curve is smooth and near-quadratic, so
* missing the interior extremum by at most 5.5 degC costs ~0.13 mV of a
* ~30 mV peak-to-peak, i.e. under 1 ppm/degC. Every temperature step
* forces ngspice to re-evaluate the whole PDK model set's temperature
* parameters, which is what makes this sweep expensive; a bring-up run at
* 33 degC resolution reported 164.5 ppm/degC at tt / 27 degC / 3.30 V, so
* the reported number is not an artifact of the grid. The
* runner is invoked with `--temp 27 --subset-reason ...` so the record says
* runner is invoked with `--temp 27 --subset-reason ...` so the record says
* plainly that the outer temperature axis was collapsed to one point
* because the bench sweeps temperature itself. The process and supply axes
* run in full (5 x 3 = 15 points), so every recorded TC number is a full
* -40..125 degC sweep at its own process corner and supply.
*
* Expected physics note (design/device-characterization-summary.md section
* 1): the measured dVBE between this core's two PNP unit sizes is
* *sub-PTAT* -- ~18.1 mV of the 62.3 mV at 27 degC rides along from the
* small device's nf = 1.028 vs. the large device's nf = 1.000, which is a
* fraction of a CTAT quantity, not a PTAT one. The box TC therefore carries
* a systematic, temperature-growing curvature term on top of ordinary VBE
* curvature. Extra curvature versus a two-term (offset + linear PTAT) model
* is expected physics from that term, not automatically a bench bug.
*
* Load: none. VREF is read open-circuit; an output buffer / load driver is
* not part of the core cell.
*
* Startup: bandgap_core has no startup circuit yet (that is issue #10), so
* this bench seeds the DC solver with a .nodeset on VREF and the mirror gate
* to land the operating point on the intended branch. A .nodeset biases only
* the initial guess -- it is dropped before the final Newton iterations, so
* the reported solution is a genuine solution of the circuit. The subsequent
* `dc temp` sweep continues from that solution point to point.
*
* Deliberately NOT in this schematic (the corner runner injects them, so one
* schematic serves the whole matrix):
*   - the .lib model corner include, .temp
*   - the numeric supply value: V1 is 'vsup', a .param the runner sets
*   - the .control analysis/measurement block
}
G {}
K {}
V {}
S {}
E {}
T {output voltage + TC testbench (issue #11)
DUT is design/bandgap_core.sym, read open-circuit at VREF.
Box-method TC over -40..125 degC is swept inside the deck (dc temp), so the
runner's outer temperature axis is collapsed to a single point on purpose.
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
