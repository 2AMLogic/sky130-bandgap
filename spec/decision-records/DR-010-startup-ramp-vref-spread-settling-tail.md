# DR-010: `startup-ramp`'s `vref_spread` FAILs are a fixed-sample-time artifact, not a startup-time failure — bound kept, convergence gated directly, residual disclosed as a bounded exception

- **Status**: proposed. **No ratified spec row, and no bound anywhere in `sim/`,
  changes** — see "Spec lines affected". This record exists because issue #284
  asked for the disposition of a standing, measured FAIL to be written down with a
  number rather than left in a testbench comment, and because it *corrects* a
  diagnosis that `sim/startup-ramp/experiment.json` and
  `sim/startup-ramp/README.md` have both been asserting since issue #11.
- **Date**: 2026-09-23.
- **Decided by**: Loom Builder agent (issue #284).
- **Relates to**: [DR-005](DR-005-ratify-target-spec.md) (ratifies the
  "Startup: self-starting, < 1 ms" row this bench serves), issue #10 (the
  injector and this bench), issue #11 (the ±1 % accuracy budget the residual is
  charged against), issue #178 / PR #193 (the `n_r2` 50 → 51 chained-array resize
  that widened the FAIL count 10 → 13 of 45), issue #279 (the post-#193 re-runs
  that recorded the widening), issue #284 (this record).

## Context

`design/block-characterization-report.md` rows 8c/8d grade the ratified Startup
row against `sim/startup-ramp/` and `sim/startup-ramp-post-layout/`. Both read
**FAIL** — 13 of 45 corners schematic (`20260910-010233-e8e2e46`), 16 of 45
post-layout (`20260910-004925-e8e2e46`), up from 10 and 12 pre-#193 — and in
every record either bench has ever produced, **every failing corner fails on
`vref_spread` and on nothing else**. No `t_start_s` / `t_start_f` / `t_start_g`
measurement has ever failed: the worst startup time on record is `+146 µs`
against a 1 ms bound.

`vref_spread` is `abs(v_s - v_g) + abs(v_s - v_f) <= 1 mV`, where `v_s`, `v_f`
and `v_g` are the settled `vref` of three copies of the DUT simulated in one
transient — slow supply ramp (`t_slow = 1 ms`), fast ramp (`t_fast = 1 µs`) and
degenerate zero-current start — each sampled at a **fixed** `at=2.45e-3`. Its
stated purpose is to assert that the three startup conditions converge to the
*same* operating point.

Two things forced this record:

1. **The bench's own standing diagnosis was wrong.** Since issue #11 the
   `vref_spread` note (and `sim/startup-ramp/README.md`, which repeats it) has
   said the FAILs are "an underdamped settling tail still ringing at the
   `at=2.45e-3` sample point at the cold/fast corner", and has deferred acting:
   "the sample point is deliberately NOT moved: until a record with a longer
   settling window retires it, the 2.90 mV stays charged against issue #11's
   budget." That framing attributes the residual to the **slow-ramp copy**. It
   is not what the numbers say (below).
2. **Rows 8c/8d read the FAIL as a failure of the `< 1 ms` line.** The row's
   Target column folds `vref_spread` in alongside `t_start`, so a `vref_spread`
   FAIL is reported as the ratified Startup row failing — which is not what the
   ratified row states.

## Investigation

### 1. What the ratified row actually binds

DR-005's Startup row is "self-starting, < 1 ms". Its two halves are verified by
two benches and both **pass**:

| Half of the ratified row | Bench | Result |
|---|---|---|
| self-starting / no other stable state | `sim/startup-stability/` (`ncross_su = 1`) | **PASS 45/45** (`20260909-232410-e8e2e46`) |
| startup time `< 1 ms` | `sim/startup-ramp/`'s `t_start_s/f/g` | **PASS at every corner of every record** |

`vref_spread` is neither half. It is an extra consistency check this bench
invented on top of them, with a 1 mV bound no ratified row states. That does not
make it optional — it catches a real failure mode — but it does mean the report
must grade it *alongside* the ratified row, not *as* it.

### 2. The decisive measurement: a DC operating point, not another transient

