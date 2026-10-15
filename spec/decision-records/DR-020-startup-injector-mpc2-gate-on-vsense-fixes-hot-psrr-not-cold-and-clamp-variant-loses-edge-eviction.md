# DR-020: Startup injector — gating `MPC2` on `VSENSE` fixes the hot PSRR failure; no screened variant clears both gates

- **Status**: proposed (investigation disposition, not a spec change — DR-006's
  `>= 60 dB` floor and `sim/startup-stability`'s `itrav_min >= 1e-9 A` are
  untouched and not relaxed).
- **Date**: 2026-10-15.
- **Decided by**: Loom Builder agent (issue #368), proposing per CLAUDE.md.
- **Continues**: [DR-019](DR-019-startup-injector-vbe-raised-ng-clamp-fails-psrr-floor-at-2p97v.md)
  (whose "state-dependent element that lowers the reference stack's running-state
  conductance" this tries) and [DR-016](DR-016-startup-injector-mng-clamp-eviction-loss-is-ng-pull-down-at-window-edge.md)
  / [DR-018](DR-018-startup-injector-three-high-stack-alone-fails-startup-stability-at-125c.md).

## Candidate (chosen on paper)

`mpc2_vs`: `MPC2` keeps its device and size but its gate moves from `NG` (diode) to
`VSENSE`. No device is added. At the startup window edge `NC1` is ~1.3-2 V above
`VSENSE` (~0.2-0.5 V), so `MPC2` still conducts the few nA the stack must deliver; once
the core runs, `VSENSE` = VREF (~1.2 V) sits within ~0.3 V of `NC1`, `MPC2`'s |Vgs|
collapses and the stack current — hence its conductance on `GDRV` — falls exponentially.

Dropped on paper/orientation before this (single corner, local, 3-4 corners each,
orientation not evidence; `ff/125/3.63` base 24.78 dB): a series resistor `GDRV` ->
`MPC1` (1/3/10 MOhm: 24.9/25.2/26.1 dB, linear drop vs an exponential problem), and a
series PMOS gated on `VSENSE` (`XMSW`, L=20/5: 25.0/24.8 dB — its |Vgs| = `GDRV` - VREF
stays ~1.1 V, so it never throttles). `mpc12_vs` (both stack devices on `VSENSE`) gives
15.5 dB at `ff/125/3.63`: worse.

## Measurement

`sim/psrr-injector-candidates --explore --backend batch --batch-hosts 3`, variants
`mpc2_vs,mpc2_vs_mng` (`mpc2_vs` + the DR-012 `MNG` clamp), requested over all 45
corners. Explore mode writes nothing under `sim/`. The fleet was at its
`BATCH_MAX_CONCURRENT_INSTANCES=8` cap (8-12 instances already running), so only the
**2.97 V** requests (15 corners) were admitted for `mpc2_vs`; every 3.30 V / 3.63 V
request came back `lost_shard` (launch refused, **no local fallback was run**), and
`mpc2_vs_mng` lost a further five 2.97 V corners (all `fs`, `sf/27`, `sf/125`).

`psrr_band_min` at 2.97 V (dB; base for reference from DR-019 / local orientation):

| corner | `mpc2_vs` | `mpc2_vs_mng` |
|---|---|---|
| `sf/27` | **49.36** FAIL | 67.90 (local) |
| `sf/-40` | **57.69** FAIL | 67.50 |
| `ff/27` | **57.62** FAIL | 67.94 |
| `tt/27` | 64.61 | 68.02 |
| `ff/-40` | 65.38 | 67.56 |
| `tt/-40`, `fs/*`, `ss/*`, `tt/125`, `ff/125`, `sf/125` | 67.1 – 72.8 (all pass) | 67.6 – 72.7 (all measured pass) |

Hot corner, local orientation: `ff/125/3.63` 24.78 -> **67.13** dB (base -> `mpc2_vs`);
`sf/-40/3.63` 34.8 -> 41.7 (still FAIL). `ng` for `mpc2_vs` is 0.28-0.48 V at the cold /
room corners (the `QS` VBE floor), ~0 at 125 C.

Window-edge eviction (`probe_itrav.py`, coarse grid, orientation; a sub-window minimum
can only over-estimate `itrav_min`, so a value below 1e-9 A is conclusive):

| corner | stock = `mpc2_vs` | `mpc2_vs_mng` |
|---|---|---|
| `tt/27/2.97` | 5.39e-8 A | **2.2e-11 A** FAIL |
| `ss/125/3.63` | 9.99e-10 A | 9.97e-10 A (both at/below the floor on this coarse grid) |
| `ff/125/2.97` | 2.68e-9 A | 2.68e-9 A |

## Reading

1. `mpc2_vs` keeps eviction identical to stock (the probe is bit-identical) and removes
   the hot-corner stack conductance (24.8 -> 67 dB at `ff/125/3.63`, 125 C corners all
   65-73 dB) at zero device cost and without `ref3`'s DR-018 drive loss. It is the first
   candidate to do both, but it is **not sufficient**: three 2.97 V corners (`sf/27`,
   `sf/-40`, `ff/27`) stay under 60 dB, because the residual there is `MNI` conducting
   at `NG` = 0.28-0.48 V, not the stack.
2. Closing that residual needs `NG` pulled to ~0 in the running state, which the plain
   `MNG` clamp does (`mpc2_vs_mng`: 67.5 - 72.7 dB on every measured corner) — but DR-016's
   edge mechanism returns: `tt/27/2.97` eviction falls to 2.2e-11 A, 45x under the floor.
   The VBE-raised `MNGQ` variant (`mpc2_vs_mngq`, local orientation) keeps edge drive but
   again floors `NG` at a VBE: 55.5 / 51.6 / 63.3 dB at `sf/27/2.97`, `sf/-40/3.63`,
   `ff/27/2.97`.
3. So the pair of requirements is still: `NG` ~ 0 at 27 C / -40 C when running, and
   `NG` untouched at the window edge, both from a gate whose swing (`VSENSE` 0.3 -> 1.2 V)
   is only ~0.9 V against a ~0.7 V threshold plus a VBE floor. No variant with one
   element and `VSENSE` as its only state input has satisfied both.
4. Not measured: all 3.30 V / 3.63 V corners for both variants (fleet cap), and the
   45-corner `sim/startup-stability` run. It is not submitted for either variant: the
   PSRR gate already fails for `mpc2_vs` at 2.97 V, and the eviction probe already fails
   for `mpc2_vs_mng`, so a certification run cannot turn either into a pass.

## Disposition

No circuit change lands; `design/startup_injector.sch` unchanged; no `sim/` record is
added. Code changes: the variants above in `run_psrr_injector_candidates.py` (with a
netlist test) and an `mpc2vs` token in `probe_itrav.py`. The remaining question —
accept a different startup architecture (e.g. a second state signal, a replica-bias
reference), or a spec ruling on the DC-1 kHz PSRR floor at the injector's cold corners —
is a human decision and is escalated via `operator-decision` on #368; the floor is not
relaxed here.

## Alternatives considered

- **Certify `mpc2_vs_mng` anyway** — rejected: eviction fails by the probe at `tt/27`.
- **Re-run the 3.30/3.63 V requests locally** — rejected: batch submit failures are
  reported, not re-run locally (host rules).

## Spec lines affected

None.
