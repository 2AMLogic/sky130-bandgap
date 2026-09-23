v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap DC power-supply-rejection testbench, CORE + STARTUP
* INJECTOR (issue #300).
*
* This is sim/psrr-dc/testbench/tb_vref_psrr.sch with exactly one change:
* a design/startup_injector.sym instance (XSU) is attached to the same
* GDRV / VREF / VDD / 0 nets the core already uses. Nothing else differs --
* same 1 V AC supply source, same open-circuit VREF readout, same
* .nodeset seed, and sim/psrr-dc-with-injector/experiment.json carries the
* same 45-corner matrix, the same measurements and the same DR-006 60 dB
* floor as sim/psrr-dc/experiment.json.
*
* Why this bench exists
* ---------------------
* sim/psrr-dc/ (report row 4a) instantiates design/bandgap_core.sym ALONE,
* so no schematic-level PSRR number in this repo has ever included the
* startup injector. When issue #285 drew design/startup_injector.sch into
* the composed layout, sim/psrr-dc-post-layout/ (row 4b) flipped from
* PASS 45/45 to FAIL 25/45 (psrr_band_min 22.75 dB worst, at
* ff / 125 C / 3.63 V, against DR-006's 60 dB DC-1 kHz band-min floor).
*
* That leaves two competing explanations for the flip, which the
* post-layout bench alone cannot separate:
*
*   (a) DESIGN. The injector's diode-connected PMOS reference pair
*       (MPC1/MPC2 in design/startup_injector.sch, sourced from GDRV)
*       sources a supply-dependent current out of the amplifier's
*       high-impedance output node, making VOUT supply-dependent.
*   (b) EXTRACTION. klt extract --parasitics overstates R on short/wide
*       stubs (klayout-tools#2359, open), which would shift the drawn
*       injector's own bias and could manufacture the effect only in the
*       extracted netlist.
*
* This bench is the decisive experiment between them: it attaches the
* injector at SCHEMATIC level, where no extraction step exists at all. A
* FAIL here means the effect is a property of the design and (b) is
* exonerated; a clean 45/45 PASS here means the schematic does not exhibit
* the effect and (b) is implicated as the dominant term.
*
* It is a diagnostic companion to row 4a, not a replacement for it: row 4a
* remains the bare-core schematic PSRR claim. Read the two together --
* their difference IS the injector's cost, measured with extraction held
* out of the loop.
*
* Wiring (identical pairing pattern to sim/startup-stability's XDUT/XSU):
*   XBG design/bandgap_core.sym      VOUT->VREF  GDRV->GDRV  VDD->VDD  VSS->0
*   XSU design/startup_injector.sym  GDRV->GDRV  VSENSE->VREF  VDD->VDD  VSS->0
*
* The injector's VSENSE pin is a high-impedance gate and its VDD pin feeds
* only the two PMOS bulks, so attaching it does not load VREF resistively
* and does not add a DC path from the supply -- everything it does to this
* measurement it does through GDRV, which is exactly the mechanism under
* test.
*
* Startup / .nodeset: kept byte-identical to sim/psrr-dc's bench so that the
* injector is the ONLY variable between the two. With the injector attached
* the seed is redundant (sim/startup-stability shows the core+injector loop
* has exactly one equilibrium), but removing it here would make this bench
* differ from row 4a's in two ways instead of one, and a .nodeset biases only
* the initial guess -- it is released before the final Newton iterations, so
* the reported operating point is a genuine solution either way.
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
T {DC PSRR testbench, core + startup injector (issue #300)
DUT is design/bandgap_core.sym with design/startup_injector.sym attached to
GDRV/VREF, read open-circuit at VREF. V1 carries a 1 V AC magnitude, so
v(vref) IS the supply-to-reference transfer function and PSRR = -db(v(vref)).
Connectivity is by net label (lab_pin on every pin), no wires.} 100 -450 0 0 0.4 0.4 {}
C {devices/code_shown.sym} 100 -650 0 0 {name=TB_SEED only_toplevel=true value="
* DC-solver seed, not a forced solution: see the header note. Kept identical
* to sim/psrr-dc/testbench/tb_vref_psrr.sch so the attached injector is the
* only difference between the two benches.
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
C {design/startup_injector.sym} 900 -200 0 0 {name=XSU}
C {devices/lab_pin.sym} 830 -220 0 0 {name=sug lab=GDRV}
C {devices/lab_pin.sym} 830 -180 0 0 {name=sus lab=VREF}
C {devices/lab_pin.sym} 900 -250 0 0 {name=suvdd lab=VDD}
C {devices/lab_pin.sym} 900 -150 0 0 {name=suvss lab=0}
