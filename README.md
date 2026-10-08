# sky130-bandgap

A bandgap voltage reference on the [sky130](https://github.com/google/skywater-pdk)
open PDK, designed end-to-end by AI agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the open-source
xschem + ngspice analog flow.

![fleet burndown](https://raw.githubusercontent.com/2AMLogic/2am/main/fleet-metrics/charts/sky130-bandgap.svg)

**Status: active development, not spec-conformant.** Bandgap-core layout is
DRC-clean, fully routed, and `klt lvs` reports **`mismatch_count: 0`** (22/22
devices matched; the composed cell is 70,360 µm², inside the `< 0.08 mm²`
budget of [DR-007](spec/decision-records/DR-007-mcc-area-budget.md)). Nothing
here has been taped out or measured in silicon. Ladder: simulation-complete →
layout DRC/LVS-clean → shuttle seat → measured silicon over temperature;
current position is mid-ladder, a **layout-complete** block with disclosed
spec failures. The verdicts below are copied from
[`design/block-characterization-report.md`](design/block-characterization-report.md)
(section 2 is the row-by-row record; read it, not this table, for numbers and
binding corners). The report is a dated snapshot; the newest `sim/*/records/`
entry is authoritative for its own claim.

| Spec row | Verdict | Where |
|---|---|---|
| Output reference, ±2% untrimmed | Schematic **PASS 45/45**; mismatch MC **PASS** (79–96% yield inside the window, N=300); post-layout **FAIL 14/15** (`vref_min` below 1.176 V; open upstream klayout-tools#2359, not confirmed as a design defect) | report rows 1a–1c |
| Trim | **STALE** — no evidence against the current ratified design | report row 2 |
| Temp coefficient, `< 50 ppm/°C` | **FAIL at every corner** — 142–159 ppm/°C schematic, 90–186 ppm/°C post-layout; disposition (keep the row, disclose the FAIL, defer curvature correction) in [DR-009](spec/decision-records/DR-009-tc-floor-disposition-defer-curvature-correction.md) | report rows 3a–3b |
| PSRR, `> 60 dB` DC–1 kHz | Schematic **PASS 45/45**; post-layout **FAIL 25/45** since the startup injector was drawn in (worst 22.75 dB); resize cannot fix it, [DR-011](spec/decision-records/DR-011-startup-injector-psrr-fix-infeasible-by-resize.md), issues #300/#315 | report rows 4a–4f |
| Supply, 3.3 V ±10% | **PASS** (operability; line regulation PASS, post-layout margin eroded by the injector) | report rows 5–5c |
| Iq, `< 50 µA` | **PASS 45/45** schematic and post-layout (the `< 20 µA` stretch is not met) | report rows 6a–6c |
| Area, `< 0.08 mm²` | **PASS** (70,360 µm²) | report row 7 |
| Startup, self-starting `< 1 ms` | **MIXED** — self-starting **PASS** (schematic 45/45, post-layout 8/8); the ratified `t_start < 1 ms` measurement passes everywhere, but the startup-ramp `vref` spread check **FAILS 13/45** schematic and post-layout ([DR-010](spec/decision-records/DR-010-startup-ramp-vref-spread-settling-tail.md)); the bare-core startup-time bench fails by construction | report rows 8a–8e |

LVS determinism, the `combine_devices` resistor accounting, the `MCC` cap and
the pinned `klt` build are explained in
[`layout/README.md`](layout/README.md#routing-the-core-and-closing-on-lvs-issue-62)
and `layout/matching-plan.md` (Sections 7bb/7cc/7ff); the `klt` pin is
deliberately not bumped past the nondeterministic combine step
([klayout-tools#2374](https://github.com/2AMLogic/klayout-tools/issues/2374)).
What remains: curvature correction (the TC row stays a disclosed FAIL until it
lands), the injector PSRR fix, the trim-network evidence refresh, and the
operator tier award.

**The T1/bronze checklist state is graded, not hand-read**:
[`signoff/README.md`](signoff/README.md) — this block's machine-graded
gap-to-T1 tracker, an eleven-row `klt signoff --manifest` verdict — is the
current verdict of record (today: **3/11 T1 items graded `met`**; see that
file's row-by-row table for why each remaining row is `unmet` and what would
close it) — no bronze/T1 claim is made here.

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

## Environment setup

Bootstrapping the open-source flow (xschem + ngspice + sky130 PDK via
volare) on a dev machine, plus a smoke test proving the toolchain works
end-to-end: see [`docs/environment-setup.md`](docs/environment-setup.md).

Operating the AI agent fleet against this repo — in particular keeping a
dispatch host's checkout current so agents do not run stale role
definitions: see
the fleet's private operations runbooks (the host-hygiene note that used to live here was moved out on 2026-08-21 — it is about the dispatch hosts, not this design).

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
