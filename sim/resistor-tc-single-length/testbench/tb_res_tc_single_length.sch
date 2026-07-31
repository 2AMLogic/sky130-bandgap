v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap single-length resistor-TC testbench (issue #25).
*
* NOT a bandgap -- device characterization only. Follow-up to
* sim/resistor-flavor-characterization/ (issue #4), whose two-length
* subtraction method returned an essentially flat TC for
* sky130_fd_pr__res_xhigh_po, disagreeing with the PDK model card's
* static tc1. This testbench measures TC at a SINGLE fixed length so no
* subtraction is involved, and carries three companion legs that
* discriminate between the candidate explanations:
*
*   xh_l50_5u    -- PRIMARY DUT. res_xhigh_po W=1um L=50um at 5uA
*                   (~106k, ~0.53V drop): a representative bias-setting
*                   resistor for this block -- 5uA sits inside the
*                   2-20uA per-branch range that the <50uA Iq budget
*                   implies (design/device-characterization-summary.md
*                   sec.3), and ~0.5V is the realistic drop for such a leg
*                   off a 3.3V supply. Current density 5uA per um of width.
*   xh_l50_0p5u  -- SAME geometry, 10x lower bias (~53mV drop). Isolates
*                   any voltage-coefficient contribution to the measured
*                   TC: geometry identical, only the voltco argument moves.
*   xh_l5_5u     -- SAME current density (5uA/um), 10x shorter (~10.6k,
*                   ~53mV drop). Isolates the model's length-dependent
*                   (Efac ~ 1/leff) voltco term, and -- because the fixed
*                   head/contact resistance is 10x a larger fraction of
*                   the total -- separates head TC from body TC.
*   high_l50_5u  -- POSITIVE CONTROL. res_high_po at the identical length
*                   and bias. Its TC is known to simulate correctly
*                   (cross-validated against its model card in issue #4),
*                   so a flat xh leg next to a moving high leg cannot be
*                   blamed on the .temp knob failing to reach the models.
*
* The three ideal resistors at the right (raw-SPICE block) are the
* simulator-mechanism probe. All three carry the SAME .model card
* (tc1=-1.47e-3 tc2=2.7e-6 tnom=25); they differ only in how the
* resistance is written:
*   TC_LIT   r=1000                              (literal)
*   TC_EXPR  r='1000*1.0'                        (constant expression)
*   TC_BEH   r='1000*(1+1e-12*abs(v(TC_BEH,0)))' (voltage-dependent expr)
* If TC_LIT and TC_EXPR move with .temp while TC_BEH does not, ngspice
* drops .model temperature scaling for voltage-controlled behavioural
* resistors -- which is exactly the element type sky130_fd_pr__res_xhigh_po
* uses for its rbody. That is a machine-checked statement of the
* mechanism at every PVT point, not a side note.
*
* Body/substrate pin (b) tied to ground on every DUT, matching the
* sibling experiment so the two records stay comparable.
*
* Deliberately NOT in this schematic (the corner runner injects them):
*   - the .lib model corner include, .temp, the .control block
}
G {}
K {}
V {}
S {}
E {}
T {single-length resistor TC characterization -- not the bandgap
xh = sky130_fd_pr__res_xhigh_po, high = sky130_fd_pr__res_high_po
one length per leg: TC read directly from R(T), no two-length subtraction
companion legs vary bias (voltco) and length (head fraction) independently
right-hand block: ideal resistors sharing one .model card, probing how
ngspice applies .model tc1/tc2 to literal / constant-expr / v-dependent r=
corner (.lib), .temp, and measurements are injected by the corner runner} -100 -420 0 0 0.35 0.35 {}
C {sky130_fd_pr/res_xhigh_po.sym} 200 -100 0 0 {name=RXhL50a
W=1
L=50
model=res_xhigh_po
spiceprefix=X
mult=1}
C {devices/lab_pin.sym} 200 -70 0 0 {name=rmXhL50a lab=R_XH_L50_5U}
C {devices/lab_pin.sym} 200 -130 0 0 {name=rpXhL50a lab=0}
C {devices/lab_pin.sym} 180 -100 0 0 {name=rbXhL50a lab=0}
C {devices/isource.sym} 200 -250 0 0 {name=IXhL50a value=5u}
C {devices/lab_pin.sym} 200 -280 0 0 {name=ipXhL50a lab=0}
C {devices/lab_pin.sym} 200 -220 0 0 {name=imXhL50a lab=R_XH_L50_5U}
C {sky130_fd_pr/res_xhigh_po.sym} 450 -100 0 0 {name=RXhL50b
W=1
L=50
model=res_xhigh_po
spiceprefix=X
mult=1}
C {devices/lab_pin.sym} 450 -70 0 0 {name=rmXhL50b lab=R_XH_L50_0P5U}
C {devices/lab_pin.sym} 450 -130 0 0 {name=rpXhL50b lab=0}
C {devices/lab_pin.sym} 430 -100 0 0 {name=rbXhL50b lab=0}
C {devices/isource.sym} 450 -250 0 0 {name=IXhL50b value=0.5u}
C {devices/lab_pin.sym} 450 -280 0 0 {name=ipXhL50b lab=0}
C {devices/lab_pin.sym} 450 -220 0 0 {name=imXhL50b lab=R_XH_L50_0P5U}
C {sky130_fd_pr/res_xhigh_po.sym} 700 -100 0 0 {name=RXhL5
W=1
L=5
model=res_xhigh_po
spiceprefix=X
mult=1}
C {devices/lab_pin.sym} 700 -70 0 0 {name=rmXhL5 lab=R_XH_L5_5U}
C {devices/lab_pin.sym} 700 -130 0 0 {name=rpXhL5 lab=0}
C {devices/lab_pin.sym} 680 -100 0 0 {name=rbXhL5 lab=0}
C {devices/isource.sym} 700 -250 0 0 {name=IXhL5 value=5u}
C {devices/lab_pin.sym} 700 -280 0 0 {name=ipXhL5 lab=0}
C {devices/lab_pin.sym} 700 -220 0 0 {name=imXhL5 lab=R_XH_L5_5U}
C {sky130_fd_pr/res_high_po.sym} 950 -100 0 0 {name=RHighL50
W=1
L=50
model=res_high_po
spiceprefix=X
mult=1}
C {devices/lab_pin.sym} 950 -70 0 0 {name=rmHighL50 lab=R_HIGH_L50_5U}
C {devices/lab_pin.sym} 950 -130 0 0 {name=rpHighL50 lab=0}
C {devices/lab_pin.sym} 930 -100 0 0 {name=rbHighL50 lab=0}
C {devices/isource.sym} 950 -250 0 0 {name=IHighL50 value=5u}
C {devices/lab_pin.sym} 950 -280 0 0 {name=ipHighL50 lab=0}
C {devices/lab_pin.sym} 950 -220 0 0 {name=imHighL50 lab=R_HIGH_L50_5U}
C {devices/code_shown.sym} 1200 -300 0 0 {name=TCPROBE only_toplevel=false value="
* --- simulator-mechanism probe: ideal resistors, one shared .model card ---
* Same tc1/tc2/tnom on all three; they differ only in how r= is written.
* Each is biased by an ideal 1uA source so R = V/1uA reads out directly.
Rtclit TC_LIT 0 tcprobe_r r=1000
Itclit 0 TC_LIT 1u
Rtcexpr TC_EXPR 0 tcprobe_r r='1000*1.0'
Itcexpr 0 TC_EXPR 1u
Rtcbeh TC_BEH 0 tcprobe_r r='1000*(1+1e-12*abs(v(TC_BEH,0)))'
Itcbeh 0 TC_BEH 1u
.model tcprobe_r r tc1=-1.47e-3 tc2=2.7e-6 tnom=25
"}
