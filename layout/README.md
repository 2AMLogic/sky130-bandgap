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
to match `mos_array`'s pinned-default topology: 8 independent unit NMOS
devices (the 4 real + 4 dummy the default 2x2-array-with-1-dummy-column
draws), each with its own isolated source/drain/gate net, bodies tied to
one shared `vsubs` pin. `klt lvs`/`NetlistComparer` compares topology, not
net *names* (see
[`docs/cli/lvs.md`](https://github.com/2AMLogic/klayout-tools/blob/main/docs/cli/lvs.md)
in the `klayout-tools` repo), so the reference's arbitrary net names do not
need to match the extracted netlist's own arbitrary `$N`-style names.

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
    render-record.py          # renders + verdict-checks a record's record.md
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
| inter-block routing | none drawn | 9/9 declared nets routed, with net labels |
| promoted top-level pins | 0 | 23 |
| R2A/R2B ladder | 16 units (reduced) | **108 units (real count)**, folded into 9 rows |
| extracted `pnp` | 0 | 16 |
| extracted `nfet` | 0 | 16 |
| DRC | clean | clean |
| LVS | not attempted | runs; **mismatch**, see below |

Three changes make that possible, each backed by a `klt` pin bump
(`requirements.txt`) or a local workaround:

1. **Full-scale ladder.** `res_array` gained a `rows` fold parameter
   (2AMLogic/klayout-tools#415, merged upstream), so the real 108-unit
   R2A/R2B ladder occupies ~1,231 µm² instead of a ~710 µm-long single row.
   The whole routed cell is 38,171 µm², inside the 50,000 µm² budget.
2. **PNP recognition overlay.** `klt gen bjt_array` draws no bipolar
   device-recognition marker on sky130 and no well tap for its base pads, so
   its output extracts as *zero* devices — filed as
   [2AMLogic/klayout-tools#432](https://github.com/2AMLogic/klayout-tools/issues/432).
   The flow composes a `klt draw` overlay (82/44 marker per functional
   emitter pad, 65/44 nwell tap per base pad, positioned from the
   generator's own reported `ports[]`) to close it locally.
3. **Router-oracle port selection.** `klt gen-compose` rejects a net whose
   Manhattan backbone would cross a block's interior but offers no "which
   port should I have used?" query, and a 108-segment ladder exposes 216
   ports. `gen_bandgap_routed.py` drives `gen-compose` itself as the
   pass/fail oracle over an ordered, geometry-derived candidate list rather
   than hardcoding port indices.

**LVS is not clean, and the record says so rather than working around it.**
The blocker is upstream, not a layout choice: sky130's generator/router
layer-role table exposes exactly one routing metal (`li1`), the same layer
every generator draws its device pads on, and the router is documented as
unaware of a block's internal geometry — so any wire crossing a block shorts
to every pad it passes over. That makes intra-block bussing (tying an array's
8 emitters, or a ladder's 108 series segments, into one node) inexpressible,
so the layout's 243 devices cannot collapse into the reference netlist's 17.
Filed as
[2AMLogic/klayout-tools#433](https://github.com/2AMLogic/klayout-tools/issues/433);
the related "no way to route into a guard-ringed block" gap is
[#434](https://github.com/2AMLogic/klayout-tools/issues/434). The flow
deliberately does **not** draw those intra-block wires: `gen-compose` would
certify them `routed: true` while producing an electrical short, and a
certified short is worse evidence than an open node.

`bandgap-core/reference.spice` is the schematic side of that comparison —
transcribed from the xschem netlist snapshot this repo already records
(`sim/output-voltage-tc/netlist-snapshots/`), never derived from the layout.
