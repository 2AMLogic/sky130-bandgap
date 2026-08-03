v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap core cell -- Kuijk-style CMOS bandgap (issue #8).
*
* Topology (spec/topology-survey.md's 3.3 V primary recommendation; Brokaw
* is a fallback that #9 may or may not trigger and is deliberately not built
* here):
*
*   VDD ---+----------------+
*          |                |
*        MPOUT            MPAMP        gates tied to GDRV
*          |                |
*         VOUT             TAIL -> error_amp ITAIL pin
*          |
*     +----+----+
*    R2A       R2B          matched, n_r2 unit segments each
*     |         |
*    VA        VB           error_amp senses VA (-) and VB (+)
*     |         |
*     |        R1           n_r1 unit segments
*     |         |
*     |        VBQ
*     |         |
*    Q1        Q2           Q1: n_pnp_ctat x W0p68L0p68 (small unit)
*     |         |           Q2: n_pnp_ptat x W3p40L3p40 (large unit)
*   VSS       VSS           both diode-connected: base = collector = VSS,
*                           emitter driven (the connection the PNP
*                           characterization in #4/#35 actually measured)
*
* The amplifier forces VA = VB. R2A = R2B, so both branches carry the same
* current I, and:
*     I * R1 = VBE(Q1) - VBE(Q2) = dVBE        (PTAT)
*     VOUT   = VBE(Q1) + I * R2 = VBE(Q1) + (R2/R1) * dVBE
* i.e. the classic Vout = VBE + K*VT*ln(N) with K = R2/R1 set by an integer
* ratio of identical unit resistor segments.
*
* Device menu is fixed by the survey + device characterization (#4):
*   PNPs      sky130_fd_pr__pnp_05v5_W0p68L0p68 / _W3p40L3p40. Only two
*             geometries exist in this PDK, so the area ratio is built by
*             *paralleling unit devices* (the m/mult multiplicity below),
*             never by scaling W/L on one instance.
*   resistors sky130_fd_pr__res_high_po on every leg (+426..+627 ppm/degC
*             measured, 2.06%/sqrt(W*L) mismatch -- the better flavor of the
*             two for ratio-critical legs; res_xhigh_po is not used here).
*   MOS       sky130_fd_pr__{n,p}fet_g5v0d10v5 only (5 V thick oxide) -- no
*             1.8 V core devices anywhere in this cell, per DR-001.
*
* Sizing rationale (design/device-characterization-summary.md sections 1/4,
* record 20260801-041501-48ac24d, tt / 27 degC):
*   - Both PNP arrays are 8 units, so each unit carries ~0.66 uA at the ~5.3
*     uA branch current. That keeps ideality n <~ 1.1 over -40..125 degC on
*     the small unit (the summary caps the small unit at ~1 uA) and takes
*     sigma(dVBE) from 0.48 mV to ~0.17 mV via the model's 1/sqrt(mult) term.
*   - dVBE for this pair at that per-unit current is ~62.3 mV, so
*     R1 = 62.3 mV / 5.3 uA ~ 11.8 kohm = 7 unit segments (5 um each, W=1 um:
*     R(L) = 380 + 325*L ohm), and VOUT = VBE(Q1) + (n_r2/n_r1)*dVBE lands
*     near 1.20 V for n_r2 = 54 (R2 ~ 88 kohm, K ~ 7.5).
*   - This is *untrimmed* first-pass sizing for a nominal operating point.
*     The +/-1% spec claim over the full PVT matrix is issue #11's job, trim
*     is #13, and the offset budget that may re-size the amp is #9.
*
* Bias / startup: MPAMP mirrors the amplifier's tail current out of the same
* GDRV gate that supplies the core branches (self-biased -- no supply-
* referenced bias resistor, which would otherwise dominate the area and the
* quiescent current). The price is the usual degenerate all-zero operating
* point, which is exactly what issue #10 exists to break: GDRV is exposed on
* the symbol as the startup attachment node. No startup circuit here.
*
* Deliberately NOT in this cell: trim network (#13), startup circuit (#10),
* output load/buffer, and any corner/temperature/analysis statement (the
* corner runner injects those around the testbench that instantiates this).
*
* Connectivity is by net label (lab_pin on every device pin), no wires --
* the same convention the sim/ testbenches use.
}
G {}
K {}
V {}
S {}
E {}
T {bandgap_core -- Kuijk-style CMOS bandgap core (issue #8)
VOUT = VBE(Q1) + (n_r2/n_r1) * dVBE(Q1,Q2); amplifier forces VA = VB.
PNP area ratio is built from paralleled fixed-geometry unit devices.
All resistors are integer multiples of one res_high_po unit segment.
GDRV is the startup attachment node (issue #10); no startup circuit here.
Connectivity is by net label; no wires.} 100 -1000 0 0 0.4 0.4 {}
C {devices/code_shown.sym} 100 -1250 0 0 {name=CORE_PARAMS only_toplevel=false value="
* ---- Kuijk core parameters (issue #8) ----
* PNP emitter-area ratio N is built ONLY from paralleled unit devices:
*   N = (n_pnp_ptat * 11.56 um2) / (n_pnp_ctat * 0.4624 um2)
* Keep both counts equal to hold the pair's measured dVBE while lowering the
* per-unit current and sigma(dVBE); raise n_pnp_ptat alone for more PTAT.
.param n_pnp_ctat=8
.param n_pnp_ptat=8
* res_high_po unit segment: W = r_w um, L = r_lseg um (R ~ 380 + 325*L ohm)
.param r_w=1
.param r_lseg=5
* segment counts. K = R2/R1 is set by the integer ratio n_r2/n_r1.
.param n_r1=7
.param n_r2=54
* PMOS mirror multiplicities (unit device W=8u L=2u)
.param m_out=2
.param m_ampbias=2
"}
C {devices/opin.sym} 100 -830 0 0 {name=p_vout lab=VOUT}
C {devices/iopin.sym} 100 -790 0 0 {name=p_gdrv lab=GDRV}
C {devices/iopin.sym} 100 -750 0 0 {name=p_vdd lab=VDD}
C {devices/iopin.sym} 100 -710 0 0 {name=p_vss lab=VSS}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 300 -800 0 0 {name=MPOUT
L=2
W=8
nf=1
mult='m_out'
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 320 -770 0 0 {name=mpoutd lab=VOUT}
C {devices/lab_pin.sym} 280 -800 0 0 {name=mpoutg lab=GDRV}
C {devices/lab_pin.sym} 320 -830 0 0 {name=mpouts lab=VDD}
C {devices/lab_pin.sym} 320 -800 0 0 {name=mpoutb lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 600 -800 0 0 {name=MPAMP
L=2
W=8
nf=1
mult='m_ampbias'
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 620 -770 0 0 {name=mpampd lab=TAIL}
C {devices/lab_pin.sym} 580 -800 0 0 {name=mpampg lab=GDRV}
C {devices/lab_pin.sym} 620 -830 0 0 {name=mpamps lab=VDD}
C {devices/lab_pin.sym} 620 -800 0 0 {name=mpampb lab=VDD}
C {design/error_amp.sym} 900 -600 0 0 {name=XAMP}
C {devices/lab_pin.sym} 850 -620 0 0 {name=ampp lab=VB}
C {devices/lab_pin.sym} 850 -580 0 0 {name=ampn lab=VA}
C {devices/lab_pin.sym} 950 -600 0 0 {name=ampo lab=GDRV}
C {devices/lab_pin.sym} 890 -650 0 0 {name=ampt lab=TAIL}
C {devices/lab_pin.sym} 910 -650 0 0 {name=ampvdd lab=VDD}
C {devices/lab_pin.sym} 900 -550 0 0 {name=ampvss lab=VSS}
C {sky130_fd_pr/res_high_po.sym} 300 -600 0 0 {name=R2A
W='r_w'
L='r_lseg*n_r2'
model=res_high_po
spiceprefix=X
mult=1}
C {devices/lab_pin.sym} 300 -630 0 0 {name=r2ap lab=VOUT}
C {devices/lab_pin.sym} 300 -570 0 0 {name=r2am lab=VA}
C {devices/lab_pin.sym} 280 -600 0 0 {name=r2ab lab=VSS}
C {sky130_fd_pr/res_high_po.sym} 500 -600 0 0 {name=R2B
W='r_w'
L='r_lseg*n_r2'
model=res_high_po
spiceprefix=X
mult=1}
C {devices/lab_pin.sym} 500 -630 0 0 {name=r2bp lab=VOUT}
C {devices/lab_pin.sym} 500 -570 0 0 {name=r2bm lab=VB}
C {devices/lab_pin.sym} 480 -600 0 0 {name=r2bb lab=VSS}
C {sky130_fd_pr/pnp_05v5.sym} 300 -400 0 0 {name=Q1
model=pnp_05v5_W0p68L0p68
m='n_pnp_ctat'
spiceprefix=X}
C {devices/lab_pin.sym} 320 -370 0 0 {name=q1c lab=VSS}
C {devices/lab_pin.sym} 280 -400 0 0 {name=q1b lab=VSS}
C {devices/lab_pin.sym} 320 -430 0 0 {name=q1e lab=VA}
C {sky130_fd_pr/res_high_po.sym} 500 -400 0 0 {name=R1
W='r_w'
L='r_lseg*n_r1'
model=res_high_po
spiceprefix=X
mult=1}
C {devices/lab_pin.sym} 500 -430 0 0 {name=r1p lab=VB}
C {devices/lab_pin.sym} 500 -370 0 0 {name=r1m lab=VBQ}
C {devices/lab_pin.sym} 480 -400 0 0 {name=r1b lab=VSS}
C {sky130_fd_pr/pnp_05v5.sym} 500 -200 0 0 {name=Q2
model=pnp_05v5_W3p40L3p40
m='n_pnp_ptat'
spiceprefix=X}
C {devices/lab_pin.sym} 520 -170 0 0 {name=q2c lab=VSS}
C {devices/lab_pin.sym} 480 -200 0 0 {name=q2b lab=VSS}
C {devices/lab_pin.sym} 520 -230 0 0 {name=q2e lab=VBQ}
