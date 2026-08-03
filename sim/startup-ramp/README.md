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
