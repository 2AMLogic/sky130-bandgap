# sky130-bandgap

A bandgap voltage reference on the [sky130](https://github.com/google/skywater-pdk)
open PDK, designed end-to-end by AI agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the open-source
xschem + ngspice analog flow.

**Status: active development.** Simulation and device characterization work
is underway, and bandgap-core layout is DRC-clean and fully routed — all 12
of 12 schematic inter-block nets joined across every block they reach,
extracted PNP/MOS/resistor devices, and 11 correctly promoted top-level
pins. `klt lvs` is not yet clean (`mismatch_count: 4` against the
xschem-derived reference netlist), but every remaining cause is disclosed
and is **not** a connectivity, topology, or routing defect: one
deliberately-undrawn device (the error amp's compensation cap, single-ended
by design since issue #15) and the routed R2A/R2B/R1 array's per-instance
head resistance, which issue #98 confirmed with independent real-SPICE
evidence is a real, material electrical effect of the layout's own folded
topology (not an LVS-extraction artifact) — ratified in
[DR-003](spec/decision-records/DR-003-res-array-head-resistance-sizing.md)
and tracked for a design-level resize by issue #99 (open); closing the LVS
comparison itself still needs an upstream `combine_devices` accounting fix,
filed as
[klayout-tools#559](https://github.com/2AMLogic/klayout-tools/issues/559)
(open); see
[`layout/README.md`](layout/README.md#routing-the-core-and-closing-on-lvs-issue-62)
for the full record. Nothing here has been taped out or measured in
silicon yet. See the maturity ladder below for where things currently
stand.

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
seat → measured silicon over temperature. Current position: mid-ladder —
bandgap-core layout is DRC-clean and fully routed but not yet LVS-clean
(two disclosed, non-topology causes remain; see Status above).

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

## History

This repo was developed privately from its first commit (2026-07-28) and
opened to the public on 2026-07-31. The full git history was kept intact
through that transition rather than squashed or rewritten, because evidence
records under `sim/*/records/` cite commit SHAs as provenance — rewriting
history would invalidate those citations.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
