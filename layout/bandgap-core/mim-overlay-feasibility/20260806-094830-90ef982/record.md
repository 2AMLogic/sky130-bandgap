# MiM-overlay feasibility for MCC: 20260806-094830-90ef982

Measured answer to issue #62's operator ruling (2026-08-11), whose primary branch is "realize MCC as a `cap_mim` overlay" and whose fallback is "draw MCC as the MOS cap it is, and re-budget the area". Which branch applies is decided here, by measurement.

**Verdict: MiM overlay is INFEASIBLE.**

| Question | Answer |
| --- | --- |
| Is the overlay area there? | **yes** -- 45,968 um^2 clear vs 10,742 um^2 needed |
| Can a drawn MiM cap's plates reach a named net? | **no** -- see the connectivity probe below |
| Is drawn MiM geometry DRC-checked? | **no** -- 2 of 4 MiM stack layers carry no curated rule |

## 1. Overlay area available above the composed cell

Measured from `layout/bandgap-core/reports/20260806-094830-90ef982/bandgap_core_routed.gds` (top cell `bandgap_core_routed`).

| Layer | Role | Drawn area |
| --- | --- | --- |
| `70/20` | met3.drawing (cap_mim bottom plate) | 0.0 um^2 |
| `89/44` | capm.drawing (cap_mim top plate) | 0.0 um^2 |
| `71/20` | met4.drawing (cap_mim_m4 bottom plate) | 0.0 um^2 |
| `97/44` | capm2.drawing (cap_mim_m4 top plate) | 0.0 um^2 |

Composed-cell footprint **45,968 um^2**, of which **0.0 um^2** carries MiM-stack geometry, leaving **45,968 um^2** clear. The routed cell draws on li1/met1/met2 only, so the whole footprint is available to an overlay in principle.

## 2. Plate area a MiM MCC would need

At this deck's own tt-corner coefficients (`area_cap_f_um2=2.00e-15`, `perim_cap_f_um=1.90e-16`), solving `C = area*A + perim*P` for a square plate:

| Sizing basis | Target C | Square plate | Plate area |
| --- | --- | --- | --- |
| cc_mcc min (sim/error-amp-loop, 45 corners) | 21.04 pF | 102.4 x 102.4 um | 10,479 um^2 |
| cc_mcc max (sim/error-amp-loop, 45 corners) | 21.56 pF | 103.6 x 103.6 um | 10,742 um^2 |

**The sizing target is the measured capacitance, not the analytic one.** The operator ruling and `layout/matching-plan.md` Section 7bb both size this from a ~29 pF figure, which is `Cox*W*L*m` on the device's drawn gate area. `design/error_amp.sch` says explicitly that MCC's capacitance is *measured, not computed from Cox*W*L*, and `sim/error-amp-loop/`'s 45-corner run measures `cc_mcc` at 21.04-21.56 pF -- the value the loop-stability result actually depends on. Sizing a replacement to the analytic number would over-build it by ~35%. Either way the answer to question 1 is the same (both fit), which is why this correction changes nothing about the verdict -- but a future revisit should size from the measured number.

## 3. Connectivity probe (the decisive one)

A MiM cap whose plates cannot join `VDD` and `GDRV` is not a realization of MCC -- it is a floating two-terminal device, and adding one makes `klt lvs`'s `mismatch_count` *worse*, not zero. This probe is the most favourable case that can be drawn: a `capm` top plate over a `met3` bottom plate laid directly over two labelled met2 wires.

`klt extract --deck sky130` recognises **1** MiM cap device(s) (`device_counts={"sky130_fd_pr__model__cap_mim": 1}`) -- so recognition is not the gap. The extracted netlist is:

```spice
* extracted by klt extract --deck sky130

* cell mim_connectivity_probe
.SUBCKT mim_connectivity_probe
* device instance $1 r0 *1 10,7.5 sky130_fd_pr__model__cap_mim
C$1 \$3 \$4 3.6226e-13 sky130_fd_pr__model__cap_mim
.ENDS mim_connectivity_probe
```

