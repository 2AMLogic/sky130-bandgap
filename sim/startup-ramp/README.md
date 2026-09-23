# `startup-ramp` — record index

Records here are append-only (`sim/README.md`); this index is a pointer added
*alongside* them so a reader does not attribute an old record's startup times
to the current design. Same purpose and format as
`sim/output-voltage-tc/README.md` (issue #55); this one exists because of
issue #52.

**Read this before citing any record here**, and read the *per-measurement*
verdicts rather than the overall line: every record under this slug is an
`Overall: FAIL` on `vref_spread` at the two `ff/-40 °C` corners, and none has
ever failed a startup time.

| Record | Design measured | Status |
|---|---|---|
| `20260803-115923-e599e30` | Pre-#41 amp (`amp_m_in=2`) + injector without `MNC` | Superseded. |
| `20260803-124933-e599e30` | Pre-#41 amp (`amp_m_in=2`) + injector without `MNC` | Superseded by `20260803-204350-f41373d`. `Overall: FAIL` on `vref_spread` only (1.5 mV / 2.5 mV at `ff/-40 °C`). Its startup times describe an amplifier the design no longer ships. |
| `20260803-204350-f41373d` | **Shipped design: `amp_m_in=16` + injector WITH the issue-#52 railed-branch clamp `MNC`** | **Current record.** `Overall: FAIL` on `vref_spread` only (1.77 mV / 2.90 mV at `ff/-40 °C`, the same cold/fast settling tail). **Every startup time passes**: worst `t_start` over all 12 corners and all three ramp profiles is `+146 µs` (`ss/125 °C/2.97 V`, slow ramp) against the 1 ms bound; degenerate-start `t_start_g` ≤ 1.71 ns; `isup_g` 24.2–39.1 µA; both no-injector controls still stuck (`vref_n` ≤ 0.534 V against a 0.95 V bound, `gn_n` ≥ 2.94 V). Supersedes `20260803-124933-e599e30`. |

## What the vintage change cost

The `< 1 ms` spec line survives with room to spare, but the margin moved and
the record should be read that way rather than as "unchanged":

| | `20260803-124933-e599e30` (pre-#41 amp) | `20260803-204350-f41373d` (shipped) |
|---|---|---|
| worst `t_start_s` | −0.38 ms (reference up *before* the ramp finished at every corner) | **+0.146 ms** (at 125 °C the reference no longer beats the 1 ms ramp) |
| worst `t_abs_s` | 0.50 ms | **1.12 ms** (bound 2.2 ms) |
| worst `t_start_g` | 57.6 ns | 1.71 ns |
| worst `vref_spread` | 2.5 mV | 2.90 mV |

`t_start_g` — the degenerate start, which is the case the injector exists
for — *improved* by more than an order of magnitude. The slow-ramp numbers got
slower because the shipped amplifier is the large, `MCC`-compensated one from
issue #9 / PR #41, not because of `MNC`: `MNC` is off (`Vgs − Vth ≈ −2.4 V`)
along the entire startup trajectory, since `VOUT` rises toward ~1.2 V while
`GDRV` falls only to `VDD − |Vgs_p| ≥ 1.5 V` and the two never cross.

## Update (2026-09-10, issue #279): newest record is `20260910-010233-e8e2e46`

This index table predates the DR-003 chained-array resistor resize (issue
#193, `n_r2` 50 → 51) and was already one generation behind it
(`20260812-073050-7eb5be4`, itself superseded, is not listed above). Rather
than reconstruct the full intervening history here, this pointer names only
the current record: `sim/startup-ramp/records/20260910-010233-e8e2e46.md`,
re-run against the post-#193 design, `Overall: FAIL`, 13/45 corners fail on
`vref_spread` (up from 10/45 pre-#193) — see that record and
`sim/startup-ramp-post-layout/README.md`'s dated update for the full
comparison. The startup-time claim itself (the actual < 1 ms spec line) still
passes at every corner; the standing `vref_spread` FAIL below is unaffected
in kind, only in count.

## The standing `vref_spread` FAIL

It is not a startup failure and it is not new. See the `vref_spread` note in
`sim/startup-ramp/experiment.json`: it is an underdamped settling tail still
ringing at the `at=2.45e-3` sample point at the cold/fast corner, it is exactly
0 V at every 125 °C corner, and the sibling `sim/startup-stability/` sweep
reports a single DC equilibrium at both `ff/-40 °C` supplies, so there is only
one operating point to converge to. The 1 mV bound is deliberately **not**
loosened and the sample point is deliberately **not** moved; the 2.90 mV stays
charged against issue #11's budget until a record with a longer settling window
retires it.

## Update (2026-09-23, issue #284 / DR-010): the section above is superseded in its diagnosis

**Read this before the "standing `vref_spread` FAIL" section above.** That
section's diagnosis — "an underdamped settling tail still ringing at the
`at=2.45e-3` sample point at the cold/fast corner" — is **wrong about which copy
lags**, and is retained above only because this repo does not rewrite history.
Issue #284 measured it instead of inferring it.

**What it actually is.** `sim/startup-stability/`'s testbench carries a
*free-running* core+injector instance (`XDUT`, node `VREFD`, own supply, no
forcing source) and reports its **DC operating point** as `vref_dut`, at the same
45 corners. Cross-reading that against `records/20260910-010233-e8e2e46.json`
corner by corner: at all 13 corners where `vref_spread` fails, the DC equilibrium
lies **strictly inside** the interval the three transient copies span. The
slow-ramp copy `v_s` is above it at 13 of 13 (+0.13 … +2.88 mV); the fast-ramp
copy `v_f` is below it at 13 of 13 (−0.38 … −4.62 mV); the degenerate-start copy
`v_g` is below it at 12 of 13. At the worst corner, `sf/−40 °C/3.63 V`:

| | value | vs. DC |
|---|---|---|
| `vref_dut` (DC, `startup-stability`) | 1.221454 V | — |
| `v_s` (slow ramp, `at=2.45e-3`) | 1.223660 V | **+2.21 mV** |
| `v_f` = `v_g` (fast ramp / degenerate) | 1.216830 V | **−4.62 mV** |

So the three copies are not settling anywhere different — they are closing on
**one** point from **opposite sides**, and at the worst corner the *fast and
degenerate* copies carry the larger residual, not the slow one. The old wording
implied the opposite, and an earlier attempt at this issue acted on it (moving the
sample point later to give the slow copy more budget) before the measurement
above showed that targets the smaller term.

**What changed in the bench.** Nothing was loosened. The 1 mV bound, the
`at=2.45e-3` sample point and the `tran 200n 2.5m uic` window are all exactly as
they were, so records stay comparable. `experiment.json` gained three
`meas … find … at=1.45e-3` taps on the trajectory already being solved, and the
two measurements they feed: `vref_spread_early` (informational) and
**`vref_converge`** (bounded ≤ 1e-5 V) — a real gate asserting the spread
*contracts* between the two sample times, which is the claim `vref_spread`'s note
has always made and could never itself test.

**Disposition.** `spec/decision-records/DR-010-startup-ramp-vref-spread-settling-tail.md`.
The residual stays charged against issue #11's budget and rows 8c/8d of
`design/block-characterization-report.md` stay FAIL on this check — DR-010 is the
numbered, bounded exception covering it, not a waiver.

### Record index update

| Record | Points | Status |
|---|---|---|
| `20260910-010233-e8e2e46` | 45 (full matrix) | **Current full-matrix result** — FAIL 13/45 on `vref_spread`. #284's manifest edit is purely additive, so every value here still stands. |
| `20260923-092903-079a778` | 4 (subset: `sf`, `tt` × −40/125 °C × 3.63 V) | First record carrying `vref_spread_early` / `vref_converge`. **Does not supersede** the row above. Same four points as the post-layout sibling `sim/startup-ramp-post-layout/records/20260923-093126-079a778`, so the two are directly comparable. Subset because the fleet host runs a corner of this deck 20–30× slower than the Darwin arm64 machine the full-matrix record was minted on — a 10-point subset was started first and abandoned after its first corner took 37 minutes wall. Full-matrix re-run tracked in #303. |
