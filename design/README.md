# design/ — schematic authoring conventions

This directory holds the xschem schematics/symbols for the shipped design
(`bandgap_core`, `error_amp`, `startup_injector`) plus a couple of standalone
throwaway/bootstrap schematics (`smoke_test.sch`). One authoring hazard is
worth flagging up front, because it fails silently.

## Do not embed literal `"` inside a `value="..."` (or other quoted text-attribute) block

xschem's netlister closes a quoted text-attribute string (`value="..."`,
`author="..."`, `format="..."`, etc.) at the **first** literal `"` character
it encounters — it does not respect a "matching" or "intended" closing quote.
Anything after that first embedded `"` is **silently dropped** from the
netlisted output, with no warning at netlist time. The failure only surfaces
later, and confusingly: ngspice rejects the truncated netlist with a fatal
`Undefined parameter [...]` error that gives no hint the real cause was a
stray quote mark in a comment.

This bit `bandgap_core.sch` for real (#54/#58): a `"Sizing rationale"`
comment with literal double quotes inside the `CORE_PARAMS` `code_shown.sym`
`value="..."` block truncated the block mid-way, silently dropping the
`n_r1`/`n_r2`/`m_out`/`m_ampbias` (and later `n_r2_trim`/`r_lseg_trim`)
`.param` declarations. It has also shown up in at least one `sim/`
testbench comment (#59) — this is a recurring, general hazard, not a
one-off.

**Rule of thumb**: inside any `code_shown.sym` (or similar) comment block, or
any other `value="..."`/`author="..."`/`format="..."` text, never wrap a
phrase in literal double quotes. Rework it instead — drop the quotes, use a
different marker (emphasis via capitalization/dashes), or use `'single
quotes'` (xschem's own parameter-substitution syntax, e.g. `'t_ramp'`, is
single-quoted and is unaffected by this hazard).

A repo-hygiene check enforces this: `.loom/scripts/check-xschem-embedded-quotes.sh`
scans every tracked `.sch`/`.sym` file for an embedded literal `"` inside a
quoted text-attribute block and fails with a `file:line` pointer on
detection. It runs as part of `npm run check:ci`.
