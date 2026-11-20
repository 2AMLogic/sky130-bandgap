# DR-022: Startup injector — a level-flag `NG` clamp with `MPC2` on `VSENSE` clears PSRR at all 45 corners but fails `startup-stability` on standing current; the one allowed revision loses window-edge eviction

- **Status**: proposed, **both candidates fail a gate** (not certified, not adopted). DR-006's `>= 60 dB`
  floor and `itrav_min >= 1e-9 A` are untouched and not relaxed. The spec question goes to a
  human via `operator-decision` on #368.
- **Date**: 2026-11-13 (re-measured under open_pdks `f6eeac7`; the 2026-10-15 numbers were taken
  under the old pin and are superseded, not mixed in).
- **Decided by**: Loom Builder agent (issue #368), proposing per CLAUDE.md, under the operator
  ruling on #368 (bounded exploration of a two-state-signal startup architecture).
- **Continues**: [DR-020](DR-020-startup-injector-mpc2-gate-on-vsense-fixes-hot-psrr-not-cold-and-clamp-variant-loses-edge-eviction.md).

## Candidate (chosen on paper): `mpc2_vs_flag`

`mpc2_vs_rsw` (local-only, never pushed) is dropped and contributes no evidence here.

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

## Measurement (all under open_pdks `f6eeac7`)

Eviction (`probe_itrav.py`, orientation; coarse grid can only over-estimate, floor 1e-9 A), `flagvs`:
`tt/27/2.97` 4.07e-9 A, `ss/125/3.63` 2.65e-7 A, `ff/125/2.97` 5.22e-8 A, `ss/125/2.97` 1.90e-9 A
— all >= 1e-9 A.

PSRR `psrr_band_min`, `--explore --backend batch --batch-hosts 3`, **all 45 corners including 3.30 V
and 3.63 V, all measured**: minimum **65.64 dB** (`sf/125/3.63`), then 66.48 (`sf/125/3.30`) and
67.07; every corner >= 60 dB; `v(NG)` 0.0000 V throughout. Explore mode writes no record, so this
row is orientation, not a `sim/` record. **The PSRR gate passes.**

`sim/startup-stability --backend batch` with the candidate's five devices and the `MPC2` rewire
applied to `design/startup_injector.sch` (reverted afterwards; the snapshot is the evidence):
record `sim/startup-stability/records/20261113-082144-99138c6.md`, `Supersedes:
20261111-234331-ebc9a64b`. **`Overall: FAIL`.**

- 31 corners measured, **all 31 FAIL**; 14 corners lost to `batch_no_capacity` (fleet at its vCPU
  budget after the 600 s wait) are unmeasured and count as not measured.
- Every measured failure is the **standing current**: `i_su_standing` 2.0-5.9 uA against the
  `<= 0.2 uA` limit, and `i_standing` 3.2-5.9 uA against `<= 1 uA`. The always-on load `XMFL`
  conducts through `XMFI` once `VSENSE` is up, so the flag costs a `VDD` -> `VSS` current the
  budget does not allow. Single-equilibrium (`ncross_su = 1`), `itrav_min` and the `imin_off`
  limits all hold at the measured corners.
- `fs/125/3.63` additionally reads `dvref = -2.32 V`; its bare control sits in the railed state
  (`ncross_bare = 3`), so it is a control-instance artefact to be re-checked, not a candidate
  result.

## The one allowed revision: `mpc2_vs_flaglatch`

The load `XMFL` gate moves from `VSS` to `FH`: once the core runs `FH` = `VDD` turns the load off,
so the standing current is leakage only. Single-corner local runs (allowed; the batch fleet was at
cap), records `20261113-083451-99138c6` (`tt/27/2.97`) and `20261113-083501-99138c6`
(`fs/125/3.63`):

| corner | `i_su_standing` | `itrav_min` |
|---|---|---|
| `tt/27/2.97` | 2.6e-11 A (fixed) | **1.28e-11 A (floor 1e-9 A) — FAIL** |
| `fs/125/3.63` | 4.9e-10 A (fixed) | 6.1e-8 A |

The latch fixes the standing current but gives up window-edge eviction at `tt/27/2.97` by about
two orders of magnitude, the same failure class as DR-015/DR-020: the latched feedback holds `FL`
against the pull the window edge needs. The `fs/125/3.63` `dvref` reading is unchanged. No further
revision is allowed by the issue, so no 45-corner run of the revision was spent.

## Disposition

Neither `mpc2_vs_flag` (fails `startup-stability` standing current) nor `mpc2_vs_flaglatch`
(fails window-edge eviction) clears both gates. `design/startup_injector.sch` is unchanged. Per
the ruling on #368 the question returns to a human through `operator-decision`: no
repository-owned variant clears DR-006 at every corner, the candidate that clears PSRR everywhere
costs 2-6 uA of standing current against a 0.2 uA budget, and relaxing either number is a spec
change agents may not make.

## Alternatives considered

- **`flag_mng` alone** (no `MPC2` rewire): 40.3 dB at `ff/125/3.63` — the stack, not `NG`, dominates.
- **`XMNF` at `L=2`**: off-state leakage fails `tt/27/2.97` eviction (1.9e-10 A).
- **Re-run the lost corners locally** — rejected (host rules: no local grids).

## Spec lines affected

None.
