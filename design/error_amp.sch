v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap error amplifier -- schematic (issue #8).
*
* Placeholder-quality amplifier for the Kuijk core in bandgap_core.sch. Its
* job in this issue is only to close the loop well enough for a nominal
* operating point; the offset-budget-driven design (input-pair sizing,
* chopping/auto-zero, systematic-offset cancellation) is issue #9, which
* replaces this file and keeps error_amp.sym's pin list.
*
* Topology: single-stage current-mirror OTA, all devices 5 V thick-oxide
* (sky130_fd_pr__{n,p}fet_g5v0d10v5) per DR-001's 3.3 V-only scope.
*
*   MP1/MP2  PMOS input pair, sources tied to the ITAIL pin. A PMOS pair is
*            forced by the core's input common mode: the sense nodes sit at
*            one VEB (~0.73 V), far too low for an NMOS pair on 5 V devices.
*   MN1/MN2  NMOS diodes loading each input-pair drain (D1, D2)
*   MN3      mirrors MN1 -> sinks I(MP1) out of AOUT
*   MN4      mirrors MN2 -> sinks I(MP2) out of the PMOS diode PN
*   MP3/MP4  PMOS mirror -> sources I(MP2) into AOUT
*
* AOUT current = I(MP2) - I(MP1). A PMOS gate carries less current when its
* gate rises, so AOUT rises when VINP rises: VINP is the non-inverting input.
* Because AOUT is bounded only by an NMOS to VSS and a PMOS to VDD (never by
* the input pair's drain compliance), it can sit near VDD - |Vgs_p| ~ 2.2 V,
* which is what a PMOS gate in the core needs. A plain 5-transistor OTA
* cannot: its output is also an input-pair drain, so it cannot be driven
* above the tail node, and it could not drive the core's PMOS pass device.
* Three extra mirror devices buy that, and nothing else -- this is still a
* one-stage, no-compensation, no-bias-network amplifier.
*
* Bias: no internal bias network. ITAIL is a current input; the core mirrors
* the amp's tail out of the same PMOS gate that supplies the core branches,
* so amp bias tracks core bias and there is exactly one startup-sensitive
* node in the block (bandgap_core.sch's GDRV, exposed for issue #10).
*
* Parameterization: device multiplicities are .param-driven (amp_m_*); W/L
* stay literal because xschem's MOS symbol template derives ad/as/pd/ps/nrd/
* nrs from a *numeric* @W via expr(), which cannot evaluate a SPICE .param.
* Multiplicity is the axis #9/#12 need anyway (area and matching scale with
* it), and .param edits change the netlist without schematic re-entry.
*
* Connectivity is by net label (lab_pin on every device pin), no wires --
* the same convention the sim/ testbenches use.
}
G {}
K {}
V {}
S {}
E {}
T {error_amp -- single-stage current-mirror OTA (placeholder for issue #9)
PMOS input pair (input common mode is one VEB, ~0.73 V), NMOS diode loads,
NMOS + PMOS mirrors fold the second branch into AOUT so AOUT can swing to a
PMOS-gate level near VDD. Tail current comes in on the ITAIL pin.
Connectivity is by net label; no wires.} 100 -700 0 0 0.4 0.4 {}
C {devices/code_shown.sym} 100 -900 0 0 {name=AMP_PARAMS only_toplevel=false value="
* error-amp device multiplicities (unit device geometry is fixed below)
* amp_m_in    : input-pair PMOS units (W=8u L=2u each)
* amp_m_nmirr : NMOS load/mirror units (W=4u L=2u each)
* amp_m_pmirr : PMOS mirror units (W=8u L=2u each)
.param amp_m_in=2
.param amp_m_nmirr=1
.param amp_m_pmirr=1
"}
C {devices/ipin.sym} 100 -560 0 0 {name=p_vinp lab=VINP}
C {devices/ipin.sym} 100 -520 0 0 {name=p_vinn lab=VINN}
C {devices/opin.sym} 100 -480 0 0 {name=p_aout lab=AOUT}
C {devices/iopin.sym} 100 -440 0 0 {name=p_itail lab=ITAIL}
C {devices/iopin.sym} 100 -400 0 0 {name=p_vdd lab=VDD}
C {devices/iopin.sym} 100 -360 0 0 {name=p_vss lab=VSS}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 300 -500 0 0 {name=MP1
L=2
W=8
nf=1
mult='amp_m_in'
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 320 -470 0 0 {name=mp1d lab=D1}
C {devices/lab_pin.sym} 280 -500 0 0 {name=mp1g lab=VINP}
C {devices/lab_pin.sym} 320 -530 0 0 {name=mp1s lab=ITAIL}
C {devices/lab_pin.sym} 320 -500 0 0 {name=mp1b lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 500 -500 0 0 {name=MP2
L=2
W=8
nf=1
mult='amp_m_in'
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 520 -470 0 0 {name=mp2d lab=D2}
C {devices/lab_pin.sym} 480 -500 0 0 {name=mp2g lab=VINN}
C {devices/lab_pin.sym} 520 -530 0 0 {name=mp2s lab=ITAIL}
C {devices/lab_pin.sym} 520 -500 0 0 {name=mp2b lab=VDD}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 300 -300 0 0 {name=MN1
L=2
W=4
nf=1
mult='amp_m_nmirr'
model=nfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 320 -330 0 0 {name=mn1d lab=D1}
C {devices/lab_pin.sym} 280 -300 0 0 {name=mn1g lab=D1}
C {devices/lab_pin.sym} 320 -270 0 0 {name=mn1s lab=VSS}
C {devices/lab_pin.sym} 320 -300 0 0 {name=mn1b lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 500 -300 0 0 {name=MN2
L=2
W=4
nf=1
mult='amp_m_nmirr'
model=nfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 520 -330 0 0 {name=mn2d lab=D2}
C {devices/lab_pin.sym} 480 -300 0 0 {name=mn2g lab=D2}
C {devices/lab_pin.sym} 520 -270 0 0 {name=mn2s lab=VSS}
C {devices/lab_pin.sym} 520 -300 0 0 {name=mn2b lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 700 -300 0 0 {name=MN3
L=2
W=4
nf=1
mult='amp_m_nmirr'
model=nfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 720 -330 0 0 {name=mn3d lab=AOUT}
C {devices/lab_pin.sym} 680 -300 0 0 {name=mn3g lab=D1}
C {devices/lab_pin.sym} 720 -270 0 0 {name=mn3s lab=VSS}
C {devices/lab_pin.sym} 720 -300 0 0 {name=mn3b lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 900 -300 0 0 {name=MN4
L=2
W=4
nf=1
mult='amp_m_nmirr'
model=nfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 920 -330 0 0 {name=mn4d lab=PN}
C {devices/lab_pin.sym} 880 -300 0 0 {name=mn4g lab=D2}
C {devices/lab_pin.sym} 920 -270 0 0 {name=mn4s lab=VSS}
C {devices/lab_pin.sym} 920 -300 0 0 {name=mn4b lab=VSS}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 700 -500 0 0 {name=MP4
L=2
W=8
nf=1
mult='amp_m_pmirr'
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 720 -470 0 0 {name=mp4d lab=AOUT}
C {devices/lab_pin.sym} 680 -500 0 0 {name=mp4g lab=PN}
C {devices/lab_pin.sym} 720 -530 0 0 {name=mp4s lab=VDD}
C {devices/lab_pin.sym} 720 -500 0 0 {name=mp4b lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 900 -500 0 0 {name=MP3
L=2
W=8
nf=1
mult='amp_m_pmirr'
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 920 -470 0 0 {name=mp3d lab=PN}
C {devices/lab_pin.sym} 880 -500 0 0 {name=mp3g lab=PN}
C {devices/lab_pin.sym} 920 -530 0 0 {name=mp3s lab=VDD}
C {devices/lab_pin.sym} 920 -500 0 0 {name=mp3b lab=VDD}
