v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap startup injector -- schematic (issue #10).
*
* Breaks the degenerate zero-current state of the Kuijk core in
* bandgap_core.sch. The core is *not* modified: this cell bolts onto the
* GDRV node the core symbol already exposes (the PMOS mirror gate that the
* error amplifier drives) and senses the core's own output on VSENSE.
*
*        VDD (bulk of both chain PMOS -- one shared nwell)
*
*   GDRV -+--------------+-----------------+
*         |              |                 |
*       MPC1 (diode)   MNI  W=10 L=0.5   (to core mirror gate)
*         |              |
*        NC1           VSS
*         |
*       MPC2 (diode)          NG = MNI gate
*         |
*        NG ----------+
*                     |
*                   MNS   W=48 L=0.5, gate = VSENSE (the core's VOUT)
*                     |
*                    NE
*                     |
*                    QS    PNP, base = collector = VSS
*                     |
*                    VSS
*
* How it works
* ------------
* MPC1/MPC2 are a two-high diode-connected PMOS reference *fed from GDRV*,
* not from VDD. That choice is the heart of the cell:
*
*   - degenerate state, GDRV = VDD: each device sees VDD/2 = 1.49..1.82 V,
*     comfortably above |Vth_p| at every corner, so the reference is in
*     strong inversion and holds NG up near GDRV. MNI then sees a full
*     Vgs ~ VDD and pulls GDRV down hard (hundreds of uA of capability --
*     the core's mirror gate is a ~200 fF node, so this is a fast eviction).
*   - running, GDRV = VDD - |Vgs| of the core mirror: each device sees only
*     0.80..1.26 V, which at the cold corners is *below* |Vth_p|, so the
*     reference collapses by orders of magnitude exactly when it should.
*
* Feeding the reference from GDRV rather than VDD is what makes the standing
* current small without an always-on bias branch: the same node the cell
* drives is also the node that switches the reference off.
*
* MNS + QS set the release threshold. A bare NMOS gated by VSENSE would
* release at ~Vth_n minus the subthreshold slack, i.e. ~0.5 V, and at -40 degC
* the core is not self-sustaining until VOUT reaches ~0.70 V (below that the
* PNPs carry no current at all, because VOUT has not yet reached a cold VBE).
* Releasing at 0.5 V therefore strands the loop in a picoamp dead zone -- this
* was measured, not assumed; see sim/startup-stability/.
*
* Stacking the diode-connected PNP QS under MNS references the threshold to a
* VBE instead of to a threshold voltage alone. VBE falls ~1.8 mV/degC, which
* is the same direction and roughly the same slope as the core's own
* self-sustaining point, so the release tracks the thing it has to stay above:
*
*   corner            core self-sustains   release   core running (VOUT)
*   ss/-40/2.97 V     VOUT >~ 0.70 V       ~0.9 V    1.207 V
*   tt/27/3.30 V      VOUT >~ 0.55 V       ~0.7 V    1.199 V
*   ff/125/3.63 V     VOUT >~ 0.30 V       ~0.6 V    1.174 V
*
* MNS is deliberately large (W=48 L=0.5) and QS is 8 unit PNPs: both push the
* threshold *down* within that window, trading disengage quality against
* traverse margin. That trade is the cell's one real design knob and the
* numbers on both sides of it are recorded per corner in
* sim/startup-stability/, not asserted here.
*
* Known limitation (recorded, not hidden): at the hot/high-supply corners the
* reference is still in strong inversion once the core is running, so the
* cell keeps drawing tens of nA out of GDRV. GDRV is a high-impedance
* amplifier output, so that residual shows up on the reference. The largest
* *measured* output shift in the record is 3.2 mV at tt/125 degC/3.63 V
* (sim/startup-stability/records/20260803-124600-e599e30.md). The reasoning
* above predicts ff/125 degC/3.63 V should be worse still, but that corner
* has NOT been measured -- it is the one point that timed out in that record,
* so no number exists for it; the re-run is tracked by issue #48. Until then
* 3.2 mV is the number to carry (issue #11 subtracts the measured worst case,
* not a prediction). Removing the residual needs a reference that is not a MOS
* threshold (a replica-current comparison), which costs a standing bias branch
* of its own -- see the record and the follow-up issue rather than a claim here.
*
* Deliberately NOT in this cell: any capacitor or one-shot. Disengagement is
* *static*, so a supply ramp of any rate is covered by the same argument, and
* the DC sweep in sim/startup-stability/ -- which is the arbitrarily-slow-ramp
* limit -- is a stronger statement than any finite ramp can make.
*
* W/L stay literal because xschem's MOS symbol template derives ad/as/pd/ps/
* nrd/nrs from a *numeric* @W via expr(); multiplicity is the .param-driven
* axis (same convention as design/error_amp.sch and design/bandgap_core.sch).
*
* Connectivity is by net label (lab_pin on every device pin), no wires --
* the same convention the sim/ testbenches use.
}
G {}
K {}
V {}
S {}
E {}
T {startup_injector -- degenerate-state breaker for bandgap_core (issue #10)
A two-high diode-connected PMOS reference fed FROM GDRV holds MNI's gate high
while the core is dead and collapses once the core pulls GDRV down; MNS over a
diode-connected PNP sets a VBE-referenced release threshold that tracks the
core's own self-sustaining point over temperature.
No always-on bias branch from VDD anywhere in this cell.
Connectivity is by net label; no wires.} 100 -820 0 0 0.4 0.4 {}
C {devices/code_shown.sym} 100 -1080 0 0 {name=SU_PARAMS only_toplevel=false value="
* ---- startup injector parameters (issue #10) ----
* m_ref  : units of the (W=1 L=20) diode-connected reference PMOS. Raising it
*          raises BOTH the release threshold and the residual current the cell
*          draws from GDRV once disengaged -- the two are the same current.
* m_sense: units of the (W=48 L=0.5) sense NMOS. Raising it lowers the release
*          threshold (better disengage, less traverse margin).
* m_pnp  : unit PNPs in the threshold reference. Raising it lowers VBE at the
*          sense current, i.e. lowers the release threshold.
* m_inj  : units of the (W=10 L=0.5) injector NMOS. Scales the eviction
*          current and the disengaged residual in the same proportion.
.param m_ref=1
.param m_sense=1
.param m_pnp=8
.param m_inj=1
"}
C {devices/iopin.sym} 100 -560 0 0 {name=p_gdrv lab=GDRV}
C {devices/ipin.sym} 100 -520 0 0 {name=p_vsense lab=VSENSE}
C {devices/iopin.sym} 100 -480 0 0 {name=p_vdd lab=VDD}
C {devices/iopin.sym} 100 -440 0 0 {name=p_vss lab=VSS}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 400 -700 0 0 {name=MPC1
L=20
W=1
nf=1
mult='m_ref'
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 420 -670 0 0 {name=mpc1d lab=NC1}
C {devices/lab_pin.sym} 380 -700 0 0 {name=mpc1g lab=NC1}
C {devices/lab_pin.sym} 420 -730 0 0 {name=mpc1s lab=GDRV}
C {devices/lab_pin.sym} 420 -700 0 0 {name=mpc1b lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 400 -560 0 0 {name=MPC2
L=20
W=1
nf=1
mult='m_ref'
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 420 -530 0 0 {name=mpc2d lab=NG}
C {devices/lab_pin.sym} 380 -560 0 0 {name=mpc2g lab=NG}
C {devices/lab_pin.sym} 420 -590 0 0 {name=mpc2s lab=NC1}
C {devices/lab_pin.sym} 420 -560 0 0 {name=mpc2b lab=VDD}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 400 -400 0 0 {name=MNS
L=0.5
W=48
nf=1
mult='m_sense'
model=nfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 420 -430 0 0 {name=mnsd lab=NG}
C {devices/lab_pin.sym} 380 -400 0 0 {name=mnsg lab=VSENSE}
C {devices/lab_pin.sym} 420 -370 0 0 {name=mnss lab=NE}
C {devices/lab_pin.sym} 420 -400 0 0 {name=mnsb lab=VSS}
C {sky130_fd_pr/pnp_05v5.sym} 400 -220 0 0 {name=QS
model=pnp_05v5_W0p68L0p68
m='m_pnp'
spiceprefix=X}
C {devices/lab_pin.sym} 420 -190 0 0 {name=qsc lab=VSS}
C {devices/lab_pin.sym} 380 -220 0 0 {name=qsb lab=VSS}
C {devices/lab_pin.sym} 420 -250 0 0 {name=qse lab=NE}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 800 -600 0 0 {name=MNI
L=0.5
W=10
nf=1
mult='m_inj'
model=nfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 820 -630 0 0 {name=mnid lab=GDRV}
C {devices/lab_pin.sym} 780 -600 0 0 {name=mnig lab=NG}
C {devices/lab_pin.sym} 820 -570 0 0 {name=mnis lab=VSS}
C {devices/lab_pin.sym} 820 -600 0 0 {name=mnib lab=VSS}
