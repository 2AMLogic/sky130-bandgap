# sim/startup-time-post-layout/

See [`sim/README.md`](../README.md) for the harness; this file carries the per-bench description and record history.

## Experiment description and record history

Moved verbatim from the "Experiments that do not go through the corner runner" table in `sim/README.md` (issue #339). The newest entry under `records/` is authoritative for the current verdict; the text below was written when the cited records were current.

**Post-layout (`provenance: extracted`) re-run of `sim/startup-time`'s supply-ramp startup-time claim (issue #16)**, same extracted-layout DUT body as the four rows above, wrapping `sim/startup-time/testbench/tb_vref_startup.sch` unmodified. Runs the FULL 45-point matrix (nothing swept inside the deck, so no axis is collapsed) — the LAST of the five spec lines issue #16's "full #11 testbench suite" Acceptance Criteria bullet enumerates. **`Overall: PASS`, 45/45 since issue #285** (`20260923-070906-dbd57a9`): the composed cell now DRAWS `design/startup_injector.sch`, so this bench's post-layout DUT is core+injector while the schematic-level bench it wraps stays the bare core. The two halves therefore measure different circuits on purpose — `t_start` 0.0678–0.1818 ms against the < 1 ms budget and `gdrv_final` 1.598–2.611 V at every corner (the degenerate all-off state parks GDRV at VDD, so this is the drawn injector evicting it). Its earlier records read `Overall: FAIL`, 45/45, the pre-existing expected FAIL of a composed cell that shipped no injector; those records remain valid for the layout record each names

## This bench still measures the klt-0.5.0 extraction (disclosed, deliberate — 2026-11-15, issue #560)

Layout record `20260923-070209-dbd57a9` now has **two** committed parasitics snapshots:
the klt-0.8.0 one under `sim/output-voltage-tc-post-layout/parasitics-snapshot/` and this
bench's own klt-0.5.0 one under `parasitics-snapshot/`. `resolve_parasitics_snapshot`
returns a bench's **own** local snapshot at step 1, before the step-2 sibling glob that
sorts `output-voltage-tc` first — so a plain re-run of this bench re-measures its own
**0.5.0** extraction and would look completely successful while the module's
"every post-layout record for a layout record measures the same extracted netlist"
invariant stays violated for it. Issue #560 therefore re-ran the other five post-layout
benches onto the 0.8.0 extraction and deliberately left this one where it is:

- its newest record (`records/20261113-111050-7efdcf3b`) resolves `source: local` at
  `total_resistance_ohm` 234 007.2692 — the 0.5.0 figure — and stays the append-only
  evidence of what was measured;
- moving it would need either a committed-snapshot overwrite (forbidden, `sim/` is
  append-only) or a new resolver override flag (an unrequested mechanism);
- it is bound to no ratified spec row (`signoff/README.md` lists the `startup-time*`
  benches among those outside the envelopes), so no graded claim depends on it; and its
  dual dialect is what `sim/tests/test_post_layout_resistor_dialects.py` exists to pin.

So: **every other post-layout bench now measures the klt-0.8.0 extraction of this layout
record; this bench alone still measures klt-0.5.0, on purpose, and this paragraph is the
disclosure.** A future issue can retire the divergence properly (fresh snapshot on a new
layout record, or a sanctioned resolver override); neither belongs to #560.
