# DR-012: Startup injector PSRR — the three-high stack is dead on startup margin, an `NG` clamp is the surviving half, and the certifying regression is unaffordable on the x86_64 Linux sweep hosts

- **Status**: proposed (investigation disposition + a partially-screened
  candidate, not a spec change — DR-006's `>= 60 dB` DC–1 kHz `psrr_band_min`
  floor is untouched and not relaxed, and neither is
  `sim/startup-stability`'s `itrav_min >= 1e-9 A`).
- **Date**: 2026-10-02.
- **Decided by**: Loom Builder agent (issue #315), proposing per CLAUDE.md's
  instruction that agents propose but do not unilaterally ratify. No spec change
  is proposed here.
- **Continues**: [DR-011](DR-011-startup-injector-psrr-fix-infeasible-by-resize.md)
  (issue #306's disposition: resize-only approaches empirically closed).

## Context

Issue #315 asked, in order:

1. Re-run `sim/startup-stability` at a longer `--timeout` to get a conclusive
   verdict for DR-011's three-high-reference-stack candidate, whose own
   regression run was inconclusive (`gmin` homotopy stepping past the harness's
   default timeout), not failed.
2. If a resize-only fix cannot close the 45-corner PSRR matrix without a
   `startup-stability` regression, **design a non-resize fix** for `MNI`'s
   residual GDRV conductance.
3. Redraw the layout for whatever lands, re-run DRC/LVS and the post-layout
   suite.
4. Confirm the injector stays drawn in the composed cell.

This record disposes of item 1, delivers item 2's design as a *screened
candidate*, and states exactly what blocks landing it (and therefore items 3–4).

## Part 1 — item 1's lever, priced

Item 1's premise was that the three-high candidate is *specifically* expensive:
"the DC sweep needed `gmin` homotopy stepping at nearly every sweep point for
this candidate at the colder corners, making most corners' wall-clock cost far
exceed the stock design's". Measured on this sweep host (AWS 8-vCPU x86_64
Linux, `ngspice-46`, same PDK pin, same deck `corner-run.py` generates), that
premise does not reproduce, and the real obstacle is different and much larger.

**The stock design gmin-steps at every sweep point too.** The committed record
`sim/startup-stability/records/20260909-232410-e8e2e46`'s own raw log for
`tt, -40 degC, 2.97 V` carries 251 `Dynamic gmin stepping completed` notes — one
per sweep point — on the *unmodified* schematic. Homotopy stepping at every
point is this bench's normal behaviour at cold corners, not a candidate
signature.

**Per-point cost on this host, stock design, `tt, -40 degC, 2.97 V`** (the
251-point `.dc valpha 0 1 0.004` sweep truncated to N points, otherwise the
identical deck):

| sweep points | wall clock | notes |
|---|---|---|
| 2 | 164 s | run concurrently with the 26-point case |
| 11 | 293 s | run alone; 258 s CPU, 88 % CPU, 179 MiB peak RSS |
| 26 | 765 s | run concurrently with the 2-point case |

A straight fit over 2 → 26 points gives **≈ 114 s fixed + ≈ 25 s per sweep
point**, i.e. the bench's own 251-point grid costs **≈ 6.4 ks ≈ 1.8 h for this
one corner**. The same deck, same corner, same `ngspice-46` major version took
**285.8 s** on the Darwin/arm64 host that minted the 45/45 record
(`elapsed_s` in that record's own json), and the full 45-corner matrix there
took 5409 s serial. Scaling that distribution by the measured ratio puts a full
45-corner re-run on this host class at **≈ 33 h serial, ≈ 17 h at `--jobs 2`**
(2 is the concurrency cap these shared hosts allow).

**This is not a sick host and not a sick ngspice.** One corner of
`sim/psrr-dc-with-injector` (`tt, 27 degC, 3.30 V`) run here cost 43 s wall /
30 s CPU against a 23.9 s median in that bench's own committed Linux record
`20260923-124813-af9ff1e` — ordinary 1.3–1.8x contention. The 20x gap is
specific to the 251-point `.dc valpha` sweep with per-point homotopy.

**The `ngspice` version matters more than the candidate.** This bench's own
record chain contains the controlled comparison: `20260815-032111-001d1b7`
(Darwin, **`ngspice-47`**) ran the full 45-corner matrix at **10–56 s per
corner** (≈ 700 s total), while `20260909-232410-e8e2e46` (Darwin,
**`ngspice-46`**, no schematic or testbench change in between — `git diff
e8e2e46..HEAD -- design/ sim/startup-stability/testbench/` is empty) took
44–407 s per corner. Roughly an order of magnitude, on the same deck, from the
simulator version alone. This host has `ngspice-46`.

**Candidate vs stock, measured head-to-head on this host**: run concurrently at
`--jobs 2`, the three-high candidate advanced 25 sweep points in 1380 s (55
s/point) while the stock deck advanced ~9 points in 650 s (72 s/point) at the
same corner. Within the noise of a shared host, the candidate is **not**
materially more expensive than stock.

**Disposition of item 1's lever**: "raise `--timeout` and re-run" is sound but
unaffordable here — it is a 17–33 h run on this host class, not a compute-budget
rounding error, and `--timeout 3600` would simply time out every cold corner
(each needs ≈ 6.4 ks). No *certified* 45-corner `startup-stability` verdict is
produced by this increment, for any candidate. The actionable fix is a
tooling/host change (an `ngspice-47` sweep host, or a remote/batch path for this
bench), which is a worker-spec decision, not something a Builder session can
provision; filed as **#320**.

## Part 1b — item 1's question answered anyway, by a targeted probe

The expensive thing about `sim/startup-stability` is its 251-point grid, not the
quantity issue #315 actually needed: `itrav_min`, the weakest downhill pull
anywhere in the degenerate region (`alpha` in `[0.75, 1]`). Probing **only that
window** at 11 points costs ≈ 340 s per body instead of ≈ 6.4 ks, and the method
validates against the committed record: on the stock design at
`ss, 125 degC, 2.97 V` — the matrix's **tightest** `itrav_min` corner
(6.774e-9 A, 6.8x the 1e-9 A floor, per record `20260909-232410-e8e2e46`) — the
probe returns **6.872e-9 A**, within 1.5 % of it. (`vecmin` over a sub-window can
only over-estimate the full-window minimum, so a probe value *below* the floor is
conclusive in the failing direction even though it is a coarse grid.)

Measured at that corner (orientation runs, same `--jobs 2` discipline):

| body | window `vecmin(iforce)` | vs stock | vs the 1e-9 A floor |
|---|---|---|---|
| stock (committed design) | 6.872e-9 A | — | 6.9x above |
| **`+MPC3` (three-high stack, DR-011's candidate 1)** | **6.504e-10 A** | **0.095x** | **below** |
| `+MNG` only (two-high stack kept) | 6.669e-9 A | 0.97x | 6.7x above |
| `+MPC3` and `+MNG` | 6.503e-10 A | 0.095x | **below** |

**Item 1's candidate is dead for a measured margin reason, not a convergence
one.** Extending the reference stack to three-high costs **10.6x** of the
tightest corner's eviction margin and puts it **below** the ratified floor; the
`+MNG` row isolates the cause to `MPC3` alone (`MNG` costs 3 %). The mechanism is
visible in the same numbers: in the degenerate state `NG`'s only job is to sit
near `GDRV` at essentially zero current, and a three-high stack at one-third the
per-device overdrive can no longer hold it there against the off-state leakage of
`MNS` (`W=48`) at 125 degC — so `NG` sags, `MNI`'s `Vgs` shrinks, and the
eviction current collapses from 1.56e-6 A to 4.56e-9 A at `alpha = 0.85`.

This is orientation, not evidence (a sub-window at a coarse grid, one corner),
and it does not substitute for the 45-corner record issue #315's AC asks for.
But it answers the question that AC was *for*: issue #315's own words were "if it
fails (a genuine margin regression, not just slow convergence): this candidate is
dead". It fails.

## Part 2 — and it would not have satisfied the acceptance criterion either

Independently of both the compute question and Part 1b, the three-high-stack-only candidate
cannot satisfy issue #315's own acceptance criterion ("clears `psrr_band_min`
>= 60 dB across the full 45-corner matrix"). The new bench
`sim/psrr-injector-candidates/` measures it over all 45 corners
(record `20261002-200944-fe334b1`): `ref3` passes **27/45**, worst
**30.35 dB** at `sf, -40 degC, 3.63 V` — i.e. FAIL 18/45, reproducing DR-011's
hand-run count and its 30.35 dB to two decimals, now on a committed, checked
record rather than an orientation run. Buying 17–33 h of
compute to certify the startup margin of a change that still leaves a DR-006
violation is the wrong purchase; the same compute certifies the candidate in
Part 3 instead, which clears the floor everywhere.

## Part 3 — item 2: a non-resize fix, screened across 45 corners

### What was rejected, and what each rejection measured

All numbers below are `psrr_band_min` at the two corners that bind this problem
— `ff / 125 degC / 3.63 V` (the shipped design's worst, 24.78 dB) and
`sf / -40 degC / 3.63 V` (the three-high candidate's worst, 34.79 dB shipped).
They are *orientation* runs (uncommitted scratch decks cut from the same
committed snapshot the bench uses, run by hand), not evidence — per CLAUDE.md
that distinction matters; the committed evidence is the bench record cited in
Part 4.

| candidate (no device resized) | `ff/125/3.63` | `sf/-40/3.63` | disposition |
|---|---|---|---|
| shipped design | 24.78 dB | 34.79 dB | the violation |
| `MPC1`/`MPC2` bulks moved from `VDD` to `GDRV` (body effect removed) | **18.02 dB** | 55.02 dB | **rejected — worse at the binding corner** |
| `MNI` cascoded (two series `W=10 L=0.5`, both gates on `NG`) | 38.02 dB | 53.19 dB | insufficient alone |
| three-high reference stack (`+ MPC3`) | 67.50 dB | 30.35 dB | DR-011's candidate; insufficient |
| three-high stack + cascoded `MNI` | 68.69 dB | 48.64 dB | insufficient |
| three-high stack + `MNI` in a three-high stack | 68.65 dB | 54.58 dB | insufficient |
| four-high stack + cascoded `MNI` | 68.72 dB | 48.62 dB | insufficient; stack height past 3 does nothing |
| four-high stack + `MNI` three-high | 68.67 dB | 54.56 dB | insufficient |
| **three-high stack + `MNG` (the landed candidate below)** | **67.05 dB** | **68.47 dB** | **screened PASS** |

Two things fall out of that table. First, the bulk-to-`GDRV` rewiring — the
cheapest untried lever, and the obvious one if the mechanism were supply
modulation of the stack's threshold — makes the binding corner **6.8 dB
worse**, which rules body effect out as the mechanism: referencing the bulk to
the source lowers `|Vth_p|`, the stack conducts *more*, and PSRR tracks the
stack's conduction. Second, stacking devices (either the PMOS reference or
`MNI`) has sharply diminishing returns and saturates ~5 dB short of the floor.

### Why, measured: the residual is a series path, not a device

Cutting one branch at a time out of the best stacking candidate (three-high
stack + three-high `MNI`, 54.58 dB) at its own worst corner
`sf / -40 degC / 3.63 V`, by the same cut-one-branch method
`sim/psrr-injector-attribution/` established:

| body | `psrr_band_min` |
|---|---|
| intact | 54.58 dB |
| `MNC` cut (the #52 railed-branch clamp) | 54.58 dB (exonerated again) |
| reference stack cut, `NG` tied to `VSS` | 68.47 dB |
| `MNI` stack cut | 68.35 dB |
| whole injector cut (bare-core ceiling, row 4a) | 68.30 dB |

Cutting **either** the reference stack **or** `MNI` recovers the entire ceiling.
So the cold-corner residual is not a device, it is the **series path
`GDRV -> reference stack -> NG -> MNI -> VSS`**: the stack biases `NG`, and
`MNI` converts that bias into a supply-dependent drain current out of the
amplifier's high-impedance output. No amount of stacking on either end removes
it, because each end is only half of it.

`NG` is the lever neither DR-011 nor issue #306 pulled. With `MNS` over the
diode-connected `QS` as `NG`'s only pull-down, `NG` cannot fall below that
stack's own floor once the core is running, so `MNI`'s gate stays within a few
hundred mV of its threshold at cold corners and it never fully turns off.
Issue #315 names this lever third ("re-examine whether `MNS`/`QS`'s
release-threshold tuning has any slack left that shifts `NG`'s cold-corner bias
away from `MNI`'s threshold") — the answer is that the slack is not in `MNS`/`QS`
at all, it is in giving `NG` a second pull-down that only acts once the core is
already running.

### The screened candidate — and the half of it that does not survive Part 1b

Two added devices, **no existing device resized, no always-on bias branch
added**:

1. `MPC3` — the reference stack extended from two-high to three-high, same
   `W=1 L=20` unit device, series node `GDRV -> NC1 -> NC2 -> NG`. This is
   DR-011's candidate 1, and it is what closes the hot-corner failure
   (24.78 dB -> 67.50 dB at `ff / 125 degC / 3.63 V`).
2. `MNG` — a weak NMOS (`W=1 L=20`) from `NG` to `VSS`, gate on `VSENSE`
   (i.e. the core's own `VOUT`), in parallel with the `MNS`/`QS` branch. Once
   the core is running (`VOUT ~ 1.2 V`) it holds `NG` at a few mV, so `MNI` is
   genuinely off rather than biased near threshold; during the startup traverse
   (`VOUT` below the release threshold) it is in subthreshold and its current is
   orders of magnitude below the reference stack's eviction drive.

Measured mechanism, at `ff / 125 degC / 3.63 V`: `v(NG)` reads 0.2560 V on the
shipped body and **0.0000 V** on the candidate, with `psrr_band_min` going
24.78 dB -> 67.05 dB against a 68.41 dB bare-core ceiling. At the cold corner
`sf / -40 degC / 3.63 V` the same readout is sharper: `v(NG)` = `v(NE)` =
**0.506 V** on the shipped body (NG pinned at `QS`'s VBE, `MNS` in deep triode)
and **0.000 V** with `MNG`, taking `psrr_band_min` 34.79 dB -> 68.47 dB against
a 68.30 dB ceiling.

**But `MPC3` is the half Part 1b kills.** The two devices split cleanly by role
and by cost:

| device | what it buys | what it costs (Part 1b) |
|---|---|---|
| `MPC3` | the hot corners (24.78 -> 67.50 dB at `ff/125/3.63`) | **10.6x of the tightest corner's eviction margin, below the ratified floor** |
| `MNG` | the cold-corner residual (34.79 -> 68.47 dB at `sf/-40/3.63`), and +15.7 dB at the hot corner on its own (24.78 -> 40.51 dB) | 3 % of eviction margin |

So the standing result is not "a landable fix" — it is a **characterized search
space**: `MNG` is a measured, nearly-free device that solves the residual nobody
had solved, and the hot corner now needs a remedy that is *not* reference-stack
height. What is ruled out for the hot corner, measured: stack height (3-high and
4-high both erode `NG`'s degenerate-state pull-up the same way), bulk-to-`GDRV`
rewiring (worse), and `MNI` cascoding (38.02 dB, insufficient).

## Part 4 — the screened result, including what it does not clear

Record `sim/psrr-injector-candidates/records/20261002-200944-fe334b1.md`
(45 corners x 3 variants = 135 ngspice points, `ngspice-46`, Linux x86_64,
PDK pin matched):

| variant | worst corner | worst `psrr_band_min` | corners >= 60 dB |
|---|---|---|---|
| `base` (shipped) | `ff_125c_3.63v` | 24.78 dB | 21/45 |
| `ref3` (three-high stack only) | `sf_-40c_3.63v` | 30.35 dB | 27/45 |
| **`ref3_ngclamp` (`+MPC3` and `+MNG`)** | `sf_125c_3.63v` | **65.64 dB** | **45/45** |

That 45/45 is a **PSRR screen only**, and Part 1b is why the wording matters:
the same body that clears DR-006 everywhere also carries `MPC3`, which erodes
the eviction margin below its own ratified floor. A reader who quotes the
45/45 line without Part 1b will conclude this design problem is solved. It is
not.

`base` reproduces row 4d's committed record within 0.5 dB at every corner (the
record's own `base_reproduces_cited_record` checks), so the candidate's
improvement is measured against the circuit the FAIL was recorded on, not
against a re-netlisted approximation.

**The record's own verdict is `Overall: FAIL`, and that is reported rather than
tuned away**: 315 of its 317 checks hold, and the two that do not are the
`candidate_within_bare_core_ceiling` margin checks at `sf, 125 degC, 3.30 V`
(2.018 dB below row 4a's ceiling, against a 2.0 dB bar) and
`sf, 125 degC, 3.63 V` (3.062 dB). Those are **the same two corners, to within
0.01 dB, where `sim/psrr-injector-attribution`'s record already measured
2.03 dB / 3.07 dB left unrecovered when the reference stack is cut outright** —
i.e. that residual is the second-order contributor row 4e disclosed, not
something `MNG` introduces, and it sits 5.6 dB above DR-006's floor rather than
below it. The DR-006 verdict the spec row cares about
(`candidate_clears_floor`, 45 corners) passes everywhere.

## Decision

**No circuit change lands in this increment.** `design/startup_injector.sch` is
unchanged; DR-006's 60 dB floor is unchanged and not relaxed.

Two independent reasons, either sufficient:

1. **The screened candidate contains a device that is measured to break a
   different ratified claim.** `MPC3` takes the tightest corner's `itrav_min`
   from 6.9x the floor to below it (Part 1b). `sim/startup-stability` is itself
   ratified (`spec/topology-survey.md`'s "self-starting, < 1 ms" row), and this
   repo does not trade one ratified row for another.
2. **The certifying 45-corner regression cannot be run to a conclusion on this
   host class** (Part 1), so even the `MNG`-only half — which Part 1b measures as
   costing 3 % of margin at the tightest corner — cannot be *certified* here,
   only probed. Landing a design change next to a regression check that could not
   be run is exactly what DR-011 refused.

What lands instead:

- `sim/psrr-injector-candidates/` — a candidate-screening bench and its first
  record: the same 45-corner PSRR matrix as rows 4a/4d, over candidate bodies
  **added to** (rather than cut from) the committed snapshot row 4d's own FAIL
  was measured on. It is the ADD-side counterpart of
  `sim/psrr-injector-attribution/`'s CUT-side attribution, and it is reusable
  for every future candidate.
- This record.
- Report row 4f and its revision note.

**What the next increment should start from** (stated here so it is not
re-derived): `MNG` is the surviving device — one added NMOS, no resize, +15.7 dB
at the shipped design's binding corner, the whole cold-corner residual, and 3 %
of eviction margin. The open problem is the hot corner *without* stack height.
Ruled out by measurement already: stack height 3 and 4 (eviction), bulk-to-`GDRV`
(PSRR worse), `MNI` cascoding to two and three high (insufficient: 38.02 /
53.19 dB). Not yet tried: an `m_ref` multiplicity change on the (two-high) stack
now that `MNG` holds `NG` down when running — it moves the running conduction and
the degenerate-state pull-up in *opposite* directions, which is the trade Part 1b
shows stack height gets wrong; and a release-threshold re-tune of `MNS`/`QS`
(the cell's own documented knob) now that `NG`'s floor is no longer `QS`'s VBE.

## Alternatives considered

- **Land the candidate on the PSRR evidence alone**, deferring the
  `startup-stability` regression to a follow-up. Rejected, and Part 1b shows why
  this was not a theoretical risk: a 45/45 PSRR record next to an unrun
  eviction-margin regression would have landed a change that a 340 s probe shows
  breaks the startup floor. This is the most confident-looking wrong landing
  available here, and PSRR evidence is exactly the half that does not bound it.
- **Land the three-high stack alone as a documented partial fix** (issue #315's
  own item-1 option). Rejected three times over: it still FAILs DR-006 27/45
  (Part 2), it breaks the `itrav_min` floor at the tightest corner (Part 1b), and
  its own certifying regression is unaffordable here (Part 1).
- **Land `MNG` alone** (the device that survives Part 1b) as a partial fix:
  +15.7 dB at the binding corner, 24.78 -> 40.51 dB, 3 % of eviction margin.
  Rejected for this increment: it still leaves DR-006 violated at the hot
  corners, so it buys no row verdict, and it still needs the same unaffordable
  45-corner `startup-stability` certification to be landable at all — a
  `--jobs 2` run that is 17–33 h for a change that does not close the row. It is
  the right first device for the next increment, once #320 makes that
  certification purchasable.
- **Run a reduced-grid `startup-stability`** (e.g. 26 of the 251 sweep points) and
  grade a candidate on that as *evidence*. Rejected: that manifest's measurements
  index the 251-point grid by literal position (`vecmin(ifsu[188,250])`, the
  sign-change count), so a re-gridded sweep changes what every measurement means
  — the manifest says so itself. Used only as orientation, and labelled as such
  wherever it appears (Part 1b).
- **Relax DR-006's floor** — explicitly rejected per CLAUDE.md and issue #306's
  own text; not seriously considered.
- **Raise `--jobs` above 2 to buy wall-clock** — rejected: these sweep hosts are
  shared 8-vCPU boxes running up to a dozen concurrent sweeps, and the harness's
  own record chain already contains two records (`20260803-114600` /
  `-114658`) whose 9-of-12 corner timeouts were caused by exactly that kind of
  self-contention.

## Spec lines affected

None. DR-006 (`README.md`'s PSRR row, `>= 60 dB` DC–1 kHz `psrr_band_min`) is
unchanged.

## Consequences

- Issues #306 and #315 both stay open. What is now *known* rather than open:
  DR-011's three-high-stack candidate is **dead on margin, not on convergence**
  (Part 1b — issue #315's item 1, answered); the cold-corner residual's mechanism
  and a nearly-free device that removes it (`MNG`); and that every PSRR candidate
  which clears DR-006 at 45/45 so far does so only with `MPC3` attached.
- The dangerous reading of this increment is "a fix exists, it just needs the
  regression run". It does not: Part 1b is the regression (in orientation form)
  and it says no to half the candidate.
- `design/block-characterization-report.md` rows 4b/4d/5c are **not** re-derived
  (no new record exists for the committed design — the committed schematic is
  unchanged), and row 4d continues to cite `20260923-124813-af9ff1e.md`'s FAIL
  24/45 as the current state of the row. New row 4f carries the screen.
- The layout cycle (issue #315 items 3–4) is unblocked only once a circuit change
  lands, so it stays with #315. One thing Part 1b simplifies: with `MPC3` out,
  the reference stack stays a two-device matched pair, so the
  `klt gen diff_pair` -> `klt gen mos_array` conversion #315 anticipated is
  **not** needed for an `MNG`-only change — `MNG` is a single device and becomes
  a sixth `mos_array` block, the shape the injector's other single devices
  already use, plus one more `NG` net segment.
- The compute gap is the critical path for everything above, and it is not a
  design question: a sweep host with `ngspice-47` (≈10x on this deck, per this
  bench's own record chain) would turn a 17–33 h regression into well under an
  hour.
