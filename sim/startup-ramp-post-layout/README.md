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

## Update (2026-09-10, issue #279): re-run against the post-#193 chained-array design — margin widens further

Issue #279 re-ran this bench (and its schematic-level sibling) against the
current design after issue #193 changed `design/bandgap_core.sch`'s resistor
network (chained-array model, `n_r2` 50 → 51). New records:
`sim/startup-ramp/records/20260910-010233-e8e2e46.md` (schematic, supersedes
`20260812-073050-7eb5be4`) and
`sim/startup-ramp-post-layout/records/20260910-004925-e8e2e46.md`
(post-layout, supersedes `20260812-043245-7eb5be4`), both against the routed
layout report `layout/bandgap-core/reports/20260817-020222-13476b7/`.

Both are `Overall: FAIL`. The corner count worsened again on both
representations: schematic 10/45 → **13/45**, post-layout 12/45 → **16/45**.
Every corner in both new records ran to completion (no timeouts, no
SIGTERMs) — the FAIL verdicts are real measured margin calls.

Recomputing this README's own "four corners flip" comparison on the new
paired records: **4 corners newly fail** post-layout that pass schematic
(`tt_-40c_3.30v`, `tt_27c_2.97v`, `tt_27c_3.30v`, `tt_27c_3.63v` — all `tt`
process now, not the `ff`/`sf` cluster the prior comparison found), and **1**
newly passes (`ff_27c_3.63v`). Net effect: post-layout now fails 3 more
corners than schematic, versus 2 more in the prior cycle. `t_start_s` again
barely moves at any of the flipped corners — this remains a
`vref_spread`-consistency-margin effect, not a startup-time regression — and
every corner that already failed at both levels in the prior cycle still
fails now. No new failure mode; the same resistance-network perturbation
(`sim/quiescent-current-post-layout/README.md`'s narrowed-but-still-present
star-R finding, `sim/psrr-dc-post-layout/README.md`'s sign-flipped PSRR
shift) continues to nudge this bench's already-thin margin, this cycle
pulling in a different subset of `tt` corners rather than the `ff`/`sf` ones
seen before.

Per this repo's append-only convention, the sections above are left exactly
as written — this is a dated addendum, not a rewrite.

## Known gaps (not closed by this record)

- This bench's own `vref_spread` margin problem (the schematic-level FAIL at
  `ff`/`sf` corners) is a pre-existing finding at the current sizing, not
  something this record discovers — see the new baseline record
  `sim/startup-ramp/records/20260812-073050-7eb5be4` and
  `sim/startup-ramp/README.md`/`experiment.json`'s own notes for that
  history. This file documents only the *incremental* effect of extraction
  on top of it.

## Update (2026-09-23, issue #284 / DR-010): the `vref_spread` FAIL is root-caused, and this bench inherits the root cause too

Issue #284 root-caused the `vref_spread` failures this README has been tracking
as "this bench's own pre-existing margin problem". They are a **fixed-sample-time
artifact**, not a second operating point and not an extraction effect:
`sim/startup-stability/`'s free-running DC solve (`vref_dut`) puts the true
equilibrium **strictly inside** the interval the three startup-condition copies
span at every failing corner, i.e. the copies are converging on one point from
opposite sides at the `at=2.45e-3` sample point. Full evidence and the corrected
diagnosis: `sim/startup-ramp/README.md`'s own dated update and
`spec/decision-records/DR-010-startup-ramp-vref-spread-settling-tail.md`.

That does not change what this file already says about **extraction**: the
divergence findings above stand exactly as written. It sharpens them. If the
underlying quantity is a not-yet-settled residual rather than a settled operating
point, then "extraction nudges already-near-threshold corners across the 0.001 V
cliff in both directions" is precisely what a small perturbation to a slow
settling trajectory should look like — which is why the flipped set changed
membership between the two cycles (`ff`/`sf` in the first, `tt` in the second)
while the cluster carrying the real risk did not.

