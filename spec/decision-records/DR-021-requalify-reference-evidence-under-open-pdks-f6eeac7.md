# DR-021: Re-qualify reference evidence under open_pdks f6eeac7 (index, in progress)

- **Status**: proposed
- **Date**: 2026-11-12
- **Decided by**: Builder (issue #370); no spec row is changed by this record

## Context

#369 moved the open_pdks pin from `c6d73a35f524070e85faff4a6a9eef49553ebc2b`
to `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`. #370 re-runs the reference
benches under the new pin, each with `--supersedes <old record id>`. This record
is the single index; later slices append to it. Existing records are not edited.

## Decision

Re-qualified records are indexed here as old -> new. Every bench in the
2026-11-11 Revision table that is not yet re-run is listed with its status.
No spec relaxation is made or implied.

### Old -> new index

| Bench | Old record | New record | Corners | Result |
|---|---|---|---|---|
| `startup-stability` | `20261015-133821-9f956c4` | `20261111-234331-ebc9a64b` | 45/45 | PASS (old: 10 of 45 FAIL, all 125 C) |
| `psrr-dc-with-injector` | `20260923-124813-af9ff1e` | `20261112-033711-4182dd56` | 45/45 | FAIL 24/45, same as old (see below) |
| `line-regulation` | `20260817-021208-13476b7` | `20261112-071544-f9871d93` | 45/45 | PASS 45/45, same as old |
| `output-voltage-tc` | `20260817-015751-13476b7` | `20261112-072452-f9871d93` | 45/45 | FAIL 45/45 (`tc_ppm`), same as old |
| `psrr-dc` | `20260909-232410-e8e2e46` | `20261112-073424-f9871d93` | 45/45 | PASS 45/45, same as old |
| `quiescent-current` | `20260909-232410-e8e2e46` | `20261112-074405-f9871d93` | 45/45 | PASS 45/45, same as old |
| `startup-ramp` | `20260923-202758-81803b1` | `20261112-075045-f9871d93` | 45/45 | FAIL 13/45 (`vref_spread`), same as old |
| `startup-time` | `20260909-232410-e8e2e46` | `20261112-075916-f9871d93` | 45/45 | FAIL 45/45, same as old |

### Not yet re-qualified (as of the pre-layout slice B, 2026-11-12)

| Bench | Status |
|---|---|
| `psrr-injector-candidates`, slice C (post-layout benches), slice D (MC, offset-MC, attribution, `trim-lsb-chained`, layout reports) | Not attempted in this slice. Old records remain the evidence. |

### Per-row old/new deltas, `startup-stability` (worst case over 45 corners)

Limits are the bench's own pass limits. All 15 measurements pass at all 45
corners in the new record.

| Measurement | Limit | Old range | New range |
|---|---|---|---|
| `itrav_min` (A) | >= 1e-9 | 5.1e-10 .. 8.3e-4 | 6.8e-9 .. 7.0e-4 |
| `imin_off_su` (A) | >= 1e-8 | 8.0e-10 .. 1.43e-3 | 3.4e-5 .. 1.39e-3 |
| `i_off_su` (A) | >= 1e-6 | 1.1e-8 .. 1.45e-3 | 3.9e-4 .. 1.94e-3 |
| `i_su_standing` (A) | <= 2e-7 | 1.1e-10 .. 3.8e-8 | 6.8e-11 .. 8.6e-8 |
| `i_standing` (A) | +/-1e-6 | -1.5e-8 .. 3.6e-7 | -1.2e-8 .. 7.7e-7 |
| `dvref` (V) | +/-0.02 | -3.2e-4 .. 6.6e-3 | -2.8e-4 .. 1.47e-2 |
| `vref_dut` (V) | 1.1 .. 1.3 | 1.186 .. 1.223 | 1.186 .. 1.221 |
| `vgdrv_dut` (V) | 1.0 .. 3.2 | 1.572 .. 2.583 | 1.573 .. 2.582 |
| `isup_dut` (A) | 5e-6 .. 5e-5 | 2.01e-5 .. 3.29e-5 | 2.01e-5 .. 3.31e-5 |

Unchanged ranges: `ncross_su`, `alpha_eq`, `imin_off_bare`, `i_off_bare`,
`i_on_su`, `ncross_bare`.

Called out: the old record's 10 failures (125 C corners, `itrav_min` /
`imin_off_su` / `i_off_su` below limit) do not reproduce under `f6eeac7`.
`dvref` max more than doubled (6.6 mV -> 14.7 mV) but stays inside its 20 mV
limit, so no ratified row fails. Whether the old failures were a PDK effect
or a transient of the old run was not investigated here.

### Per-row old/new deltas, `psrr-dc-with-injector` (all 45 corners)

`psrr_dc`, `psrr_band_min` and `psrr_1m` are identical between
`20260923-124813-af9ff1e` and `20261112-033711-4182dd56` at every corner
(max absolute difference 0 dB). Worst case `psrr_band_min` 24.78 dB
(`ff_125c_3.63v`) in both; worst `psrr_1m` 15.53 dB in both. Both records
FAIL 24 of 45 corners against the DR-006 60 dB band-min floor, so the
failure is unchanged and not a PDK-pin effect. No result moved, so nothing
is outside tolerance because of the re-pin. This bench is a diagnostic
companion (issue #300); the pre-existing failure is already tracked and no
spec row is relaxed here.

### Per-row old/new deltas, pre-layout slice B (all 45 corners each)

Run with `corner-run.py --backend batch`, full matrix, no subset. For every
measurement of the six benches the min and max over the 45 corners are
identical between old and new record to the printed precision (4 significant
figures), and the per-measurement pass/fail counts are identical. Nothing moved,
so no result is outside tolerance because of the re-pin. The pre-existing
failures (`output-voltage-tc` `tc_ppm` 142-159 ppm/C at all 45 corners;
`startup-ramp` `vref_spread` at 13 corners; `startup-time` at all 45 corners)
are unchanged and not PDK-pin effects; no spec row is relaxed here and no new
ratified-row failure appears.

## Alternatives considered

- **Run non-batch / local grids for the remaining benches** - rejected: host
  rules forbid local grids on the dispatch worker.
- **Commit the partial `psrr-dc-with-injector` record** - rejected: n/a
  corners are lost shards, not simulation results.

## Spec lines affected

None.

## Consequences

#370 stays open. `design/block-characterization-report.md` and `signoff/`
are not regenerated in this slice, since the set is incomplete and they cite
the old records. Remaining benches are re-run in later slices, appending here.
