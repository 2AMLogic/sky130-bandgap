v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap offset-budget Monte Carlo testbench (issue #9).
*
* This is the *distribution* half of issue #9's evidence. sim/error-amp-loop/
* covers everything deterministic (stability, offset gain, PSRR, Iq); local
* mismatch is a different axis -- the same deck resampled N times at one
* process point -- so it is driven by sim/error-amp-offset-mc/run_amp_offset_mc.py
* rather than by sim/bin/corner-run.py, exactly the split sim/pnp-mismatch/
* already uses (see sim/README.md, "Experiments that do not go through the
* corner runner").
*
* ---------------------------------------------------------------------------
* What is in the deck and why
* ---------------------------------------------------------------------------
* The point of the experiment is that every line of design/error-amp-offset-budget.md
* is measured on the same seed stream, at the same process point, on the same
* run -- so the budget's RSS arithmetic can be checked against the measured
* total instead of being asserted.
*
* (1) XBG -- the real design/bandgap_core.sym, closed loop.
*     - `vos`  = v(XBG.VA) - v(XBG.VB), the residual across the amplifier's own
*       sense inputs. In a settled loop the amplifier's differential input
*       equals its input-referred offset plus (whatever its output has to be)
*       divided by its own voltage gain. The second term is microvolts here
*       (the amplifier's gain is ~50 dB and the core's mismatch moves GDRV by
*       only millivolts), so sigma(vos) is the amplifier's random VOS -- the
*       budget's amp term, measured in the circuit it actually sits in rather
*       than in an artificial servo rig.
*     - `vout` = v(VREF), the untrimmed reference. sigma(vout) is the total
*       the budget's three terms have to add up to. NOTE: this is a
*       mismatch-only spread at one process point -- it is NOT the +/-1%
*       untrimmed spec line, which also carries global process shift and
*       temperature curvature and belongs to issue #11.
*
* (2) The PNP term, at the multiplicity the core actually uses.
*     design/device-characterization-summary.md section 4 measured sigma(dVBE)
*     on *unit* devices and predicted the 8x-array case by the model's
*     1/sqrt(mult) term. The core (issue #8) ships n_pnp_ctat = n_pnp_ptat = 8,
*     so this deck measures the arrayed pair directly -- `dvbe8`, biased at the
*     core's own 5.3 uA branch current -- instead of inheriting the prediction.
*     `dvbe1` is the un-arrayed pair at 1 uA, included as an ANCHOR: it must
*     reproduce section 4's published numbers (63.0 mV mean, 0.480 mV sigma at
*     27 degC). If it does not, this harness is wrong and nothing else in the
*     record should be believed.
*
* (3) The resistor term. `rra`/`rrb` are one R2-length (L = 270 um) and one
*     R1-length (L = 35 um) res_high_po segment chain, each driven by its own
*     ideal 1 uA source, so v(NRA)/v(NRB) is the R2/R1 ratio and its spread is
*     the ratio mismatch that scales the whole PTAT term. This measures what
*     the PDK's 2.06 %/sqrt(W*L) coefficient predicts, on the two lengths the
*     core actually uses, rather than re-deriving it by hand.
*
* Every probe is an independent instance, so ngspice's AGAUSS draws for it are
* independent of the core's -- (2) and (3) are independent estimators of the
* same coefficients the core's own devices are drawing from, not a re-read of
* the core's draw.
*
* ---------------------------------------------------------------------------
* Inputs supplied by the run script (this schematic is not standalone)
* ---------------------------------------------------------------------------
*   the .lib section (tt_mm for mismatch, tt for the control), .temp, .param
*   vsup, and the .control Monte Carlo loop. MC_MM_SWITCH is not settable from
*   a deck: the *_mm library sections are the switch, so the section name is
*   how mismatch is turned on and off. See sim/pnp-mismatch/testbench for the
*   full note on the sky130 mismatch mechanism.
}
G {}
K {}
V {}
S {}
E {}
T {offset-budget Monte Carlo testbench (issue #9)
XBG      = the real bandgap core, closed loop -> vos (amp random offset) and
           vout (total untrimmed mismatch spread).
XQ8S/XQ8L = the 8x PNP arrays the core actually ships, at the core's 5.3 uA
           branch current -> dvbe8 (the budget's PNP term, measured not scaled).
XQ1S/XQ1L = un-arrayed pair at 1 uA -> dvbe1, the anchor against
           device-characterization-summary section 4.
XRRA/XRRB = R2-length and R1-length res_high_po at 1 uA -> the R2/R1 ratio term.
Connectivity is by net label; no wires.} 100 -1100 0 0 0.4 0.4 {}
C {devices/code_shown.sym} 100 -1350 0 0 {name=TB_SEED only_toplevel=true value="
* DC-solver seed, not a forced solution: bandgap_core has a stable
* zero-current state by construction (issue #10's startup circuit is what
* breaks it in silicon). A .nodeset only biases the initial guess and is
* removed before the final Newton iterations, so each Monte Carlo sample is a
* genuine solution of that sample's circuit -- and the same seed is applied to
* every sample, so it cannot bias the spread.
*
* v(gdrv)=2.0 rather than the 2.2 sim/bandgap-smoke and sim/error-amp-loop
* use, and the difference is load-bearing HERE and nowhere else. The mirror
* gate settles near 1.97 V, so a 2.2 V guess sits on the wrong side of it;
* the deterministic runs converge anyway, but under Monte Carlo 12 of 40
* draws at -40 degC converged instead to the core's other stable solution
* (VOUT ~ 0.52 V), which would have shown up as a 350 mV sigma. With 2.0 V
* the same 40 draws all land on the operating solution. Verified not to be
* the tail wagging the dog: at 27 degC, where neither guess produces a
* degenerate sample, the two nodesets give sigma(VOUT) = 5.57 vs 5.67 mV and
* sigma(VOS) = 0.485 vs 0.495 mV over the same 40 draws -- i.e. the guess
* moves which *solution branch* the solver finds, not the spread it reports.
* The runner also classifies every sample and refuses to fold a
* non-operating one into the statistics, so this is belt and braces.
.nodeset v(vref)=1.2 v(gdrv)=2.0
"}
C {devices/vsource.sym} 200 -200 0 0 {name=V1 value='vsup'}
C {devices/lab_pin.sym} 200 -230 0 0 {name=v1p lab=VDD}
C {devices/lab_pin.sym} 200 -170 0 0 {name=v1m lab=0}
C {design/bandgap_core.sym} 500 -200 0 0 {name=XBG}
C {devices/lab_pin.sym} 570 -200 0 0 {name=bgout lab=VREF}
C {devices/lab_pin.sym} 430 -200 0 0 {name=bggdrv lab=GDRV}
C {devices/lab_pin.sym} 500 -270 0 0 {name=bgvdd lab=VDD}
C {devices/lab_pin.sym} 500 -130 0 0 {name=bgvss lab=0}
C {devices/isource.sym} 300 -500 0 0 {name=IE8S value=5.3u}
C {devices/lab_pin.sym} 300 -530 0 0 {name=ie8sp lab=0}
C {devices/lab_pin.sym} 300 -470 0 0 {name=ie8sm lab=E8S}
C {sky130_fd_pr/pnp_05v5.sym} 300 -380 0 0 {name=XQ8S
model=pnp_05v5_W0p68L0p68
m=8
spiceprefix=X}
C {devices/lab_pin.sym} 320 -350 0 0 {name=xq8sc lab=0}
C {devices/lab_pin.sym} 280 -380 0 0 {name=xq8sb lab=0}
C {devices/lab_pin.sym} 320 -410 0 0 {name=xq8se lab=E8S}
C {devices/isource.sym} 500 -500 0 0 {name=IE8L value=5.3u}
C {devices/lab_pin.sym} 500 -530 0 0 {name=ie8lp lab=0}
C {devices/lab_pin.sym} 500 -470 0 0 {name=ie8lm lab=E8L}
C {sky130_fd_pr/pnp_05v5.sym} 500 -380 0 0 {name=XQ8L
model=pnp_05v5_W3p40L3p40
m=8
spiceprefix=X}
C {devices/lab_pin.sym} 520 -350 0 0 {name=xq8lc lab=0}
C {devices/lab_pin.sym} 480 -380 0 0 {name=xq8lb lab=0}
C {devices/lab_pin.sym} 520 -410 0 0 {name=xq8le lab=E8L}
C {devices/isource.sym} 700 -500 0 0 {name=IE1S value=1u}
C {devices/lab_pin.sym} 700 -530 0 0 {name=ie1sp lab=0}
C {devices/lab_pin.sym} 700 -470 0 0 {name=ie1sm lab=E1S}
C {sky130_fd_pr/pnp_05v5.sym} 700 -380 0 0 {name=XQ1S
model=pnp_05v5_W0p68L0p68
m=1
spiceprefix=X}
C {devices/lab_pin.sym} 720 -350 0 0 {name=xq1sc lab=0}
C {devices/lab_pin.sym} 680 -380 0 0 {name=xq1sb lab=0}
C {devices/lab_pin.sym} 720 -410 0 0 {name=xq1se lab=E1S}
C {devices/isource.sym} 900 -500 0 0 {name=IE1L value=1u}
C {devices/lab_pin.sym} 900 -530 0 0 {name=ie1lp lab=0}
C {devices/lab_pin.sym} 900 -470 0 0 {name=ie1lm lab=E1L}
C {sky130_fd_pr/pnp_05v5.sym} 900 -380 0 0 {name=XQ1L
model=pnp_05v5_W3p40L3p40
m=1
spiceprefix=X}
C {devices/lab_pin.sym} 920 -350 0 0 {name=xq1lc lab=0}
C {devices/lab_pin.sym} 880 -380 0 0 {name=xq1lb lab=0}
C {devices/lab_pin.sym} 920 -410 0 0 {name=xq1le lab=E1L}
C {devices/isource.sym} 1100 -500 0 0 {name=IRA value=1u}
C {devices/lab_pin.sym} 1100 -530 0 0 {name=irap lab=0}
C {devices/lab_pin.sym} 1100 -470 0 0 {name=iram lab=NRA}
C {sky130_fd_pr/res_high_po.sym} 1100 -380 0 0 {name=XRRA
W=1
L=270
model=res_high_po
spiceprefix=X
mult=1}
C {devices/lab_pin.sym} 1100 -410 0 0 {name=xrrap lab=NRA}
C {devices/lab_pin.sym} 1100 -350 0 0 {name=xrram lab=0}
C {devices/lab_pin.sym} 1080 -380 0 0 {name=xrrab lab=0}
C {devices/isource.sym} 1300 -500 0 0 {name=IRB value=1u}
C {devices/lab_pin.sym} 1300 -530 0 0 {name=irbp lab=0}
C {devices/lab_pin.sym} 1300 -470 0 0 {name=irbm lab=NRB}
C {sky130_fd_pr/res_high_po.sym} 1300 -380 0 0 {name=XRRB
W=1
L=35
model=res_high_po
spiceprefix=X
mult=1}
C {devices/lab_pin.sym} 1300 -410 0 0 {name=xrrbp lab=NRB}
C {devices/lab_pin.sym} 1300 -350 0 0 {name=xrrbm lab=0}
C {devices/lab_pin.sym} 1280 -380 0 0 {name=xrrbb lab=0}
