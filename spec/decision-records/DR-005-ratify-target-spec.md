# DR-005: Ratify the sky130-bandgap target spec — output accuracy re-cast to gf180-bandgap parity (±2% untrimmed / ±0.5% trimmed) on the measured offset budget

- **Status**: **ratified 2026-08-11**
- **Decided by**: Robb (engineering / spec-ratification authority), issue #1. Drafted by Loom agent; the accuracy-row ruling and the port-parity confirmation are the operator's.
- **Date**: 2026-08-11
- **Ratifies**: the DRAFT target-spec table in `README.md` as the block's single source of truth, unblocking the layout gate (#14 DRC/LVS bring-up, #15 floorplan) and the #8 design chain that were `Blocked by: #1`.
- **Supersedes / relates to**: closes the deferral in #32 (ratification held pending PNP-pair σ(ΔVBE), #31 — now landed); folds in the spec-review "defer" verdict (klt#124, input to ratification, not a decision); relates to DR-001 (supply-flavor scope), DR-003 (res-array head resistance). The flavor-scope call (#7 lineage) is recorded in DR-001 and is not re-opened here.

## Context — what was deferred, and why it no longer is

The output-accuracy row (`1.20 V ±1% untrimmed`) was the one load-bearing line the spec-review could not judge without PNP-pair local-mismatch data, so #1 was deferred (#32). That data has since landed:

- **#31** (closed) measured σ(ΔVBE) on matched sky130 substrate-PNP pairs: **≈0.65 mV (identical pair) / ≈0.45 mV (area-ratioed)**, MC N=300, `tt_mm`, −40/27/125 °C, with an MC-off zero control and a second-seed stability check.
- **#9** (closed) rolled the full error-amp offset/mismatch budget end-to-end into `design/error-amp-offset-budget.md`, measured across 45 PVT corners.

## The measured verdict: ±1% untrimmed is not achievable; the physics is clear

The untrimmed reference's **local-mismatch spread alone is 1.39% (3σ) at 27 °C, 1.54% at 125 °C** of a 1.2 V output — already outside the draft ±1% line **before** any global process shift or temperature curvature. Output-referred budget (measured, 1σ → 3σ via the Kuijk core's measured offset gain **9.65 V/V**):

| Term | output-referred 3σ | share of variance |
|---|---|---|
| Amplifier V_OS | **1.266 %** | **83.4 %** |
| res_high_po R2/R1 ratio | 0.475 % | 11.7 % |
| PNP ΔVBE (8× arrays) | 0.305 % | 4.8 % |
| PNP V_EB (CTAT) | 0.040 % | 0.1 % |
| **RSS** | **1.387 %** | — |

Two facts drive the ruling: **(1)** ±1% untrimmed is physically off the table (local mismatch alone is ~1.4–1.5% 3σ, before process/temp); **(2)** the dominant term (83%) is the **amplifier's own random offset**, not the σ(ΔVBE) the deferral was waiting on — so PNP-pair sizing cannot rescue an untrimmed ±1% line, and a trim (which corrects the amp-V_OS + R-ratio terms = ~95% of the variance) is the effective lever. This is exactly the trap `error-amp-offset-budget.md` warned against papering over per CLAUDE.md; the spec moves deliberately, not silently.

## The decision

**Ratify the output-accuracy row at gf180-bandgap parity:**

> **Output reference: 1.20 V — ±2% untrimmed (3σ, mismatch MC N≥300 + process corners, −40…125 °C); ±0.5% trimmed (3σ, 1-point trim).**

- **±2% untrimmed is a *guaranteed* line, and the data supports it:** measured local mismatch is 1.39–1.54% (3σ), leaving headroom for global process + temperature curvature under the ±2% bound. Full untrimmed-over-PVT confirmation is the #11 harness's job; ±2% is the ratified target it verifies against.
- **±0.5% trimmed** is reached by trimming out the amp-V_OS + R-ratio terms (the 95%-of-variance trimmable set), same mechanism gf180-bandgap ratified.

**Add the Trim row** (required to support the ±0.5% line; mirrors gf180):

> **Trim: 1-point resistor trim (binary-weighted segments, `res_high_po` per `error-amp-offset-budget.md`), range ≥ ±5%, resolution ≤ 0.25%/step (≥5 bits equiv.), magnitude only; performed at 27 °C.**

**The remaining rows ratify as drafted** (they already match gf180 in substance):

| Parameter | Ratified value | Parity |
|---|---|---|
| Temp coefficient (−40…125 °C) | < 50 ppm/°C (box method); stretch < 20 ppm/°C (curvature correction) | matches gf180 |
| PSRR | > 60 dB @ DC; stretch > 70 dB | see divergence note below |
| Supply | 3.3 V ±10%; stretch: 1.8 V-core Banba variant | see PDK-stretch note |
| Iq | < 50 µA; stretch < 20 µA | matches gf180 |
| Startup | self-starting, < 1 ms | matches gf180 (gf180 additionally qualifies "at all corners, to within 1%" — adopt on next spec pass) |

## Port-parity confirmation (item 3 of #1)

**Confirmed — the spec mirrors gf180-bandgap.** Accuracy, trim, temp-coefficient, supply nominal, and Iq now match gf180-bandgap's ratified spec exactly. Two intentional, recorded differences, neither a parity break:

1. **Supply stretch is PDK-appropriate, not divergent:** sky130's stretch is the **1.8 V-core Banba variant** (a real sky130 device-menu option); gf180's is a 5 V flavor. Each PDK's stretch reflects its own device menu — parity is on the primary 3.3 V spec, which matches.
2. **PSRR frequency-qualification is a known minor gap:** the draft states `> 60 dB @ DC / > 70 dB`; gf180 states `> 60 dB DC–1 kHz / > 30 dB @ 1 MHz`. sky130's DC number matches; the band qualification and the 1 MHz stretch are **deferred to a follow-up spec pass** (flagged, not silently amended here) since the accuracy row was the ratification blocker and PSRR was not in question.

## Consequences

- **`README.md` line 50** (output-reference row) is amended to the ratified accuracy values, and line 48's table heading annotation changes from DRAFT to cite this record. A Trim row is added. Agent-executable follow-up in the same motion as this DR lands.
- **The layout gate opens:** #14 (DRC/LVS bring-up) and #15 (floorplan) may lock to this spec; #8's design chain unblocks. Their `Blocked by: #1` dependency is discharged.
- **A trim network is now in the block's scope** (`res_high_po`, per `error-amp-offset-budget.md`) — the ±0.5% trimmed line depends on it; layout must budget for it. This is a consequence of the accuracy ruling, not a new decision.
- **#11's characterization** verifies the ratified untrimmed ±2% over full PVT and, once a trim network exists, the ±0.5% trimmed line; a corner that misses is handled by fix-or-superseding-record, never silent relaxation.
- **PSRR band-qualification** is an open follow-up (see parity note 2).