The question "have the three copies converged to the same operating point?"
cannot be answered by comparing three unsettled transients to each other. It can
be answered by comparing them to the operating point itself — and this suite
already measures that, at the same 45 corners, with an entirely different
analysis. `sim/startup-stability/`'s testbench carries a **free-running**
core+injector instance (`XDUT`/`XSU`, node `VREFD`, its own supply `VDDA`, no
forcing source attached) and reports its DC solution as `vref_dut`.

Cross-reading `sim/startup-stability/records/20260909-232410-e8e2e46.json`
against `sim/startup-ramp/records/20260910-010233-e8e2e46.json`, corner by
corner, at the 13 corners where `vref_spread` fails:

| corner | DC `vref_dut` (V) | `v_s − DC` (mV) | `v_f − DC` (mV) | `v_g − DC` (mV) | `vref_spread` (mV) |
|---|---|---|---|---|---|
| `tt/−40 °C/3.63 V` | 1.216881 | +0.19 | −0.38 | −0.38 | 1.152 |
| `ff/−40 °C/2.97 V` | 1.216442 | +0.83 | −0.43 | −0.42 | 2.509 |
| `ff/−40 °C/3.30 V` | 1.216889 | +0.76 | −0.86 | −0.86 | 3.245 |
| `ff/−40 °C/3.63 V` | 1.217440 | +0.67 | −1.39 | −1.39 | 4.120 |
| `ff/27 °C/2.97 V` | 1.210913 | +0.30 | −0.70 | −0.77 | 2.064 |
| `ff/27 °C/3.30 V` | 1.211211 | +0.27 | −0.89 | −1.11 | 2.542 |
| `ff/27 °C/3.63 V` | 1.211823 | +0.13 | −0.73 | −0.50 | 1.485 |
| `sf/−40 °C/2.97 V` | 1.218114 | +2.88 | −1.31 | −1.31 | 8.391 |
| `sf/−40 °C/3.30 V` | 1.219604 | +2.61 | −2.79 | −2.79 | 10.799 |
| `sf/−40 °C/3.63 V` | 1.221454 | **+2.21** | **−4.62** | **−4.63** | **13.661** |
| `sf/27 °C/2.97 V` | 1.214204 | +0.78 | −2.10 | +0.20 | 3.451 |
| `sf/27 °C/3.30 V` | 1.214962 | +0.70 | −2.70 | −2.64 | 6.736 |
| `sf/27 °C/3.63 V` | 1.215828 | +0.61 | −3.64 | −2.00 | 6.865 |

**The DC equilibrium lies strictly inside the interval the three copies span, at
all 13 failing corners.** The slow-ramp copy is above it at 13 of 13; the
fast-ramp copy is below it at 13 of 13; the degenerate-start copy is below it at
12 of 13 (`sf/27 °C/2.97 V` sits +0.20 mV above). The three copies are not
disagreeing about where to go — they are **closing in on the same point from
opposite sides**, and at the worst corner it is the *fast/degenerate* pair that
carries the larger residual (−4.62 mV) and the slow-ramp copy the smaller
(+2.21 mV).

That is the correction this record makes: the pre-#284 diagnosis ("an
underdamped settling tail", implicitly the slow copy's) had the sign of the
effect and the identity of the lagging copy wrong. The conclusion it reached —
"not divergent operating points" — was right, but it was an inference from
`ncross_su = 1` rather than a measurement of the three copies themselves.

### 3. The premise is independently established, not assumed

`sim/startup-stability/` sweeps `GDRV` over the full `0..VDD` range and reports
`ncross_su = 1` at all 45 corners, including every corner above. Its own manifest
frames that sweep as "the arbitrarily-slow-ramp limit … a supply ramp slower than
every time constant in the loop is quasi-static", i.e. a strictly stronger
statement than any finite-rate ramp can make. So a second stable operating point
is excluded by a separate bench, and a nonzero `vref_spread` at a finite sample
time can only be a **not-yet-arrived** measurement.

### 4. How long a window would actually be needed

A 10-corner sensitivity run (this issue, discarded scratch) moved every `at=`
sample point `2.45e-3 → 3.40e-3` with the `tran` window extended `2.5m → 3.45m`,
i.e. +38 % simulation time per corner, and re-measured:

