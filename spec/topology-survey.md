# Bandgap Topology Survey — sky130

**Status: engineering input, not a ratified decision.** This document compares
candidate bandgap-reference topologies against the draft spec in
[`README.md`](../README.md) and feeds two open decisions: spec ratification
(#1) and the supply/flavor scope call (#7). It does not itself ratify
anything — if a finding here argues for changing a spec line, that discussion
belongs in #1, not a silent edit to this file or to `README.md`.

Related, non-blocking: device characterization (#4) would sharpen the
resistor-flavor and mismatch judgments below once it lands; this survey
proceeds on sky130 PDK model-card data in the interim. Downstream consumers
of this survey's recommendation: schematic entry (#8, blocked on this
issue), the error-amplifier offset budget (#9, which inherits the
amp-offset-sensitivity notes below), and startup verification (#10, which
inherits the degenerate-state notes below).

**No simulated or measured numbers appear in this document.** Electrical
values quoted for sky130 primitives below are static SPICE model-card
parameters (`.model`/`.subckt` fields) read directly from the local PDK
checkout, not simulation output — consistent with CLAUDE.md's "no claim
without a testbench" for anything presented as measured/simulated data.
Topology-level TC/PSRR/Iq/area behavior is qualitative and literature-sourced
(see "Sources" at the end).

## Draft spec recap (from README.md, pending ratification in #1)

| Parameter | Target (3.3 V primary) | Stretch (1.8 V core) |
|---|---|---|
| Output reference | 1.20 V ±1% untrimmed | sub-1V Banba-style, ±0.5% w/ trim |
| Temp coefficient (−40…125 °C) | < 50 ppm/°C | < 20 ppm/°C |
| PSRR @ DC | > 60 dB | > 70 dB |
| Supply | 3.3 V ±10% | 1.8 V |
| Iq | < 50 µA | < 20 µA |
| Area | < 0.05 mm² | — |
| Startup | self-starting, < 1 ms | — |

## sky130 device menu (confirmed against the local PDK checkout)

The issue's device shorthand (`pnp_05v5`, poly resistor flavors, 5V-rated
thick-oxide MOS) is directionally correct but the literal cell names below
are what the PDK actually ships (`sky130A/libs.ref/sky130_fd_pr/spice`,
open-pdks `c6d73a35f524070e85faff4a6a9eef49553ebc2b`).

**Bipolar (substrate PNP — the only practical vertical bipolar for a bandgap
core in this PDK):**

- `sky130_fd_pr__pnp_05v5_W0p68L0p68` — small unit device. `Is ≈ 1.51e-18 A`,
  `BF ≈ 19.4`.
- `sky130_fd_pr__pnp_05v5_W3p40L3p40` — large unit device. `Is ≈ 7.12e-18 A`,
  `BF ≈ 16.6`.
- **Only two fixed geometries exist — there is no continuously-sized PNP.**
  Any emitter-area ratio (N:1) needed by a topology must be built by
  paralleling multiple unit devices in an array (e.g. 1× vs 8× of the small
  device, laid out common-centroid), not by scaling W/L on a single
  instance. This is a first-order layout/mismatch constraint for every
  candidate below, not just an implementation detail.
- The device's 4th SPICE terminal ties the substrate node to the Collector
  pin (`... Collector Base Emitter Collector <model>`) — i.e. this is a
  **grounded-collector substrate PNP**: the collector is fixed to the local
  substrate/deepest local ground reference, it cannot be used as a floating
  high-impedance node. Every topology below is evaluated against this
  constraint.
- `sky130_fd_pr__npn_05v5_W1p00L1p00` / `W1p00L2p00` also exist but are not
  considered further here — none of the five reference topologies benefit
  from an NPN core over the grounded-collector PNP, and the survey's
  candidate set is PNP-based per the issue body.

**Poly resistors (the ratio-critical PTAT/CTAT network in every candidate):**

