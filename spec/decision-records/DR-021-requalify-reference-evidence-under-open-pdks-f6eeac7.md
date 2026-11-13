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
| `psrr-dc-post-layout` | `20260923-073641-dbd4dda` | `20261112-165538-ffb50731` | 45/45 | FAIL, same as old (psrr_band_min 20/45 pass) |
| `quiescent-current-post-layout` | `20260923-072514-dbd57a9` | `20261112-172211-ffb50731` | 45/45 | PASS 45/45, same as old |
| `startup-stability-post-layout` | `20260924-041313-999407b` | `20261112-171240-ffb50731` | 8/8 (the bench's own worst-corner subset) | PASS 8/8, same as old |
| `trim-lsb-chained` | `20261008-163545-ffa415c` | `20261112-224417-24a14a1` | 60 batch requests (15 corners; `chained` 17 codes, `lumped` 3 codes), no subset | PASS, per-corner graded table identical to old |
| `psrr-injector-candidates` | `20261002-200944-fe334b1` | `20261113-052755-9402fb82` | 45/45 x 4 variants (180 points), no subset | Overall FAIL, same as old (2 `candidate_within_bare_core_ceiling` checks at `sf_125c`; old record fails the same two) |

### Not yet re-qualified (as of slice D3, 2026-11-13)

Every bench of the 2026-11-11 Revision table now has a disposition: either a
row in the index above, or a reason here. None is left as "not attempted".

| Bench | Status |
|---|---|
| `monte-carlo-untrimmed` | **Not re-qualified: batch collector loses samples.** `--backend batch` exists (#437) but has never produced a usable record; all three attempts on disk report `klt_status: "error"` on every job and parse back fewer samples than requested. A partial-sample MC record cannot be comparable evidence. Blocked on #444 (open, `loom:operator`). Old record `20260817-121131-d7d85b6` remains the evidence. See "Slice D3 dispositions" below. |
| `error-amp-offset-mc` | **Not re-qualified: batch path is dry-run only.** `run_amp_offset_mc.py --backend batch` builds and prints the requests but refuses a real run ("collecting klt's per-sample reports into a record is not implemented yet"), asserted by `sim/tests/test_amp_offset_mc_batch.py`. Blocked on the collector half of #398. Old record `20260817-130441-aa5324e` remains the evidence. |
| `psrr-injector-attribution` | **Attempted and not re-qualified: fleet spot quota exhausted.** A full 5-variant x 45-corner run on 2026-11-13 completed but lost 15 of its 225 points to `batch_no_capacity` / `lost_shard`, including 7 `core_only` (the control variant) and 8 `ref_open` (the dominant-contributor variant). The record was **not committed**. Old record `20261002-070506-29da08e` remains the evidence. See "Slice D3 dispositions" below. |
| layout reports | **Re-qualification does not apply.** The cited DRC/LVS/extraction verdicts come from KLayout's curated sky130 deck at a pinned klt/KLayout version, not from the open_pdks ngspice model cards `f6eeac7` changed. No new report is minted or needed. See "Slice D3 dispositions" below. |
| post-layout `startup-ramp`, `startup-time`, `line-regulation`, `output-voltage-tc` (slice C') | **Still not re-qualified, but the slice C reason is now stale.** A single-corner submit on 2026-11-13 shows the fleet runner *does* accept `analysis_steps` (ngspice 47) and returns values bit-identical to the newest local record. Lifting the hold is a script change this issue puts out of scope, and the probe exposed a second blocker (`options.timeout_s` above the fleet's job ceiling); both are filed as **#510**. Old records remain the evidence. See "Slice C' re-test" below. |

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

### Per-row old/new deltas, post-layout slice C

Run with `--backend batch`, same extracted netlist inputs as the superseded
records (layout record `20260923-070209-dbd57a9`), no subset beyond what the
bench itself uses (`startup-stability-post-layout` is an 8-corner worst-corner
bench by design). For every measurement of the three benches the min and max
and the per-measurement pass counts match the superseded record; the largest
per-corner absolute difference is 0 for `psrr-dc-post-layout` (all measurements)
and `quiescent-current-post-layout`, and at most 1.5e-8 A (`itrav_min`) for
`startup-stability-post-layout`. Nothing moved because of the re-pin. The
pre-existing `psrr-dc-post-layout` failure (21/45 corners below the 60 dB
floor on `psrr_dc`, 25/45 on `psrr_band_min`) is unchanged and is a
pre-existing finding, not a PDK-pin effect; no spec row is relaxed here.

### Per-row old/new deltas, slice D2 (`psrr-injector-candidates`)

Run with `--backend batch --batch-capacity-wait-s 600` under `f6eeac7`, full
45-corner matrix, no subset. The runner has no `--supersedes` option, so the new
record carries no `Supersedes` field; supersession is recorded only by this
index row (old record is not edited). The default variant set has since gained
`ngclamp`, so the new record holds 180 points to the old 135; for the three
variants common to both (`base`, `ref3`, `ref3_ngclamp`) the per-corner
`psrr_band_min` difference is 0 dB at all 45 corners, and the below-60 dB counts
are identical (24, 18, 0). The two failing `candidate_within_bare_core_ceiling`
checks (`sf_125c_3.30v`, `sf_125c_3.63v`) are the same two the old record fails;
nothing moved because of the re-pin. No spec relaxation is made.

### Per-row old/new deltas, slice D1 (`trim-lsb-chained`)

Run with the runner's batch-only path under `f6eeac7`. The per-corner graded
`chained` table (VREF at codes 0/-16, span, LSB, min/max step, monotonic) is
identical to the superseded record for all 15 corners, so nothing moved because
of the re-pin. The DR-005 Trim-row verdict (derived qualification section, now
inline in the new record) is the same as the superseded
`20261008-163545-ffa415c-dr005-qualification.md`: FAIL on range (down 38.46 mV =
3.2 % < 5 %; up 0) and on >= 5 bits (17 levels, 4.09 bits); max step passes.
That is a pre-existing finding, not a PDK-pin effect; no spec row is relaxed.

### Slice D3 dispositions (2026-11-13, `bcacdb67`)

Slice D3 closes out the slice D remainder of the 2026-11-11 Revision table
and re-tests the slice C' refusal. Three of its four items need no fleet run,
and the reasons are recorded here rather than left as "not attempted".

#### `monte-carlo-untrimmed` — not re-qualified: batch collector loses samples

The reference record is `20260817-121131-d7d85b6` (N=300 requested per
temperature, 838 converged mismatch samples; cited by
`design/block-characterization-report.md` row 1c and, as the
`-klt-yield`/`-dr005-qualification` derivations of the 2026-09-23 re-mint, by
`signoff/block-manifest.json` item 6). The 2026-11-11 Revision made this row
conditional: "run only if the runner's batch path is live; else 'not
re-qualified'". It is not live.

`--backend batch` exists (#437) but has never produced a usable record. The
three batch records on disk are the #444 smoke attempts, and all three fail
the same way — every one of their 14 klt jobs reports `klt_status: "error"`
with `klt_exit_code: 4`, and the per-point `sample_count` check fails
because the collector parses back fewer samples than it requested:

| Record | N requested | Jobs | `klt_status` | Example point |
|---|---|---|---|---|
| `20261104-192509-4193f7c5` | 20 | 14 | `error` (14/14) | — |
| `20261105-052441-84832cb5` | 20 | 14 | `error` (14/14) | — |
| `20261105-061037-ef9df345` | 20 | 14 | `error` (14/14) | `tt_mm_all_-40c_3.30v`: `parsed 9 samples, expected 20`, 2 converged |

A re-run at the reference N=300 would lose samples the same way, and a
Monte Carlo record whose sample count does not match the superseded
record's cannot be comparable evidence — the issue's own Test Plan requires
"seeds/sample counts must match the superseded record to be comparable".
Committing one would repeat the lost-shard mistake slice A already
refused. #444 (the real-fleet smoke run that would prove this path) is open
and labelled `loom:operator`: its last Builder report says a further full
submit needs an operator ruling, so it is not this slice's to force.

**Old record `20260817-121131-d7d85b6` remains the evidence.** Re-qualifying
it depends on #444.

#### `error-amp-offset-mc` — not re-qualified: batch path is dry-run only

The reference record is `20260817-130441-aa5324e` (cited by
`design/block-characterization-report.md` row 6). The 2026-11-11 Revision
recorded "no `--backend` option found (grep, 2026-11-11)". **That stamped
fact has drifted and is corrected here**: `run_amp_offset_mc.py` does take
`--backend {local,batch}` (added by `f11d9256`, request-building only), but
batch is refused unless `--dry-run` is also passed:

> `--backend batch is dry-run only for error-amp-offset-mc: the request is
> built and printed, but collecting klt's per-sample reports into a record
> is not implemented yet (issue #398); run it locally, or add --dry-run`

`sim/tests/test_amp_offset_mc_batch.py::test_batch_without_dry_run_is_refused_before_any_work`
asserts that refusal, so it is the designed behaviour, not a regression. The
disposition is unchanged by the correction: there is no batch path that can
mint a record, and a local 12-point MC grid on a shared dispatch worker is
forbidden by the host rules.

**Old record `20260817-130441-aa5324e` remains the evidence.** Re-qualifying
it needs the collector half of #398 to land first.

#### Layout reports — re-qualification does not apply

Scope item 2 said "Layout reports likewise get new report ids via the
existing layout flow". On inspection the open_pdks re-pin does not stale
them, so no new report is minted and none is needed:

- The cited layout evidence is DRC, LVS and extraction
  (`layout/bandgap-core/reports/{20260811-221633-a0ee5e7,20260817-020222-13476b7,20260923-070209-dbd57a9,20261022-070000-e6e4be0}`).
  Those verdicts are produced by **KLayout's curated sky130 deck** at a
  pinned klt/KLayout version (`KLayout engine version: 0.30.12` in the
  newest record), not by the open_pdks **ngspice model cards** that
  `f6eeac7` changed. `klt drc` / `klt extract` / `klt lvs` never read
  `sky130.lib.spice`.
- The only open_pdks dependency in the layout tree is a **provenance
  stamp** that `klt gen` writes into its GDS sidecars
  (`"pdk": {"version": "open_pdks c6d73a35…"}` in the 2026-09-23 report's
  `*.gen.json`). The newest report's artifacts
  (`20261028-063447-2c76afb7/{extract,drc,lvs}.json`) carry no `pdk` field
  at all.
- Where the layout *does* feed a PDK-sensitive result, it does so through
  the extracted netlist that the post-layout **simulations** consume — and
  those were re-qualified in slice C (and are held in C' for the four
  benches below), which is the correct place for it.
- Re-running the layout flow would mint a **new layout** (a design act),
  not a re-measurement of the cited one, and `layout/*/reports/*/record.md`
  is explicitly not-to-be-edited by scope item 4.

**Not traced**: whether `f6eeac7` changes the sky130A layer definitions
`klt gen` reads. The superseded revision `c6d73a35…` is no longer installed
on this host (`~/.ciel/ciel/sky130/versions/` holds `f6eeac7…` only), so the
two could not be diffed here. This does not affect the DRC/LVS/extraction
verdicts above, which come from KLayout's own deck.

#### `psrr-injector-attribution` — attempted, not re-qualified: fleet spot quota exhausted

The reference record is `20261002-070506-29da08e` (cited by
`design/block-characterization-report.md` row 4e). Its batch path is live
(#398), so unlike the two benches above this one was **run**, at the full
5-variant x 45-corner matrix (225 points, 30 `klt sim` requests: one AC and
one `op` request per variant per supply), `--backend batch
--batch-capacity-wait-s 600`, no subset. The variant set is byte-identical
to the superseded record's (`base`, `core_only`, `ref_open`, `inj_open`,
`clamp_open`), so the comparison would have been apples-to-apples.

**The run completed but is not usable evidence.** 15 of the 225 points came
back with no measurements at all, because their shards were lost to spot
capacity:

> shard lost: batch-fleet-provision.sh launch failed (exit 1): error: 288
> vCPU already running + 1 instance(s) of up to 32 vCPU exceeds
> BATCH_MAX_VCPU=224, and only 0 type(s) fit the -64 vCPU left (floor 3) --
> the spot quota is shared with ci-spot (capacity wait budget of 599.999s
> exhausted after 6 launch attempt(s)) ... [batch_no_capacity]

37 `batch_integrity` checks fail on that basis, and the lost points land
exactly where the attribution's conclusions live: 7 in `core_only` (the
CONTROL variant and the recovery ceiling) and 8 in `ref_open` (the variant
that identifies `MPC1`/`MPC2` as dominant). The remaining check failures
(`control_core_only_clears_floor` 7, `ref_stack_is_dominant` 7,
`ref_open_restores_control` 16, against 4 in the superseded record) are
consequences of the missing points, not measured findings.

A lost shard is not a simulation result, so the record cannot supersede
anything, and this slice applies the same rule slice A applied to the
partial `psrr-dc-with-injector` run: **the uncommitted record and its
artifact manifests were deleted rather than committed.** Per the host rules
and this issue's execution rule, no local grid fallback was attempted; the
failure is reported here and in the PR instead.

**Old record `20261002-070506-29da08e` remains the evidence.** Re-qualifying
it needs only fleet headroom -- no code change -- so it is a straight retry
when the shared spot quota (`BATCH_MAX_VCPU=224`, shared with `ci-spot`) has
room. This is the second capacity-driven failure on this issue (the first
was slice A's 2026-11-11 attempt), which is worth noting as a pattern: the
re-qualification campaign's remaining work is gated on fleet budget, not on
the design or the harness.

#### Slice C' re-test — the fleet runner now accepts `analysis_steps`

The 2026-11-11 Revision left one thing untraced: "whether the fleet runner
image has since been upgraded past klt 0.7.0 (re-test one single-corner
submit of a C' bench at build time; if it now succeeds, include it)". It has
been, and the refusal recorded in slice C is **stale**.

The request was emitted with
`run_post_layout_startup_time.py --backend batch --dry-run --process tt
--temp 27 --supply 3.3` and submitted by hand (`batch_sim.py`'s own guard
still refuses the slug), `klt sim <request> --backend batch
--wait-for-capacity 600`:

- Job `klt-sim-47a1478901e2`: `status: pass`, `corners: 1  passed: 1
  failed: 0  errored: 0  inconclusive: 0`, engine **ngspice 47** (the
  2026-10-21 refusal was on an image running 46), `pdk: sky130A open_pdks
  f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`. Measurements came back
  step-qualified (`main.t_start_ms`, …) exactly as `plain_name()` expects.
  **No `batch_runner_feature_unsupported`.**
- The values match the bench's newest local record bit-for-bit. Fleet vs
  `sim/startup-time-post-layout/records/20260923-070906-dbd57a9.json`
  corner `tt_27c_3.30v`:

  | Measurement | Fleet (2026-11-13) | Local record (2026-09-23) | Delta |
  |---|---|---|---|
  | `t_start_ms` | 0.08886417 | 0.08886417 | 0 |
  | `vref_final` | 1.193888 | 1.193888 | 0 |
  | `gdrv_final` | 2.08979 | 2.08979 | 0 |
  | `vdd_final` | 3.3 | 3.3 | 0 |
  | `n_tran_points` | 418.0 | 418.0 | 0 |

That is exactly the condition `POST_LAYOUT_STEP_REQUEST_SLUGS`' own comment
names for lifting the hold ("once the runner image accepts the shape and a
live single-corner run matches the bench's newest local record").

**C' is still not re-qualified in this slice**, for two reasons:

1. Lifting the hold means moving four slugs out of
   `POST_LAYOUT_BATCH_REFUSALS` in `sim/bin/batch_sim.py` — a **script
   change**, which this issue puts out of scope ("Out of Scope addition:
   enabling batch for any bench"). Every previous enablement in this family
   went through its own issue (#395, #396, #398), each with its own live
   single-corner validation, and this one follows that precedent.
2. The probe exposed a **second** blocker that flipping the slug set alone
   would not fix. The emitted request carries
   `options.timeout_s: 10800` (`DEFAULT_BATCH_TIMEOUT_S`), and klt warned:

   > batch job bound 10920s (options.timeout_s 10800s x 1 units + 120s …)
   > exceeds the fleet's whole-job ceiling of 3600s (max_job_seconds from
   > fleet_config) … No remote.hosts value fits: a single unit's bound
   > exceeds the ceiling — lower options.timeout_s to at most 3480s

   The single-corner probe passed anyway (real runtime 3.3 s), but
   `shard_hosts()` answers that bound with one unit per host, so a
   full-matrix C' request would be a 45-host job whose bound is ~486 ks
   against a 3.6 ks ceiling. These benches' measured per-corner runtime is
   ~16 s, so the fix is a `timeout_s` that fits the ceiling.

Filed as **#510** with both findings and the measured evidence above. C'
re-qualification unblocks once it lands. Old records remain the evidence
meanwhile.

**Noted for every future batch slice** (measured in this slice, not
specific to C'): the same `timeout_s` → `shard_hosts()` interaction makes
any bench that keeps `DEFAULT_BATCH_TIMEOUT_S` shard one corner per host.
The `psrr-injector-attribution` attempt above first went out at the default
and was given 15 hosts per request, which on a contended fleet serialised
its 30 requests; relaunched with `--timeout 300` (>12x headroom over the
measured ~18-24 s per corner) each request took 2 hosts and four ran
genuinely concurrently. That is a large reduction in requested vCPU for the
same work, and on a fleet whose spot quota is shared with `ci-spot` it is
the difference between a run that progresses and one that does not --
so it is worth passing a realistic `--timeout` on every batch submit, not
only on the benches #510 covers.

## Alternatives considered

- **Run non-batch / local grids for the remaining benches** - rejected: host
  rules forbid local grids on the dispatch worker.
- **Commit the partial `psrr-dc-with-injector` record** - rejected: n/a
  corners are lost shards, not simulation results.
- **Re-run `monte-carlo-untrimmed` on the batch backend anyway, at the
  reference N=300** - rejected: the collector parses back fewer samples than
  it requests (9 of 20 in the last #444 attempt), so the record's sample
  count would not match the superseded record's and could not be compared;
  and #444 is held at `loom:operator` precisely because a further full
  submit needs an operator ruling.
- **Enable the four slice C' benches here, now that the fleet runner accepts
  `analysis_steps`** - rejected: that is a change to
  `sim/bin/batch_sim.py`, which this issue puts out of scope, and the
  precedent in this family (#395, #396, #398) is a separate issue with its
  own live single-corner validation. Filed as #510, with the measured probe
  as its evidence.
- **Re-run the layout flow to mint new report ids** - rejected: it would
  produce a new layout rather than re-measure the cited one, and the cited
  verdicts carry no open_pdks model dependency to re-qualify.

## Spec lines affected

None.

## Consequences

#370 stays open for one remaining step: regenerating
`design/block-characterization-report.md` and the `signoff/` outputs so they
cite the new records (scope item 5). They are deliberately **not** touched in
this slice — they are snapshots of the whole reference set, and four of its
benches (slice C') are expected to be re-qualified as soon as #510 lands, so
regenerating now would mean regenerating twice and citing a set that is
about to change.

With slice D3 the re-run work itself is complete: every bench in the
2026-11-11 Revision table is either re-qualified (the index above) or has a
recorded reason it is not, each with what it waits on — #510 (slice C'),
#444 (`monte-carlo-untrimmed`), #398's collector half
(`error-amp-offset-mc`), and fleet spot-quota headroom
(`psrr-injector-attribution`, a straight retry needing no code change).
Layout reports need no re-qualification. No spec row is relaxed by any slice
of this record, and no result moved outside its tolerance because of the
re-pin.

Of the four, only `psrr-injector-attribution` is purely a scheduling matter;
the other three need code to land first. Two of this issue's slices have now
failed on the shared spot quota, so the remaining re-qualification work is
gated on fleet budget rather than on the design or the harness.
