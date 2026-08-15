# `line-regulation-post-layout` — divergence finding

Post-layout (`provenance: extracted`) re-run of `sim/line-regulation`'s
large-signal DC line-regulation claim against the routed, LVS-clean
`layout/bandgap-core/` GDS (issue #62), for issue #16. Records here are
append-only and are **new** evidence — they neither overwrite nor retire
`sim/line-regulation/`'s schematic-level records.

This file exists because issue #16 requires documenting any divergence from
the schematic-level result as a finding, not reconciling it away. There are
two divergences and they point in opposite directions, so neither is visible
in the overall verdict alone:

1. the **line-regulation quantity itself degrades** — supply-induced shift
   ~1.46× larger on average, large-signal DC rejection down a mean 2.57 dB —
   directionally corroborating `sim/psrr-dc-post-layout/`'s finding with a
   second, methodologically independent instrument, but far more noisily
   than that record's tight −4.05 ± 0.36 dB. The spec line is never in
   danger: the worst post-layout corner still sits **755× inside** the
   24 mV limit.
2. the bench's **`vref_nom` regulation sanity guard improves** by a mean
   **+29.6 mV**, flipping the *overall* verdict from FAIL (schematic) to
   PASS (post-layout) — the opposite direction from `psrr-dc`. Separating
   the extracted netlist's 143 resistor devices from its 813 parasitic
   elements shows this is the **drawn chained array**, not the parasitics
   (which move `K = R2/R1` by only −0.2 %): a different mechanism, on the
   very same extracted netlist, from the one
   `sim/quiescent-current-post-layout/` attributed its −35.8 % Iq shift to.

## What the records say

Two records back this write-up. Both are on the same commit (`9a2360a`),
both are 15-point runs collapsing only the axis the deck sweeps internally,
and neither modifies anything that already existed:

| Record | Bench | Provenance | Overall |
|---|---|---|---|
| `sim/line-regulation-post-layout/records/20260812-015312-9a2360a` | this one | `extracted` (routed GDS) | **PASS** 15/15 |
| `sim/line-regulation/records/20260812-014944-9a2360a` | schematic-level baseline | `schematic` (`design/bandgap_core.sch`) | **FAIL** 10/15 |

The subset is `sim/line-regulation`'s own, reused unchanged: process ×
temperature in full, supply axis collapsed to the nominal 3.30 V because the
deck itself sweeps 2.97 … 3.63 V via `dc v1 2.97 3.63 0.022`, so the outer
supply axis's other two points would just re-run the identical in-deck sweep.

### Why a new schematic-level baseline was needed

The second record is a **new schematic-level run appended to
`sim/line-regulation/`**, not a modification of anything there. It exists
because the newest pre-existing schematic-level record
(`20260803-123439-497b50f`) is at the **superseded `n_r2=54` sizing**, while
both `design/bandgap_core.sch` and the routed layout are now at
`n_r1=7 / n_r2=50` (issue #99, DR-003). Comparing an extracted `n_r2=50`
netlist against an `n_r2=54` schematic record conflates the extraction with a
sizing change — and it conflates it *specifically* on `vref_nom`, which is
where the second divergence lives, so the conflation is not harmless: against
the `n_r2=54` record the `vref_nom` delta reads a modest −6.1 mV and looks
like nothing, while against the sizing-matched baseline it is +29.6 mV and
flips the verdict.

This is the same same-day-baseline pattern PR #134 used for
`sim/output-voltage-tc-post-layout/` (record
`sim/output-voltage-tc/records/20260811-231903-84ef136`); it also closes, for
this bench, the "no schematic-level record exists at the adopted chained
sizing" gap `sim/quiescent-current-post-layout/README.md` had to leave open.

### Post-layout measured ranges

| Quantity | Post-layout (extracted) | Limit | Verdict |
|---|---|---|---|
| `line_shift_mv` | 0.0109 … 0.0318 mV | ≤ 24 mV | pass, 15/15, **755×** margin at the worst corner |
| `line_reg_pct_per_v` (informational) | 0.00141 … 0.00400 %/V | none | n/a |
| `line_psrr_db` (informational) | 86.35 … 95.65 dB | none | n/a |
| `vref_nom` | 1.16706 … 1.20365 V | 1.14 … 1.26 V | pass, 15/15 |
| `sweep_start_v` / `sweep_end_v` / `n_supply_points` (guards) | 2.97 V / 3.63 V / 31 | in-window | pass, 15/15 |
| `vref_nom` spread check | 0.0366 V observed | ≥ 0.005 V | pass |
| `line_shift_mv` spread check | 0.0209 mV observed | ≥ 0.005 mV | pass |

All three in-deck sweep guards resolving is what rules out the "the sweep
silently collapsed, `line_shift_mv` read ~0 mV, and that looked like a
perfect pass" failure mode; both spread checks passing rules out a
dead/uncorner'd run.

### Reproducibility note

Two independent runs of the whole extract → translate → simulate chain were
made minutes apart on this commit by two concurrently-dispatched builder
sessions (record ids `20260812-015312` and `20260812-015457`). Their netlist
snapshots are **byte-identical** (`sha256 95b7b9db…`), and their 105 measured
scalars agree to 7 significant figures — 22 of 105 differ only in the last
printed digit. Only `…-015312` is committed (there is no evidential value in
two copies of the same 15 corner logs); the agreement is recorded here
because it is the strongest available check that the extraction, the device
translation, the body substitution and the corner loop are all deterministic.

## Divergence 1 — the line-regulation quantity degrades, but noisily

Same-corner comparison against the sizing-matched baseline (identical bench,
manifest, measurement expressions and sizing — the *only* variable is the DUT
body):

| | schematic (`n_r2=50`) | post-layout | delta |
|---|---|---|---|
| `line_shift_mv` range | 0.00687 … 0.02813 mV | 0.01089 … 0.03176 mV | mean **+0.0057 mV** (sd 0.0081), 12/15 larger |
| `line_shift_mv` per-corner ratio | — | — | 0.387 … 2.195, mean **1.46** |
| `line_psrr_db` range | 87.41 … 99.66 dB | 86.35 … 95.65 dB | −6.83 … **+8.24** dB, mean **−2.57** (sd 3.91), 12/15 degrade |

**Direction agrees with `sim/psrr-dc-post-layout/`; precision does not, and
that is expected.** That record found a strikingly tight −4.05 ± 0.36 dB on
`psrr_band_min` across all 45 corners and used the *tightness* as its main
diagnostic argument (a corner-independent dB offset is the signature of a
fixed linear network in the signal path). This bench cannot support that kind
of argument, for a reason intrinsic to what it measures:

- `psrr_dc`/`psrr_band_min` are AC small-signal quantities — one linear
  solve, the transfer function read directly.
- `line_psrr_db` here is `db(0.66 / peak-to-peak VREF)` over a **31-point
  large-signal DC sweep**, i.e. it is derived from a difference of two
  nearly-equal DC solutions **tens of microvolts apart** on a characteristic
  the manifest's own notes describe as having a *shallow interior minimum*
  near 3.45 V. Where that minimum sits, and therefore which two of the 31
  points set the peak-to-peak, moves with corner. A network that changes the
  curve's shape slightly can move the p-p by a factor of two while changing
  the local slope anywhere by a fraction of a dB.

That is also why the three corners moving the *other* way (`tt_125c`
+4.39 dB, `sf_125c` +8.24 dB, `ff_125c` +0.04 dB — all at 125 °C) are not
evidence against the mechanism: they are what a shifted shallow minimum looks
like, not a corner where the layout rejects the supply better. The
manifest's own history is the calibration for how delicate this measurement
is — its first run (record `20260803-100723-77b96e3`) reported a
0.11 … 1.27 mV shift that was entirely the DC solver's convergence noise
floor at ngspice's default tolerances, and the `line_shift_mv` spread-check
threshold had to be rescaled once the real quantity turned out to be three
orders of magnitude smaller.

So the honest reading: this bench **independently confirms the sign and rough
scale** of `psrr-dc`'s post-layout rejection loss (mean −2.57 dB here vs
−4.05 dB there, both a few dB, both on the same extracted netlist) while
being a much blunter instrument for it. It does **not** independently confirm
the *constancy* across corners that `psrr-dc-post-layout` leaned on, and it
should not be cited as if it did. `sim/psrr-dc/`'s own manifest anticipates
exactly this: `line_psrr_db` (an average slope over the full 0.66 V range)
and `psrr_dc`/`psrr_1k` (local small-signal slopes) are expected to differ by
a few dB — what they must not do is differ by *tens* of dB, and they do not.

**The spec line is not in question at either end.** `line_shift_mv`'s pass
window is the full ±1 % output-accuracy envelope (24 mV on 1.20 V); the worst
post-layout corner is 0.0318 mV, 755× inside it. A 1.46× growth on a quantity
three orders of magnitude below its bound does not threaten the claim; it is
reported because issue #16 asks for the divergence. (Per the manifest's own
claim text this bound is NECESSARY-not-sufficient: a real budget would give
line regulation a fraction of the accuracy window. Setting a dedicated
line-regulation line item was issue #1's call, and DR-005 did not add one;
these numbers are its input.)

