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

### Not yet re-qualified (slice A attempt, 2026-11-12)

| Bench | Status |
|---|---|
| `psrr-dc-with-injector` | Batch run lost shards (`batch_no_capacity` / `lost_shard`, 600 s capacity wait exhausted); the record carried n/a corners and was discarded, not committed. Not run locally. Old record `20260923-124813-af9ff1e` remains the evidence. Retry when fleet capacity allows. |
| `psrr-injector-candidates`, slice B (pre-layout benches), slice C, slice D | Not attempted in this slice. Old records remain the evidence. |

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
