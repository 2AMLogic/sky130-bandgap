# `output-voltage-tc` — record index

Records here are append-only (`sim/README.md`); this index is not a substitute
for that convention, it is a pointer added *alongside* the records so a reader
who lists `records/` newest-first does not misattribute the newest record's
`FAIL` verdict to the shipped design. See issue #55 for why this file exists.

**Read this before citing the newest record.** The newest record id is **not**
always the shipped `design/bandgap_core.sch` — one entry below is a rejected
sizing candidate, kept only as evidence for the investigation that rejected it,
and several measure sizings that have since been superseded. The shipped
sizing today is `n_r1=7`, `n_r2=51` with the chained-array resistor model
(issue #178); the standing record for it is `20260817-015751-13476b7`.

| Record | Design measured | Status |
|---|---|---|
| `20260817-015751-13476b7` | **Shipped core, `n_r2=51`, chained-array resistor model (issue #178).** | **Standing untrimmed accuracy/TC result for the shipped design.** 45/45 corners. DR-005's ratified untrimmed accuracy row (`vref_27`/`vref_min`/`vref_max` inside 1.176–1.224 V) **PASSes at every corner** — worst `vref_min` 1.18603 V and worst `vref_max` 1.21780 V, both at `fs`, i.e. 10.0 mV / 6.2 mV inside the window. `Overall: FAIL` is entirely the `tc_ppm` row: box TC 142.4–159.0 ppm/degC, 45/45 FAIL vs DR-005's `< 50 ppm/degC`, binding corner `fs`. That range **is** this core's measured untrimmed TC floor with the ratio lever exhausted — see issue #46's device-level root cause (Q1 `nf=1.028` vs Q2 `nf=1.000`) and issue #179 for the spec-side routing. |
| `20260816-084351-69a8867` | Pre-#178 core, `n_r2=50`, **single-device** resistor model | Superseded by the row above. First record graded against DR-005's ratified bounds (issue #177). `Overall: FAIL` on both rows: `vref_27` 1.16513–1.16679 V (below the 1.176 V floor at all 45 corners) and TC 250.1–268.4 ppm/degC. Both are the signature of the schematic modelling one `res_high_po` device per leg while the routed layout chains 143 of them (DR-003) — issue #178 closes that modelling gap rather than sizing around it. |
| `20260815-030801-001d1b7` | Pre-#178 core, `n_r2=50`, single-device model | Superseded. Same design as the row above, graded against the *draft* ±1% bounds. |
| `20260811-231903-84ef136` | Pre-#178 core, `n_r2=50`, single-device model | Superseded. |
| `20260803-102002-32194bc` | Pre-#99 core, `n_r2=54`, single-device model | Superseded (was the shipped design until issue #99). `Overall: FAIL` — untrimmed TC ~161–171 ppm/degC vs the draft's < 50 ppm/degC target; expected, trim is issue #13. |
| `20260803-115356-7759435` | Pre-#99 core, `n_r2=54`, single-device model | Superseded by `20260817-015751-13476b7` (was the standing untrimmed-TC result until issue #178). Supersedes `20260803-102002-32194bc` (re-run on a clean tree). `Overall: FAIL` — untrimmed TC 152.9–169.3 ppm/degC, 15/15 corners FAIL vs the draft's < 50 ppm/degC target; no regulation-collapse corners. It was the number to cite for "what is the shipped core's untrimmed TC" until issue #178; note it measures the *single-device* resistor model, i.e. a topology the routed layout does not build (DR-003). |
| `20260803-142220-b24b404` | **Rejected candidate, `n_r2=55`, NOT the shipped design.** | Recorded from a working tree mid-way through issue #46's investigation, before `n_r2` was reverted to 54. `Overall: FAIL`, including two corners (`ff/2.97 V`, `fs/2.97 V`) where the continuous -40..125 degC sweep loses the bandgap operating point above ~123-124 degC and `vref_max` jumps to ~2.82 V (sanity-band FAIL, not a TC number) — this is a property of the rejected `n_r2=55` resize, not of the shipped `n_r2=54` core. Kept as append-only evidence for issue #46's floor finding (see the "Sizing rationale" comment in `design/bandgap_core.sch`); do not read its `Result` block as describing the current design. |

## Why this happened / general convention

`--supersedes` is the wrong field for this: the `b24b404` run did not correct
an earlier measurement of the same design, it measured a *different* design
that was subsequently rejected and reverted. The record format currently has
no "rejected candidate" field, so a record minted from a working tree that
does not match the shipped `design/bandgap_core.sch` sizing needs a pointer
like this one added to the experiment's `README.md` until the runner grows a
proper field for it.

If you are about to mint a record from a working tree that does not match
what is currently committed in `design/`, consider whether this experiment
needs the same treatment before you finish.
