# `startup-ramp-post-layout` — divergence finding

Post-layout (`provenance: extracted`) re-run of `sim/startup-ramp`'s
supply-ramp startup-TIME claim against the ROUTED, LVS-clean
`layout/bandgap-core/` GDS (issue #62) wired to the SCHEMATIC-netlisted
`design/startup_injector.sch` (issue #10 has no layout yet for the
injector), for issue #16. Records here are append-only and are **new**
evidence — they neither overwrite nor retire `sim/startup-ramp/`'s
schematic-level records.

This file exists because issue #16 requires any divergence from the
schematic-level result to be **documented as a finding, not reconciled
away**. The divergence here is small and does not change the story the
schematic-level bench already tells: the extraction nudges a handful of
already-near-threshold `vref_spread` margins across the 0.001 V cliff, in
both directions, without changing which process corners carry the risk
(`ff`/`sf`, cold) or the overall verdict (FAIL both before and after
extraction, for the same reason).

## What the record says

Record `20260812-043245-7eb5be4` — full 45-point PVT matrix (this bench
completes a corner in about a minute even on the extracted netlist, unlike
the DC-sweep-heavy `startup-stability` bench, so the full matrix was run
rather than a worst-corner subset), `Overall: FAIL`, 12/45 corners fail.

Every corner ran to completion (no ngspice failures, no timeouts), so the
FAIL verdict is a real measured margin call, not a harness/translation
failure.

## Why a new schematic-level baseline was needed

`sim/startup-ramp/`'s existing committed records
(`20260803-115923-e599e30`, `20260803-124933-e599e30`,
`20260803-204350-f41373d`) all predate the `n_r2` resize chain (`54 -> 50`,
DR-003 close-out issue #99, PR #105/#110/#111/#113) — comparing an extracted,
current-sizing netlist against them would conflate the extraction with the
resize, the same trap `sim/line-regulation-post-layout/README.md` and
`sim/quiescent-current-post-layout/README.md` already document for their own
benches. A new same-sizing schematic-level record,
`sim/startup-ramp/records/20260812-073050-7eb5be4`, was appended for a clean
comparison (same bench, same manifest, same measurement expressions, same
commit `7eb5be4` the post-layout record itself measured against; the only
variable is the DUT body).

## The divergence: four corners flip a near-threshold `vref_spread` margin

`vref_spread` (`abs(v_s - v_g) + abs(v_s - v_f)`, the slow/fast/degenerate-
ramp final-`vref` consistency check) has a 0.001 V pass ceiling. Both records
sit close to that ceiling at several corners; extraction moves four of them
across it — three newly failing, one newly passing:

| Corner | schematic `vref_spread` | post-layout `vref_spread` | schematic verdict | post-layout verdict |
|---|---|---|---|---|
| `tt_-40c_3.63v` | 0.000747 V | 0.001205 V | PASS | **FAIL** |
| `ff_27c_2.97v` | 0.000896 V | 0.001370 V | PASS | **FAIL** |
| `sf_27c_2.97v` | 0.000855 V | 0.004149 V | PASS | **FAIL** |
| `ff_27c_3.63v` | 0.001068 V | 0.000500 V | FAIL | **PASS** |

`t_start_s` (the startup-time measurement the spec line actually cares about)
barely moves at any of the four — sub-microsecond shifts
(e.g. `tt_-40c_3.63v`: −0.301223 ms schematic vs −0.303302 ms post-layout) —
so this is a consistency-margin effect, not a startup-time regression. Every
other already-failing corner (the `ff`/`sf` cold/room cluster the schematic
baseline itself already fails) stays failing in the post-layout record too;
extraction does not introduce a new failure mode, it only nudges four corners
that were already sitting within a few hundred microvolts of the cliff.

**Net effect on the corner count**: 10/45 fail at schematic level, 12/45 fail
post-layout — a marginal, bounded widening entirely explained by the same
resistance-network perturbation (`sim/quiescent-current-post-layout/README.md`'s
star-R network, `sim/line-regulation-post-layout/README.md`'s drawn chained
array) that every other post-layout bench on this extraction already
attributes its own shifts to. No new corner class is implicated, and the
verdict (FAIL) does not change in kind — both the schematic and the
post-layout record fail for the same reason, at overlapping corners, with
this bench's own pre-existing margin problem being the root cause rather
than anything specific to extraction.

## Known gaps (not closed by this record)

- This bench's own `vref_spread` margin problem (the schematic-level FAIL at
  `ff`/`sf` corners) is a pre-existing finding at the current sizing, not
  something this record discovers — see the new baseline record
  `sim/startup-ramp/records/20260812-073050-7eb5be4` and
  `sim/startup-ramp/README.md`/`experiment.json`'s own notes for that
  history. This file documents only the *incremental* effect of extraction
  on top of it.
