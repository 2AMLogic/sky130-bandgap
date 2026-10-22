# signoff/ — the block's graded T1 state

This directory is the **verdict of record** for this block's gap to T1
("sim-validated", the `klt signoff --manifest` tier-verdict report) —
the state issue #175's ten-item checklist re-read (2026-08-15) and the
README's "T1/bronze checklist" paragraph used to hand-carry. Both are
retained unchanged as the dated snapshots they are; from this manifest's
merge onward, the checklist state lives here and is re-derived, not
re-read by hand. That hand-read is also now stale by construction: the
checklist grew an eleventh item ("Power delivery (structural)",
klayout-tools#2025, 2026-09-17) after #175 was written, so a ten-item
re-read cannot even enumerate today's row set.

| File | What it is |
|---|---|
| `block-manifest.json` | The block manifest: this block's declared `kind` and, per T1 item, the evidence envelope cited behind it, each pinned to a `content_hash` of the committed artifact it grades. This is the file the fleet roll-up (2AMLogic/2am#956) consumes. |
| `signoff-report.json` | The committed `klt signoff --manifest block-manifest.json --format json` output — the graded per-item `met`/`unmet` table with a `reason` on every `unmet` row. Regenerate with `./signoff/regenerate.sh`. |
| `regenerate.sh` | Refreshes the item-8 evidence pin, rebuilds the item 1/2/9/10 attestations, re-grades the manifest with the pinned released klt (overwriting `signoff-report.json`), and re-verifies every pin against the artifact it describes. |
| `pinned-inputs.json` | Per pinned citation, **where in this repo the artifact that pin describes actually lives**. Neither the manifest nor the evidence envelopes hold that: a `content_hash` is the hash of the artifact the envelope *describes*, and the envelope's own path field may be absolute and machine-local (item 3's is). `scripts/ci/check_signoff_pins.py` needs it to re-hash the artifact — see "What `klt signoff` cannot check" below. |
| (item 6's citation) | Lives outside this directory, under [`sim/monte-carlo-untrimmed/records/`](../sim/monte-carlo-untrimmed/records/), because it is produced by a simulation harness (`sim/monte-carlo-untrimmed/emit_klt_yield.py`) rather than hand-assembled here. Its pinned `content_hash` is the hash of the **sample-set document** the report names in its own `samples` field, not of the report file — that is the input hash `klt signoff` computes for a `klt yield` envelope, which carries no `provenance` block of its own, so `pinned-inputs.json` names that same sample-set document. |
| (item 11's citation) | Lives outside this directory, under [`layout/bandgap-core/erc/`](../layout/bandgap-core/erc/README.md), because it is produced by a layout flow (`layout/bin/run-erc-supply-flow.sh`) rather than hand-assembled here. That flow re-points this manifest's item-11 entry at each new record it writes (`layout/bin/erc_signoff_citation.py`); re-grading is still `./signoff/regenerate.sh`'s job. Item 11 is the one T1 item whose `evidence` entry is a JSON **array** — the `klt erc` supply run plus item 4's own LVS report. |
| `evidence/characterization.generic.json` | The hand-rolled `kind: generic` envelope (issue #1152's item-8-only wrapper) asserting the aggregated [`design/block-characterization-report.md`](../design/block-characterization-report.md), pinned to that report's own `content_hash`. |
| `attest/` | The artifact-anchored attestations for T1 items **1, 2, 9 and 10** (issue #387): `design-sources.inventory.json`, `testbench-inventory.json` and `repo-hygiene.inventory.json` list the audited files with `content_hash`, and `item-{1,2,9,10}.evidence.json` are the `kind: generic` envelopes the manifest cites. Item 2 has no inventory: its envelope pins the routed GDS itself. All nine files are derived from the tree by `scripts/ci/attest_inventories.py`; never hand-edit them. See "Items 1, 2, 9 and 10" below. |
| `../design/netlist/` | The SPICE netlists derived from `design/*.sch` (item 1), plus `netlist.lock.json` recording the schematic hash each was derived from. Written by `scripts/ci/design_netlists.py --write`. |

CI checks this directory in **two** places, and they catch different things:

| CI job | Check | Catches |
|---|---|---|
| `signoff` | `scripts/ci/check-signoff-freshness.sh` — re-grades the manifest with the pinned released klt and requires byte-identical output to the committed `signoff-report.json` | an edited/re-pointed evidence envelope, a manifest or vendored-checklist edit, a grader that renders differently |
| `checks` | `scripts/ci/check_signoff_pins.py` (via `npm run check:ci`; stdlib-only, no klt/PDK) — re-hashes the committed artifact behind every `content_hash` | **a change to the artifact a pin describes** (the routed GDS behind items 3/11, the characterization report behind item 8) |

The fix for either is the same one-liner: `./signoff/regenerate.sh`, then
commit the refreshed report.

### What `klt signoff` cannot check, and why the pin check exists

**Items 3 and 8** cite envelopes that record their own
`provenance.input.content_hash`, and their `content_hash` in
`block-manifest.json` is copied from that recorded value — it pins the
artifact the envelope **describes**, not the envelope file. When `klt signoff`
grades that kind of citation it compares the manifest pin against the
*recorded* hash and stops there; it never opens the artifact. The committed
report says so itself: `citation.input_verified` is `null` on both of those
rows.

So for items 3 and 8 the manifest and the envelope can keep agreeing with each
other while the artifact they both claim to describe has moved on, and a pure
re-grade renders byte-identically:

- **item 3** — the DRC envelope records its input as an absolute path into the
  worktree that produced it (`/Users/…/.loom/worktrees/issue-178/…`), which
  resolves on no other machine. Filed upstream as
  [klayout-tools#2340](https://github.com/2AMLogic/klayout-tools/issues/2340).
  Rewrite `bandgap_core_routed.gds` and the render does not change.
- **item 8** — the generic envelope is hand-rolled and never re-derived at
  grading time. Edit `design/block-characterization-report.md` and, again, the
  render does not change.

**Item 6 is the exception, and it runs the other way.** A `klt yield` report
carries no `provenance` block *at all*, so there is no recorded hash to
compare against — `klt signoff` opens and hashes the sample-set document the
report names in its own `samples` field instead. That is precisely the leg the
paragraph above says never happens, and the committed report shows it
happening: item 6 is the one row whose `citation.input_verified` is `true`.

What a re-grade does and does not catch therefore **inverts** for item 6. The
manifest pins
`sha256(sim/monte-carlo-untrimmed/records/20260923-062524-1e38c62-klt-yield-input.json)`
and `klt signoff` hashes that same document at grading time, so editing it
stops the computed hash matching the pin and
`scripts/ci/check-signoff-freshness.sh`'s byte-identical re-grade **fails** —
unlike items 3 and 8, where the same edit is invisible. That is also why the
`samples` value has to stay **repo-relative** (issue #288): `klt signoff`
resolves it from the directory grading runs in, so an absolute, machine-local
path resolves nowhere else and the row silently loses this check. What
`check_signoff_pins.py` adds for item 6 is not a hash the re-grade misses but
coverage the re-grade cannot give: it runs klt-free and PDK-free in the
`checks` job, and it re-hashes the artifact at the repo-relative path declared
in `pinned-inputs.json`. With no envelope-recorded hash to compare against,
item 6 is verified on two of the three legs below rather than three.

**What item 6 means (and does not).** Item 6 is an *evidence-existence* check: a committed, pinned `klt yield`
envelope exists. The native envelope declares no `target_yield`, so its status can only be `reported`, never
failed, and `met` says nothing about accuracy conformance. Output-accuracy conformance is graded separately by the
derived DR-005 qualification
`sim/monte-carlo-untrimmed/records/20260817-121131-d7d85b6-dr005-qualification.json`
(issue #334; mean ± 3σ against the ratified window, currently **FAIL**), and the ≥50 % harness sanity floor is a
third, weaker verdict. None of the three substitutes for another.

`check_signoff_pins.py` closes that gap by asserting a three-way agreement per
pin: **manifest pin == `sha256` of the committed artifact == the hash the
cited envelope recorded**. `pinned-inputs.json` supplies the missing piece —
the artifact's repo-relative path — and must stay 1:1 with the manifest's
pinned citations: a new pinned citation with no entry there fails the check,
as does an entry for a citation that no longer exists. That is deliberate;
adding a citation should require saying what its hash describes.

Item 11's second citation is item 4's `lvs.combined.json`, and it is pinned like item 4's: both entries carry the report's own `provenance.input.content_hash` (the `klt lvs` 0.7.0 report records the hash of the pre-extracted layout netlist it compared), and `pinned-inputs.json` names that committed `bandgap_core_routed.extract.spice` for both (`item 4`, `item 11[1]`). `layout/bin/erc_signoff_citation.py` re-points item 11's LVS half at whatever report item 4 cites, so the two cannot drift apart, and refuses a report that records no input hash.

## Grader distribution discipline

Regeneration and CI grade with the **released PyPI registry wheel** of
the pinned `klayout-tools` release (`KLT_VERSION` in
`scripts/ci/check_signoff_freshness.py`; it is the first to natively
grade item 11 — `build_t1_item_count: 11` in the committed report), never
whatever `klt` is already on the host. Under the same version string a
`uv tool install git+...` snapshot or a full-checkout install can grade
differently (observed live across the fleet for 0.5.0: an 11-item-era
full-repo install under the name "0.5.0" next to the v0.5.0 tag snapshot
whose bundled checklist predates item 11 entirely,
klayout-tools#2216). The released wheel reports the git tag it was built
from (`klt version --format json` → `git_tag: v<pin>`, `is_release: true`);
`regenerate.sh` and the freshness check both assert that identity before
grading, through one shared implementation (`check_signoff_freshness.py
--assert-grader [KLT]`). The version pin lives in exactly one place,
`KLT_VERSION` in `scripts/ci/check_signoff_freshness.py`; the CI `signoff`
job and `regenerate.sh` read it via `--print-version`. To bump the grader,
edit that one constant.

**Checklist doc (`--tiers-doc`) decision, 0.6.0 → 0.7.0 (issue #387).** The
grader is now graded against the checklist **bundled with the pinned wheel**
(`source_doc: docs/design-evidence-tiers.md` in the report), not a vendored copy.
The vendored `signoff/design-evidence-tiers.md` (upstream `08825416`) predated the
0.7.0 text for items 1, 2, 9 and 10 (klayout-tools#2718 added the artifact-anchored
generic form), so passing it with `--tiers-doc` would have graded those rows against
the old "no verb, any passing envelope" wording. Grading without the flag renders the
same 11-item T1 skeleton, so the flag and the vendored file were dropped.

**Rows whose verdict moved with the 0.7.0 re-grade** (3/11 → 6/11 met; item 4 then moved to met, 7/11, with issue #388; item 11 then moved to met, 8/11, with issue #389):

| Item | 0.6.0 | 0.7.0 | Cause |
|---|---|---|---|
| 1, 2, 9, 10 | unmet `no_evidence` | **met** | the attestations below |
| 6 | met | unmet `undersized_sample` | not caused by this change to the evidence: 0.7.0 grades the `klt yield` report's own `sample_size.verdict` (klayout-tools#2467), and the committed report's verdict is `insufficient` on a measurement. `sim/` records are append-only, so the row is reported as graded; closing it needs a larger campaign, tracked separately. |

## Block kind: `analog`

The manifest's `kind` is **`analog`** — this block is a single bandgap
voltage-reference core with no digital/synthesized partition, so it
satisfies only the Analog column of items 1, 2, 5, 7, and 11. Nothing in
this repo warrants `mixed-signal` today.

## The verdict, row by row

`klt signoff` renders every T1 item either `met` (a cited, freshly-pinned,
passing check backs it) or `unmet` with a `reason`. Today's committed
verdict is **8/11 met** — an honest mechanical reading, not a hand-read: it
is a mechanical reading, not a hand-read, and a manifest that renders a row
`unmet` with a stated reason (items 5–7) is worth more than prose nobody
re-verifies.

**A row can get better without getting to `met`, and that is visible here.**
Item 11 moved from `no_evidence` (nothing existed) to
`supply_spec_disclosed_tool_limitation` (the supply half computed and passing,
the missing-tie half blocked by a named, filed upstream tool gap) when issue
#281 landed, and to **`met`** when issue #389 declared real n-well `ties[]` on
klt 0.7.0. The `reason` moves are what say what would close a row.

**And a row can get *worse* without the artifact changing, which is why item
4 stayed `unmet` for as long as it did.** Issue #288 investigated the
`mismatch_count` 0 -> 12 diagnostic and found it was not a version-to-version
regression: on the then-installed `klt` build (0.5.0 snapshot) the verdict was
*nondeterministic* (762/1000 clean, 238/1000 a false `mismatch`) while the
committed `0` reproduced 1000/1000 on the build `layout/requirements.txt`
pins. That measurement is retained in
`layout/bandgap-core/combine-determinism/20260923-062919-1e38c62/`; the
upstream tool gap is klayout-tools#2374 (closed); the disposition is
`layout/matching-plan.md` Section 7ff. Issue #388 re-measured on the released
0.7.0 wheel and the false `mismatch` is gone (see the item-4 row), which is
what let the row close.

| Item | Verdict today | Why — and what would change it |
|---|---|---|
| 1 — Design sources | **met** | Cites `signoff/attest/item-1.evidence.json`, an artifact-anchored generic envelope pinning `signoff/attest/design-sources.inventory.json`: [`design/bandgap_core.sch`](../design/bandgap_core.sch), `error_amp.sch`, `startup_injector.sch` with their `.sym` symbols, and the three netlists derived from them in [`design/netlist/`](../design/netlist/). Each netlist is bound to the hash of the schematic it was derived from (`netlist.lock.json`), so a schematic edit without regenerating its netlist fails CI (`design_netlists.py --check-lock`, and `--check-regen` against a fresh `klt netlist` in the `pdk-smoke` job). Netlists are xschem 3.4.7 output (CI's pinned build; 3.4.4 leaves `expr()` unevaluated) with the machine-local `** sch_path:` line rewritten repo-relative, because `klt netlist --check` otherwise reports `drifted` on every other checkout (klayout-tools#3010, fix not yet released). |
| 2 — Layout | **met** | Cites `signoff/attest/item-2.evidence.json`, which pins the committed routed GDS `layout/bandgap-core/reports/20260923-070209-dbd57a9/bandgap_core_routed.gds` directly (the same stream items 3 and 11 pin), generated by `layout/bin/run-bandgap-routed-flow.sh`. `met` attests that this stream is the committed layout, not that it is LVS-clean (item 4) or free of rule gaps (see item 3). |
| 3 — DRC clean | **met** | Cites `layout/bandgap-core/reports/20260817-020222-13476b7/drc.json` — `status: clean`, `violation_count: 0`, `provenance.input.content_hash` pinning the committed `bandgap_core_routed.gds` byte-for-byte (independently re-verified: `sha256sum` of that GDS matches the pinned hash). Coverage disclosure, read from the report rather than assumed (this envelope predates the `deck_scope` field, so only two of the three item-3 disclosure fields are available): `rules_skipped` is empty, but `coverage.layers_in_stream_without_rules` is **not** — 8 layers this stream draws (`64/20`, `65/44`, `66/13`, `68/5`, `82/44`, `83/20`, `86/20`, `94/20`) carry no rule in the curated sky130 deck this run used. A "clean" from a deck with disclosed holes is disclosed here, not hidden. |
| 4 — LVS clean | **met** | Cites `layout/bandgap-core/reports/20261022-070000-e6e4be0/lvs.combined.json` (issue #388), produced by the released `klayout-tools` 0.7.0 wheel (`provenance.klt_version: 0.7.0`, KLayout 0.30.12) from the unmodified committed `lvs.combined.request.json`, with the request, `bandgap_core_routed.extract.spice` and `reference.spice` copied byte-for-byte from the item-2/3 record `20260923-070209-dbd57a9` into the new record so it is self-contained. `status: match`, `error_count: 0`; nets 14/14, devices 22/22, pins 13 matched. Its `provenance.input.content_hash` (`sha256:29937be4…`, the extract netlist) is non-null and pinned in the manifest; `klt signoff` re-hashes it (`input_verified: true`). The earlier `20260923-070209-dbd57a9`/`20260817-020222-13476b7` reports (0.2.0, `provenance.input: null`) are untouched, append-only evidence and are no longer cited. **Determinism**: `layout/bandgap-core/combine-determinism/20261022-070000-e6e4be0/` repeats the same request 1000 times in-process under the 0.7.0 wheel, for both the as-committed build default and `combine_devices_max_attempts: 1`: 1000/1000 `status: match` in each, identical findings every time. The 238/1000 false `mismatch` seen on the 0.5.0 snapshot (klayout-tools#2374) does not occur on 0.7.0, so the verdict is citable. **Disclosures read from the report, not assumed.** (a) `mismatch_count` is 1 and `error_count` is 0: the one entry is a *warning*, `device.geometry_not_compared` for `RES_HIGH_PO` — KLayout declares a resistor's `A`/`L`/`P`/`W` secondary, so only `R` took part in the compare and the resistors' drawn geometry is **not** verified by this LVS (3 layout / 3 reference combined devices); it appears in all 1000 repeats and is not a flake (the determinism harness's `clean_fraction` of 0 reflects that warning, not a mismatch). The committed request is not changed to name `options.compare_parameters`, which would be a different, stricter claim than the one this row makes. (b) `power_connectivity.status` is `unchecked`, expected: the reference is a plain-element SPICE netlist (`reference.form: plain-element`) whose supplies take part in the ordinary compare. (c) `body_verification.status` is `unchecked`: the request is the pre-extracted-netlist form with no extraction deck, so nothing in this run says anything about device bodies / well taps either way. |
| 5 — Full corner verification vs a ratified spec | unmet `no_evidence` | This repo's `sim/*/records/*.json` are custom append-year harness records (see [`sim/README.md`](../sim/README.md)), not `klt sim`-shaped envelopes — no native evidence exists for `klt signoff` to grade yet. The human-audited evidence is real and extensive (`design/block-characterization-report.md` rolls up all seven ratified spec rows across PVT corners), but citing it here without a `klt sim`/`klt yield`/`klt pex` envelope would be the documented anti-pattern. Would need a minted `klt sim`-shaped envelope (see e.g. `2AMLogic/gf180-sram`'s `sim/signoff-sim-envelope.json` for the pattern) or a first-party `klt sim` run. |
| 6 — Statistical claims carry Monte Carlo evidence | unmet `undersized_sample` | Moved from `met` on the 0.6.0 → 0.7.0 re-grade; see "Rows whose verdict moved" above. The cited evidence is unchanged: `sim/monte-carlo-untrimmed/records/20260923-062524-1e38c62-klt-yield.json` (pinned to the sample-set document named in its `samples` field, 838 converged mismatch samples at −40/27/125 °C). 0.7.0 treats a `sample_size.verdict` of `insufficient` as a failed campaign even when no `target_yield` is declared. The citation stays in the manifest so the row re-grades when a larger campaign is minted. The earlier prose about this row (re-mint of the #288 envelope, evidence-existence reading) is retained in git history and in the "What item 6 means" paragraph above. |
| 7 — Post-layout verification | unmet `no_evidence` | `sim/output-voltage-tc-post-layout/parasitics-snapshot/*/bandgap_core_routed.pex.json` exists but is a `klt extract --parasitics` output (`status: "extracted"`, no `delta[]`/`reference_netlist`/`corner_count`), not the `klt pex` schematic-vs-extracted-delta shape item 7 requires — the *only* evidence kind this item accepts. Citing it would render `wrong_kind` at best; left uncited rather than borrowing a near-miss. A first-party `klt pex` run is the way to close this row. |
| 8 — Characterization report | **met** | Cites `signoff/evidence/characterization.generic.json` — a hand-rolled `kind: generic` envelope (the one item this wrapper is allowed to satisfy) asserting [`design/block-characterization-report.md`](../design/block-characterization-report.md): the aggregated, current, per-ratified-spec-row roll-up across corners, with disclosed FAILs (box-method TC, post-layout output accuracy, startup-time/-ramp, Trim) stated plainly rather than summarized away. The envelope's `provenance.input.content_hash` pins that report; `regenerate.sh` step 1 refreshes it mechanically whenever the report changes. |
| 9 — Testbenches shipped | **met** | Cites `signoff/attest/item-9.evidence.json`, pinning `testbench-inventory.json`: every `sim/` directory with an `experiment.json` or a `run_*.py` entry point, its testbench `.sch` and runner files each hash-pinned, the cold-start command (`python3 sim/bin/corner-run.py sim/<dir>` or the directory's runner), the PDK pin (`sim/pdk.json`, open_pdks `c6d73a35…`) and tool versions. Directories that only hold derived records are listed under `record_only_directories`, not omitted. **The PDK revision recorded here moves when #369/#370 land; whichever lands second regenerates this inventory** (`./signoff/regenerate.sh` — CI fails until it does). `met` attests the testbenches are shipped and pinned, not that every cold start was re-run for this change. |
| 10 — Repo hygiene | **met** | Cites `signoff/attest/item-10.evidence.json`, pinning `repo-hygiene.inventory.json`: the root [`README.md`](../README.md), `LICENSE`, `.github/workflows/ci.yml` (triggers on push and pull_request) and `package.json`, with the commands the workflow runs. |
| 11 — Power delivery (structural) | **met** | Cites `layout/bandgap-core/erc/20261022-072429-9eb67913/erc.20260923-070209-dbd57a9.json` (pinned to the routed GDS's own `content_hash`, `input_verified: true`; produced by klt 0.7.0, pin in `layout/requirements-erc.txt`) **plus** item 4's `lvs.combined.json` (the pinned 0.7.0 report `20261022-070000-e6e4be0`, issue #388), the two-part citation item 11's analog column requires. The **supply half**: `VDD` and `VSS` each resolve to exactly one electrical island, zero `erc.unconnected_net`, zero `erc.supply_short`. The **tie half** (issue #389, clearing the old `supply_spec_disclosed_tool_limitation` / klayout-tools#2339 disclosure): two real `ties[]` entries, `nwell_tie_vdd` (5 wells) and `nwell_tie_vss` (3 wells), scoped per well class with `well_requires_boxes`, both in `erc_coverage.checked`, `skipped` empty, zero `erc.missing_tie`, no `ties_disclosure`. **Disclosed, as the report states it**: because the class of each well rests on the caller's boxes, both ties are listed in `power_delivery.ties_checked_by_well_assertion`; the grader does not verify the box assignment. The falsifiability evidence is the negative control committed in the same record (`erc.negative-control-nwell-swapped.20260923-070209-dbd57a9.json`: the same boxes declared to the opposite net, 8 of 8 wells flagged `erc.missing_tie`). The n-well count is 8 shapes (5 + 3), not the 4 + 2 earlier text under-counted. A ninth nwell shape added to the layout would match neither box list and would not be checked. Structural only: IR drop and EM are outside the item. The LVS half carries the same item-4 disclosures (`RES_HIGH_PO` geometry not compared; `body_verification` unchecked). The older records' reports (klt 0.6.0, `ties_disclosure`) are untouched append-only evidence. |

## Items 1, 2, 9 and 10: artifact-anchored attestations

These four items have no `klt` verb, and until klayout-tools#2718 the grader accepted
any passing envelope for them with no topical check, so this manifest left them
**uncited by deliberate choice** (citing an unrelated passing envelope to turn a row
green is the anti-pattern the manifest exists to prevent). Two things changed upstream:

- **klayout-tools#2718** (in 0.7.0): items 1, 2, 9 and 10 accept only a generic
  envelope that declares `t1_item`, pins the audited artifact by `provenance.input`
  path and `content_hash`, and is cited by a manifest entry pinning the same hash.
  The row is `met` only while the artifact still re-hashes to that value, and the
  citation carries an `artifact_binding` block saying what was bound.
- **klayout-tools#2844** adds `klt signoff --attest {1,9,10} --inventory <file>` to
  derive that envelope's status mechanically. **It is not in 0.7.0** (`klt signoff
  --help` on the pinned wheel has no `--attest`). `scripts/ci/attest_inventories.py`
  therefore writes the generic form itself; switch to the verb once a klayout-tools
  release carries it.

The chain for items 1, 9 and 10 is `manifest pin == envelope pin == sha256(inventory)`,
and every inventory entry `== sha256(file)`. `check_signoff_pins.py` verifies the
first link (offline, `checks` job) and `attest_inventories.py` (default mode, same
job, via `npm run check:signoff-pins`) rebuilds the inventories from the tree and
fails naming the stale one, so **editing any inventoried file, or adding a testbench
directory, fails CI** until `./signoff/regenerate.sh` is run and the result committed.
`scripts/ci/tests/test_attest_inventories.py` holds the negative controls. Item 2 skips
the inventory: its envelope pins the routed GDS, which `check_signoff_pins.py` re-hashes.

## Regenerating the evidence record

```sh
./signoff/regenerate.sh
```

Exit code 3 (`tier: null`, some item `unmet`) is a **successful grader
run** — it is not an error; only exit 1 (manifest/doc/flag parse failure)
is. Gate on the payload, never the exit code (`klayout-tools`
`docs/cli/signoff.md` → "Exit codes and errors").

Regenerate whenever:

- a citation is added, removed, or its pinned artifact changes (the
  committed record and the manifest must tell the same story),
- the klt pin is bumped,
- an inventoried file changes (a schematic, testbench, `sim/pdk.json`, the README, the CI workflow), or
- `design/netlist/` is refreshed after a schematic edit (`scripts/ci/design_netlists.py --write`, needs xschem 3.4.7 and the pinned PDK, then `./signoff/regenerate.sh`).

## Fleet context

The fleet roll-up that consumes this manifest is `2AMLogic/2am#956`
(`klt signoff --fleet`). This repo's `block` value (`sky130-bandgap`) is
that roll-up's identity for this row.
