# `line-regulation-post-layout` — divergence check (PASS, huge margin)

Post-layout (`provenance: extracted`) re-run of `sim/line-regulation`'s
large-signal DC line-regulation claim against the routed, LVS-clean
`layout/bandgap-core/` GDS (issue #62), for issue #16. Records here are
append-only and are **new** evidence — they neither overwrite nor retire
`sim/line-regulation/`'s schematic-level records.

This file exists because issue #16 requires documenting any divergence from
the schematic-level result as a finding, not reconciling it away — even when,
as here, the verdict does not change. Unlike `psrr-dc-post-layout` (a real
spec-line FAIL), this record is `Overall: PASS` at both levels, with a
~750x margin to the limit, so this write-up is deliberately short: there is
a measured delta worth recording, but it does not threaten the spec line and
does not present a clean single-cause story the way the Iq or PSRR findings
did.

## What the record says

Record `20260812-015312-9a2360a` — 15-point subset (process x temperature in
full, supply axis collapsed to nominal 3.30 V — the deck itself sweeps
2.97 .. 3.63 V internally via `dc v1 2.97 3.63 0.022`, so the outer supply
axis's other two points would just rerun the identical in-deck sweep; this
is `sim/line-regulation`'s own established subset, reused unchanged), `Overall: PASS`, 15/15.

| Quantity | Post-layout (extracted) | Limit | Verdict |
|---|---|---|---|
| `line_shift_mv` | 0.0109 … 0.0318 mV | ≤ 24 mV | pass, 15/15, ~755x margin at the worst corner |
| `line_psrr_db` (informational) | 86.35 … 95.65 dB | none enforced | n/a |
| `vref_nom` | 1.167 … 1.204 V | 1.14 … 1.26 V | pass |
| `sweep_start_v` / `sweep_end_v` / `n_supply_points` (guards) | 2.97 V / 3.63 V / 31 | in-window | pass, 15/15 |
| `vref_nom` spread check | 0.0366 V observed | ≥ 0.005 V | pass |
| `line_shift_mv` spread check | 0.0209 mV observed | ≥ 0.005 mV | pass |

## The divergence

Closest schematic-level reference: `sim/line-regulation/records/20260803-123439-497b50f`
(same bench, same manifest, same measurement expressions, same 15-point subset).

Per-corner `line_shift_mv` delta (post-layout minus schematic, same 15 corner
IDs in both records): mean **+0.0047 mV**, population stdev **0.0084 mV**,
range **−0.0192 … +0.0146 mV**. Unlike `quiescent-current-post-layout`'s Iq
delta (tightly clustered, one consistent sign) or `psrr-dc-post-layout`'s
`psrr_1k` delta (tightly clustered, one consistent sign), this delta is
**not** a clean scale factor: 3 of 15 corners (`tt_125c`, `ff_125c`,
`sf_125c` — all at 125 °C) move the *opposite* direction from the other 12.
That mixed-sign pattern, combined with the absolute magnitudes involved
(tens of microvolts, the same scale the manifest's own notes document as
being at the edge of what even the tightened `reltol=1e-6`/`vntol=1e-9`/
`abstol=1e-15` solver tolerances resolve cleanly — see
`sim/line-regulation/experiment.json`'s notes on the bench's first run being
dominated by convergence noise at ngspice's default tolerances), is
consistent with this delta being dominated by solver-resolution-scale
variation rather than a single physical mechanism. No further attribution is
claimed here — see Known gaps.

`line_psrr_db` (informational, no enforced limit) moves more clearly:
mean delta **−2.06 dB**, population stdev **3.94 dB**, 11 of 15 corners
degrade. The direction (post-layout supply rejection worse than schematic)
and rough order of magnitude are **consistent with**
`psrr-dc-post-layout`'s `psrr_1k` finding (a tight **−4.05 dB** mean across
all 45 corners, attributed there to the extraction's star-R parasitic
network lowering loop gain via the same R1/R2 resistance inflation
`quiescent-current-post-layout` characterized for Iq). `sim/psrr-dc/`'s own
manifest notes call this cross-check out explicitly: `line_psrr_db` (an
average slope over the full 0.66 V range) and `psrr_dc`/`psrr_1k` (local
small-signal slopes) are expected to differ by a few dB, not agree exactly —
and must not differ by *tens* of dB, which they do not here. This record is
therefore a second, independent (large-signal DC vs. small-signal AC)
confirmation that supply rejection is measurably worse post-layout, without
being precise enough on its own to add anything past what
`psrr-dc-post-layout/README.md` already attributes it to.

## Why this one does not need a deep mechanistic write-up

`line_shift_mv`'s ~750x margin to its 24 mV limit means no plausible
extraction-driven shift — real or artifact — moves this spec line's verdict;
the measurement that *would* be sensitive enough to flag the same underlying
mechanism at finer resolution is `line_psrr_db`, and that one already points
in the same direction `psrr-dc-post-layout` characterized in depth. Spending
further effort isolating `line_shift_mv`'s microvolt-scale, mixed-sign delta
would be chasing solver-resolution noise, not new circuit information — the
manifest's own history (the rescaled `line_shift_mv` spread-check threshold,
issue notes above) already established that this measurement's noise floor
is at exactly this scale even schematic-to-schematic.

## Friction filed

None new. Reuses the extraction/translation machinery and the shared
parasitics snapshot `output-voltage-tc-post-layout` (#134),
`quiescent-current-post-layout` (#137) and `psrr-dc-post-layout` (#139)
already built and filed friction for
([2AMLogic/klayout-tools#800](https://github.com/2AMLogic/klayout-tools/issues/800)).

## Shared-infrastructure change alongside this record

`sim/bin/post_layout_common.py`'s `run_post_layout_experiment()` previously
only supported collapsing the runner's outer **temperature** axis
(`temp_override`, used by `output-voltage-tc-post-layout` for its in-deck
box-TC sweep). `sim/line-regulation`'s in-deck **supply** sweep needed the
symmetric case, so this record adds `supply_override` alongside it —
mechanically identical (sets `_Args.supply` instead of `_Args.temp` before
`cr.build_matrix()`), no other behavior changed.
`output-voltage-tc-post-layout`, `quiescent-current-post-layout` and
`psrr-dc-post-layout` all still resolve their existing corner matrices
identically (re-verified via `--dry-run` against all three before this
record was run).

## Known gaps (not closed by this record)

- `line_shift_mv`'s mixed-sign, sub-solver-tolerance-scale delta is not
  attributed to a specific mechanism, unlike the Iq and PSRR findings — the
  huge margin to the limit makes that attribution low-value, but it is
  genuinely open, not resolved.
- No attempt was made to reconcile `line_psrr_db`'s exact −2.06 dB average
  against `psrr-dc-post-layout`'s −4.05 dB `psrr_1k` figure beyond noting
  they agree in sign and order of magnitude, as the two manifests' own notes
  say to expect (average-over-range vs. local-slope are different
  quantities by construction). A closer reconciliation would need the same
  per-net attribution `psrr-dc-post-layout/README.md` already flagged as an
  open item for its own finding.
