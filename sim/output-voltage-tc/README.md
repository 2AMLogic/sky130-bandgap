# `output-voltage-tc` — record index

Records here are append-only (`sim/README.md`); this index is not a substitute
for that convention, it is a pointer added *alongside* the records so a reader
who lists `records/` newest-first does not misattribute the newest record's
`FAIL` verdict to the shipped design. See issue #55 for why this file exists.

**Read this before citing the newest record.** The newest record id is **not**
always the shipped `design/bandgap_core.sch` (`n_r2=54`) — one entry below is a
rejected sizing candidate, kept only as evidence for the investigation that
rejected it.

| Record | Design measured | Status |
|---|---|---|
| `20260803-102002-32194bc` | Shipped core, `n_r2=54` | Shipped design. `Overall: FAIL` — untrimmed TC ~161–171 ppm/degC vs the draft's < 50 ppm/degC target; expected, trim is issue #13. |
| `20260803-115356-7759435` | Shipped core, `n_r2=54` | **Standing untrimmed-TC result for the shipped design.** Supersedes `20260803-102002-32194bc` (re-run on a clean tree). `Overall: FAIL` — untrimmed TC 152.9–169.3 ppm/degC, 15/15 corners FAIL vs the draft's < 50 ppm/degC target; no regulation-collapse corners. This is the number to cite for "what is the shipped core's untrimmed TC". |
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
