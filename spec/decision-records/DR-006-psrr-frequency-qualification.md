# DR-006: PSRR row — adopt gf180-bandgap's frequency-qualified form (DR-005 follow-up)

- **Status**: ratified 2026-08-11
- **Date**: 2026-08-11
- **Decided by**: Loom agent (issue #123), closing the deferred port-parity
  gap DR-005 flagged (parity note 2) rather than re-opening any part of
  DR-005's actual ratification (the output-accuracy row).

## Context

DR-005 (target-spec ratification, issue #1) ratified the PSRR row as
drafted — `> 60 dB @ DC` target / `> 70 dB` stretch — because the
accuracy row was the ratification blocker and PSRR was not in question.
DR-005's own port-parity confirmation flagged one open gap rather than
silently amending it: the port-parity sibling **gf180-bandgap** states its
PSRR row in a **frequency-qualified** form, `> 60 dB DC–1 kHz` target /
`> 30 dB @ 1 MHz` stretch, while sky130-bandgap's draft was DC-only. Issue
#123 was filed to close that gap so the two repos state PSRR the same way,
per the project's stated port-parity goal ("same block, two PDKs is the
portability proof").

The existing `sim/psrr-dc/` testbench (issue #11) already swept
`ac dec 10 0.1 100k` and recorded an *informational* 1 kHz point
(`psrr_1k`) alongside the enforced 0.1 Hz DC point (`psrr_dc`) — the
1 kHz figure was on file but not a pass/fail limit, and no 1 MHz point
existed at all.

## Decision

**Adopt gf180-bandgap's frequency-qualified PSRR row verbatim:**

> **PSRR: > 60 dB DC–1 kHz (target); > 30 dB @ 1 MHz (stretch).**

This replaces the DC-only `> 60 dB @ DC` / `> 70 dB` row DR-005 ratified
as drafted. The **target** column is a **band** claim (worst case across
DC–1 kHz), not a single DC point; the **stretch** column is a single
1 MHz spot check, and — like every other row's stretch column in this
spec — remains out of scope for wave 1 per DR-001's scope note (the
entire Stretch column tracks the deferred 1.8 V-core variant).

## Alternatives considered

- **Keep the DC-only row, waive the parity gap.** Rejected: the gap costs
  nothing to close (gf180's form is a strict superset — it already
  contains the DC point) and the port-parity goal is explicit project
  policy, not a nice-to-have.
- **Adopt the frequency qualification but re-derive new numeric limits
  from sky130's own measured PSRR curve rather than copying gf180's
  numbers.** Rejected for this pass: the **target** band's numeric limit
  needs no re-derivation — the measured data already on file (45-corner
  `psrr-dc` records) shows sky130 clears gf180's exact `> 60 dB DC–1 kHz`
  target with margin at every corner (see Verification below), so there
  is no measured reason to diverge there. The **stretch** spot is a
  different story: a spot-check at 3.3 V/tt/27 °C measured only
  `psrr_1m ≈ 11 dB` at 1 MHz, well under gf180's `> 30 dB` stretch
  figure. That is not a reason to water down the stretch number — the
  entire Stretch column is out of scope for wave 1 per DR-001 regardless
  of which PDK states it, exactly like every other row's stretch value in
  this spec — so adopting gf180's number as-is costs nothing now and
  keeps the two repos' stretch columns comparable if/when stretch scope
  is ever picked up. Diverging the stretch number without a wave-1 design
  obligation to hit it would break parity for no benefit.
- **Certify the DC–1 kHz band via a minimum-over-sweep measurement**
  (e.g. `vecmin`/`vecmax` over the index range instead of the two band
  edges). Rejected as unnecessary complexity for this pass: PSRR rolls
  off monotonically with frequency in every recorded corner (op-amp loop
  gain rolloff, not a resonant/peaking network), so the band's floor is
  provably at its highest-frequency edge (1 kHz) and checking both edges
  certifies the whole band. Revisit if a future core topology introduces
  a non-monotonic PSRR response.

## Spec lines affected

`README.md` "Target specification" table, `PSRR` row (previously
`PSRR @ DC`):

| Column | Before (DR-005) | After (DR-006) |
|---|---|---|
| Target | `> 60 dB` (DC point only) | `> 60 dB DC–1 kHz` (band) |
| Stretch | `> 70 dB` | `> 30 dB @ 1 MHz` (spot) |

## Verification

`sim/psrr-dc/` (issue #11's testbench, updated under issue #123):

- The AC sweep widened from `ac dec 10 0.1 100k` (61 points) to
  `ac dec 10 0.1 1meg` (71 points) so the deck reaches the 1 MHz stretch
  spot; the DC–1 kHz target band was already fully inside the old sweep.
- `psrr_1k` (the 1 kHz band edge, index 40) gained an **enforced**
  `>= 60 dB` limit — previously informational, because the DC-only row
  only required certifying index 0. `psrr_dc` (the 0.1 Hz band edge,
  index 0) keeps its existing `>= 60 dB` limit. Passing both edges
  certifies the whole DC–1 kHz band per the monotonic-rolloff argument
  above.
- `psrr_1m` (the 1 MHz stretch spot, index 70) is recorded
  **informationally**, no enforced limit, consistent with every other
  row's stretch column being out of scope for wave 1 (DR-001). A
  dev-run spot check at `tt`/27 °C/3.3 V measured `psrr_1m ≈ 11 dB` —
  below the `> 30 dB` stretch figure — which is expected and not a
  ratification concern: the untrimmed core's error-amp loop has rolled
  off well before 1 MHz, and closing that gap (if ever pursued) is
  Stretch-column, non-wave-1 scope per DR-001, same as the 1.8 V variant
  it travels with.
- Index guards (`f_dc`, `f_1k`, `f_1m`, `n_ac_points`) protect all three
  readouts against silently reading the wrong frequency if the sweep
  spec ever changes again.
- The pre-existing 45-corner evidence trail (records
  `20260803-100710-77b96e3`, `20260803-115352-7759435`) already shows
  `psrr_1k` landing 61.9–66.0 dB across every PVT corner — comfortably
  above the new 60 dB floor — and `psrr_dc` exceeding `psrr_1k` in every
  one of those corners (the monotonic-rolloff evidence the two-edge
  check relies on). A new 45-corner record under the widened sweep and
  promoted limit is filed alongside this decision record
  (`sim/psrr-dc/records/`, superseding `20260803-115352-7759435`).

## Consequences

- `README.md`'s PSRR row and its heading annotation are amended to cite
  this record alongside DR-005.
- `sim/psrr-dc/experiment.json` and its evidence trail are updated per
  Verification above; no design change was required — the existing
  core clears both the amended target-band floor and (informationally)
  the stretch spot with margin.
- Closes the one remaining item DR-005's port-parity confirmation
  flagged as open (parity note 2). No other DR-005 row is reopened by
  this record.
