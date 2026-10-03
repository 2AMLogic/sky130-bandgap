# DR-013: Startup injector PSRR — the hot-corner remedy is not a multiplicity knob (`m_ref`, `m_pnp` screened with `MNG` attached)

- **Status**: proposed (investigation disposition, not a spec change — DR-006's
  `>= 60 dB` floor and `sim/startup-stability`'s `itrav_min >= 1e-9 A` are
  untouched and not relaxed).
- **Date**: 2026-10-03.
- **Decided by**: Loom Builder agent (issue #315), proposing per CLAUDE.md.
- **Continues**: [DR-012](DR-012-startup-injector-psrr-ng-clamp-and-stack-height-margin.md),
  whose closing section named two untried levers for the hot corner without
  stack height: an `m_ref` multiplicity change on the two-high stack, and a
  release-threshold re-tune of `MNS`/`QS`. Both are now measured.

## Measurement

Orientation runs (`run_psrr_injector_candidates.py --explore`, uncommitted
output, `ngspice-46`, same committed base snapshot and deck as the bench's
record `20261002-200944-fe334b1`). Body = shipped two-high stack + the `MNG`
clamp (DR-012's surviving device) + one knob change. `psrr_band_min`, dB:

| knob (with `MNG`) | `ff/125/3.63` | `sf/125/3.63` | `sf/-40/3.63` |
|---|---|---|---|
| none (`ngclamp`) | 40.51 | 59.36 | 68.47 |
| `m_ref = 0.5` | 46.04 | 62.10 | 68.47 |
| `m_ref = 0.25` | 51.44 | 63.77 | 68.47 |
| `m_pnp = 4` | 40.51 | 59.36 | 68.47 |
| `m_pnp = 16` | 40.51 | 59.36 | 68.47 |

- **`m_pnp` (release-threshold knob): zero effect** on PSRR, to three decimals.
  This is expected in hindsight: with the core running the `MNS`/`QS` branch is
  off and `MNG` owns `NG`, so the release threshold is simply not in the
  running-state signal path. This closes DR-012's "release-threshold re-tune"
  lever for the PSRR problem.
- **`m_ref`**: moves the right way but at ~5.4 dB per halving at the binding
  corner (`ff/125/3.63`). Extrapolating, 60 dB needs `m_ref` ~ 0.08, i.e. a
  ~12x weaker reference stack. DR-012 Part 1b measured that a 3x-weaker
  per-device overdrive alone (the three-high stack) already costs 10.6x of the
  tightest corner's eviction margin and falls below the ratified `itrav_min`
  floor; a 12x-weaker stack lands on the same side of that trade. A fractional
  `m_ref` is also not drawable as a matched device group. Not pursued to a
  45-corner record, because the binding corner alone already fails.

## Disposition

No circuit change lands; `design/startup_injector.sch` is unchanged and no
spec line moves. Together with DR-011/DR-012 the closed list for the hot corner
is now: stack height (3, 4), bulk-to-`GDRV`, `MNI` cascoding/stacking, `MNI`
resize, `m_ref` reduction, `m_pnp`/`m_sense` retune. What remains is
topological: the hot-corner residual is conduction of the reference stack
(`GDRV -> NC1 -> NC2 -> NG -> MNG -> VSS`) while the core is running, and the
reference must stay strong in the degenerate state (`GDRV = VDD`). A remedy has
to make the stack's running-state conductance small *without* weakening it in
the degenerate state — i.e. a state-dependent element. A simple series PMOS
switch gated by `VSENSE` does not do it (running `GDRV` is ~1 V below `VDD`,
~1.1 V above `VSENSE`, so it stays on); a level-shifted or `VOUT`-derived gate
is the open design question.

The certifying `sim/startup-stability` regression remains unaffordable on this
host class (DR-012 Part 1; issue #320), so any candidate arising from the open
question can again only be probed, not certified, until that is resolved.

## Evidence discipline

The table above is orientation, not evidence (three corners, uncommitted
output). The committed evidence remains
`sim/psrr-injector-candidates/records/20261002-200944-fe334b1`. The bench now
carries the knob variants (`ng_mref0p5`, `ng_mref0p25`, `ng_mpnp4`,
`ng_mpnp16`) so the table is reproducible with `--explore`; they are not in the
default `VARIANTS` set, so the committed record's `verify` path is unchanged.

## Spec lines affected

None.

## Consequences

- #315 stays open; items 1 (answered in DR-012), 2 (still open — hot corner),
  3 and 4 (blocked on a landed circuit change) are unchanged in status.
- Report rows 4b/4d/5c are not re-derived (committed design unchanged).
