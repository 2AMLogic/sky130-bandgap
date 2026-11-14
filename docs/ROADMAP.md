# Roadmap

A bandgap voltage reference on the sky130 open PDK, designed and verified by AI
agents with xschem, ngspice and klayout-tools (`klt`); this file says where the
block stands and what work comes next.

Status as of 2026-11-13, `main` @ `9b100d43`. The verdict of record is
[`signoff/signoff-report.json`](../signoff/signoff-report.json), not this file;
the tracking issue is #436.

## Where it stands

Layout-complete, not spec-conformant. `klt signoff` (pinned klayout-tools 0.8.0)
grades **8 of 11 T1 items `met`**:

| T1 item | Verdict | Evidence or gap |
|---|---|---|
| 1 Design sources, 2 Layout, 9 Testbenches, 10 Repo hygiene | met | `signoff/attest/item-*.evidence.json` |
| 3 DRC clean | met | `layout/bandgap-core/reports/20260817-020222-13476b7/drc.json`; 8 rule-free layers disclosed in `signoff/README.md` |
| 4 LVS clean | met | `layout/bandgap-core/reports/20261022-070000-e6e4be0/lvs.combined.json`, 22/22 devices, 1000/1000 deterministic |
| 5 Full corner verification | unmet, `check_failed` | 14 envelopes in `sim/signoff-envelopes/`; rows 1b, 3a, 3b, 4b fail |
| 6 Monte Carlo | unmet, `undersized_sample` | 838 converged samples, no negative control declared (#435) |
| 7 Post-layout verification | unmet, `no_evidence` | a `klt pex` pilot exists in `sim/pex-native/records/20261106-pilot/` but is not cited |
| 8 Characterization report | met | `design/block-characterization-report.md` |
| 11 Power delivery (structural) | met | `layout/bandgap-core/erc/20261022-072429-9eb67913/` |

Also done:

- Reference evidence re-qualified under open_pdks `f6eeac7`: 19 of 20 benches
  (DR-021, PRs #495 to #521). Only `monte-carlo-untrimmed` still cites its
  2026-08-17 record.
- Every runner has a `--backend batch` path (#395, #398, #510), and the two
  Monte Carlo runners record every fleet job id (#523).
- The startup-injector PSRR search is recorded candidate by candidate in
  DR-011 to DR-020; no variant on `main` clears the 60 dB floor.

The failing item-5 rows, in the repo's own row numbering:

- **1b**, post-layout `vref_min` below 1.176 V at 14 of 15 corners.
- **3a / 3b**, temperature coefficient above 50 ppm/°C at every corner; kept as
  a disclosed FAIL by DR-009.
- **4b**, post-layout PSRR, worst 22.75 dB, caused by the startup injector
  (DR-011, #368, #315).

Changed since the last hand-written status: klayout-tools#2359, which the README
and `sim/output-voltage-tc-post-layout/README.md` cite as the open cause of row
1b, was closed on 2026-09-23. The post-layout benches still read the parasitics
snapshot `20260817-020222-13476b7`, extracted before that date, so row 1b has
not been re-measured on a current extraction.

## Now

1. **Bound the Monte Carlo batch request** (#528, PR #535 open with changes
   requested). Done when `build_mc_group()` refuses an over-ceiling budget and
   the default shard count is sized from the measured sample time, with tests in
   `sim/tests/`. This is the code half of the #444 shard loss.
2. **Land the three approved pull requests**: #529 (DR-021 slice G), #531
   (#525), #532 (#522). Done when each is merged and `main` CI is green.
3. **Re-extract parasitics at the pinned klt and re-measure row 1b** (no issue
   yet). Done when a new `sim/output-voltage-tc-post-layout/parasitics-snapshot/`
   directory produced by klayout-tools 0.8.0 exists, a record that supersedes
   `20261113-111050-7efdcf3b` reports `vref_min` on it, and the statements that
   call klayout-tools#2359 open are corrected to the measured outcome.
4. **Separate routing resistance from the extractor's star model in the pex
   pilot** (no issue yet). `sim/pex-native/README.md` leaves this open: the
   −27.754 mV delta is almost entirely resistor-array parasitics. Done when a
   second record under `sim/pex-native/records/` runs with
   `--critical-net VB,VBQ --distributed-rc` and the README states which share of
   the delta survives.
5. **Cite the `klt pex` pilot for item 7, or record why the grader refuses it**
   (no issue yet). Done when `signoff/signoff-report.json` item 7 no longer
   reads `no_evidence`, or when the refusal is written into `signoff/README.md`
   with a tool-gap issue filed at klayout-tools.
6. **Bring `signoff/README.md` and the README status text back in line with the
   report** (no issue yet). The item-5 row still lists 8a as failing and counts
   16 envelopes, the item-9 row names the old open_pdks pin `c6d73a35`, and the
   README says the `klt` pin is held back for klayout-tools#2374 while
   `layout/requirements.txt` pins 0.8.0. Done when each statement matches the
   committed files and `npm run check:signoff-pins` passes.
7. **Close out #432**. A routed-flow record with an artifact manifest now exists
   (`manifests/artifacts/layout-bandgap-core-20261028-063447-2c76afb7.manifest.json`).
   Done when `klt artifact verify` and `scripts/ci/check_artifact_manifests.py`
   pass on it and the issue is closed, or the remaining failure is stated there.

## Next

- **#444, real-fleet smoke run of the Monte Carlo batch path.** Unblocked by
  item 1 plus the ruling requested on the issue. Done when one N=20 record has
  every job `klt_status: ok` and no lost shard.
- **#435, a sufficiently sized untrimmed-Vref campaign with a negative
  control.** After #444. Done when the `klt yield` report reads
  `sample_size.verdict: sufficient` on all three temperatures and item 6
  re-grades.
- **#370, the twentieth bench.** After #444. Done when `monte-carlo-untrimmed`
  has a record under `f6eeac7` and DR-021 leaves "proposed".
- **#315, injector certification and the post-fix layout cycle.** After #368
  lands a circuit change that passes PSRR and startup-stability at 45/45.
- **Post-layout trim check.** After Now item 3: a `trim-lsb-chained` run on the
  extracted chain, which the README lists as not yet done.

## Later

- **Curvature correction for rows 3a/3b.** Question first: which correction
  topology fits the area left under DR-007's 0.08 mm² budget (70,360 µm² used).
- **Trim range.** The ratified row asks for ±5 %; the design trims 3.2 % down
  and 0 up. Question first: what "magnitude only" means in DR-005, which the
  report discloses as an open question that agents may not settle.
- **Row 1c, 3σ accuracy.** The mean ± 3σ window fails at all three
  temperatures on local mismatch alone. Question first: whether the #435
  campaign, combined with process corners, confirms the fail or narrows it.

## Blocked and waiting

| Item | Waiting on |
|---|---|
| #368 injector PSRR | A ruling on the standing-current budget or a further design iteration; PR #509 (DR-022) records that the flag candidate clears PSRR and fails `i_su_standing` |
| #444 | The ruling on its decision block; #528 changes the cost picture |
| #435, #370; #306, #315 | #444; #368 |
| #517 `met2_drc.py` scope | A verification-policy ruling: keep the independent re-check or delegate to `klt drc` |
| #533 | PR #532 |

Every open issue is in progress, blocked, or waiting on a ruling; the
dispatchable work today is Now items 3 to 6, which need issues filed.

## Not planned

- Relaxing a ratified spec row to make a result pass (`CLAUDE.md`). A failing
  row stays a disclosed FAIL until the design changes or a decision record
  changes the spec.
- The stretch targets in the README's spec table, the 1.8 V-core variant included.
