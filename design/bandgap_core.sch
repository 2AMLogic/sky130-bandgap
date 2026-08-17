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
*   NOTE (issue #99, RESOLVED -- read before the n_r2 discussion below): the
*   n_r2 rationale in this section is the ORIGINAL issue #46 investigation
*   against the single-res_high_po-device-per-leg model, which set n_r2=54.
*   n_r2 has since been RESIZED to 50 against the ROUTED LAYOUT's real
*   chained-array topology -- issue #98/DR-003 established that chained
*   topology (not the single-device model) is what the fabricated part
*   actually experiences. See the CORE_PARAMS "RESIZE STATUS (issue #99)"
*   block below for the current sizing, the reason, and its full PVT + trim
*   re-verification (sim/res-array-resize/). The #46 material below is
*   retained unchanged as the single-device-model rationale it always was;
*   every "n_r2 stays 54" statement in it is a correct statement about that
*   single-device investigation, now superseded by the routed-topology resize.
*   - Both PNP arrays are 8 units, so each unit carries ~0.66 uA at the ~5.3
*     uA branch current. That keeps ideality n <~ 1.1 over -40..125 degC on
*     the small unit (the summary caps the small unit at ~1 uA) and takes
*     sigma(dVBE) from 0.48 mV to ~0.17 mV via the model's 1/sqrt(mult) term.
*   - dVBE for this pair at that per-unit current is ~62.3 mV, so
*     R1 = 62.3 mV / 5.3 uA ~ 11.8 kohm = 7 unit segments (5 um each, W=1 um:
*     R(L) = 380 + 325*L ohm).
*   - n_r2 (issue #46 investigation -- n_r2 stays 54, see conclusion below):
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
VOUT = VBE(Q1) + K * dVBE(Q1,Q2), K = R2/R1; amplifier forces VA = VB.
K is NOT n_r2/n_r1: each leg chains a different NUMBER of separately-
contacted unit instances and pays the model card's head/end term once per
instance (DR-003). The XR1/XR2A/XR2B devices below are the body half of an
exact lumped equivalent of that chain -- see CHAINED-ARRAY MODEL in the
CORE_PARAMS block and the RES_HEAD_MODEL block that completes it.
PNP area ratio is built from paralleled fixed-geometry unit devices.
All resistors are integer multiples of one res_high_po unit segment.
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
* res_high_po unit segment: W = r_w um, L = r_lseg um (R ~ 380 + 325*L ohm)
.param r_w=1
.param r_lseg=5
* segment counts. K = R2/R1. n_r2 history: 54 (issue #46, single-device
* model) -> 50 (issue #99/DR-003, chained topology, single-device SCHEMATIC
* left un-modelled) -> 51 (issue #178, chained topology modelled HERE and
* re-centred against DR-005's ratified accuracy row). See CHAINED-ARRAY
* MODEL and SIZING (issue #178) below.
* HISTORY (issue #99 / DR-003, RESOLVED): n_r1/n_r2 are sized against the
* ROUTED LAYOUT's real chained-array topology -- the ground truth the
* fabricated part experiences. Issue #98/DR-003
* (sim/res-array-head-resistance/) established that the routed layout draws
* each leg as N separately-contacted unit instances in series
* (layout/bin/gen_bandgap_routed.py's bus_res_series), paying real per-instance
* head resistance: at the old n_r2=54 that made the REAL part's K=R2/R1 read
* 8.1474 vs the single-device model's 7.4973, pushing VOUT(27 degC) to
* ~1.233 V (outside the draft +/-1% window 1.188..1.212 V) at all 5
* (process,supply) corners and collapsing regulation at ff/2.97 V and
* fs/2.97 V. Resizing n_r2 54 -> 50 (n_r1 left at 7 so branch current -- and
* therefore hot-corner headroom -- is not raised while K is corrected) brought
* the real chained topology's K back to 7.576. Full PVT + trim
* re-verification of that step: sim/res-array-resize/records/ (issue #99).
* ---- CHAINED-ARRAY MODEL (issue #178) ----
* DR-003 deliberately left the SCHEMATIC modelling each leg as ONE
* res_high_po device, so simulating this cell as-drawn read VOUT(27 degC)
* ~1.165 V -- ~36 mV below what the routed part builds. Issue #178 closes
* that gap HERE rather than sizing around it: XR1/XR2A/XR2B are now the
* *body* devices of an EXACT lumped equivalent of the routed N-instance
* chain, completed by the per-leg replica + gain elements in the
* RES_HEAD_MODEL block below. The identity used (exact, not an
* approximation) follows from the PDK model card
* (models_resistors.spice: rhead has a hardcoded l=1 independent of the
* caller's drawn length; rbody is linear in leff = l + 0.247):
*     R_chain(N units, total drawn length Ltot)
*         = N*rhead + rbody(Ltot + 0.247*N)
*         = R_res_high_po(L = Ltot - (N-1)*r_ov_seg)      <- the body device
*           + (N-1) * R_res_high_po(L = r_ov_seg)          <- the replica
* for ANY r_ov_seg, because both terms are affine in the drawn length. The
* (N-1) copies are realized as ONE replica instance whose drop is multiplied
* by (N-1) with an ideal VCVS, which is exact for the nominal value at every
* temperature and process corner (rhead and rbody are re-evaluated by the
* model card, not frozen) -- verified against an explicit 143-instance chain
* of the same decomposition: identical to 7 significant figures on
* vref_27 / vref_min / vref_max / tc_ppm over the whole -40..125 degC sweep.
* The replica carries mult='n_*_ov' so the PDK's own AGAUSS mismatch term
* (sigma ~ 1/sqrt(w*mult)) reproduces the 1/sqrt(N) averaging of N
* independent series instances; `m` is deliberately pinned to 1 on those
* lines (the stock res_high_po symbol ties m to mult, which would parallel
* the subcircuit and divide the value -- that is why the replica/VCVS pair
* lives in a code block instead of as drawn symbol instances).
* ---- SIZING (issue #178) ----
* With the chain modelled, n_r2 was re-derived against DR-005's ratified
* untrimmed accuracy row (1.20 V +/-2% over -40..125 degC => 1.176..1.224 V),
* not against the superseded draft +/-1% window:
*   n_r2=50 (K = 7.630): vref_min 1.1744..1.1747 -- ~1.3 mV BELOW the 1.176 V
*     floor at every corner. FAIL.
*   n_r2=51 (K = 7.773): vref 1.18603..1.21780 at all 15 (process, supply)
*     points -- inside the window with 10.0 mV bottom / 6.2 mV top margin,
*     and box TC 142.4..159.0 ppm/degC (binding corner fs). ADOPTED.
*   n_r2=52 (K = 7.917): vref_max 1.22394..1.22507 -- over the 1.224 V
*     ceiling at 6 of 15 points. FAIL.
* n_r1 is held at 7 for the same reason issue #99 held it: R1 sets the branch
* current, and raising it raises the hot-corner headroom demand that the
* ff/2.97 V and fs/2.97 V regulation collapse depends on. No collapse is seen
* at n_r2=51 or 52 at those corners with the chained model.
* The K figures above are the routed chain's own values, computed from the
* per-instance terms DR-003 measured and klt extract independently reports
* (head+end 379.705 ohm/instance, body 324.827 ohm/um):
*   R1  = 7 * (379.705 + 324.827*5)                       = 14.027 kohm
*   R2  = (n_r2-2) * (379.705 + 324.827*5)
*         + 20 * (379.705 + 324.827*0.5)                  = 109.03 kohm at 51
* i.e. K = 7.773 at n_r2=51 -- NOT the textbook n_r2/n_r1 = 7.286, and NOT
* the single-device model's 7.087. The residual TC (142-159 ppm/degC, still
* far above DR-005's < 50 ppm/degC row) is issue #46's device-level floor,
* not a ratio error: design/device-characterization-summary.md section 1
* measures Q1's nf = 1.028 vs Q2's nf = 1.000, so ~18.1 mV of the 62.3 mV
* dVBE at 27 degC is a fraction of a CTAT quantity rather than true PTAT and
* its shortfall grows with temperature. See sim/output-voltage-tc/records/
* for the graded evidence and issue #179 for the spec-side routing.
.param n_r1=7
.param n_r2=51
* PMOS mirror multiplicities (unit device W=8u L=2u)
.param m_out=2
.param m_ampbias=2
* ---- Trim network (issue #13), DOWNWARD ONLY -- see DR-002 ----
* Ladder-tap length added to R2A/R2B equally (metal option, no switches).
* n_r2_trim: valid range 0..-16 only. r_lseg_trim: 1 um/code (~1.7 mV/code)
* in DR-002's original SINGLE-DEVICE model. Positive codes are REJECTED:
* this is the same R2/R1 ratio issue #46 found causes ff/2.97V, fs/2.97V
* hot-corner (>~123C) operating-point collapse at even a +5 um increase
* (n_r2=55). sim/trim-range-monotonicity/ reconfirms it for trim and finds
* codes +1/+2 ALSO collapse (VOUT -> ~2.8V) while +3/+4 happen not to --
* non-monotonic-in-code, i.e. no positive code is a certified-safe point,
* not a safe zone at +3/+4. Only downward (R2 decrease) moves away from
* that edge; confirmed monotonic, collapse-free to -16 across corners. See
* DR-002 and the sim record for the full case.
* LSB REVISION (issue #106, DR-002 revision): the routed layout's fine trim
* chain does NOT draw one length-tapped device -- it chains N separately-
* contacted res_high_po unit instances (layout/bin/gen_bandgap_routed.py's
* bus_res_series), each paying a real per-instance head/fringe resistance
* term this schematic's single-device XR2A/XR2B lines do not model (DR-003,
* sim/res-array-head-resistance/). Re-deriving DR-002's <=3.000 mV/code LSB
* comfort bound against that REAL chained topology at the adopted
* n_r1=7/n_r2=50 sizing (sim/trim-lsb-chained/) found the shipped
* r_lseg_trim=1 per-code step reads 3.12-3.15 mV/code across all 5 corners
* -- a real, measured violation of the comfort bound (smaller than an
* earlier, now-superseded estimate against an abandoned n_r1=6/n_r2=42
* sizing, but still a violation). Halving the fine unit's drawn length to
* 0.5 um fixes it: the per-instance head-resistance term (~379.7 ohm, the
* DOMINANT piece of the per-code step) is a PDK-model-card constant
* independent of the unit's drawn length, so only the smaller `rbody`
* fringe term shrinks -- re-verified at r_lseg_trim=0.5 to read
* 2.40-2.42 mV/code, PASS at all 5 corners, with the same certified 0..-16
* code range and downward span still clearing DR-002's 1.5x-of-3sigma
* coverage target. See sim/trim-lsb-chained/records/ for the full
* re-derivation. NEXT INCREMENT (not done here, per one-lever-per-
* increment): layout/bin/gen_bandgap_routed.py's
* R_LSEG_TRIM_UM/SCH_R_LSEG_TRIM_UM (currently still transcribing 1 um)
* must be re-transcribed to 0.5 um and the routed cell re-verified through
* klayout DRC/LVS -- klayout's extraction backend is not available in this
* run environment, so that is a follow-up issue, the same split issue #99
* used for #107/#108.
.param n_r2_trim=0
.param r_lseg_trim=0.5
* ---- Routed chained-array decomposition (issue #178) ----
* Transcribed from layout/bin/gen_bandgap_routed.py's N_R1 / N_R2_COARSE /
* N_R2_TRIM_UNITS: each leg is drawn as separately-contacted unit instances
* in series, so the instance COUNT (not just the total drawn length) is an
* electrical parameter -- every instance pays the model card's rhead term.
*   R1        : n_r1 coarse units of r_lseg um.
*   R2A/R2B   : n_r2_coarse coarse units of r_lseg um, plus the fixed
*               n_r2_fine-unit fine ladder of r_lseg_trim um each, of which
*               (n_r2_fine + n_r2_trim) are in circuit at a DOWNWARD-only
*               trim code (code 0 = all of them = the untrimmed leg).
* n_r2_coarse is derived, not transcribed twice: the fine ladder's drawn
* length is held inside the specified r_lseg*n_r2 leg, which is exactly the
* constraint gen_bandgap_routed.py's R2_LEG_SPEC_UM assertion enforces.
.param n_r2_fine=20
.param n_r2_coarse='n_r2-r_lseg_trim*n_r2_fine/r_lseg'
.param n_r2_inst='n_r2_coarse+n_r2_fine+n_r2_trim'
* Replica multiplicities: (N-1) per leg -- see CHAINED-ARRAY MODEL above.
.param n_r2_ov='n_r2_inst-1'
.param n_r1_ov='n_r1-1'
* Replica unit drawn length. The lumped identity is exact for ANY value;
* 0.5 um is chosen only so the body devices' remaining length stays well
* positive (R2A/R2B body = 221.0 um, R1 body = 32.0 um at the shipped
* sizing) and so the replica is a length the layout actually draws.
.param r_ov_seg=0.5
"}
C {devices/code_shown.sym} 700 -1250 0 0 {name=RES_HEAD_MODEL only_toplevel=false value="
* ---- Per-instance head-resistance replicas (issue #178) ----
* These three (replica, VCVS) pairs complete the EXACT lumped equivalent of
* the routed layout's N-instance series chains; the drawn XR1/XR2A/XR2B
* symbols carry only the body length. See the CORE_PARAMS block's
* CHAINED-ARRAY MODEL section for the identity, its exactness proof and the
* explicit-chain cross-check.
* Written as SPICE text rather than drawn symbols for one concrete reason:
* the stock res_high_po symbol emits 'mult=@mult m=@mult', and an X-line's
* `m` PARALLELS the subcircuit -- which would divide the replica's value by
* N-1 instead of leaving it alone. These lines set mult (mismatch sigma,
* 1/sqrt(w*mult), reproducing N-1 independent instances) while pinning m=1
* (nominal value untouched). The VCVS then multiplies the replica's own
* drop by (N-1), so the leg's total series resistance is exactly
* (N-1) * R_unit(r_ov_seg) + R_body -- at every temperature and corner,
* because the replica is a real model-card evaluation, not a frozen number.
XR2A_HD VA R2A_HD1 VSS sky130_fd_pr__res_high_po W='r_w' L='r_ov_seg' mult='n_r2_ov' m=1
ER2A_HD R2A_HD1 R2A_HD2 VA R2A_HD1 'n_r2_ov-1'
XR2B_HD VB R2B_HD1 VSS sky130_fd_pr__res_high_po W='r_w' L='r_ov_seg' mult='n_r2_ov' m=1
ER2B_HD R2B_HD1 R2B_HD2 VB R2B_HD1 'n_r2_ov-1'
XR1_HD VBQ R1_HD1 VSS sky130_fd_pr__res_high_po W='r_w' L='r_ov_seg' mult='n_r1_ov' m=1
ER1_HD R1_HD1 R1_HD2 VBQ R1_HD1 'n_r1_ov-1'
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
L='r_lseg*n_r2+r_lseg_trim*n_r2_trim-n_r2_ov*r_ov_seg'
model=res_high_po
spiceprefix=X
mult=1}
C {devices/lab_pin.sym} 300 -630 0 0 {name=r2ap lab=VOUT}
C {devices/lab_pin.sym} 300 -570 0 0 {name=r2am lab=R2A_HD2}
C {devices/lab_pin.sym} 280 -600 0 0 {name=r2ab lab=VSS}
C {sky130_fd_pr/res_high_po.sym} 500 -600 0 0 {name=R2B
W='r_w'
L='r_lseg*n_r2+r_lseg_trim*n_r2_trim-n_r2_ov*r_ov_seg'
model=res_high_po
spiceprefix=X
mult=1}
C {devices/lab_pin.sym} 500 -630 0 0 {name=r2bp lab=VOUT}
C {devices/lab_pin.sym} 500 -570 0 0 {name=r2bm lab=R2B_HD2}
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
L='r_lseg*n_r1-n_r1_ov*r_ov_seg'
model=res_high_po
spiceprefix=X
mult=1}
C {devices/lab_pin.sym} 500 -430 0 0 {name=r1p lab=VB}
C {devices/lab_pin.sym} 500 -370 0 0 {name=r1m lab=R1_HD2}
C {devices/lab_pin.sym} 480 -400 0 0 {name=r1b lab=VSS}
C {sky130_fd_pr/pnp_05v5.sym} 500 -200 0 0 {name=Q2
model=pnp_05v5_W3p40L3p40
m='n_pnp_ptat'
spiceprefix=X}
C {devices/lab_pin.sym} 520 -170 0 0 {name=q2c lab=VSS}
C {devices/lab_pin.sym} 480 -200 0 0 {name=q2b lab=VSS}
C {devices/lab_pin.sym} 520 -230 0 0 {name=q2e lab=VBQ}