## Divergence 2 — `vref_nom` is 29.6 mV higher post-layout, and flips the verdict

| | schematic (`n_r2=50`) | post-layout | delta |
|---|---|---|---|
| `vref_nom` @ `tt/27 °C` | 1.16519 V | 1.19335 V | **+28.16 mV** |
| `vref_nom` range | 1.12936 … 1.18116 V | 1.16706 … 1.20365 V | +22.20 … +38.50 mV, mean **+29.57** |

This is what flips the overall verdict. The schematic baseline FAILs at all
five 125 °C corners on **`vref_nom` below its 1.14 V floor** — and on nothing
else; every one of its `line_shift_mv` readings passes with the same enormous
margin the post-layout ones do. `vref_nom`'s ±5 % band is this bench's
regulation sanity guard, not the accuracy claim (that belongs to
`sim/output-voltage-tc/`), so what the flip actually says is: *at the adopted
`n_r2=50` sizing the single-device schematic model droops out of the sanity
band at 125 °C, and the extracted layout does not.*

### Attribution: `K = R2/R1` is 9.7 % higher in the layout — and it is the *drawn* array, not the parasitics

Effective DC resistances computed directly from this record's own committed
netlist snapshot (`netlist-snapshots/20260812-015312-9a2360a.spice`) by nodal
analysis. That snapshot's `bandgap_core_routed` block holds **956 resistor
elements: 143 `res_high_po` device units** (103 coarse at 2003.841367 Ω /
5 µm, 40 fine at 542.118769 Ω / 0.5 µm) **plus 813 `klt extract --parasitics`
star-R elements**, so the two contributions separate exactly — solve the
network as-is for the extracted values, then solve it again with every
parasitic R shorted (union-find node merge) for the drawn values:

