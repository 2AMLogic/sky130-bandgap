v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap MOS mirror sizing-extension characterization testbench
* (issue #26 -- follow-up to issue #4's sim/mos-matching-characterization/,
* run once #8 (schematic entry, PR #40) fixed the core's actual mirror
* device sizes and node currents).
*
* NOT a bandgap -- device characterization only, same diode-connected
* single-device methodology as sim/mos-matching-characterization/.
*
* Unlike the original experiment (2 sizes x 3 generic currents, ratio- and
* current-agnostic), this testbench targets the ACTUAL PMOS mirror device
* geometry and node current design/bandgap_core.sch (#8, merged via PR #40)
* uses: sky130_fd_pr__pfet_g5v0d10v5, W=8/L=2 (mult=2) for both MPOUT and
* MPAMP, self-biased off one GDRV gate. Per bandgap_core.sch's own sizing
* comment, the branch current is I ~= dVBE/R1 ~= 62.3mV/11.8kohm ~= 5.3uA;
* because MPOUT/MPAMP are both mult=2 devices whose total current equals
* twice (MPOUT, feeding both R2A/R2B branches) or once (MPAMP mirrors the
* same GDRV gate into the error-amp's tail) that branch current, every unit
* device in this self-biased mirror chain lands at the SAME ~5.3uA per-unit
* current -- there is one actual bias point, not a generic sweep, which is
* why this testbench fixes a single current rather than reusing the
* original's 2/5/20uA matrix (see design/device-characterization-summary.md
* Sec 3 for the derivation and the record for the full corner matrix).
*
* Device size is W=8/L=2 (size B, 16um^2, the schematic's actual size, kept
* here only as a cross-check against the original record's 5uA row) plus
* three larger sizes that hold the SAME W/L=4 aspect ratio as size B (so
* Vov/gm-Id stay close to size B's operating point at the same current --
* isolating the sigma(Vth)-vs-area trend the AVT projection needs) while
* scaling raw area up to and beyond the 32-64 um^2 range issue #26 asked
* for, to actually locate where the projected mismatch crosses below 1%:
*   B: W=8  L=2  ( 16 um^2, 1x -- the schematic's actual size)
*   C: W=12 L=3  ( 36 um^2, 2.25x)
*   D: W=16 L=4  ( 64 um^2, 4x)
*   E: W=20 L=5  (100 um^2, 6.25x)
*
* Both device types (NFET/PFET) are swept at every size for parity with the
* original experiment's structure and so the record can state which leg (if
* either) needs sub-1% area. The core's own mirror devices are PFET only
* (MPOUT/MPAMP); the schematic's only NFET mirror/load devices are
* error_amp.sch's MN1-MN4 (W=4/L=2, W/L=2 -- a different aspect ratio, not
* covered by this W/L=4 family) inside the placeholder amplifier issue #9
* replaces, so the NFET numbers here are a like-for-like generalization of
* size A/B's aspect ratio, not a literal error_amp device match -- flagged
* in the summary record rather than adding a third aspect-ratio family here.
*
* Deliberately NOT in this schematic (the corner runner injects them):
*   - the .lib model corner include, .temp, the .control/measurement block
}
G {}
K {}
V {}
S {}
E {}
T {NFET/PFET mirror-device sizing sweep beyond size B -- not the bandgap
sizes: B=8/2 (16um^2, actual core size), C=12/3 (36um^2), D=16/4 (64um^2),
E=20/5 (100um^2) -- all W/L=4, same aspect ratio as size B
current: 5.3uA -- the actual per-unit mirror-device node current #8's
bandgap_core.sch self-biased chain converges on (see header)
corner (.lib), .temp, and measurements are injected by the corner runner} -100 -700 0 0 0.35 0.35 {}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 200 -100 0 0 {name=MNB
L=2
W=8
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 220 -130 0 0 {name=dNB lab=VD_NB}
C {devices/lab_pin.sym} 180 -100 0 0 {name=gNB lab=VD_NB}
C {devices/lab_pin.sym} 220 -70 0 0 {name=sNB lab=0}
C {devices/lab_pin.sym} 220 -100 0 0 {name=bNB lab=0}
C {devices/isource.sym} 220 -250 0 0 {name=INB value=5.3e-06}
C {devices/lab_pin.sym} 220 -280 0 0 {name=ipNB lab=0}
C {devices/lab_pin.sym} 220 -220 0 0 {name=imNB lab=VD_NB}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 200 -500 0 0 {name=MPB
L=2
W=8
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 220 -470 0 0 {name=dPB lab=0}
C {devices/lab_pin.sym} 180 -500 0 0 {name=gPB lab=0}
C {devices/lab_pin.sym} 220 -530 0 0 {name=sPB lab=VS_PB}
C {devices/lab_pin.sym} 220 -500 0 0 {name=bPB lab=VS_PB}
C {devices/isource.sym} 220 -650 0 0 {name=IPB value=5.3e-06}
C {devices/lab_pin.sym} 220 -680 0 0 {name=ipPB lab=0}
C {devices/lab_pin.sym} 220 -620 0 0 {name=imPB lab=VS_PB}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 420 -100 0 0 {name=MNC
L=3
W=12
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 440 -130 0 0 {name=dNC lab=VD_NC}
C {devices/lab_pin.sym} 400 -100 0 0 {name=gNC lab=VD_NC}
C {devices/lab_pin.sym} 440 -70 0 0 {name=sNC lab=0}
C {devices/lab_pin.sym} 440 -100 0 0 {name=bNC lab=0}
C {devices/isource.sym} 440 -250 0 0 {name=INC value=5.3e-06}
C {devices/lab_pin.sym} 440 -280 0 0 {name=ipNC lab=0}
C {devices/lab_pin.sym} 440 -220 0 0 {name=imNC lab=VD_NC}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 420 -500 0 0 {name=MPC
L=3
W=12
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 440 -470 0 0 {name=dPC lab=0}
C {devices/lab_pin.sym} 400 -500 0 0 {name=gPC lab=0}
C {devices/lab_pin.sym} 440 -530 0 0 {name=sPC lab=VS_PC}
C {devices/lab_pin.sym} 440 -500 0 0 {name=bPC lab=VS_PC}
C {devices/isource.sym} 440 -650 0 0 {name=IPC value=5.3e-06}
C {devices/lab_pin.sym} 440 -680 0 0 {name=ipPC lab=0}
C {devices/lab_pin.sym} 440 -620 0 0 {name=imPC lab=VS_PC}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 640 -100 0 0 {name=MND
L=4
W=16
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 660 -130 0 0 {name=dND lab=VD_ND}
C {devices/lab_pin.sym} 620 -100 0 0 {name=gND lab=VD_ND}
C {devices/lab_pin.sym} 660 -70 0 0 {name=sND lab=0}
C {devices/lab_pin.sym} 660 -100 0 0 {name=bND lab=0}
C {devices/isource.sym} 660 -250 0 0 {name=IND value=5.3e-06}
C {devices/lab_pin.sym} 660 -280 0 0 {name=ipND lab=0}
C {devices/lab_pin.sym} 660 -220 0 0 {name=imND lab=VD_ND}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 640 -500 0 0 {name=MPD
L=4
W=16
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 660 -470 0 0 {name=dPD lab=0}
C {devices/lab_pin.sym} 620 -500 0 0 {name=gPD lab=0}
C {devices/lab_pin.sym} 660 -530 0 0 {name=sPD lab=VS_PD}
C {devices/lab_pin.sym} 660 -500 0 0 {name=bPD lab=VS_PD}
C {devices/isource.sym} 660 -650 0 0 {name=IPD value=5.3e-06}
C {devices/lab_pin.sym} 660 -680 0 0 {name=ipPD lab=0}
C {devices/lab_pin.sym} 660 -620 0 0 {name=imPD lab=VS_PD}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 860 -100 0 0 {name=MNE
L=5
W=20
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 880 -130 0 0 {name=dNE lab=VD_NE}
C {devices/lab_pin.sym} 840 -100 0 0 {name=gNE lab=VD_NE}
C {devices/lab_pin.sym} 880 -70 0 0 {name=sNE lab=0}
C {devices/lab_pin.sym} 880 -100 0 0 {name=bNE lab=0}
C {devices/isource.sym} 880 -250 0 0 {name=INE value=5.3e-06}
C {devices/lab_pin.sym} 880 -280 0 0 {name=ipNE lab=0}
C {devices/lab_pin.sym} 880 -220 0 0 {name=imNE lab=VD_NE}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 860 -500 0 0 {name=MPE
L=5
W=20
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
C {devices/lab_pin.sym} 880 -470 0 0 {name=dPE lab=0}
C {devices/lab_pin.sym} 840 -500 0 0 {name=gPE lab=0}
C {devices/lab_pin.sym} 880 -530 0 0 {name=sPE lab=VS_PE}
C {devices/lab_pin.sym} 880 -500 0 0 {name=bPE lab=VS_PE}
C {devices/isource.sym} 880 -650 0 0 {name=IPE value=5.3e-06}
C {devices/lab_pin.sym} 880 -680 0 0 {name=ipPE lab=0}
C {devices/lab_pin.sym} 880 -620 0 0 {name=imPE lab=VS_PE}
