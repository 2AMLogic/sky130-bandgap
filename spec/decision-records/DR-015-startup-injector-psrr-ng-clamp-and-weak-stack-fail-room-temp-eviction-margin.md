# DR-015: Startup injector PSRR — the `MNG` clamp and every weaker reference stack fail `itrav_min` at the 27 °C corners; DR-012's "3 % cost" holds only at its one probed corner

- **Status**: proposed (investigation disposition, not a spec change — DR-006's
  `>= 60 dB` floor and `sim/startup-stability`'s `itrav_min >= 1e-9 A` are
  untouched and not relaxed).
- **Date**: 2026-10-15.
- **Decided by**: Loom Builder agent (issue #315), proposing per CLAUDE.md.
- **Continues**: [DR-012](DR-012-startup-injector-psrr-ng-clamp-and-stack-height-margin.md)
  and [DR-013](DR-013-startup-injector-psrr-hot-corner-multiplicity-knobs-closed.md).
  **Corrects** one claim in DR-012 (below); supersedes nothing.

## Context

DR-012 Part 1b probed eviction margin at **one** corner, `ss / 125 °C / 2.97 V`
— the corner where the *stock* design's `itrav_min` is tightest in the
`20260909-232410-e8e2e46` record — and concluded that `MNG` "costs 3 %" there and
is therefore "the surviving device" for the next increment. DR-013 then screened
`m_ref` for PSRR only and rejected a 12x-weaker stack on an *extrapolated*
eviction argument, not a measured one. Issue #315 was re-opened for work after
#320 made the 45-corner `sim/startup-stability` regression affordable (batch
path), and its Champion note asks for item 2: a state-dependent element. Before
spending a certification run on any candidate, this increment checks the one
premise both records leaned on: that the tightest *stock* corner is also the
tightest corner for the *candidates*.

It is not.

## Measurement

Orientation probe, `sim/psrr-injector-candidates/probe_itrav.py` (new, 3 s per
point): core + injector instance from the newest `sim/startup-stability`
snapshot, GDRV forced over `alpha` in `[0.75, 1]` at 11 points, smallest signed
forced current. Same quantity as the bench's `itrav_min`
(`vecmin(ifsu[188,250])`) on a coarser grid. A sub-window minimum can only
**over**-estimate the full-window minimum, so a value below the floor is
conclusive in the failing direction; a value above it is *not* a pass. Method
check: the stock body reads 6.900e-9 A at `ss/125/2.97` against 6.774e-9 A in
the committed batch record, and 8.96e-9 A at `tt/27/2.97` against 1.10e-8 A.

`itrav_min`, A (floor `1e-9`; **bold** = below the floor):

| body | `ss/125/2.97` | `ff/27/2.97` | `tt/27/2.97` | `ss/27/3.30` | `ss/-40/2.97` |
|---|---|---|---|---|---|
| stock | 6.90e-9 | 1.25e-8 | 8.96e-9 | 9.54e-8 | 4.07e-4 |
| `+MNG` | 6.74e-9 | **3.18e-10** | **1.96e-10** | **5.45e-10** | 7.31e-5 |
| `+MNG`, `m_ref = 0.42` | 3.59e-9 | **1.48e-10** | **5.97e-11** | **1.59e-10** | — |
| `+MNG`, `m_ref = 0.25` | 2.22e-9 | **1.17e-10** | **4.04e-11** | **1.00e-10** | — |

Further `ss/125/2.97` points: `m_ref` 0.5 → 4.35e-9, 0.1 → 1.41e-9,
0.08 → 1.32e-9; three-high stack (`+MPC3`, with `MNG`) → 6.4e-10 to 6.5e-10
**independent of `m_ref`** (0.25, 0.42, 1).

## What this changes

1. **DR-012's "`MNG` costs 3 % of eviction margin" is a one-corner result and is
   wrong as a bench-level claim.** At the 27 °C corners `MNG` alone takes
   `itrav_min` from 9e-9..1e-7 A to 2e-10..5e-10 A, i.e. 40x–175x down and
   **below the ratified 1e-9 A floor**. `ss/125/2.97` was the one corner where
   the stock margin is tightest *and* `MNG`'s leak is least visible; the 27 °C
   corners are where `MNG` binds. `MNG` is therefore not "the surviving device"
   as DR-012 presented it: like `MPC3`, it cannot land as drawn.
