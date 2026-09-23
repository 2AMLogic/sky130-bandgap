# `psrr-dc-with-injector` — the decisive design-vs-extraction experiment for #300

Schematic-level (`provenance: schematic`) PSRR bench that instantiates
`design/bandgap_core.sym` **and** `design/startup_injector.sym` together on the
same GDRV / VREF / VDD / VSS nets. Records here are append-only and are **new**
evidence — they neither overwrite nor retire `sim/psrr-dc/`'s (report row 4a)
bare-core records.

This bench is a **diagnostic companion to row 4a, not a replacement for it.**
Row 4a remains the bare-core schematic PSRR claim. What this bench adds is the
one measurement neither existing bench could make: the injector's cost on
supply rejection with **no extraction step anywhere in the loop**.

## Why it exists

Issue #285 drew `design/startup_injector.sch` into the composed cell. On the
very next post-layout run, `sim/psrr-dc-post-layout/` (report row 4b) flipped
from **PASS 45/45** to **FAIL 25/45**, worst `psrr_band_min` 22.75 dB at
`ff / 125 °C / 3.63 V` — 37.25 dB below DR-006's 60 dB DC–1 kHz band-min floor.

Two explanations were live, and the post-layout bench alone cannot separate
them, because both variables (the injector, and extraction of the injector)
changed in the same record:

1. **Design.** The injector's diode-connected PMOS reference pair (`MPC1`/`MPC2`
   in `design/startup_injector.sch`, sourced from GDRV) sources a
   supply-dependent current out of the amplifier's high-impedance output node,
   making VOUT supply-dependent — the hypothesis in #300's body, argued from
   the corner signature.
