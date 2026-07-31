# Device Characterization Summary — sky130 Bandgap Core (Issue #4)

**Status**: characterization complete, full PVT matrices, all records PASS.
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
| Substrate PNP | `sim/pnp-characterization/` | `20260731-043353-a8c4147` | 15/15 (tt/ss/ff/sf/fs × −40/27/125 °C @ 3.30 V) — PASS |
| Poly resistors | `sim/resistor-flavor-characterization/` | `20260731-044337-a8c4147` | 21/21 (tt/ss/ff/sf/fs/ll/hh × −40/27/125 °C @ 3.30 V) — PASS |
| 5 V MOS mirror devices | `sim/mos-matching-characterization/` | `20260731-045825-a8c4147` | 15/15 (tt/ss/ff/sf/fs × −40/27/125 °C @ 3.30 V) — PASS |

All three testbenches bias their DUTs with ideal current sources referenced
to ground only (no supply-referenced terminal), so the ±10 % supply axis is
intentionally fixed at nominal 3.30 V in each `experiment.json` — documented
per-experiment as the reason a supply sweep would not change any result.

---

## 1. Substrate PNP (`sky130_fd_pr__pnp_05v5_W0p68L0p68` / `_W3p40L3p40`)

Testbench: `sim/pnp-characterization/testbench/tb_pnp_vbe.sch` — both
emitter-size variants diode-connected (B=C=0), each swept across 7
collector currents (100 nA – 100 µA, half-decade steps) at every PVT point.

### Ideality factor (n), extracted from consecutive half-decade VEB steps

n = ΔVEB / (V_T · ln(ΔIc)), evaluated at the `tt` corner (representative —
see "process-corner sensitivity" below):

| Ic step | n, small (`W0p68L0p68`, area 0.4624 µm²) | n, large (`W3p40L3p40`, area 11.56 µm²) |
|---|---|---|
| 100 nA → 316 nA | 1.01 | 1.00 |
| 316 nA → 1 µA | 1.02 | 1.00 |
| 1 µA → 3.16 µA | 1.06 | 1.01 |
| 3.16 µA → 10 µA | 1.20 | 1.04 |
| 10 µA → 31.6 µA | 1.62 | 1.12 |
| 31.6 µA → 100 µA | 2.95 | 1.35 |

(values shown at 27 °C; −40/125 °C tell the same qualitative story — see
the full record for all three temperatures)

**Usable current-density window**: ideality stays ≲ 1.1 (near-ideal) up to
~3 µA on the small unit device (current density J = Ic/area ≈ 6.8 µA/µm²)
and up to ~10 µA on the large unit (J ≈ 0.87 µA/µm²). Beyond that, series
resistance / high-injection roll-off sets in and worsens quickly — n
exceeds 1.6 by 31.6 µA on the small device. Because rolloff tracks current
density rather than absolute current, the large device (25× area) buys
roughly the same ideality headroom at ~10× higher absolute current, not the
full 25× — the two unit devices are not simple current-density clones of
each other.

**Recommendation for sizing**: keep each *unit* PNP's collector current at
or below ~3 µA (small device) / ~10 µA (large device) if the design wants
n ≲ 1.1 everywhere in the −40…125 °C range. This comfortably fits inside
the < 50 µA total Iq budget for a handful of unit devices, but rules out
running a single small-unit device at 20–50 µA if ideality matters at the
edge of the temperature range — favor the large unit or a paralleled array
of small units for any leg carrying tens-of-µA current density.

### Process-corner sensitivity

VEB is effectively **insensitive to process corner** at fixed temperature:
across tt/ss/ff/sf/fs at 27 °C and 1 µA, VEB varies by < 20 µV (5th
significant figure) — e.g. `veb_small_1u` = 0.545166–0.545167 V across all
five corners. Temperature is the dominant — effectively only — sensitivity
axis for this device family in this PDK. (Confirmed in the full record;
this matches `sim/pdk.json`'s note that `tt/ss/ff/sf/fs` corners gate
BJT `Is`/`Bf`/`Nf` only weakly relative to the MOSFET parameters they're
named for.)

### dVBE (PTAT term) between the two emitter-size variants — a correction to the topology survey

`spec/topology-survey.md` computed the survey's PTAT-gain expectations from
the two devices' static model-card `Is` values (`Is_small ≈ 1.51e-18 A`,
`Is_large ≈ 7.12e-18 A`, ratio ≈ 4.72). **The simulated dVBE at matched
current implies a materially smaller — and temperature-dependent — Is
ratio**:

| Corner | dVBE @ 100 nA (matched Ic) | Implied `Is_large/Is_small` |
|---|---|---|
| tt, −40 °C | 5.45 mV | 1.31 |
| tt, 27 °C | 14.40 mV | 1.75 |
| tt, 125 °C | 37.52 mV | 2.98 |

This is a genuine, measured correction, not a restatement of the datasheet
ratio: a Kuijk-style core's `K·V_T·ln(N)` PTAT term, sized against the
naive static-`Is`-ratio assumption, will get **less** PTAT voltage out of
these two fixed unit devices than that assumption implies, and the shortfall
is itself temperature-dependent (worse at cold, better at hot). Any
schematic-entry sizing (#8) or offset-budget analysis (#9) that leans on a
`ln(N)` PTAT gain from this device pair should use the measured dVBE
figures above (or re-derive from a matched-current sweep at its actual bias
point), not the raw model-card `Is` ratio. Building a larger effective
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

---

## Cross-references

- Confirms/refines `spec/topology-survey.md`'s provisional `res_high_po`
  pick (§ "Poly resistors") — see recommendation above; refines its
  static-`Is`-ratio PTAT assumption for the two PNP unit devices (§1).
- Input to #8 (schematic entry) for device sizing and #9 (amplifier offset
  budget) — MOS mirror mismatch and the corrected PNP dVBE figures above
  should both enter #9's budget as explicit terms.
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
2. **MOS mirror sizing beyond size B.** §3's mismatch projection suggests
   the < 1 % mismatch region may require device areas larger than the 16
   µm² (size B) evaluated here; once #8 fixes actual mirror ratios, a sizing
   sweep extending this experiment's device-size axis would sharpen the
   recommendation.

## Evidence

- PNP: `sim/pnp-characterization/records/20260731-043353-a8c4147.md`
  (+ `.json` twin, netlist snapshot, 15 per-corner logs)
- Resistors: `sim/resistor-flavor-characterization/records/20260731-044337-a8c4147.md`
  (+ `.json` twin, netlist snapshot, 21 per-corner logs)
- Resistor TC single-length re-check (issue #25):
  `sim/resistor-tc-single-length/records/20260731-073440-3dfe830.md`
  (+ `.json` twin, netlist snapshot, 21 per-corner logs)
- MOS: `sim/mos-matching-characterization/records/20260731-045825-a8c4147.md`
  (+ `.json` twin, netlist snapshot, 15 per-corner logs)
