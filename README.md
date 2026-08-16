# sky130-bandgap

A bandgap voltage reference on the [sky130](https://github.com/google/skywater-pdk)
open PDK, designed end-to-end by AI agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the open-source
xschem + ngspice analog flow.

**Status: active development.** Simulation and device characterization work
is underway, and bandgap-core layout is DRC-clean and fully routed — all 12
of 12 schematic inter-block nets joined across every block they reach,
extracted PNP/MOS/resistor devices, and 11 correctly promoted top-level
pins. As of issue #62's thirty-first increment, `klt lvs` itself reports
**`mismatch_count: 0`** against the xschem-derived reference netlist — the
error amp's compensation cap (`MCC`) is now drawn as the `pfet`
MOS-as-capacitor device `design/error_amp.sch` specifies, matching the
reference netlist's own `MMCC` device exactly. A `cap_mim` MIM-cap overlay
(the zero-incremental-footprint alternative) was checked and found
infeasible on two independent grounds — see
[`layout/README.md`](layout/README.md#routing-the-core-and-closing-on-lvs-issue-62)
and `layout/matching-plan.md` Sections 7bb/7cc. Drawing `MCC` pushes the
composed cell to 73,989 µm²; the Area budget was relaxed from 50,000 µm² to
80,000 µm² (`< 0.08 mm²`) to accommodate the now-measured drawn figure,
ratified in
[DR-007](spec/decision-records/DR-007-mcc-area-budget.md) (operator, issue
#62) — the composed cell is now within budget. The routed R2A/R2B/R1 array's per-instance head
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
four accounting variants, and deliberately **not** adopted — doing so would
regress `mismatch_count` and would state a resistance the fabricated
cell does not have. See
[`layout/README.md`](layout/README.md#routing-the-core-and-closing-on-lvs-issue-62)
for the full record. **Known gaps, disclosed here rather than only in the
maturity ladder below**: two of the seven ratified spec rows currently fail
at every corner on the freshest evidence — box-method temperature
coefficient (191–268 ppm/°C measured, schematic and post-layout alike,
against the ratified `< 50 ppm/°C` target) and untrimmed output accuracy
(`vref` falls outside the ratified ±2% window over temperature, down to
~1.130 V at hot corners) — tracked in #178. Separately, the sole Monte
Carlo run on file predates both the ratified spec and the current design's
error-amp resize, so the statistical evidence for the dominant accuracy
term is stale (#180). Nothing here has been taped out or measured in
silicon yet. See the maturity ladder below for where things currently
stand, and issue #175's ten-item T1/bronze checklist re-read (5/10 pass as
of 2026-08-15) for the full evidence-tier accounting.

**Built agent-native.** Every schematic, testbench, decision record, and
line of documentation in this repo was produced by AI agents working from
a ratified spec and an append-only evidence trail — not human-authored
work that agents merely assisted with. Verification is the product: every
claim traces to a testbench result recorded under PVT corners in `sim/`.
Where the agents hit friction with the open-source tooling — most often
[klayout-tools](https://github.com/2AMLogic/klayout-tools), the layout /
DRC / LVS driver — that friction gets filed as a public issue against the
tool itself, so the fix benefits everyone using sky130, not just this repo.

## Target specification (ratified — see [DR-005](spec/decision-records/DR-005-ratify-target-spec.md), issue #1; PSRR row amended by [DR-006](spec/decision-records/DR-006-psrr-frequency-qualification.md), issue #123)

| Parameter | Target | Stretch |
|---|---|---|
| Output reference | 1.20 V ±2% untrimmed (3σ, mismatch MC N≥300 + process corners, −40…125 °C) | ±0.5% trimmed (3σ, 1-point trim) |
| Trim | 1-point resistor trim (binary-weighted segments, `res_high_po`), range ≥ ±5%, resolution ≤ 0.25%/step (≥5 bits equiv.), magnitude only, at 27 °C | — |
| Temp coefficient (−40…125 °C) | < 50 ppm/°C (box method) | < 20 ppm/°C (curvature correction) |
| PSRR | > 60 dB DC–1 kHz | > 30 dB @ 1 MHz |
| Supply | 3.3 V ±10% | 1.8 V-core Banba variant |
| Iq | < 50 µA | < 20 µA |
| Area | < 0.08 mm² (DR-007; relaxed from 0.05 to fit the drawn `MCC` cap) | — |
| Startup | self-starting, < 1 ms | — |

Port parity note: spec mirrors gf180-bandgap deliberately — same block,
two PDKs is the portability proof. The PSRR row is stated in the same
frequency-qualified form gf180-bandgap uses (`> 60 dB DC–1 kHz` target,
`> 30 dB @ 1 MHz` stretch) as of DR-006 — closing the one deferred
port-parity gap DR-005 flagged.

Maturity ladder: simulation-complete → layout DRC/LVS-clean → shuttle
seat → measured silicon over temperature. Current position: mid-ladder —
bandgap-core layout is DRC-clean, fully routed, and `klt lvs`-clean
(`mismatch_count: 0`), and the composed cell is within the Area budget
relaxed to `< 0.08 mm²` by [DR-007](spec/decision-records/DR-007-mcc-area-budget.md)
(operator-ratified) — a **layout-complete** block. It is **not** currently
spec-conformant: two of the seven ratified spec rows fail at every corner
on the freshest evidence — box-method temp coefficient measures
250–268 ppm/°C on the schematic and 191–209 ppm/°C on the extracted
post-layout netlist, against the ratified `< 50 ppm/°C` target, and
untrimmed `vref` falls outside the ratified ±2% window over temperature
(down to ~1.130 V at hot corners); the remaining five ratified rows
(PSRR, supply, Iq, area, startup) pass on the same-day reruns. See
`sim/output-voltage-tc/records/20260815-030801-001d1b7.md` and
`sim/output-voltage-tc-post-layout/records/20260815-035841-001d1b7.md`
for the measured numbers; tracked in #178. Post-layout extraction itself is
no longer pending — seven `sim/*-post-layout/` suites (line-regulation,
output-voltage-tc, psrr-dc, quiescent-current, startup-ramp,
startup-stability, startup-time) are committed with 2026-08-15 records.
What remains: closing the TC/accuracy gap (#178), refreshing the stale
Monte Carlo statistical evidence (#180), and the operator tier award.
Issue #175's ten-item T1/bronze checklist re-read puts the block at
**5/10 pass** (design sources, layout, DRC, LVS, testbenches), with items
5 (PVT vs. ratified spec), 6 (Monte Carlo), and 8 (block-level
characterization report) blocking — no bronze/T1 claim is made here.

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
