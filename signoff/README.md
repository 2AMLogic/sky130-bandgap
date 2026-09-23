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
| `signoff-report.json` | The committed `klt signoff --manifest block-manifest.json --tiers-doc design-evidence-tiers.md --format json` output — the graded per-item `met`/`unmet` table with a `reason` on every `unmet` row. Regenerate with `./signoff/regenerate.sh`. |
| `regenerate.sh` | Refreshes the item-8 evidence pin and re-grades the manifest with the pinned released klt, overwriting `signoff-report.json`. |
| (item 11's citation) | Lives outside this directory, under [`layout/bandgap-core/erc/`](../layout/bandgap-core/erc/README.md), because it is produced by a layout flow (`layout/bin/run-erc-supply-flow.sh`) rather than hand-assembled here. That flow re-points this manifest's item-11 entry at each new record it writes (`layout/bin/erc_signoff_citation.py`); re-grading is still `./signoff/regenerate.sh`'s job. Item 11 is the one T1 item whose `evidence` entry is a JSON **array** — the `klt erc` supply run plus item 4's own LVS report. |
| `evidence/characterization.generic.json` | The hand-rolled `kind: generic` envelope (issue #1152's item-8-only wrapper) asserting the aggregated [`design/block-characterization-report.md`](../design/block-characterization-report.md), pinned to that report's own `content_hash`. |
| `design-evidence-tiers.md` | Vendored copy of `klayout-tools`' checklist definition ([`docs/design-evidence-tiers.md`](https://github.com/2AMLogic/klayout-tools/blob/main/docs/design-evidence-tiers.md)), pinned at upstream commit `08825416` ("feat(signoff): carry a mixed-signal manifest's declared partition boundary", 2026-09-22; file `sha256:63eeec72e3d849761cf32dcf091af5728b069b1515e32bb3138e9454303671e5`). Passed to grading via `--tiers-doc` so the checklist doc and the grading `klt` build agree on the same 11-item skeleton even as upstream keeps moving; re-pin when a materially newer doc lands. |

CI (the `signoff` job in `.github/workflows/ci.yml`) re-grades the manifest on
every push/PR and requires byte-identical output to the committed
`signoff-report.json` — so a manifest citation whose underlying artifact has
since changed (the cited DRC report's layout, the characterization report)
fails CI instead of silently rotting. The fix is always the same one-liner:
`./signoff/regenerate.sh`, then commit the refreshed report.

## Grader distribution discipline

Regeneration and CI grade with the **released PyPI registry wheel** of
`klayout-tools==0.6.0` (the current release; it is the first to natively
grade item 11 — `build_t1_item_count: 11` in the committed report — so
`--tiers-doc` here pins the *checklist doc*, not a stand-in for missing
grading rules the way it did for repos still pinned to 0.5.0), never
whatever `klt` is already on the host. Under the same version string a
`uv tool install git+...` snapshot or a full-checkout install can grade
differently (observed live across the fleet for 0.5.0: an 11-item-era
full-repo install under the name "0.5.0" next to the v0.5.0 tag snapshot
whose bundled checklist predates item 11 entirely,
klayout-tools#2216). The released wheel reports the git tag it was built
from (`klt version --format json` → `git_tag: v0.6.0`, `is_release: true`);
`regenerate.sh` and `scripts/ci/check_signoff_freshness.py` both assert that
identity before grading. Keep the version pin in `regenerate.sh`, the CI
job, and `check_signoff_freshness.py` in sync (all three say `0.6.0` today).

## Block kind: `analog`

The manifest's `kind` is **`analog`** — this block is a single bandgap
voltage-reference core with no digital/synthesized partition, so it
satisfies only the Analog column of items 1, 2, 5, 7, and 11. Nothing in
this repo warrants `mixed-signal` today.

## The verdict, row by row

`klt signoff` renders every T1 item either `met` (a cited, freshly-pinned,
passing check backs it) or `unmet` with a `reason`. Today's committed
verdict is **2/11 met** — an honest mechanical reading, not a hand-read: it
is lower than the (stale, pre-item-11, pre-refresh) prose ever claimed,
because several artifacts this repo already has on disk cannot be honestly
cited yet (see below), and a manifest that renders fewer rows `met` than an
old hand-read did is worth more than prose nobody re-verifies.

**A row can get better without getting to `met`, and that is visible here.**
Item 11 moved from `no_evidence` (nothing existed) to
`supply_spec_disclosed_tool_limitation` (the evidence exists, the supply half
is computed and passes, and the one remaining half is blocked by a named,
filed upstream tool gap) when issue #281 landed. The count is unchanged at
2/11; the `reason` is not, and it is the `reason` that says what would close
the row.

| Item | Verdict today | Why — and what would change it |
|---|---|---|
| 1 — Design sources | unmet `no_evidence` | No `klt` verb grades this item — a claim about what the repo *contains*, not a runnable check. Uncited by deliberate choice (citing an unrelated passing envelope to turn the row green is the documented anti-pattern — see `docs/cli/signoff.md`'s "Items 1, 2, 9, and 10" section). Human-audited evidence stands: [`design/bandgap_core.sch`](../design/bandgap_core.sch), `design/error_amp.sch`, `design/startup_injector.sch`, and the reference netlists they derive. |
| 2 — Layout | unmet `no_evidence` | Same structural reason as item 1. Human-audited: [`layout/README.md`](../layout/README.md) and the committed, reproducibly-generated `layout/bandgap-core/reports/*/bandgap_core_routed*.gds`. |
| 3 — DRC clean | **met** | Cites `layout/bandgap-core/reports/20260817-020222-13476b7/drc.json` — `status: clean`, `violation_count: 0`, `provenance.input.content_hash` pinning the committed `bandgap_core_routed.gds` byte-for-byte (independently re-verified: `sha256sum` of that GDS matches the pinned hash). Coverage disclosure, read from the report rather than assumed (this envelope predates the `deck_scope` field, so only two of the three item-3 disclosure fields are available): `rules_skipped` is empty, but `coverage.layers_in_stream_without_rules` is **not** — 8 layers this stream draws (`64/20`, `65/44`, `66/13`, `68/5`, `82/44`, `83/20`, `86/20`, `94/20`) carry no rule in the curated sky130 deck this run used. A "clean" from a deck with disclosed holes is disclosed here, not hidden. |
| 4 — LVS clean | unmet `no_evidence` | The freshest committed LVS report (`layout/bandgap-core/reports/20260817-020222-13476b7/lvs.combined.json`, `status: match`, `mismatch_count: 0` — the evidence the root README's "layout-complete" claim currently cites) was produced under `klt` 0.2.0, which predates klayout-tools#1969 (the release that adds `provenance.input.content_hash` to `klt lvs` output): its `provenance.input` is `null`, so **no content_hash pin can be verified against it**, and this manifest's own discipline (every citation pins a hash that matches the committed artifact) refuses to cite it uncredentialed. **Diagnostic finding, not yet actioned**: re-running the same committed `lvs.combined.request.json` under the currently-installed `klt` 0.5.0/0.6.0 (same request, same committed netlists) reports `status: mismatch`, `mismatch_count: 12` — a regression from the committed `0` this repo's README currently states, isolated to a `klt`-version difference (the curated sky130 DRC deck's own `content_hash` also differs between the two builds, confirming the toolchain moved under this evidence). This needs its own investigation before item 4 can be honestly re-cited; tracked in #288, filed alongside this manifest rather than silently reflected here as `met`. |
| 5 — Full corner verification vs a ratified spec | unmet `no_evidence` | This repo's `sim/*/records/*.json` are custom append-year harness records (see [`sim/README.md`](../sim/README.md)), not `klt sim`-shaped envelopes — no native evidence exists for `klt signoff` to grade yet. The human-audited evidence is real and extensive (`design/block-characterization-report.md` rolls up all seven ratified spec rows across PVT corners), but citing it here without a `klt sim`/`klt yield`/`klt pex` envelope would be the documented anti-pattern. Would need a minted `klt sim`-shaped envelope (see e.g. `2AMLogic/gf180-sram`'s `sim/signoff-sim-envelope.json` for the pattern) or a first-party `klt sim` run. |
| 6 — Statistical claims carry Monte Carlo evidence | unmet `no_evidence` | A real `klt yield` envelope exists (`sim/monte-carlo-untrimmed/records/20260817-121131-d7d85b6-klt-yield.json`, `status: reported`) but its own `samples` field records an **absolute, machine-local path** (`/Users/rwalters/GitHub/sky130-bandgap/.claude/worktrees/agent-.../...-klt-yield-input.json`) rather than a repo-relative one — exactly the provenance-hygiene hazard `design-evidence-tiers.md`'s "Provenance hygiene in evidence records" section warns about. `klt signoff` cannot resolve that path on any other machine, so the citation cannot be verified fresh here even though the sibling file it should have named is committed at a stable repo-relative location (`sim/monte-carlo-untrimmed/records/20260817-121131-d7d85b6-klt-yield-input.json`). Evidence records are append-only by construction (see that same doc section) so this one is not rewritten; a **re-minted** yield report with a repo-relative `samples` path is the fix, tracked alongside item 4 in #288. |
| 7 — Post-layout verification | unmet `no_evidence` | `sim/output-voltage-tc-post-layout/parasitics-snapshot/*/bandgap_core_routed.pex.json` exists but is a `klt extract --parasitics` output (`status: "extracted"`, no `delta[]`/`reference_netlist`/`corner_count`), not the `klt pex` schematic-vs-extracted-delta shape item 7 requires — the *only* evidence kind this item accepts. Citing it would render `wrong_kind` at best; left uncited rather than borrowing a near-miss. A first-party `klt pex` run is the way to close this row. |
| 8 — Characterization report | **met** | Cites `signoff/evidence/characterization.generic.json` — a hand-rolled `kind: generic` envelope (the one item this wrapper is allowed to satisfy) asserting [`design/block-characterization-report.md`](../design/block-characterization-report.md): the aggregated, current, per-ratified-spec-row roll-up across corners, with disclosed FAILs (box-method TC, post-layout output accuracy, startup-time/-ramp, Trim) stated plainly rather than summarized away. The envelope's `provenance.input.content_hash` pins that report; `regenerate.sh` step 1 refreshes it mechanically whenever the report changes. |
| 9 — Testbenches shipped | unmet `no_evidence` | Same structural reason as item 1. Human-audited: [`sim/README.md`](../sim/README.md) inventories the committed testbenches with cold-start invocation and pinned PDK revision. |
| 10 — Repo hygiene | unmet `no_evidence` | Same structural reason as item 1. Human-audited: the root [`README.md`](../README.md), `LICENSE`, and `.github/workflows/ci.yml` (runs on every push/PR). |
| 11 — Power delivery (structural) | unmet `supply_spec_disclosed_tool_limitation` | **No longer `no_evidence`** — issue #281 landed the `klt erc` supply spec and reports, and this row now cites them: `layout/bandgap-core/erc/<record-id>/erc.20260817-020222-13476b7.json` (pinned to the routed GDS's own `content_hash`) **plus** item 4's `lvs.combined.json`, the two-part citation item 11's analog column requires (`docs/cli/signoff.md`, "Power delivery (structural)"). The **supply half is met and computed**: `VDD` and `VSS` each resolve to exactly one electrical island, zero `erc.unconnected_net`, zero `erc.supply_short`, both in `erc_coverage.checked`; and the cited LVS report's `net_correspondence` pairs both supplies to reference-side nets from a SPICE reference. What keeps the row `unmet` is the **missing-tie half**: the spec declares an empty `ties[]` with a `ties_disclosure` of kind `tool_limitation`, so `erc.missing_tie` is *not computed* — an absence of evidence, not evidence of absence. The blocker is [klayout-tools#2339](https://github.com/2AMLogic/klayout-tools/issues/2339) (filed from this repo): `ties[].well_layer` checks every merged shape on one layer against one declared net, and this block's single `nwell` layer holds two differently-biased well classes (4 PMOS body wells at `VDD`, 2 vertical-PNP base tubs at `VSS`), so either declaration reports the other class as a false `erc.missing_tie`. **This is not klayout-tools#2169**, which is fixed on the pinned 0.6.0 build and re-confirmed not to reproduce here. Both halves of the reproduction and the standing-in well-tie evidence are in [`layout/bandgap-core/erc/README.md`](../layout/bandgap-core/erc/README.md). Closed by a `klt` build with a well-side tie selector, not by redrawing the layout. |

Items 1, 2, 9, and 10 are uncited by deliberate choice: the grader accepts
any passing envelope for them without checking topical relevance (there is
no verb to bind them to), and citing an envelope that does not actually
support the claim — to make rows go green — is the failure mode this
manifest exists to prevent (`docs/cli/signoff.md`, "Items 1, 2, 9, and 10:
`klt signoff` cannot check topical relevance"). Their evidence remains the
committed, human-auditable artifacts named above.

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
- the klt pin is bumped, or
- the vendored checklist doc is re-pinned to a newer upstream revision.

## Fleet context

The fleet roll-up that consumes this manifest is `2AMLogic/2am#956`
(`klt signoff --fleet`). This repo's `block` value (`sky130-bandgap`) is
that roll-up's identity for this row.
