# Error-Amplifier Offset / Mismatch Budget — sky130 Bandgap Core (Issue #9)

**Status**: budget complete and measured end to end. Three of the four
acceptance criteria the amplifier itself owns are met (loop stability, PSRR,
Iq); the fourth — the amplifier's input-referred offset allocation — is
**not met, and this document's central finding is that it cannot be met by
sizing alone.** That finding is flagged back to #3/#8 in §6 rather than
papered over by quietly relaxing the target, per `CLAUDE.md`.

**Headline**: with the amplifier in `design/error_amp.sch` and the core in
`design/bandgap_core.sch`, the untrimmed reference's **local-mismatch spread
alone is 1.41 % (3 σ) at 27 °C and 1.54 % at 125 °C** of a 1.2 V output —
already outside the draft ±1 % untrimmed line before any global process
shift or temperature curvature is added. **74–90 % of that variance is the
amplifier's own random offset**, multiplied into the output by the Kuijk
core's measured offset gain of 9.65.

Scope: wave 1, 3.3 V primary only, per DR-001
(`spec/decision-records/DR-001-supply-flavor-scope.md`). The amplifier uses
only `sky130_fd_pr__nfet_g5v0d10v5` / `pfet_g5v0d10v5` — no 1.8 V core
devices anywhere.

This document does **not** ratify a spec value (that is #1's job) and does
**not** make the ±1 % untrimmed output-accuracy claim over PVT (that is
#11's experiment — it needs the global process and temperature axes this
budget deliberately separates out). It allocates a budget, measures every
term in it, and checks that the terms add up to the measured total.

## Evidence backing every number below

| What | Experiment | Record ID | Points run |
|---|---|---|---|
| Loop stability, offset gain, PSRR, Iq split, operating point | `sim/error-amp-loop/` | `20260803-085320-e599e30` (supersedes `20260803-083344-e599e30`) | **45/45** full PVT (tt/ss/ff/sf/fs × −40/27/125 °C × 2.97/3.30/3.63 V) — PASS |
| σ(VOS), σ(ΔVBE) at 8×, σ(V_EB), σ(R2/R1), σ(VOUT), and their closure | `sim/error-amp-offset-mc/` | `20260803-084950-e599e30` | 3 Monte Carlo points (`tt_mm` × −40/27/125 °C, N = 300 each) + 1 MC-off control + 1 second-seed point — PASS |
| Device coefficients consumed (A_VT, res_high_po mismatch, unit-PNP σ(ΔVBE)) | `design/device-characterization-summary.md` §§3–4 | `20260731-045825-a8c4147`, `20260731-232801-ab27f82` | — |

Two records exist for `sim/error-amp-loop/` because the second re-runs the
same 45 points with three extra operating-point measurements added
(`av_amp`, `rout_amp`, `cc_mcc`); it supersedes the first per
`sim/README.md`'s append-only rule. The first is kept because
`sim/error-amp-offset-mc/`'s record read its offset gain (identical value,
9.652797 V/V).

---

## 1. Where the offset goes: the Kuijk offset gain, derived and then measured

The core forces its two sense nodes together through the amplifier. With
`VOS` the amplifier's input-referred offset, `ΔVBE = V_BE1 − V_BE2`,
`K = R2/R1`, and both R2 legs matched:

```
  V_A  = V_BE1                     V_B = V_BE2 + I_B·R1        V_B − V_A = VOS
  VOUT − V_A = I_A·R2              VOUT − V_B = I_B·R2

  ⇒ VOS = (I_A − I_B)·R2  and  I_B·R1 = ΔVBE + VOS
  ⇒ VOUT = V_BE1 + K·ΔVBE + (K + 1)·VOS
```

So the **idealized** offset gain is `1 + K`. For this core's geometry the
`res_high_po` segment model `R(L) = 380 + 325·L` Ω gives
`R1 = 11.755 kΩ` (L = 35 µm) and `R2 = 88.130 kΩ` (L = 270 µm), so

