# Device Characterization Summary — sky130 Bandgap Core (Issue #4)

**Status**: characterization complete, all records PASS — full PVT matrices
for §§1–3, plus a Monte Carlo local-mismatch experiment in §4 whose
process/supply-axis subset is justified in its own record.
This is a summary of measured/simulated results; it does not itself ratify
spec values (that is #1's job) or the topology (that is #3/#8's job) — it
gives both of those issues real sky130 device data to cite instead of the
static PDK model-card values `spec/topology-survey.md` used as a
placeholder.

Scope: wave 1, 3.3 V primary only, per DR-001
(`spec/decision-records/DR-001-supply-flavor-scope.md`). No 1.8 V-flavor
devices (`nfet_01v8`/`pfet_01v8`, native devices) were characterized here —
out of scope for this issue's wave.

Evidence backing every number below (append-only, `sim/README.md` format):

| Family | Experiment | Record ID | Corners run |
|---|---|---|---|
| Substrate PNP | `sim/pnp-characterization/` | `20260801-041501-48ac24d` (supersedes `20260731-043353-a8c4147`, issue #35) | 15/15 (tt/ss/ff/sf/fs × −40/27/125 °C @ 3.30 V) — PASS |
| Poly resistors | `sim/resistor-flavor-characterization/` | `20260731-044337-a8c4147` | 21/21 (tt/ss/ff/sf/fs/ll/hh × −40/27/125 °C @ 3.30 V) — PASS |
| 5 V MOS mirror devices | `sim/mos-matching-characterization/` | `20260731-045825-a8c4147` | 15/15 (tt/ss/ff/sf/fs × −40/27/125 °C @ 3.30 V) — PASS |
| Substrate PNP pair, local mismatch (§4, issue #31) | `sim/pnp-mismatch/` | `20260731-232801-ab27f82` | 3 Monte Carlo points (`tt_mm` × −40/27/125 °C, N = 300 each) + 1 MC-off control + 1 second-seed point — PASS |

All of these testbenches bias their DUTs with ideal current sources referenced
to ground only (no supply-referenced terminal), so the ±10 % supply axis is
intentionally fixed at nominal 3.30 V in each `experiment.json` — documented
per-experiment as the reason a supply sweep would not change any result. The
mismatch experiment (§4) has no supply rail at all and no `experiment.json`:
Monte Carlo sampling is a different axis than the PVT matrix
`sim/bin/corner-run.py` drives, so it ships a bespoke run script and states
its process/supply-axis justification inline in the record.

---

## 1. Substrate PNP (`sky130_fd_pr__pnp_05v5_W0p68L0p68` / `_W3p40L3p40`)

Testbench: `sim/pnp-characterization/testbench/tb_pnp_vbe.sch` — both
emitter-size variants diode-connected with **base and collector grounded and
the emitter driven** (the connection a bandgap core has, so VEB =
V(emitter)), each swept across 7 emitter currents (100 nA – 100 µA,
half-decade steps) at every PVT point.

> **Record `20260801-041501-48ac24d` supersedes `20260731-043353-a8c4147`
> (issue #35).** The original ladder wired each current source to the
> subcircuit's **collector** pin with the emitter grounded, so it measured
> the base-collector junction, not VEB: its ideality table, current-density
> window and dVBE figures did not describe the quantity a bandgap core uses.
> The superseded record is retained under
> `sim/pnp-characterization/records/` (`sim/` is append-only); **every
> number in this section comes from the new, emitter-driven record**, and
> the two are not interchangeable — VEB at tt / 27 °C / 1 µA moved from
> 0.545166 V (collector-driven) to 0.742539 V (emitter-driven). §4's
> independently written raw-SPICE deck measures 0.742569 V for the same
> device at the same bias, an agreement to 30 µV that is now a genuine
> cross-validation of both testbenches rather than a discrepancy.

### Ideality factor (n), extracted from consecutive half-decade VEB steps

n = ΔVEB / (V_T · ln(ΔIe)), evaluated at the `tt` corner (representative —
see "process-corner sensitivity" below):

| Ie step | n, small (`W0p68L0p68`, area 0.4624 µm²) | n, large (`W3p40L3p40`, area 11.56 µm²) |
|---|---|---|
| 100 nA → 316 nA | 1.045 | 1.012 |
| 316 nA → 1 µA | 1.061 | 1.012 |
| 1 µA → 3.16 µA | 1.111 | 1.014 |
| 3.16 µA → 10 µA | 1.249 | 1.025 |
| 10 µA → 31.6 µA | 1.565 | 1.057 |
| 31.6 µA → 100 µA | 2.226 | 1.142 |

(values shown at 27 °C; the −40/125 °C ladders track these within ±0.06 on
every step except the last, where n_small is 2.39 at −40 °C and 2.14 at
125 °C — see the full record for all three temperatures)

Note the floor: the small device never reaches n = 1.00, even at 100 nA.
That is not a fitting artifact — its model card carries `nf = 1.028` against
the large device's `nf = 1.000` (`continuous/models_bjt.spice`), and that
2.8 % emission-coefficient offset turns out to be the single largest term in
the dVBE figures below.

**Usable current-density window**: ideality stays ≲ 1.1 (near-ideal) up to
~1 µA on the small unit device (current density J = Ie/area ≈ 2.2 µA/µm²)
and up to ~10 µA on the large unit (J ≈ 0.87 µA/µm², n ≤ 1.03 there). Beyond
that the roll-off worsens quickly — n_small is 1.25 by 10 µA and 1.57 by
31.6 µA, while n_large is still only 1.06 at 31.6 µA.

The asymmetry is **not** a current-density effect, and the two unit devices
are emphatically not current-density clones of each other: the small device
tolerates ~2.5× the *density* of the large one before rolling off. The model
card says why — the degradation terms scale nothing like the 25× area ratio:

| Parameter | small `W0p68L0p68` | large `W3p40L3p40` | ratio |
|---|---|---|---|
| `re` (emitter series R) | 219 Ω | 5.38 Ω | 41× |
| `rb` (base series R) | 316 Ω | 73.3 Ω | 4.3× |
| `ikf` (high-injection knee) | 33.1 µA | 386 µA | 11.7× |
| emitter area | 0.4624 µm² | 11.56 µm² | 25× |

Roll-off on the small device is therefore dominated by its 219 Ω emitter
resistance and by an `ikf` knee that sits *inside* the swept ladder — neither
of which a density-normalised argument predicts.

**Recommendation for sizing**: keep each *unit* PNP's emitter current at or
below ~1 µA (small device) / ~10 µA (large device) if the design wants
n ≲ 1.1 everywhere in the −40…125 °C range. Both fit inside the < 50 µA
total Iq budget for a handful of unit devices, but this now rules out running
a single small-unit device even at 3–10 µA where ideality matters at the edge
of the temperature range (n_small = 1.13 already at the 1 → 3.16 µA step at
125 °C) — favor the large unit, or parallel small units, for any leg carrying
more than about a microamp.

### Process-corner sensitivity

VEB is **weakly sensitive to process corner** at fixed temperature, and
**strongly sensitive to temperature**. Across tt/ss/ff/sf/fs at 1 µA the
small device's VEB spans:

| Temperature | `veb_small_1u` range across the 5 process corners | spread |
|---|---|---|
| −40 °C | 0.851572 V (sf) – 0.854474 V (fs) | 2.90 mV (0.34 %) |
| 27 °C | 0.740969 V (sf) – 0.743224 V (fs) | 2.26 mV (0.30 %) |
| 125 °C | 0.565701 V (sf) – 0.567341 V (fs) | 1.64 mV (0.29 %) |

against 287 mV of movement over the same −40…125 °C span at `tt`
(≈ −1.74 mV/°C). The corner ordering is consistent (sf lowest, fs highest)
at every temperature, so the process axis behaves as a small systematic
offset rather than noise. This is ≈ 100× larger than the < 20 µV the
superseded collector-driven record reported — the base-collector junction
really was nearly corner-blind; the emitter-base junction is not, though
2–3 mV is still small next to the ±15 % resistor spread of §2. Temperature
remains the dominant sensitivity axis for this device family. (Consistent
with `sim/pdk.json`'s note that `tt/ss/ff/sf/fs` gate BJT `Is`/`Bf`/`Nf`
only weakly relative to the MOSFET parameters they are named for.)

### dVBE (PTAT term) between the two emitter-size variants — a correction to the topology survey

`spec/topology-survey.md` computed the survey's PTAT-gain expectations from
the two devices' static model-card `Is` values (`Is_small ≈ 1.51e-18 A`,
`Is_large ≈ 7.12e-18 A`, ratio ≈ 4.72). **The simulated dVBE at matched
current is larger than that assumption implies — roughly a 10× effective
ratio, and nearly temperature-independent**:

| Corner | dVBE @ 100 nA (matched Ie) | dVBE @ 1 µA | Implied `Is_large/Is_small` (from the 100 nA column, n = 1) |
|---|---|---|---|
| tt, −40 °C | 47.84 mV | 49.45 mV | 10.8 |
| tt, 27 °C | 60.52 mV | 62.97 mV | 10.4 |
| tt, 125 °C | 79.14 mV | 82.24 mV | 10.0 |

**This inverts the conclusion the superseded record supported.** That record
(collector-driven) reported 5.45 / 14.40 / 37.52 mV and an implied ratio
climbing 1.31 → 2.98 with temperature — i.e. *less* PTAT than the model card
promised, and strongly temperature-dependent. The emitter-driven measurement
says the opposite on both counts. Anything sized against those three numbers
needs re-deriving.

The extra PTAT is real but **it is not extra area ratio**, and the
distinction matters for sizing. Decomposing the 27 °C figure against the
model card:

| Term | at 27 °C | mechanism |
|---|---|---|
| `V_T · ln(Is_large/Is_small)` | 40.2 mV | the genuine 4.72× `Is` ratio — true PTAT |
| `(nf_small − 1) · VBE_small` | 18.1 mV | small device's `nf = 1.028` vs large's `1.000` — a fraction of a *CTAT* quantity |
| `ise` / `re` / `rb` residual | 2.3 mV | series and non-ideal-injection terms |
| **measured total** | **60.5 mV** | |

Because the second term is a fixed fraction of a CTAT voltage, the measured
dVBE is **sub-PTAT**: anchored at −40 °C, strict proportionality to absolute
temperature would predict 61.6 mV at 27 °C and 81.7 mV at 125 °C against the
measured 60.5 and 79.1 mV — a 1.7 % / 3.1 % shortfall that grows with
temperature. A `K·ΔVBE` core sized on the assumption that ΔVBE is exactly
proportional to T will therefore see a residual, systematically-signed
curvature term from this device pair, on top of the usual VBE curvature.

Practical consequences for #8/#9: use the measured dVBE figures above (or
re-derive from a matched-current sweep at the actual bias point) rather than
either the raw model-card `Is` ratio or an `N`-from-geometry argument — the
pair's *effective* `ln(N)` is ≈ ln(10.4), not ln(4.72), but roughly a third
of it is `nf`-derived and does not scale when unit devices are paralleled.
Building a larger effective
area ratio via a paralleled unit-device array (as `spec/topology-survey.md`
already requires for other reasons — PNP geometries are fixed, not
continuously sized) is the mitigation if a topology needs more PTAT gain
than this pair alone provides.

---

## 2. Poly resistor flavors (`sky130_fd_pr__res_high_po`, `sky130_fd_pr__res_xhigh_po`)

Testbench: `sim/resistor-flavor-characterization/testbench/tb_res_flavors.sch`
— two lengths (L=1 µm, L=20 µm; W=1 µm) per flavor, 1 µA bias each; sheet
resistance extracted by the two-length slope method (removes head/contact
resistance): `Rs = (R(L20) − R(L1)) · W / (L20 − L1)`.

**Device-name caveat resolved**: there is no separate "precision p+ poly"
cell in this PDK checkout — `sky130_fd_pr__res_high_po` *is* the
precision, non-silicided p+ poly flavor (confirmed against
`continuous/models_resistors.spice`; only two poly flavors exist,
`res_high_po` and `res_xhigh_po`).

### Sheet resistance (27 °C, `tt` corner unless noted)

| Flavor | Rs (Ω/sq), tt/27 °C | Rs range across process (tt/ss/ff/sf/fs, 27 °C) | Rs range across resistor-skew corners (ll/hh, 27 °C) |
|---|---|---|---|
| `res_high_po` | 324.8 | 321.3 – 328.4 (±1.1 %) | 276.9 (ll) – 369.8 (hh) (≈ −15 % / +14 %) |
| `res_xhigh_po` | 2118.6 | 2118.6 (flat to sim precision) | 1800.9 (ll) – 2436.4 (hh) (≈ −15 % / +15 %) |

Confirms `sim/pdk.json`'s documented finding: the standard `tt/ss/ff/sf/fs`
corners barely move resistor value (< 2.5 % spread) — the PDK's dedicated
`ll`/`hh` resistor-skew corners are where the ≈ ±15 % process spread
actually shows up. Any resistor-ratio or absolute-value margin analysis
must sweep `ll`/`hh`, not just `tt/ss/ff/sf/fs`.

### Temperature coefficient

| Flavor | TC, −40→27 °C (measured) | TC, 27→125 °C (measured) | TC (PDK model card, `tc1`) |
|---|---|---|---|
| `res_high_po` | +426 ppm/°C | +627 ppm/°C | +514 ppm/°C |
| `res_xhigh_po` | ≈ +0.6 ppm/°C (single-length, issue #25) | ≈ −2.6 ppm/°C (single-length, issue #25) | **−1470 ppm/°C** |

`res_high_po`'s measured TC is a positive, mildly-accelerating curve
(steeper hot than cold), same sign and same order of magnitude as the model
card's static `tc1` — this cross-validates the survey's number.

**`res_xhigh_po` re-measured at a single length (issue #25) — confirmed
flat; root cause identified as an ngspice/model-implementation limitation,
not a testbench artifact.** The original two-length subtraction method
(`sim/resistor-flavor-characterization/`, record
`20260731-044337-a8c4147`) returned an essentially flat TC and flagged a
plausible confound: its L=1 µm (≈2 mV drop) and L=20 µm (≈42 mV drop) legs
sit at very different bias voltages at fixed 1 µA, and `res_xhigh_po`'s
model defines a length-dependent voltage-coefficient term that could distort
a length-difference extraction. `sim/resistor-tc-single-length/` (record
`20260731-073440-3dfe830`, full 21-point PVT matrix, PASS) re-measured with
four legs designed to falsify that bias-mismatch theory rather than merely
produce a different number:

- **Primary DUT** (`res_xhigh_po`, W=1 µm, L=50 µm, 5 µA, ≈0.53 V drop — a
  representative bias-setting-resistor operating point for this block, see
  §3) is flat: ≈+0.6 ppm/°C (−40→27 °C) / ≈−2.6 ppm/°C (27→125 °C), `tt`
  corner — same order of magnitude as the two-length figure, at a single
  length and a realistic bias point.
- **10× lower bias** (0.5 µA, ≈53 mV drop) at the identical geometry tracks
  the primary DUT to within ≈0.001 % at every one of the 21 corners —
  ruling out a voltage-coefficient effect as the explanation; bias-point
  choice is not moving this measurement.
- **10× shorter length at matched current density** (L=5 µm, 5 µA) is also
  flat and stays two orders of magnitude below the model card's TC — ruling
  out the model's length-dependent voltage-coefficient term and the fixed
  head/contact resistance's share of the total as the explanation.
- **`res_high_po` positive control** at the identical length/bias moves
  strongly and correctly with temperature (16.16 kΩ → 16.62 kΩ → 17.62 kΩ,
  `tt` corner, −40/27/125 °C) — proving `.temp` reaches the resistor models
  in this deck; the flatness is specific to `res_xhigh_po`.
- **Simulator-mechanism probe**: three ideal 1 kΩ resistors sharing one
  `.model` card (`tc1=-1.47e-3 tc2=2.7e-6`), differing only in how `r=` is
  written. The literal (`r=1000`) and constant-expression (`r='1000*1.0'`)
  forms track `.temp` exactly as the model predicts (1106.96 Ω / 997.07 Ω /
  880 Ω at −40/27/125 °C, every process corner) — but the
  voltage-dependent-expression form (`r='1000*(1+1e-12*abs(v(...)))'`) reads
  **exactly** 1000.000 Ω at every one of the 21 PVT points, completely
  ignoring the shared `tc1`/`tc2`.

Cross-checked against the PDK's own model source
(`sky130_fd_pr/spice/sky130_fd_pr__res_xhigh_po__base.model.spice`):
`res_xhigh_po`'s `rbody` element is written in exactly this pattern —
`rbody ra r2 r = {rbody*(1+abs(v(r1,r2))*vc1_body+...)} tc1 = -1.47e-3 tc2 =
2.7e-6` — a voltage-dependent behavioral resistor with `tc1`/`tc2` declared
on the same element. This is a direct, mechanistic match to the simulator
probe above: **ngspice does not apply `tc1`/`tc2` temperature scaling to a
resistor whose value is a voltage-dependent expression**, which is exactly
the element type `res_xhigh_po` uses for its body. The flat simulated TC is
therefore a genuine ngspice/PDK-model-interaction limitation of this
simulation path, not a bias-point or two-length-subtraction artifact of the
original testbench, and not evidence that the physical device lacks the
model card's TC.

**Design guidance unchanged: continue to treat the model card's
`tc1 = −1470 ppm/°C` as authoritative for `res_xhigh_po`.** ngspice's
op-analysis simulation of this device cannot currently reproduce that
figure (mechanism identified above), so no numeric TC figure for
`res_xhigh_po` from this harness should be substituted for the model card
value in a design decision. This methodology question is now closed — see
"Follow-up issues" below.

### Mismatch (pulled directly from the PDK's own resistor models, per the acceptance criteria — not simulated Monte Carlo)

From `libs.tech/combined/continuous/models_global.spice`:

| Flavor | Mismatch coefficient (`sw_mm_sky130_fd_pr__*`) | σ(R)/R model |
|---|---|---|
| `res_high_po` | 2.06 % | `σ_R/R = 2.06 % / sqrt(W·L)` (W, L in µm) |
| `res_xhigh_po` | 4.64 % | `σ_R/R = 4.64 % / sqrt(W·L)` (W, L in µm) |

`res_xhigh_po` mismatches roughly 2.25× worse than `res_high_po` per unit
area — consistent with its much higher sheet resistance (fewer squares of
poly per unit area for the same nominal value).

### Recommendation — confirms the topology survey's provisional pick, with one caveat

- **PTAT resistor and output-ladder legs: `res_high_po`.** Confirms
  `spec/topology-survey.md`'s provisional pick. Its milder, positive,
  now cross-validated TC keeps ratio-to-VBE-slope cancellation predictable,
  and its mismatch (2.06 %/√(WL)) is the better of the two flavors.
- **Trim network: `res_high_po`** for the same TC-predictability reason,
  sized for the smallest area the trim step resolution allows; do not reach
  for `res_xhigh_po`'s density advantage on a trim leg where absolute TC
  tracking against the main ladder matters.
- **`res_xhigh_po`** remains reasonable only for legs where *ratio to
  another same-flavor `res_xhigh_po` resistor* is what matters (not
  absolute TC against the PNP's VBE slope) — e.g. a bias-current-setting
  resistor whose partner is also `res_xhigh_po` — per the survey's original
  guidance, now with the caveat that its TC needs the follow-up
  measurement above before being treated as simulation-confirmed.

---

## 3. MOS mirror-device matching (`sky130_fd_pr__nfet_g5v0d10v5` / `sky130_fd_pr__pfet_g5v0d10v5`)

Testbench: `sim/mos-matching-characterization/testbench/tb_mos_matching.sch`
— diode-connected NFET/PFET at two sizes (A: W=4/L=1 µm, 4 µm²; B: W=8/L=2
µm, 16 µm², 4× A) and three bias currents (2/5/20 µA, spanning the
per-branch range implied by < 50 µA total Iq), operating-point parameters
(`Id`, `Vth`, `Vov = Vgs−Vth`, `gm/Id`) read directly from the BSIM model
via `@m.<instance>.<model>[param]`.

The PDK's static Vth-mismatch (AVT) coefficients (only mismatch term this
device family exposes — no separate mobility/beta mismatch term in the
model), from `continuous/models_global.spice`:

| Device | `sw_mm_vth0` coefficient |
|---|---|
| `nfet_g5v0d10v5` | 8.2 mV·µm |
| `pfet_g5v0d10v5` | 12.0 mV·µm |

σ(Vth) = coefficient / √(W·L); analytic mismatch projection
`σ(ΔId/Id) ≈ (gm/Id) · σ(Vth)` (Pelgrom-style, first-order — this is the
correct combination method given the PDK models only expose a Vth0 mismatch
term for this family, not a separate current-factor term).

### Operating point and projected mismatch (tt, 27 °C — see the full record for all 15 PVT points)

| Device | Size | Ic | Vov (V) | gm/Id (1/V) | σ(Vth) (mV) | Projected σ(ΔId/Id) |
|---|---|---|---|---|---|---|
| NFET | A (4 µm²) | 2 µA | 0.051 | 15.4 | 4.10 | 6.31 % |
| NFET | A | 5 µA | 0.118 | 11.7 | 4.10 | 4.81 % |
| NFET | A | 20 µA | 0.279 | 6.21 | 4.10 | 2.55 % |
| NFET | B (16 µm²) | 2 µA | 0.065 | 14.9 | 2.05 | 3.05 % |
| NFET | B | 5 µA | 0.136 | 11.1 | 2.05 | 2.27 % |
| NFET | B | 20 µA | 0.308 | 5.89 | 2.05 | 1.21 % |
| PFET | A (4 µm²) | 2 µA | 0.153 | 12.2 | 6.00 | 7.30 % |
| PFET | A | 5 µA | 0.243 | 8.23 | 6.00 | 4.94 % |
| PFET | A | 20 µA | 0.496 | 3.67 | 6.00 | 2.20 % |
| PFET | B (16 µm²) | 2 µA | 0.133 | 10.8 | 3.00 | 3.25 % |
| PFET | B | 5 µA | 0.235 | 7.36 | 3.00 | 2.21 % |
| PFET | B | 20 µA | 0.508 | 3.57 | 3.00 | 1.07 % |

### Recommended operating region

Mismatch improves with **both** larger device area and higher `Vov` (lower
`gm/Id`) — the two levers trade against headroom (higher `Vov` eats into
cascode/output swing at 3.3 V) and Iq. For a mirror device whose current
mismatch has to stay in the low single digits of a percent against a
< 50 µA total Iq budget:

- **Recommended region: `Vov ≈ 0.10 – 0.30 V` (moderate-to-strong
  inversion, `gm/Id` ≈ 6 – 12 1/V), device area ≥ size B (16 µm²), biased
  toward the upper half of the 2 – 20 µA per-branch range** where feasible.
  At size B / 20 µA this reaches ≈ 1.1 – 1.2 % projected mismatch on either
  device type — still not negligible against a ±1 % untrimmed output
  target, so **the offset budget in #9 should treat MOS mirror mismatch as
  a material, not incidental, contributor**, not an afterthought behind the
  amplifier-offset term.
- Avoid sizing a mirror device at size A (4 µm²) and 2 µA — the smallest,
  lowest-current combination measured here — where projected mismatch
  exceeds 6 % on the NFET and 7 % on the PFET; that combination should be
  reserved for non-critical bias-generation legs, not the core PTAT/CTAT
  mirror.
- If the design needs mismatch meaningfully below 1 %, this data implies
  going beyond size B (larger W·L than 16 µm²) rather than relying on
  current/Vov tuning alone — worth a follow-up sizing pass once #8's
  schematic fixes actual mirror ratios and node currents.

### Sizing extension at the core's actual mirror current (issue #26)

Testbench: `sim/mos-mirror-sizing-extended/testbench/tb_mos_mirror_sizing.sch`
— record `20260803-112036-e599e30`, full tt/ss/ff/sf/fs × −40/27/125 °C @
3.30 V matrix, 15/15 PASS.

Once #8's schematic (`design/bandgap_core.sch`, merged via PR #40) fixed the
core's actual mirror geometry and node current — `MPOUT`/`MPAMP` are both
PFET `W=8/L=2` (size B, 16 µm², `mult=2`), self-biased off `GDRV`, converging
on a single ~5.3 µA per-unit branch current (`I = dVBE/R1 ≈ 62.3 mV /
11.8 kΩ`, per the core schematic's own sizing comment) — this current sits
*below* the original sweep's 20 µA best case, so size B's real-world
mismatch at the core's actual bias point is worse than the 1.1–1.2 % figure
above. This experiment re-measures size B at the actual 5.3 µA current and
extends the size axis with three larger sizes at the same W/L = 4 aspect
ratio: C (W=12/L=3, 36 µm², 2.25×), D (W=16/L=4, 64 µm², 4×), E (W=20/L=5,
100 µm², 6.25×) — both NFET and PFET at each size, for parity with the
original experiment's structure (the core's own mirror devices are PFET
only; the NFET row is a like-for-like generalization of the same aspect
ratio, not a literal match to `error_amp.sch`'s placeholder `MN1`–`MN4`,
which use a different W/L — see the testbench header for the full caveat).

| Device | Size | Area | gm/Id (1/V), tt/27 °C | Projected σ(ΔId/Id), tt/27 °C | gm/Id (1/V), worst PVT corner | Projected σ(ΔId/Id), worst PVT corner |
|---|---|---|---|---|---|---|
| NFET | B | 16 µm² | 10.842 | 2.223 % | 13.504 (ff, −40 °C) | 2.768 % |
| NFET | C | 36 µm² | 10.936 | 1.495 % | 13.594 (ff, −40 °C) | 1.858 % |
| NFET | D | 64 µm² | 10.986 | 1.126 % | 13.639 (ff, −40 °C) | 1.398 % |
| NFET | E | 100 µm² | 10.866 | 0.891 % | 13.504 (ff, −40 °C) | 1.107 % |
| PFET | B | 16 µm² | 7.157 | 2.147 % | 8.399 (fs, −40 °C) | 2.520 % |
| PFET | C | 36 µm² | 7.212 | 1.442 % | 8.385 (fs, −40 °C) | 1.677 % |
| PFET | D | 64 µm² | 7.285 | 1.093 % | 8.441 (fs, −40 °C) | 1.266 % |
| PFET | E | 100 µm² | 7.205 | 0.865 % | 8.311 (fs, −40 °C) | **0.997 %** |

- **PFET** (the core's actual mirror devices, `MPOUT`/`MPAMP`) crosses below
  1 % projected mismatch only at **size E (100 µm², 6.25× size B)**, and only
  just: 0.865 % nominal (tt, 27 °C), **0.997 % at the worst PVT corner** (fs,
  −40 °C) — a thin margin, not a comfortable one. Size D (64 µm²) stays just
  above 1 % worst-case (1.266 %).
- **NFET** does not cross below 1 % projected mismatch at any size tested
  here, even at 100 µm² (0.891 % nominal but 1.107 % worst-case PVT) — an
  NFET-based mirror leg biased at this current would need to go larger
  still. As noted above, this design's actual mirror legs are PFET-only, so
  this row is informational rather than a resizing target.

**Updated recommendation for the core's actual PFET mirror legs**: reaching
meaningfully-below-1 % projected mismatch at the schematic's actual ~5.3 µA
branch current means sizing to **size E (W=20/L=5, 100 µm², 6.25× the
schematic's current W=8/L=2) or larger** — and even then the worst-case-PVT
margin is thin (0.997 %, essentially at the 1 % line). If #9's offset budget
needs real margin below 1 % (not just a nominal-corner pass), plan for an
even larger mirror device, or accept MOS mirror mismatch as a material
contributor near the 1 % line rather than a solved problem. This sharpens,
but does not contradict, the general recommendation above: the general
region (`Vov ≈ 0.10–0.30 V`, area ≥ size B) still applies as a floor, and
this section gives the specific size needed at the specific current the
core schematic actually uses.

**Area/layout check (issue #15's floorplan)**: `MPOUT`/`MPAMP` are each
`mult=2` at their current per-unit `W=8/L=2` (16 µm²) size in
`design/bandgap_core.sch`; resizing the unit device to size E raises
per-unit area 6.25× (16 µm² → 100 µm²; 200 µm² per `mult=2` mirror leg, up
from 32 µm² today). Against the < 0.05 mm² (50,000 µm²) floorplan budget
issue #15 is scoped to (still open as of this writing), that increase is a
small fraction of the total budget even doubled for a common-centroid
array's dummy/interdigitation overhead — flagged here so #15 does not have
to independently re-derive it, and not expected to be a layout blocker.

This does not edit or supersede the original `mos-matching-characterization`
record (`20260731-045825-a8c4147`) — that record's generic 2/5/20 µA sweep
remains valid, unedited evidence for the ratio-agnostic characterization it
was scoped to; this section adds a second, current-specific record for the
sizing question the schematic's actual bias point raises.

---

## 4. Substrate PNP pair **local mismatch** — σ(ΔVBE) by Monte Carlo (issue #31)

Testbench: `sim/pnp-mismatch/testbench/tb_pnp_mismatch.spice`, driven by
`sim/pnp-mismatch/run_pnp_mismatch.py` (record `20260731-232801-ab27f82`).
Two pairs — an identical pair (two `W0p68L0p68` units) and the area-ratioed
PTAT pair (`W0p68L0p68` / `W3p40L3p40`) — each at 1 µA and 10 µA, N = 300
Monte Carlo samples per temperature at the nominal process point.

**The sky130 mismatch switch, verified against the pinned PDK.** gf180mcu's
`sw_stat_mismatch` / `mis_is_pnp_*` convention does not exist here. sky130's
PNP subcircuits carry `MC_MM_SWITCH`-gated `AGAUSS()` terms on `is` and `bf`
(`libs.tech/combined/continuous/models_bjt.spice`), and `MC_MM_SWITCH` is
set by the *`.lib` section*: 0 in `tt/ss/ff/sf/fs`, 1 only in the `*_mm`
sections. The sigmas (`continuous/models_global.spice`) are **1.662 % on Is**
and **5.537 % on Bf** for the `W0p68L0p68` unit; the `W3p40L3p40` subcircuit
reuses the same coefficients scaled by 0.13 / 0.45, i.e. the 25× emitter
area's matching benefit is already inside the PDK model. The model also
divides by `sqrt(mult)`, so paralleling unit devices is an explicit,
model-supported lever.

Because a wrong-but-silent switch would produce a plausible-looking record,
the run carries an **MC-off control point** (same deck on the plain `tt`
section: every σ came back *exactly* 0) and a **second-seed point** (σ within
1 – 8 % of the first seed while the individual samples all moved). Measured
σ also lands 1.05 – 1.26× a first-principles prediction from the PDK's own
Is coefficient (V_T·σ_Is/Is per leg, added in quadrature), which is the
expected small excess from the Bf/Ise/Vaf and `xti` terms.

### σ(ΔVBE), 1 µA (10 µA within ±10 % of these — see the record for all rows)

| Pair | T (°C) | mean ΔVBE (mV) | 1 σ (mV) | 3 σ (mV) | worst of 300 (mV) |
|---|---|---|---|---|---|
| identical `W0p68L0p68` ×2 | −40 | −0.003 | 0.541 | 1.62 | 1.56 |
| identical `W0p68L0p68` ×2 | 27 | +0.015 | 0.648 | 1.94 | 1.91 |
| identical `W0p68L0p68` ×2 | 125 | +0.048 | 0.867 | 2.60 | 2.60 |
| ratioed `W0p68L0p68` / `W3p40L3p40` | −40 | +49.49 | 0.391 | 1.17 | 50.68 |
| ratioed `W0p68L0p68` / `W3p40L3p40` | 27 | +63.00 | 0.480 | 1.44 | 64.33 |
| ratioed `W0p68L0p68` / `W3p40L3p40` | 125 | +82.26 | 0.680 | 2.04 | 84.22 |

Two properties matter more than the absolute numbers:

- **σ(ΔVBE) is essentially bias-current independent** (0.480 mV at 1 µA vs
  0.472 mV at 10 µA, 27 °C). It is an `Is`-mismatch effect, not a
  current-density effect — you cannot bias your way out of it. The only
  levers are device area (`mult`, which the model divides by `sqrt(mult)`)
  and trim.
- **σ grows with temperature** (0.39 → 0.48 → 0.68 mV over −40 → 125 °C),
  roughly with V_T plus the `xti` mismatch term, so the hot corner sets the
  budget.

### Offset-budget implication for #9 (error amplifier)

Sizing a ~1.2 V reference from this pair at 1 µA/unit and 27 °C: the small
unit's VBE is 0.7426 V and the pair's ΔVBE is 63.0 mV (both emitter-driven,
this record; §1's superseding record independently measures 0.742539 V and
63.0 mV), so the PTAT gain a Kuijk/Brokaw-style core needs is
K = (1.2 − 0.7426)/0.0630 ≈ **7.3**. Every millivolt in series with ΔVBE is
amplified by that same K, which turns the numbers above into a hard budget:

| Term at 27 °C | value | referred to a 1.2 V output |
|---|---|---|
| σ(ΔVBE), PTAT pair | 0.480 mV | 3.5 mV = **0.29 %** (1 σ) |
| 3σ(ΔVBE), PTAT pair | 1.44 mV | 10.5 mV = **0.87 %** (3 σ) |
| 3σ(ΔVBE) at 125 °C | 2.04 mV | 14.8 mV = **1.24 %** (3 σ) |
| amplifier input offset, per 1 mV | 1.00 mV | 7.3 mV = 0.61 % |

Consequences #9 should carry as explicit line items:

1. **PNP-pair mismatch alone consumes essentially all of a ±1 % untrimmed
   budget at 3 σ** (0.87 % at 27 °C, 1.24 % at 125 °C) — before the
   amplifier's own offset and before the MOS mirror mismatch §3 already
   flagged as material (≈ 1.2 % current mismatch at size B / 20 µA). An
   untrimmed ±1 % output from single unit devices is **not reachable**; the
   design needs either trim or area.
2. **Area is the lever, and it is cheap in σ terms.** σ scales as
   1/√mult, so an 8× paralleled PNP array takes σ(ΔVBE) from 0.480 mV to
   0.170 mV (3 σ → 0.31 % of 1.2 V). `spec/topology-survey.md` already
   requires paralleled unit devices because sky130's PNP geometries are
   fixed; this gives that requirement a number to size against.
3. **The amplifier offset target follows from row 4 of the table.** To keep
   the amplifier from dominating the PNP term, its input-referred offset must
   sit at or below σ(ΔVBE) — i.e. **≲ 0.5 mV 1 σ against un-arrayed unit
   devices, and ≲ 0.2 mV if the PNPs are arrayed** to the 8× point above.
   Both are demanding for a plain 5 V MOS input pair given §3's Vth-mismatch
   coefficients (8.2 mV·µm N / 12.0 mV·µm P), which points at large input
   devices, chopping/auto-zeroing, or trim as a topology-level decision for
   #9 rather than a sizing detail.

### Cross-repo comparison (gf180-bandgap)

The sibling repo's equivalent record (`sim/device-pnp-mismatch/`,
`20260731-040850-187a336`, same N = 300 and same 1/10 µA biases) reports
σ(ΔVBE) ≈ **0.047 mV** for its identical pair at 27 °C. sky130's
**0.648 mV is ~14× looser** — not a modelling artifact of this harness but
the two PDKs' matching models: gf180mcu's PNP Is-mismatch coefficient works
out near 0.13 %, sky130's is 1.662 %. Any offset-budget intuition carried
over from the gf180 port is therefore optimistic by an order of magnitude
and must be re-derived here.

### Terminal-connection discrepancy vs §1 — RESOLVED (issue #35)

While building this deck the PNP terminal ordering was checked against the
PDK subcircuit definition (`.subckt sky130_fd_pr__pnp_05v5_W0p68L0p68 c b e`)
rather than assumed, and §1's then-current netlist snapshot turned out to
instantiate `XQS0 E_small_100n 0 0 sky130_fd_pr__pnp_05v5_W0p68L0p68` — the
driven node on pin 1 = **`c`**, so the collector was biased with the emitter
grounded and that experiment measured the base-collector junction, not VEB.
Reproduced exactly at tt / 27 °C / 1 µA:

| connection | V at the driven node, small unit | matches |
|---|---|---|
| collector-driven (§1's superseded netlist) | 0.545166 V | superseded record's `veb_small_1u` = 0.545166 V |
| emitter-driven (this section) | 0.742539 V | this record's `vr1a` mean, 0.742569 V |

**Issue #35 fixed §1's schematic and re-ran its full 15-point matrix**
(record `20260801-041501-48ac24d`, superseding `20260731-043353-a8c4147`).
§1's `veb_small_1u` at tt / 27 °C is now 0.742539 V, agreeing with this
section's independently written raw-SPICE deck to 30 µV — so the table above
is retained as a **cross-validation between two independent testbenches**,
not as an open discrepancy. §1's ideality table, current-density window and
dVBE figures have all been re-derived from the new record and are again the
authoritative numbers for PTAT-gain sizing; the root cause (the `pnp_05v5`
symbol's `pinnumber` attributes disagreeing with the order xschem actually
netlists) is documented in `tb_pnp_vbe.sch`'s header, and the experiment's
`veb_*` sanity window was tightened so a recurrence fails the harness at the
hot corners rather than passing silently.

---

## Cross-references

- Confirms/refines `spec/topology-survey.md`'s provisional `res_high_po`
  pick (§ "Poly resistors") — see recommendation above; refines its
  static-`Is`-ratio PTAT assumption for the two PNP unit devices (§1).
- Input to #8 (schematic entry) for device sizing and #9 (amplifier offset
  budget) — MOS mirror mismatch, the PNP-pair local mismatch of §4 and the
  corrected PNP dVBE figures above should all enter #9's budget as explicit
  terms. §4's "Offset-budget implication" subsection states the three line
  items in the form #9 can consume directly.
- §4 mirrors gf180-bandgap's `sim/device-pnp-mismatch/` so the two canary
  ports' mismatch figures are directly comparable; the divergences (`.json`
  twin, MC-off control point, second-seed point) are listed in the record.
  The terminal-connection divergence that record lists is resolved by issue
  #35 — §1 and §4 now agree to 30 µV on VEB at tt / 27 °C / 1 µA.
- Scope: 3.3 V primary only, per DR-001
  (`spec/decision-records/DR-001-supply-flavor-scope.md`); no 1.8 V-flavor
  device characterization performed.

## Follow-up issues suggested (not filed as part of this PR — flagging for triage)

1. ~~`res_xhigh_po` TC re-measurement.~~ **Resolved by issue #25** — see §2
   "Temperature coefficient" above and
   `sim/resistor-tc-single-length/records/20260731-073440-3dfe830.md`. A
   single-length testbench with bias/length/positive-control legs plus a
   raw-SPICE simulator-mechanism probe confirmed the flat measured TC is an
   ngspice/model-implementation limitation (temperature scaling not applied
   to voltage-dependent behavioral resistor elements), not a
   two-length-subtraction bias-point artifact. The model card's
   `tc1 = −1470 ppm/°C` remains authoritative for `res_xhigh_po` design use.
2. ~~MOS mirror sizing beyond size B.~~ **Resolved by issue #26** — see §3
   "Sizing extension at the core's actual mirror current" above. Record
   `20260803-112036-e599e30` extends the device-size axis to C/D/E (36/64/
   100 µm²) at the core's actual ~5.3 µA branch current; the PFET mirror
   legs (`MPOUT`/`MPAMP`) cross below 1 % projected mismatch only at size E,
   with a thin worst-case-PVT margin (0.997 %).
3. ~~Re-run `sim/pnp-characterization` with the emitter driven.~~ **Resolved
   by issue #35** — the schematic now drives the emitter, and record
   `20260801-041501-48ac24d` supersedes `20260731-043353-a8c4147` with the
   full 15-point matrix. §1 has been re-derived from it and §4's
   terminal-connection note is marked resolved above.
4. **Sweep the PNP `mult` axis.** §4 measures unit devices only; the PDK's
   `1/sqrt(mult)` term predicts the array benefit but the prediction is
   unmeasured here. Once #8 fixes the array size, one extra Monte Carlo
   point at that `mult` would confirm it.

## Evidence

- PNP: `sim/pnp-characterization/records/20260801-041501-48ac24d.md`
  (+ `.json` twin, netlist snapshot, 15 per-corner logs) — supersedes
  `20260731-043353-a8c4147.md`, which is retained (collector-driven; see §4)
- Resistors: `sim/resistor-flavor-characterization/records/20260731-044337-a8c4147.md`
  (+ `.json` twin, netlist snapshot, 21 per-corner logs)
- Resistor TC single-length re-check (issue #25):
  `sim/resistor-tc-single-length/records/20260731-073440-3dfe830.md`
  (+ `.json` twin, netlist snapshot, 21 per-corner logs)
- MOS: `sim/mos-matching-characterization/records/20260731-045825-a8c4147.md`
  (+ `.json` twin, netlist snapshot, 15 per-corner logs)
- MOS mirror sizing extension (issue #26):
  `sim/mos-mirror-sizing-extended/records/20260803-112036-e599e30.md`
  (+ `.json` twin, netlist snapshot, 15 per-corner logs)
- PNP pair local mismatch (issue #31):
  `sim/pnp-mismatch/records/20260731-232801-ab27f82.md`
  (+ `.json` twin, netlist snapshot, 5 per-point logs — 3 Monte Carlo
  temperatures at N = 300, one MC-off control, one second-seed point)
