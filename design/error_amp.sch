v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap error amplifier -- schematic (issue #9).
*
* Offset-budget-driven redesign of the placeholder amplifier PR #40 committed
* for issue #8. The *topology* is unchanged (it is forced by the pin list and
* by the core's needs, see below); what changes is the sizing, which is now
* derived from design/error-amp-offset-budget.md rather than picked to close
* the loop at one nominal point.
*
* Pin list is FIXED and must not change -- design/bandgap_core.sch
* instantiates this cell by name as
*     XAMP VB VA GDRV TAIL VDD VSS error_amp
* so VINP/VINN are the core's sense nodes (~0.73 V = one VEB, which forces a
* PMOS input pair), AOUT drives the core's PMOS mirror gate GDRV (which also
* has to swing to a PMOS-gate level near VDD), and ITAIL is a current input:
* the amplifier has no internal bias network, its tail comes from the core's
* MPAMP so amp bias tracks core bias.
*
* Topology: single-stage current-mirror OTA, all devices 5 V thick-oxide
* (sky130_fd_pr__{n,p}fet_g5v0d10v5) per DR-001's 3.3 V-only scope.
*
*   MP1/MP2  PMOS input pair, sources tied to the ITAIL pin
*   MN1/MN2  NMOS diodes loading each input-pair drain (D1, D2)
*   MN3      mirrors MN1 -> sinks I(MP1) out of AOUT
*   MN4      mirrors MN2 -> sinks I(MP2) out of the PMOS diode PN
*   MP3/MP4  PMOS mirror -> sources I(MP2) into AOUT
*
* AOUT current = I(MP2) - I(MP1). A PMOS gate carries less current when its
* gate rises, so AOUT rises when VINP rises: VINP is the non-inverting input.
* Because AOUT is bounded only by an NMOS to VSS and a PMOS to VDD (never by
* the input pair's drain compliance), it can sit near VDD - |Vgs_p|, which is
* what a PMOS gate in the core needs. A plain 5-transistor OTA cannot.
*
* Why this arrangement is also *systematically* well balanced (it matters as
* much as the random term the sizing below buys): MN1 and MN2 are both
* diode-connected, so the two input-pair drains sit at the same voltage and
* the input pair sees no Vds-induced imbalance. MN3 and MN4 both have their
* drains at the AOUT/PN level rather than at the diode level, so their
* channel-length-modulation errors relative to MN1/MN2 are equal and cancel
* at the AOUT summing node instead of adding. PR #40's smoke record measured
* the residual (vos_loop = 8.68 uV at tt/27 C) -- that is the *systematic*
* offset, and it is not what this issue's budget is about. The budget term is
* the *random* (local-mismatch) offset, which is set by device area and by
* the gm ratios below, and which no amount of topology symmetry removes.
*
* ---------------------------------------------------------------------------
* Sizing rationale (full derivation: design/error-amp-offset-budget.md)
* ---------------------------------------------------------------------------
* Input-referred random offset of this stage, to first order:
*
*   sigma(VOS)^2 = sigma(dVth_in)^2                        input pair
*                + (gm_n/gm_in)^2 * 4 * sigma(Vth_n)^2     MN1..MN4
*                + (gm_p/gm_in)^2 * 2 * sigma(Vth_p34)^2   MP3/MP4
*
* with sigma(Vth) = A_VT / sqrt(W*L*mult), A_VT = 8.2 mV*um (nfet_g5v0d10v5)
* and 12.0 mV*um (pfet_g5v0d10v5) -- the PDK's own sw_mm_vth0 coefficients,
* recorded in design/device-characterization-summary.md section 3.
*
* Three levers, all of them used here:
*   1. Area on every device that can inject offset. sigma scales as
*      1/sqrt(area), so this is the only lever that works on the input pair.
*   2. gm_load/gm_in < 1: the input pair runs weak-inversion (large W/L,
*      high gm/Id) while the NMOS loads and the PMOS mirror run at a
*      deliberately *high* Vov (small W/L, low gm/Id). Their Vth mismatch is
*      divided by that ratio when referred to the input.
*   3. Long channels (L = 10..20 um, inside the model's 8..20.2 um top bin)
*      for output resistance -- the same lever that buys the DC loop gain the
*      > 60 dB PSRR line needs.
*
* Per-device geometry and the resulting area (unit device x mult). The gm
* figures are MEASURED, not estimated -- range over all 45 PVT corners of
* sim/error-amp-loop/ (record 20260803-085320-e599e30):
*   MP1/MP2  W=20 L=10 mult=16 -> 3200 um^2 each   gm_in    74.2 .. 81.2 uS
*   MN1..MN4 W=8  L=20 mult=4  ->  640 um^2 each   gm_nload 32.1 .. 40.6 uS
*   MP3/MP4  W=6  L=20 mult=8  ->  960 um^2 each   gm_pmirr 26.0 .. 29.0 uS
*   MCC      W=30 L=20 mult=16 -> 9600 um^2 (compensation, see below)
* i.e. the two gm ratios the offset formula above divides by come out at
* gm_nload/gm_in = 0.43..0.53 and gm_pmirr/gm_in = 0.34..0.38 over PVT.
* Transistor area is 1.09e4 um^2 plus 9.6e3 um^2 of MOS capacitor -- an order
* of magnitude more than the core's own device area, and the honest price of
* an untrimmed, unchopped offset on this process.
*
* What that buys, measured: sigma(VOS) = 0.52 mV (1 sigma) at 27 degC over
* N = 300 Monte Carlo draws (sim/error-amp-offset-mc/, record
* 20260803-084950-e599e30), against 0.47 mV predicted by the formula above
* from the PDK's A_VT coefficients. It is NOT enough to reach an untrimmed
* +/-1 % output: through the measured offset gain of 9.65 that is 1.27 % at
* 3 sigma from the amplifier alone. See design/error-amp-offset-budget.md's
* "Finding" -- flagged back to #3/#8 rather than papered over here, and NOT
* fixed by making these devices bigger (the doc shows the area that would
* take).
*
* ---------------------------------------------------------------------------
* MCC -- loop compensation
* ---------------------------------------------------------------------------
* MCC is a thick-oxide PMOS wired as a capacitor (gate on AOUT, source, drain
* and bulk on VDD, so it sits in inversion at every PVT corner). It is a
* *capacitor built from the allowed device menu* -- issue #9 restricts this
* cell to nfet_g5v0d10v5 / pfet_g5v0d10v5, so cap_mim_m3_* is deliberately
* not used. Its gate capacitance is measured, not computed from Cox*W*L:
* cc_mcc = 21.4 pF at tt/27 degC, and the corner runner asserts a floor on it
* at every PVT point, which is what would fail loudly if the device ever fell
* out of inversion.
*
* It is not optional. Area is what buys offset, and area is capacitance: the
* devices above put picofarads on the amplifier's internal nodes, which drags
* the loop's non-dominant poles down toward the same decade as its unity-gain
* frequency. With MCC in place the measured loop is comfortable at every one
* of the 45 corners -- 49.9..51.1 dB DC loop gain, 207..231 kHz unity gain,
* 61.1..64.6 deg phase margin, 10.8..11.6 dB gain margin. (No claim is made
* here about the uncompensated variant: that would need its own record, and
* removing MCC is not something any committed record in sim/ measures.)
*
* Referencing MCC to VDD rather than VSS is deliberate: AOUT drives a PMOS
* gate whose source is VDD, so a VDD-referenced capacitor keeps that Vsg
* constant against supply steps instead of degrading high-frequency PSRR.
*
* Quiescent current is NOT a free parameter of this cell: the tail comes in
* on ITAIL from the core's MPAMP (m_ampbias = 2, mirroring m_out = 2), and
* the two mirror branches copy half of it each, so the amplifier draws
* ~2x its tail current. Sizing above changes areas and Vov, not currents.
* Measured over PVT: the amplifier draws 15.5..25.9 uA of the cell's total
* 24.2..39.1 uA, i.e. roughly two thirds -- so a chopping or auto-zero scheme
* added later has ~11 uA of headroom under the < 50 uA line at the hottest
* corner, not the ~25 uA an even split would suggest.
*
* Parameterization: device multiplicities are .param-driven (amp_m_*); W/L
* stay literal because xschem's MOS symbol template derives ad/as/pd/ps/nrd/
* nrs from a *numeric* @W via expr(), which cannot evaluate a SPICE .param.
*
* Connectivity is by net label (lab_pin on every device pin), no wires --
* the same convention the sim/ testbenches use.
}
G {}
K {}
V {}
S {}
E {}
T {error_amp -- single-stage current-mirror OTA, sized to the offset budget (issue #9)
PMOS input pair (input common mode is one VEB, ~0.73 V), NMOS diode loads,
NMOS + PMOS mirrors fold the second branch into AOUT so AOUT can swing to a
PMOS-gate level near VDD. Tail current comes in on the ITAIL pin.
Input pair is large-area / high-gm-per-amp; loads and mirror are low-gm-per-amp,
so their Vth mismatch is divided down when referred to the input. MCC is a
thick-oxide PMOS wired as a ~21 pF capacitor from AOUT to VDD: without it the
loop built from these (necessarily large, therefore capacitive) devices
oscillates.
Connectivity is by net label; no wires.} 100 -700 0 0 0.4 0.4 {}
C {devices/code_shown.sym} 100 -900 0 0 {name=AMP_PARAMS only_toplevel=false value="
* ---- error-amp device multiplicities (issue #9 sizing) ----
* Unit geometry is fixed on the instances below; mult is the matching axis
* (sigma(Vth) scales as 1/sqrt(W*L*mult) in the PDK's own model).
* amp_m_in    : input-pair PMOS units   (W=20u L=10u each -> 3200 um^2 total)
* amp_m_nmirr : NMOS load/mirror units  (W=8u  L=20u each ->  640 um^2 total)
* amp_m_pmirr : PMOS mirror units       (W=6u  L=20u each ->  960 um^2 total)
* amp_m_cc    : MOS-capacitor units     (W=30u L=20u each -> 9600 um^2 total)
.param amp_m_in=16
.param amp_m_nmirr=4
.param amp_m_pmirr=8
.param amp_m_cc=16
"}
C {devices/ipin.sym} 100 -560 0 0 {name=p_vinp lab=VINP}
C {devices/ipin.sym} 100 -520 0 0 {name=p_vinn lab=VINN}
C {devices/opin.sym} 100 -480 0 0 {name=p_aout lab=AOUT}
C {devices/iopin.sym} 100 -440 0 0 {name=p_itail lab=ITAIL}
C {devices/iopin.sym} 100 -400 0 0 {name=p_vdd lab=VDD}
C {devices/iopin.sym} 100 -360 0 0 {name=p_vss lab=VSS}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 300 -500 0 0 {name=MP1
L=10
W=20
nf=1
mult='amp_m_in'
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 320 -470 0 0 {name=mp1d lab=D1}
C {devices/lab_pin.sym} 280 -500 0 0 {name=mp1g lab=VINP}
C {devices/lab_pin.sym} 320 -530 0 0 {name=mp1s lab=ITAIL}
C {devices/lab_pin.sym} 320 -500 0 0 {name=mp1b lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 500 -500 0 0 {name=MP2
L=10
W=20
nf=1
mult='amp_m_in'
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 520 -470 0 0 {name=mp2d lab=D2}
C {devices/lab_pin.sym} 480 -500 0 0 {name=mp2g lab=VINN}
C {devices/lab_pin.sym} 520 -530 0 0 {name=mp2s lab=ITAIL}
C {devices/lab_pin.sym} 520 -500 0 0 {name=mp2b lab=VDD}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 300 -300 0 0 {name=MN1
L=20
W=8
nf=1
mult='amp_m_nmirr'
model=nfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 320 -330 0 0 {name=mn1d lab=D1}
C {devices/lab_pin.sym} 280 -300 0 0 {name=mn1g lab=D1}
C {devices/lab_pin.sym} 320 -270 0 0 {name=mn1s lab=VSS}
C {devices/lab_pin.sym} 320 -300 0 0 {name=mn1b lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 500 -300 0 0 {name=MN2
L=20
W=8
nf=1
mult='amp_m_nmirr'
model=nfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 520 -330 0 0 {name=mn2d lab=D2}
C {devices/lab_pin.sym} 480 -300 0 0 {name=mn2g lab=D2}
C {devices/lab_pin.sym} 520 -270 0 0 {name=mn2s lab=VSS}
C {devices/lab_pin.sym} 520 -300 0 0 {name=mn2b lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 700 -300 0 0 {name=MN3
L=20
W=8
nf=1
mult='amp_m_nmirr'
model=nfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 720 -330 0 0 {name=mn3d lab=AOUT}
C {devices/lab_pin.sym} 680 -300 0 0 {name=mn3g lab=D1}
C {devices/lab_pin.sym} 720 -270 0 0 {name=mn3s lab=VSS}
C {devices/lab_pin.sym} 720 -300 0 0 {name=mn3b lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 900 -300 0 0 {name=MN4
L=20
W=8
nf=1
mult='amp_m_nmirr'
model=nfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 920 -330 0 0 {name=mn4d lab=PN}
C {devices/lab_pin.sym} 880 -300 0 0 {name=mn4g lab=D2}
C {devices/lab_pin.sym} 920 -270 0 0 {name=mn4s lab=VSS}
C {devices/lab_pin.sym} 920 -300 0 0 {name=mn4b lab=VSS}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 700 -500 0 0 {name=MP4
L=20
W=6
nf=1
mult='amp_m_pmirr'
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 720 -470 0 0 {name=mp4d lab=AOUT}
C {devices/lab_pin.sym} 680 -500 0 0 {name=mp4g lab=PN}
C {devices/lab_pin.sym} 720 -530 0 0 {name=mp4s lab=VDD}
C {devices/lab_pin.sym} 720 -500 0 0 {name=mp4b lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 900 -500 0 0 {name=MP3
L=20
W=6
nf=1
mult='amp_m_pmirr'
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 920 -470 0 0 {name=mp3d lab=PN}
C {devices/lab_pin.sym} 880 -500 0 0 {name=mp3g lab=PN}
C {devices/lab_pin.sym} 920 -530 0 0 {name=mp3s lab=VDD}
C {devices/lab_pin.sym} 920 -500 0 0 {name=mp3b lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 1100 -500 0 0 {name=MCC
L=20
W=30
nf=1
mult='amp_m_cc'
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 1120 -470 0 0 {name=mccd lab=VDD}
C {devices/lab_pin.sym} 1080 -500 0 0 {name=mccg lab=AOUT}
C {devices/lab_pin.sym} 1120 -530 0 0 {name=mccs lab=VDD}
C {devices/lab_pin.sym} 1120 -500 0 0 {name=mccb lab=VDD}
