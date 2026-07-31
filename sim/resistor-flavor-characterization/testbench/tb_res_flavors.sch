v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap resistor-flavor characterization testbench (issue #4).
*
* NOT a bandgap -- device characterization only. Four independent
* current-biased two-terminal resistors (1 uA each, small enough that the
* modeled voltage-coefficient/self-heating terms are negligible), covering
* both candidate poly flavors (sky130_fd_pr__res_high_po, __res_xhigh_po)
* at two lengths (L=1um, L=20um; W=1um both) so sheet resistance can be
* extracted from the two-length slope method (removes rhead/contact-end
* resistance from the sheet-Rs estimate): Rs = (R(L20)-R(L1))*W/(L20-L1).
*
* Body/substrate pin (b) tied to ground for both flavors -- see
* sim/resistor-flavor-characterization/records/*.md for the corner list
* and the documented reason the supply axis is fixed (no supply-referenced
* terminal in this DUT).
*
* Deliberately NOT in this schematic (the corner runner injects them):
*   - the .lib model corner include, .temp, the .control block
}
G {}
K {}
V {}
S {}
E {}
T {resistor flavor Rs/TC characterization -- not the bandgap
high = sky130_fd_pr__res_high_po, xhigh = sky130_fd_pr__res_xhigh_po
two-length (L=1,20um) slope method extracts Rs excluding head/contact R
corner (.lib), .temp, and measurements are injected by the corner runner} -100 -400 0 0 0.35 0.35 {}
C {sky130_fd_pr/res_high_po.sym} 200 -100 0 0 {name=RHighL1
W=1
L=1
model=res_high_po
spiceprefix=X
mult=1}
C {devices/lab_pin.sym} 200 -70 0 0 {name=rmHighL1 lab=R_HighL1}
C {devices/lab_pin.sym} 200 -130 0 0 {name=rpHighL1 lab=0}
C {devices/lab_pin.sym} 180 -100 0 0 {name=rbHighL1 lab=0}
C {devices/isource.sym} 200 -250 0 0 {name=IHighL1 value=1u}
C {devices/lab_pin.sym} 200 -280 0 0 {name=ipHighL1 lab=0}
C {devices/lab_pin.sym} 200 -220 0 0 {name=imHighL1 lab=R_HighL1}
C {sky130_fd_pr/res_high_po.sym} 450 -100 0 0 {name=RHighL20
W=1
L=20
model=res_high_po
spiceprefix=X
mult=1}
C {devices/lab_pin.sym} 450 -70 0 0 {name=rmHighL20 lab=R_HighL20}
C {devices/lab_pin.sym} 450 -130 0 0 {name=rpHighL20 lab=0}
C {devices/lab_pin.sym} 430 -100 0 0 {name=rbHighL20 lab=0}
C {devices/isource.sym} 450 -250 0 0 {name=IHighL20 value=1u}
C {devices/lab_pin.sym} 450 -280 0 0 {name=ipHighL20 lab=0}
C {devices/lab_pin.sym} 450 -220 0 0 {name=imHighL20 lab=R_HighL20}
C {sky130_fd_pr/res_xhigh_po.sym} 700 -100 0 0 {name=RXhighL1
W=1
L=1
model=res_xhigh_po
spiceprefix=X
mult=1}
C {devices/lab_pin.sym} 700 -70 0 0 {name=rmXhighL1 lab=R_XhighL1}
C {devices/lab_pin.sym} 700 -130 0 0 {name=rpXhighL1 lab=0}
C {devices/lab_pin.sym} 680 -100 0 0 {name=rbXhighL1 lab=0}
C {devices/isource.sym} 700 -250 0 0 {name=IXhighL1 value=1u}
C {devices/lab_pin.sym} 700 -280 0 0 {name=ipXhighL1 lab=0}
C {devices/lab_pin.sym} 700 -220 0 0 {name=imXhighL1 lab=R_XhighL1}
C {sky130_fd_pr/res_xhigh_po.sym} 950 -100 0 0 {name=RXhighL20
W=1
L=20
model=res_xhigh_po
spiceprefix=X
mult=1}
C {devices/lab_pin.sym} 950 -70 0 0 {name=rmXhighL20 lab=R_XhighL20}
C {devices/lab_pin.sym} 950 -130 0 0 {name=rpXhighL20 lab=0}
C {devices/lab_pin.sym} 930 -100 0 0 {name=rbXhighL20 lab=0}
C {devices/isource.sym} 950 -250 0 0 {name=IXhighL20 value=1u}
C {devices/lab_pin.sym} 950 -280 0 0 {name=ipXhighL20 lab=0}
C {devices/lab_pin.sym} 950 -220 0 0 {name=imXhighL20 lab=R_XhighL20}
