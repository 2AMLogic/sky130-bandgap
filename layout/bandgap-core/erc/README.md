# `klt erc` supply evidence — T1 item 11 (power delivery, structural)

This directory is `bandgap-core`'s **item 11** evidence trail. Item 11 is the
*structural* power-delivery question — "is the supply actually connected to what
it powers" — and is deliberately **not** the analysis question (IR drop, EM);
those stay outside the item, per
[`klayout-tools/docs/design-evidence-tiers.md`](https://github.com/2AMLogic/klayout-tools/blob/main/docs/design-evidence-tiers.md).

**Read the newest `<record-id>/record.md` first.** This file explains what the
evidence establishes and — just as importantly — what it does not.

## What is here

```
erc-supply-spec.json                        # ../ -- the item-11 spec (inline rationale per field)
erc-nwell-tie-spec.known-gap.vdd.json       # ../ -- friction reproduction, half 1
erc-nwell-tie-spec.known-gap.vss.json       # ../ -- friction reproduction, half 2
erc/
  README.md                                 # this file
  <record-id>/                              # <YYYYMMDD-HHMMSS>-<short-sha>, one per flow run
    erc.<gds-record-id>.json                # klt erc --format json, supply spec, one per routed GDS
    erc.known-gap-nwell-{vdd,vss}.<id>.json # the two known-gap runs, newest GDS only
    record.md                               # gated human-readable summary (read this first)
```

Reproduce with `layout/bin/run-erc-supply-flow.sh` (no PDK install needed — the
curated deck and the antenna-limit table both ship inside `klt`). The `klt` build
is pinned separately from the DRC/LVS flow's; see `layout/requirements-erc.txt`
for why.

## The claim, stated exactly

**Met, and computed:**

- Both supplies, `VDD` and `VSS`, are declared as `nets[]` entries with
  `"kind": "supply"`, and each resolves to **exactly one electrical island** on
  both committed routed GDSs. Zero `erc.unconnected_net`; zero
  `erc.supply_short`. `erc_coverage.checked` carries
  `erc.net_connectivity:["VDD"]` and `erc.net_connectivity:["VSS"]`, so this is a
  check that ran, not a check that was skipped into silence.
- Each report's `provenance.input.content_hash` equals the sha256 of the routed
  GDS it names — the flow gates on that equality, so a report cannot drift from
  the layout it claims to describe.
- The `stackup` covers every conductor level the supplies are actually routed on
  (`poly` → `li1` → `met1` → `met2`), with `stackup[0]` carrying `"role": "gate"`
  and an `active_layer`, and `vias[]` bridging all three role boundaries this
  block draws.
- The **analog** column's LVS half is satisfied by item 4's own report: the
  freshest `lvs.combined.json`
  (`layout/bandgap-core/reports/20260817-020222-13476b7/lvs.combined.json`) is
  `status: "match"`, `mismatch_count: 0`, and its `net_correspondence` pairs both
  `VDD` and `VSS` to reference-side nets of the same name with `"pin": true`.
  The reference is a SPICE netlist (`reference.spice`), which carries the
  supplies by construction — the case item 11's analog column names explicitly,
  and the reason it asks for `net_correspondence` rather than the
  `power_connectivity` verdict a signal-only gate-level-Verilog reference would
  need. This block is analog and hand/generator-drawn: there is no `klt
  place-and-route` response, so the digital column's `power.pdn` /
  `power.tapcell_master` / `power.straps[]` requirements do not apply to it.

**Not met, and the reason it is not met:**

- **`erc.missing_tie` is NOT COMPUTED by the supply run.** The spec declares an
  empty `ties[]`, which per `klt erc`'s own contract
  (`docs/cli/erc.md`: *"Omitted entirely → `erc.missing_tie` is never
  computed"*) means the rule never runs. **Its zero count in the committed
  reports is an absence of evidence, not evidence of absence.** The reports say
  so themselves: `erc_coverage.inapplicable` records
  `erc.missing_tie:[]` with reason `ties_disclosed_tool_limitation`, and the
  top-level `ties_disclosure` block carries the reason in full text.

  Because of that, **item 11 as a whole is UNMET** for this block. It grades as
  `supply_spec_disclosed_tool_limitation` — distinguishable from
  `supply_spec_incomplete` ("nobody asked the question"), but still unmet,
  because a disclosure is the caller's word about their toolchain and never a
  computed result.

## Why `ties[]` is empty — the specific blocker

This is **not** klayout-tools#2169 (the `ties[]` well-conductor collapse that
produced a false `erc.supply_short` on any routed design). That is **fixed** on
the pinned `klt` build (0.6.0, via #2186), and this repo re-confirms the fix
rather than asserting it: both known-gap runs in the newest record declare a real
tie and report **zero** `erc.supply_short`.

The actual blocker is a different, second gap, filed from this repo under the
friction protocol as
**[2AMLogic/klayout-tools#2339](https://github.com/2AMLogic/klayout-tools/issues/2339)**:

> `ties[].well_layer` names one layer, and *every* merged shape on it is checked
> against that entry's single `net`. There is no well-side selector —
> `tap_requires`, `tap_is_dedicated` and `tap_boxes` all narrow the **tap**, and
> `well_boxes` is rejected outright alongside a drawn `well_layer`.

`bandgap-core`'s single `nwell` (64/20) layer holds **two differently-biased well
classes**, which is ordinary for a bandgap:

| n-well class | count | biased to | why |
|---|---|---|---|
| PMOS body wells | 4 | `VDD` | ordinary device-body tie |
| vertical-PNP base tubs | 2 | `VSS` | the `sky130_fd_pr__pnp_05v5` devices are diode-connected, so their base sits at the negative rail with the substrate collector |

Both classes are real, correct and fully tapped (sky130's dedicated `tap` 65/44,
up through `licon1` → `li1`). Neither can be declared without the other class
reporting a **false** `erc.missing_tie`. Rather than assert that, this repo
commits the reproduction: the two known-gap specs' reports have **disjoint,
complementary** finding sets — 2 findings and 4 findings, summing to exactly the
6 n-well shapes on the layout — so between them every well is shown tapped to its
correct supply, and neither run alone can say so.

`ties_disclosure` only takes effect when `ties[]` is empty, so there is no
configuration in which one tie is declared and the other disclosed. Declaring
one anyway would put findings in the report of record that are artifacts of the
declaration rather than defects in the layout — the exact thing the disclosure
machinery exists to avoid.

## Standing-in well-tie evidence (what *is* known about the ties)

Since `erc.missing_tie` was not computed, this is the evidence that the wells and
the substrate really are tied, named explicitly so the gap is bounded rather than
open-ended. None of it is a substitute for a computed `erc.missing_tie`; all of
it is independently checkable from committed artifacts.

1. **The two known-gap `klt erc` runs themselves.** Each is a real, checked
   `erc.missing_tie` computation (`erc_coverage.checked` carries
   `erc.missing_tie:["nwell_tie_vdd"]` / `["nwell_tie_vss"]`, not
   `inapplicable`), over a non-degenerate tie declaration — `tap_is_dedicated:
   true` against sky130's own tap layer, which is precisely the narrowing
   klayout-tools#2199 added so a tap declaration cannot silently pass on a
   source/drain contact. Their union covers all 6 n-well shapes with a passing
   tie. **This is the strongest single piece of standing-in evidence**: it is the
   same computation item 11 asks for, just split across two reports because the
   spec language cannot express it in one.
2. **LVS `net_correspondence`, from a SPICE reference.**
   `layout/bandgap-core/reports/20260817-020222-13476b7/lvs.combined.json` is
   `status: "match"` with `mismatch_count: 0` across 11/11 nets and 16/16
   devices, against `reference.spice`. The curated sky130 extraction deck resolves
   a device body through its well/substrate tap (`klayout_tools/decks/sky130.py`
   splits `tap` 65/44 by `nwell` containment — inside a well it is a PMOS well
   tie, outside it is a genuine substrate tie). A device whose body resolved to
   an unconnected or wrong net would not match its reference counterpart's body
   terminal, so a clean `match` is a body-connectivity statement, not only a
   signal-connectivity one. **Caveat, stated rather than hidden**: `klt lvs`'s
   own `body_verification` block is not present in this 0.2.0-era report, so this
   is an inference from the deck's behaviour, not a verdict the report states in
   its own words.
3. **A drawn substrate guard ring.** `tap` 65/44 outside every `nwell` is
   3 merged shapes totalling 2236 µm² on the newest GDS — two interior straps
   (87 µm² each) plus a continuous ring enclosing the whole block, spanning its
   full (−10, −10)…(284.06, 215.44) µm extent (`guard_ring_outer.gds` in each
   report directory is its generator output). It is contacted up through
   `licon1` → `li1` → `met1` to the `VSS` island that `erc.net_connectivity`
   above confirms is a single island.
4. **Pin labels in the merged GDS.** Both supplies carry `met1.label` (68/5) text
   in the committed stream — that is what lets `nets[]` resolve them at all, and
   what `lvs.combined.json` matches its 11 pins against.

## What would clear this

A `klt` build with a well-side tie selector (klayout-tools#2339 proposes
`well_requires`, symmetric with the existing `tap_requires`). At that point
`erc-supply-spec.json`'s `ties_disclosure` is replaced by two real `ties[]`
entries, `layout/requirements-erc.txt`'s pin is bumped, the flow is re-run, and
item 11 can be claimed met on a single report. It is **not** cleared by redrawing
the layout — the layout is already correct.

## Where the graded verdict lives

`signoff/signoff-report.json` — the committed `klt signoff --manifest` report
(issue #282) — is this block's verdict of record, and its item-11 row cites the
newest record here plus item 4's own `lvs.combined.json`. It renders
**`supply_spec_disclosed_tool_limitation`**: unmet, but mechanically
distinguishable from `supply_spec_incomplete` ("nobody declared ties at all")
and from `supply_spec_disclosed_unexpressible` ("there is no tap to name").
`layout/bin/run-erc-supply-flow.sh` re-points that citation at every new record
it writes; `./signoff/regenerate.sh` re-grades, and CI fails on any drift.

**`klt signoff` re-reads `erc-supply-spec.json` off disk** from the path the
report's own `spec` field names (`docs/cli/signoff.md`: without it, "every
declared supply resolved to one island" and "no supply was ever declared" are
indistinguishable — both report zero findings). That is why the flow runs from
the repo root with **repo-relative** paths, and why the spec must stay committed
beside the evidence: an absolute path baked into a committed report resolves on
exactly one machine.