Nothing in the wrapped manifest was loosened: the 1 mV bound, the `at=2.45e-3`
sample point and the 2.5 ms window are unchanged. The manifest gained
`vref_spread_early` (informational) and `vref_converge` (bounded ≤ 1e-5 V, a new
gate asserting the spread contracts between two sample times), at zero
incremental simulation cost, and this bench inherits both because it reuses that
manifest unmodified.

### Record index update

| Record | Points | Status |
|---|---|---|
| `20260910-004925-e8e2e46` | 45 (full matrix) | **Current full-matrix result** — FAIL 16/45 on `vref_spread`. #284's manifest edit is purely additive, so every value here still stands. |
| `20260923-093126-079a778` | 2 (subset: `sf` × −40/125 °C × 3.63 V) | First post-layout record carrying `vref_spread_early` / `vref_converge`, on the extracted DUT. **Does not supersede** the row above. Its two points are a strict subset of the schematic-side record `sim/startup-ramp/records/20260923-092903-079a778`'s four (`sf`, `tt` × −40/125 °C × 3.63 V), so the two are directly comparable on the `sf` pair they share: `sf/−40 °C/3.63 V` is the global worst-case `vref_spread` corner of the whole matrix on **both** representations, and `sf/125 °C/3.63 V` is a corner where the spread is exactly 0 V, which is what exercises `vref_converge`'s 1e-5 V numerical tolerance on extracted parasitics. Narrower than the schematic side because a post-layout corner of this deck costs roughly twice a schematic one; host-capacity-limited, full-matrix re-run tracked in #303. |

This bench's script still defaults to the **full 45-point matrix**. The subset
above was taken through the `--process/--temp/--supply/--subset-reason` flags
issue #284 added to `sim/bin/post_layout_common.py`, precisely so that a
capacity-limited re-run states its reason inside the record rather than being
done by editing the runner script.

### Interaction with #285/#299 (noted after the fact)

`20260923-093126-079a778` was taken against layout record
`20260817-020222-13476b7` — the same **pre-#285** layout every other record in
this directory cites, and the freshest one at the time it ran. Issue #285 has
since drawn `design/startup_injector.sch` into the composed cell, which breaks
this bench's mixed-provenance premise (the separately netlisted schematic
injector would be a *second* one, and the bare-core control would stop being
bare), so `run_post_layout_startup_ramp.py` now **refuses** to run against a
layout that draws the injector and `sim/bin/post_layout_common.py` carries the
structural guard. Restructuring is **#299**.

Nothing above is invalidated by that: this record measures the same DUT
construction, against the same layout record, as the full-matrix record it sits
alongside, and row 8d of `design/block-characterization-report.md` carries the
superseded-layout disclosure for both. It is simply the **last** record this
bench can mint in its current shape — the `vref_converge` evidence it carries
had to be taken before #299 lands, or not at all.

## Update (2026-09-24, issue #299): the bench was restructured onto an all-extracted DUT, and the divergence comparison above is retired

The section immediately above called `20260923-093126-079a778` "the **last**
record this bench can mint in its current shape." That is what happened.
Issue #299 replaced the shape.

**Decided DUT shape: the composed cell alone, with no schematic-level
control.** This bench no longer wraps `sim/startup-ramp/`'s testbench or
manifest. It carries its own `testbench/tb_startup_ramp_pl.sch` — three
`design/bandgap_core.sym` copies (XSLOW, XFAST, XDEG) and no
`design/startup_injector.sym` anywhere in the deck, because since #285 the
extracted body supplies the injector — and its own `experiment.json`.

A schematic-netlisted bare core placed *alongside* the extracted ones was
considered and rejected: it would make the control a mixed-provenance
construction rather than a control.

### What that costs

