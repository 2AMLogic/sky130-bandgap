# DR-004: Spec-review verdict for target-spec ratification — ratify-with-amendments

- **Status**: proposed (input to spec ratification, see #1). **This record does not itself
  ratify the spec.** Per this issue's 2026-08-09 operator ruling, the `spec-review` skill
  (klayout-tools) is currently forbidden from marking a spec ratified
  (klayout-tools#654 requests the contract change); the deliverable here is the verdict and
  its proposed amendments, staged for the operator to accept, amend, or reject by comment on
  #1.
- **Date**: 2026-08-09
- **Decided by**: Loom agent (issue #1), running the `klayout-tools` `spec-review` skill's
  procedure by hand (its bandgap-voltage-reference reference file, dated 2026-07-31) against
  this repo's own decision records and device-characterization/sim evidence. This is a
  **re-review**: the first spec-review pass (klayout-tools#124, posted on #1 2026-07-31)
  returned `defer`, gated on issue #31's PNP-pair σ(ΔVBE) evidence not existing yet. #31
  closed 2026-08-01 (PR #34); the evidence gap that forced that defer no longer exists, and
  substantial additional evidence (#9's offset budget, #11's full testbench suite, #12's
  whole-core Monte Carlo, #46's TC investigation) has landed since.

## Context

Issue #1 gates the whole dependency chain: per this repo's `CLAUDE.md`, "layout work locks
to the spec" only after ratification, and per the 2026-08-09 operator comment on #1, that
ruling was scaffolding (`loom:operator-only`) without a recorded per-block reason, blocking
work indefinitely. The operator's ruling unblocked #1 with an explicit interim contract: run
the `spec-review` skill, post its verdict with rationale as a comment on #1, and stage a
**proposed** (not ratified) decision record — the ratification flip itself stays with the
operator until klayout-tools#654 lands.

The full verdict, per-line rationale, and numbered amendments are posted as a comment on #1
(2026-08-09) and are not reproduced verbatim here; this record summarizes the verdict and
lists the exact amended values the operator can accept by comment, per this repo's `spec/
README.md` convention and mirroring DR-001's own "proposed, not itself ratification" pattern.

Grounding, in priority order per the skill: this repo's own decision records (DR-001,
DR-002 incl. its issue #106 revision, DR-003 incl. its issue #99 closure) and `sim/`
evidence (cited by record ID in the #1 comment); the bundled `bandgap-voltage-reference.md`
reference file (2026-07-31) for published achievability anchors; `kb/entries/
sky130-bandgap-reference.json` (read directly — `klt kb list`/`show` errors against this
install's path resolution, a tool issue out of this record's scope).

## Decision

**The spec-review verdict is `ratify-with-amendments`.** Five of seven Target-column rows
(PSRR, Supply, Iq, Area, and — via DR-001 — the Stretch-column/port-parity questions) are
either comfortably met with measured margin or already cleanly settled by an existing
decision record. Two rows — Output reference and Temp coefficient — cannot be ratified as
literally written: both are now **measured**, not merely argued, to miss their Target-column
value, on real-SPICE PVT and Monte Carlo evidence with internal closure checks. Neither
finding is a missing-evidence gap (which would call for `defer`); each has enough evidence to
state a precise amended value or an honest floor, which is what pushes the verdict to
`ratify-with-amendments` rather than a further `defer`.

**This record does not amend `README.md`'s spec table.** It states, precisely enough for the
operator to approve by comment, the amended row content the evidence supports — mirroring
DR-001's own explicit "does not itself constitute formal ratification" framing.

### Proposed amended spec-table content (for the operator to accept, amend, or reject)

| README row | Proposed amended content | Evidence basis |
|---|---|---|
| Output reference | Split into two rows. **Untrimmed**: "1.20 V, local-mismatch 3σ ≈1.22–1.30 % (whole-core, N=300 Monte Carlo, `tt_mm`, −40…125 °C) — measured **not** to meet ±1 %." **Trimmed**: "±1 % via DR-002's downward-only ladder-tap trim (0..−16 codes, ≈2.4 mV/code post-issue-#106 revision), covering ≥1.5×3σ of the mismatch spread in the downward direction only — does not correct dies whose mismatch pushes VOUT low." | `design/error-amp-offset-budget.md` §2 (1.41 %/1.54 % 3σ, 27 °C/125 °C, with closure check); `sim/monte-carlo-untrimmed/records/20260803-142259-544cc5e.md` (1.22–1.30 % 3σ, 0.67 % yield at 125 °C, FAIL); DR-002 (trim range/LSB). |
| Temp coefficient | "< 50 ppm/°C target **not yet met** — measured floor 152.9–169.3 ppm/°C untrimmed (all 15 PVT corners); the one lever investigated (`R2/R1` resize) has **no safe setting** (breaches accuracy at the TC-matching value, loses hot-corner regulation above ~123–124 °C at ff/2.97 V, fs/2.97 V at the next accuracy-safe step). Open gap, tracked pending a curvature-shaped correction, error-amp headroom widening, or `n_pnp_ptat` growth — none yet attempted." | `sim/output-voltage-tc/records/20260803-115356-7759435.md`, `20260803-142220-b24b404.md` (issue #46 / PR #54's floor finding). |
| PSRR @ DC | Unchanged value (> 60 dB); add corner binding "worst at sf/125 °C/2.97 V" and a new row "PSRR @ 1 kHz > 60 dB (evidenced; ≥100 kHz–1 MHz point still needed, reference-checklist gap)." | `sim/error-amp-loop/records/20260803-085320-e599e30.md` (worst 77.7 dB); `sim/psrr-dc/records/20260803-115352-7759435.md` (worst DC 77.67 dB, worst 1 kHz 61.97 dB). |
| Supply | Unchanged value (3.3 V ±10%); add corner binding "regulation-margin risk binds at ff/2.97 V, fs/2.97 V." | DR-003 closure (`sim/res-array-resize/records/20260805-204809-2c83c7a.md`); #46/DR-003's shared hot-corner-collapse mechanism. |
| Iq | Unchanged value (< 50 µA); add corner binding "worst at sf/125 °C/3.63 V, ≈11 µA headroom" and a cross-reference note that this headroom is the budget any future chopping/auto-zero fix for the accuracy row must fit inside. | `sim/error-amp-loop/`, `sim/quiescent-current/records/20260803-115334-7759435.md`; `design/error-amp-offset-budget.md` §5–§6. |
| Area | Unchanged value (< 0.05 mm²); add a note that measured margin is ≈8 % (down from ≈29 % at the skeleton stage) and MCC (9,600 µm²) is still carried analytically, not drawn. | `layout/matching-plan.md` §6 (45,968 µm² measured vs. 50,000 µm² budget). |
| Startup | Unchanged value (self-starting, < 1 ms); add an explicit "settled" definition and note the unresolved ff/−40 °C 2.9 mV cross-path convergence finding. | `sim/startup-stability/records/20260803-204236-f41373d.md` (12/12 PASS); `sim/startup-ramp/records/20260803-204350-f41373d.md` (10/12 PASS, 2 FAIL on a self-consistency check, not the 1 ms bound itself). |
| New rows | Add: Line regulation (evidenced, worst ≈0.0039 %/V); explicit "not specified" rows for Output noise, Load capability, Long-term drift. | `sim/line-regulation/records/20260803-123439-497b50f.md`; absence of any `sim/*noise*`/`*load*`/drift experiment. |
| Stretch column | Cite DR-001 directly: deferred in full to a separate, later-scoped block — not a ratified stretch goal, not aspirational-only. | `spec/decision-records/DR-001-supply-flavor-scope.md`. |
| Port parity | Confirm as-is (spec mirrors gf180-bandgap deliberately); no divergence found this pass beyond what the 2026-07-31 review already flagged (resistor-corner semantics, PNP menu, device-family naming, `res_xhigh_po` TC gap) — all already informational, not spec-value changes. | 2026-07-31 spec-review (klayout-tools#124), unchanged this pass. |

### Evidence-currency caveat (applies to the Output reference, Temp coefficient, PSRR,
Iq, and Startup rows above)

Every "single-device" testbench that instantiates `design/bandgap_core.sch` directly
(`sim/output-voltage-tc`, `sim/error-amp-loop`, `sim/error-amp-offset-mc`,
`sim/monte-carlo-untrimmed`, `sim/psrr-dc`, `sim/quiescent-current`, `sim/line-regulation`,
`sim/startup-*`) was last run 2026-08-03, **two days before** issue #99's `n_r2` 54→50 resize
(2026-08-05, DR-003 close-out). `design/bandgap_core.sch`'s own header comment (lines
226–238) discloses that simulating the schematic *as drawn* at the current `n_r2=50` through
this single-device family now reads ~33 mV low (VOUT(27 °C) ≈ 1.165 V) — a known, disclosed
modeling gap, not a fresh regression, but meaning every number cited above from that
testbench family is against the *superseded* `n_r2=54` parameterization. Only DR-002's and
DR-003's own purpose-built chained-topology testbenches (`sim/res-array-head-resistance/`,
`sim/res-array-resize/`, `sim/trim-lsb-chained/`) are current against `n_r2=50`.

This does not change the amendments above: the resize moved the opposite direction from the
one partial TC improvement issue #46 found (raising `n_r2`), so there is no basis to expect
the current parameterization reads better than what's cited. But re-running the `#11`
testbench family against the current sizing (or migrating it to the chained-topology
pattern) should happen before any of these specific numbers are treated as the final,
current word — see "Consequences" below.

## Alternatives considered

- **Ratify as literally written (no amendments).** Rejected — two Target-column rows
  (Output reference, Temp coefficient) are measured to miss their stated value; ratifying
  the table unchanged would state a false claim the repo's own evidence contradicts.
- **Defer again, pending TC-floor resolution.** Rejected. The 2026-07-31 review deferred
  because the evidence needed to make a judgment call did not exist (`#31` was open). That is
  no longer true: the evidence to state a precise judgment — including an honest "not yet
  met, here is the measured floor and the untried options" — now exists for every row. The
  skill's own defer criterion ("a prerequisite... is missing") does not apply; what's missing
  now is a *design* fix, not *evidence*, and `ratify-with-amendments` is the verdict shape
  built for exactly that: the operator ratifies the honest current state and the amendments
  name what closes the gap, rather than the whole ratification decision waiting on
  unscheduled design work with no committed timeline.
- **Silently relax the Target-column numbers to whatever the design currently measures, and
  call that "ratified."** Rejected — this repo's `CLAUDE.md` explicitly rules this out
  ("agents do not relax the ratified spec to make results pass"), and it is not this record's
  call to make regardless: the amendments above are worded as honest disclosures of what is
  and isn't met, with the actual amended *value* choice (relax the line vs. keep it as an
  explicitly open gap) left to the operator.

## Spec lines affected

All seven `README.md` Target-column rows, the Stretch column, and the port-parity note — see
the "Proposed amended spec-table content" table above for the row-by-row detail. No
`README.md` edit is made by this record.

## Consequences

- **Unblocks #1's remaining scope**: the operator can now rule on the amendments above by
  comment on #1, at which point (per the interim contract, klayout-tools#654 pending) a
  follow-up agent action transcribes the ruling into `README.md` and flips this record's
  Status to `ratified` — neither of which this record performs.
- **Names two open design gaps, not yet scoped as issues**: (1) a credible path to the
  Output-reference row closing at ±1% trimmed with full corner/global-process coverage (the
  amp budget doc's own top recommendation is chopping/auto-zeroing, costed at ≈11 µA of
  headroom and an unbuilt switch network); (2) a credible path to the Temp-coefficient row
  closing at all, since the one lever tried (R2/R1 resize) has no safe setting. Both should
  become tracked follow-up issues if the operator wants them pursued rather than accepted as
  open gaps.
- **Names one evidence-hygiene follow-up**: re-run (or migrate to the chained-topology
  pattern) the `#11` testbench family against the schematic's current `n_r2=50`
  parameterization before treating any of its cited numbers as final — see the
  evidence-currency caveat above. This is bounded, mechanical work (unlike the two design
  gaps above), a good candidate for the next Builder pass regardless of how the operator
  rules on the amendments.
- **Does not change #32's own status** (`spec: #1 ratification deferred pending PNP-pair
  sigma(dVBE) evidence (#31)`) — #32 tracked exactly the gate this record's evidence now
  closes; the operator may want to close #32 once #1 itself resolves, but that is not this
  record's call.
- **Reaffirms DR-001, DR-002, DR-003 unchanged** — this record cites and builds on all
  three; none of their own "proposed, not ratification" status changes here.
