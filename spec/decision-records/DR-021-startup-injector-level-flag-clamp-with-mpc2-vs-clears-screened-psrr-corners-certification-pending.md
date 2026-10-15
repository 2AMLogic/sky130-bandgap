# DR-021: Startup injector — a rail-to-rail level flag gating an `NG` clamp, with `MPC2` on `VSENSE`, clears every PSRR corner measured so far; certification pending

- **Status**: proposed (design candidate, **not certified** — 3.30 V / 3.63 V batch coverage and
  `sim/startup-stability` 45/45 are outstanding; DR-006's `>= 60 dB` floor and
  `itrav_min >= 1e-9 A` are untouched and not relaxed).
- **Date**: 2026-10-15.
- **Decided by**: Loom Builder agent (issue #368), proposing per CLAUDE.md, under the operator
  ruling on #368 (bounded exploration of a two-state-signal startup architecture).
- **Continues**: [DR-020](DR-020-startup-injector-mpc2-gate-on-vsense-fixes-hot-psrr-not-cold-and-clamp-variant-loses-edge-eviction.md).

## Candidate (chosen on paper): `mpc2_vs_flag`

DR-020 ends with: every one-signal design needs `NG` ~ 0 when running **and** `NG` untouched at
the window edge, from a gate (`VSENSE`, 0.3 -> 1.2 V) whose swing is too small against a ~0.7 V
threshold plus a VBE floor. The second state signal here is a **restored level flag** derived
from `VSENSE`, not a second analog node:

- `XMFL` (W=1 L=20 PMOS, gate `VSS`, always on) loads `XMFI` (W=1 L=0.5 NMOS, gate `VSENSE`):
  a ratioed inverter `FL` that trips near one threshold of `VSENSE`.
- `XMFP`/`XMFN` (W=1 L=0.5) restore `FL` to `FH`: 0 V in the startup window, `VDD` once the
  core runs.
- `XMNF` (W=1 L=20 NMOS, `NG` -> `VSS`) is gated by `FH`.
- `MPC2` keeps DR-020's `VSENSE` gate (`mpc2_vs`), which removes the hot-corner stack
  conductance (`ff/125/3.63` 24.8 -> 67 dB). Without it, `flag_mng` alone gives 40.3 dB there.

Failure modes, by name:

| DR | failure | why this avoids it |
|---|---|---|
| DR-015 | room-temp eviction margin lost to an `NG` clamp | `XMNF`'s gate is `FH` = 0 V (not a `VSENSE` ~0.3-0.5 V subthreshold gate) until `VSENSE` crosses the inverter trip, above the window edge |
| DR-016 | `NG` pull-down at the window edge | same; plus `L=20` on `XMNF` — at `L=2` its off-state leakage alone took `tt/27/2.97` to 1.9e-10 A (measured), at `L=20` it is 4.07e-9 A |
| DR-017/019 | `MNI` conducts at `NG` = a VBE at 27 C / -40 C | `FH` = `VDD` drives `XMNF` hard on, so `NG` ~ 0 V (`ng` column below), no VBE-raised source |
| DR-018 | three-high stack fails `startup-stability` at 125 C | the stack is unchanged (two-high) |
| DR-020 | one-signal `VSENSE` gate floors `NG` at a VBE; a `VSENSE`-gated clamp costs edge eviction | clamp gate is a full-swing flag, not `VSENSE` |

## Measurement (so far)

Eviction (`probe_itrav.py`, orientation; coarse grid can only over-estimate, floor 1e-9 A):

| corner | `flagvs` (this candidate) |
|---|---|
| `tt/27/2.97` | 4.07e-9 A |
| `ss/125/3.63` | 2.65e-7 A |
| `ff/125/2.97` | 5.22e-8 A |
| `ss/125/2.97` | 1.90e-9 A |

PSRR `psrr_band_min` (dB), `--explore --backend batch --batch-hosts 3`, all 45 corners requested:
**2.97 V, measured: `ff/-40` 67.56, `ff/125` 68.10, `ff/27` 67.94, `sf/-40` 67.50, `ss/-40` 70.02,
`ss/125` 72.66, `ss/27` 71.15, `tt/-40` 67.62, `tt/125` 68.42, `tt/27` 68.02** — every one >= 60 dB,
including DR-020 failers `ff/27` and `sf/-40` (`sf/27`, also a DR-020 failer, is unmeasured by batch: 67.90 locally). `v(NG)` is 0.0000 V at all
of them.

Local single-corner orientation (not evidence): `ff/125/3.63` 67.07, `sf/27/2.97` 67.90,
`sf/-40/3.63` 68.47, `sf/27/3.63` 68.68, `ff/27/3.63` 68.58, `ss/-40/3.63` 72.73.

## Not measured (why this is not a pass)

The Spot batch fleet was at `BATCH_MAX_CONCURRENT_INSTANCES=8` (8-13 instances already running):
65 requests came back `lost_shard`, i.e. **every 3.30 V and 3.63 V corner and the remaining 2.97 V
corners (`fs/*`, `sf/27`, `sf/125`) are unmeasured by the batch path**. No local grid was run. Also
not run: `sim/startup-stability --backend batch` (45/45) and the standing supply current of the
inverter pair. Per the issue's acceptance criteria this DR therefore does **not** claim a pass and
no `sim/` record is written.

## Disposition

No circuit change lands; `design/startup_injector.sch` unchanged; no `sim/` record. Next (needs
fleet capacity): the 45-corner `--backend batch` run for `mpc2_vs_flag`, then
`sim/startup-stability --backend batch` for the same netlist, then record and hand to #315. At
most one revision remains if either fails (the inverter trip point is the knob). The spec is not
relaxed.

## Alternatives considered

- **`flag_mng` alone** (no `MPC2` rewire): 40.3 dB at `ff/125/3.63` — the stack, not `NG`, dominates.
- **`XMNF` at `L=2`**: off-state leakage fails `tt/27/2.97` eviction (1.9e-10 A).
- **Re-run the unmeasured corners locally** — rejected (host rules: no local grids).

## Spec lines affected

None.
