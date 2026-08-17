# Block-level characterization report — `bandgap-core` (sky130)

**T1/bronze checklist item 8 artifact** (the gap #39 flagged 2026-08-04 and #175's
2026-08-15 re-read confirmed still open). This is the single, current, block-level
roll-up of items 3–7's evidence — one row per **ratified** spec parameter
([DR-005](../spec/decision-records/DR-005-ratify-target-spec.md), amended by
[DR-006](../spec/decision-records/DR-006-psrr-frequency-qualification.md),
[DR-007](../spec/decision-records/DR-007-mcc-area-budget.md),
[DR-008](../spec/decision-records/DR-008-psrr-post-layout-margin-proposal.md)) —
with target, measured value, binding corner, verdict, and the evidence record each
verdict rests on.

**Coverage-honesty rule (this repo's own, restated so it travels with the claim
below): a FAIL is reported as FAIL, with its number, not omitted or rounded toward
the target.** Two rows fail at every corner on the freshest evidence
(output accuracy, temp coefficient — tracked #178); the statistical (Monte Carlo)
evidence for the dominant accuracy term, while freshly re-run against the current
design this cycle, still shows the window failing at every non-cold temperature
(tracked #180); one row (Trim) has no evidence against the current ratified
design at all. All of that is stated plainly below, not summarized away.

> **Partially superseded by issue #178 (`n_r2` 50 -> 51 + the chained-array
> resistor model).** Rows **1a** (output accuracy, schematic), **1b** (output
> accuracy, extracted), **3a/3b** (temp coefficient) and **4** (line
> regulation) all rest on records this report cites that a later design change
> has since re-measured. Current numbers, at the same ratified bounds:
> schematic accuracy **PASS 45/45** (`vref` 1.18603-1.21780 V, binding `fs`),
> schematic TC **FAIL 45/45 at 142.4-159.0 ppm/degC** (binding `fs` — the
> measured untrimmed floor, not a ratio error), extracted accuracy **FAIL
> 15/15** by 8.5-9.4 mV on `vref_min` (a post-layout interconnect-resistance
> effect, quantified in `sim/output-voltage-tc-post-layout/README.md`),
> extracted TC 167.9-186.9 ppm/degC, and line regulation **PASS 45/45**
> (schematic) / **PASS 15/15** (extracted) — the 16/45 hot-corner FAILs this
> report records have cleared. Evidence:
> `sim/output-voltage-tc/records/20260817-015751-13476b7.md`,
> `sim/output-voltage-tc-post-layout/records/20260817-020357-13476b7.md`,
> `sim/line-regulation/records/20260817-021208-13476b7.md`,
> `sim/line-regulation-post-layout/records/20260817-022402-13476b7.md`.
> Regenerating the whole roll-up against the post-fix design is item 8's own
> follow-up (#181), not issue #178's scope; this pointer exists so no row
> below is read as current in the meantime.

## 0. Freshness / regeneration rule

- **Generated against**: commit `3ba0e47` (2026-08-16), the tip of `main` at the time
  this report was written. **Read every citation's own commit/record-id, not this
  header** — this report is a snapshot; a record it cites is authoritative for its own
  claim only as of that record's own `Repo state` field.
- **Freshest layout report cited throughout**: `layout/bandgap-core/reports/20260815-034022-001d1b7/`
  (routed, DRC-clean, `klt lvs`-clean, `mismatch_count: 0`; no layout regeneration has
  landed since).
- **This artifact is stale, not wrong, the moment any of the following changes**:
  a new `sim/output-voltage-tc(-post-layout)/`, `sim/monte-carlo-untrimmed/`,
  `sim/psrr-dc(-post-layout)/`, `sim/quiescent-current(-post-layout)/`,
  `sim/startup-*/` record is appended, a new `layout/bandgap-core/reports/<stamp>/`
  lands, or a spec/DR is ratified/amended. **Regeneration rule**: re-derive every row
  below from the *newest* record under each cited `sim/*/records/` and
  `layout/bandgap-core/reports/` directory (not the ones named here) before relying on
  this report; `sim/README.md`'s "Draft-graded vs. ratified-graded records" section is
  the authoritative way to tell which record is graded against which spec vintage —
  read the record's own `**Claim**` line, never infer from its date or this report's.
  Whoever regenerates this report should append a **new** file revision noting the
  commit/report-dir it was generated against (this file is a normal committed doc, not
  an append-only `sim/` record, but should still name its own freshness basis in its
  first commit and every subsequent one).
- **A pointer to this rule also lives in [`sim/README.md`](../sim/README.md)** (added by
  this same change) so a reader who starts there is routed here.

## 1. What `klt signoff` already produces, and what it does not

Per this issue's own instruction, this was evaluated **before** hand-rolling the table
below.

- **Envelope-aggregation mode (`klt signoff <files...>`) works and is used**: running it
  against the freshest layout report's own four `klt`-envelope JSON files —

  ```
  klt signoff layout/bandgap-core/reports/20260815-034022-001d1b7/{drc,met2-drc,lvs.combined,extract}.json
  ```

  returns `status: "pass"`, `check_count: 4`, `passed_count: 4`, `failed_count: 0`,
  `provenance_consistency.ok: true` — a machine-checked, cross-validated (same
  input-layout `content_hash` on every check) confirmation of DRC, the met2 DRC
  supplement, LVS, and extraction agreeing on one input. That result backs item 3/4's
  rows in Section 2 directly, instead of this report re-deriving pass/fail by hand.
- **Tier-verdict mode (`klt signoff --manifest`) does not work in this environment, for
  a real, generic (non-design-specific) reason**: the pinned `klt` build (`0.2.0`, `uv
  tool install`) cannot locate `docs/design-evidence-tiers.md` — the doc-parsing modes
  compute that path relative to the installed package's own site-packages location
  (`Path(__file__).resolve().parent.parent.parent / "docs" / "design-evidence-tiers.md"`),
  which only resolves for an in-place source checkout, not a packaged install; the wheel
  does not bundle `docs/` as package data, and there is no `--tiers-doc` override flag.
  Confirmed directly:

  ```
  $ echo '{"kind":"analog","block":"bandgap-core","evidence":{}}' | klt signoff --manifest - --format json
  {"schema_version": 1, "error": {"command": "signoff", "message": "could not read
  design-evidence-tiers doc at '.../lib/python3.12/docs/design-evidence-tiers.md': ..."}}
  ```

  This is a packaging gap in `klt` itself, not something fixable from this repo, and it
  is generic to any consumer installing `klt` the documented way — filed upstream per
  this repo's friction protocol, kept tool-scoped and design-agnostic:
  **[2AMLogic/klayout-tools#1050](https://github.com/2AMLogic/klayout-tools/issues/1050)**.
  Until it lands, items 5–7 (PVT vs. ratified spec, Monte Carlo, post-layout) are graded
  by hand below, from the same `sim/*/records/*.json` envelopes a fixed `--manifest`
  mode would eventually consume — but note those records use **this repo's own**
  corner-run/record schema (`record_id`/`matrix`/`corners`/…), not `klt`'s
  `schema_version`/`kind` envelope contract (`klt` has no `sim` verb of its own), so even
  a fixed `--manifest` mode would need a translation step for items 5–7 that items 3/4
  do not.

## 2. Per-ratified-spec-row scoreboard

Read against DR-005's eight rows (Output reference, Trim, Temp coefficient, PSRR,
Supply, Iq, Area, Startup), each amended where a later DR applies.

| # | Parameter | Target | Measured (binding corner) | Verdict | Evidence |
|---|---|---|---|---|---|
| 1a | Output reference — untrimmed, corner-matrix half (schematic) | 1.20 V ±2 % (1.176–1.224 V), −40…125 °C | `vref_27` 1.16513–1.16679 V; `vref_min` 1.12969–1.13218 V — below 1.176 V at **every** corner. Binding: **ff** (`vref_min` 1.12969 V, deepest floor) | **FAIL 45/45** | `sim/output-voltage-tc/records/20260816-084351-69a8867.md` |
| 1b | Output reference — untrimmed, corner-matrix half, post-layout (extracted) | same | `vref_27` 1.17966–1.18113 V; `vref_min` 1.15112–1.15366 V — below 1.176 V at every corner. Binding: **ss** (`vref_min` 1.15112 V) | **FAIL 15/15** | `sim/output-voltage-tc-post-layout/records/20260816-100445-6ea30d8.md` |
| 1c | Output reference — untrimmed, mismatch-MC half (3σ, N≥300, local mismatch, `tt_mm`) | The record's own per-point PASS/FAIL gate: ≥50 % of converged draws inside the ±2 % window — a **sanity floor**, per the record's own caveat, not itself the literal 3σ spec threshold (a true 3σ-centered pass implies far higher yield; the yield number itself is "the deliverable," for the spec owner to judge, not a hard-coded threshold) | Yield (of converged draws) inside [1.176, 1.224] V: **76.67 %** (−40 °C) / **5.00 %** (27 °C) / **0.00 %** (125 °C), N=300 each, MC-off control at 0 mV and second-seed check both pass. Binding: **125 °C** (0 % yield) | **FAIL** | `sim/monte-carlo-untrimmed/records/20260816-091855-69a8867.md` (fresh 2026-08-16 run against the current design and the ratified window — see §3 on what is and isn't still stale here) |
| 2 | Trim (1-point `res_high_po`, ≥±5 % range, ≤0.25 %/step) | monotonic-in-code, downward span ≥1.5×3σ MC spread, LSB ≤25 % of window half-width | Design ships `r_lseg_trim=0.5 µm` (`design/bandgap_core.sch:283`). The last full monotonic/span/LSB check's equivalent 0.5 µm ("revised") configuration **passes all three criteria** at the current `n_r1=7`/`n_r2=50` sizing — but that run predates DR-005's ratification (2026-08-11) **and** the #170 amplifier resize (2026-08-14); no trim-criteria evidence exists against the current ratified spec/design | **STALE — no current-design verdict** | `sim/trim-lsb-chained/records/20260806-052035-dea0ca5.md` (2026-08-06) |
| 3a | Temp coefficient (schematic) | < 50 ppm/°C (box method) | 250.10–268.39 ppm/°C at **every** corner. Binding: **fs** (268.39 ppm/°C, worst) | **FAIL 45/45** | `sim/output-voltage-tc/records/20260816-084351-69a8867.md` |
| 3b | Temp coefficient, post-layout | same | 190.997–208.88 ppm/°C at every corner. Binding: **fs** (208.88 ppm/°C, worst; best corner `sf` at 190.997 still fails) | **FAIL 15/15** | `sim/output-voltage-tc-post-layout/records/20260816-100445-6ea30d8.md` |
| 4a | PSRR (schematic) | > 60 dB DC–1 kHz (band-min, DR-006) | `psrr_band_min` 70.24–81.47 dB. Binding: **sf, −40 °C, 2.97 V** (70.24 dB, closest to the floor) | **PASS 45/45** | `sim/psrr-dc/records/20260815-020301-001d1b7.md` |
| 4b | PSRR, post-layout | same | `psrr_band_min` 72.31–93.74 dB. Binding: **sf, 125 °C, 2.97 V** (72.31 dB — 12.31 dB above the floor; DR-008's own ratification citation) | **PASS 45/45** | `sim/psrr-dc-post-layout/records/20260815-034139-001d1b7.md` |
| 4c | PSRR stretch (> 30 dB @ 1 MHz) | informational | `psrr_1m` 17.62–18.78 dB (schematic), 17.04–18.69 dB (post-layout) — **below** the stretch line at every corner | **FAIL (stretch, non-blocking)** | same two records |
| 5 | Supply — operability (3.3 V ±10 %) | operate 2.97–3.63 V | every corner-matrix bench in this table (rows 1a/1b/3a/3b/4a/4b/6a/6b/8a–8d) sweeps this full 2.97–3.63 V range without solver divergence | **PASS** | as cited per row |
| 5b | Supply — line-regulation shift (informational; no dedicated ratified line item yet, see `sim/line-regulation`'s own claim text) | shift must fit inside the ±2 % accuracy window (48 mV p-p) — necessary, not sufficient | 15/45 corners fail, **all at 125 °C**, because `vref_nom` (1.12969–1.13216 V) is already below the bench's derived 1.14 V floor — the **same root cause as row 1a/3a**, not an independent supply defect | **FAIL 15/45 (inherits row 1a/3a)** | `sim/line-regulation/records/20260816-085818-69a8867.md` |
| 5c | Supply — line regulation, post-layout | same | still graded against the **draft** ±1 % window — not yet re-pointed at the ratified bound; see §3. 1/15 FAIL, at `fs_125c_3.30v`, which is a known, documented DC-sweep solver convergence-basin artifact (issue #172, commit `67460c0`) reproduced byte-for-byte against this layout, not a circuit instability — disclosed here rather than silently excluded | **STALE** | `sim/line-regulation-post-layout/records/20260815-041348-001d1b7.md` |
| 5d | Supply stretch (1.8 V-core Banba variant) | — | not implemented; wave-1 scope explicitly defers it | **N/A / deferred** | [DR-001](../spec/decision-records/DR-001-supply-flavor-scope.md) |
| 6a | Iq (schematic) | < 50 µA | 24.1–39.0 µA | **PASS 45/45** | `sim/quiescent-current/records/20260816-085818-69a8867.md` |
| 6b | Iq, post-layout | same | 24.4–43.6 µA | **PASS 45/45** | `sim/quiescent-current-post-layout/records/20260815-035028-001d1b7.md` (claim text still cites "DRAFT" — pre-#177 re-point; the <50 µA numeric target is unchanged between draft and ratified so the verdict itself is not affected, see §3) |
| 6c | Iq stretch (< 20 µA) | informational | not met at any corner (24.1 µA best case) | **FAIL (stretch, non-blocking)** | same two records |
| 7 | Area | < 0.08 mm² (80,000 µm², DR-007) | composed bbox **66,293 µm²** (≈17 % margin under budget) | **PASS** | `layout/bandgap-core/reports/20260815-034022-001d1b7/record.md` |
| 8a | Startup — self-starting (no other stable state), schematic, core+injector | exactly one DC operating point over 0…VDD on GDRV | **45/45 corner-point checks PASS** (plus 2 corner-sensitivity checks, also PASS) | **PASS** | `sim/startup-stability/records/20260815-032111-001d1b7.md` |
| 8b | Startup — self-starting, post-layout, extracted core + schematic injector | same | **8/8 checks PASS** (subset — see the record's own subset reason) | **PASS** | `sim/startup-stability-post-layout/records/20260815-040144-001d1b7.md` |
| 8c | Startup — time < 1 ms, schematic, core+injector | `t_start` and cross-condition `vref` convergence spread bounded | **35/45 PASS**, 10 FAIL at `ff`/fast corners (the convergence-spread check exceeds its 1 mV bound; the raw `t_start_ms` figures are all well inside the 1 ms budget) | **FAIL 10/45** | `sim/startup-ramp/records/20260812-073050-7eb5be4.md` |
| 8d | Startup — time, post-layout | same, extracted core + schematic injector | **33/45 PASS**, 12 FAIL, same failure shape | **FAIL 12/45** | `sim/startup-ramp-post-layout/records/20260812-043245-7eb5be4.md` |
| 8e | Startup — core-as-composed (no injector) | informational (the injector is drawn only as a schematic block, `design/startup_injector.sch`, and has no layout yet, so the composed/routed cell in row 7's own report does not include it) | 45/45 and 45/45 FAIL — **expected**: the composed cell as merged ships no injector | **FAIL (expected, disclosed)** | `sim/startup-time/records/20260816-085818-69a8867.md`, `sim/startup-time-post-layout/records/20260812-034744-6767688.md` |

### Reading the "Startup" row as one ratified claim

DR-005's single "Startup: self-starting, < 1 ms" line is verified by **three** distinct
benches, each disclosing exactly what it does and doesn't cover in its own `**Claim**`
text (not a report-writing simplification — the benches say this themselves):
`startup-stability` (the no-other-stable-state half, **passes**),
`startup-ramp` (the < 1 ms half, **partially fails** — 10–12 of 45 corners at the
fastest process corner), and `startup-time` (the core exactly as composed today, with
**no** injector attached at all, which **fails everywhere by construction** because the
routed cell doesn't yet include one). Reporting only `startup-stability`'s PASS (as the
top-level README currently does in its maturity-ladder summary line) would round the
Startup row toward the target — this report does not do that; the row is **mixed**, not
a clean PASS, and the `startup-ramp` partial FAIL plus the injector-less `startup-time`
FAIL are both disclosed here rather than omitted. This report does not modify the
README; see §5.

## 3. Items 3–7 verification rollup, with freshness

| Item | Verdict | Freshness | Artifact(s) |
|---|---|---|---|
| 3. DRC | **PASS, disclosed gaps** | 2026-08-15, `layout/bandgap-core/reports/20260815-034022-001d1b7/` | `drc.json` (`violation_count: 0`, deck `sky130` content-hash `sha256:aa7aca65…`) + `met2-drc.json` (supplementary met2-min-area checker, `violation_count: 0`) — both fed into the `klt signoff` envelope-aggregation run in §1 |
| 4. LVS | **PASS, single-engine** | same report dir | `lvs.combined.json` (`mismatch_count: 0`, 11/11 nets, 16/16 devices, engine `klayout` only) — same `klt signoff` run |
| 5. Full PVT vs. ratified spec | **FAIL** | 2026-08-16 (`sim/output-voltage-tc(-post-layout)/records/20260816-*`) | rows 1a/1b/3a/3b above — 45/45 and 15/15 FAIL respectively, both representations |
| 6. Monte Carlo | **FAIL** (fresh, not stale — see below) | 2026-08-16, commit `69a8867` | `sim/monte-carlo-untrimmed/records/20260816-091855-69a8867.md` — re-run this cycle against the **current** design (post-#170 amp resize, post-DR-003 `n_r2=50`) and the **ratified** ±2 % window (issue #187/#177). This resolves the corner/window half of #180's staleness complaint; the yield collapse (row 1c) is a *measured* current-design result, not a stale one. **What is still stale**: the isolated amplifier-offset measurement `sim/error-amp-offset-mc/records/20260803-084950-e599e30.md` (2026-08-03, pre-#170) — `design/error-amp-offset-budget.md` §9 still substitutes an analytic ~0.688 mV estimate for it, not a fresh measurement, so the *contributor-breakdown* half of item 6 (which term dominates today) is unmeasured even though the *window/yield* half now is. Tracked #180. |
| 7. Post-layout | **PARTIAL** | 2026-08-15/16, layout report `20260815-034022-001d1b7` | Mechanism is current: `klt extract --parasitics` → `sim/bin/post_layout_common.py` re-runs every schematic-level bench same-day/next-day. Where the schematic row passes, the post-layout rerun passes (rows 4b/6b/8b); where it fails, post-layout inherits, not fixes (rows 1b/3b/8d). `klt pex` (the machine-checkable parasitic-delta grader `docs/cli/signoff.md` names as the only accepted automated evidence for this item) is still not implemented upstream ([klayout-tools Epic #709](https://github.com/2AMLogic/klayout-tools/issues/709)) — the extraction-based re-run above remains the manual substitute this repo actually has. **Not fully refreshed**: `sim/line-regulation-post-layout/`, `sim/quiescent-current-post-layout/` (claim text only — numeric target unaffected) and `sim/startup-time-post-layout/` still carry pre-#177 draft-graded claim text (see row 5c and `sim/README.md`'s own "still-unconverted benches" list). |

## 4. Known blind spots (disclosed, not fixed here)

Carried forward from items 3/4/7's own citations, plus what this rollup itself
surfaced:

- **DRC deck coverage gap.** `drc.json`'s own `layers_in_stream_without_rules` lists 8
  layers the curated sky130 deck does not check (`64/20`, `65/44`, `66/13`, `68/5`,
  `82/44`, `83/20`, `86/20`, `94/20`).
- **met2 deck gap.** The curated sky130 **DRC** deck lacked met2 rules until
  [klayout-tools#513](https://github.com/2AMLogic/klayout-tools/issues/513) (merged via
  #515) added width/spacing/enclosure; the met2 **min-area** rule (`m2.6`) is still
  outside the deck's rule vocabulary and is covered by this repo's own supplementary
  checker (`met2-drc.json`, `layout/bin/met2_drc.py`), not upstream `klt drc` alone.
- **Single-engine LVS.** `lvs.combined.json`'s `mismatch_count: 0` is one toolchain
  (`klayout`) agreeing with itself — the independent-second-engine cross-check
  [klayout-tools#343](https://github.com/2AMLogic/klayout-tools/issues/343) describes
  has not landed.
- **No `klt pex`.** The machine-checkable parasitic-delta post-layout grader named by
  `docs/cli/signoff.md` does not exist upstream yet
  ([klayout-tools Epic #709](https://github.com/2AMLogic/klayout-tools/issues/709));
  this repo's extraction-based re-simulation (`klt extract --parasitics` translated and
  re-run through every schematic-level bench) is the manual substitute.
- **`klt signoff --manifest`/`--fleet` unusable from a packaged install.** Confirmed and
  filed generically upstream:
  [2AMLogic/klayout-tools#1050](https://github.com/2AMLogic/klayout-tools/issues/1050)
  (§1 above). The envelope-aggregation mode (no `--manifest`) works and is used in §1/§3.
- **Trim-network evidence is stale against the current ratified design** (row 2) — the
  same class of gap #180 flags for Monte Carlo, found independently while assembling
  this report; no issue currently tracks a refresh of `sim/trim-lsb-chained/`, and this
  report does not open one (out of scope for a report-writing issue; noted here so the
  gap travels with the claim rather than needing rediscovery).
- **Three post-layout benches still carry pre-ratification claim text**
  (`sim/line-regulation-post-layout/`, `sim/quiescent-current-post-layout/`,
  `sim/startup-time-post-layout/`) — `sim/README.md`'s own "Draft-graded vs.
  ratified-graded records" section already discloses this; repeated here because it
  bears directly on rows 5c/6b/8e above.
- **Area figure drift across docs, not fixed here.** The top-level `README.md`,
  `layout/README.md`, and DR-007/DR-008 all cite a composed-bbox figure of
  **73,989 µm²**, measured against an earlier layout report
  (`layout/bandgap-core/reports/20260811-221633-a0ee5e7/`). The freshest layout report
  (`20260815-034022-001d1b7`, generated after the DR-003 `n_r2` 54→50 resize settled)
  measures **66,293 µm²** — smaller, and still comfortably within the DR-007 80,000 µm²
  budget either way, so no verdict changes. This report cites the fresher number (row 7)
  and flags the drift rather than editing those other files, which are outside this
  issue's scope.

## 5. What this report deliberately does not do

- **Does not modify** any spec row, decision record, `product/` file, or existing
  `sim/*/records/*` file (append-only, per `CLAUDE.md` and this issue's own
  constraints). Row values above are transcribed from existing records, not re-derived.
- **Does not fix** the currently-failing rows (#178) or re-run the stale statistical
  evidence (#180) — those are separate issues by design (see #175's decomposition,
  #176), and this report's job is to state the current verdicts honestly, not improve
  them.
- **Does not duplicate** device-level characterization. `design/device-characterization-summary.md`
  (654 lines: PNP/resistor/MOS local-matching, five experiment families, all PASS at the
  *device* level) stands as the device-level companion to this *block*-level report and
  is cited, not re-derived, here.
- **Does not record a tier grant.** `product/everyblock/grants.md` is the authoritative
  ledger and grants are the operator's call, per its own "How a grant gets recorded
  here" procedure — nothing here should be read as one.
