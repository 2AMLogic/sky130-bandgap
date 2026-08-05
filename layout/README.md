# layout/ — the klayout-tools (`klt`) DRC/LVS flow

Issue #14's deliverable: a headless, repeatable DRC/LVS flow driven by
[`klayout-tools`](https://github.com/2AMLogic/klayout-tools) (`klt`),
**proven on a trivial known-good cell**. Bandgap-core-specific layout
starts with issue #15's floorplan + matching plan (see "Extending to the
bandgap core" below) — the material above this section predates that and
is not core-specific.

Two rules from the root `CLAUDE.md` shape this directory the same way they
shape `sim/`:

- **Verification is the product.** A DRC/LVS "pass" claim ships with the
  actual reports it came from, plus a negative control proving the flow can
  also report failure.
- **Friction protocol, with force.** Every `klt` gap/awkwardness hit while
  standing this up gets checked against the public
  [`2AMLogic/klayout-tools`](https://github.com/2AMLogic/klayout-tools)
  tracker and filed (or, if already tracked, cross-confirmed) there —
  tool-gap description only, never this repo's design/spec content. See
  "Friction protocol: what was found" below.

## Quick start (cold machine)

```bash
# 1. install the pinned klt build (~10s; see requirements.txt for the pin)
layout/bin/setup-venv.sh

# 2. sanity-check the sky130A PDK resolves (same pin as sim/pdk.json)
layout/.venv/bin/klt pdk find --pdk sky130A

# 3. run the trivial-cell DRC/LVS proof (~5s)
layout/bin/run-trivial-cell-flow.sh
```

The last command writes a fresh, timestamped record under
`trivial-cell/reports/<record-id>/` and updates
`trivial-cell/reports/LATEST` to point at it. The currently-checked-in
record is
[`trivial-cell/reports/20260803-133256-69a6ac2/record.md`](trivial-cell/reports/20260803-133256-69a6ac2/record.md)
— **read that file first**; it is the actual pass/fail evidence this issue
delivers, not this README.

## Why `klt`, and why a git-commit pin (not a PyPI version)

`klayout-tools` v0.1.0 on PyPI ships only five verbs
(`layers`/`stats`/`cells`/`drc`/`pdk`). This flow needs `gen` (to build the
trivial cell), `extract`, and `lvs` — all implemented and documented on
`main` but not yet in a PyPI release
([2AMLogic/klayout-tools#342](https://github.com/2AMLogic/klayout-tools/issues/342)
tracks cutting one). The project's own README names installing from a git
ref as the sanctioned way to get the latest development verbs; `requirements.txt`
pins an **exact commit**, not floating `main`, for the same reproducibility
discipline `sim/pdk.json` applies to the PDK version — a re-run months from
now installs the identical `klt` build instead of whatever `main` has
drifted to since. Bump the pin deliberately (and re-run
`layout/bin/run-trivial-cell-flow.sh` to refresh the checked-in report)
when picking up new `klt` capability.

## The flow

```
klt gen mos_array --pdk sky130A         (1) build the trivial known-good cell
        |
        v
klt drc <cell>.gds --deck sky130        (2) DRC against the sky130 deck
        |
        v
klt extract <cell>.gds --deck sky130    (3) layout -> schematic-equivalent netlist
        |
        v
klt lvs (extracted vs. hand-written      (4) LVS: topology compare
         reference netlist)
```

**The trivial cell**: `klt gen mos_array`'s documented defaults (a 2x2
array of unit NMOS devices with a one-column dummy guard on each side,
`nfet` flavor, no well) are chosen because the project's own docs guarantee
every generator's default `params` pass `klt drc --deck sky130` clean —
exactly the "trivial known-good cell" this issue's acceptance criteria
call for. `res_array` (the resistor-array generator — closer in spirit to
this repo's own poly-resistor-heavy topology) was tried first and rejected
for this specific proof: its output cannot round-trip through `klt
extract`'s resistor recognition today, a real `klt` gap, not a mistake on
this repo's side — see "Friction protocol" below. `mos_array` has no such
gap and round-trips cleanly through the whole flow.

**The reference netlist** (`trivial-cell/reference.spice`) is hand-written
to match `mos_array`'s pinned-default topology: 4 independent *real* unit
NMOS devices, each with its own isolated source/drain/gate net, bodies tied
to one shared `vsubs` pin. `klt lvs`/`NetlistComparer` compares topology, not
net *names* (see
[`docs/cli/lvs.md`](https://github.com/2AMLogic/klayout-tools/blob/main/docs/cli/lvs.md)
in the `klayout-tools` repo), so the reference's arbitrary net names do not
need to match the extracted netlist's own arbitrary `$N`-style names.
`mos_array` still physically draws 8 units (4 real + 4 dummy, the default
2x2-array-with-1-dummy-column shape) -- since issue #62's fourteenth
increment (2AMLogic/klayout-tools#490/#491, merged via #494/#495), sky130's
curated deck recognizes the 4 dummy-column units as dummies (no schematic
counterpart by construction) and `klt extract` drops them from the
comparison, so the reference only needs to state the 4 that matter. See
`trivial-cell/reference.spice`'s own header for the full history.

**Two negative controls** (`reference.broken-device.spice`,
`reference.broken-topology.spice`) prove the flow actually *fails* on a
real defect, not just that it produces a report — per `klt lvs`'s own
documented guidance, a device-parameter-only corruption and an independent
topology (shorted-net) corruption, since a single corruption class can
pass by accident on a compare that ignores the other axis. Both must (and
do) report `status: "mismatch"`.

## Repeatability

`layout/bin/run-trivial-cell-flow.sh` was run twice in immediate succession
from a clean worktree; both runs produced the identical four-way verdict
(DRC clean, LVS match on the good reference, LVS mismatch on both negative
controls) — `layout/bin/render-record.py` asserts all four and exits
non-zero if any flips, so a silent regression on a future `klt` pin bump
would fail loudly instead of quietly shipping a stale-looking "clean"
report. Only one of the two runs' reports is checked in (the redundant
second run added no evidence).

## Directory layout

```
layout/
  README.md                  # this file
  requirements.txt           # pinned `klt` install (git commit SHA)
  bin/
    setup-venv.sh             # create/refresh layout/.venv from requirements.txt
    run-trivial-cell-flow.sh  # the repeatable driver: gen -> drc -> extract -> lvs -> report
    met1_bus.py               # hand-drawn met1 bussing + the met2/via1 escape plane
    met2_drc.py               # DRC for the met2 plane the curated deck has no rules for
    render-record.py          # renders + verdict-checks a record's record.md
  tests/                      # PDK-free unit coverage for the flows' own gates
  .venv/                      # gitignored -- `klt` install, created by setup-venv.sh
  trivial-cell/
    reference.spice                    # known-good LVS reference netlist
    reference.broken-device.spice      # negative control 1: device.property corruption
    reference.broken-topology.spice    # negative control 2: net.merged corruption
    reports/
      LATEST                    # plain-text pointer to the newest record id
      <record-id>/              # <YYYYMMDD-HHMMSS>-<short-git-sha>, one per run
        gen.json, trivial_mos_array.gds
        drc.json
        extract.json, trivial_mos_array.extract.spice
        lvs.request.json, lvs.json
        lvs.broken-device.request.json, lvs.broken-device.json
        lvs.broken-topology.request.json, lvs.broken-topology.json
        reference*.spice           # snapshot of the reference(s) used for this record
        report.md                  # `klt report --format github-summary` rendering
        record.md                  # human-readable pass/fail summary (read this first)
```

`<record-id>` mirrors `sim/`'s `<YYYYMMDD>-<HHMMSS>-<short-git-sha>` (UTC)
convention (see `sim/README.md`) so the two evidence trails read the same
way. Unlike `sim/`, this flow does not yet enforce a PDK-version pin the
way `sim/bin/corner-run.py` does — `record.md` surfaces the resolved PDK
version as a manual cross-check against `sim/pdk.json` instead.

## Friction protocol: what was found

Standing this flow up surfaced two real `klt` gaps. Both turned out to
already be tracked publicly (this canary's friction protocol has already
been exercised against this same tool from the sibling `gf180-bandgap`
repo, so a fresh, unrelated gap on every attempt is not expected) —
independently confirmed with a short reproduction comment on each rather
than filed as new duplicate issues, per the protocol's actual goal (surface
the gap, not inflate the tracker):

1. **[`klt gen res_array` never draws the resistor-ID marker layer its own
   PDK deck's resistor recognition requires](https://github.com/2AMLogic/klayout-tools/issues/369)**
   (open). Running the resistor-array generator's own output straight
   through `klt extract --deck sky130` extracts zero devices — the body
   geometry is silently absorbed into ordinary interconnect instead of
   recognized as a resistor. This is why the trivial-cell proof above uses
   `mos_array`, not `res_array`, even though poly resistors are closer to
   this repo's actual device mix — confirmed independently reproducing on
   `sky130`, tracked upstream, not re-filed.
2. **[PyPI's `klayout-tools` release lags `main` by 13 verbs](https://github.com/2AMLogic/klayout-tools/issues/342)**
   (open) — `gen`/`extract`/`lvs` (everything this flow needs beyond `drc`)
   are `main`-only today, hence this directory's git-commit pin instead of
   a normal version pin. Confirmed as a downstream-consumer data point.

Both closed/already-fixed gaps hit along the way
([`__version__` drift from the released version](https://github.com/2AMLogic/klayout-tools/issues/69),
[no path to compose more than a single-generator layout](https://github.com/2AMLogic/klayout-tools/issues/210))
needed no action.

If a *new* gap (not already covered by the above) turns up in follow-on
layout issues, file it at `2AMLogic/klayout-tools` per the root `CLAUDE.md`
— tool-gap description only, no spec values or design content from this
repo.

## Known klt-deck limitations relevant to later, core-specific layout issues

Not gaps to file (both are documented, deliberate scope limits of the
curated `sky130` deck, not bugs) but worth flagging now for whichever later
issue takes on bandgap-core layout/LVS, since this issue's own scope
stops at the trivial-cell proof:

- **No NMOS substrate-tap extraction.** The curated deck ties every NMOS
  body to a single global `vsubs` net rather than a real drawn tap
  (`docs/cli/extract.md` → "Coverage"). Harmless for this issue's trivial
  cell (see `record.md`'s `device.body_unverified` note) but means an LVS
  reference netlist for a real block should also tie NMOS bodies to a
  single net, not model per-tap connectivity the extractor can't see.
- **No voltage-flavor distinction on MOS devices.** `klt extract`'s `nfet`/
  `pfet` classes are flavor-agnostic — a 5 V-flavor (thick-oxide) device
  and a core-voltage device both extract as the same generic class, with
  no `L`/`W`/oxide-thickness-based disambiguation. A future bandgap-core
  LVS reference netlist that mixes voltage flavors (per this repo's own
  device survey) will need `hints`/manual review to confirm the *intended*
  flavor correspondence, since `klt lvs` cannot check it structurally.
- The deck does recognize `pnp` (vertical bipolar) and three poly-resistor
  sheet-rho flavors as distinct device classes (see `klt extract`'s own
  `device_classes` field) — the primitive families this repo's core will
  need are already modeled in principle; #1's finding above is the one
  concrete blocker on the resistor family specifically, and only for the
  `klt gen`-generated fixture path, not for hand-drawn or PCell-instanced
  resistor geometry that already carries the marker layer.

## Extending to the bandgap core (issue #15)

Issue #15's deliverable: a floorplan + written matching plan for
`bandgap_core`/`error_amp`, plus an **initial placed layout skeleton**
proving the floorplan composes and DRC-cleans. Read
[`matching-plan.md`](matching-plan.md) first — it is the actual matching
rationale (which mismatch term dominates, per issue #12's Monte Carlo
contributor breakdown, and why the floorplan prioritizes it); this section
only points at where the generated evidence and tooling live.

```bash
layout/bin/setup-venv.sh                    # once, or after a requirements.txt bump
layout/bin/run-bandgap-floorplan-flow.sh    # generate + place + guard-ring + DRC
```

Writes a fresh record under `bandgap-core/reports/<record-id>/` (same
`<YYYYMMDD-HHMMSS>-<short-sha>` convention as `trivial-cell/reports/`) and
updates `bandgap-core/reports/LATEST`. The checked-in record is
[`bandgap-core/reports/20260803-192947-e7a30b4/record.md`](bandgap-core/reports/20260803-192947-e7a30b4/record.md)
— read that for the actual DRC-clean / area-budget evidence, and its
`renders/overview.png` for a visual check of the common-centroid/dummy-ring
placement.

`layout/requirements.txt`'s `klt` pin was bumped for this issue (see that
file's own comment) to pick up `gen-compose`'s `placement.strategy:
"explicit"` (2AMLogic/klayout-tools#330), which is what makes a real 2D
floorplan possible instead of the single-row-only composition #14's flow
used. The bump was verified non-regressing by re-running
`run-trivial-cell-flow.sh` unmodified before building on it — see
`trivial-cell/reports/` for the refreshed record with an identical PASS
verdict to the pre-bump one.

This skeleton is DRC-clean but explicitly **not** LVS-checked (two of its
matched-device generators, `bjt_array` and `res_array`, don't round-trip
through `klt extract` as recognized devices yet — see
`matching-plan.md` Section 7) and **not** a tape-out-ready layout (no
routing, and the resistor ladder is at reduced scale pending
2AMLogic/klayout-tools#415 — see `matching-plan.md` Section 4). Routing and
LVS are issue #62's scope, below.

## Routing the core and closing on LVS (issue #62)

```bash
layout/bin/setup-venv.sh                 # once, or after a requirements.txt bump
layout/bin/run-bandgap-routed-flow.sh    # gen -> draw -> compose+route -> drc -> extract -> lvs
```

Writes a fresh record under `bandgap-core/reports/<record-id>/` alongside
(never replacing) the #15 skeleton's records, and updates
`bandgap-core/reports/LATEST`. **Read that record's `record.md` first** — it
carries a per-criterion scoreboard, the routed-net table, the promoted-pin
table, and a quantitative LVS mismatch analysis. Summary of what it measures:

| | #15 skeleton | #62 routed |
|---|---|---|
| inter-block routing | none drawn | 13/13 declared nets routed — **12/12 schematic inter-block nets fully joined** (criterion 1 MET), 7 hops via the met2 escape plane |
| promoted top-level pins | 0 | 11 |
| R2A/R2B ladder | 16 units (reduced) | **270 µm/leg (the real length)** — 100 coarse 5 µm units folded into 10 rows, plus 40 fine 1 µm trim units in 4 rows carrying each leg's last 20 µm |
| extracted `pnp` | 0 | 16 |
| extracted `nfet` | 0 | 16 |
| DRC | clean | clean |
| LVS | not attempted | runs; **mismatch**, see below |

Getting from the #15 skeleton to this state took roughly twenty-three
increments (the full history is `layout/matching-plan.md` Sections 7a-7u,
not repeated here); a few changes are worth knowing before reading a record:

1. **Full-length ladder.** `res_array` gained a `rows` fold parameter
   (2AMLogic/klayout-tools#415, merged upstream), so the real R2A/R2B ladder
   folds into a compact block instead of a ~710 µm-long single row. It draws
   the schematic's whole 270 µm per leg — 50 coarse 5 µm units plus 20 fine
   1 µm trim units, so the trim taps *subtract* from the specified length
   rather than adding to it (issue #91; it drew 286 µm before). The whole
   routed cell is 45,968 µm², inside the 50,000 µm² budget.
2. **PNP recognition is drawn by the generator itself now.** `klt gen
   bjt_array` originally drew no bipolar device-recognition marker on sky130
   and no well tap for its base pads, so its output extracted as *zero*
   devices — filed as
   [2AMLogic/klayout-tools#432](https://github.com/2AMLogic/klayout-tools/issues/432),
   resolved via [#440](https://github.com/2AMLogic/klayout-tools/issues/440):
   `bjt_array` now draws sky130's bipolar marker and a well tap per unit
   device on its own. The local `klt draw` overlay this flow used to compose
   to close the gap is retired.
3. **A met2 escape plane for inter-block hops met1 has no corridor for.**
   sky130's curated deck originally exposed exactly one routing metal above
   the device pads (`li1`/met1, the same layer every generator draws its own
   pads on) — filed as
   [2AMLogic/klayout-tools#433](https://github.com/2AMLogic/klayout-tools/issues/433),
   resolved via [#508](https://github.com/2AMLogic/klayout-tools/issues/508)
   (merged via #511): the curated *extraction* deck now has a met2/via1
   level too, which `gen_bandgap_routed.py`'s router uses as a last-resort
   escape for the three hops (`D1`, `GDRV`, `VSS`) that had no met1 corridor
   under any router lever tried (search depth, channel window, row-0
   margin/re-placement, a genuine 2D row split — `matching-plan.md` Sections
   7d-7o). The escape plane's own DRC is checked by this repo's own
   `layout/bin/met2_drc.py` against the installed PDK's source rules, since
   the curated *DRC* deck still carries no met2/via rule
   ([klayout-tools#513](https://github.com/2AMLogic/klayout-tools/issues/513),
   open).

**All 12 of 12 schematic inter-block nets are joined across every block they
reach — criterion 1 is MET, not partial.** Measured against
`design/bandgap_core.sch`'s own inter-block node list, not just the flow's
own `connectivity[]` declaration; the record's "Schematic inter-block nets:
drawn vs. labelled only" table is the per-net evidence.

**LVS is not clean, but every remaining cause is disclosed, non-topology,
and out of this repo's own layout to fix.** `mismatch_count` reached **4**
as of issue #62's twenty-first increment and has not moved since (an
independent re-run from a clean checkout reproduces it byte-for-byte —
`matching-plan.md` Section 7u); `devices.matched` is 12, and there is no
`device.class`, `net.split`, `net.merged`, or `net.unmatched` mismatch left.
The two causes:

1. **`MCC`** (the error amp's compensation cap) is in the schematic and
   deliberately not drawn — a single-ended layout omission documented since
   issue #15's own area-budget section, not a defect. The only
   `device.unmatched` entry.
2. **`res_high_po`'s per-device head/contact resistance is charged once per
   drawn primitive, not once per logical device.** sky130's real
   `sky130_fd_pr__res_high_po` SPICE model card has a fixed per-instance
   head/end-resistance term in addition to its length-scaling term, and
   `klt extract` now models that term too
   ([klayout-tools#518](https://github.com/2AMLogic/klayout-tools/issues/518),
   merged). But this repo's own trim-tap ladder draws each schematic
   `R1`/`R2A`/`R2B` device as many (70, or 7) separately-contacted series
   primitives — required so every DR-002 trim tap lands on real, individually
   contacted metal — and `klt lvs`'s `combine_devices` sums the per-instance
   offset once per primitive when it folds the series chain, not once for
   the logical device. No drawn shape can fix this without removing the
   functional trim taps. Filed generically as
   [klayout-tools#559](https://github.com/2AMLogic/klayout-tools/issues/559),
   open.

Closing AC4 the rest of the way needs klayout-tools#559 upstream (or a new
`klt gen` continuous-poly-with-taps resistor capability) plus a decision on
`MCC`, both outside this repo's own layout — see `layout/matching-plan.md`
Section 7u for the current, fully-reasoned status and what it means for
issue #62 and for issue #16 (the post-layout extracted verification-suite
re-run this issue exists to unblock).

### The flow's own gates, and their unit tests

`run-bandgap-routed-flow.sh`'s exit status is not `klt`'s verdict — it is
`gen_bandgap_routed.flow_gate()`, ten named conditions that must all hold
(DRC clean, met2 DRC clean, area within budget, ladder at full scale, **the
drawn R2 leg length equal to the schematic's**, every device class extracted,
pins promoted, **no drawn shorts**, **no merged pin names**, **no split
routed nets**).
`klt lvs`-clean and full schematic-net coverage are deliberately *not* gated:
both are blocked on open upstream `klt` gaps, and gating on them would stop
the flow producing the very record that measures how far short it falls.

Two of those conditions are checks nothing else performs, and both catch the
same class of defect — the layout claiming connectivity the schematic does
not contain, which reads as a *better* LVS result and is therefore the one
failure mode that must never pass silently:

- **Drawn-short check** (`met1_bus.Met1Bus.conflicts()`). Every met1
  rectangle this flow hand-draws is tagged with its electrical node, so two
  nodes' wires touching — or sitting inside the deck's `met1.space.1` /
  `mcon.space.1` thresholds — is detectable here rather than showing up as a
  mystery LVS merge.
- **Label-collision check**
  (`gen_bandgap_routed.assert_no_merged_pin_names()`). A pin label landing on
  a pad another node's metal already contacts renames *that* node, and
  `klt extract` emits the result as a single `A|B` net with no diagnostic
  ([2AMLogic/klayout-tools#470](https://github.com/2AMLogic/klayout-tools/issues/470)).
  Invisible to DRC and to the drawn-short check — the shapes are legal and
  well separated; it is the labels that collide.
- **met2 DRC** (`layout/bin/met2_drc.py`). Since
  [klayout-tools#511](https://github.com/2AMLogic/klayout-tools/pull/511)
  sky130's curated *extraction* deck has a third connectivity level (met2
  over `via.drawing`), which is what lets the router escape a saturated met1
  — but the curated *DRC* deck has no rule for that level at all, so
  `klt drc` returns `violation_count: 0` on any met2 geometry whatsoever
  (its own `coverage.layers_in_stream_without_rules` says so). This checker
  applies the installed sky130A PDK's own source rules (`m2.1`, `m2.2`,
  `m2.6`, `via.1a`, `via.2`, `via.4a`/`via.5a`, `m2.4`/`m2.5`) to the
  composed stream instead. Filed upstream as
  [klayout-tools#513](https://github.com/2AMLogic/klayout-tools/issues/513).
- **R2 leg-length check** (`gen_bandgap_routed.r2_leg_length()`). The drawn
  divider leg's length against `design/bandgap_core.sch`'s own
  `L = r_lseg*n_r2 + r_lseg_trim*n_r2_trim`. `klt lvs` can only report a
  resistor's *value*, and only once both sides pair; `klt drc` has no opinion
  about length at all. For nineteen increments neither noticed that the trim
  ladder was wired in series *after* a full-length leg, drawing 286 um where
  the schematic states 270 and making every trim tap move the leg the one
  direction DR-002 forbids (issue #91). The check itself already existed and
  reported the defect — into `record.md` only. It is a gate row now.
- **Split-node check** (`met1_bus.Met1Bus.components()` scored by
  `gen_bandgap_routed.split_routed_nets()`). The inverse of the drawn-short
  check: a node this router reports as routed whose own metal is still in
  two pieces. It spans both routing planes — a met1 piece counts as joined
  to a met2 piece only where a via1 cut of the same net sits inside both —
  so a via stack that missed its own met1 is reported rather than reading as
  connected because each plane is individually in one piece.

Alongside them, `schematic_net_coverage()` scores acceptance criterion 1
against `design/bandgap_core.sch`'s own inter-block node list (never against
this flow's `connectivity[]` declaration) and also drives the router's
ordering search, so a scoring bug silently changes which layout gets drawn.

```bash
npm run test:unit    # or: python3 -m unittest discover -s layout/tests
```

`layout/tests/test_routed_flow_gates.py` covers those plus the gate
composition, in milliseconds, with **no `klt` install and no PDK** — so they
run in `npm run check:ci` on every push. Before these existed the three were
exercised only end-to-end, which meant their *failure* paths were never
exercised at all: a passing flow run by construction never reaches them. The
suite includes two regression cases read from this directory's own
append-only evidence (the record whose `VOUT`/trim-tap labels really did
collide, and the current clean one), so the gates are pinned against the
exact netlists they were written to judge.

`bandgap-core/reference.spice` is the schematic side of that comparison —
transcribed from `design/bandgap_core.sch` + `design/error_amp.sch` and
corroborated by the checked-in `n_r2=54` xschem snapshot its header cites
(`sim/output-voltage-tc/netlist-snapshots/`), never derived from the layout.
It states the schematic even where the layout falls short of it: there is no
0-ohm bridge device standing in for the unrouted `AOUT`→`GDRV` net.