| corner | `vref_spread` at `2.45 ms` | at `3.40 ms` | change |
|---|---|---|---|
| `tt/−40 °C/2.97 V` | 0.700 mV | 0.521 mV | −26 % |
| `tt/−40 °C/3.30 V` | 0.908 mV | 0.708 mV | −22 % |
| `tt/−40 °C/3.63 V` | 1.152 mV (**FAIL**) | 0.955 mV (**PASS**) | −17 % |
| `tt/27 °C/2.97 V` | 0.625 mV | 0.465 mV | −26 % |
| `tt/27 °C/3.30 V` | 0.980 mV | 0.818 mV | −17 % |
| `tt/27 °C/3.63 V` | 0.874 mV | 0.629 mV | −28 % |
| `tt/125 °C` (×3) | 0.000 mV | 0.000 mV | — |
| `ss/−40 °C/2.97 V` | 0.201 mV | 0.146 mV | −27 % |

A 38 % longer window buys a ~17–28 % spread reduction and clears **one** of the
13 failing corners — the marginal one.

**And the tail flattens, which is the part that settles the question.** The new
`vref_spread_early` tap measures the contraction over the *earlier* interval
`1.45 → 2.45 ms` on the same corners (records
`sim/startup-ramp/records/20260923-092903-079a778`,
`sim/startup-ramp-post-layout/records/20260923-093126-079a778`):

| corner | representation | `1.45 ms` | `2.45 ms` | contraction |
|---|---|---|---|---|
| `sf/−40 °C/3.63 V` (worst overall) | schematic | 22.740 mV | 13.661 mV | −39.9 % |
| `sf/−40 °C/3.63 V` (worst overall) | post-layout | 27.506 mV | 16.746 mV | −39.1 % |
| `tt/−40 °C/3.63 V` (marginal) | schematic | 2.016 mV | 1.152 mV | −42.9 % |
| `sf/125 °C/3.63 V` | both | 0.000 mV | 0.000 mV | — |

Put the two intervals side by side at the **same** corner, `tt/−40 °C/3.63 V`:
**−42.9 %** over `1.45 → 2.45 ms`, then only **−17 %** over `2.45 → 3.40 ms`. The
decay is markedly slower than exponential — an exponential fitted to the early
interval would predict clearing 1 mV a few milliseconds later, and the measured
later interval shows it does not. So extrapolating a specific required window is
not meaningful, and this record deliberately does not quote one. What the two
intervals *do* establish is the shape of the trade: each additional millisecond
of window costs ~40 % more simulation time on 45 corners × 4 simulated copies ×
2 representations and removes a **shrinking** fraction of a residual that starts
at 13.7× (schematic) and 16.7× (post-layout) over bound at the worst corner. No
*proportionate* window closes this, and that is the finding — not a number.

## Decision

**Four parts. Nothing is loosened.**

1. **The 1 mV `vref_spread` bound is kept, unchanged, and stays graded.** The
   bound is not shown to be wrong. The evidence above shows the *instrument* is
   wrong for it — a fixed-time sample of an unsettled transient — not the
   requirement. Loosening it to a number the artifact fits would hide a real
   consistency property behind a wider bound, which is the move this repo's
   `CLAUDE.md` forbids.
2. **The sample point, the `tran` window and every deck parameter are kept
   unchanged.** `at=2.45e-3` / `tran 200n 2.5m uic` stay exactly as they were, so
   the new records are directly comparable to `20260910-010233-e8e2e46` and
   `20260910-004925-e8e2e46` rather than being a differently-sampled quantity
   that happens to read lower. See "Alternatives considered".
3. **The convergence claim is now gated by the bench itself, at zero incremental
   simulation cost.** `sim/startup-ramp/experiment.json` gains three
   `meas tran … find … at=1.45e-3` taps (`v_s1`/`v_f1`/`v_g1`) on the trajectory
   already being solved, and the two measurements they feed:
   - `vref_spread_early` — the same spread expression sampled 1 ms earlier.
     Informational (deliberately unbounded).
   - `vref_converge` = `vref_spread − vref_spread_early`, **bounded `<= 1e-5 V`**.
     A negative value is convergence. This is the gate `vref_spread`'s note has
     always *claimed* to be: if the three startup conditions were settling toward
     genuinely different operating points, this difference would be zero or
     positive no matter how long the window, whereas a fixed-time magnitude check
     cannot distinguish "diverged" from "not yet arrived". The 1e-5 V (10 µV)
     tolerance rather than exactly 0 V is because at the 125 °C corners both
     samples are already at the deck's print resolution, so the sign of a
     sub-10 µV difference there is numerical; 10 µV is 1 % of the `vref_spread`
     bound and two orders below the ≥ 1 mV contraction measured at failing
     corners.