- `sky130_fd_pr__res_high_po` (+ width variants `_0p35/_0p69/_1p41/_2p85/_5p73`):
  sheet resistance ≈ 317–345 Ω/sq (rbody vs rhead components differ
  slightly). Body TC: `tc1 ≈ +5.14e-4` (**+514 ppm/°C**), `tc2 ≈ +1.22e-6`
  (+1.22 ppm/°C²) — a **mild, fairly linear positive TC**.
- `sky130_fd_pr__res_xhigh_po` (+ same width variants): sheet resistance =
  2000 Ω/sq (**~6× more compact per Ω** than `res_high_po`). Body TC:
  `tc1 = -1.47e-3` (**−1470 ppm/°C**), `tc2 = +2.7e-6` — a **much stronger,
  opposite-sign TC** relative to `res_high_po`. Head/end resistors on both
  flavors share `tc1 = -4.3e-4`.
- `sky130_fd_pr__res_generic_pd` / `res_generic_nd` (diffusion resistors)
  exist but are junction-based (voltage-coefficient and TC nonlinearity from
  the underlying diode), not precision-analog candidates here; not used by
  any recommended candidate below.
- **Implication used throughout this survey**: `res_high_po` is the better
  default for any leg whose *absolute* TC linearity matters (it is 3× lower
  |TC1| and more linear than `res_xhigh_po`); `res_xhigh_po`'s much higher
  sheet resistance is attractive for area on high-value legs, but its
  stronger, opposite-sign TC means it is only safe where the design relies
  on *ratio* tracking between same-flavor unit resistors rather than
  absolute TC cancellation against the PNP's VBE slope.

**MOS (device menu, not modeled electrically here beyond voltage rating):**

- `sky130_fd_pr__nfet_01v8` / `pfet_01v8` (+ `_lvt`/`_hvt` variants) — 1.8 V
  core devices, used for the amplifier/mirror on the **1.8 V stretch
  flavor**.
- `sky130_fd_pr__nfet_g5v0d10v5` / `pfet_g5v0d10v5` — 5 V gate / 10.5 V
  drain thick-oxide "medium voltage" devices, the correct menu entry for
  **3.3 V primary** operation (gate never exceeds 5 V even when the 3.3 V
  ±10% rail is applied across drain-source).
- `sky130_fd_pr__nfet_05v0_nvt` / `nfet_03v3_nvt` — native (near-zero-Vt)
  devices, useful in startup/self-bias legs on either flavor where headroom
  is tight (notably the 1.8 V stretch core).

## Evaluation dimensions (applied identically to every candidate)

- **TC** < 50 ppm/°C, −40…125 °C (stretch: < 20 ppm/°C) — is curvature
  correction inherent to the topology, a bolt-on addition, or absent?
- **PSRR** > 60 dB @ DC (stretch: > 70 dB) — is supply rejection carried by
  an explicit high-gain error-amp loop, or by cascode/self-regulation?
- **Iq** < 50 µA (stretch: < 20 µA).
- **Area** < 0.05 mm² — relative sizing only (PNP array + resistor network +
  amp/mirror), not an extracted number.
- **Startup** self-starting, < 1 ms — does the topology have a degenerate
  zero-current state, and what does the startup circuit need to break it?
- **±1% untrimmed accuracy** (3.3 V primary) — decomposed into amplifier
  offset sensitivity (amp-based cores only), PNP VBE/area-ratio mismatch,
  and resistor-ratio mismatch.
- **Resistor-flavor demand** — which sky130 poly flavor the topology's
  PTAT/CTAT ratio realistically needs, and why.

Score labels used below: **Strong** (comfortably meets target with margin),
**Adequate** (meets target, limited margin or extra design care needed),
**Marginal** (meets target only with added compensation/complexity),
**Weak** (does not meet target as a bare topology).

---

## Candidate 1: Brokaw cell

Two grounded-collector PNPs (unequal area or unequal collector current) with
bases tied together; a differential error amplifier forces the correct
VBE-derived voltage across a degeneration resistor between the two emitter
legs, generating a PTAT current that is summed with the VBE floor at a third
resistor tapped from the common collector/base node. (Brokaw, *A Simple
Three-Terminal IC Bandgap Reference*, IEEE JSSC 1974.) Unlike the
Kuijk-style core, the PTAT current is summed directly at the output node
rather than passed through a separate ln(N) voltage-divider network.

