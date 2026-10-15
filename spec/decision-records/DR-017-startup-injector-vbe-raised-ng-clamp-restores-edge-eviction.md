# DR-017: Startup injector — a clamp with its source one VBE above VSS keeps the window-edge eviction current that `MNG` loses

- **Status**: proposed (investigation disposition, not a spec change — DR-006's
  `>= 60 dB` floor and `sim/startup-stability`'s `itrav_min >= 1e-9 A` are
  untouched and not relaxed).
- **Date**: 2026-10-15.
- **Decided by**: Loom Builder agent (issue #315), proposing per CLAUDE.md.
- **Continues**: [DR-016](DR-016-startup-injector-mng-clamp-eviction-loss-is-ng-pull-down-at-window-edge.md),
  whose "untried and now motivated" clamp this tests.

## Candidate

`mngq`: `MNG`'s device (`W=1 L=20`, `NG` drain, gate `VSENSE`) with its source on
a diode-connected unit PNP (`m=1`, base = collector = `VSS`) instead of on
`VSS`. It needs `VSENSE > Vth_n + VBE` before it conducts, so it should leave `NG`
alone at the window edge (`VSENSE` ≈ 0.24–0.46 V) and act only once the core runs.

## Measurement (orientation, not evidence)

`sim/psrr-injector-candidates/probe_itrav.py <variant> <proc> <T> <V> nodes`,
6 alpha points, single corner, local runs. Forced current at alpha = 0.75:

| corner | stock | `+MNG` | `+MNGQ` |
|---|---|---|---|
| `tt / 27 °C / 2.97 V` | 8.96e-9 A | 1.96e-10 A | **5.54e-9 A** |
| `sf / -40 °C / 3.63 V` | 6.30e-4 A | 1.89e-11 A | **1.96e-4 A** |

`v(NG)` at alpha = 0.75: 0.402 / 0.185 / 0.375 V (tt/27) and 1.324 / 0.068 /
1.003 V (sf/-40). At alpha >= 0.80 `+MNGQ` tracks `+MNG` (e.g. sf/-40 alpha 0.85:
5.76e-4 vs 5.56e-4 A), so the clamp still acts away from the edge.

## Reading

1. DR-016's mechanism holds: moving the clamp's conduction threshold up by a VBE
   removes most of its edge-point loss (tt/27 stays above the 1e-9 A floor; `MNG`
   was 5x below it). This is the first clamp variant seen to do so.
2. Not established: the PSRR benefit (needs `sim/psrr-injector-candidates`
   across 45 corners — whether `NG` still falls low enough in the running state is
   untested), and the full-window `itrav_min` (this grid is coarse, so values
   above the floor are not a pass).

## Disposition

No circuit change lands; `design/startup_injector.sch` unchanged; no `sim/`
record added. The only code change is the `mngq` variant in the probe. The
PSRR screen and the 45-corner `sim/startup-stability` certification are a grid,
so they must go through `klt sim` (corners) to the batch fleet, not hand-run on
this dispatch host. #315 stays open; items 3–4 remain blocked on a landed circuit
change.

## Spec lines affected

None.
