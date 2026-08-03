v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap error-amplifier loop testbench (issue #9).
*
* What this substantiates: the amplifier in design/error_amp.sch, *in its
* loop around design/bandgap_core.sch*, over the full PVT matrix --
*   - loop gain and phase margin (the stability acceptance criterion),
*   - the Kuijk offset gain dVOUT/dVOS the offset budget hangs on, measured
*     rather than assumed,
*   - PSRR at DC (> 60 dB line) of the closed loop,
*   - the amplifier's own share of the < 50 uA Iq budget, separated from the
*     core's share by two 0 V ammeters.
*
* ---------------------------------------------------------------------------
* Why there are two copies of the core in this deck
* ---------------------------------------------------------------------------
* XBG is the real design/bandgap_core.sym instance. It is what the Iq and
* PSRR numbers are read from, so those numbers are about the shipped cell and
* not about a hand copy of it.
*
* Loop gain, though, has to be measured with the loop *broken*, and the break
* has to happen at a node that is internal to bandgap_core: GDRV is driven by
* the amplifier's AOUT and read by the two PMOS mirror gates, all inside the
* cell. bandgap_core.sch is reference-only for this issue (it is #8's
* deliverable), so instead of re-entering it with a split node, this testbench
* carries a flattened replica of exactly its netlist -- same devices, same
* .param values, same connectivity -- with GDRV split into
*   GDRVA  the amplifier's AOUT, and
*   GDRVC  the two PMOS mirror gates,
* joined by VINJ, a 0 V DC source that is a short at DC (so the replica's
* operating point is the real cell's) and the AC injection point for the loop
* probe.
*
* A replica can go stale when the cell it copies changes. The `vref_delta`
* measurement is the guard: it compares the replica's output against the real
* cell's on every corner and fails the record if they differ by more than
* 1 uV. If someone re-sizes bandgap_core.sch and forgets this file, the
* record does not quietly report loop gain for a circuit that no longer
* exists -- it fails.
*
* ---------------------------------------------------------------------------
* Loop probe: voltage injection at the mirror-gate node
* ---------------------------------------------------------------------------
* T(f) = -v(GDRVA)/v(GDRVC): drive GDRVC (what the core sees), read back what
* comes around to GDRVA (what the amplifier puts out). A *series* voltage
* source is used rather than a cut, so the amplifier still drives the mirror
* gate capacitance -- the loading the loop actually has is preserved.
*
* Voltage injection is valid where the impedance looking forward into the
* break greatly exceeds the impedance looking back. Forward is two MOS gates
* (purely capacitive, ~0.5 pF: >300 kohm below 1 MHz); backward is the
* amplifier's output resistance in parallel with its ~20 pF compensation
* device (~8 kohm at 1 MHz, megohms at DC). The ratio is >= 40 over the whole
* band that sets the margins, so the single-injection form is used and the
* Middlebrook/Tian dual-injection correction is not needed here.
*
* ---------------------------------------------------------------------------
* Measuring the offset gain instead of asserting it
* ---------------------------------------------------------------------------
* VOSINJ sits in series with the replica amplifier's VINN pin, so it *is* an
* input-referred offset of exactly the kind the budget allocates. Driving it
* with a 1 V AC excitation at 0.01 Hz and reading |v(VOUTR)| yields
* dVOUT/dVOS directly. Kuijk's algebra predicts (1 + R2/R1) = 8.50 for this
* core's segment counts (R1 = 11.755 kohm, R2 = 88.13 kohm including the
* res_high_po end resistance, so K = 7.497, not the 54/7 = 7.714 the segment
* counts alone suggest). The measurement is what the budget doc cites.
*
* ---------------------------------------------------------------------------
* Iq split
* ---------------------------------------------------------------------------
* Four 0 V sources are ammeters, nothing else:
*   VIBG   feeds the real cell        -> iq_total = i(VIBG)   (the < 50 uA line)
*   VIREP  feeds the whole replica    -> iq_replica
*   VAVDD  feeds the replica amp's VDD pin
*   VTAIL  carries the replica amp's tail current
* so the amplifier's share is i(VTAIL) + i(VAVDD) and the core's share is
* iq_replica - that sum. iq_total and iq_replica must agree (a second,
* independent staleness guard on the replica alongside vref_delta).
*
* Deliberately NOT in this schematic (the corner runner injects them):
*   - the .lib model corner include and .temp
*   - the numeric supply value: V1 is 'vsup'
*   - the .control analysis/measurement block
}
G {}
K {}
V {}
S {}
E {}
T {error_amp loop testbench (issue #9)
XBG   = the real design/bandgap_core.sym -- Iq and PSRR are read from this.
Replica (XPOUT/XPAMP/XAMPR/XRA/XRB/XR1R/XQ1R/XQ2R) = the same netlist with
GDRV split into GDRVA (amp output) and GDRVC (mirror gates) so VINJ can break
the loop for an AC probe. vref_delta guards the replica against going stale.
VOSINJ measures the Kuijk offset gain; VTAIL/VAVDD are 0 V ammeters that split
the amplifier's Iq out of the total.
Connectivity is by net label; no wires.} 100 -1250 0 0 0.4 0.4 {}
C {devices/code_shown.sym} 100 -1550 0 0 {name=TB_PARAMS only_toplevel=true value="
* ---- replica core parameters: must match design/bandgap_core.sch ----
* (guarded by the vref_delta measurement, which compares the replica against
* the real cell on every corner)
.param n_pnp_ctat=8
.param n_pnp_ptat=8
.param r_w=1
.param r_lseg=5
.param n_r1=7
.param n_r2=54
.param m_out=2
.param m_ampbias=2

* DC-solver seed, not a forced solution. bandgap_core has a stable
* zero-current state by construction (issue #10's startup circuit is what
* breaks it in silicon); a .nodeset only biases the initial guess and is
* removed before the final Newton iterations, so the reported operating point
* is a genuine solution.
.nodeset v(vref)=1.2 v(gdrv)=2.2 v(voutr)=1.2 v(gdrva)=2.2 v(gdrvc)=2.2
"}
C {devices/vsource.sym} 200 -200 0 0 {name=V1 value='vsup' savecurrent=true}
C {devices/lab_pin.sym} 200 -230 0 0 {name=v1p lab=VDD}
C {devices/lab_pin.sym} 200 -170 0 0 {name=v1m lab=0}
C {devices/vsource.sym} 200 -400 0 0 {name=VIBG value=0 savecurrent=true}
C {devices/lab_pin.sym} 200 -430 0 0 {name=vibgp lab=VDD}
C {devices/lab_pin.sym} 200 -370 0 0 {name=vibgm lab=VDDBG}
C {devices/vsource.sym} 200 -600 0 0 {name=VIREP value=0 savecurrent=true}
C {devices/lab_pin.sym} 200 -630 0 0 {name=virepp lab=VDD}
C {devices/lab_pin.sym} 200 -570 0 0 {name=virepm lab=VDDR}
C {design/bandgap_core.sym} 500 -200 0 0 {name=XBG}
C {devices/lab_pin.sym} 570 -200 0 0 {name=bgout lab=VREF}
C {devices/lab_pin.sym} 430 -200 0 0 {name=bggdrv lab=GDRV}
C {devices/lab_pin.sym} 500 -270 0 0 {name=bgvdd lab=VDDBG}
C {devices/lab_pin.sym} 500 -130 0 0 {name=bgvss lab=0}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 300 -800 0 0 {name=XPOUT
L=2
W=8
nf=1
mult='m_out'
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 320 -770 0 0 {name=xpoutd lab=VOUTR}
C {devices/lab_pin.sym} 280 -800 0 0 {name=xpoutg lab=GDRVC}
C {devices/lab_pin.sym} 320 -830 0 0 {name=xpouts lab=VDDR}
C {devices/lab_pin.sym} 320 -800 0 0 {name=xpoutb lab=VDDR}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 600 -800 0 0 {name=XPAMP
L=2
W=8
nf=1
mult='m_ampbias'
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 620 -770 0 0 {name=xpampd lab=TAILX}
C {devices/lab_pin.sym} 580 -800 0 0 {name=xpampg lab=GDRVC}
C {devices/lab_pin.sym} 620 -830 0 0 {name=xpamps lab=VDDR}
C {devices/lab_pin.sym} 620 -800 0 0 {name=xpampb lab=VDDR}
C {devices/vsource.sym} 800 -800 0 0 {name=VTAIL value=0 savecurrent=true}
C {devices/lab_pin.sym} 800 -830 0 0 {name=vtailp lab=TAILX}
C {devices/lab_pin.sym} 800 -770 0 0 {name=vtailm lab=TAILR}
C {devices/vsource.sym} 1000 -800 0 0 {name=VAVDD value=0 savecurrent=true}
C {devices/lab_pin.sym} 1000 -830 0 0 {name=vavddp lab=VDDR}
C {devices/lab_pin.sym} 1000 -770 0 0 {name=vavddm lab=VDDA}
C {design/error_amp.sym} 900 -600 0 0 {name=XAMPR}
C {devices/lab_pin.sym} 850 -620 0 0 {name=ampp lab=VBC}
C {devices/lab_pin.sym} 850 -580 0 0 {name=ampn lab=VAN}
C {devices/lab_pin.sym} 950 -600 0 0 {name=ampo lab=GDRVA}
C {devices/lab_pin.sym} 890 -650 0 0 {name=ampt lab=TAILR}
C {devices/lab_pin.sym} 910 -650 0 0 {name=ampvdd lab=VDDA}
C {devices/lab_pin.sym} 900 -550 0 0 {name=ampvss lab=0}
C {devices/vsource.sym} 1200 -600 0 0 {name=VOSINJ value="0 ac 0"}
C {devices/lab_pin.sym} 1200 -630 0 0 {name=vosinjp lab=VAN}
C {devices/lab_pin.sym} 1200 -570 0 0 {name=vosinjm lab=VAC}
C {devices/vsource.sym} 1400 -600 0 0 {name=VINJ value="0 ac 1"}
C {devices/lab_pin.sym} 1400 -630 0 0 {name=vinjp lab=GDRVC}
C {devices/lab_pin.sym} 1400 -570 0 0 {name=vinjm lab=GDRVA}
C {sky130_fd_pr/res_high_po.sym} 300 -600 0 0 {name=XRA
W='r_w'
L='r_lseg*n_r2'
model=res_high_po
spiceprefix=X
mult=1}
C {devices/lab_pin.sym} 300 -630 0 0 {name=xrap lab=VOUTR}
C {devices/lab_pin.sym} 300 -570 0 0 {name=xram lab=VAC}
C {devices/lab_pin.sym} 280 -600 0 0 {name=xrab lab=0}
C {sky130_fd_pr/res_high_po.sym} 500 -600 0 0 {name=XRB
W='r_w'
L='r_lseg*n_r2'
model=res_high_po
spiceprefix=X
mult=1}
C {devices/lab_pin.sym} 500 -630 0 0 {name=xrbp lab=VOUTR}
C {devices/lab_pin.sym} 500 -570 0 0 {name=xrbm lab=VBC}
C {devices/lab_pin.sym} 480 -600 0 0 {name=xrbb lab=0}
C {sky130_fd_pr/pnp_05v5.sym} 300 -400 0 0 {name=XQ1R
model=pnp_05v5_W0p68L0p68
m='n_pnp_ctat'
spiceprefix=X}
C {devices/lab_pin.sym} 320 -370 0 0 {name=xq1rc lab=0}
C {devices/lab_pin.sym} 280 -400 0 0 {name=xq1rb lab=0}
C {devices/lab_pin.sym} 320 -430 0 0 {name=xq1re lab=VAC}
C {sky130_fd_pr/res_high_po.sym} 500 -400 0 0 {name=XR1R
W='r_w'
L='r_lseg*n_r1'
model=res_high_po
spiceprefix=X
mult=1}
C {devices/lab_pin.sym} 500 -430 0 0 {name=xr1rp lab=VBC}
C {devices/lab_pin.sym} 500 -370 0 0 {name=xr1rm lab=VBQR}
C {devices/lab_pin.sym} 480 -400 0 0 {name=xr1rb lab=0}
C {sky130_fd_pr/pnp_05v5.sym} 500 -200 0 0 {name=XQ2R
model=pnp_05v5_W3p40L3p40
m='n_pnp_ptat'
spiceprefix=X}
C {devices/lab_pin.sym} 520 -170 0 0 {name=xq2rc lab=0}
C {devices/lab_pin.sym} 480 -200 0 0 {name=xq2rb lab=0}
C {devices/lab_pin.sym} 520 -230 0 0 {name=xq2re lab=VBQR}