| Dimension | Score | Reasoning |
|---|---|---|
| TC | Adequate | First-order VBE+PTAT cancellation identical in principle to Kuijk; curvature term is bolt-on (needs an added compensation branch to push below ~20–30 ppm/°C). |
| PSRR | Adequate–Strong | Carried by the error-amp loop gain, same as Kuijk; a cascoded output stage on `pfet_g5v0d10v5` gets comfortably past 60 dB DC. |
| Iq | Strong | Dominated by the amp bias branch + two PNP currents; easily under 50 µA at low-µA branch currents. |
| Area | Adequate | PNP array (built from the two fixed unit geometries per the device-menu note above) + 3 resistors + 2-stage amp; comparable footprint to Kuijk. |
| Startup | Adequate | Has the same degenerate zero-current state as any amp-plus-mirror loop; needs a standard startup injector — well-understood, not topology-specific risk. |
| ±1% untrimmed | Adequate | Amp offset still appears at the output, but summed directly through the PTAT-current path rather than through a large resistor-ratio divider — for some sizings this can give a smaller offset-amplification factor than Kuijk's `(R2/R1)` gain term (worth quantifying once #9 sizes the amp). |

- **Amplifier offset sensitivity**: present and material — the amp forces
  equal voltage across the degeneration resistor, so its input-referred
  offset directly perturbs the PTAT current and thus the output. This is
  the dominant untrimmed error source, same class of error as Kuijk but via
  a different signal path (current-summing vs. voltage-divider).
- **Startup/degenerate-state risk**: standard — a positive-feedback loop
  with a zero-current stable point; a conventional startup transistor
  injecting a small kick current into the core resolves it. No
  topology-specific surprise beyond what #10 already expects to analyze for
  any amp-based core.