**Neither plate carries either labelled net.** The cap's two terminals are anonymous, isolated nodes. This is not a probe artifact -- it is what the curated deck declares: `EXTRACTION_DECK.metals` is `(li1, met1, met2)` and `vias` is `(mcon, via)`, so neither `met3` (the `cap_mim` bottom plate) nor `met4` (`cap_mim_m4`'s) is a connectivity level, and neither capacitor entry declares a `top_plate_via`. The deck's own comment states the consequence directly: *"both plates stay isolated connectivity nodes, not wired into this deck's li1/met1/met2-only stack"*. There is no layout-side way around it: the plates are unreachable by construction, not by placement.

## 4. DRC coverage of the MiM stack

| Layer | Role | Curated rule? |
| --- | --- | --- |
| `70/20` | met3.drawing (cap_mim bottom plate) | **no** (in stream, no rule) |
| `89/44` | capm.drawing (cap_mim top plate) | **no** (in stream, no rule) |
| `71/20` | met4.drawing (cap_mim_m4 bottom plate) | not drawn in the probe |
| `97/44` | capm2.drawing (cap_mim_m4 top plate) | not drawn in the probe |

`klt drc --deck sky130` on the probe reports `status=clean`, `violations=0` -- a clean verdict that says nothing about the MiM geometry, because the curated deck has no rule for those layers. A MiM overlay would therefore need this repo's own rule checker alongside it, the way `layout/bin/met2_drc.py` covers the met2 escape plane.

## 5. The gate this harness does not probe (and why it decides)

Questions 2 and 3 are measured against **this repo's pinned `klt`** (`layout/requirements.txt`) -- the build every record here is produced with. Upstream is moving on exactly this: klayout-tools#619 (merged via #621) made met3/met4 real connectivity levels, which fixes the *bottom* plate, and #775 asks for the `top_plate_via`/`top_plate_via_metal` pairing that would finish the top one. A future pin bump can flip question 2's answer, and this harness is re-runnable precisely so that it is re-measured rather than assumed.

It would not flip the conclusion. `klt lvs` compares the drawn cell against `reference.spice`, which transcribes design/bandgap_core.sch + design/error_amp.sch, and MCC is stated there as `MMCC VDD GDRV VDD VDD pfet L=20U W=30U m=16`. **A `cap_mim` in the layout does not match a `pfet` in the reference** -- it would be an unmatched layout device *and* an unmatched reference device, i.e. `mismatch_count` 1 -> 2, not 1 -> 0. Realizing MCC as a MiM therefore requires changing the schematic, and three ratified things say no:

1. **Issue #9's device menu.** Its acceptance criteria restrict this cell to `sky130_fd_pr__nfet_g5v0d10v5`/`pfet_g5v0d10v5`. design/error_amp.sch cites that restriction by name as the reason `cap_mim_m3_*` is "deliberately not used".
2. **The 45-corner loop-stability evidence.** `sim/error-amp-loop/` measures `cc_mcc` (21.04-21.56 pF) for *this* device at every PVT point and asserts a floor on it. A different device -- different C(V) behaviour, different parasitics -- would need that whole corner set re-run before the amp could be called stable again.
3. **Issue #62's own operator ruling**, which put changes to the closed amp cell (and the #9/loop-stability re-verification they drag in) explicitly outside this issue's scope.

## Consequence

The ruling's **fallback** branch applies. The area is there (question 1); the connectivity is not (question 3); and even when upstream finishes closing that (question 5), the schematic-side gate stands. MCC is drawn as the MOS cap `design/error_amp.sch` already specifies -- which is what issue #9's ratified device menu requires, what keeps the drawn cell the same circuit the 45-corner loop-stability record measured, and what lets `klt lvs` reach `mismatch_count: 0` against an unedited reference -- and the area it costs is re-budgeted through the Area-row decision record `spec/decision-records/` carries for it (`DR-007-mcc-area-budget.md`). See `layout/matching-plan.md` Section 7bb for the same conclusion reached independently, with a three-geometry `klt draw` reproduction this harness's single probe deliberately does not repeat.

