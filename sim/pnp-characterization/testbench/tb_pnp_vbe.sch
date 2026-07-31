v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap PNP characterization testbench (issue #4).
*
* NOT a bandgap -- device characterization only. Two sky130_fd_pr__pnp_05v5
* emitter-size variants (W0p68L0p68 'small unit', W3p40L3p40 'large unit'),
* each diode-connected (base+collector tied to substrate/ground -- the
* pnp_05v5 collector node IS the substrate in this device, see the PDK
* model card), biased by independent ideal DC current sources spanning
* 100 nA .. 100 uA (log half-decade steps) so one .op analysis captures the
* full VBE-vs-Ic sweep at a single PVT point -- the corner runner sweeps
* PVT around this fixed bias ladder.
*
* Measured per branch: v(E_small_<i>) / v(E_large_<i>) = VEB of the diode-
* connected device (base=collector=0, so VEB = V(emitter)).
* dVBE at matched current: v(E_small_<i>) - v(E_large_<i>).
*
* Deliberately NOT in this schematic (the corner runner injects them):
*   - the .lib model corner include, .temp, the .control block
}
G {}
K {}
V {}
S {}
E {}
T {PNP VBE/dVBE vs Ic characterization -- not the bandgap
small = sky130_fd_pr__pnp_05v5_W0p68L0p68, large = sky130_fd_pr__pnp_05v5_W3p40L3p40
both diode-connected (B=C=0); one ideal Idc branch per current point
corner (.lib), .temp, and measurements are injected by the corner runner} -100 -650 0 0 0.35 0.35 {}
C {sky130_fd_pr/pnp_05v5.sym} 200 -100 0 0 {name=QS0
model=pnp_05v5_W0p68L0p68
m=1
spiceprefix=X}
C {devices/lab_pin.sym} 180 -100 0 0 {name=qbS0 lab=0}
C {devices/lab_pin.sym} 220 -130 0 0 {name=qcS0 lab=0}
C {devices/lab_pin.sym} 220 -70 0 0 {name=qeS0 lab=E_small_100n}
C {devices/isource.sym} 220 -250 0 0 {name=IS0 value=1e-07}
C {devices/lab_pin.sym} 220 -280 0 0 {name=ipS0 lab=0}
C {devices/lab_pin.sym} 220 -220 0 0 {name=imS0 lab=E_small_100n}
C {sky130_fd_pr/pnp_05v5.sym} 200 -500 0 0 {name=QL0
model=pnp_05v5_W3p40L3p40
m=1
spiceprefix=X}
C {devices/lab_pin.sym} 180 -500 0 0 {name=qbL0 lab=0}
C {devices/lab_pin.sym} 220 -530 0 0 {name=qcL0 lab=0}
C {devices/lab_pin.sym} 220 -470 0 0 {name=qeL0 lab=E_large_100n}
C {devices/isource.sym} 220 -650 0 0 {name=IL0 value=1e-07}
C {devices/lab_pin.sym} 220 -680 0 0 {name=ipL0 lab=0}
C {devices/lab_pin.sym} 220 -620 0 0 {name=imL0 lab=E_large_100n}
C {sky130_fd_pr/pnp_05v5.sym} 450 -100 0 0 {name=QS1
model=pnp_05v5_W0p68L0p68
m=1
spiceprefix=X}
C {devices/lab_pin.sym} 430 -100 0 0 {name=qbS1 lab=0}
C {devices/lab_pin.sym} 470 -130 0 0 {name=qcS1 lab=0}
C {devices/lab_pin.sym} 470 -70 0 0 {name=qeS1 lab=E_small_316n}
C {devices/isource.sym} 470 -250 0 0 {name=IS1 value=3.16e-07}
C {devices/lab_pin.sym} 470 -280 0 0 {name=ipS1 lab=0}
C {devices/lab_pin.sym} 470 -220 0 0 {name=imS1 lab=E_small_316n}
C {sky130_fd_pr/pnp_05v5.sym} 450 -500 0 0 {name=QL1
model=pnp_05v5_W3p40L3p40
m=1
spiceprefix=X}
C {devices/lab_pin.sym} 430 -500 0 0 {name=qbL1 lab=0}
C {devices/lab_pin.sym} 470 -530 0 0 {name=qcL1 lab=0}
C {devices/lab_pin.sym} 470 -470 0 0 {name=qeL1 lab=E_large_316n}
C {devices/isource.sym} 470 -650 0 0 {name=IL1 value=3.16e-07}
C {devices/lab_pin.sym} 470 -680 0 0 {name=ipL1 lab=0}
C {devices/lab_pin.sym} 470 -620 0 0 {name=imL1 lab=E_large_316n}
C {sky130_fd_pr/pnp_05v5.sym} 700 -100 0 0 {name=QS2
model=pnp_05v5_W0p68L0p68
m=1
spiceprefix=X}
C {devices/lab_pin.sym} 680 -100 0 0 {name=qbS2 lab=0}
C {devices/lab_pin.sym} 720 -130 0 0 {name=qcS2 lab=0}
C {devices/lab_pin.sym} 720 -70 0 0 {name=qeS2 lab=E_small_1u}
C {devices/isource.sym} 720 -250 0 0 {name=IS2 value=1e-06}
C {devices/lab_pin.sym} 720 -280 0 0 {name=ipS2 lab=0}
C {devices/lab_pin.sym} 720 -220 0 0 {name=imS2 lab=E_small_1u}
C {sky130_fd_pr/pnp_05v5.sym} 700 -500 0 0 {name=QL2
model=pnp_05v5_W3p40L3p40
m=1
spiceprefix=X}
C {devices/lab_pin.sym} 680 -500 0 0 {name=qbL2 lab=0}
C {devices/lab_pin.sym} 720 -530 0 0 {name=qcL2 lab=0}
C {devices/lab_pin.sym} 720 -470 0 0 {name=qeL2 lab=E_large_1u}
C {devices/isource.sym} 720 -650 0 0 {name=IL2 value=1e-06}
C {devices/lab_pin.sym} 720 -680 0 0 {name=ipL2 lab=0}
C {devices/lab_pin.sym} 720 -620 0 0 {name=imL2 lab=E_large_1u}
C {sky130_fd_pr/pnp_05v5.sym} 950 -100 0 0 {name=QS3
model=pnp_05v5_W0p68L0p68
m=1
spiceprefix=X}
C {devices/lab_pin.sym} 930 -100 0 0 {name=qbS3 lab=0}
C {devices/lab_pin.sym} 970 -130 0 0 {name=qcS3 lab=0}
C {devices/lab_pin.sym} 970 -70 0 0 {name=qeS3 lab=E_small_3p16u}
C {devices/isource.sym} 970 -250 0 0 {name=IS3 value=3.16e-06}
C {devices/lab_pin.sym} 970 -280 0 0 {name=ipS3 lab=0}
C {devices/lab_pin.sym} 970 -220 0 0 {name=imS3 lab=E_small_3p16u}
C {sky130_fd_pr/pnp_05v5.sym} 950 -500 0 0 {name=QL3
model=pnp_05v5_W3p40L3p40
m=1
spiceprefix=X}
C {devices/lab_pin.sym} 930 -500 0 0 {name=qbL3 lab=0}
C {devices/lab_pin.sym} 970 -530 0 0 {name=qcL3 lab=0}
C {devices/lab_pin.sym} 970 -470 0 0 {name=qeL3 lab=E_large_3p16u}
C {devices/isource.sym} 970 -650 0 0 {name=IL3 value=3.16e-06}
C {devices/lab_pin.sym} 970 -680 0 0 {name=ipL3 lab=0}
C {devices/lab_pin.sym} 970 -620 0 0 {name=imL3 lab=E_large_3p16u}
C {sky130_fd_pr/pnp_05v5.sym} 1200 -100 0 0 {name=QS4
model=pnp_05v5_W0p68L0p68
m=1
spiceprefix=X}
C {devices/lab_pin.sym} 1180 -100 0 0 {name=qbS4 lab=0}
C {devices/lab_pin.sym} 1220 -130 0 0 {name=qcS4 lab=0}
C {devices/lab_pin.sym} 1220 -70 0 0 {name=qeS4 lab=E_small_10u}
C {devices/isource.sym} 1220 -250 0 0 {name=IS4 value=1e-05}
C {devices/lab_pin.sym} 1220 -280 0 0 {name=ipS4 lab=0}
C {devices/lab_pin.sym} 1220 -220 0 0 {name=imS4 lab=E_small_10u}
C {sky130_fd_pr/pnp_05v5.sym} 1200 -500 0 0 {name=QL4
model=pnp_05v5_W3p40L3p40
m=1
spiceprefix=X}
C {devices/lab_pin.sym} 1180 -500 0 0 {name=qbL4 lab=0}
C {devices/lab_pin.sym} 1220 -530 0 0 {name=qcL4 lab=0}
C {devices/lab_pin.sym} 1220 -470 0 0 {name=qeL4 lab=E_large_10u}
C {devices/isource.sym} 1220 -650 0 0 {name=IL4 value=1e-05}
C {devices/lab_pin.sym} 1220 -680 0 0 {name=ipL4 lab=0}
C {devices/lab_pin.sym} 1220 -620 0 0 {name=imL4 lab=E_large_10u}
C {sky130_fd_pr/pnp_05v5.sym} 1450 -100 0 0 {name=QS5
model=pnp_05v5_W0p68L0p68
m=1
spiceprefix=X}
C {devices/lab_pin.sym} 1430 -100 0 0 {name=qbS5 lab=0}
C {devices/lab_pin.sym} 1470 -130 0 0 {name=qcS5 lab=0}
C {devices/lab_pin.sym} 1470 -70 0 0 {name=qeS5 lab=E_small_31p6u}
C {devices/isource.sym} 1470 -250 0 0 {name=IS5 value=3.16e-05}
C {devices/lab_pin.sym} 1470 -280 0 0 {name=ipS5 lab=0}
C {devices/lab_pin.sym} 1470 -220 0 0 {name=imS5 lab=E_small_31p6u}
C {sky130_fd_pr/pnp_05v5.sym} 1450 -500 0 0 {name=QL5
model=pnp_05v5_W3p40L3p40
m=1
spiceprefix=X}
C {devices/lab_pin.sym} 1430 -500 0 0 {name=qbL5 lab=0}
C {devices/lab_pin.sym} 1470 -530 0 0 {name=qcL5 lab=0}
C {devices/lab_pin.sym} 1470 -470 0 0 {name=qeL5 lab=E_large_31p6u}
C {devices/isource.sym} 1470 -650 0 0 {name=IL5 value=3.16e-05}
C {devices/lab_pin.sym} 1470 -680 0 0 {name=ipL5 lab=0}
C {devices/lab_pin.sym} 1470 -620 0 0 {name=imL5 lab=E_large_31p6u}
C {sky130_fd_pr/pnp_05v5.sym} 1700 -100 0 0 {name=QS6
model=pnp_05v5_W0p68L0p68
m=1
spiceprefix=X}
C {devices/lab_pin.sym} 1680 -100 0 0 {name=qbS6 lab=0}
C {devices/lab_pin.sym} 1720 -130 0 0 {name=qcS6 lab=0}
C {devices/lab_pin.sym} 1720 -70 0 0 {name=qeS6 lab=E_small_100u}
C {devices/isource.sym} 1720 -250 0 0 {name=IS6 value=0.0001}
C {devices/lab_pin.sym} 1720 -280 0 0 {name=ipS6 lab=0}
C {devices/lab_pin.sym} 1720 -220 0 0 {name=imS6 lab=E_small_100u}
C {sky130_fd_pr/pnp_05v5.sym} 1700 -500 0 0 {name=QL6
model=pnp_05v5_W3p40L3p40
m=1
spiceprefix=X}
C {devices/lab_pin.sym} 1680 -500 0 0 {name=qbL6 lab=0}
C {devices/lab_pin.sym} 1720 -530 0 0 {name=qcL6 lab=0}
C {devices/lab_pin.sym} 1720 -470 0 0 {name=qeL6 lab=E_large_100u}
C {devices/isource.sym} 1720 -650 0 0 {name=IL6 value=0.0001}
C {devices/lab_pin.sym} 1720 -680 0 0 {name=ipL6 lab=0}
C {devices/lab_pin.sym} 1720 -620 0 0 {name=imL6 lab=E_large_100u}
