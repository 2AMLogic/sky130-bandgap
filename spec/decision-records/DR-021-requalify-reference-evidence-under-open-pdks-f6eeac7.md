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
| `line-regulation-post-layout` | `20260923-075227-dbd4dda` | `20261113-110852-7efdcf3b` | 15/15 (the bench's own in-deck-sweep subset) | PASS 15/15, same as old |
| `output-voltage-tc-post-layout` | `20260923-074724-dbd4dda` | `20261113-111050-7efdcf3b` | 15/15 (the bench's own in-deck-sweep subset) | FAIL, same as old (`tc_ppm` 15/15, `vref_min` 14/15) |
| `startup-time-post-layout` | `20260923-070906-dbd57a9` | `20261113-111050-7efdcf3b` | 45/45 | PASS 45/45, same as old |
| `startup-ramp-post-layout` | `20260924-041313-999407b` | `20261113-111230-7efdcf3b` | 45/45 | FAIL 13/45 (`vref_spread`), same as old |
| `psrr-injector-attribution` | `20261002-070506-29da08e` | `20261113-111649-7efdcf3b` | 45/45 x 5 variants (225 points), no subset | Overall FAIL, same as old (the same 4 of 429 checks; all 225 points bit-identical) |
| `error-amp-offset-mc` | `20260817-130441-aa5324e` | `20261113-140022-64c42cad` | 5 MC points (3x300 + 30 control + 300 second seed = 1 230 samples), same seeds and N as the old record, 0 excluded | PASS, same as old (6/6 cross-point checks, `budget_closure` holds at all three temperatures); the mismatch *draws* are not bit-identical -- see below |

### Not yet re-qualified (as of slice F, 2026-11-13)

Every bench of the 2026-11-11 Revision table has a disposition: either a row
in the index above, or a reason here. None is left as "not attempted". After
slice F exactly **one** bench is not re-qualified, and it is also stated in
`design/block-characterization-report.md` itself (row 1c and section 3 item 6),
so a reader who starts there is not left to infer the gap from a date.

| Bench | Status |
|---|---|
| `monte-carlo-untrimmed` | **Not re-qualified: batch collector loses samples.** `--backend batch` exists (#437) but has never produced a usable record; all three attempts on disk report `klt_status: "error"` on every job and parse back fewer samples than requested. A partial-sample MC record cannot be comparable evidence. Blocked on #444 (open, `loom:operator`). Old record `20260817-121131-d7d85b6` remains the evidence. See "Slice D3 dispositions" below. |
| layout reports | **Re-qualification does not apply.** The cited DRC/LVS/extraction verdicts come from KLayout's curated sky130 deck at a pinned klt/KLayout version, not from the open_pdks ngspice model cards `f6eeac7` changed. No new report is minted or needed. See "Slice D3 dispositions" below. |

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

#### `error-amp-offset-mc` — not re-qualified: no fleet run has minted a record

The reference record is `20260817-130441-aa5324e` (cited by
`design/block-characterization-report.md` row 6). The 2026-11-11 Revision
recorded "no `--backend` option found (grep, 2026-11-11)". **That stamped
fact has drifted and is corrected here**: `run_amp_offset_mc.py` does take
`--backend {local,batch}` (added by `f11d9256`, request-building only), and
at slice D3 batch was refused unless `--dry-run` was also passed:

> `--backend batch is dry-run only for error-amp-offset-mc: the request is
> built and printed, but collecting klt's per-sample reports into a record
> is not implemented yet (issue #398); run it locally, or add --dry-run`

`sim/tests/test_amp_offset_mc_batch.py::test_batch_without_dry_run_is_refused_before_any_work`
asserted that refusal, so it was the designed behaviour, not a regression. The
disposition at slice D3 was unchanged by the correction: there was no batch
path that could mint a record, and a local 12-point MC grid on a shared
dispatch worker is forbidden by the host rules.

**Superseded on 2026-11-13 by #514**, which implements the collector: the
refusal and its test are gone, `--backend batch` (no `--dry-run`) now submits
one request per point, folds the per-sample reports back through the same
`evaluate()` / `render_record()` path as a local run, and writes a record
carrying an `execution` block. A submit/collect failure, a short report, a
model-library mismatch or runner skew is still an error that writes no record
and never falls back to a local run.

**The disposition itself does not change: still not re-qualified.** #514 was
code and unit tests only — no fleet submission was made and no record was
minted, so there is nothing new to cite here. Two things follow from that and
are recorded rather than glossed:

- No committed klt report in this repo is a Monte Carlo one: of the
  `klt-report.json` files under `sim/`, none carries a
  `monte_carlo.sample_index` entry (`git grep -l sample_index -- sim`
  matches only `sim/bin/batch_sim.py`, the two batch test files and
  `sim/README.md`). The collector's tests therefore parse hand-built reports
  whose shape comes from klt's own report contract, and the parsing is
  **unverified against a real fleet report**.
- #444 (the sibling bench's fleet smoke run losing 170–177 of 280 MC shards,
  cause unconfirmed, `loom:operator`) is about the same fleet this bench would
  submit to. A full 300-sample run here would be exposed to the same loss.

**Old record `20260817-130441-aa5324e` remains the evidence.** Re-qualifying it
now needs only a fleet run, which belongs to #370; it should be a small-N run
first, for both reasons above.

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

### Per-row old/new deltas, slice C' (the four `analysis_steps` post-layout benches)

The slice C' hold recorded above is lifted: **#510 landed** (PR #512) and moved
`startup-ramp-post-layout`, `startup-time-post-layout`,
`line-regulation-post-layout` and `output-voltage-tc-post-layout` into
`batch_sim.POST_LAYOUT_BATCH_ENABLED_SLUGS`, so all four ran here on the fleet
at their full matrices.

Run with `run_post_layout_*.py --backend batch --batch-capacity-wait-s 1800
--timeout 230 --supersedes <old>`, no subset beyond what each bench itself uses
(`line-regulation` and `output-voltage-tc` collapse one outer axis because
their decks sweep it internally -- the superseded records carry the **same**
`subset_reason`, byte-for-byte). Same extracted-netlist inputs as the
superseded records (layout record `20260923-070209-dbd57a9`, parasitics
snapshot reused), so the comparison is apples-to-apples; the only variable is
the pin (`c6d73a3` -> `f6eeac7`, and with it the fleet's ngspice 47 against the
old records' local ngspice 46).

**Nothing moved.** Over all 120 corner points and all 28 measurements, the
largest difference from the superseded record is last-printed-digit rounding,
and **no** measurement verdict, corner verdict or spread check changes:

| Bench | Points | Largest absolute difference (measurement @ corner) | Largest relative | Verdict flips |
|---|---|---|---|---|
| `line-regulation-post-layout` | 15 | 1.5e-4 dB (`line_psrr_db` @ `ff_-40c_3.30v`); 3.0e-5 mV (`line_shift_mv` @ `sf_27c_3.30v`) | 1.8e-5 | none |
| `output-voltage-tc-post-layout` | 15 | 1.9e-3 ppm/C (`tc_ppm` @ `fs_27c_3.63v`) | 1.2e-5 | none |
| `startup-time-post-layout` | 45 | 0 (every measurement at every corner) | 0 | none |
| `startup-ramp-post-layout` | 45 | 1.4e-5 V (`vref_spread_early` @ `ss_-40c_3.63v`) | 3.4e-2 (`vref_converge` @ `ss_-40c_3.63v`, -0.000356 -> -0.000344) | none |

Two cells in that table were corrected on 2026-11-13 after the #516 review, by
recomputing both diffs from the committed records; neither correction touches a
verdict or a conclusion. `line-regulation-post-layout`'s largest absolute
difference is `line_psrr_db`'s 1.5e-4 dB, not `line_shift_mv`'s 3.0e-5 mV -- the
two measurements are in different units, so both are now listed rather than one
being called "largest". `startup-ramp-post-layout`'s largest *relative*
difference is `vref_converge`'s 3.4e-2, not `vref_spread_early`'s 1.7e-2; the
prose below the table already said so.

`vref_nom`, `vref_27`, `vref_min`, `vref_max`, `n_supply_points`,
`n_temp_points`, `sweep_start_v`, `sweep_end_v`, all five `startup-time`
measurements and `startup-ramp`'s `isup_g` / `vref_f` / `vref_g` are **exactly
equal** at every corner. `startup-ramp`'s largest *relative* differences
(`vref_spread_early` 1.7e-2, `vref_converge` 3.4e-2, `vref_spread` 4.3e-3,
`t_start_f` 8.3e-4) all sit on quantities whose absolute value is at or near
zero -- 1.4e-5 V, 1.2e-5 V, 2e-6 V and 3.8e-11 s respectively -- i.e. the ratio
is large only because the denominator is small, which is the same
last-digit-rounding class `sim/README.md` already records for
`line-regulation-post-layout`'s #510 probe and for `startup-ramp`'s pre-layout
twin (#493).

The pre-existing failures are unchanged and are **not** PDK-pin effects. The
failing corner sets are identical old-to-new, not merely the same counts:

- `output-voltage-tc-post-layout`: `tc_ppm` fails all 15 corners (89.81 ..
  185.61 ppm/C, the same binding corner `sf_27c_3.63v`) and `vref_min` fails 14
  of 15 (`ff_27c_3.63v` clears the 1.176 V floor at 1.186483 V, as before) --
  rows 1b and 3b of `design/block-characterization-report.md`.
- `startup-ramp-post-layout`: `vref_spread` fails the **same 13** corners,
  worst 18.462 mV at `sf_-40c_3.63v` (`sf_-40c_2.97v` reads 8.208 mV); the
  ratified `t_start < 1 ms` half still passes 45/45 and `vref_converge` still passes 45/45 -- row 8d's DR-010
  exception, unchanged.
- `line-regulation-post-layout` (row 5c) and `startup-time-post-layout`
  (row 8e, post-layout half) still PASS at every corner, with the eroded
  line-regulation margin (`line_shift_mv` up to 18.47 mV, `line_psrr_db` down
  to 31.06 dB at `ff_125c`) reproduced to within 3e-5 mV / 1.5e-4 dB.

No result is outside its tolerance because of the re-pin, no ratified row newly
fails, and no spec relaxation is made or implied.

**Fleet execution note.** Every request sharded to `remote.hosts: 1`
(`--timeout 230` x 15 units + 120 s = 3 570 s, under the 3 600 s whole-job
ceiling), so each bench asked the fleet for at most three hosts instead of the
45 a `DEFAULT_BATCH_TIMEOUT_S` request would have demanded. All ten jobs came
back `state: done`/`failed`-on-verdict with `runner_request_features.status =
supported` (runner klt 0.9.0, ngspice 47, `open_pdks f6eeac7`,
`remote_pdk_matches_pin: true`), **no** `batch_no_capacity`, **no**
`lost_shard`, and no corner without measurements. Wall clock was 60-124 s per
bench. The two `klt_exit_code: 3` benches report
`exit_reason.message` as a verdict exit ("not a runner crash and not the
whole-job ceiling"), which is why their records are usable evidence where slice
A's partial run was not.

### Slice D4 -- `psrr-injector-attribution` re-run (the capacity retry succeeded)

Slice D3 ran this bench's full matrix and lost 15 of 225 points to
`batch_no_capacity` / `lost_shard`, deleted the record uncommitted, and recorded
it as "needs only fleet headroom -- no code change -- so it is a straight retry".
**That retry is this slice, and it succeeded.**

Re-run at the same full 5-variant x 45-corner matrix (225 points, 30 `klt sim`
requests: one `ac` and one `op` per variant per supply), `--backend batch
--batch-capacity-wait-s 1800 --batch-max-jobs 8`, no subset, same variant set
(`base`, `core_only`, `ref_open`, `inj_open`, `clamp_open`) and the same cited
snapshot record (`sim/psrr-dc-with-injector/records/20260923-124813-af9ff1e.md`)
as the superseded record. The one thing changed from slice D3's attempt is the
per-point budget: **`--timeout 200`** rather than the runner's 1 800 s default,
which puts each 15-unit request's bound at 3 120 s and so shards it to
`remote.hosts: 1` instead of one host per corner. That is D3's own measured
lesson applied, and it is why 30 requests fit inside the shared spot quota this
time.

**All 225 points came back with measurements; none was lost.** The result is
not merely comparable to the superseded record, it is **bit-identical**: over
all 225 points and all 14 measurements (`psrr_dc`, `psrr_band_min`, `psrr_1k`,
`psrr_1m`, `v_gdrv`, `v_vref`, `v_ne`, `v_ng`, `v_nc1`, `i_vdd`, `f_dc`,
`f_1k`, `f_1m`, `n_ac_points`) the maximum absolute difference from
`20261002-070506-29da08e` is **0**. The check sets are the same 429 checks, and
the same **4** fail -- `ref_stack_is_dominant` at `ff_125c_3.30v` and
`sf_125c_3.63v`, `ref_open_restores_control` at `sf_125c_3.30v` (2.025 dB) and
`sf_125c_3.63v` (3.067 dB) -- with zero check verdict flips. Those four are the
second-order unrecovered term row 4e already disclosed, 5.6 dB above DR-006's
floor rather than below it, and they are a pre-existing finding, not a PDK-pin
effect.

So row 4e's attribution conclusion stands unchanged under `f6eeac7`: cutting
`MPC1`/`MPC2` (`ref_open`) recovers the control, cutting `MNC` recovers
nothing, cutting `MNI` recovers only partially. The runner has no
`--supersedes` option (as with `psrr-injector-candidates`), so the new record
carries no `Supersedes` field and supersession is recorded only by this index's
row; the old record is not edited.

### Slice E -- `design/block-characterization-report.md` regenerated (scope item 5 closed)

No simulation, no fleet, no code: this slice re-derives the report's rows from
the newest record under each cited `sim/*/records/` directory, which is what
its own section 0 "Regeneration rule" requires after any new record lands.
Twenty of its rows change citation; **no verdict, binding corner or disposition
moves**, which is the expected outcome given the per-slice deltas recorded
above.

What the regeneration actually changed, beyond citations:

- Three last-printed-digit updates. Row 1b's `vref_27` range
  1.193300-1.199550 V -> 1.193297-1.199547 V; row 4f's check denominator
  317 -> 363 and its body count 3 -> 4 variants / 135 -> 180 points (the
  re-qualified `psrr-injector-candidates` record carries a fourth variant,
  `ngclamp`, that the superseded one did not -- the two unmet ceiling checks
  are still the same two, at the same corners, to the same 2.018/3.062 dB).
- One rounding correction inherited from an earlier revision, not a new
  measurement: rows 8d/8e printed `gdrv_final`'s floor as 1.598 V where both
  the superseded and the re-qualified `startup-time-post-layout` record read
  1.597262 V. It now reads 1.597 V.
- Row 8a's citation jumps **two** records, and the report says so rather than
  absorbing it. That row cited `20260909-232410-e8e2e46`; the intervening
  `20261015-133821-9f956c4` -- which the report never cited -- failed 10 of 45
  corners, and those failures do not reproduce under `f6eeac7` (see the
  `startup-stability` delta table above). The row's PASS rests on the new
  record, not on the record it skipped.
- The two benches that were **not** re-qualified now carry that reason in the
  report itself (row 1c and section 3 item 6), instead of citing a pre-pin
  record as "the newest record on disk". `monte-carlo-untrimmed`'s row is the
  one place in the report where the cited record is deliberately **not** the
  newest file in its directory, and it now says why.

Because the report's `sha256` is pinned by T1 item 8, `./signoff/regenerate.sh`
was re-run in the same change: `signoff/evidence/characterization.generic.json`,
`signoff/block-manifest.json` and `signoff/signoff-report.json` carry the new
hash and nothing else moved. The T1 verdict is unchanged at **8/11 items met**,
graded with the pinned released klayout-tools 0.8.0 wheel in a throwaway venv.

Two documentation corrections to this record's own slice C' delta table were
made in the same change, from the #516 review; both are recomputed from the
committed records and neither touches a verdict. They are described under that
table.

### Slice F -- `error-amp-offset-mc` re-qualified, and the one delta in this record that is not last-digit rounding

Slice D3 recorded this bench as blocked on a batch collector; #514 landed that
collector, and slice E recorded that the only thing still missing was the run.
This slice is that run, and it succeeded on the first submit.

Run as `run_amp_offset_mc.py --backend batch --timeout 30
--batch-capacity-wait-s 1800 --supersedes 20260817-130441-aa5324e`: 5 Monte
Carlo points (three `tt_mm` temperatures at N=300, a 30-sample MC-off control,
and a second-seed 300-sample repeat = **1 230 samples**), the **same** nominal
seed values (`20260803` / `20260804`) and the same N as the superseded record,
so the two are comparable **statistically** -- same N, same nominal seeds, but
not the same draws: the batch backend derives its own per-sample seeds from
those values rather than replaying a `setseed` loop, so the individual samples
are a different stream (see the cause bullet below). All 1 230 samples parsed;
**none excluded, none lost**.

**The `--timeout` lesson from slice D4 was load-bearing here, not incidental.**
At the runner's 7 200 s default each request declares `remote.hosts: 300` --
one host per MC sample -- so the five requests would have asked the shared spot
quota for 1 230 hosts, which is the shape that starved slices A and D3. Sizing
the per-sample budget to the analysis actually being run (an `op` solve,
`--timeout 30`) drops each 300-sample request to `remote.hosts: 3`. All five
jobs came back `klt_status: pass` with `klt_exit_code: 0`, **zero
`batch_no_capacity`, zero `lost_shard`, zero `batch_job_timeout`**. The budget
was generous rather than tight: measured per-sample remote runtime was
2.6-3.9 s against the 30 s bound. Wall clock was about 18 minutes for the whole
bench (the five requests overlap; their submit-to-collect walls sum to 71
minutes). **This is the first time this repo's `klt sim` Monte Carlo collector has
met a real fleet report** -- its tests used hand-built ones -- and it parsed all
five without a diagnostic.

**The verdict does not move: PASS, 6 of 6 cross-point checks, `budget_closure`
holding at all three temperatures.** But unlike every other slice in this
record, the numbers are **not** reproduced to the printed precision, and that is
a property of Monte Carlo rather than a result that moved:

- The **MC-off control point** (`tt_27c_3.30v_mm-off`, mismatch switched off) is
  **bit-identical** to the superseded record on every one of its nine
  measurements, mean and sigma alike. The deterministic operating point this
  bench rests on is therefore unchanged by the re-pin, which is exactly what the
  control exists to establish.
- The **mismatch points are not**. `sigma(vos)` at 27 C reads 0.6399 mV against
  the superseded 0.6254 mV (+2.3 %). The **largest** move in the record is
  `sigma(dvbe1)` at -40 C, 0.4310 -> 0.3657 mV (**-15.1 %**); seven sigma
  estimates move by more than 8 %, the next six being `dvbe1` at 27 C
  (-12.2 %), `dvbe1` on the second seed (+10.9 %), `rrb` on the second seed
  (-9.5 %), `vos` on the second seed (+8.9 %), `vgdrv` on the second seed
  (+8.7 %) and `vout` on the second seed (+8.3 %). `dvbe1` is the vector the
  `anchor_sigma` check grades against the published 0.480 mV: that ratio moves
  1.05 -> 0.92 at 27 C, well inside its 0.7-1.4 band, and the -40 C point is
  not graded against the previous record at all. `budget_closure`'s ratio moves
  1.04/1.07/1.10 -> 1.03/1.05/1.08 against its 0.7-1.4 band.
- **The cause is the backend's seeding scheme, not the model cards.** The batch
  path does not use `setseed` at all. One `klt sim` request per point replaces
  the `setseed` / `reset` / `dowhile` loop with `monte_carlo` `{n, seed}`, and
  klt derives each sample's `.options seed=` from `monte_carlo.seed` itself
  (`sim/error-amp-offset-mc/run_amp_offset_mc.py`, `build_batch_groups`
  docstring; and the new record's own `execution.note`: "per-sample seeds come
  from klt's monte_carlo seed contract, not `setseed`"). The draws are therefore
  a different -- equally valid -- stream from `setseed N` **by construction of
  the backend, on any platform**, so "same seed" does not mean "same samples"
  here. The superseded record was minted on Darwin arm64 and this one on the
  fleet's Linux x86_64, both under ngspice-47, but **whether ngspice's
  `setseed` draws are portable across platform is not measured anywhere in this
  issue**, and no such claim is needed to explain the difference. With N=300 the
  standard error on a single sigma estimate is about +/-4.1 %, and about
  +/-5.8 % on the ratio of two independent estimates, so the +2.3 % move on
  `sigma(vos)` is inside sampling noise -- but the -15.1 % move on
  `sigma(dvbe1)` is **not**, at roughly 3.7 single-estimate standard errors
  (2.6 on the ratio), and no blanket "inside two standard errors" claim holds
  across the set. This is why the bench grades seed stability with a +/-25 %
  `seed_sigma_stable` tolerance and grades `dvbe1` against a **published**
  anchor rather than against the previous record's draws. Both records pass
  `seed_sigma_stable`, on both seeds, and every `anchor_sigma` check passes.
- **Not separable here, and said rather than implied**: **three** things changed
  together between the two records -- the PDK pin, the execution platform
  (Darwin arm64 -> the fleet's Linux x86_64), and the seeding scheme (a local
  `setseed` loop -> klt's `monte_carlo` contract on the batch backend) -- so this
  run cannot attribute the residual between model-card changes and
  draw-sequence changes. Re-running the `f6eeac7` deck on the old platform would
  not settle it either, because the batch path would not reproduce the old draw
  stream there; separating the two would need the old `setseed` loop re-run
  locally at `f6eeac7`, which is not available to this issue. No conclusion in
  this record depends on the separation, because the verdict, every check and
  the budget closure are unchanged either way.

`design/error-amp-offset-budget.md` section 2's allocation table is derived from
the superseded record's sigmas and is **not** re-derived here (it is not in this
issue's reference set, and re-deriving an allocation is its own task). That doc
gains a short section 11 pointing at the new record and at this section, so it
does not read as current.

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
- **Keep the runners' default `--timeout` on the slice C'/D4 batch submits**
  - rejected: `shard_hosts()` answers a large per-unit budget with one host
  per corner, which is what starved slice A's and slice D3's runs on the
  shared spot quota. Each request here was given a budget sized from the
  bench's own measured worst corner (`--timeout 230` for C', 8x the 27.8 s
  fleet worst; `--timeout 200` for D4, ~8x its ~24 s points), which shards
  every request to a single host and still leaves the job bound under the
  3 600 s ceiling.
- **Regenerate `design/block-characterization-report.md` in this slice** -
  rejected, deferred one more slice. The re-run work is complete so the
  precondition is met, but that report is a hand-written 400-line narrative
  with no generator: "regenerate" means re-stating ~20 evidence citations and
  auditing the prose around them. Folding that into a PR that also adds five
  new records makes both halves harder to review, and this issue's execution
  rule slices by table row (the 2026-11-11 Revision lists the regeneration as
  its own row-D item). It is the next slice, and the only remaining step that
  needs neither code nor the fleet. **What is NOT deferred**: the `signoff/`
  item-5 outputs are regenerated here, because they are mechanically derived
  and `sim/tests/test_emit_klt_sim_envelopes.py` fails if they are not --
  see Consequences.

## Spec lines affected

None.

## Consequences

Scope item 5 is **complete** as of slice E. Both halves are recorded below;
the deferral the slice C'+D4 revision of this section carried is discharged.

- **The `signoff/` item-5 outputs cite the new records** (done in slice C'+D4).
  `sim/signoff-envelopes/emit_klt_sim_envelopes.py --write` re-minted the four
  envelopes whose bench moved (`output-voltage-tc-post-layout` 1b and 3b,
  `line-regulation-post-layout` 5c, `startup-ramp-post-layout` 8d) plus
  `signoff/block-manifest.json` and `signoff/pinned-inputs.json`. This is
  mechanical (the envelope selector takes the newest multi-point record whose
  netlist snapshot matches `main`'s design) and it is *required*:
  `sim/tests/test_emit_klt_sim_envelopes.py::test_committed_envelopes_are_fresh`
  fails otherwise, exactly as slices B and C re-minted their own benches'
  envelopes in the same PR as their records. No bound, limit, verdict or
  corner count changed in that diff — only the pinned record ids, their
  content hashes, and the last-printed-digit values (and the margins by the
  same delta). `signoff/signoff-report.json` needed **no** change: re-grading
  the manifest with the pinned released klayout-tools 0.8.0 grader in a
  throwaway venv still renders byte-identically ("T1 8/11 items met"), so the
  T1 verdict is unmoved by this slice.
- **`design/block-characterization-report.md` is regenerated** (slice E). Every
  row now cites the newest record under its bench directory, or states why it
  does not; no verdict, binding corner or disposition moved. Slice D3 had
  deferred this because four benches (slice C') were about to be re-qualified
  and regenerating twice would have cited a set that was about to change; C'
  ran in the previous slice, so the regenerate-twice risk was gone. Its
  `sha256` is pinned by T1 item 8, so `./signoff/regenerate.sh` was re-run with
  it — the hash propagates to three files and the T1 verdict is unchanged at
  8/11.

**Nineteen of the twenty reference benches are now re-qualified under
`f6eeac7`.** Exactly one is not, and it keeps its old record as the cited
evidence:

| Bench | Waits on | Needs code? |
|---|---|---|
| `monte-carlo-untrimmed` | #444 (open, `loom:operator`) | yes — the batch collector loses samples |

With slice E the derived artifacts are current, and with slice F the last
bench that needed only a fleet submission has one. **#370's remaining work is
exactly #444's**, which is an operator-held issue, not a scheduling matter.

Layout reports need no re-qualification (slice D3). **Nothing on this issue is
gated on fleet budget any more**, and slice F is the third independent
confirmation of why: slice D3 closed by noting that two of this
issue's slices had failed on the shared spot quota and that the remainder was
therefore a scheduling matter. The retry in slice D4 settles that — with a
per-point budget sized from the bench's own measured runtime rather than the
runner's default, 30 requests and 225 points went through with no
`batch_no_capacity` and no lost shard, and all ten C' jobs did the same. The
capacity failures were a request-shape problem as much as a quota problem.

No spec row is relaxed by any slice of this record, and no result moved outside
its tolerance because of the re-pin. Of the 345 corner points added in slice
C'+D4, 225 are bit-identical to the record they supersede and the other 120
differ only in the last printed digit. Slice F's 1 230 Monte Carlo samples are
the one exception to "bit-identical or last-digit", and the exception is
disclosed rather than smoothed: its MC-off control is bit-identical, its
mismatch draws are not (largest move -15.1 % on `sigma(dvbe1)` at -40 C, whose
`anchor_sigma` check stays well inside its band), the cause is the batch
backend's seeding scheme -- a different draw stream by construction, not a
moved measurement -- and every check, the verdict and the budget closure are
unchanged. See slice F for why the pin, the platform and the seeding scheme
cannot be separated by this run, and for the fact that they do not need to be.
