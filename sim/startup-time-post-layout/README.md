# sim/startup-time-post-layout/

See [`sim/README.md`](../README.md) for the harness; this file carries the per-bench description and record history.

## Experiment description and record history

Moved verbatim from the "Experiments that do not go through the corner runner" table in `sim/README.md` (issue #339). The newest entry under `records/` is authoritative for the current verdict; the text below was written when the cited records were current.

**Post-layout (`provenance: extracted`) re-run of `sim/startup-time`'s supply-ramp startup-time claim (issue #16)**, same extracted-layout DUT body as the four rows above, wrapping `sim/startup-time/testbench/tb_vref_startup.sch` unmodified. Runs the FULL 45-point matrix (nothing swept inside the deck, so no axis is collapsed) — the LAST of the five spec lines issue #16's "full #11 testbench suite" Acceptance Criteria bullet enumerates. **`Overall: PASS`, 45/45 since issue #285** (`20260923-070906-dbd57a9`): the composed cell now DRAWS `design/startup_injector.sch`, so this bench's post-layout DUT is core+injector while the schematic-level bench it wraps stays the bare core. The two halves therefore measure different circuits on purpose — `t_start` 0.0678–0.1818 ms against the < 1 ms budget and `gdrv_final` 1.598–2.611 V at every corner (the degenerate all-off state parks GDRV at VDD, so this is the drawn injector evicting it). Its earlier records read `Overall: FAIL`, 45/45, the pre-existing expected FAIL of a composed cell that shipped no injector; those records remain valid for the layout record each names