```
  K = R2/R1 = 7.497        (not 54/7 = 7.714 — the 380 Ω end resistance matters)
  1 + K     = 8.50
```

**Measured**: `offset_gain` = **9.653 V/V** at tt/27 °C/3.30 V, ranging
**9.570 … 9.734** over all 45 PVT corners
(`sim/error-amp-loop/`, measured by injecting a 1 V AC excitation in series
with the amplifier's `VINN` pin and reading |v(VOUT)|).

That is 14 % above the idealized figure, and the reason is that the algebra
above treats `V_BE1` and `ΔVBE` as stiff against the branch-current change
the offset causes. They are not: each 8× PNP array carries ~5.3 µA, so its
small-signal emitter resistance is `r_e = V_T/I ≈ 25.85 mV / 5.31 µA
≈ 4.88 kΩ`, which is 41 % of R1. Redoing the perturbation with `r_e` in
place gives

```
  dVOUT/dVOS = (R2 + r_e)·[ (1 + r_e/R2)/R1 + 1/R2 ] = 9.41
```

within 3 % of the measured 9.65 (the remainder is ideality `n ≳ 1`, which
raises `r_e`, plus the finite loop gain). **The budget below uses the
measured 9.65, not either algebraic figure** — that is the whole reason it
is measured rather than assumed.

---

## 2. The four terms, each measured

All from `sim/error-amp-offset-mc/` record `20260803-084950-e599e30`,
N = 300 Monte Carlo draws per temperature at the nominal process point with
the PDK's local-mismatch switch on (`tt_mm`), 1 σ unless stated. "Output
referred" applies the gain each term reaches VOUT through: the amplifier's
offset through the measured 9.653, ΔVBE and the resistor-ratio error through
K = 7.497, and the CTAT V_EB at unity.

### 27 °C

| Term | measured 1 σ | output-referred 1 σ | output-referred 3 σ | share of variance |
|---|---|---|---|---|
| Amplifier VOS | 0.5246 mV | 5.064 mV | **1.266 %** | 83.4 % |
| PNP ΔVBE, 8× arrays | 0.1626 mV | 1.219 mV | 0.305 % | 4.8 % |
| PNP V_EB (CTAT), 8× array | 0.1600 mV | 0.160 mV | 0.040 % | 0.1 % |
| `res_high_po` R2/R1 ratio | 0.4062 % | 1.900 mV | 0.475 % | 11.7 % |
| **RSS of the four** | — | **5.547 mV** | **1.387 %** | — |
| **Independently measured σ(VOUT)** | — | **5.648 mV** | **1.412 %** | — |

### All three temperatures

| T (°C) | amp VOS | PNP ΔVBE | PNP V_EB | resistor ratio | RSS | **measured σ(VOUT)** |
|---|---|---|---|---|---|---|
| −40 | 1.361 % | 0.253 % | 0.033 % | 0.375 % | 1.434 % | **1.434 %** |
| 27 | 1.266 % | 0.305 % | 0.040 % | 0.475 % | 1.387 % | **1.412 %** |
| 125 | 1.247 % | 0.422 % | 0.054 % | 0.614 % | 1.454 % | **1.544 %** |

(all output-referred, 3 σ, as a fraction of a 1.2 V reference)

**The last two columns are the point of the experiment.** The budget is not
an assertion about how errors combine — the same run measures σ(VOUT)
directly on the same draws, and the RSS of the four terms reproduces it to
within 0.0 % / 1.8 % / 6.2 % at the three temperatures (the record's
`budget_closure` check). A budget that did not close would mean a term was
missing or double-counted; this one closes.

### Where each coefficient came from, and what was re-measured

- **Amplifier VOS** — measured here, not projected. §3 of
  `design/device-characterization-summary.md` warned that MOS mirror
  mismatch had to be treated as *material, not incidental*; that warning is
  vindicated (see §4 below: the NMOS load/mirror devices contribute as much
  input-referred offset as the input pair itself).
- **PNP ΔVBE at 8×** — §4 measured σ(ΔVBE) on **unit** devices and
  *predicted* the 8× case by the model's 1/√mult term. The core ships
  `n_pnp_ctat = n_pnp_ptat = 8`, so this experiment measures the arrayed
  pair directly at the core's own 5.3 µA branch current. It also carries the
  un-arrayed 1 µA pair as a cross-harness anchor, which reproduces §4's
  published numbers (**62.96 mV mean vs 63.0 mV published; 0.497 mV σ vs
  0.480 mV**), and confirms the array scaling
  (σ(8×)/σ(1×) = 0.327 vs 1/√8 = 0.354).
- **Resistor ratio** — the PDK's `sw_mm_sky130_fd_pr__res_high_po`
  coefficient, 2.06 %/√(W·L), applies to the resistor **body** sheet only
  (`models_resistors.spice`, `rbody_model`); on L = 270 µm and L = 35 µm it
  predicts 0.370 % for the ratio. Measured: **0.406 %**. The model also
  carries a separate, much larger head-resistance term
  (`sw_mm_..._res_generic_po_head` = 6.3 %, divided by √(w·mult) rather than
  √(w·l·mult)) and works in effective rather than drawn dimensions, so the
  two are not expected to agree exactly — per leg the measurement comes out
  above the body-only figure on the long resistor (0.155 % vs 0.125 %) and
  below it on the short one (0.306 % vs 0.337 %). **The budget uses the
  measured ratio spread**, and the record's
  `res_ratio_vs_pdk_coefficient` check is a sanity band, not an identity.
- **A_VT for the analytic cross-check in §4** — §3's PDK coefficients:
  8.2 mV·µm (`nfet_g5v0d10v5`), 12.0 mV·µm (`pfet_g5v0d10v5`).

---

## 3. The allocation, and the one line that misses it

The draft spec's untrimmed accuracy line is ±1 % — read here as a 3 σ
figure on a 1.2 V output, i.e. **12.0 mV (3 σ)**. Three of the four terms
are set by the core (#8) and by the PDK, not by this issue: the PNP array
size, the CTAT device and the resistor lengths are all fixed by
`design/bandgap_core.sch`. So the honest way to state the amplifier's
allocation is *whatever is left after the other three*:

| T (°C) | fixed terms (PNP + V_EB + resistor, 3 σ) | **allocation left for amp VOS (3 σ)** | allowed σ(VOS) | **measured σ(VOS)** | shortfall |
|---|---|---|---|---|---|
| −40 | 0.454 % | 0.891 % | 0.369 mV | 0.564 mV | **1.53 ×** |
| 27 | 0.566 % | 0.825 % | 0.342 mV | 0.525 mV | **1.54 ×** |
| 125 | 0.747 % | 0.664 % | 0.275 mV | 0.517 mV | **1.88 ×** |

**125 °C is the binding corner** — the PNP and resistor terms both grow with
temperature (ΔVBE is PTAT, so its absolute σ scales with T, and the resistor
term scales with the PTAT voltage it multiplies), squeezing the amplifier's
allocation exactly where the amplifier's own offset does not shrink.

**Acceptance criterion "amp meets its VOS allocation": NOT MET.**
Everything else the amplifier owns is met — see §5.

---

## 4. The amplifier that was built, and why it is not undersized

`design/error_amp.sch` is a single-stage current-mirror OTA: PMOS input pair
(forced by the ~0.73 V input common mode — measured `vcm_in` 0.559 … 0.841 V
over PVT, far below what an NMOS pair on 5 V thick-oxide devices can use),
NMOS diode loads, and NMOS + PMOS mirrors that fold the second branch into
`AOUT` so the output can swing to a PMOS-gate level near VDD. It sits behind
the fixed pin list `error_amp VINP VINN AOUT ITAIL VDD VSS` that
`design/bandgap_core.sch` instantiates as `XAMP VB VA GDRV TAIL VDD VSS`;
the interface and `design/error_amp.sym` are unchanged.

Input-referred random offset of this stage, to first order:

```
  σ²(VOS) = 2·σ²(Vth,in)                         input pair
          + 4·(gm_nload/gm_in)²·σ²(Vth,n)        MN1..MN4
          + 2·(gm_pmirr/gm_in)²·σ²(Vth,p)        MP3/MP4
                       with  σ(Vth) = A_VT/√(W·L·mult)
```

With the shipped geometry and the **measured** gm ratios at tt/27 °C
(`gm_nload/gm_in = 0.464`, `gm_pmirr/gm_in = 0.348`):

| Group | W × L × mult | area | σ(Vth) | contribution to σ(VOS) |
|---|---|---|---|---|
| MP1/MP2 input pair | 20 × 10 × 16 | 3200 µm² each | 0.212 mV | 0.300 mV |
| MN1…MN4 loads/mirrors | 8 × 20 × 4 | 640 µm² each | 0.324 mV | 0.301 mV |
| MP3/MP4 PMOS mirror | 6 × 20 × 8 | 960 µm² each | 0.387 mV | 0.190 mV |
| **total (RSS)** | | **10 880 µm²** | | **0.466 mV predicted** |

Measured: **0.525 mV** — 13 % above the first-order formula, which is the
expected direction (the formula carries only threshold mismatch; the PDK
models also draw on current-factor and mobility terms).

Three levers were used and all three are at a sensible stop:

1. **Area.** 10 880 µm² of offset-contributing transistor, an order of
   magnitude more than the whole core's device area.
2. **gm ratios below 1.** The input pair runs at high gm/I_D (aggregate
   W/L = 32, i.e. 16 × 20 µm / 10 µm) while the loads and mirror run
   deliberately low (aggregate W/L = 1.6 and 2.4),
   so their Vth mismatch is divided down by 0.46 and 0.35 when referred to
   the input. Note the consequence, which is §3's warning made concrete:
   **the four NMOS loads contribute as much offset as the input pair itself**
   (0.301 vs 0.300 mV). Pushing that ratio lower means even lower gm on the
   loads, which costs output swing headroom.
3. **Long channels** (L = 10–20 µm, inside the model's 8–20.2 µm top bin),
   which also buy the output resistance the loop gain and PSRR need:
   measured `rout_amp` = 10.8–12.0 MΩ, `av_amp` = 834–942 (58.4–59.5 dB).

**Why more area is not the answer.** σ scales as 1/√area, so closing the
1.88 × shortfall at 125 °C needs **3.5 × the area — about 38 000 µm² of
offset-contributing transistor** (plus a proportionally larger compensation
device, since the added area is added capacitance). And the reward for that
is a total of exactly 1.00 % at 3 σ: **zero margin**, against a σ that is
itself only known to ±4.1 % at N = 300, and before any global process or
curvature term. This is the quantitative form of the finding below: the
budget does not close by sizing.

---

## 5. The acceptance criteria that *are* met

All from `sim/error-amp-loop/` record `20260803-085320-e599e30`, **45/45 PVT
corners PASS**, worst case over the whole matrix:

| Criterion | Limit | Worst measured | Corner | Verdict |
|---|---|---|---|---|
| Loop phase margin | ≥ 45° | **61.1°** | fs/125 °C/3.63 V | PASS |
| Loop gain margin | ≥ 6 dB | **10.8 dB** | fs/125 °C/2.97 V | PASS |
| DC loop gain | ≥ 35 dB | **49.9 dB** | ss/−40 °C/2.97 V | PASS |
| PSRR @ DC | > 60 dB | **77.7 dB** | sf/125 °C/2.97 V | PASS |
| Iq total (amp + core) | < 50 µA | **39.1 µA** | sf/125 °C/3.63 V | PASS |
| Systematic (mismatch-off) VOS | < 1 mV | **0.185 mV** | ff/125 °C/2.97 V | PASS |

Supporting numbers worth carrying forward:

- **Unity-gain frequency** 207–231 kHz; −180° crossing 715–805 kHz.
- **Compensation**: `MCC`, a thick-oxide PMOS wired as a capacitor
  (`cap_mim_m3_*` is deliberately not used — this issue restricts the cell to
  the two MOS primitives). Its gate capacitance is measured, not computed
  from Cox·W·L: **21.0–21.6 pF** across the matrix, and the runner asserts a
  floor on it at every corner, which is what would fail loudly if the device
  ever fell out of inversion.
- **Iq split**: the amplifier draws **15.5–25.9 µA** of the cell's
  24.2–39.1 µA — roughly two thirds, not the half an even split would
  assume. Under the < 50 µA line that leaves **≈ 11 µA of headroom at the
  hottest corner** for anything added later (this is the number a chopping or
  auto-zero scheme has to fit inside, and it is the reason §6 does not treat
  extra bias current as free).
- **Systematic vs random.** The systematic offset above is ~0.19 mV worst
  case — a third of the random σ, and it is what the topology's symmetry
  buys (both input-pair drains sit at diode-connected NMOS, so the pair sees
  no Vds imbalance; MN3/MN4 both sit at the AOUT/PN level so their
  channel-length-modulation errors cancel at the summing node). **Improving
  it further would not move this budget** — the budget's term is the random
  one.

---

## 6. Finding: ±1 % untrimmed is not reachable with this core and a plain amplifier

This is the finding the issue's acceptance criteria explicitly require to be
documented rather than engineered around silently.

**What was found.** The local-mismatch spread of the untrimmed reference is
1.41 % (3 σ) at 27 °C and 1.54 % at 125 °C, against a ±1 % target — and
that is mismatch **only**, at one process point, with no global process
shift of V_BE or of the resistor sheet and no temperature curvature. The
amplifier's own random offset is 77–81 % of that variance, amplified by the
core's measured 9.65 offset gain. Meeting the allocation by sizing needs
3.5 × the amplifier's offset-contributing area for zero margin (§4).

**What this does and does not say about topology.**
`spec/topology-survey.md` names Brokaw as the fallback "for the case where
the offset-budget analysis finds Kuijk's R2/R1 divider gain amplifies amp
offset more than the ±1 % target tolerates." That condition is met on the
Kuijk side: the offset gain is measured at 9.65 and it is what makes the
amplifier term dominate. **But this document does not conclude that Brokaw
fixes it** — a Brokaw core multiplies its amplifier's offset into the output
through its own resistor ratio by a comparable factor, and nobody in this
repo has measured that. Answering it needs a Brokaw testbench and a matching
Monte Carlo record, which is a topology decision and belongs to #3/#8, not
to this issue. **Flagged, not decided.**

**Recommended paths, in the order they should be evaluated:**

1. **Chopping or auto-zeroing the amplifier (most likely the answer).** It
   attacks the term that actually dominates. Remove the amplifier's static
   offset and the remaining three measured terms RSS to **0.57 % (3 σ) at
   27 °C and 0.75 % at 125 °C** — inside ±1 % with real margin, without
   touching the core or growing the amplifier. Cost, from measurements here:
   it must fit in ≈ 11 µA at the hot corner (§5), it adds chopping ripple at
   the switching frequency into a loop whose unity gain is ~220 kHz, and it
   adds switches to a cell that currently has none. Not free, but the only
   option that changes the dominant term by an order of magnitude.
2. **Trim (#13).** A trim network cancels the *static* part of all three
   mismatch terms at once, leaving trim resolution plus drift. This is
   already a planned issue; this budget is the quantitative case for it —
   and it says the trim range has to cover **at least** ±1.5 % at 3 σ, not
   ±1 %: 1.54 % is the mismatch-only figure, and #11's global process and
   curvature terms come on top of it.
3. **A larger PNP array and/or longer resistors.** Cheap in design effort,
   and it moves the second- and third-largest terms (PNP 0.42 %, resistor
   0.61 % at 125 °C). It cannot close the gap alone: even driving both to
   zero leaves the amplifier's 1.25 % (3 σ).
4. **Brute-force amplifier area.** 3.5 × for zero margin — documented in §4
   for completeness and **not recommended**.
5. **Re-examining the ±1 % untrimmed line itself.** This is a spec question
   (#1), not a design one. Agents do not relax the ratified spec to make
   results pass, so it is listed only to record that this budget is the
   evidence such a discussion would need.

---

## 7. Cross-references

- **#3 / #8 (topology, core)** — the Kuijk offset gain is measured at 9.65
  and dominates the budget; the survey's Brokaw-fallback trigger condition
  is met, but whether Brokaw actually helps is unmeasured. See §6.
- **#10 (startup)** — `bandgap_core` is bistable and has no startup circuit.
  The Monte Carlo runner classifies every draw and refuses to fold a
  non-operating one into the statistics; the committed record has 0 excluded
  draws, but only because the testbench seeds the mirror gate at 2.0 V. With
  a 2.2 V seed, 12 of 40 draws at −40 °C converged to the other branch
  instead (see the testbench header). That is a solver-path observation, not
  a startup-yield prediction — quantifying startup is a transient and is
  #10's job — but it is one more reason #10 is not optional.
- **#11 (full-PVT accuracy)** — this budget is mismatch only at one process
  point. #11 adds the global process and temperature axes, and should expect
  a *worse* total than the 1.41 %/1.54 % here.
- **#13 (trim)** — §6 path 2: the trim range needs to cover at least
  ±1.5 % at 3 σ (mismatch alone), before #11's global terms.
- **#15 (floorplan)** — the amplifier's matching depends on common-centroid
  layout of the input pair and of the NMOS load/mirror quad, and those two
  groups contribute equally (§4). The 10 880 µm² of offset-contributing
  transistor plus 9 600 µm² of MOS capacitor is the area #15 has to place.
- **`design/device-characterization-summary.md`** §3 (A_VT, res_high_po
  mismatch) and §4 (unit-PNP σ(ΔVBE)) are the coefficients this budget
  consumes; §4's "Offset-budget implication for #9" predicted the arrayed
  PNP term, and this document replaces that prediction with a measurement.

## 8. Evidence

| Artifact | Path |
|---|---|
| Amplifier schematic / symbol | `design/error_amp.sch`, `design/error_amp.sym` |
| Loop testbench (stability, offset gain, PSRR, Iq) | `sim/error-amp-loop/testbench/tb_error_amp_loop.sch` |
| Loop manifest | `sim/error-amp-loop/experiment.json` |
| Loop record (45/45 PVT, PASS) | `sim/error-amp-loop/records/20260803-085320-e599e30.md` |
| Monte Carlo testbench | `sim/error-amp-offset-mc/testbench/tb_amp_offset_mc.sch` |
| Monte Carlo runner | `sim/error-amp-offset-mc/run_amp_offset_mc.py` |
| Monte Carlo record (N = 300 × 3 T + control + second seed, PASS) | `sim/error-amp-offset-mc/records/20260803-084950-e599e30.md` |

Both experiments carry falsification controls, because a mismatch or
loop-gain harness that silently measured nothing would otherwise produce
plausible-looking numbers:

- the loop testbench's `vref_delta` / `iq_delta` fail if its flattened
  replica of `bandgap_core` ever drifts from the real cell;
- the Monte Carlo's MC-off control point requires **every** σ to come back
  exactly 0 on the plain `tt` section, its second-seed point requires σ to
  be stable while the samples change, and its 1 µA un-arrayed PNP pair has
  to reproduce a number measured by a different testbench on a different run.
