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
erc-supply-spec.json                        # ../ -- the item-11 spec (supplies + n-well ties)
erc-supply-spec.rationale.md                # ../ -- per-field rationale (klt 0.7.0 rejects comment keys)
erc-nwell-tie-spec.negative-control.json    # ../ -- same well boxes, nets swapped; must fail
erc-nwell-tie-spec.known-gap.{vdd,vss}.json # ../ -- superseded pre-0.7.0 reproduction (evidence, no longer run)
erc/
  README.md                                 # this file
  <record-id>/                              # <YYYYMMDD-HHMMSS>-<short-sha>, one per flow run
    erc.<gds-record-id>.json                # klt erc --format json, supply spec, one per routed GDS
    erc.negative-control-nwell-swapped.<id>.json  # swapped-net control, newest GDS only
                                            # (older records carry erc.known-gap-nwell-{vdd,vss}.<id>.json)
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

- **`erc.missing_tie` is computed.** The spec declares two n-well `ties[]`
  entries on nwell 64/20 with sky130's dedicated tap 65/44 connected through
  `li1`: `nwell_tie_vdd` (five wells, the PMOS bodies) and `nwell_tie_vss`
  (three wells, the vertical-PNP base tubs). Each is in
  `erc_coverage.checked`, `erc_coverage.skipped` is empty (no
  `degenerate_well_selection`), there is no `ties_disclosure`, and
  `erc.missing_tie` is zero on all three committed routed GDSs.
- **Falsifiable, not asserted.** The same well boxes declared to the *opposite*
  net (`erc-nwell-tie-spec.negative-control.json`) make `klt erc` report
  `erc.missing_tie` on all eight wells (3 declared `VDD`, 5 declared `VSS`).
  The record gates that count, so a tie declaration that could not fail would
  fail the flow.

**What the tie evidence rests on, stated rather than hidden:**

- The n-well count is **eight merged shapes, five + three** (read from the
  merged 64/20 region of the newest routed GDS). Earlier text here said six
  (four + two); the old known-gap reports' bounds (3 + 5) were always the
  authority and the six was a miscount.
- Which wells belong to which class is the **caller's word**: the stream draws
  one nwell layer and no marker separating the classes, so each tie selects its
  wells with `well_requires_boxes` (literal micrometre boxes, one per well).
  `klt` reports that as `erc_coverage.checked_by_well_assertion` (both ties),
  and `klt signoff` echoes it in `power_delivery.ties_checked_by_well_assertion`.
  The grader does not verify the assignment. The class assignment was derived
  from the pre-0.7.0 known-gap runs, whose finding sets were exact
  complements; the negative control re-tests it on every flow run (a
  mis-assigned well would flip a tie to `erc.missing_tie`).
- The boxes are the bounding boxes of today's wells. **A ninth nwell shape
  matches neither list and is not checked**; extend the boxes if the well set
  changes.
- Structural only: no IR-drop/EM analysis (outside item 11).

## Standing-in evidence (supplementary)

Now that the tie result is computed, this is corroboration, not a substitute:

1. **LVS `net_correspondence`, from a SPICE reference** — the item-4 report
   (`layout/bandgap-core/reports/20261022-070000-e6e4be0/lvs.combined.json`,
   `status: "match"`) pairs both supplies to reference-side nets. The curated
   sky130 deck resolves a device body through its well/substrate tap, so a clean
   match is also a body-connectivity statement; the report's own
   `body_verification` is `unchecked`, so that is inference from the deck.
2. **A drawn substrate guard ring** — `tap` 65/44 outside every `nwell` is 3
   merged shapes (two interior straps plus a ring enclosing the block),
   contacted up to the `VSS` island `erc.net_connectivity` confirms is one island.
3. **Pin labels in the merged GDS** — both supplies carry `met1.label` (68/5)
   text, which is what lets `nets[]` resolve them at all.

## History

Until issue #389 this directory's records (klt 0.6.0) declared an empty
`ties[]` plus a `ties_disclosure` of kind `tool_limitation`, because
[klayout-tools#2339](https://github.com/2AMLogic/klayout-tools/issues/2339)
(no well-side selector) made either tie report the other well class as a false
`erc.missing_tie`. klt 0.7.0 added `well_requires_boxes`/`well_excludes_boxes`
(#2540). The older records and the two `known-gap` reproductions are kept as
append-only evidence; they are no longer run by the flow. klt 0.7.0 also
rejects unknown spec keys, so the spec's former `_comment` block moved to
`erc-supply-spec.rationale.md`.

## Where the graded verdict lives

`signoff/signoff-report.json` — the committed `klt signoff --manifest` report
(issue #282) — is this block's verdict of record, and its item-11 row cites the
newest record here plus item 4's own `lvs.combined.json`. It renders **`met`**.
`layout/bin/run-erc-supply-flow.sh` re-points that citation at every new record
it writes; `./signoff/regenerate.sh` re-grades, and CI fails on any drift.

**`klt signoff` re-reads `erc-supply-spec.json` off disk** from the path the
report's own `spec` field names (`docs/cli/signoff.md`: without it, "every
declared supply resolved to one island" and "no supply was ever declared" are
indistinguishable — both report zero findings). That is why the flow runs from
the repo root with **repo-relative** paths, and why the spec must stay committed
beside the evidence: an absolute path baked into a committed report resolves on
exactly one machine. Editing the spec invalidates every earlier record's
`provenance.spec.content_hash`; only the newest record is cited.