Two measurements are gone: `vref_n` (≤ 0.95 V — the unprotected core, given
the same degenerate initial condition, must stay stuck) and `gn_n` (≥ 2.5 V —
and stuck *in the degenerate state specifically*, its mirror gate still parked
near the rail). Both were readings on the bare-core control copy `XDEGN`,
which the drawn monolithic cell cannot express.

They are not lost. `vref_n`/`gn_n` remain a schematic-level claim on report
row 8c, and `gn_n` has a direct post-layout counterpart in report row 8e:
`sim/startup-time-post-layout/`'s `gdrv_final`, measured on this **same**
composed cell from the **same** degenerate start over the full 45-point matrix
(1.598–2.611 V — pulled off the rail the degenerate state parks it on).

The control's falsifiability job inside this bench is carried by `t_start_g`
plus the runner's `require_layout_draws_injector()` precondition. `t_start_g`
is the time to leave the degenerate state; a cell with no working injector
never produces the `v(VREFG) = 1.05 V` crossing that measurement is the
difference of, and a `meas tran ... when` that finds no crossing writes no
vector, so the corner is recorded as a failure rather than reading plausibly.

### Record index update

| Record | Points | Status |
|---|---|---|
| `20260924-041313-999407b` | 45 (full matrix) | **Current result**, and the first from the restructured all-extracted bench. Layout record `20260923-070209-dbd57a9`. `Overall: FAIL` — see the breakdown below. |
| `20260910-004925-e8e2e46` | 45 (full matrix) | History. Pre-#299 mixed-provenance DUT against the pre-#285 layout record `20260817-020222-13476b7`. Superseded **in role**, not by a `Supersedes` field: it measures a different DUT construction, so it is not a baseline the row above can be differenced against. |
| `20260923-093126-079a778` | 2 (subset) | History, same reason. |

`Overall: FAIL` decomposes exactly as rows 8c/8d grade it:

- **The ratified `< 1 ms` half passes 45/45.** Worst `t_start` over all 45
  corners and all three ramp profiles is **+169 µs** (`t_start_s`,
  `ss/125 °C/2.97 V`); `t_start_f` ≤ 27.1 µs; `t_start_g` ≤ 45.6 µs and
  resolves at every single corner.
- **`vref_spread` fails 13/45**, worst 18.46 mV at `sf/−40 °C/3.63 V` — the
  DR-010 fixed-sample-time artifact, unchanged in kind. `vref_converge` passes
  45/45 (≤ 0 V everywhere), so the spread is still contracting at the sample
  point at every corner, which is the contraction gate #284 added precisely to
  distinguish "not settled yet" from "settling somewhere else".

### The divergence finding, restated for the new shape

The 2026-09-10 addendum's headline was "post-layout now fails 3 more corners
than schematic" (16/45 vs 13/45). On the restructured bench that gap
**closes**: this record fails **13/45, the same count as the schematic-level
record** `sim/startup-ramp/records/20260923-202758-81803b1`, and **12 of the 13
are the same corners** — `ff_27c_3.63v` fails at schematic and passes here,
`tt_-40c_3.30v` the reverse.

Read that carefully: it is **not** evidence that extraction got cleaner. Two
variables moved at once (the DUT construction *and* the layout record), so the
two records above are not separable, and this addendum does not claim a
separation. What it does support is the weaker, still useful statement the
earlier addenda were reaching for — the `vref_spread` failures are a property
of the **circuit's settling behaviour**, not of the extraction: with the
injector now present on both representations, the post-layout and
schematic-level benches land on essentially the same corner set at the same
count, and the residual disagreement is one corner in each direction, both
within a few hundred microvolts of the 1 mV cliff.

Nothing in DR-010 is loosened by any of this: the 1 mV bound, the
`at=2.45e-3` sample point and the 2.5 ms window are unchanged, the row stays
FAIL on that check, and the residual stays charged against issue #11's budget.

Per this repo's append-only convention, the sections above are left exactly as
written — this is a dated addendum, not a rewrite.
