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

## Put a custom netlist `format` on a **symbol**, never on an instance

When a device needs a netlist line the PDK symbol's own `format="..."` cannot
express, add a project-local `.sym` (see `res_high_po_series.sym`) rather than
overriding `format=` in the instance's attribute block in the `.sch`.

Measured on xschem 3.4.7 (issue #99): a schematic carrying **more than one**
instance-level `format=` attribute makes batch netlisting
(`xschem -n -q -x -s`) exit with status **10**, even though the netlist it
writes is complete and correct. One such instance exits 0; two or more exit
10. `sim/bin/corner-run.py`'s `netlist_with_xschem()` treats any non-zero
xschem exit as a hard harness error — correctly, since it must not silently
trust a netlister that reported failure — so the whole `sim/` harness stops
working. A symbol-level `format=` is the supported shape and netlists cleanly
at any instance count.

The concrete case: `bandgap_core.sch` needs `mult` and `m` to carry
*different* values on `sky130_fd_pr__res_high_po` (`mult` = the real series
unit count, which the PDK model card uses only in its Pelgrom mismatch terms;
`m` = `1/mult`, which is how a series chain of identical units is expressed
as one SPICE instance). The PDK's own `res_high_po.sym` emits `m=@mult`, tying
them together. `res_high_po_series.sym` is a verbatim copy of that symbol
whose only change is a `format=` emitting the two independently — see its
header comment for the full rationale.

Note also that a `format=` string's `@token` substitution does **not** nest:
`m='1/@n_series'` netlists as a truncated `m='1/`, silently losing the rest
of the line. State the reciprocal as its own instance attribute
(`m_series='1/n_r1'`) and reference it directly (`m=@m_series`).
