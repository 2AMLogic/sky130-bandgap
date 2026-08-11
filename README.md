# sky130-bandgap

A bandgap voltage reference on the [sky130](https://github.com/google/skywater-pdk)
open PDK, designed end-to-end by AI agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the open-source
xschem + ngspice analog flow.

**Status: active development.** Simulation and device characterization work
is underway, and bandgap-core layout is DRC-clean and fully routed — all 12
of 12 schematic inter-block nets joined across every block they reach,
extracted PNP/MOS/resistor devices, and 11 correctly promoted top-level
pins. `klt lvs` is not yet clean (`mismatch_count: 1` against the
xschem-derived reference netlist), but the one remaining cause is disclosed
and is **not** a connectivity, topology, or routing defect: a single
deliberately-undrawn device, the error amp's compensation cap, single-ended
by design since issue #15. The routed R2A/R2B/R1 array's per-instance head
resistance — which issue #98 confirmed with independent real-SPICE evidence
is a real, material electrical effect of the layout's own folded topology,
not an LVS-extraction artifact, ratified in
[DR-003](spec/decision-records/DR-003-res-array-head-resistance-sizing.md) —
was closed by issue #99's `n_r2` 54 → 50 resize plus issue #108's
chained-value `reference.spice` convention. An upstream `combine_devices`
correction
([klayout-tools#559](https://github.com/2AMLogic/klayout-tools/issues/559),
closed via [#583](https://github.com/2AMLogic/klayout-tools/pull/583)/[#587](https://github.com/2AMLogic/klayout-tools/pull/587))
_would_ make `klt lvs` re-report those resistors at the single-device value
instead; it is picked up in the pinned `klt` build and measured under all
four accounting variants, and deliberately **not** adopted — doing so takes
`mismatch_count` back from 1 to 4 and would state a resistance the fabricated
cell does not have. See
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

## Target specification (ratified — see [DR-005](spec/decision-records/DR-005-ratify-target-spec.md), issue #1)

| Parameter | Target | Stretch |
|---|---|---|
| Output reference | 1.20 V ±2% untrimmed (3σ, mismatch MC N≥300 + process corners, −40…125 °C) | ±0.5% trimmed (3σ, 1-point trim) |
| Trim | 1-point resistor trim (binary-weighted segments, `res_high_po`), range ≥ ±5%, resolution ≤ 0.25%/step (≥5 bits equiv.), magnitude only, at 27 °C | — |
| Temp coefficient (−40…125 °C) | < 50 ppm/°C (box method) | < 20 ppm/°C (curvature correction) |
| PSRR @ DC | > 60 dB | > 70 dB |
| Supply | 3.3 V ±10% | 1.8 V-core Banba variant |
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

Operating the AI agent fleet against this repo — in particular keeping a
dispatch host's checkout current so agents do not run stale role
definitions: see
[`docs/loom-agent-host-hygiene.md`](docs/loom-agent-host-hygiene.md).

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