- **Resistor-flavor demand**: the degeneration resistor and the output
  summing resistor form a ratio that sets both PTAT gain and the output
  tap — `res_high_po` is the right default for both (mild, linear TC keeps
  the ratio's temperature dependence predictable); `res_xhigh_po` is not
  needed since neither resistor is naturally large enough to justify its
  area saving at the cost of the strong opposite-sign TC.

## Candidate 2: CMOS-amp Kuijk-style (voltage-mode)

Two diode-connected, grounded-collector PNPs at an N:1 emitter-area ratio; a
CMOS op-amp forces equal voltage across a resistor pair, producing
`Vout = VBE + K·VT·ln(N)`. (Kuijk, *A Precision Reference Voltage Source*,
IEEE JSSC 1973, and its many CMOS-amp descendants — this is the de facto
industrial baseline and the reference point the other candidates are
compared against below.)

| Dimension | Score | Reasoning |
|---|---|---|
| TC | Adequate | Same first-order VBE+PTAT cancellation as Brokaw; curvature correction bolt-on. Most-published topology for hitting <50 ppm/°C untrimmed with a modest design effort. |
| PSRR | Adequate–Strong | Carried entirely by amp loop gain + output cascode; > 60 dB DC is routine on `pfet_g5v0d10v5` with one cascode stage. |
| Iq | Strong | Same order as Brokaw — amp bias branch dominates, comfortably < 50 µA. |
| Area | Adequate | PNP array (unit-device replication for the N:1 ratio) + 2–3 resistors + 2-stage amp; the best-characterized area budget of the five, since it is the most-published topology. |
| Startup | Adequate | Standard startup injector, same profile as Brokaw. |
| ±1% untrimmed | Adequate | The dominant untrimmed error is amp input-referred offset, amplified by the `(R2/R1)` gain from the divider node to the output — this ratio is the direct input #9 needs for its offset budget. Secondary contributors: PNP area-ratio mismatch (mitigated by unit-array common-centroid layout) and R1/R2 ratio mismatch (mitigated by `res_high_po`'s tight, linear TC and standard matching layout). |

- **Amplifier offset sensitivity**: the single largest untrimmed error term
  in this topology, because the offset is multiplied by the resistor
  divider gain before reaching the output — this is exactly the number #9
  needs to close its offset budget against the ±1% target, and it is the
  most literature-precedented of the five candidates for doing that
  analysis.
- **Startup/degenerate-state risk**: standard, well-documented startup
  circuit (diode-connected MOS injector breaking the zero-current state);
  lowest topology-specific risk of the five because it is the most-built
  pattern.
- **Resistor-flavor demand**: `res_high_po` for both divider resistors —
  the ratio (not the absolute value) sets the ln(N) gain term, and
  `res_high_po`'s milder, more linear TC keeps that ratio's temperature
  drift smaller and more predictable than `res_xhigh_po` would.

## Candidate 3: Self-biased current-mode core

No dedicated high-gain error amplifier; PTAT and CTAT currents are generated
and summed through a self-biasing MOS-mirror loop (Widlar-style or a
beta-multiplier-derived core), with the loop's own gain doing the job an
explicit amp does in candidates 1–2.

| Dimension | Score | Reasoning |
|---|---|---|
| TC | Adequate | Same first-order cancellation available in principle; curvature correction is bolt-on and, absent an explicit amp loop, typically requires more careful current-mirror design to keep the PTAT/CTAT ratio stable over the corner set. |
| PSRR | Marginal (as bare core) → Adequate (with added cascode) | No explicit high-gain loop enforcing supply-independence; hitting > 60 dB DC generally requires adding cascoded mirrors or a pre-regulation stage — which erodes the topology's Iq/area advantage once added. |
| Iq | Strong | The clearest advantage of this candidate — no dedicated amp bias branch, so Iq can be pushed well under 50 µA (and plausibly under the 20 µA *stretch* target) more easily than the amp-based cores. |
| Area | Adequate | Saves the amp's area relative to Kuijk/Brokaw, but the cascode/regulation stage usually needed to close PSRR gives some of that saving back. |
| Startup | Marginal | **Structurally higher risk than the amp-based cores.** The self-bias loop has (at minimum) two stable operating points sharing the same bias node: the desired nonzero-current point and an all-zero-current degenerate point, and — unlike a simple amp-plus-startup-injector — the startup circuit here must be placed *inside* the self-bias loop itself, not bolted onto an otherwise-independent amp. This is exactly the degenerate-state analysis #10 will need to do explicitly for whichever core is ultimately chosen; flagging it here rather than assuming it is solved by a generic startup transistor. |
| ±1% untrimmed | Marginal–Adequate | **No amplifier-offset term exists** (there is no discrete error amp), but MOS threshold-voltage mismatch and current-mirror ratio mismatch substitute as the dominant error source instead — this is a *different* error mechanism from candidates 1/2/4/5, not a strictly smaller one; sky130's `nfet_01v8`/`pfet_01v8` mismatch model cards (`vth0_slope` mismatch terms) would need to be pulled into #9's budget in place of an amp-offset term if this core is selected. |

- **Amplifier offset sensitivity**: **not applicable** — there is no
  dedicated error amplifier. The substituted error source is MOS
  threshold-voltage mismatch (`ΔVTH`) and W/L mirror-ratio mismatch across
  the self-biasing loop's transistors, which #9 would need to model
  differently (device mismatch model cards, not an amp offset spec) if this
  core is chosen.
- **Startup/degenerate-state risk**: the standout risk for this candidate —
  see the Startup row above. This is not a minor caveat; it is the primary
  reason this candidate is not recommended as primary below.
- **Resistor-flavor demand**: still needs a PTAT/CTAT-setting resistor
  ratio (typically smaller in count than Kuijk/Brokaw since some ratio-
  setting is done via mirror W/L ratios instead of resistors); `res_high_po`
  remains the right default for whatever resistor legs remain, for the same
  TC-linearity reason as the other amp-based candidates.

## Candidate 4: Banba (current-mode, resistor-summing sub-bandgap)

`Vout = R3·(I_PTAT + I_CTAT)`, with no stacked VBE sitting directly in the
output path — the output is set by resistor ratios rather than a fixed
`VBE + K·VT·ln(N)` floor, which is what makes sub-1 V / 1.8 V-core operation
possible. (Banba et al., *A CMOS Bandgap Reference Circuit with Sub-1-V
Operation*, IEEE JSSC 1999.) Still uses an error amplifier internally (to
force the two VBE-derived branch voltages equal, generating I_PTAT), it is
the *output* that decouples from the VBE floor, not the amplifier.

| Dimension | Score | Reasoning |
|---|---|---|
| TC | Adequate | Inherent first-order I_PTAT+I_CTAT cancellation; curvature correction is bolt-on (an added compensation current branch) to reach the < 20 ppm/°C stretch target. |
| PSRR | Adequate (with care) | Carried by the internal error-amp loop plus current-mirror PSRR; hitting the *stretch* > 70 dB target on a 1.8 V rail is tighter than on 3.3 V — cascode headroom is scarce at 1.8 V, so the mirror/cascode design has less margin than the 3.3 V-flavor candidates above. Flag explicitly for whoever designs the 1.8 V amp in #9. |
| Iq | Strong | No stacked-VBE headroom to waste; naturally low-current, well suited to the < 20 µA stretch target. |
| Area | Adequate | Three resistor legs (R1, R2, R3) + PNP pair + amp + mirror array — comparable order to Kuijk, not smaller or larger in any first-order way. |
| Startup | Adequate | Same class of degenerate zero-current state as Kuijk/Brokaw (it has an internal error amp + mirror loop); standard startup injector applies. |
| ±0.5% (trimmed) / accuracy | Adequate | Amp offset still propagates into I_PTAT and then through R3's gain to the output — and unlike Kuijk, there is no VBE floor partially absorbing that error, so the offset budget in #9 needs to be built fresh for this topology rather than reused from the 3.3 V candidate above. PNP area-ratio mismatch and the R1:R2:R3 ratio mismatch are additional, independent error sources (three resistor ratios instead of two). |

- **Amplifier offset sensitivity**: present and arguably *more* exposed than
  Kuijk's, because there is no VBE floor term in the output to dilute the
  offset's relative contribution — the entire output is built from
  amplified/summed currents. #9 should not assume the Kuijk offset budget
  transfers directly to this topology.
- **Startup/degenerate-state risk**: standard amp-plus-mirror degenerate
  state, same mitigation as Kuijk/Brokaw — lower risk than the self-biased
  core (candidate 3).
- **Resistor-flavor demand**: three resistor legs with two independent
  ratios (R3/R1 and R3/R2) to hold across corners — `res_high_po` is the
  right default for the ratio-critical legs given its milder, more linear
  TC; if area pressure pushes toward `res_xhigh_po`'s ~6× denser sheet
  resistance for one leg, it should only be a leg whose *ratio* to a
  same-flavor partner resistor is what matters (not its absolute TC against
  the PNP's VBE slope), given `res_xhigh_po`'s much stronger, opposite-sign
  TC1.

## Candidate 5: Malcovati (weighted/curvature-compensated Banba generalization)

Generalizes Banba by adding a weighting/scaling factor on the summed
currents (an extra current branch and/or resistor tap), so the output
magnitude is not pinned to whatever value Banba's bare R-ratios naturally
produce, and by adding an explicit curvature-compensation current (typically
subthreshold-MOS-derived) rather than treating curvature correction as a
separate bolt-on. (Malcovati et al., *Curvature-Compensated BiCMOS Bandgap
with 1-V Supply Voltage*, IEEE JSSC 2001.)

| Dimension | Score | Reasoning |
|---|---|---|
| TC | Strong | The one candidate here where curvature compensation is part of the topology's own definition rather than an afterthought — best-positioned of the five to reach the < 20 ppm/°C stretch target without a separate bolt-on branch. |
| PSRR | Adequate (with care) | Same 1.8 V headroom caveat as Banba, plus the extra weighting branch is another node whose supply-sensitivity needs to be checked. |
| Iq | Adequate | Slightly worse than bare Banba — the added weighting/compensation branch draws its own bias current — but still well within the < 20 µA stretch target for reasonable branch sizing. |
| Area | Adequate | Modest area premium over Banba for the extra branch/mirror; still well inside the 0.05 mm² budget in absolute terms, the delta matters only relative to Banba. |
| Startup | Adequate | Same class of risk as Banba — the added branch is another amp/mirror loop that also needs to clear its own zero-current state, so the startup circuit's scope is larger (more nodes to guarantee) even though the risk *class* is unchanged. |
| ±0.5% (trimmed) / accuracy | Marginal–Adequate | More summing/weighting nodes than Banba means more independent offset and mismatch contributors feeding into the output — each helps flexibility (tunable output value, better curvature) at the cost of a wider, harder-to-close error budget in #9. |

- **Amplifier offset sensitivity**: present at every summing node in the
  design (the base Banba amp plus the added weighting branch), so the
  offset budget is strictly more complex to build than Banba's — more
  independent terms to characterize, not a single dominant one.
- **Startup/degenerate-state risk**: same class as Banba, but #10's
  degenerate-state analysis has more nodes to cover (the added
  weighting/compensation branch is itself a loop that needs to start).
- **Resistor-flavor demand**: same as Banba, plus the additional matched
  resistors/mirrors in the weighting network — no new flavor requirement,
  just more instances of the same `res_high_po`-preferred pattern.

### Other variants considered

No sixth distinct base topology emerged from this survey that isn't better
described as a refinement layered onto Banba/Malcovati (e.g. piecewise-
linear or exponential curvature-correction add-ons) — those are captured
above as "bolt-on curvature correction" rather than separate candidates.
Nothing here argues for dropping any of the five required candidates.

---

## Cross-candidate summary

| | Brokaw | Kuijk-style | Self-biased | Banba | Malcovati |
|---|---|---|---|---|---|
| TC (bare) | Adequate | Adequate | Adequate | Adequate | **Strong** |
| PSRR | Adequate–Strong | Adequate–Strong | **Marginal→Adequate** | Adequate (1.8V headroom-limited) | Adequate (1.8V headroom-limited) |
| Iq | Strong | Strong | **Strong** | Strong | Adequate |
| Area | Adequate | Adequate | Adequate | Adequate | Adequate (small premium) |
| Startup risk | Standard | Standard | **Elevated** | Standard | Standard (more nodes) |
| Amp-offset term? | Yes (current-summed) | Yes (voltage-divided) | **No — MOS mismatch instead** | Yes (undiluted by VBE floor) | Yes (multiple nodes) |
| Resistor flavor | `res_high_po` | `res_high_po` | `res_high_po` (fewer legs) | `res_high_po` (3-leg ratio) | `res_high_po` (more legs) |
| Sub-1V capable? | No | No | No | **Yes** | **Yes, tunable** |

---

## Recommendation

**This section is input to #1 (spec ratification) and #7 (supply/flavor
scope decision) — it recommends, it does not decide.**

### 3.3 V primary

- **Primary: CMOS-amp Kuijk-style.** It is the most-published, best-
  characterized of the five for exactly this spec profile (1.2 V ±1%
  untrimmed, < 50 ppm/°C, > 60 dB DC PSRR, < 50 µA, < 0.05 mm², self-
  starting < 1 ms) with a mature, well-understood startup pattern and the
  single clearest offset-to-output gain relationship (`R2/R1`) for #9 to
  budget against directly. It maps cleanly onto sky130's fixed two-geometry
  PNP menu (N:1 built as unit-array replication) and `res_high_po`'s mild,
  linear TC for the divider ratio.
- **Fallback: Brokaw cell.** Comparable TC/PSRR/Iq/area profile with a
  structurally different offset-injection path (current-summed rather than
  voltage-divided) — worth keeping in reserve specifically in case #9's
  offset-budget analysis finds Kuijk's resistor-divider gain amplifies amp
  offset more than the ±1% target tolerates for a realistic sky130 amp
  design; Brokaw's direct current-summing path is a plausible way to reduce
  that amplification factor without changing device menu or resistor
  flavor.
- **Not recommended as primary or fallback: self-biased current-mode
  core.** Its Iq advantage is real, but its structurally elevated startup
  risk (startup circuit must live *inside* the self-bias loop, not bolted
  onto an independent amp) and the PSRR margin it gives back once a
  cascode/regulation stage is added to hit > 60 dB DC make it a weaker fit
  than Kuijk or Brokaw for a first-pass ±1%-untrimmed design. Worth
  revisiting later specifically if Iq becomes the binding constraint (e.g.
  a future ultra-low-power variant), but not for this spec's primary flavor.

### 1.8 V stretch

- **Primary: Banba.** Minimum-complexity path to sub-1 V current-mode
  operation on the 1.8 V core; the most-cited sub-bandgap reference
  architecture, with adequate TC/PSRR/Iq for the stretch targets once
  curvature compensation and cascoded mirrors are added, and the fewest
  independent offset/mismatch nodes of the two sub-1V candidates — keeping
  #9's stretch-flavor offset budget and #10's stretch-flavor startup
  analysis as tractable as this architecture class allows.
- **Fallback: Malcovati.** Recommended as fallback rather than primary
  because its main advantages — tunable output magnitude and inherent
  (non-bolt-on) curvature compensation — are only worth their added
  offset-node and area cost if either (a) the ratified spec/scope decision
  locks in a specific 1.8 V-flavor output value that Banba's bare resistor
  ratios cannot hit cleanly, or (b) Banba's bolt-on curvature correction is
  shown insufficient to reach the < 20 ppm/°C stretch TC target. Absent
  either condition, adopt Banba first and only escalate to Malcovati if it
  proves insufficient — no reason to carry Malcovati's extra offset/area
  burden speculatively.

---

## Cross-references

- Input to: #1 (spec ratification), #7 (supply/flavor scope decision).
- Feeds: #9 (error-amplifier offset budget — inherits the per-candidate
  amp-offset-sensitivity notes above), #10 (startup verification — inherits
  the per-candidate degenerate-state notes above), #8 (schematic entry,
  blocked on this issue's recommendation).