4. **The residual is disclosed as a bounded, characterized exception, and the
   number of that exception is this record, DR-010.** Concretely, what DR-010
   permits is narrow and stated in full:
   - **What**: `sim/startup-ramp/`'s and `sim/startup-ramp-post-layout/`'s
     `vref_spread` measurement may read over its 1 mV bound.
   - **Where**: at the cold/skewed corner cluster — `ff` and `sf` process, and
     `tt` at −40 °C/3.63 V — and nowhere else. `ss`, `fs` and every 125 °C corner
     are inside bound and stay that way.
   - **How much**: bounded by the recorded worst case, `13.661 mV` schematic and
     `16.746 mV` post-layout in the pre-#284 records; the post-#284 records named
     in "Consequences" carry the current figures.
   - **On what evidence**: the DC-equilibrium bracket in §2 plus `ncross_su = 1`
     at all 45 corners, i.e. the copies provably share one equilibrium and are
     measurably contracting toward it (`vref_converge`).
   - **What it does NOT cover**: any `t_start_*` measurement (all pass), any
     `vref_converge` failure (that would be a real finding, not this exception),
     and any spread at a `ss`/`fs`/125 °C corner. It also does not retire the
     charge: the residual stays charged against issue #11's ±1 % accuracy budget
     exactly as before, and rows 8c/8d stay **FAIL**.

This record does not ask for the rows to be reported as PASS. It asks for them to
be reported as what they are: the ratified `< 1 ms` line substantiated at every
corner, with a named, bounded, understood consistency-check exception alongside
it.

## Alternatives considered

- **Loosen the 1 mV bound to fit the measured spread.** Rejected. The bound is
  not the thing that is wrong, and `CLAUDE.md` is explicit that agents do not
  relax a ratified spec — or, by the same logic, a testbench bound — to make
  results pass.
- **Extend the `tran` window / move the sample point later** (the approach an
  earlier attempt at this issue took: `2.5m → 3.45m`, `at=2.45e-3 → 3.40e-3`).
  Rejected on the measured evidence in §4: +38 % simulation cost per corner on
  both representations to clear 1 of 13 corners, while making the new records
  non-comparable with the ones they supersede. It is also a fix aimed at the
  wrong copy — that attempt justified the shift as giving the *slow-ramp* copy
  the settling budget the fast copies already had, but §2 shows the fast and
  degenerate copies carry the larger residual at the worst corner, so an
  absolute-time shift does not target the dominant term.
- **Sample each copy at a fixed offset from its own supply-arrival crossing**
  (`at = t_vdd_x + margin`) instead of one absolute time. Rejected for this
  increment for the same reason: it equalizes settling budgets more exactly, but
  §2 shows the budgets are not what dominates, and it adds deck complexity ngspice
  `meas` does not express cleanly. Left as a possible future refinement.
- **Drop `vref_spread`, on the grounds that `startup-stability` already proves a
  single equilibrium.** Rejected. A DC sweep cannot see a startup circuit that
  stays partly engaged on one ramp profile and not another for a bounded time —
  that is a transient property, and it is exactly what this measurement is for.
  Keeping it graded, and adding `vref_converge` next to it, is strictly more
  coverage than either alone.
- **Redesign the injector / loop to shorten the recovery.** Out of scope for an
  investigation-and-methodology issue, and not indicated: the residual is a
  settling time at a cold corner, not a defect, and the ratified startup-TIME
  claim is unaffected by it. If the block ever needs `vref_spread` genuinely
  inside 1 mV at those corners, this is the lever — not the bench.

## Spec lines affected

**None.** `spec/topology-survey.md`'s "Startup: self-starting, < 1 ms" row and
DR-005's ratification of it are untouched, as is every row of the target-spec
table in `README.md`. No `min`/`max` on any existing measurement in
`sim/startup-ramp/experiment.json` changes, and no deck parameter, sample point or
analysis window changes. The manifest edit is purely additive: three new `meas`
taps and two new measurements.

