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
| `regenerate.sh` | Refreshes the item-8 evidence pin, re-grades the manifest with the pinned released klt (overwriting `signoff-report.json`), and re-verifies every pin against the artifact it describes. |
| `pinned-inputs.json` | Per pinned citation, **where in this repo the artifact that pin describes actually lives**. Neither the manifest nor the evidence envelopes hold that: a `content_hash` is the hash of the artifact the envelope *describes*, and the envelope's own path field may be absolute and machine-local (item 3's is). `scripts/ci/check_signoff_pins.py` needs it to re-hash the artifact — see "What `klt signoff` cannot check" below. |
| (item 6's citation) | Lives outside this directory, under [`sim/monte-carlo-untrimmed/records/`](../sim/monte-carlo-untrimmed/records/), because it is produced by a simulation harness (`sim/monte-carlo-untrimmed/emit_klt_yield.py`) rather than hand-assembled here. Its pinned `content_hash` is the hash of the **sample-set document** the report names in its own `samples` field, not of the report file — that is the input hash `klt signoff` computes for a `klt yield` envelope, which carries no `provenance` block of its own, so `pinned-inputs.json` names that same sample-set document. |
| (item 11's citation) | Lives outside this directory, under [`layout/bandgap-core/erc/`](../layout/bandgap-core/erc/README.md), because it is produced by a layout flow (`layout/bin/run-erc-supply-flow.sh`) rather than hand-assembled here. That flow re-points this manifest's item-11 entry at each new record it writes (`layout/bin/erc_signoff_citation.py`); re-grading is still `./signoff/regenerate.sh`'s job. Item 11 is the one T1 item whose `evidence` entry is a JSON **array** — the `klt erc` supply run plus item 4's own LVS report. |
| `evidence/characterization.generic.json` | The hand-rolled `kind: generic` envelope (issue #1152's item-8-only wrapper) asserting the aggregated [`design/block-characterization-report.md`](../design/block-characterization-report.md), pinned to that report's own `content_hash`. |
| `design-evidence-tiers.md` | Vendored copy of `klayout-tools`' checklist definition ([`docs/design-evidence-tiers.md`](https://github.com/2AMLogic/klayout-tools/blob/main/docs/design-evidence-tiers.md)), pinned at upstream commit `08825416` ("feat(signoff): carry a mixed-signal manifest's declared partition boundary", 2026-09-22; file `sha256:63eeec72e3d849761cf32dcf091af5728b069b1515e32bb3138e9454303671e5`). Passed to grading via `--tiers-doc` so the checklist doc and the grading `klt` build agree on the same 11-item skeleton even as upstream keeps moving; re-pin when a materially newer doc lands. |

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

`check_signoff_pins.py` closes that gap by asserting a three-way agreement per
pin: **manifest pin == `sha256` of the committed artifact == the hash the
cited envelope recorded**. `pinned-inputs.json` supplies the missing piece —
the artifact's repo-relative path — and must stay 1:1 with the manifest's
pinned citations: a new pinned citation with no entry there fails the check,
as does an entry for a citation that no longer exists. That is deliberate;
adding a citation should require saying what its hash describes.

Item 11's second citation (`lvs.combined.json`) is deliberately **unpinned**
(see `layout/bin/erc_signoff_citation.py` for why), so it has no entry and the
check reports it as skipped rather than silently ignoring it.

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
verdict is **3/11 met** — an honest mechanical reading, not a hand-read: it
is lower than the (stale, pre-item-11, pre-refresh) prose ever claimed,
because several artifacts this repo already has on disk cannot be honestly
cited yet (see below), and a manifest that renders fewer rows `met` than an
old hand-read did is worth more than prose nobody re-verifies.

**A row can get better without getting to `met`, and that is visible here.**
Item 11 moved from `no_evidence` (nothing existed) to
`supply_spec_disclosed_tool_limitation` (the evidence exists, the supply half
is computed and passes, and the one remaining half is blocked by a named,
filed upstream tool gap) when issue #281 landed. That move did not change the
count; the `reason` is what changed, and it is the `reason` that says what
would close the row.

**And a row can get *worse* without the artifact changing, which is why item
4 is still `unmet`.** Issue #288 investigated the `mismatch_count` 0 -> 12
diagnostic recorded in the item-4 row below and found it is not a
version-to-version regression at all: on the newer `klt` builds the verdict is
*nondeterministic* (762/1000 clean, 238/1000 a false `mismatch`), and the
committed `0` reproduces 1000/1000 on the build `layout/requirements.txt`
pins. The measurement is `layout/bandgap-core/combine-determinism/`; the
upstream tool gap is klayout-tools#2374; the full disposition is
`layout/matching-plan.md` Section 7ff.

| Item | Verdict today | Why — and what would change it |
|---|---|---|
| 1 — Design sources | unmet `no_evidence` | No `klt` verb grades this item — a claim about what the repo *contains*, not a runnable check. Uncited by deliberate choice (citing an unrelated passing envelope to turn the row green is the documented anti-pattern — see `docs/cli/signoff.md`'s "Items 1, 2, 9, and 10" section). Human-audited evidence stands: [`design/bandgap_core.sch`](../design/bandgap_core.sch), `design/error_amp.sch`, `design/startup_injector.sch`, and the reference netlists they derive. |
| 2 — Layout | unmet `no_evidence` | Same structural reason as item 1. Human-audited: [`layout/README.md`](../layout/README.md) and the committed, reproducibly-generated `layout/bandgap-core/reports/*/bandgap_core_routed*.gds`. |
| 3 — DRC clean | **met** | Cites `layout/bandgap-core/reports/20260817-020222-13476b7/drc.json` — `status: clean`, `violation_count: 0`, `provenance.input.content_hash` pinning the committed `bandgap_core_routed.gds` byte-for-byte (independently re-verified: `sha256sum` of that GDS matches the pinned hash). Coverage disclosure, read from the report rather than assumed (this envelope predates the `deck_scope` field, so only two of the three item-3 disclosure fields are available): `rules_skipped` is empty, but `coverage.layers_in_stream_without_rules` is **not** — 8 layers this stream draws (`64/20`, `65/44`, `66/13`, `68/5`, `82/44`, `83/20`, `86/20`, `94/20`) carry no rule in the curated sky130 deck this run used. A "clean" from a deck with disclosed holes is disclosed here, not hidden. |
| 4 — LVS clean | unmet `no_evidence` | The freshest committed LVS report (`layout/bandgap-core/reports/20260817-020222-13476b7/lvs.combined.json`, `status: match`, `mismatch_count: 0` — the evidence the root README's "layout-complete" claim currently cites) was produced under `klt` 0.2.0, which predates klayout-tools#1969 (the release that adds `provenance.input.content_hash` to `klt lvs` output): its `provenance.input` is `null`, so **no content_hash pin can be verified against it**, and this manifest's own discipline (every citation pins a hash that matches the committed artifact) refuses to cite it uncredentialed. **The `mismatch_count: 12` diagnostic this row used to carry is now investigated and dispositioned (#288), and it did *not* invalidate the committed `0`.** Re-running the same committed `lvs.combined.request.json` under the currently-installed `klt` (same request, same committed netlists) reports `mismatch_count: 12` on only **238 of 1000** repetitions and `0` on the other **762** — the *same build, same inputs, same process*. Under the build `layout/requirements.txt` pins it is `0` on **1000 of 1000**, and under the newer build with `options.combine_devices_max_attempts: 1` it is `0` on **1000 of 1000** again. So this is a nondeterministic false `mismatch` introduced by klayout-tools#1185/#1186's `Netlist.dup()`-based combine retry (bisected to `66f73d0c`), not a real defect and not an accounting re-baseline: filed upstream as [klayout-tools#2374](https://github.com/2AMLogic/klayout-tools/issues/2374), measured by `layout/bin/measure_combine_devices_determinism.py` into `layout/bandgap-core/combine-determinism/20260923-062919-1e38c62/`, dispositioned in `layout/matching-plan.md` Section 7ff. **This makes the row harder to close, not easier**: the only `klt` builds that populate `provenance.input.content_hash` (klayout-tools#1969, what this row needs) are exactly the builds whose combine step is intermittently wrong, so minting a fresh hash-pinnable LVS report today would pin a verdict that does not reproduce. Item 4 closes on klayout-tools#2374, not on a re-run. |
| 5 — Full corner verification vs a ratified spec | unmet `no_evidence` | This repo's `sim/*/records/*.json` are custom append-year harness records (see [`sim/README.md`](../sim/README.md)), not `klt sim`-shaped envelopes — no native evidence exists for `klt signoff` to grade yet. The human-audited evidence is real and extensive (`design/block-characterization-report.md` rolls up all seven ratified spec rows across PVT corners), but citing it here without a `klt sim`/`klt yield`/`klt pex` envelope would be the documented anti-pattern. Would need a minted `klt sim`-shaped envelope (see e.g. `2AMLogic/gf180-sram`'s `sim/signoff-sim-envelope.json` for the pattern) or a first-party `klt sim` run. |
| 6 — Statistical claims carry Monte Carlo evidence | **met** | Cites `sim/monte-carlo-untrimmed/records/20260923-062524-1e38c62-klt-yield.json` — `status: reported` (no measurement declares a `target_yield`, so nothing could fail), three `vout` measurements over 838 converged mismatch samples at −40/27/125 °C, each with its Clopper-Pearson interval, Cp/Cpk, sigma-to-spec and sample-size verdict against DR-005's own ±2 % window. The pinned `content_hash` is the hash of the sample-set document the envelope names in its `samples` field (`klt yield` carries no `provenance` block of its own, so `klt signoff` hashes that input directly). **This is a re-mint, and the envelope it supersedes is still committed beside it.** The earlier `20260817-121131-d7d85b6-klt-yield.json` recorded an **absolute, machine-local** `samples` path (`/Users/…/.claude/worktrees/agent-…`), because `klt yield` echoes back the path it is invoked with and `emit_klt_yield.py` invoked it with an absolute one — the exact provenance-hygiene hazard `design-evidence-tiers.md`'s "Provenance hygiene in evidence records" section warns about, and unresolvable (so uncitable) on any other machine. Issue #288 fixed the harness to run `klt yield` from the repo root with a repo-relative path; `records/*` being append-only, the old envelope was **not** rewritten — a new one was minted from the *same* committed corner logs, with a `…-klt-yield.md` note recording what it supersedes and why. The statistics are byte-identical to the superseded envelope's: only the path changed. |
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