- Informed by (non-blocking): #4 (device characterization) — this survey
  uses sky130 PDK model-card data directly; #4's measured/simulated
  characterization would sharpen but is not required to unblock the
  recommendation above.

## Sources

- A. P. Brokaw, "A Simple Three-Terminal IC Bandgap Reference," *IEEE
  Journal of Solid-State Circuits*, vol. 9, no. 6, 1974.
- K. E. Kuijk, "A Precision Reference Voltage Source," *IEEE Journal of
  Solid-State Circuits*, vol. 8, no. 3, 1973.
- H. Banba et al., "A CMOS Bandgap Reference Circuit with Sub-1-V
  Operation," *IEEE Journal of Solid-State Circuits*, vol. 34, no. 5, 1999.
- P. Malcovati, F. Maloberti, C. Fiocchi, M. Pruzzi, "Curvature-Compensated
  BiCMOS Bandgap with 1-V Supply Voltage," *IEEE Journal of Solid-State
  Circuits*, vol. 36, no. 7, 2001.
- SkyWater sky130 PDK, `sky130_fd_pr` analog primitive SPICE model cards
  (`sky130A/libs.ref/sky130_fd_pr/spice/`), open-pdks commit
  `c6d73a35f524070e85faff4a6a9eef49553ebc2b`: `pnp_05v5_W0p68L0p68`,
  `pnp_05v5_W3p40L3p40`, `res_high_po`, `res_xhigh_po`, `nfet_g5v0d10v5`,
  `pfet_g5v0d10v5`, `nfet_01v8`, `pfet_01v8`, `nfet_05v0_nvt`,
  `nfet_03v3_nvt`, and the shared TC constants in
  `libs.tech/ngspice/sky130_fd_pr__model__r+c.model.spice`.
