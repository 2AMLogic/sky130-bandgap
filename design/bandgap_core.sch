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
* HOW THE RESISTOR LEGS ARE MODELLED (issue #99, DR-003) -- read this before
* the sizing numbers below. Each divider leg is drawn, and is now modelled,
* as N SEPARATELY-CONTACTED res_high_po unit instances in series, not as one
* device at the leg's total length. That is what layout/bin/
* gen_bandgap_routed.py's res_r2/res_trim/res_r1 blocks actually draw
* (bus_res_series contacts every internal unit boundary), and
* sim/res-array-head-resistance/ proved with real SPICE that a real device
* pays the PDK model card's per-INSTANCE rhead/fringe term once per
* instance: one 5 um unit measures 2003.84 ohm and one 1 um trim unit
* 704.53 ohm at tt/27 degC -- i.e. the R ~ 380 + 325*L unit model below,
* applied once PER UNIT, which is where the 380 ohm head really lands.
* R1/R2A/R2B below are therefore stated on design/res_high_po_series.sym
* (one UNIT-length symbol carrying the series count; see that symbol's
* header for the mult/m split), and every sim record taken from this
* schematic from now on measures the topology the layout builds. Before
* issue #99 this cell modelled one long device per leg -- one head per LEG
* rather than per unit -- so the drawn array really builds R1 19.4% and
* R2A/R2B 29.7% higher than this cell used to model, and K = R2/R1 8.67%
* higher (the deltas are unequal, so it is not a common scale factor) --
* enough to
* put VOUT(27 degC) outside the draft +/-1% window at every corner checked
* (spec/decision-records/DR-003-res-array-head-resistance-sizing.md).
*
* Sizing rationale (design/device-characterization-summary.md sections 1/4,
* record 20260801-041501-48ac24d, tt / 27 degC):
*   - Both PNP arrays are 8 units, so each unit carries ~0.65 uA at the ~5.2
*     uA branch current. That keeps ideality n <~ 1.1 over -40..125 degC on
*     the small unit (the summary caps the small unit at ~1 uA) and takes
*     sigma(dVBE) from 0.48 mV to ~0.17 mV via the model's 1/sqrt(mult) term.
*   - dVBE for this pair at that per-unit current is ~62.4 mV, so R1 has to
*     be ~11.8-12.0 kohm. On the chained array that is n_r1 = 6 unit
*     segments (6 x 2003.84 = 12,023.05 ohm, branch current 5.194 uA, -2.0%
*     of the 5.3 uA the PNP/amp/Iq characterizations were taken at). It was
*     7 segments while this cell modelled one device per leg (7 x 5 um at
*     R(L) = 380 + 325*L ~ 11.75 kohm); carried onto the real array those
*     same 7 instances draw 14,026.89 ohm, 19.4% high -- see issue #99.
*   - n_r2 = 42 (38 coarse 5 um units + 20 fine 1 um trim units per leg =
*     90,236.6 ohm, K = 7.5053) is issue #99's re-derivation against those
*     chained values: the integer pair that lands VOUT(27 degC) closest to
*     1.200 V (1.19934 V at tt/3.30 V) while holding the branch current on
*     the anchor above. Verified over the full 15-point PVT matrix in
*     sim/res-array-resize/. The 54 in the issue #46 discussion below is the
*     PRE-#99 value, sized against the single-device model; it is retained
*     verbatim because #46's floor finding (K alone cannot close the TC gap,
*     and the hot corners have no headroom for a K INCREASE) is a statement
*     about the loop, not about the resistor model, and survives the resize.
*   - n_r2 (issue #46 investigation -- historical, at n_r1=7/n_r2=54 on the
*     single-device model):
*     the original n_r2=54 (K = R2/R1 ~ 7.5, R2 ~ 88 kohm) was sized only to
*     hit VOUT(27 degC) ~ 1.20 V from the single-point dVBE(27 degC) figure
*     above -- it never used the *slope* of the measured dVBE, so it
*     under-compensates Q1's CTAT slope and the core measured
*     152.9..169.3 ppm/degC untrimmed TC (issue #11 record
*     20260803-115356-7759435, all 15 corners FAIL vs the draft's < 50).
*     device-characterization-summary.md section 1 shows *why*: at the
*     tt corner, VEB(Q1) (the small unit, 1 uA column) runs
*     0.8535749/0.7425389/0.5668493 V at -40/27/125 degC, a secant slope of
*     -1.776 mV/degC once interpolated to our ~0.66 uA per-unit current
*     (log-interpolated between the record's 316 nA and 1 uA columns); the
*     matching dVBE secant slope at that current is only +0.196 mV/degC
*     because ~18.1 mV of the 62.3 mV dVBE at 27 degC rides on Q1's
*     nf = 1.028 vs Q2's nf = 1.000 (section 1's decomposition table) -- a
*     fraction of a CTAT quantity, not true PTAT, so it under-delivers a
*     shortfall that grows with T (61.6/81.7 mV predicted by strict
*     T-proportionality vs 60.5/79.1 mV measured, at the record's 100 nA
*     column). Full first-order cancellation of the *average* slope over
*     -40..125 degC needs K = 1.776/0.196 ~ 9.0 (n_r2 ~ 65 at n_r1 = 7) --
*     EPISTEMIC STATUS (issue #55): the n_r2=65 figure below is an
*     uncommitted scratch run outside the sim/ harness (tt/27 degC/3.30 V
*     corner only) -- no testbench/record backs it, so treat it as a single
*     spot-check, not a corner-matrix claim, and re-measure via
*     sim/output-voltage-tc/ before relying on it. As measured: n_r2=65
*     gives VOUT(27 degC) = 1.2947 V
*     (+7.9 % vs 1.20 V) and still only 85.3 ppm/degC box TC (the residual
*     curvature in both VBE(T) and the sub-PTAT dVBE(T) isn't a straight
*     line, so even a perfectly slope-matched K doesn't zero the box
*     metric). That VOUT is far outside the "+/-1 % untrimmed" spec line
*     (1.188..1.212 V) that issue #11's testbench also checks, and
*     CLAUDE.md rules out relaxing the ratified spec to make TC pass.
*   - The accuracy-constrained ceiling is n_r2 = 55 -- the largest integer
*     segment count for which sim/output-voltage-tc/testbench/tb_vref_tc.sch
*     still measures VOUT(27 degC) inside the 1.188..1.212 V window at the
*     nominal corner (tt/27 degC/3.30 V measures 1.20836 V, from the
*     committed record 20260803-142220-b24b404; n_r2=56 already
*     measures 1.21699 V at that same corner -- EPISTEMIC STATUS (issue
*     #55): the n_r2=56 figure is an uncommitted scratch run outside the
*     harness, no testbench/record backs it, re-measure before relying on
*     it), over the 1.212 V ceiling. It raises K from ~7.50
*     to ~7.64 (R2 ~ 89.4..90 kohm) and cuts the box TC at the nominal
*     tt/27 degC/3.30 V point from 163.4 to 140.8 ppm/degC -- a real but
*     partial improvement, EXCEPT that a full 15-corner run at n_r2=55
*     (sim/output-voltage-tc/ record 20260803-142220-b24b404, kept as
*     append-only evidence of the REJECTED n_r2=55 candidate -- NOT the
*     shipped design; see sim/output-voltage-tc/README.md's record index,
*     issue #55) found that two corners (ff/2.97 V, fs/2.97 V) do not
*     merely fail the TC/accuracy limits -- ngspice's continuous -40..125
*     degC sweep loses the bandgap operating point somewhere in the
*     committed grid's (114, 125] degC gap, jumping to ~2.82 V (VREF
*     pinned near VDD, sanity-band FAIL, not a TC number); that range is
*     exactly what the committed 11 degC grid supports. EPISTEMIC STATUS
*     (issue #55): the "123 and 124 degC" localization and the n_r2=54
*     control both below come from a fine-resolution (1 degC step)
*     diagnostic sweep run as an uncommitted scratch deck outside the sim/
*     harness -- no testbench/record/log backs either number, so a reader
*     should not expect to find one, and should re-measure with a
*     committed fine-grid deck before treating "genuine bifurcation, not a
*     solver artifact" as more than a strong prior. As run: a
*     fine-resolution (1 degC step) diagnostic sweep indicated this is a
*     genuine bifurcation between 123 and 124 degC, not a coarse-grid solver
*     artifact -- and indicated it is introduced BY the resize: the same
*     diagnostic at n_r2=54 stayed smooth and well-behaved out to 140 degC
*     (10 degC past the qualified range) at the identical ff/2.97 V corner.
*     Trading a ~150 ppm/degC TC miss for a corner that stops regulating at
*     all above ~124 degC is a worse regression than the problem #46 set out
*     to fix, so **n_r2 stays at 54** -- the record above is kept as
*     append-only evidence of why the attempted resize was rejected, not as
*     the shipped design.
*   - Conclusion (issue #46's floor finding): on this device menu and this
*     error-amp/core loop, R2/R1 alone cannot close the TC gap. The
*     accuracy-safe ceiling (n_r2=55) already erodes hot-corner loop margin
*     at the fast-process/low-supply extreme badly enough to lose regulation
*     before 125 degC; the TC-cancelling K (~9.0) both breaches +/-1 %
*     accuracy by 7.9 % AND (untested, but starting from a worse margin
*     baseline than n_r2=55) would be expected to lose the operating point
*     at more corners, not fewer. Reaching < 50 ppm/degC untrimmed needs
*     either curvature correction/trim (#13) or attacking the ideality
*     mismatch at the source by growing n_pnp_ptat (raises the *true*
*     V_T*ln(N) term without adding CTAT-tainted gain or R2-driven offset
*     gain, at the cost of halving Q2's per-unit current and needing R1/R2
*     to be re-solved together) or widening the error amp's own headroom
*     margin (#9) so a larger K does not cost hot-corner regulation --
*     all out of scope here, flagged for follow-up.
*   - This is *untrimmed* (n_r2_trim=0) first-pass sizing for a nominal
*     operating point. The +/-1% spec claim over the full PVT matrix is
*     issue #11's job; the offset budget that may re-size the amp is #9.
*     #12's Monte Carlo mismatch analysis found the untrimmed +/-1% target
*     NOT met (yield collapses to <1% at 125 degC), so #13 adds the
*     n_r2_trim ladder-tap trim below -- see spec/decision-records/
*     DR-002-trim-network-scoping.md.
*
* Bias / startup: MPAMP mirrors the amplifier's tail current out of the same
* GDRV gate that supplies the core branches (self-biased -- no supply-
* referenced bias resistor, which would otherwise dominate the area and the
* quiescent current). The price is the usual degenerate all-zero operating
* point, which is exactly what issue #10 exists to break: GDRV is exposed on
* the symbol as the startup attachment node. No startup circuit here.
*
* The trim network (#13) is the n_r2_trim/r_lseg_trim length-tap addition on
* R2A/R2B above -- a metal-option choice, not an active device, so it adds
* no switch/decode circuitry to this cell. Deliberately NOT in this cell:
* startup circuit (#10), output load/buffer, and any corner/temperature/
* analysis statement (the corner runner injects those around the testbench
* that instantiates this).
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
VOUT = VBE(Q1) + (R2/R1) * dVBE(Q1,Q2); amplifier forces VA = VB. R2/R1 is
NOT n_r2/n_r1 -- every unit segment carries its own head resistance, so see
the CORE_PARAMS block for the real ratio.
PNP area ratio is built from paralleled fixed-geometry unit devices.
All resistors are integer multiples of one res_high_po unit segment, drawn
AND modelled as that many separately-contacted units in series (issue #99 /
DR-003) -- each R2 leg is a coarse block (R2AC/R2BC) plus the trim ladder's
fine block (R2AF/R2BF), joined at TRIMA/TRIMB.
R2A/R2B carry a downward-only ladder-tap length trim, n_r2_trim (issue #13,
metal option, code 0..-16); code 0 is untrimmed and matches #8/#11/#12
exactly. Positive codes are rejected -- see the CORE_PARAMS block below.
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
* res_high_po unit segment: W = r_w um, L = r_lseg um (R ~ 380 + 325*L ohm).
* That 380 ohm head is per DEVICE, and the routed array draws every unit as
* its own separately-contacted device -- so it is paid per unit segment, not
* once per leg. Measured (tt/27 degC, sim/res-array-resize/): 2003.84 ohm per
* r_lseg unit, 704.53 ohm per r_lseg_trim unit.
.param r_w=1
.param r_lseg=5
* Segment counts, in UNIT SEGMENTS of the routed array (issue #99 / DR-003).
* Each divider leg is n unit res_high_po instances IN SERIES, so its total
* resistance is n*(rhead + rbody(unit)), not one device drawn at n*r_lseg --
* the routed layout contacts every internal unit boundary and therefore pays
* the model card's per-instance rhead term n times (real-SPICE evidence in
* sim/res-array-head-resistance/, ratified by DR-003; this cell models it
* via design/res_high_po_series.sym). K = R2/R1 is therefore NOT
* (380 + 325*r_lseg*n_r2)/(380 + 325*r_lseg*n_r1); it is
*   K = (n_r2_coarse*u5 + n_r2_fine_used*u1) / (n_r1*u5)
* with u5 / u1 the measured per-unit values above.
* n_r1=6 / n_r2=42 is issue #99's re-derivation against THOSE values: the
* integer pair that lands VOUT(27 degC) closest to 1.200 V (1.19934 V at
* tt/3.30 V; R1 = 12,023.05 ohm, R2A = R2B = 90,236.6 ohm, K = 7.5053) while
* holding the branch current at 5.194 uA, within 2.0% of the 5.3 uA
* operating point every other block in this design (PNP ideality #4/#35, amp
* offset budget #9, quiescent current #15) was characterized at. See the
* header's Sizing rationale and sim/res-array-resize/ for the derivation
* table and the full 15-point PVT verification.
* The previous n_r1=7 / n_r2=54 pair was sized against a SINGLE-device model
* of each leg; carried onto the real array it reads K = 8.1474 (+8.7%) and
* VOUT(27 degC) ~ 1.233 V, outside the draft +/-1% window at every corner
* checked, with hot-corner regulation collapse at ff/2.97 V and fs/2.97 V
* (DR-003). It is not restored by any change here.
.param n_r1=6
.param n_r2=42
* Routed-array decomposition of an R2 leg (layout/bin/gen_bandgap_routed.py's
* res_r2 + res_trim blocks, issue #91's coarse/fine split): the leg is
* n_r2_coarse units of r_lseg um followed by the DR-002 trim ladder's
* n_r2_fine units of r_lseg_trim um, and trim code n_r2_trim (<= 0) taps out
* |n_r2_trim| of the fine units. Total drawn length is therefore still
* r_lseg*n_r2 + r_lseg_trim*n_r2_trim, exactly as before; what changed is
* that the instance COUNT is now modelled, not just the length. n_r2_fine
* stays at the 20 units the layout already draws, so DR-002's certified
* 0..-16 code range keeps the same 4 units of drawn margin. The two derived
* counts are declared at the END of this block, after the trim params they
* depend on -- SPICE resolves .param lines in textual order.
.param n_r2_fine=20
* PMOS mirror multiplicities (unit device W=8u L=2u)
.param m_out=2
.param m_ampbias=2
* ---- Trim network (issue #13), DOWNWARD ONLY -- see DR-002 ----
* Ladder-tap length added to R2A/R2B equally (metal option, no switches).
* n_r2_trim: valid range 0..-16 only. r_lseg_trim: 1 um/code. Each code taps
* out one separately-contacted fine unit per leg, i.e. 704.53 ohm (not the
* 325 ohm the single-device model implied), so the step is ~3.7 mV/code and
* the certified 0..-16 range spans ~58 mV -- issue #99 re-ran DR-002's own
* corner set against the resized baseline and found the range still covers
* the 15.62 mV worst-case 3-sigma spread it was sized for, with ~3.7x margin
* instead of ~1.7x. See sim/res-array-resize/ Phase 3 and DR-003's closure.
* Positive codes are REJECTED: this is the same R2/R1 ratio issue #46 found
* causes ff/2.97V, fs/2.97V hot-corner (>~123C) operating-point collapse at
* even a +5 um increase (n_r2=55). sim/trim-range-monotonicity/ reconfirms
* it for trim and finds codes +1/+2 ALSO collapse (VOUT -> ~2.8V) while +3/
* +4 happen not to -- non-monotonic-in-code, i.e. no positive code is a
* certified-safe point, not a safe zone at +3/+4. Only downward (R2
* decrease) moves away from that edge; confirmed monotonic, collapse-free
* to -16 across corners. See DR-002 and the sim record for the full case.
.param n_r2_trim=0
.param r_lseg_trim=1
* Derived unit counts (must follow n_r2_trim / r_lseg_trim above -- SPICE
* resolves .param in textual order). n_r2_coarse is the res_r2 block's unit
* count per leg; n_r2_fine_used is how many of the res_trim ladder's fine
* units are still in circuit at the selected trim code.
.param n_r2_coarse='n_r2-n_r2_fine*r_lseg_trim/r_lseg'
.param n_r2_fine_used='n_r2_fine+n_r2_trim'
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
C {design/res_high_po_series.sym} 300 -660 0 0 {name=R2AC
W='r_w'
L='r_lseg'
n_series='n_r2_coarse'
m_series='1/n_r2_coarse'
model=res_high_po
spiceprefix=X}
C {devices/lab_pin.sym} 300 -690 0 0 {name=r2acp lab=VOUT}
C {devices/lab_pin.sym} 300 -630 0 0 {name=r2acm lab=TRIMA}
C {devices/lab_pin.sym} 280 -660 0 0 {name=r2acb lab=VSS}
C {design/res_high_po_series.sym} 300 -600 0 0 {name=R2AF
W='r_w'
L='r_lseg_trim'
n_series='n_r2_fine_used'
m_series='1/n_r2_fine_used'
model=res_high_po
spiceprefix=X}
C {devices/lab_pin.sym} 300 -570 0 0 {name=r2afm lab=VA}
C {devices/lab_pin.sym} 280 -600 0 0 {name=r2afb lab=VSS}
C {design/res_high_po_series.sym} 500 -660 0 0 {name=R2BC
W='r_w'
L='r_lseg'
n_series='n_r2_coarse'
m_series='1/n_r2_coarse'
model=res_high_po
spiceprefix=X}
C {devices/lab_pin.sym} 500 -690 0 0 {name=r2bcp lab=VOUT}
C {devices/lab_pin.sym} 500 -630 0 0 {name=r2bcm lab=TRIMB}
C {devices/lab_pin.sym} 480 -660 0 0 {name=r2bcb lab=VSS}
C {design/res_high_po_series.sym} 500 -600 0 0 {name=R2BF
W='r_w'
L='r_lseg_trim'
n_series='n_r2_fine_used'
m_series='1/n_r2_fine_used'
model=res_high_po
spiceprefix=X}
C {devices/lab_pin.sym} 500 -570 0 0 {name=r2bfm lab=VB}
C {devices/lab_pin.sym} 480 -600 0 0 {name=r2bfb lab=VSS}
C {sky130_fd_pr/pnp_05v5.sym} 300 -400 0 0 {name=Q1
model=pnp_05v5_W0p68L0p68
m='n_pnp_ctat'
spiceprefix=X}
C {devices/lab_pin.sym} 320 -370 0 0 {name=q1c lab=VSS}
C {devices/lab_pin.sym} 280 -400 0 0 {name=q1b lab=VSS}
C {devices/lab_pin.sym} 320 -430 0 0 {name=q1e lab=VA}
C {design/res_high_po_series.sym} 500 -400 0 0 {name=R1
W='r_w'
L='r_lseg'
n_series='n_r1'
m_series='1/n_r1'
model=res_high_po
spiceprefix=X}
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
