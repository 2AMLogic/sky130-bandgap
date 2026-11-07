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

## Pilot delta attribution (2026-11-07, issue #486)

Why `records/20261106-pilot/` fails every `vref_27` delta (tt / 27 °C / 3.30 V:
−27.753 mV against a 5 mV limit). Reproduce every number below with
`python3 -I sim/pex-native/attribute_delta.py all` (`legs` is pure Python;
`rtc` is one `ngspice -b`; `probe` is five sequential single-corner local
`ngspice -b` runs — no grid). The record, `delta-limits.json` and the design are
unchanged. klt 0.8.0 extraction, `extracted.spice` as committed.

**Answer.** The delta is **not** a normaliser effect and is **not** the old
2 × 229.7 Ω star. It is series parasitic resistance in the resistor legs that
shifts the divider ratio K = R2B/R1 from 7.773 to 7.377 (−5.1 %). 89 % of the
−27.8 mV is that K change; the rest is the lower branch current moving VB.

### Leg resistance (resistor-only subset: 145 `X$n … res_high_po` + 800 `R` cards)

| leg | units | device sum (Ω) | extracted incl. parasitics (Ω) | delta | internal-link parasitic (Ω) | pin-net arms (Ω) |
|---|---|---|---|---|---|---|
| `R1` (VB→VBQ) | 7 | 14026.89 | 15863.8 | +13.1 % | 612.3 | 1224.7 |
| `R2A` (VOUT→VA) | 69 | 109030.60 | 116902.3 | +7.2 % | 7276.6 | 595.1 |
| `R2B` (VOUT→VB) | 69 | 109030.60 | 117021.4 | +7.3 % | 7192.6 | 798.2 |

K = R2B/R1: device 7.7730, extracted 7.3766 (−5.10 %). The earlier post-layout
bench (900 `R` cards, klt 0.5.0) had +32 % / +29.5 % / +29.7 % and K −1.9 %.

* **Per-link parasitic.** 142 chain-internal links: min / median / max
  102.0 / 105.3 / 187.3 Ω (≈ 52.7 Ω per terminal arm). **The 2 × 229.7 Ω star is
  gone** (0 of 142 within 5 % of 459.5 Ω) (klt 0.8.0 here; the earlier figure was from klt 0.5.0 — which change removed it was not bisected).
* **What is left in R1.** Of R1's +1837 Ω, 1224.7 Ω are the star arms of the two
  *pin nets* it ends on: `RVB_t9` 1136.4 Ω (`VB__t9`) and `RVBQ_t8` 88.3 Ω
  (`VBQ__t8`) — `grep -E '^R(VB_t9|VBQ_t8) ' records/20261106-pilot/extracted.spice`.
  The same two arms on R2 are ≈ 0.7 % of a 109 kΩ leg, which is why R1 moves
  +13.1 % and R2 +7.2 %. "pin-net arms" is the part of the hub-to-hub
  resistance not explained by device values or internal links.

### Resistor value and temperature behaviour (normaliser check)

`rtc`: resistance of the PDK model `sky130_fd_pr__res_high_po` (the schematic's
device) versus the fixed `R` card that `normalize_klt_resistors` +
`translate_extracted_netlist` emit, tt corner:

| resistor (Ω) | −40 °C | 27 °C | 125 °C |
|---|---|---|---|
| model W=1 L=5 | 1955.241 | 2003.843 | 2108.601 |
| fixed 2003.841367 | 2003.843 | 2003.843 | 2003.843 |
| model W=1 L=0.5 | 535.200 | 542.120 | 557.032 |
| fixed 542.118769 | 542.120 | 542.120 | 542.120 |
| schematic R1 leg | 13686.687 | 14026.898 | 14760.213 |
| schematic R2A = R2B leg | 106510.905 | 109030.566 | 114462.182 |

**The normaliser preserves the value at 27 °C (to 2 mΩ) and does not preserve
temperature behaviour**: the rewritten card is a plain resistor with no TC, while
the model rises +5.2 % from 27 to 125 °C and falls −2.4 % to −40 °C. It cannot be
the cause of the 27 °C delta (next table, "normaliser" = 0), but the extracted
side's `vref_min` / `vref_max` / TC are evaluated with temperature-flat resistors,
so those three observables are not a like-for-like comparison. This is a
pilot-bench limitation of `pexlib`, not an extraction defect; not changed here.

### Probe tt / 27 °C / 3.30 V (V)

Five variants of the same cell, each one local `ngspice -b` op: `schematic`
(reference), `extracted` (what the pilot grades), `extracted_model_R` (extracted
netlist, PDK-model resistors instead of fixed-R cards), `array_parasitics_only`
(parasitic `R` cards not on a resistor terminal shorted to 1 mΩ), `no_parasitics`
(all parasitic `R` cards shorted).

| node | schematic | extracted | extracted_model_R | array_parasitics_only | no_parasitics |
|---|---|---|---|---|---|
| `VREF` | 1.210747 | 1.182993 | 1.182993 | 1.181651 | 1.210638 |
| `VA` | 0.726301 | 0.723126 | 0.723126 | 0.722901 | 0.726294 |
| `VB` | 0.726473 | 0.723291 | 0.723291 | 0.723060 | 0.726454 |
| `VBQ` | 0.664171 | 0.660972 | 0.660972 | 0.660893 | 0.664165 |
| `ΔVBE = VB − VBQ` | 0.062302 | 0.062319 | 0.062319 | 0.062167 | 0.062289 |

### Attribution of the −27.754 mV

The divider gives `VREF = VB + K·ΔVBE` (checks to < 1 µV on both sides), so
`ΔVREF = ΔVB + (K_e − K_s)·ΔVBE_s + K_e·(ΔVBE_e − ΔVBE_s)`:

| share | mV |
|---|---|
| total (extracted − schematic) | −27.754 |
| K-ratio change at fixed ΔVBE | −24.694 |
| branch-current change (VB falls −3.18 mV as R1 rises) | −3.182 |
| ΔVBE change × K | +0.122 |
| **unexplained** | **0.000** (identity closes; < 1 µV) |
| normaliser (extracted − extracted_model_R) | 0.000 |
| memo: resistor-array parasitics (`array_parasitics_only` − `no_parasitics`) | −28.987 |
| memo: all other-net parasitics (`extracted` − `array_parasitics_only`) | +1.342 |
| memo: `no_parasitics` − `schematic` (device-level differences) | −0.109 |

### Disposition

Still open: whether the 1136 Ω / 88 Ω pin-net arms are physical routing
resistance or the klt star model's allocation (it splits each net's single lumped
R over every terminal, including DC-idle gate terminals — a documented
approximation in the extractor's own header, `--distributed-rc` refines it only
for `--critical-net` nets). Separating the two needs per-segment geometry or a
`--critical-net VB,VBQ --distributed-rc` rerun, which is a new pex record and out
of scope here. No klayout-tools gap is filed: no defect is shown, only a
modelling approximation. Not done: changing limits or `n_r2` (out of scope).
