# DR-014: `error_amp` stays in-tree — sky130-opamp declines the 3.3 V / 5 V-gate flavor

- **Status**: proposed (ledger disposition, not a spec change; no spec row is
  relaxed and no design or `sim/` evidence is touched).
- **Date**: 2026-10-08
- **Decided by**: Loom Builder agent (issue #337), proposing per CLAUDE.md.
- **Closes out**: the deferred steps 2-4 of
  [#286](https://github.com/2AMLogic/sky130-bandgap/issues/286) (PR #294 landed
  only the `evaluate` ledger entry).

## Context

`reuse.lock.json` recorded the in-tree `error_amp` block against sibling
`2AMLogic/sky130-opamp` as `status: evaluate`. The sibling has since answered:
its issue #36 closed via PR #37, recording
[DR-005](https://github.com/2AMLogic/sky130-opamp/blob/e82e1e6249227679c0d4183fb85c895361812222/spec/decision-records/DR-005-io-flavor-not-served.md)
(pinned at sibling `main` = `e82e1e6249227679c0d4183fb85c895361812222`,
re-checked 2026-10-08): the sibling "does not serve a 3.3 V-rail / 5 V-gate
amplifier position", and the 3.3 V I/O-device flavor stays named-not-opened.
Caveat: that record's Status line still reads `proposed`. By its own text this
is the two-key wart (merging the PR does not rewrite the line); the merged
copy at the pinned commit is the standing answer, and is cited by commit for
that reason.

This block's need was verified against local files, not assumed:

- `design/error_amp.sch` builds the whole amplifier on
  `sky130_fd_pr__{n,p}fet_g5v0d10v5` (header: "per DR-001's 3.3 V-only
  scope"), with AOUT swinging to a PMOS-gate level near VDD and a thick-oxide
  PMOS MIM-substitute compensation capacitor to VDD.
- `design/error-amp-offset-budget.md` derives the offset budget from the PDK's
  `g5v0d10v5` mismatch coefficients (A_VT 8.2 / 12.0 mV*um).

That is exactly the position DR-005 declines (1.8 V `_01v8` core devices only).

## Decision

1. `error_amp` is **kept in-tree**; the sibling does not serve this block's
   3.3 V rail / 5 V-gate amplifier position, by standing decision.
2. `reuse.lock.json` moves the `error_amp` entry from `evaluate` to `kept`,
   with `decision` pointing at this record.
3. No adoption of the sibling amplifier is proposed or implied.

## Alternatives considered

- **Leave the entry at `evaluate`** — misstates a settled question and leaves
  no record here saying why the block stays in-tree.
- **Adopt the sibling amplifier (`adopting`)** — not possible: it is built on
  1.8 V core devices and cannot operate at this block's rail.
- **Ask the sibling to open the 3.3 V flavor** — DR-005 prices that as an
  epic-sized effort and declines it; not warranted by this block's needs.

## Spec lines affected

None. No `README.md` target-spec row and no `spec/` file is changed.

## Consequences

- The ledger is accurate and passes the reuse-check validator's `kept` rule
  (requires an existing decision record).
- Reversible: if sky130-opamp later supersedes its DR-005 and opens the 3.3 V
  flavor, a new DR here supersedes this one and the entry can move to
  `evaluate`/`adopting` again.
- The sibling's DR-005 Status wart is a standing weakness of the citation;
  the pinned commit makes any later drift detectable.
