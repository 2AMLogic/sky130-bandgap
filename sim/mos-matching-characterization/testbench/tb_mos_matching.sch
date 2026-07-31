v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap MOS mirror-matching characterization testbench (issue #4).
*
* NOT a bandgap -- device characterization only. Diode-connected
* sky130_fd_pr__nfet_g5v0d10v5 / __pfet_g5v0d10v5 devices at two sizes
* (A: W=4/L=1um, area=4um^2; B: W=8/L=2um, area=16um^2, 4x A) and three
* bias currents (2/5/20 uA) spanning the per-branch range implied by a
* <50uA total Iq bandgap core. One .op analysis captures the whole
* size x current sweep at each PVT point; gm/Id/Vth/Vgs are read directly
* from the BSIM operating-point via '@m...[param]' so the recommended
* operating region (VOV, gm/Id) can be reported alongside the PDK's own
* static Vth-mismatch (AVT) coefficients -- see the summary record for
* the analytic dID/ID projection method.
*
* Deliberately NOT in this schematic (the corner runner injects them):
*   - the .lib model corner include, .temp, the .control/measurement block
}
G {}
K {}
V {}
S {}
E {}
T {NFET/PFET mirror-device operating-point sweep -- not the bandgap
size A: W=4 L=1 (4um^2); size B: W=8 L=2 (16um^2, 4x area of A)
currents: 2uA, 5uA, 20uA -- representative per-branch bandgap mirror currents
corner (.lib), .temp, and measurements are injected by the corner runner} -100 -700 0 0 0.35 0.35 {}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 200 -100 0 0 {name=MNA2u
L=1
W=4
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 220 -130 0 0 {name=dNA2u lab=VD_NA2u}
C {devices/lab_pin.sym} 180 -100 0 0 {name=gNA2u lab=VD_NA2u}
C {devices/lab_pin.sym} 220 -70 0 0 {name=sNA2u lab=0}
C {devices/lab_pin.sym} 220 -100 0 0 {name=bNA2u lab=0}
C {devices/isource.sym} 220 -250 0 0 {name=INA2u value=2e-06}
C {devices/lab_pin.sym} 220 -280 0 0 {name=ipNA2u lab=0}
C {devices/lab_pin.sym} 220 -220 0 0 {name=imNA2u lab=VD_NA2u}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 200 -500 0 0 {name=MPA2u
L=1
W=4
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 220 -470 0 0 {name=dPA2u lab=0}
C {devices/lab_pin.sym} 180 -500 0 0 {name=gPA2u lab=0}
C {devices/lab_pin.sym} 220 -530 0 0 {name=sPA2u lab=VS_PA2u}
C {devices/lab_pin.sym} 220 -500 0 0 {name=bPA2u lab=VS_PA2u}
C {devices/isource.sym} 220 -650 0 0 {name=IPA2u value=2e-06}
C {devices/lab_pin.sym} 220 -680 0 0 {name=ipPA2u lab=0}
C {devices/lab_pin.sym} 220 -620 0 0 {name=imPA2u lab=VS_PA2u}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 420 -100 0 0 {name=MNA5u
L=1
W=4
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 440 -130 0 0 {name=dNA5u lab=VD_NA5u}
C {devices/lab_pin.sym} 400 -100 0 0 {name=gNA5u lab=VD_NA5u}
C {devices/lab_pin.sym} 440 -70 0 0 {name=sNA5u lab=0}
C {devices/lab_pin.sym} 440 -100 0 0 {name=bNA5u lab=0}
C {devices/isource.sym} 440 -250 0 0 {name=INA5u value=5e-06}
C {devices/lab_pin.sym} 440 -280 0 0 {name=ipNA5u lab=0}
C {devices/lab_pin.sym} 440 -220 0 0 {name=imNA5u lab=VD_NA5u}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 420 -500 0 0 {name=MPA5u
L=1
W=4
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 440 -470 0 0 {name=dPA5u lab=0}
C {devices/lab_pin.sym} 400 -500 0 0 {name=gPA5u lab=0}
C {devices/lab_pin.sym} 440 -530 0 0 {name=sPA5u lab=VS_PA5u}
C {devices/lab_pin.sym} 440 -500 0 0 {name=bPA5u lab=VS_PA5u}
C {devices/isource.sym} 440 -650 0 0 {name=IPA5u value=5e-06}
C {devices/lab_pin.sym} 440 -680 0 0 {name=ipPA5u lab=0}
C {devices/lab_pin.sym} 440 -620 0 0 {name=imPA5u lab=VS_PA5u}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 640 -100 0 0 {name=MNA20u
L=1
W=4
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 660 -130 0 0 {name=dNA20u lab=VD_NA20u}
C {devices/lab_pin.sym} 620 -100 0 0 {name=gNA20u lab=VD_NA20u}
C {devices/lab_pin.sym} 660 -70 0 0 {name=sNA20u lab=0}
C {devices/lab_pin.sym} 660 -100 0 0 {name=bNA20u lab=0}
C {devices/isource.sym} 660 -250 0 0 {name=INA20u value=2e-05}
C {devices/lab_pin.sym} 660 -280 0 0 {name=ipNA20u lab=0}
C {devices/lab_pin.sym} 660 -220 0 0 {name=imNA20u lab=VD_NA20u}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 640 -500 0 0 {name=MPA20u
L=1
W=4
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 660 -470 0 0 {name=dPA20u lab=0}
C {devices/lab_pin.sym} 620 -500 0 0 {name=gPA20u lab=0}
C {devices/lab_pin.sym} 660 -530 0 0 {name=sPA20u lab=VS_PA20u}
C {devices/lab_pin.sym} 660 -500 0 0 {name=bPA20u lab=VS_PA20u}
C {devices/isource.sym} 660 -650 0 0 {name=IPA20u value=2e-05}
C {devices/lab_pin.sym} 660 -680 0 0 {name=ipPA20u lab=0}
C {devices/lab_pin.sym} 660 -620 0 0 {name=imPA20u lab=VS_PA20u}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 860 -100 0 0 {name=MNB2u
L=2
W=8
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 880 -130 0 0 {name=dNB2u lab=VD_NB2u}
C {devices/lab_pin.sym} 840 -100 0 0 {name=gNB2u lab=VD_NB2u}
C {devices/lab_pin.sym} 880 -70 0 0 {name=sNB2u lab=0}
C {devices/lab_pin.sym} 880 -100 0 0 {name=bNB2u lab=0}
C {devices/isource.sym} 880 -250 0 0 {name=INB2u value=2e-06}
C {devices/lab_pin.sym} 880 -280 0 0 {name=ipNB2u lab=0}
C {devices/lab_pin.sym} 880 -220 0 0 {name=imNB2u lab=VD_NB2u}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 860 -500 0 0 {name=MPB2u
L=2
W=8
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 880 -470 0 0 {name=dPB2u lab=0}
C {devices/lab_pin.sym} 840 -500 0 0 {name=gPB2u lab=0}
C {devices/lab_pin.sym} 880 -530 0 0 {name=sPB2u lab=VS_PB2u}
C {devices/lab_pin.sym} 880 -500 0 0 {name=bPB2u lab=VS_PB2u}
C {devices/isource.sym} 880 -650 0 0 {name=IPB2u value=2e-06}
C {devices/lab_pin.sym} 880 -680 0 0 {name=ipPB2u lab=0}
C {devices/lab_pin.sym} 880 -620 0 0 {name=imPB2u lab=VS_PB2u}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 1080 -100 0 0 {name=MNB5u
L=2
W=8
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 1100 -130 0 0 {name=dNB5u lab=VD_NB5u}
C {devices/lab_pin.sym} 1060 -100 0 0 {name=gNB5u lab=VD_NB5u}
C {devices/lab_pin.sym} 1100 -70 0 0 {name=sNB5u lab=0}
C {devices/lab_pin.sym} 1100 -100 0 0 {name=bNB5u lab=0}
C {devices/isource.sym} 1100 -250 0 0 {name=INB5u value=5e-06}
C {devices/lab_pin.sym} 1100 -280 0 0 {name=ipNB5u lab=0}
C {devices/lab_pin.sym} 1100 -220 0 0 {name=imNB5u lab=VD_NB5u}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 1080 -500 0 0 {name=MPB5u
L=2
W=8
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 1100 -470 0 0 {name=dPB5u lab=0}
C {devices/lab_pin.sym} 1060 -500 0 0 {name=gPB5u lab=0}
C {devices/lab_pin.sym} 1100 -530 0 0 {name=sPB5u lab=VS_PB5u}
C {devices/lab_pin.sym} 1100 -500 0 0 {name=bPB5u lab=VS_PB5u}
C {devices/isource.sym} 1100 -650 0 0 {name=IPB5u value=5e-06}
C {devices/lab_pin.sym} 1100 -680 0 0 {name=ipPB5u lab=0}
C {devices/lab_pin.sym} 1100 -620 0 0 {name=imPB5u lab=VS_PB5u}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 1300 -100 0 0 {name=MNB20u
L=2
W=8
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 1320 -130 0 0 {name=dNB20u lab=VD_NB20u}
C {devices/lab_pin.sym} 1280 -100 0 0 {name=gNB20u lab=VD_NB20u}
C {devices/lab_pin.sym} 1320 -70 0 0 {name=sNB20u lab=0}
C {devices/lab_pin.sym} 1320 -100 0 0 {name=bNB20u lab=0}
C {devices/isource.sym} 1320 -250 0 0 {name=INB20u value=2e-05}
C {devices/lab_pin.sym} 1320 -280 0 0 {name=ipNB20u lab=0}
C {devices/lab_pin.sym} 1320 -220 0 0 {name=imNB20u lab=VD_NB20u}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 1300 -500 0 0 {name=MPB20u
L=2
W=8
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 1320 -470 0 0 {name=dPB20u lab=0}
C {devices/lab_pin.sym} 1280 -500 0 0 {name=gPB20u lab=0}
C {devices/lab_pin.sym} 1320 -530 0 0 {name=sPB20u lab=VS_PB20u}
C {devices/lab_pin.sym} 1320 -500 0 0 {name=bPB20u lab=VS_PB20u}
C {devices/isource.sym} 1320 -650 0 0 {name=IPB20u value=2e-05}
C {devices/lab_pin.sym} 1320 -680 0 0 {name=ipPB20u lab=0}
C {devices/lab_pin.sym} 1320 -620 0 0 {name=imPB20u lab=VS_PB20u}
