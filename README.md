# sky130-bandgap

**PRIVATE — 2AM Logic proprietary IP. Canary block (wave 1).**

Bandgap voltage reference on sky130 (open PDK), designed by agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the
open-source analog flow. Dual purpose, per the canary model: catalog
inventory (eventually silicon-measured) and tool forcing-function
(friction issues go to the public klayout-tools tracker).

Selection rationale: First cross-node port ('every PDK' proof); free sky130 version exists but is sim-only — silicon-measured tier differentiates cheaply (matrix row 5).

## Target specification (DRAFT — engineering to ratify, see issue #1)

| Parameter | Target | Stretch |
|---|---|---|
| Output reference | 1.20 V ±1% untrimmed (3.3 V I/O devices) | ±0.5% with trim; sub-1V Banba variant on 1.8 V core |
| Temp coefficient (−40…125 °C) | < 50 ppm/°C | < 20 ppm/°C |
| PSRR @ DC | > 60 dB | > 70 dB |
| Supply | 3.3 V ±10% | 1.8 V variant |
| Iq | < 50 µA | < 20 µA |
| Area | < 0.05 mm² | — |
| Startup | self-starting, < 1 ms | — |

Port parity note: spec mirrors gf180-bandgap deliberately — same block,
two PDKs is the portability proof.

Maturity ladder: simulation-complete → layout DRC/LVS-clean → shuttle
seat → measured silicon over temperature.

## Layout

```
spec/          ratified spec + decision records
design/        schematics / netlists (xschem)
sim/           testbenches + PVT corner results (ngspice)
layout/        GDS + DRC/LVS reports (klayout-tools driven)
measurements/  silicon characterization (empty until tape-out)
```
