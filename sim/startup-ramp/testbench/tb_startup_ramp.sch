v {xschem version=3.4.7 file_version=1.2
* sky130-bandgap supply-ramp startup testbench (issue #10).
*
* Four independent copies of (bandgap_core + startup_injector), one per
* power-up profile, all simulated in a single transient so every PVT point
* costs one ngspice invocation:
*
*   XSLOW / XSUS   VDDS ramps 0 -> vsup in t_slow (slow supply ramp)
*   XFAST / XSUF   VDDF ramps 0 -> vsup in t_fast (fast supply ramp)
*   XDEG  / XSUG   VDDG steps 0 -> vsup in 1 ns AND the mirror gate GG is
*                  initialised to vsup -- i.e. the circuit is *placed in*
*                  the degenerate zero-current state, at full supply, and
*                  asked to leave it. This is the case the issue is really
*                  about; the two ramps above start from GDRV = 0, which is
*                  the over-driven side of the loop, not the stuck side.
*   XDEGN          the CONTROL: the same degenerate initial condition and
*                  the same 1 ns supply step, on a core with NO injector
*                  attached. It has to stay stuck. If it ever came up on
*                  its own, the premise of this issue -- and the value of
*                  every other number in the record -- would be wrong, so
*                  vref_degn is a bounded measurement, not a comment.
*
* The transient is run with UIC, so every node starts at 0 V (except GG and
* GN, set by the .ic below). No .nodeset, no preloaded operating point --
* contrast sim/bandgap-smoke/, which had to seed the solver because no
* startup circuit existed yet.
*
* Startup time is reported two ways per ramp:
*   t_start_*  = (VREF crosses 1.05 V) - (VDD crosses 2.90 V), i.e. measured
*                from the supply arriving, which is what the "< 1 ms,
*                self-starting" spec line means. 2.90 V is used rather than
*                the 2.97 V minimum-supply endpoint so the crossing exists
*                even at the 2.97 V corner, where the ramp only *reaches*
*                2.97 V. Negative means the reference was already up before
*                the supply finished arriving (normal on the slow ramp) --
*                a pass, and the reason there is no lower limit on it.
*   t_abs_*    = absolute time of the VREF crossing from t = 0, bounded by
*                (that ramp's duration + the 1 ms spec line). Recorded so a
*                negative t_start_* is never the only number on the page.
*
* vref_spread additionally asserts the four copies converge to the *same*
* operating point: a startup circuit that left the core in a different (e.g.
* over-driven) stable state would show up as a ramp-rate-dependent output.
*
* Deliberately NOT in this schematic (the corner runner injects them, so one
* schematic serves the whole PVT matrix):
*   - the .lib model corner include, .temp
*   - the numeric supply value: the sources are 'vsup', a .param the runner
*     sets, and t_slow / t_fast come from the manifest's deck.params
*   - the .control analysis/measurement block
}
G {}
K {}
V {}
S {}
E {}
T {startup ramp testbench -- three supply profiles, one transient
DUTs are design/bandgap_core.sym + design/startup_injector.sym.
Started from the zero-current state by running the transient with UIC.
Connectivity is by net label (lab_pin on every pin), no wires.
Supply value comes from .param vsup; ramp times from .param t_slow/t_fast;
corner (.lib) and .temp are injected by sim/bin/corner-run.py.} 100 -700 0 0 0.4 0.4 {}
C {devices/code_shown.sym} 100 -900 0 0 {name=TB_DEGENERATE only_toplevel=true value="
* Put the XDEG copy (injector attached) and the XDEGN control copy (no
* injector) in the degenerate zero-current state at t = 0: their mirror gates
* start at the supply rail, which is where the all-off solution parks them,
* while every other node starts at 0 V (UIC). Nothing holds GG/GN there after
* t = 0 -- .ic only sets the transient's starting point -- so whether either
* circuit leaves that state is decided by the circuit, not by the deck.
.ic v(GG)='vsup' v(GN)='vsup'
"}
C {devices/vsource.sym} 200 -200 0 0 {name=VSLOW value="pwl(0 0 't_slow' 'vsup')" savecurrent=true}
C {devices/lab_pin.sym} 200 -230 0 0 {name=vslowp lab=VDDS}
C {devices/lab_pin.sym} 200 -170 0 0 {name=vslowm lab=0}
C {devices/vsource.sym} 200 -400 0 0 {name=VFAST value="pwl(0 0 't_fast' 'vsup')" savecurrent=true}
C {devices/lab_pin.sym} 200 -430 0 0 {name=vfastp lab=VDDF}
C {devices/lab_pin.sym} 200 -370 0 0 {name=vfastm lab=0}
C {devices/vsource.sym} 200 -600 0 0 {name=VDEGN value="pwl(0 0 1n 'vsup')" savecurrent=true}
C {devices/lab_pin.sym} 200 -630 0 0 {name=vdegnp lab=VDDN}
C {devices/lab_pin.sym} 200 -570 0 0 {name=vdegnm lab=0}
C {design/bandgap_core.sym} 600 -200 0 0 {name=XSLOW}
C {devices/lab_pin.sym} 670 -200 0 0 {name=bgsout lab=VREFS}
C {devices/lab_pin.sym} 530 -200 0 0 {name=bgsgdrv lab=GS}
C {devices/lab_pin.sym} 600 -270 0 0 {name=bgsvdd lab=VDDS}
C {devices/lab_pin.sym} 600 -130 0 0 {name=bgsvss lab=0}
C {design/startup_injector.sym} 900 -200 0 0 {name=XSUS}
C {devices/lab_pin.sym} 830 -220 0 0 {name=susg lab=GS}
C {devices/lab_pin.sym} 830 -180 0 0 {name=suss lab=VREFS}
C {devices/lab_pin.sym} 900 -250 0 0 {name=susvdd lab=VDDS}
C {devices/lab_pin.sym} 900 -150 0 0 {name=susvss lab=0}
C {design/bandgap_core.sym} 600 -400 0 0 {name=XFAST}
C {devices/lab_pin.sym} 670 -400 0 0 {name=bgfout lab=VREFF}
C {devices/lab_pin.sym} 530 -400 0 0 {name=bgfgdrv lab=GF}
C {devices/lab_pin.sym} 600 -470 0 0 {name=bgfvdd lab=VDDF}
C {devices/lab_pin.sym} 600 -330 0 0 {name=bgfvss lab=0}
C {design/startup_injector.sym} 900 -400 0 0 {name=XSUF}
C {devices/lab_pin.sym} 830 -420 0 0 {name=sufg lab=GF}
C {devices/lab_pin.sym} 830 -380 0 0 {name=sufs lab=VREFF}
C {devices/lab_pin.sym} 900 -450 0 0 {name=sufvdd lab=VDDF}
C {devices/lab_pin.sym} 900 -350 0 0 {name=sufvss lab=0}
C {design/bandgap_core.sym} 600 -600 0 0 {name=XDEGN}
C {devices/lab_pin.sym} 670 -600 0 0 {name=bgnout lab=VREFN}
C {devices/lab_pin.sym} 530 -600 0 0 {name=bgngdrv lab=GN}
C {devices/lab_pin.sym} 600 -670 0 0 {name=bgnvdd lab=VDDN}
C {devices/lab_pin.sym} 600 -530 0 0 {name=bgnvss lab=0}
C {devices/vsource.sym} 200 -800 0 0 {name=VDEG value="pwl(0 0 1n 'vsup')" savecurrent=true}
C {devices/lab_pin.sym} 200 -830 0 0 {name=vdegp lab=VDDG}
C {devices/lab_pin.sym} 200 -770 0 0 {name=vdegm lab=0}
C {design/bandgap_core.sym} 600 -800 0 0 {name=XDEG}
C {devices/lab_pin.sym} 670 -800 0 0 {name=bggout lab=VREFG}
C {devices/lab_pin.sym} 530 -800 0 0 {name=bgggdrv lab=GG}
C {devices/lab_pin.sym} 600 -870 0 0 {name=bggvdd lab=VDDG}
C {devices/lab_pin.sym} 600 -730 0 0 {name=bggvss lab=0}
C {design/startup_injector.sym} 900 -800 0 0 {name=XSUG}
C {devices/lab_pin.sym} 830 -820 0 0 {name=sugg lab=GG}
C {devices/lab_pin.sym} 830 -780 0 0 {name=sugs lab=VREFG}
C {devices/lab_pin.sym} 900 -850 0 0 {name=sugvdd lab=VDDG}
C {devices/lab_pin.sym} 900 -750 0 0 {name=sugvss lab=0}
