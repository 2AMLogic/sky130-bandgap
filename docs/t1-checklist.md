# Gap to T1 / bronze — `bandgap-core` (sky130)

The block's standing **gap-to-T1 tracker**: one row per checklist item, with the
verdict, the read it was taken from, and the artifact that read rests on.

T1 ("designed and simulation-validated with open tools") is defined by
[`klayout-tools/docs/design-evidence-tiers.md`](https://github.com/2AMLogic/klayout-tools/blob/main/docs/design-evidence-tiers.md)
→ "T1 checklist", read against its **Analog** column (this block is analog,
hand/generator-drawn, with no RTL and no `klt place-and-route` step). T1 and
"bronze" are the same rung; **awarding** the catalog tier is a separate operator
decision recorded in `product/everyblock/grants.md`, and nothing in this file is
one.

## The checklist grew to eleven items on 2026-09-17

Item 11 (**Power delivery, structural**) was added upstream as
klayout-tools#2025. Every "gap to T1" figure in this repo dated before that —
including the `5/10` this file supersedes — was taken against a **ten**-item
checklist that no longer exists. The denominator changed; that alone changes what
a T1 claim means, which is why the count is restated here rather than quietly
carried forward.

## Status

| # | Item | Verdict | Read from | Evidence |
|---|---|---|---|---|
| 1 | Design sources | **PASS** | #175 re-read, 2026-08-15 | `design/bandgap_core.sch`, `design/error_amp.sch`, `design/startup_injector.sch`; `layout/bandgap-core/reference.spice` re-derived on every schematic-affecting change |
| 2 | Layout | **PASS** | #175 re-read, 2026-08-15 | `layout/bandgap-core/reports/<newest>/bandgap_core_routed.gds` + per-cell GDS/`.gen.json`, with the `klt gen`/`draw`/`compose` chain documented in that dir's `record.md` |
| 3 | DRC clean | **PASS**, disclosed deck gaps | `design/block-characterization-report.md` §3, 2026-09-10 | `reports/20260817-020222-13476b7/drc.json` (`violation_count: 0`) + `met2-drc.json`; `layers_in_stream_without_rules` and the met2 deck gap disclosed in §4 of that report |
| 4 | LVS clean | **PASS**, single-engine | `design/block-characterization-report.md` §3, 2026-09-10 | `reports/20260817-020222-13476b7/lvs.combined.json` — `status: "match"`, `mismatch_count: 0`, 11/11 nets, 16/16 devices. Single toolchain (`klayout`); the second-engine cross-check (klayout-tools#343) has not landed |
| 5 | Full PVT vs. ratified spec | **FAIL (mixed)** | `design/block-characterization-report.md` §3, 2026-09-10 | Box-method TC fails at every corner (schematic and post-layout); disposition recorded in [DR-009](../spec/decision-records/DR-009-tc-floor-disposition-defer-curvature-correction.md). Trim row has no evidence against the current ratified design |
| 6 | Monte Carlo | **PASS** | `design/block-characterization-report.md` §3, 2026-09-10 | `sim/monte-carlo-untrimmed/records/20260817-121131-d7d85b6.md` re-run against the post-#193 chained-array design; `sim/error-amp-offset-mc/records/20260817-130441-aa5324e.md` |
| 7 | Post-layout verification | **PARTIAL** — no `klt pex` | `design/block-characterization-report.md` §3, 2026-09-10 | Seven `sim/*-post-layout/` suites, all ratified-graded at/after the post-#193 design. `klt pex` — the only automated evidence `docs/cli/signoff.md` accepts for this item — does not exist upstream ([Epic #709](https://github.com/2AMLogic/klayout-tools/issues/709)); the extraction-based re-run is a manual substitute |
| 8 | Characterization report | **PASS** | this file's own read, 2026-09-22 | [`design/block-characterization-report.md`](../design/block-characterization-report.md) exists and is current as of commit `e8e2e46`; it carries its own staleness rule in §0 |
| 9 | Testbenches shipped | **PASS** | #175 re-read, 2026-08-15 | Every `sim/*/` suite ships its bench + a cold-start invocation; PDK pinned in `sim/pdk.json` |
| 10 | Repo hygiene | **PASS** | this file's own read, 2026-09-22 | `README.md` states the block, its ratified spec table, and how to reproduce; `LICENSE` present; CI validates the harness and evidence formats. (#175 marked this FAIL on 2026-08-15 for stale maturity-ladder text; that text was rewritten since) |
| 11 | **Power delivery (structural)** | **UNMET** — `supply_spec_disclosed_tool_limitation` | this file's own read, 2026-09-22 | [`layout/bandgap-core/erc/`](../layout/bandgap-core/erc/README.md) — supply half **met and computed**; `erc.missing_tie` **not computed**, disclosed. See below |

**7/11 pass** as of 2026-09-22. Blocking: **5** (PVT vs. ratified spec — the TC
row, disposition deferred by DR-009), **7** (no `klt pex`, blocked upstream),
**11** (missing-tie half, blocked upstream). Item 5 is the only one blocked by
this block's own engineering rather than by missing upstream tooling.

**Freshness rule, same as every other evidence artifact here**: each row above is
**transcribed** from the read named in its "Read from" column, not re-derived at
the moment you are reading this. Rows sourced from #175 (2026-08-15) predate the
post-#193 design/layout refresh; rows sourced from
`design/block-characterization-report.md` are that report's own verdicts and are
governed by its §0 regeneration rule. Re-read an item against current `main`
before relying on its verdict; the item-11 row below is the only one this file
derives itself.

## Item 11 in detail (derived here, 2026-09-22)

Item 11 is the **structural** power-delivery question — is the supply actually
connected to what it powers — graded from a `klt erc` supply-spec run. IR drop
and EM (`klt power`) stay deliberately outside it.

| Half | State | Where |
|---|---|---|
| Supply islands | **MET, computed** — `VDD` and `VSS` each resolve to exactly one electrical island on both committed routed GDSs; zero `erc.unconnected_net`, zero `erc.supply_short`; both present in `erc_coverage.checked` | `layout/bandgap-core/erc/<record-id>/erc.*.json`, spec `layout/bandgap-core/erc-supply-spec.json` |
| LVS carried the supplies (analog column) | **MET** — `lvs.combined.json`'s `net_correspondence` pairs `VDD` and `VSS` to reference-side nets, `"pin": true`, from a SPICE reference | `layout/bandgap-core/reports/20260817-020222-13476b7/lvs.combined.json` |
| Well/substrate ties (`erc.missing_tie`) | **NOT COMPUTED** — `ties[]` is empty with a `ties_disclosure` of kind `tool_limitation`; `erc_coverage.inapplicable` records `ties_disclosed_tool_limitation`. **A zero count here is an absence of evidence, not evidence of absence.** | `layout/bandgap-core/erc/README.md` names the standing-in well-tie evidence |

The blocker is **[2AMLogic/klayout-tools#2339](https://github.com/2AMLogic/klayout-tools/issues/2339)**
(filed from this repo under the friction protocol): `ties[].well_layer` checks
every merged shape on one layer against a single declared net, and this block's
one `nwell` layer holds two differently-biased well classes (4 PMOS body wells at
`VDD`, 2 vertical-PNP base tubs at `VSS`). Either declaration reports the other
class as a false `erc.missing_tie`. This is **not** klayout-tools#2169, which is
fixed on the pinned `klt` 0.6.0 build and re-confirmed fixed against this layout.
The gap is cleared by a `klt` build with a well-side selector, not by redrawing
the layout.
