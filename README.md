# sky130-bandgap

A bandgap voltage reference on the [sky130](https://github.com/google/skywater-pdk)
open PDK, designed end-to-end by AI agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the open-source
xschem + ngspice analog flow.

**Status: early-stage.** This project is in active development — simulation
and device characterization work is underway, layout has not started, and
nothing here has been taped out or measured in silicon yet. See the
maturity ladder below for where things currently stand.

**Built agent-native.** Every schematic, testbench, decision record, and
line of documentation in this repo was produced by AI agents working from
a ratified spec and an append-only evidence trail — not human-authored
work that agents merely assisted with. Verification is the product: every
claim traces to a testbench result recorded under PVT corners in `sim/`.
Where the agents hit friction with the open-source tooling — most often
[klayout-tools](https://github.com/2AMLogic/klayout-tools), the layout /
DRC / LVS driver — that friction gets filed as a public issue against the
tool itself, so the fix benefits everyone using sky130, not just this repo.

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

## Environment setup

Bootstrapping the open-source flow (xschem + ngspice + sky130 PDK via
volare) on a dev machine, plus a smoke test proving the toolchain works
end-to-end: see [`docs/environment-setup.md`](docs/environment-setup.md).

## Layout

```
spec/          ratified spec + decision records
design/        schematics / netlists (xschem)
sim/           testbenches + PVT corner results (ngspice)
layout/        GDS + DRC/LVS reports (klayout-tools driven)
measurements/  silicon characterization (empty until tape-out)
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).