2. **Extraction.** `klt extract --parasitics` overstates R on short/wide stubs
   ([klayout-tools#2359](https://github.com/2AMLogic/klayout-tools/issues/2359),
   open), which would shift the drawn injector's own bias and could manufacture
   the effect only in the extracted netlist — the mechanism already implicated
   on report rows 1b and 6b.

This bench holds (2) out by construction. Its testbench is
`sim/psrr-dc/testbench/tb_vref_psrr.sch` with **exactly one change** — an `XSU`
`startup_injector.sym` instance attached to GDRV/VREF — and its
`experiment.json` reuses `sim/psrr-dc/experiment.json`'s corners, deck,
measurements, limits and spread checks byte-for-byte (only
`slug`/`title`/`claim`/`schematic`/`provenance_source` and three added notes
differ). The injector is therefore the only variable between row 4a and this
bench.

## What the record says

Record `20260923-124813-af9ff1e` — full 45-point PVT matrix, **no** collapsed
axis, real ngspice, `Overall: FAIL`.

| Measurement | Range across 45 corners | Limit | Corners passing |
|---|---|---|---|
| `psrr_dc` (0.1 Hz edge) | 24.78 … 88.79 dB | ≥ 60 dB | 27 / 45 |
| `psrr_1k` (1 kHz edge) | 24.78 … 73.03 dB | ≥ 60 dB | 21 / 45 |
| `psrr_band_min` (DC–1 kHz interior floor, issue #127) | **24.78** … 73.03 dB | ≥ 60 dB | **21 / 45** |
| `psrr_1m` (1 MHz spot, informational) | 15.53 … 16.71 dB | none (stretch, out of scope wave 1) | n/a |
| `f_dc` / `f_1k` / `f_1m` / `n_ac_points` (guards) | all in-window | — | 45 / 45 |

Binding corner: **`ff, 125 °C, 3.63 V`**, `psrr_band_min` = **24.78 dB**, i.e.
**35.22 dB below** the DR-006 floor. Every index guard and the `n_ac_points`
guard resolved cleanly at every corner, and the corner-sensitivity spread check
(`psrr_dc` must move ≥ 0.5 dB across the matrix; observed spread 64.01 dB)
passes — the FAIL is a measured degradation, not a collapsed or un-cornered run.

**Issue #127's band-interior guard earns its keep here for the first time.** On
the bare core, and on the post-layout run, `psrr_band_min == psrr_1k` at every
corner (the band floor sits at the 1 kHz edge, monotonic rolloff). With the
injector attached, **11 of 45 corners develop a genuine interior dip** below
both edges — largest at `sf, −40 °C, 2.97 V` (edges 46.00 dB, interior floor
45.10 dB, a 0.90 dB dip). No corner is *rescued* by this (the two-edge check
would have caught all 24 failures anyway on these numbers), but the monotonic-
rolloff assumption the pre-#127 check rested on is now empirically false for
this circuit.

## The finding: the collapse is a property of the DESIGN

| | `psrr_band_min` range | binding corner | verdict |
|---|---|---|---|
| Bare core, schematic (row 4a, `20260909-232410-e8e2e46`) | 67.34 … 75.18 dB | `sf, −40 °C, 2.97 V` (67.34 dB) | PASS 45/45 |
| **Core + injector, schematic (this bench, `20260923-124813-af9ff1e`)** | **24.78** … 73.03 dB | **`ff, 125 °C, 3.63 V` (24.78 dB)** | **FAIL 24/45** |
| Core + injector, post-layout (row 4b, `20260923-073641-dbd4dda`) | 22.75 … 74.32 dB | `ff, 125 °C, 3.63 V` (22.75 dB) | FAIL 25/45 |

Attaching the injector at schematic level reproduces the post-layout collapse
almost exactly:

- **Same binding corner** (`ff, 125 °C, 3.63 V`), **same magnitude**
  (24.78 dB schematic vs. 22.75 dB post-layout — a 2.03 dB difference against a
  ~43 dB collapse).
- **Per-corner agreement across all 45 points**: median |Δ| **0.21 dB**, mean
  0.96 dB, max 4.32 dB; **29 of 45 corners agree within 0.5 dB**.
- **Exactly one corner differs in verdict**: `fs, 27 °C, 3.63 V` (62.29 dB
  schematic PASS vs. 59.14 dB post-layout FAIL) — a corner straddling the 60 dB
  floor, which is why the counts read 24/45 and 25/45 rather than the same
  number.

Extraction therefore accounts for at most a couple of dB, concentrated at the
125 °C corners, on top of a collapse the schematic already exhibits in full.

**Disposition: the design-cause branch of #300's acceptance criteria is
confirmed; the extraction-artifact branch is refuted for this mechanism.**
klayout-tools#2359 remains the correct tracker for the *separate*, already
documented extraction effects on rows 1b and 6b, and for the ≈2 dB residual and
the ≈1.5–2 dB downward shift in the informational `psrr_1m` spot here (15.53–
16.71 dB schematic vs. 13.40–14.69 dB post-layout). Nothing new needs to be
filed there for row 4b — this bench exonerates extraction as the *dominant*
term, which is a result about this design, not a tool gap.

## What this does and does not say about `MPC1`/`MPC2`

The injector's corner signature reproduces at schematic level too, and it is
the signature #300's body argued from:

| mean `psrr_band_min` degradation vs. bare core | | |
|---|---|---|
| by process | `sf` −21.58 dB, `ff` −21.02 dB, `tt` −10.99 dB, `ss` −7.53 dB, `fs` −6.91 dB |
| by supply | 3.63 V −21.51 dB, 3.30 V −13.11 dB, 2.97 V −6.21 dB |
| by temperature | 125 °C −16.29 dB, 27 °C −12.79 dB, −40 °C −11.75 dB |

Monotone in supply, strongly fast-PMOS-selective (`sf`/`ff` worst, `fs` mildest
— `fs, −40 °C` moves by 0.03–0.95 dB, i.e. essentially not at all), which is
what a supply-dependent PMOS conductance on the high-impedance GDRV node looks
like.

**This corroborates the `MPC1`/`MPC2` hypothesis; it does not prove it.** What
is now measured, not inferred, is that *the injector* causes the collapse and
that extraction does not. Which of the injector's six devices dominates is
still an inference from the corner signature — this bench does not isolate it,
because it attaches the whole cell at once. Isolating and fixing it is
deliberately **out of scope here** (#300's acceptance criteria say so
explicitly) and is tracked in **issue #306**, because any `MPC1`/`MPC2`
resize has to be re-verified against `sim/startup-stability` and
`sim/startup-time-post-layout` — starving that stack is exactly what would stop
the injector working — and that needs its own layout/extraction cycle.

## Reproducing

```bash
python3 sim/bin/corner-run.py sim/psrr-dc-with-injector
```

Exit status 2 (`Overall: FAIL`) is the expected result today, and is the
finding. It mints a new record id; per `sim/README.md`'s append-only rule the
record above is never edited.