| | R1 (`VB`–`VBQ`) | R2 leg (`VOUT`–`VA`) | K = R2/R1 |
|---|---|---|---|
| schematic, one device per leg, `n_r1=7`/`n_r2=50` | 11 748.8 Ω | 81 587.2 Ω | 6.9443 |
| layout as drawn, chained units, parasitics shorted | 14 026.9 Ω | 107 026.8 Ω | **7.6301** |
| layout + `klt extract --parasitics` star-R network | 18 207.9 Ω | 138 649.8 Ω | **7.6148** |

Three things fall out of that table, and the middle one is the finding:

- **The drawn decomposition, not the parasitics, moves K.** The star-R
  network inflates R1 by +29.8 % and each R2 leg by +29.6 % — almost exactly
  proportionally — so it moves K by **−0.2 %** (7.6301 → 7.6148). Contrast
  `sim/quiescent-current-post-layout/`'s finding, where that same +30 % on R1
  *is* the whole story because Iq tracks `1/R1`. The two sibling records are
  therefore probing genuinely different mechanisms of the same extraction:
  Iq's divergence is a **parasitics** effect; VREF's is a **drawn-topology**
  effect that a parasitics-free layout netlist would show just as strongly.
- **Where the drawn K comes from is arithmetic, not mystery.** Both legs draw
  the same total poly length the schematic models (R1: 7 × 5 µm = 35 µm;
  R2 leg: 48 × 5 µm + 20 × 0.5 µm = 250 µm = the schematic's `n_r2=50`
  length), but as 7 and 68 separately-contacted units. Each unit pays the
  `res_high_po` model's ~379.71 Ω head resistance once, so R1 gains 6 extra
  heads (+2 278 Ω, landing on 14 027 Ω) and each R2 leg gains 67 (+25 441 Ω,
  landing on 107 027 Ω). K rises because 68 heads and 7 heads are not in the
  ratio the poly bodies are. This is exactly the effect
  `sim/res-array-head-resistance/` and `sim/res-array-resize/` characterized
  at schematic level (DR-003, issue #99) — a real property of the drawn
  silicon, not an extraction artifact.
- The `VOUT`–`VB` leg reads 138 744.5 Ω extracted, 0.07 % off its mate — the
  two R2 legs are matched to that precision. R1 and the R2 legs reproduce
  `sim/quiescent-current-post-layout/README.md`'s independently derived
  18 208 Ω / 138 650 Ω (and its 107 027 Ω drawn figure) exactly, as they must:
  both records reuse the same shared parasitics snapshot,
  `sim/output-voltage-tc-post-layout/parasitics-snapshot/20260811-221633-a0ee5e7/`.

### The +29.6 mV is quantitatively accounted for

In this Kuijk core `VREF = V_BE + K·ΔV_BE`, so a higher K raises VREF.
Quantifying it **without assuming any device physics**, using only committed
evidence — the two schematic records at each corner differ *only* in `n_r2`
(same R1, therefore same branch current), so they give a clean two-point
secant in K:

- take `dVREF/dK` and the implied `V_BE` intercept, per corner, from
  `20260803-123439-497b50f` (K = 7.4973) and `20260812-014944-9a2360a`
  (K = 6.9443);
- re-evaluate that secant at the layout's K;
- add the one term the secant cannot see: a larger R1 means a smaller PTAT
  branch current, worth `V_T·ln(R1_schematic / R1_layout)` on `V_BE`
  (−8.8 mV at −40 °C, −11.3 mV at 27 °C, −15.0 mV at 125 °C).

Applying it in two steps isolates the two mechanisms above:

| step | mean | range over 15 corners |
|---|---|---|
| measured total (post-layout − schematic `vref_nom`) | **+29.57 mV** | +22.20 … +38.50 |
| A — drawn chained array (K → 7.6301, R1 → 14 027 Ω) | +39.52 mV | +29.98 … +50.51 |
| B — plus star-R parasitics (K → 7.6148, R1 → 18 208 Ω) | −7.97 mV | −10.21 … −5.99 |
| residual (measured − A − B) | **−1.99 mV** (sd 0.50) | −2.83 … −1.15 |

So the drawn array raises VREF by ~40 mV, the parasitics pull ~8 mV of that
back (via the −35.8 % branch current the sibling Iq record measured, not via
K), and the model lands within 2 mV — **93 % of the divergence accounted
for**, with a residual that is itself nearly constant across process and
temperature rather than scattered.

### Cross-check: the extracted core lands on the *pre-resize* schematic's VREF

Two independent quantities agree that the layout behaves like a higher-K core
than its own schematic at the adopted sizing:

- the layout's K (7.6148 extracted / 7.6301 drawn) is **+1.6 % / +1.8 %**
  above the *pre-resize* single-device schematic K of 7.4973 (`n_r2=54`), and
  +9.7 % above the `n_r2=50` schematic it is supposed to correspond to;
- post-layout `vref_nom` lands within **−8.2 … −4.2 mV (mean −6.1 mV)** of
  the *pre-resize* `n_r2=54` schematic record's `vref_nom` at every corner —
  against +22 … +39 mV versus the `n_r2=50` record it should nominally
  match. The remaining small negative offset is the lower-current `V_BE`
  term above.

The `n_r2` 54 → 50 resize (issue #99, DR-003) was derived against the chained
array in `sim/res-array-resize/`, so the layout drawing 68 units is the
intended topology, not a drafting error. What this record adds is that
`design/bandgap_core.sch` — the netlist every *other* schematic-level bench in
`sim/` still measures — does **not** carry that decomposition, so every
schematic-level `vref`-bearing record at `n_r2=50` sits ~30 mV low relative to
the silicon it is meant to represent. Whether the fix is to teach
`design/bandgap_core.sch` the chained topology or to re-derive the sizing is a
design call for the resize's own line of work — issue #99 is closed, but its
open follow-up PR #109 ("model the drawn series resistor array and resize
n_r1 7→6 / n_r2 54→42 against it", `loom:operator-decision`) is exactly the
place this belongs — not this record's. Noted here so it is not re-discovered
from scratch, and so PR #109's reviewer has a measured post-layout number to
check its proposed sizing against.

## Shared-infrastructure change alongside this record

`sim/bin/post_layout_common.py`'s `run_post_layout_experiment()` previously
only supported collapsing the runner's outer **temperature** axis
(`temp_override`, used by `output-voltage-tc-post-layout` for its in-deck
box-TC sweep). `sim/line-regulation`'s in-deck **supply** sweep needed the
symmetric case, so this record adds `supply_override` alongside it —
mechanically identical (sets `_Args.supply` instead of `_Args.temp` before
`cr.build_matrix()`), no other behavior changed.
`output-voltage-tc-post-layout`, `quiescent-current-post-layout` and
`psrr-dc-post-layout` all still resolve their existing corner matrices
identically (re-verified via `--dry-run` against all three).

## Friction filed

None new. Reuses the extraction/translation machinery and the shared
parasitics snapshot `output-voltage-tc-post-layout` (#134),
`quiescent-current-post-layout` (#137) and `psrr-dc-post-layout` (#139)
already built and filed friction for
([2AMLogic/klayout-tools#800](https://github.com/2AMLogic/klayout-tools/issues/800)).
Note that klayout-tools#800's poly double-count inflates R1 and both R2 legs
nearly proportionally, so it barely touches K and is **not** a material
contributor to divergence 2 — unlike its role in the Iq finding.

## Investigation: `fs_125c_3.30v` DC-sweep solver artifact (issue #172)

A third record, `20260815-060103-fa15a7c`, was appended for this
investigation — a plain re-run of this bench, unmodified, against the
post-#170 layout (`layout/bandgap-core/reports/20260815-034022-001d1b7`,
the same one `20260815-041348-001d1b7` measured; #170 halved
`design/error_amp.sch`'s `amp_m_in` 16→8, DR-008 Option B). It exists to
document a harness-solver finding, not a design or spec change:
`20260815-041348-001d1b7`'s `fs_125c_3.30v` corner reports
`line_shift_mv=2250.25` (limit 24) and `line_psrr_db=-10.65` — a ~296 %/V
"line regulation" figure with no physical plausibility, while every other
corner in both this record and its predecessor measures tens of µV of
shift (0.014 … 0.032 mV) consistent with the schematic-level bench at the
same corners. This section is that investigation's write-up; the flagged
record is **not** edited, retired or superseded by it — both stand as
committed evidence, per `sim/README.md`.

### Reproduction is exact, not flaky

`20260815-060103-fa15a7c`'s `fs_125c_3.30v` corner reproduces
`20260815-041348-001d1b7`'s **bit-for-bit** on all 7 of that corner's
measurements (`line_shift_mv`, `line_reg_pct_per_v`, `line_psrr_db`,
`vref_nom`, and the three sweep guards) — its netlist snapshot is
byte-identical to the flagged record's (`sha256 39474568…`, same extracted
netlist, same translation). Across the other 14 corners, 59 of 98
measurements matched exactly and the remaining 39 differ only in the last
printed significant digit (ordinary solver noise-floor jitter on a
few-tens-of-µV quantity, the same scale `sim/line-regulation/`'s own
manifest notes document). The spurious corner's value moving **zero**
digits while every clean corner's moves the expected one confirms this is
a hard, repeatable convergence outcome, not floating-point/scheduling
flakiness landing near a threshold.

### Root cause: the DC-sweep continuation solver, not the circuit

The committed corner log
(`sim/line-regulation-post-layout/corners/20260815-060103-fa15a7c/fs_125c_3.30v.log`,
and identically in `.../20260815-041348-001d1b7/fs_125c_3.30v.log`) shows
`ngspice` prints `Note: Starting dynamic gmin stepping` /
`Note: Dynamic gmin stepping completed` **exactly twice** during the
31-point sweep — i.e. standard Newton–Raphson continuation (which seeds
each new bias point's initial guess from the previous point's converged
solution) fails exactly at sweep indices 27 and 28 (`vsup` = 3.564 V,
3.586 V), and ngspice falls back to gmin-stepping homotopy to recover.
Isolated single-point `.op` solves at those same two `vsup` values, seeded
with a `.nodeset` near the surrounding plateau (`v(vref)=1.151`,
`v(gdrv)` matching the neighboring points' trend) instead of the sweep's
own continuation guess, converge on the **first** Newton iteration — no
gmin stepping needed at all — to `v(vref) = 1.151183 V` and `1.151185 V`
respectively, in line with the neighboring sweep points (1.15118150 V at
3.542 V, 1.15118738 V at 3.608 V). This refutes "genuine circuit
instability": there is one well-defined physical operating point at each
of the two bias points, and it is trivially found once the search isn't
routed through the sweep's own degraded initial guess. What gmin-stepping's
homotopy path lands on instead — reproducibly, to 6+ significant figures,
across every variant tried below — is a spurious, non-physical root near
rail level (≈3.38–3.40 V, close to `vsup` itself), not a second stable
bias point of the real circuit.

Isolated to this one process/temperature/netlist combination, checked
directly (same extracted body, only `.temp`/`.lib <corner>` varied): clean
at `fs`/−40 °C and `fs`/27 °C, and clean at 125 °C for `tt`/`ss`/`ff`/`sf`
— only `fs`/125 °C exhibits it, consistent with the flagged record's own
14/15-clean reading.

### Solver-tuning knobs tried — none move the outcome

Per the issue's own suggested next steps, each of the following was tried
against the identical deck (all other settings unchanged), independently
and re-derived by hand outside the harness (no repo file was changed for
these trials):

| Knob | Values tried | Effect on the spurious point |
|---|---|---|
| Sweep step | 0.022 V (as-recorded), 0.011 V, 0.005 V | **Not eliminated, and gets worse with resolution.** Halving to 0.011 V still triggers the fallback, now at *three* adjacent points (3.553, 3.564, 3.586 V); the finer 0.005 V step triggers it at *five* (3.545, 3.550, 3.565, 3.585, 3.590 V) — finer resolution samples the same 3.54–3.59 V region more densely, it does not avoid it. |
| `itl1` (DC op iteration limit) | default, 500 | No change — spurious value bit-identical. |
| `itl2` (DC sweep-point iteration limit) | default, 500 | No change — spurious value bit-identical. |
| `gmin` | default (1e-12), 1e-15 | No change — spurious value bit-identical. |
| `gminsteps` (homotopy step count) | default (25), 10, 50, 100, 200 | No change — spurious value bit-identical to 6 sig. figs at every step count. |
| `reltol`/`vntol`/`abstol` | this bench's tightened values (as-recorded), ngspice defaults (looser), and further-tightened | No change — the deck's `.option` tolerances (load-bearing for this bench's µV-scale resolution per `sim/line-regulation/experiment.json`'s own notes) were **not** the trigger; loosening them all the way to ngspice's defaults still reproduces the identical spurious value. |
| Direct linear solver | KLU (as-recorded, via `sim/spiceinit`), SPARSE | No change — spurious value bit-identical regardless of solver. |

The only thing that avoided it was **not** a solver-tuning parameter: a
standalone, freshly `.nodeset`-seeded `.op` per point bypasses the sweep's
continuation guess entirely (see above). Restructuring the shared,
continuous `dc v1 2.97 3.63 0.022` sweep in
`sim/line-regulation/experiment.json`'s `deck.analyses` (used unchanged by
both this bench and the schematic-level `sim/line-regulation/`) into a
scripted per-point reseed loop was evaluated and rejected as
disproportionate: it would change how every one of this bench's 31 points
at every corner is solved (not just the two affected ones), for a shared
manifest two benches depend on, to correct 2 of 465 total post-layout
sweep points (31 × 15) that already fail loudly and visibly rather than
silently reporting a plausible-looking wrong number.

### Disposition: acceptance criterion (b)

Per issue #172's acceptance criteria, this is **(b): a genuine, narrow
convergence-basin sensitivity that solver tuning cannot cleanly avoid** —
with the precision that "genuine" describes the *solver's* behavior, not
the circuit's. The physical operating point at both affected bias points
is single-valued, well-behaved, and matches its neighbors; what is narrow
and untunable (against every knob in the issue's own suggested-next-steps
list) is the DC-sweep continuation's basin of attraction into gmin-stepping
homotopy's alternate root, specific to the `fs`/125 °C corner of the
post-#170 (`amp_m_in=8`) extracted netlist. No design, spec, or
shared-harness-tolerance change was made. Two things independently limit
the blast radius of leaving this untuned:

- `line_shift_mv`'s pass window is 24 mV; every genuinely-measured point in
  this bench (including the other 14/15 corners here and the two
  nodeset-seeded points confirmed above) sits three to four orders of
  magnitude inside it — an artifact landing near `vsup` itself is not a
  quiet near-miss, it is a loud, self-flagging outlier.
- `sim/psrr-dc-post-layout/` — the metric issue #170 actually targeted —
  measures the same physical quantity via a small-signal AC analysis
  around a single `.nodeset`-seeded bias point (a different solve path
  that never invokes DC-sweep continuation) and converged cleanly with a
  plausible value at this exact corner, so #170's PSRR-margin claim is
  unaffected by this finding.

Any future reader of `fs_125c_3.30v` FAILing in either
`20260815-041348-001d1b7` or `20260815-060103-fa15a7c` should treat it as
this documented, instrumented solver artifact, not a line-regulation
regression — and a future attempt at eliminating it should start from "a
scripted per-point `.nodeset` reseed replacing the shared continuous `.dc`
sweep" (the one approach confirmed to work here), understanding that it is
a `deck.analyses` architecture change affecting both benches, not a
one-line tuning knob.

## Known gaps (not closed by these records)

- `line_psrr_db`'s scatter is *characterized* (a p-p readout on a
  shallow-minimum characteristic) but not *decomposed*: these records do not
  show, per corner, where on the 2.97–3.63 V sweep the minimum sat before and
  after extraction. The corner logs carry only the deck and the evaluated
  scalars, following `sim/line-regulation/`'s own manifest, so a shape
  comparison of the two DC characteristics would need a re-run with a
  `write`/vector dump added to the deck — the same gap
  `sim/psrr-dc-post-layout/README.md` records for its AC sweep.
- `line_shift_mv`'s per-corner delta is reported but not attributed to a
  mechanism. At 5.7 µV mean on a 24 mV limit this is close enough to the
  measurement's own documented resolution history that isolating it would be
  chasing solver-scale variation, not circuit information; the measurement
  that *is* sensitive enough to the same underlying mechanism is
  `line_psrr_db`, and `psrr-dc-post-layout` already characterizes that one in
  depth.
- The K attribution explains 93 % of the `vref_nom` shift; the residual
  −1.99 ± 0.50 mV is left unattributed rather than absorbed into a fitted
  parameter. Candidates not separated here: the dropped `res_high_po` bulk
  terminal (a documented first-order simplification of the translation, see
  `sim/bin/post_layout_common.py`), finite-beta base-current loading that the
  two-point secant folds into its intercept, and the star-R network's effect
  on the amplifier's own bias legs.
- `sim/line-regulation/experiment.json`'s `claim` string still says the
  target spec is a draft "PROVISIONAL until issue #1 ratifies it". DR-005
  ratified the spec on 2026-08-11 but did **not** add a dedicated line
  regulation line item, so this bench's bound remains the derived ±1 %
  envelope it always was. The manifest is the schematic-level experiment's
  and is deliberately **not** edited here (both records reuse it unchanged so
  the two are comparable), so both inherited claim heads carry the stale
  wording. No verdict depends on it.
