#!/usr/bin/env python3
"""Orientation probe (NOT evidence): eviction-margin screen for injector candidates.

One ngspice run per invocation. Forces GDRV over alpha in [0.75, 1] (11 points)
on the core + injector instance taken from the newest sim/startup-stability
netlist snapshot, and prints the smallest signed forced current -- the same
quantity as that bench's `itrav_min` (`vecmin(ifsu[188,250])`) on a coarser
grid. A sub-window minimum can only OVER-estimate the full-window minimum, so a
value below the 1e-9 A floor is conclusive in the failing direction; a value
above it is not a pass. Certification is the full 45-corner `sim/startup-stability`
run (batch path, #320).

usage: probe_itrav.py VARIANT PROCESS TEMP_C SUPPLY_V [nodes]
  nodes   : instead of the minimum, print forced current, v(NG), v(NE), v(VREFD), v(GD)
            at 6 alpha points (0.75..1, step 0.05) -- the per-node look DR-016 uses
  VARIANT = stock | mng[_mref<x>][_h3] | mngq   (p = decimal point, e.g. mref0p42)
            mng  : add the DR-012 NG clamp (W=1 L=20 NMOS, NG -> VSS, gate VSENSE)
            mngq : same clamp with its source a PNP VBE above VSS (DR-017)
            mref : .param m_ref value;  h3 : three-high reference stack
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAP = sorted((ROOT / "sim/startup-stability/netlist-snapshots").glob("*.spice"))[-1]
LIB = Path.home() / ".volare/sky130A/libs.tech/combined/sky130.lib.spice"
MNG = ("XMNG NG VSENSE VSS VSS sky130_fd_pr__nfet_g5v0d10v5 L=20 W=1 nf=1 ad=0.29 as=0.29 "
       "pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0 m=1")


# DR-016 follow-up: same clamp, but its source sits a diode-connected PNP (VBE) above VSS, so it
# needs VSENSE > Vth + VBE before it conducts and leaves NG alone at the window edge.
MNGQ = ("XMNGQ NG VSENSE NQ VSS sky130_fd_pr__nfet_g5v0d10v5 L=20 W=1 nf=1 ad=0.29 as=0.29 "
        "pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0 m=1\n"
        "XQG VSS VSS NQ sky130_fd_pr__pnp_05v5_W0p68L0p68 m=1")


def subckts() -> str:
    lines = SNAP.read_text().splitlines()
    first = next(i for i, ln in enumerate(lines) if ln.startswith(".subckt bandgap_core"))
    last = max(i for i, ln in enumerate(lines) if ln.startswith(".ends"))
    return "\n".join(lines[first:last + 1])


def variant(name: str) -> str:
    s = subckts()
    if "mngq" in name:
        s = s.replace("XMNS NG", MNGQ + "\nXMNS NG", 1)
    elif "mng" in name:
        s = s.replace("XMNS NG", MNG + "\nXMNS NG", 1)
    if (m := re.search(r"mref([0-9p]+)", name)):
        s = s.replace(".param m_ref=1", ".param m_ref=" + m.group(1).replace("p", "."))
    if "h3" in name:
        s = s.replace("XMPC2 NG NG NC1 VDD", "XMPC2 NC2 NC2 NC1 VDD")
        mp = next(ln for ln in s.split("\n") if ln.startswith("XMPC2"))
        s = s.replace(mp, mp + "\n" + mp.replace("XMPC2 NC2 NC2 NC1", "XMPC3 NG NG NC2"), 1)
    return s


def main(name: str, proc: str, temp: str, vdd: str, mode: str = "min", pts: int = 11) -> int:
    nodes = mode == "nodes"
    deck = f"""* itrav probe {name} {proc} {temp}C {vdd}V
.param vsup={vdd}
.option wnflag=1
.temp {temp}
.lib "{LIB}" {proc}
V1 VDDA 0 'vsup'
XDUT VREFD GD VDDA 0 bandgap_core
XSU GD VREFD VDDA 0 startup_injector
VALPHA ALPHA 0 0
BSW NSW 0 V='vsup*v(ALPHA)'
VPSW GD NSW 0
{variant(name)}
.control
dc valpha 0.75 1 {0.05 if nodes else 0.25 / (pts - 1)}
let ifsu = -i(vpsw)
let m = vecmin(ifsu)
{'print ifsu v(xsu.ng) v(xsu.ne) v(vrefd) v(gd)' if nodes else 'print m'}
.endc
.end
"""
    with tempfile.TemporaryDirectory() as td:
        cir = Path(td) / "probe.cir"
        cir.write_text(deck)
        out = subprocess.run(["ngspice", "-b", str(cir)], capture_output=True, text=True,
                             timeout=1800)
    if nodes:
        print(out.stdout + out.stderr)
        return 0
    hit = re.findall(r"^m\s*=\s*(\S+)", out.stdout + out.stderr, re.M)
    print(f"{name:18s} {proc} {temp:>4s}C {vdd}V  itrav_probe = {hit[0] if hit else 'NO RESULT'} A")
    return 0 if hit else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:6]))
