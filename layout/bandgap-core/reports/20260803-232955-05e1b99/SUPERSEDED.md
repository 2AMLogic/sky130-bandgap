# SUPERSEDED by `../20260803-235842-b4bcce9/`

This record is kept because report directories are append-only evidence, but
**do not cite its scoreboard or its `reference.spice`.** Both were corrected
inside the same (issue #62) pull request, before merge, after review found
three defects in the reference netlist this run compared against and one in
its own self-assessment:

1. `RR2A` / `RR2B` were `87750` ohm (`325*270`), omitting the per-leg 380 ohm
   head resistance that `design/bandgap_core.sch` line 188's unit model
   (`R ~ 380 + 325*L`) gives every `res_high_po` device and that this run's
   own `RR1` (`380 + 325*35 = 11755`) already included. Correct value is
   `380 + 325*270 = 88130`, i.e. K = 7.4972, not the 7.4649 this run's
   reference implied.
2. The reference header cited
   `sim/output-voltage-tc/netlist-snapshots/20260803-142220-b24b404.spice` as
   its transcription source. That snapshot carries `.param n_r2=55` -- the
   candidate commit 297073f (issue #57) records as **rejected**. The values
   transcribed were the correct n_r2=54 ones; only the citation was wrong.
3. The reference carried an `RGDRV AOUT GDRV 0` card. The schematic has one
   node there (error_amp's `AOUT` opin is tied straight to `bandgap_core`'s
   `GDRV` iopin), no device; the 0-ohm card existed only because the layout
   leaves `AOUT` and `GDRV` as two separate, unrouted labelled pins. It is
   removed -- the reference states the schematic, and the layout gap is
   disclosed in the successor record's "Schematic inter-block nets" table.
4. Criterion 1 was scored **MET** on "9/9 declared nets routed", i.e. against
   this flow's own `connectivity[]` declaration rather than against
   `design/bandgap_core.sch`'s inter-block node list. Measured against the
   schematic, 4 of 12 inter-block nets are joined across every block they
   reach; the successor record scores criterion 1 **PARTIAL** and tables the
   drawn-vs-labelled-only breakdown.

Everything else this record measured (DRC clean, 38,171 um^2, the extracted
device classes, the promoted pins, and criterion 4 being unmet for
2AMLogic/klayout-tools#433) is unchanged in the successor run.