2. **DR-013's rejection of a weaker `m_ref` is confirmed, now on measurements.**
   Its extrapolated mechanism was incomplete — at `ss/125` a 12x-weaker stack
   keeps 1.3e-9 A — but the 27 °C corners (above) fail earlier and harder, so
   the conclusion (a ~12x weaker stack is not available) stands.
3. **The weak-stack route is also not drawable.** `pfet_g5v0d10v5` is binned so
   that `L > 20 um` requires `W >= 20 um`; at `W = 1` `L = 20` is the longest
   channel, and the narrowest is `W = 0.42`. The weakest two-device diode stack
   available is therefore `m_ref ~ 0.42`, which already fails above and reaches
   only ~46 dB at the binding PSRR corner (DR-013 table, `m_ref = 0.5` ->
   46.04 dB).
4. **The three-high floor does not move with `m_ref`** (6.4e-10..6.5e-10 for
   0.25/0.42/1): it is a threshold effect at `alpha = 0.75` (`GDRV ~ 0.75 VDD`,
   ~0.74 V per device, below `|Vth_p|`), not a conduction one. This sharpens
   DR-012's "NG sags" explanation: stack height fails because the lowest-`alpha`
   end of the window drops under threshold, and no sizing of the stack repairs
   that.

## Disposition

No circuit change lands; `design/startup_injector.sch` is unchanged and no spec
line moves. The closed list for the hot corner is now: stack height (3, 4),
bulk-to-`GDRV`, `MNI` cascoding/stacking, `MNI` resize, `m_ref` reduction,
`m_pnp`/`m_sense` retune **and the `MNG` clamp itself**. The cold-corner
residual `MNG` removes (34.79 -> 68.47 dB) needs a clamp that does **not**
cost the traverse margin. The mechanism of `MNG`'s 27 °C loss is **not
identified** by this increment (a 40x-175x drop from a `W=1 L=20` device whose
gate sits at `VSENSE ~ 0` in this window is larger than its off-state leak
alone would suggest; a per-node look at `v(NG)`/`i(MNG)` across the window is
the first thing the next increment should do). Candidates for the open design
question — a clamp that is off until the core is running, and DR-013's open
question for the hot corner — are untouched here.

**What the next increment should start from**: run
`probe_itrav.py` on every candidate at `ff/27/2.97`, `tt/27/2.97` and
`ss/27/3.30` as well as `ss/125/2.97` *before* spending any PSRR or
certification compute; those three plus `ss/125/2.97` are the corners that bind
the eviction margin for the clamp-class candidates. The certification run is
`sim/startup-stability` on the batch path (#320), 45 corners.

## Evidence discipline

Everything in the table is orientation (five corners, coarse window), not
evidence; it is **not** a substitute for the 45-corner batch record. Its role is
only to falsify: the sub-floor entries are conclusive failures for the bodies
they name, because the probe over-estimates the minimum. No `sim/` record is
added or modified. The committed PSRR evidence remains
`sim/psrr-injector-candidates/records/20261002-200944-fe334b1`, whose
`ref3_ngclamp` "45/45" is a PSRR screen of a body that this record and DR-012
show cannot pass the eviction floor — quote it only with that qualifier.

## Alternatives considered

- **Certify `+MNG` on the 45-corner batch path anyway.** Rejected: the probe
  already shows a conclusive sub-floor value at three corners; the batch run
  would spend fleet compute to confirm a failure and would not close the PSRR
  row (`MNG` alone leaves 40.51 dB at the hot corner).
- **Relax `itrav_min`'s floor to admit `MNG`.** Rejected per CLAUDE.md; the
  floor backs the ratified "< 1 ms startup" row.
- **Land the probe's numbers as a new `sim/` record.** Rejected: the probe is a
  coarse sub-window by design; a record claims a grid-complete measurement.

## Spec lines affected

None.

## Consequences

- #315 stays open; items 3–4 (layout) remain blocked on a landed circuit change.
  Item 2 is still open and now has two measured-dead entries added to its
  closed list (the `MNG` clamp as drawn, and a drawable weaker stack).
- DR-012's wording "`MNG` is the surviving device" should be read as
  "`MNG` is the surviving *PSRR* device"; its eviction cost is as above.
- Report rows 4b/4d/5c are not re-derived (committed design unchanged).