What *does* change is `design/block-characterization-report.md` rows 8c/8d — not
their verdict (still **FAIL**), but their wording: the Target column is split so
the ratified `< 1 ms` half is graded separately from the bench's own
`vref_spread` consistency check, and the Verdict column names this record as the
bounded exception covering the latter.

## Consequences

- `sim/startup-ramp/` and `sim/startup-ramp-post-layout/` are both re-run against
  the current design (the post-layout wrapper reuses this manifest unchanged, so
  one edit reaches both). New records:
  `sim/startup-ramp/records/20260923-092903-079a778` (4 points: `sf`, `tt` ×
  −40/125 °C × 3.63 V) and
  `sim/startup-ramp-post-layout/records/20260923-093126-079a778` (2 points: the
  `sf` pair of the same four — a strict subset, so the two are comparable on the
  corners they share).
- **Those two records are deliberately SUBSETS and deliberately do NOT supersede
  the full-matrix records.** `20260910-010233-e8e2e46` (45 points, FAIL 13/45) and
  `20260910-004925-e8e2e46` (45 points, FAIL 16/45) remain the current
  full-matrix result for every measurement they already carry, because this
  record's manifest edit is purely additive and changed no existing measurement,
  bound, deck parameter or sample point — so no value in them can have moved. The
  new records exist to carry first evidence for `vref_converge`, and each states
  its own subset reason in full. Why a subset: the full-matrix records were minted
  on a Darwin arm64 host at 53 s (schematic) / ~105 s (post-layout) per corner;
  the shared Linux x86_64 fleet host this issue ran on, under concurrent load from
  several repos' agents, took 20–30 minutes per schematic corner and over half an
  hour per post-layout corner, with one corner hitting a 1800 s timeout outright.
  A full-matrix re-run on faster or uncontended hardware is tracked in **#303**,
  which also carries the "give `corner-run.py` a parallel-corner mode" follow-up.
  Until it lands, rows 8c/8d carry two citations each — the full-matrix record for
  the corner counts, the subset record for the convergence evidence.
- `sim/bin/post_layout_common.py` gains `--process` / `--temp` / `--supply` /
  `--subset-reason` passthrough (previously only `corner-run.py` had them), so a
  post-layout bench whose runner script declares a full matrix can be re-run over
  fewer points **with the reason written into the record** instead of by editing
  the script. Defaults are unchanged, and an axis a bench's own script pins
  deliberately is refused from the command line rather than silently overridden.
- Per-corner simulation cost is **unchanged** — the new taps read a trajectory
  already being solved.
- **The additivity claim is verified, not asserted.** On the four (schematic) and
  two (post-layout) corners the new records share with the full-matrix ones, every
  measurement reproduces **bit-identically** except `t_start_f` at
  `sf/−40 °C/3.63 V`, which differs by 1 ps (schematic) / 5 ps (post-layout) —
  interpolation round-off against a 1 ms bound — even though the new runs were made
  on a different OS and architecture (Linux x86_64 vs Darwin arm64). So the new taps
  perturbed nothing, and the full-matrix corner counts stand without re-derivation.
- Every future record of these two benches carries a per-corner contraction
  (`vref_spread_early` → `vref_spread`), so the "is it converging or is it stuck"
  question is answerable from the record itself instead of by cross-reading a
  second bench. The cross-bench DC comparison in §2 stays the stronger evidence
  and is cited from the manifest, but it is no longer the *only* evidence.
- The residual stays charged against issue #11's ±1 % budget. Rows 8c/8d stay
  FAIL, and the block's Startup row stays **mixed**, not a clean PASS — this
  record makes the mixture legible, it does not dissolve it.
- `vref_converge` is a new way for these benches to fail. That is deliberate: a
  corner where the copies stop contracting would be a genuine finding about the
  injector, and it would no longer hide inside a `vref_spread` number that a
  reader could dismiss as "the known settling artifact".
- The bad consequence: this record leaves a real, measured 1 % -of-output
  condition-dependence at the cold/skewed corners uncorrected, and explicitly
  declines to chase it with simulation time. If the block ever needs
  `vref_spread` genuinely inside 1 mV at those corners, the lever is the design
  (injector residual / loop recovery), not the bench, and that is tracked
  separately rather than folded in here.
