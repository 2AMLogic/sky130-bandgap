# `sim/pex-native` — native `klt pex` pilot (issue #335)

One bench (output-voltage TC, spec rows 1a/1b), injector-inclusive composed cell,
pinned klt 0.8.0 (`uvx`, never the host `klt`). Reproduce from a clean checkout:
`sim/pex-native/run.sh` (15 corners x 2 sides go to the batch fleet; a failed
submit fails the run, nothing is retried locally). Then
`grade_deltas.py records/<stamp>/pex-stdout.json` applies `delta-limits.json`.

| File | Role |
|---|---|
| `delta-limits.json` | pilot delta limits, committed before any result |
| `reference/bandgap_core_composed.spice` | generated flat schematic reference with the routed cell's 13 pins (`compose_reference.py [--check]`) |
| `measure_command.py` | `klt pex --measure-command` hook; `PEX_NATIVE_BACKEND=local` runs ONE probe corner only |
| `check_inputs.py` / `pexlib.py` | refuses pin mismatch, injector-less reference, incomplete matrix |
| `records/` | append-only runs: klt report (`pex-stdout.json`), `inputs.json` hashes, per-job fleet receipts |

Notes: klt 0.8.0 writes resistors as `X$n … res_high_po r=V` cards, which
`post_layout_common.translate_extracted_netlist` does not match; `pexlib.normalize_klt_resistors`
rewrites them (value-preserving) rather than editing the shared translator.
`pex-netlist.spice` in a record is klt's `-o` file: with klt 0.8.0 it holds the extracted SPICE netlist, not a JSON report (written before the final stdout report);
`pex-stdout.json` is the complete report.
