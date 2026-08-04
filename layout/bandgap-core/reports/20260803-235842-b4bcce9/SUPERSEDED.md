# SUPERSEDED by `../20260804-001742-bc9c31f/`

This record is kept because report directories are append-only evidence, but
**do not cite its `reference.spice`.** It was corrected inside the same
(issue #62) pull request, before merge, after a second review found one more
defect in the reference netlist this run compared against:

1. The amp's differential-pair gates were transcribed the wrong way round:

   ```
   MMP1  D1   VA   TAIL VDD pfet L=10U W=20U m=16
   MMP2  D2   VB   TAIL VDD pfet L=10U W=20U m=16
   ```

   `design/error_amp.sym` puts `VINP` at symbol-relative `(-50, -20)` and
   `VINN` at `(-50, +20)`; `design/bandgap_core.sch` instantiates `XAMP` at
   `900 -600` rot 0 flip 0, so `VINP` lands on `ampp lab=VB` and `VINN` on
   `ampn lab=VA`. `design/error_amp.sch` wires MP1's gate to `VINP` and MP2's
   to `VINN`, so the flattened cards are `MMP1 D1 VB TAIL VDD` and
   `MMP2 D2 VA TAIL VDD`. The checked-in `n_r2=54` snapshot agrees
   (`XAMP VB VA GDRV TAIL VDD VSS error_amp` against
   `.subckt error_amp VINP VINN AOUT ITAIL VDD VSS`).

   This was not a benign relabeling. `D1` drives `MMN3` -> `GDRV` while `D2`
   drives `MMN4` -> `PN`, so the two input devices are distinguishable in the
   graph and no `VA`<->`VB` rename restores isomorphism -- such a rename would
   also have to move `RR1` (schematic has `R1`'s head on `VB`) and `QQ1`'s
   emitter (on `VA`), both of which were already correct. Functionally, this
   run's reference described a positive-feedback amplifier rather than the
   intended negative-feedback bandgap loop.

Also corrected in the successor run, in the flow's own scoring table rather
than in the reference netlist:

2. `SCHEMATIC_INTER_BLOCK_NETS["VSS"]["blocks"]` omitted the three resistor
   blocks. `res_high_po` is a 3-terminal device whose bulk ties to `VSS` in
   the schematic (`design/bandgap_core.sch` `r2ab` / `r2bb` / `r1b`), so `VSS`
   reaches seven blocks, not four. The reference cards legitimately drop that
   bulk terminal (the `klt` LVS reader's `res_generic_po` is 2-terminal), but
   this table's stated bar is what the *schematic* requires, and understating
   it understated the "missing" column. `VSS` is `partial` either way and the
   headline 4/12 count is unchanged.

Everything else this record measured is unchanged in the successor run: DRC
clean (0 violations), 38,171 um^2, 243 extracted devices
(`nfet` 16 / `pfet` 52 / `pnp` 16 / `res_generic_po` 159), 23 promoted pins,
`klt lvs` `mismatch` with `mismatch_count = 790`, criterion 1 PARTIAL at
4/12, and criterion 4 unmet for
[2AMLogic/klayout-tools#433](https://github.com/2AMLogic/klayout-tools/issues/433).
The three defects and the criterion-1 rescoring that this record itself fixed
relative to `../20260803-232955-05e1b99/` all still stand -- see that record's
own `SUPERSEDED.md`.
